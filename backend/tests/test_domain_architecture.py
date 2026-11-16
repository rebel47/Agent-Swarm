"""Domain invariants and use cases run without a database, queue, or model request."""

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.domain.budgets import BudgetAccount, InferenceCharge
from app.domain.errors import AgentBudgetExhausted, BudgetExhausted, Rejected
from app.domain.investigations import AgentAllowance, ReviewBrief
from app.application.investigations import InvestigationService
from app.application.sources import SourceService


def test_reservation_invariant_includes_inflight_usage_and_agent_limit():
    account = BudgetAccount(10000, 6000, 2000, 1.0, 0.2, 0.1)
    charge = InferenceCharge(1500, 1000, 0.01)
    with pytest.raises(BudgetExhausted, match="Job token budget"):
        account.authorize(charge, 64000)
    account = BudgetAccount(20000, 0, 0, 1.0, 0, 0)
    with pytest.raises(AgentBudgetExhausted):
        account.authorize(charge, 64000, agent_remaining=2000)
    with pytest.raises(Rejected, match="model capability"):
        account.authorize(charge, 2000)


def test_agent_finishes_before_spending_its_report_allowance():
    assert AgentAllowance(9, 15429, 7576, 4096).finish_required
    assert AgentAllowance(1, 60000, 1000, 4096).finish_required
    assert not AgentAllowance(12, 60000, 1000, 4096).finish_required


def test_review_brief_rejects_invalid_domain_state():
    with pytest.raises(Rejected):
        ReviewBrief("", "source")
    with pytest.raises(Rejected):
        ReviewBrief("Review the code", "", mode="adaptive")
    with pytest.raises(Rejected):
        ReviewBrief("Review the code", "source", mode="unknown")


@pytest.mark.asyncio
async def test_start_review_persists_before_waking_worker_and_returns_owned_snapshot():
    repository, queue = AsyncMock(), AsyncMock()
    order = []

    async def create(brief, owner, key):
        order.append(("persist", owner, key))
        return "review-1"

    async def wake(job_id):
        order.append(("wake", job_id))

    repository.create.side_effect = create
    repository.get.return_value = {"id": "review-1", "status": "RUNNING", "agents": []}
    queue.wake.side_effect = wake
    service = InvestigationService(repository, queue)
    result = await service.start(ReviewBrief("Review reliability", "source"), "tenant", "request-1")
    assert result == {"id": "review-1", "status": "RUNNING"}
    assert order == [("persist", "tenant", "request-1"), ("wake", "review-1")]
    repository.get.assert_awaited_once_with("review-1", "tenant")


@pytest.mark.asyncio
async def test_foreign_review_cannot_be_cancelled_or_expose_agent_steps():
    repository, queue = AsyncMock(), AsyncMock()
    repository.get.side_effect = LookupError("Job not found")
    service = InvestigationService(repository, queue)
    with pytest.raises(LookupError):
        await service.cancel("foreign", "tenant")
    with pytest.raises(LookupError):
        await service.steps("foreign", "agent", "tenant", 0, 20)
    repository.cancel.assert_not_awaited()
    repository.steps.assert_not_awaited()
    queue.wake.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_survives_request_disconnect_and_shutdown_waits_for_it():
    repository, preparer = AsyncMock(), AsyncMock()
    repository.admit.return_value = {"id": "source-1"}
    entered, release = asyncio.Event(), asyncio.Event()

    async def prepare(record):
        entered.set()
        await release.wait()
        return {"revision": "abc", "file_count": 1, "size_bytes": 10}

    preparer.prepare.side_effect = prepare
    service = SourceService(repository, preparer)
    request = asyncio.create_task(service.prepare("https://github.com/team/repo", None, "owner"))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert service.tasks
    shutdown = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await shutdown
    repository.finish.assert_awaited_once_with(
        "source-1", info={"revision": "abc", "file_count": 1, "size_bytes": 10}
    )


def test_domain_and_application_do_not_import_framework_or_infrastructure():
    root = Path(__file__).resolve().parents[1] / "app"
    forbidden = {
        "fastapi",
        "sqlalchemy",
        "openai",
        "redis",
        "langgraph",
        "infrastructure",
        "models",
        "store",
        "config",
    }
    for layer in ("domain", "application"):
        for path in (root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not set((node.module or "").split(".")) & forbidden, path
                elif isinstance(node, ast.Import):
                    assert all(not set(alias.name.split(".")) & forbidden for alias in node.names), path
