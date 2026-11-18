"""Regressions for citation loss, filtered inventories and malformed paid responses."""

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.infrastructure.evidence import retain_source_evidence
from app.models import Budget, Inference, ToolExecution
from app.runtime import Runtime
from app.schemas import AgentTurn, ToolCall
from app.tools import Repository, bounded
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider
from tests.responses import response_payload
from tests.test_openai import sdk
from tests.test_runtime import result


def source_observation(path="app.py", line=2, text="    return a / b"):
    return {
        "name": "read_repository_file",
        "output": {
            "path": path,
            "untrusted": True,
            "lines": [{"line": line, "text": text}],
        },
    }


def test_exact_evidence_merges_without_using_model_summary_text():
    original = source_observation(text="    return 'quoted \\\"text\\\"'  # café")
    first = retain_source_evidence({}, [original], 2000)
    second = retain_source_evidence(
        first, [source_observation("tools.py", 43, "    requests.get(url)")], 2000
    )
    assert second["source_evidence"][0]["lines"] == original["output"]["lines"]
    assert second["source_evidence"][1]["lines"][0]["line"] == 43
    assert all(excerpt["untrusted"] for excerpt in second["source_evidence"])
    assert not second["source_evidence_omitted"]
    assert first["source_evidence"] != second["source_evidence"]
    trimmed = retain_source_evidence(second, [source_observation("large.py", 1, "x" * 4000)], 300)
    assert trimmed["source_evidence_omitted"]
    assert {item["path"] for item in trimmed["source_evidence_index"]} == {"app.py", "tools.py", "large.py"}
    assert len(json.dumps(trimmed["source_evidence"], ensure_ascii=False)) <= 300


@pytest.mark.asyncio
async def test_numbered_citations_survive_two_summaries_and_a_restart(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)

    async def seed(start):
        async with store.db.locked(job_id) as (session, job):
            for index in range(start, start + 8):
                session.add(
                    ToolExecution(
                        job_id=job_id,
                        agent_id=agent_id,
                        idempotency_key=f"seed:{index}",
                        name="read_repository_file",
                        arguments={"path": "app.py"},
                        output=source_observation()["output"],
                        created_at=index,
                    )
                )

    await seed(1)
    first = ScriptedProvider(
        turns=[AgentTurn(call=ToolCall(name="read_repository_file", arguments={"path": "app.py"}))]
    )
    await Runtime(store, first).execute(await store.claim("first-worker"))
    await seed(9)
    second = ScriptedProvider(turns=[AgentTurn(result=result())])
    # A fresh runtime must recover exact quotes from persisted artifacts, not process memory.
    await Runtime(store, second).execute(await store.claim("restarted-worker"))
    context = json.loads(second.calls[-1][1][-1]["content"])
    assert [call[0] for call in second.calls] == ["summary", "agent"]
    assert "source_evidence" not in context["context_summary"]
    excerpt = next(item for item in context["source_evidence"] if item["path"] == "app.py")
    assert {"line": 2, "text": "    return a / b"} in excerpt["lines"]
    assert context["source_evidence_index"]
    snapshot = await store.snapshot(job_id)
    assert snapshot["agents"][0]["status"] == "COMPLETED"
    assert snapshot["agents"][0]["tokens"] == 600


def test_compaction_marks_evidence_omissions_without_mutating_durable_context(store):
    context = {
        **retain_source_evidence({}, [source_observation(text="x" * 4000)], 10000),
        "tool_history": [{"output": "latest observation"}],
    }
    before = json.dumps(context)
    compacted = json.loads(Runtime(store, ScriptedProvider()).compact(context, 1000))
    assert compacted["source_evidence_omitted"]
    assert compacted["tool_history"] == context["tool_history"]
    assert json.dumps(context) == before


def test_inventory_is_explicitly_filtered_even_when_not_truncated(settings):
    root = Path(settings.workspaces["test"])
    (root / ".gitignore").write_text(".env\nnode_modules/\n", encoding="utf-8")
    (root / ".env").write_text("secret content", encoding="utf-8")
    (root / "excluded.unknown").write_text("not an authorized file type", encoding="utf-8")
    repository = Repository(root, settings)
    listing = repository.execute("list_repository_files", {})
    assert ".gitignore" in listing["files"]
    assert ".env" not in listing["files"] and "excluded.unknown" not in listing["files"]
    assert listing["complete_repository_inventory"] is False
    assert listing["truncated"] is False
    assert "not evidence of absence" in listing["note"]
    assert repository.execute("read_repository_file", {"path": ".gitignore"})["lines"][0]["text"] == ".env"
    empty = repository.execute("list_repository_files", {"pattern": "missing.*"})
    assert empty["files"] == [] and empty["complete_repository_inventory"] is False
    limited = repository.execute("list_repository_files", {"limit": 1})
    assert limited["truncated"] is True and limited["complete_repository_inventory"] is False
    settings.max_repository_files = 1
    assert repository.execute("list_repository_files", {})["scan_limit_reached"] is True


def test_output_bounds_preserve_inventory_limits_and_exact_numbered_lines(settings):
    settings.max_tool_output_chars = 2000
    listing = {
        "files": [f"directory/{index}/" + "x" * 100 + ".py" for index in range(100)],
        "complete_repository_inventory": False,
        "scope": "filtered_reviewable_files",
        "truncated": False,
    }
    limited = bounded(listing, settings)
    assert limited["complete_repository_inventory"] is False and limited["truncated"] is True
    assert len(json.dumps(limited)) <= 2000
    original = {
        "path": "app.py",
        "untrusted": True,
        "lines": [{"line": index + 1, "text": "    " + "source " * 10} for index in range(100)],
    }
    excerpt = bounded(original, settings)
    assert excerpt["lines"] and excerpt["lines"] == original["lines"][: len(excerpt["lines"])]
    assert excerpt["next_start_line"] == excerpt["lines"][-1]["line"] + 1
    assert len(json.dumps(excerpt)) <= 2000
    oversized = bounded({"path": "app.py", "lines": [{"line": 1, "text": "x" * 5000}]}, settings)
    assert oversized["lines"] == [] and oversized["error"]


def malformed_response(kind):
    raw = response_payload(
        "submit_result", {"result": result().model_dump(), "api_key": "secret-never-record"}
    )
    if kind == "json":
        raw["output"][0]["arguments"] = '{"api_key":"secret-never-record'
    elif kind == "multiple":
        raw["output"].append(response_payload("read_repository_file", {"path": "app.py"}, 1)["output"][0])
    elif kind == "incomplete":
        raw["status"] = "incomplete"
        raw["incomplete_details"] = {"reason": "max_output_tokens"}
    elif kind == "unauthorized":
        raw["output"][0]["name"] = "shell"
    elif kind == "refusal":
        raw["output"] = [
            {
                "id": "msg_refusal",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Request refused"}],
            }
        ]
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["schema", "json", "multiple", "incomplete", "unauthorized"])
async def test_malformed_sdk_result_recovers_in_a_budgeted_turn_with_safe_diagnostics(store, spec, kind):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json=malformed_response(kind))
        context = json.loads(body["input"][-1]["content"])
        observation = context["tool_history"][-1]
        assert observation["name"] == "invalid_response"
        assert observation["output"]["response_id"] == "resp_test_0"
        assert "direct" in observation["output"]["guidance"]
        assert "secret-never-record" not in json.dumps(context)
        return httpx.Response(200, json=response_payload("submit_result", result().model_dump(), 1))

    provider = sdk(store.settings, handler)
    try:
        runtime = Runtime(store, provider)
        await runtime.execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["agents"][0]["status"] == "QUEUED"
        assert snapshot["metrics"]["tokens"] == 150
        await runtime.execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["agents"][0]["status"] == "COMPLETED"
        assert snapshot["agents"][0]["error"] is None
        assert snapshot["agents"][0]["steps"] == 2
        assert snapshot["metrics"]["tokens"] == 300
        assert snapshot["metrics"]["reserved_tokens"] == snapshot["metrics"]["unknown_usage_calls"] == 0
        event = next(event for event in await store.events(job_id) if event["type"] == "llm.invalid_response")
        assert event["data"]["retry_scheduled"] is True
        assert event["data"]["function_call_count"] == (2 if kind == "multiple" else 1)
        if kind == "schema":
            assert event["data"]["validation_errors"]
        if kind == "incomplete":
            assert event["data"]["incomplete_reason"] == "max_output_tokens"
        async with store.db.sessions() as session:
            recorded = list(await session.scalars(select(Inference).where(Inference.job_id == job_id)))
            assert len(recorded) == 2 and all(inference.status == "ACCOUNTED" for inference in recorded)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_corrective_retry_cannot_bypass_the_job_budget(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    generated = []

    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        generated.append(request)
        assert len(generated) == 1
        return httpx.Response(200, json=malformed_response("schema"))

    provider = sdk(store.settings, handler)
    try:
        runtime = Runtime(store, provider)
        await runtime.execute(await store.claim("worker"))
        async with store.db.locked(job_id) as (session, job):
            budget = await session.get(Budget, job_id)
            budget.max_cost_usd = budget.cost_usd + 0.0000001
        await runtime.execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["status"] == "CANCELLED" and snapshot["error"]["code"] == "budget_exhausted"
        assert len(generated) == 1 and snapshot["metrics"]["tokens"] == 150
        assert snapshot["metrics"]["reserved_tokens"] == 0
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,retries,attempts", [("schema", 1, 2), ("schema", 0, 1), ("refusal", 3, 1)])
async def test_repeated_invalid_responses_are_bounded_and_refusals_are_not_retried(
    store, spec, kind, retries, attempts
):
    store.settings.max_retries = retries
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)

    def handler(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        return httpx.Response(200, json=malformed_response(kind))

    provider = sdk(store.settings, handler)
    try:
        runtime = Runtime(store, provider)
        for _ in range(attempts):
            await runtime.execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["agents"][0]["status"] == "FAILED"
        assert snapshot["agents"][0]["steps"] == attempts
        assert snapshot["metrics"]["tokens"] == 150 * attempts
        assert snapshot["status"] == "RUNNING"  # The supervisor may replan the failed branch.
        events = [event for event in await store.events(job_id) if event["type"] == "llm.invalid_response"]
        assert len(events) == attempts and events[-1]["data"]["retry_scheduled"] is False
    finally:
        await provider.close()
