"""Shared review budgets cannot strand specialists behind model-chosen token caps."""

import asyncio
import json

import pytest
from sqlalchemy import select

from app.models import Agent, Artifact, Budget, ToolExecution
from app.runtime import Runtime
from app.schemas import AgentTurn, ModelEscalationRequest
from app.store import BudgetExhausted
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider
from tests.test_runtime import result


def shared_review(store):
    store.settings.shared_agent_budget = True
    store.settings.max_agent_steps = 200
    store.settings.max_agent_tokens = 5000000
    store.settings.max_total_tokens = 100000000
    store.settings.max_total_cost_usd = 1000


@pytest.mark.parametrize("requested_steps,requested_tokens", [(1, 100), (14, 32000), (9999, 999999999)])
async def test_model_cannot_assign_small_allowances_or_exceed_admin_turn_limits(
    store, spec, requested_steps, requested_tokens
):
    shared_review(store)
    job_id = await new_job(store)
    agent_id = await add_agent(
        store,
        job_id,
        spec.model_copy(
            update={
                "max_steps": requested_steps,
                "token_budget": requested_tokens,
            }
        ),
    )
    async with store.db.locked(job_id) as (session, job):
        parent = await session.get(Agent, agent_id)
        child_id = (
            await store.spawn(
                session,
                job,
                [
                    spec.model_copy(
                        update={
                            "task_key": "child",
                            "objective": "Independently verify the division boundaries",
                            "max_steps": requested_steps,
                            "token_budget": requested_tokens,
                        }
                    )
                ],
                "Independent verification is useful",
                "Additional source coverage",
                parent=parent,
            )
        )[0]
    async with store.db.sessions() as session:
        for identifier in (agent_id, child_id):
            agent = await session.get(Agent, identifier)
            assert agent.spec["max_steps"] == 200
            assert agent.spec["token_budget"] == 5000000


@pytest.mark.parametrize("used_tokens", [20088, 80000])
async def test_reported_failure_and_old_checkpoints_use_shared_pool(store, spec, monkeypatch, used_tokens):
    shared_review(store)
    store.settings.policy("test-model").max_output_tokens = 4096
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, agent_id)
        # The failed review had 32,000 allocated, 20,088 used and needed 12,857 next.
        # Also exercise a checkpoint that has already exceeded the old 64k admin cap.
        agent.spec = {**agent.spec, "token_budget": 32000, "max_steps": 14}
        agent.tokens, agent.steps = used_tokens, 4
        budget = await session.get(Budget, job_id)
        budget.tokens = used_tokens
    provider = ScriptedProvider(turns=[AgentTurn(result=result())])

    async def count(*args):
        provider.counts.append(args)
        return 8505  # 8,505 + 256 headroom + 4,096 output = 12,857.

    monkeypatch.setattr(provider, "count_input_tokens", count)
    await Runtime(store, provider).execute(await store.claim("worker"))
    snapshot = await store.snapshot(job_id)
    agent = snapshot["agents"][0]
    assert agent["status"] == "COMPLETED" and agent["error"] is None
    context = json.loads(provider.calls[-1][1][-1]["content"])
    assert context["execution_budget"]["scope"] == "job"
    assert context["execution_budget"]["remaining_tokens"] == 100000000 - used_tokens
    assert context["execution_budget"]["finish_required"] is False
    assert snapshot["metrics"]["tokens"] == used_tokens + 150
    assert snapshot["metrics"]["reserved_tokens"] == 0


async def test_summary_still_runs_after_old_individual_allowance_is_spent(store, spec):
    shared_review(store)
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, agent_id)
        agent.spec = {**agent.spec, "token_budget": 32000}
        agent.tokens = 80000
        budget = await session.get(Budget, job_id)
        budget.tokens = 80000
        for index in range(8):
            session.add(
                ToolExecution(
                    job_id=job_id,
                    agent_id=agent_id,
                    idempotency_key=f"source-read-{index}",
                    name="read_repository_file",
                    arguments={"path": "app.py"},
                    output={"observation": "Read division source"},
                    created_at=index + 1,
                )
            )
    provider = ScriptedProvider(turns=[AgentTurn(result=result())])
    await Runtime(store, provider).execute(await store.claim("worker"))
    assert provider.calls[0][0] == "summary"
    async with store.db.sessions() as session:
        assert await session.scalar(
            select(Artifact).where(Artifact.agent_id == agent_id, Artifact.kind == "context_summary")
        )
    assert (await store.snapshot(job_id))["agents"][0]["status"] == "COMPLETED"


async def test_model_escalation_uses_shared_pool_after_old_individual_cap(store, spec):
    shared_review(store)
    store.settings.model_policies["stronger-model"] = store.settings.policy("test-model").model_copy()
    store.settings.verification_model = "stronger-model"
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, agent_id)
        agent.spec = {**agent.spec, "token_budget": 32000}
        agent.tokens = 80000
        await store.escalate(
            session,
            job,
            agent,
            ModelEscalationRequest(
                purpose="verification",
                reason="Independently resolve a difficult correctness claim",
                expected_benefit="Verify the source finding with stronger reasoning",
            ),
        )
        assert agent.spec["model"] == "stronger-model"


@pytest.mark.parametrize("limit", ["tokens", "cost"])
async def test_shared_pool_reservations_cannot_overspend_under_concurrency(store, spec, limit):
    shared_review(store)
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    await add_agent(
        store,
        job_id,
        spec.model_copy(
            update={"task_key": "sibling", "objective": "Check an independent correctness concern"}
        ),
    )
    first, second = await asyncio.gather(store.claim("one"), store.claim("two"))
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        if limit == "tokens":
            budget.max_tokens = 30000
        else:
            budget.max_cost_usd = 0.03  # Each reservation costs 0.020048.
    attempts = await asyncio.gather(
        *(store.reserve(claim, "test-model", 18000, 1024) for claim in (first, second)),
        return_exceptions=True,
    )
    assert sum(isinstance(attempt, BudgetExhausted) for attempt in attempts) == 1
    assert sum(not isinstance(attempt, Exception) for attempt in attempts) == 1
    snapshot = await store.snapshot(job_id)
    assert snapshot["metrics"]["reserved_tokens"] == 19024
    assert snapshot["status"] == "RUNNING"
