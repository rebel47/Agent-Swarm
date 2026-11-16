import asyncio
import time

import pytest

from app.llm import ProviderError
from app.models import Agent
from app.runtime import Runtime, AGENT_PROMPT
from app.schemas import AgentTurn, ToolCall
from app.store import Rejected
from app.worker import Worker
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider


@pytest.mark.asyncio
async def test_wait_graph_cycle_through_existing_prerequisite_is_rejected(store, spec):
    job_id = await new_job(store)
    parent_id = await add_agent(store, job_id, spec)
    dependent = spec.model_copy(
        update={
            "task_key": "dependent",
            "objective": "Review output after the parent",
            "depends_on": [spec.task_key],
        }
    )
    await add_agent(store, job_id, dependent)
    child = spec.model_copy(
        update={
            "task_key": "child",
            "objective": "Review existing dependent result",
            "depends_on": ["dependent"],
        }
    )
    with pytest.raises(Rejected, match="cycle"):
        async with store.db.locked(job_id) as (session, job):
            parent = await session.get(Agent, parent_id)
            await store.spawn(
                session, job, [child], "Separate verification is needed", "More evidence", parent
            )


@pytest.mark.asyncio
async def test_child_permission_escalation_is_rejected(store, spec):
    job_id = await new_job(store)
    parent_id = await add_agent(
        store,
        job_id,
        spec.model_copy(update={"allowed_tools": ["request_subagents", "read_repository_file"]}),
    )
    with pytest.raises(Rejected, match="escalate"):
        async with store.db.locked(job_id) as (session, job):
            parent = await session.get(Agent, parent_id)
            await store.spawn(
                session,
                job,
                [
                    spec.model_copy(
                        update={
                            "task_key": "child",
                            "objective": "Independent verification",
                            "allowed_tools": ["search_repository"],
                        }
                    )
                ],
                "Need independent review",
                "Separate evidence",
                parent,
            )


@pytest.mark.asyncio
async def test_prompt_injection_cannot_grant_shell_capability(store, spec):
    assert "UNTRUSTED DATA" in AGENT_PROMPT
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    runtime = Runtime(
        store,
        ScriptedProvider(
            turns=[AgentTurn(call=ToolCall(name="shell", arguments={"command": "echo unauthorized"}))]
        ),
    )
    await runtime.execute(await store.claim("worker"))
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][0]["status"] == "QUEUED"
    async with store.db.sessions() as session:
        from sqlalchemy import select
        from app.models import ToolExecution

        tool = await session.scalar(select(ToolExecution).where(ToolExecution.job_id == job_id))
        assert tool.output["code"] == "tool_rejected"


@pytest.mark.asyncio
async def test_100_logical_agents_are_durable_and_bounded(store, spec):
    store.settings.max_total_agents = 100
    job_id = await new_job(store)
    specs = [
        spec.model_copy(update={"task_key": str(i), "objective": f"Investigate independent concern {i}"})
        for i in range(100)
    ]
    async with store.db.locked(job_id) as (session, job):
        await store.spawn(
            session, job, specs, "Independent components require review", "Parallel evidence collection"
        )
    snapshot = await store.snapshot(job_id)
    assert len(snapshot["agents"]) == 100
    claims = await asyncio.gather(*(store.claim(str(i)) for i in range(10)))
    assert sum(claim is not None for claim in claims) == store.settings.max_concurrent_agents
    await store.cancel(job_id, "default")


@pytest.mark.asyncio
async def test_agent_step_limit_and_job_timeout(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec.model_copy(update={"max_steps": 1}))
    runtime = Runtime(
        store,
        ScriptedProvider(
            turns=[AgentTurn(call=ToolCall(name="read_repository_file", arguments={"path": "app.py"}))]
        ),
    )
    await runtime.execute(await store.claim("worker"))
    claim = await store.claim("worker")
    assert claim.agent_id is None
    assert (await store.snapshot(job_id))["agents"][0]["status"] == "TIMED_OUT"
    await store.cancel(job_id, "default")
    other = await new_job(store)
    async with store.db.locked(other) as (session, job):
        job.created_at = time.time() - store.settings.max_job_seconds - 1
    assert await store.claim("worker") is None
    assert (await store.snapshot(other))["status"] == "TIMED_OUT"


@pytest.mark.asyncio
async def test_graceful_release_preserves_queued_work(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    claim = await store.claim("worker")
    worker = Worker(store, Runtime(store, ScriptedProvider()))
    await worker.release(claim)
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][0]["status"] == "QUEUED"
    replacement = await store.claim("replacement")
    assert replacement.agent_id == agent_id
    assert replacement.worker_id != claim.worker_id


@pytest.mark.asyncio
async def test_global_concurrency_across_jobs(store, spec):
    for _ in range(3):
        job_id = await new_job(store)
        await add_agent(store, job_id, spec)
    claims = await asyncio.gather(*(store.claim(str(i)) for i in range(10)))
    assert sum(claim is not None for claim in claims) == 2


@pytest.mark.asyncio
async def test_provider_timeout_uses_conservative_accounting(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    runtime = Runtime(
        store, ScriptedProvider(turns=[ProviderError("TimeoutError", "Request timed out", True)])
    )
    await runtime.execute(await store.claim("worker"))
    metrics = (await store.snapshot(job_id))["metrics"]
    assert metrics["tokens"] > 0 and metrics["estimated_cost_usd"] > 0
    assert metrics["reserved_tokens"] == 0


@pytest.mark.asyncio
async def test_supervisor_can_cancel_unnecessary_branch_while_other_work_runs(store, spec):
    from app.schemas import SupervisorDecision

    job_id = await new_job(store)
    first_id = await add_agent(store, job_id, spec)
    second_id = await add_agent(
        store,
        job_id,
        spec.model_copy(update={"task_key": "parallel", "objective": "Another independent investigation"}),
    )
    async with store.db.locked(job_id) as (session, job):
        first = await session.get(Agent, first_id)
        store.transition(session, job, first, "COMPLETED")
    claim = await store.claim("supervisor")
    assert claim.agent_id is None
    provider = ScriptedProvider(
        decisions=[
            SupervisorDecision(
                action="CANCEL_AGENT",
                reason="The independent branch already resolved the objective",
                expected_benefit="Avoid redundant work",
                cancel_agent_ids=[second_id],
            )
        ]
    )
    await Runtime(store, provider).execute(claim)
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][1]["status"] == "CANCELLED"
    assert any(e["type"] == "supervisor.decision" for e in await store.events(job_id))


@pytest.mark.asyncio
async def test_cancelled_job_settles_inflight_reservations_even_if_worker_dies(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    claim = await store.claim("worker")
    reservation = await store.reserve(claim, "test-model", 1000, 1000)
    await store.cancel(job_id, "default")
    snapshot = await store.snapshot(job_id)
    assert snapshot["metrics"]["reserved_tokens"] == 0
    assert snapshot["metrics"]["tokens"] == 2000
    await store.settle(reservation, (100, 50))
    assert (await store.snapshot(job_id))["metrics"]["tokens"] == 150
