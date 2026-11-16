import asyncio
import time

import pytest
from sqlalchemy import select

from app.database import Database
from app.llm import ProviderError
from app.models import Agent, Artifact, Budget, Inference, Job
from app.runtime import Runtime
from app.schemas import AgentResult, AgentTurn, Evidence, Finding, SupervisorDecision, ToolCall
from app.store import Rejected, Store
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider


def result():
    return AgentResult(
        summary="Division has no zero-divisor guard.",
        findings=[
            Finding(
                title="Zero divisor is unhandled",
                description="A zero divisor raises ZeroDivisionError at the division.",
                severity="medium",
                evidence=[Evidence(path="app.py", start_line=2, end_line=2, quote="return a / b")],
            )
        ],
    )


def decision(specs):
    return SupervisorDecision(
        action="SPAWN_AGENTS",
        reason="Independent evidence review is required",
        expected_benefit="Inspect the division implementation",
        agents=specs,
    )


async def drain(store, runtime, max_turns=30):
    for _ in range(max_turns):
        claim = await store.claim("test-worker")
        if not claim:
            return
        await runtime.execute(claim)
    raise AssertionError("Execution did not settle within the bounded test turns")


@pytest.mark.asyncio
async def test_llm_decomposition_tools_synthesis_and_persistence(store, spec):
    job_id = await new_job(store)
    provider = ScriptedProvider(
        decisions=[
            decision([spec]),
            SupervisorDecision(
                action="SYNTHESIZE_RESULTS",
                reason="Source evidence is sufficient",
                expected_benefit="Deliver verified source observations",
                report=result(),
            ),
        ],
        turns=[
            AgentTurn(call=ToolCall(name="read_repository_file", arguments={"path": "app.py"})),
            AgentTurn(result=result()),
        ],
    )
    await drain(store, Runtime(store, provider))
    snapshot = await store.snapshot(job_id)
    assert snapshot["status"] == "COMPLETED"
    assert snapshot["agents"][0]["steps"] == 2
    assert snapshot["metrics"]["tokens"] == 750
    db2 = Database(store.settings.database_url)
    try:
        reopened = await Store(db2, store.settings).snapshot(job_id)
        assert reopened["report"] == snapshot["report"]
        assert reopened["agents"] == snapshot["agents"]
    finally:
        await db2.close()
    assert len(provider.calls) == 5
    assert any(e["type"] == "tool.completed" for e in await store.events(job_id))


@pytest.mark.asyncio
async def test_recursive_delegation_releases_slot_and_aggregates(store, spec):
    store.settings.max_concurrent_agents = 1
    job_id = await new_job(store)
    parent_id = await add_agent(store, job_id, spec)
    child = spec.model_copy(
        update={
            "task_key": "child",
            "objective": "Independently inspect the zero divisor",
            "role": "Verification specialist",
        }
    )
    from app.schemas import SubagentRequest

    request = SubagentRequest(
        reason="Independent verification of arithmetic is needed",
        expected_benefit="Cross-check source evidence",
        agents=[child],
    )
    provider = ScriptedProvider(
        turns=[
            AgentTurn(call=ToolCall(name="request_subagents", arguments=request.model_dump())),
            AgentTurn(result=result()),
            AgentTurn(result=result()),
        ]
    )
    runtime = Runtime(store, provider)
    claim = await store.claim("worker-one")
    assert claim.agent_id == parent_id
    await runtime.execute(claim)
    snapshot = await store.snapshot(job_id)
    parent, child_view = snapshot["agents"]
    assert parent["status"] == "WAITING_FOR_CHILDREN"
    assert child_view["parent_agent_id"] == parent_id
    assert child_view["depth"] == 1
    claim = await store.claim("worker-two")
    assert claim.agent_id == child_view["id"]  # Parent does not hold the only slot.
    await runtime.execute(claim)
    claim = await store.claim("worker-one")
    assert claim.agent_id == parent_id
    await runtime.execute(claim)
    assert all(a["status"] == "COMPLETED" for a in (await store.snapshot(job_id))["agents"])
    assert (await store.snapshot(job_id))["metrics"]["max_concurrency"] == 1


@pytest.mark.asyncio
async def test_dedup_depth_permissions_and_batch_atomicity(store, spec):
    job_id = await new_job(store)
    parent_id = await add_agent(store, job_id, spec)
    with pytest.raises(Rejected, match="Duplicate task objective"):
        await add_agent(
            store, job_id, spec.model_copy(update={"task_key": "different", "role": "Other role"})
        )
    with pytest.raises(Rejected, match="unauthorized tool"):
        await add_agent(
            store,
            job_id,
            spec.model_copy(
                update={"task_key": "bad", "objective": "Execute unsafe commands", "allowed_tools": ["shell"]}
            ),
        )
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        budget.max_depth = 0
    with pytest.raises(Rejected, match="recursion depth"):
        async with store.db.locked(job_id) as (session, job):
            parent = await session.get(Agent, parent_id)
            await store.spawn(
                session,
                job,
                [
                    spec.model_copy(
                        update={"task_key": "child", "objective": "Investigate another independent concern"}
                    )
                ],
                "Independent work needed",
                "Separate analysis",
                parent,
            )
    assert len((await store.snapshot(job_id))["agents"]) == 1


@pytest.mark.asyncio
async def test_dependencies_cycle_validation_and_failure_propagation(store, spec):
    job_id = await new_job(store)
    first = spec.model_copy(update={"task_key": "first"})
    second = spec.model_copy(
        update={"task_key": "second", "objective": "Verify first result", "depends_on": ["first"]}
    )
    async with store.db.locked(job_id) as (session, job):
        ids = await store.spawn(
            session, job, [first, second], "Dependent verification needed", "Verify evidence"
        )
    claim = await store.claim("worker")
    assert claim.agent_id == ids[0]
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, ids[0])
        store.transition(session, job, agent, "FAILED")
    claim = await store.claim("worker")
    assert claim.agent_id is None  # Dependency failed, so supervisor must replan.
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][1]["status"] == "FAILED"
    assert snapshot["agents"][1]["error"]["code"] == "dependency_failed"


@pytest.mark.asyncio
async def test_dependency_cycles_rejected(store, spec):
    job_id = await new_job(store)
    a = spec.model_copy(update={"depends_on": ["second"]})
    b = spec.model_copy(
        update={"task_key": "second", "objective": "Distinct investigation", "depends_on": [a.task_key]}
    )
    with pytest.raises(Rejected, match="cycle"):
        async with store.db.locked(job_id) as (session, job):
            await store.spawn(session, job, [a, b], "Split the review", "Independent evidence")
    assert (await store.snapshot(job_id))["metrics"]["total_agents"] == 0


@pytest.mark.asyncio
async def test_atomic_concurrency_and_agent_cap(store, spec):
    store.settings.max_total_agents = 2
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    await add_agent(
        store, job_id, spec.model_copy(update={"task_key": "second", "objective": "Distinct check"})
    )
    with pytest.raises(Rejected, match="budget exhausted"):
        await add_agent(
            store, job_id, spec.model_copy(update={"task_key": "third", "objective": "Another check"})
        )
    claims = await asyncio.gather(*(store.claim(f"worker-{i}") for i in range(8)))
    assert len([c for c in claims if c]) == 2
    assert len({c.agent_id for c in claims if c}) == 2


@pytest.mark.asyncio
async def test_token_and_cost_reservations_are_atomic(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    claim = await store.claim("worker")
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        budget.max_tokens = 1000
    with pytest.raises(Rejected, match="token budget"):
        await store.reserve(claim, "test-model", 1000, 1000)
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        budget.max_tokens, budget.max_cost_usd = 100000, 0.0001
    with pytest.raises(Rejected, match="cost budget"):
        await store.reserve(claim, "test-model", 1000, 1000)


@pytest.mark.asyncio
async def test_crash_recovery_and_unknown_billing(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    claim = await store.claim("crashed-worker")
    reservation = await store.reserve(claim, "test-model", 1000, 1000)
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, agent_id)
        agent.lease_until = time.time() - 1
        inference = await session.get(Inference, reservation)
        inference.created_at = time.time() - 100
    new_claim = await store.claim("replacement")
    assert new_claim.agent_id == agent_id
    assert new_claim.worker_id != claim.worker_id
    snapshot = await store.snapshot(job_id)
    assert snapshot["metrics"]["recoveries"] == 1
    assert snapshot["metrics"]["reserved_tokens"] == 0
    assert snapshot["metrics"]["tokens"] == 2000
    async with store.db.sessions() as session:
        job = await session.get(Job, job_id)
        agent = await session.get(Agent, agent_id)
        assert not store.valid_claim(job, agent, claim)


@pytest.mark.asyncio
async def test_cancellation_prevents_stale_outputs(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    claim = await store.claim("worker")
    await store.cancel(job_id, "default")
    runtime = Runtime(store, ScriptedProvider(turns=[AgentTurn(result=result())]))
    await runtime.execute(claim)
    snapshot = await store.snapshot(job_id)
    assert snapshot["status"] == "CANCELLED"
    assert snapshot["agents"][0]["status"] == "CANCELLED"
    assert snapshot["agents"][0]["result"] is None


@pytest.mark.asyncio
async def test_retry_backoff_and_clear_failure(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    runtime = Runtime(store, ScriptedProvider(turns=[ProviderError("RateLimitError", "Rate limited", True)]))
    await runtime.execute(await store.claim("worker"))
    async with store.db.sessions() as session:
        agent = await session.get(Agent, agent_id)
        assert agent.status == "QUEUED"
        assert agent.failures == 1 and agent.next_attempt > time.time()
    assert await store.claim("worker") is None


@pytest.mark.asyncio
async def test_invalid_evidence_never_becomes_completed_output(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    invalid = result()
    invalid.findings[0].evidence[0].quote = "this does not exist"
    runtime = Runtime(store, ScriptedProvider(turns=[AgentTurn(result=invalid)]))
    await runtime.execute(await store.claim("worker"))
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][0]["status"] == "QUEUED"
    assert snapshot["agents"][0]["result"] is None
    async with store.db.sessions() as session:
        assert not list(
            await session.scalars(
                select(Artifact).where(Artifact.agent_id == agent_id, Artifact.kind == "result")
            )
        )


@pytest.mark.asyncio
async def test_single_and_fixed_forbid_recursive_delegation(store, spec, request_body):
    for mode in ["single", "fixed"]:
        body = request_body.model_copy(update={"mode": mode, "fixed_agent_count": 1})
        job_id = await new_job(store, body)
        with pytest.raises(Rejected, match="Delegation tool"):
            await add_agent(store, job_id, spec)
        permitted = spec.model_copy(update={"allowed_tools": ["read_repository_file"]})
        await add_agent(store, job_id, permitted)
        with pytest.raises(Rejected):
            await add_agent(
                store,
                job_id,
                permitted.model_copy(update={"task_key": "extra", "objective": "Additional check"}),
            )


@pytest.mark.asyncio
async def test_idempotency_key(store, request_body):
    one = await store.create_job(request_body, "default", "unique-request")
    assert await store.create_job(request_body, "default", "unique-request") == one
    with pytest.raises(Rejected, match="another request"):
        await store.create_job(
            request_body.model_copy(update={"objective": "A different objective"}),
            "default",
            "unique-request",
        )
