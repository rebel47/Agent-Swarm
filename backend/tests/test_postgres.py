"""Real row-lock integration test; PostgreSQL test database must already be migrated."""

import asyncio
import os

import pytest

from app.database import Database
from app.models import Agent, Budget
from app.schemas import JobRequest
from app.store import BudgetExhausted, Rejected, Store
from tests.conftest import add_agent


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_postgres_atomic_spawn_claim_and_restart(settings, spec, shared):
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to a migrated disposable PostgreSQL database")
    settings.database_url = url
    settings.shared_agent_budget = shared
    settings.max_total_agents = 5
    settings.max_concurrent_agents = 2
    first_db, second_db = Database(url), Database(url)
    first, second = Store(first_db, settings), Store(second_db, settings)
    job_id = await first.create_job(
        JobRequest(objective="Test PostgreSQL queue atomicity", workspace_id="test"), "default"
    )
    try:

        async def spawn(index):
            try:
                return await add_agent(
                    first if index % 2 else second,
                    job_id,
                    spec.model_copy(
                        update={
                            "task_key": str(index),
                            "objective": f"Independent PostgreSQL investigation {index}",
                        }
                    ),
                )
            except Rejected:
                return None

        ids = await asyncio.gather(*(spawn(i) for i in range(20)))
        assert len([i for i in ids if i]) == 5
        claims = await asyncio.gather(
            *(state.claim(f"process-{i}") for i, state in enumerate([first, second] * 6))
        )
        valid = [c for c in claims if c]
        assert len(valid) == 2
        assert len({c.agent_id for c in valid}) == 2
        assert (await second.snapshot(job_id))["metrics"]["total_agents"] == 5
        async with first_db.locked(job_id) as (session, job):
            budget = await session.get(Budget, job_id)
            budget.max_tokens = 30000
        reservations = await asyncio.gather(
            first.reserve(valid[0], "test-model", 18000, 1024),
            second.reserve(valid[1], "test-model", 18000, 1024),
            return_exceptions=True,
        )
        assert sum(isinstance(item, BudgetExhausted) for item in reservations) == 1
        assert sum(not isinstance(item, Exception) for item in reservations) == 1
        assert (await first.snapshot(job_id))["metrics"]["reserved_tokens"] == 19024
        # Reopening the service doesn't reset claims, history, budgets or agent relationships.
        await first_db.close()
        first_db = Database(url)
        assert len((await Store(first_db, settings).snapshot(job_id))["agents"]) == 5
        await second.cancel(job_id, "default")
        async with second_db.sessions() as session:
            assert all(
                [
                    (await session.get(Agent, agent_id)).status == "CANCELLED"
                    for agent_id in [i for i in ids if i]
                ]
            )
    finally:
        await second.cancel(job_id, "default")
        await first_db.close()
        await second_db.close()
