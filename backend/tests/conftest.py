import asyncio

import pytest
import pytest_asyncio

from app.config import ModelPolicy, Settings
from app.database import Database
from app.schemas import AgentSpec, JobRequest
from app.store import Store


def pytest_asyncio_loop_factories(config, item):
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    # Pydantic merges dictionary settings across sources. Tests must never inherit
    # administrator workspaces or model policies from the host/Compose environment.
    monkeypatch.delenv("WORKSPACES", raising=False)
    monkeypatch.delenv("MODEL_POLICIES", raising=False)
    monkeypatch.delenv("LOCAL_REPOSITORY_ROOTS", raising=False)
    repo = tmp_path / "repository"
    repo.mkdir()
    (repo / "app.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'state.db').as_posix()}",
        redis_url="",
        api_token="test-bearer-token-that-is-at-least-32-characters",
        openai_api_key="unit-test-key-never-used-for-inference",
        orchestrator_model="test-model",
        subagent_model="test-model",
        verification_model="test-model",
        synthesis_model="test-model",
        model_policies={
            "test-model": ModelPolicy(
                input_per_million=1, output_per_million=2, context_tokens=64000, max_output_tokens=1024
            )
        },
        workspaces={"test": str(repo)},
        repository_cache_dir=str(tmp_path / "snapshots"),
        local_repository_roots={},
        max_agent_tokens=60000,
        max_agent_steps=20,
        max_concurrent_agents=2,
        max_total_cost_usd=100,
        poll_seconds=0.01,
        request_timeout_seconds=5,
        lease_seconds=10,
    )


@pytest_asyncio.fixture
async def store(settings):
    db = Database(settings.database_url)
    await db.create_test_schema()
    state = Store(db, settings)
    yield state
    await db.close()


@pytest.fixture
def request_body():
    return JobRequest(
        objective="Investigate division reliability and validate source evidence", workspace_id="test"
    )


@pytest.fixture
def spec():
    return AgentSpec(
        task_key="division",
        role="Arithmetic investigator",
        objective="Check division handling in app.py",
        system_instructions="Read the division implementation and report source evidence",
        allowed_tools=["read_repository_file", "retrieve_agent_result", "request_subagents"],
        token_budget=60000,
    )


async def new_job(store, body=None):
    return await store.create_job(
        body or JobRequest(objective="Investigate repository reliability", workspace_id="test"), "default"
    )


async def add_agent(store, job_id, spec, parent=None):
    async with store.db.locked(job_id) as (session, job):
        return (
            await store.spawn(
                session,
                job,
                [spec],
                "Independent source investigation",
                "Evidence-backed review",
                parent=parent,
            )
        )[0]
