"""Regressions for real reviews failing while most of the job budget remained."""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select

from app.llm import ProviderError, RealProvider, messages
from app.models import Agent, Inference
from app.runtime import Runtime
from app.schemas import AgentTurn, SupervisorDecision
from app.tools import READ_TOOLS
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider
from tests.responses import response_payload
from tests.test_runtime import result


@pytest.mark.asyncio
@pytest.mark.parametrize("allowance,turn_limit", [(20000, 2), (18500, 20)])
async def test_source_review_uses_counted_tokens_and_keeps_latest_observation(
    store, spec, allowance, turn_limit
):
    policy = store.settings.policy("test-model")
    policy.max_output_tokens = 4096
    path = Path(store.settings.workspaces["test"]) / "app.py"
    path.write_text(path.read_text() + "# source context for edge case review\n" * 350, encoding="utf-8")
    spec = spec.model_copy(
        update={"token_budget": allowance, "max_steps": turn_limit, "allowed_tools": sorted(READ_TOOLS)}
    )
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    counts, requests = [], []

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/input_tokens"):
            counts.append(body)
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 3400})
        requests.append(body)
        if len(requests) == 1:
            raw = response_payload("read_repository_file", {"path": "app.py"})
        else:
            context = json.loads(body["input"][-1]["content"])
            assert context["execution_budget"]["remaining_steps"] == turn_limit - 1
            assert context["execution_budget"]["finish_required"] is True
            assert [tool["name"] for tool in body["tools"]] == ["submit_result"]
            assert context["tool_history"][-1]["output"]["path"] == "app.py"
            assert "source context for edge case review" in json.dumps(context["tool_history"])
            # This is larger in bytes than the remaining cumulative token allowance.
            assert len(json.dumps(body).encode()) > allowance - 3450
            raw = response_payload("submit_result", result().model_dump(), 1)
        raw["usage"].update(input_tokens=3400, total_tokens=3450)
        return httpx.Response(200, json=raw)

    provider = RealProvider(
        store.settings,
        AsyncOpenAI(
            api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ),
    )
    try:
        runtime = Runtime(store, provider)
        for _ in range(2):
            await runtime.execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["status"] == "RUNNING" and snapshot["agents"][0]["status"] == "COMPLETED"
        assert snapshot["agents"][0]["tokens"] == 6900
        assert len(requests) == len(counts) == 2
        for counted, generated in zip(counts, requests, strict=True):
            for key in ("model", "input", "tools", "tool_choice", "reasoning", "parallel_tool_calls"):
                assert counted[key] == generated[key]
        async with store.db.sessions() as session:
            inferences = list(await session.scalars(select(Inference).where(Inference.agent_id == agent_id)))
            assert all(i.reserved_tokens == 3400 + 256 + 4096 for i in inferences)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_exhausted_agent_does_not_cancel_sibling_or_job(store, spec):
    job_id = await new_job(store)
    exhausted_id = await add_agent(store, job_id, spec.model_copy(update={"token_budget": 2000}))
    healthy_id = await add_agent(
        store,
        job_id,
        spec.model_copy(
            update={"task_key": "healthy", "objective": "Independently check the implementation"}
        ),
    )
    async with store.db.locked(job_id) as (session, job):
        exhausted = await session.get(Agent, exhausted_id)
        exhausted.tokens = 1900
    provider = ScriptedProvider(
        decisions=[
            SupervisorDecision(
                action="WAIT_FOR_RESULTS",
                reason="The independent reviewer is still pending",
                expected_benefit="Preserve useful coverage while another agent is exhausted",
            )
        ],
        turns=[AgentTurn(result=result())],
    )
    runtime = Runtime(store, provider)
    await runtime.execute(await store.claim("worker"))
    snapshot = await store.snapshot(job_id)
    assert snapshot["status"] == "RUNNING" and not provider.calls and not provider.counts
    assert snapshot["agents"][0]["status"] == "FAILED"
    assert snapshot["agents"][0]["error"]["code"] == "agent_budget_exhausted"
    claim = await store.claim("worker")
    assert claim.agent_id is None  # Supervisor sees the exhausted branch and can recover.
    await runtime.execute(claim)
    claim = await store.claim("worker")
    assert claim.agent_id == healthy_id
    await runtime.execute(claim)
    assert (await store.snapshot(job_id))["agents"][1]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_small_summary_does_not_hide_cost_of_next_agent_turn(store, spec):
    """Replay the remaining allowance immediately after the reported run's summary."""
    store.settings.policy("test-model").max_output_tokens = 4096
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec.model_copy(update={"token_budget": 30000}))
    async with store.db.locked(job_id) as (session, job):
        agent = await session.get(Agent, agent_id)
        agent.tokens = 14571  # 15,429 left: enough to finish, too little for two full turns.
        agent.steps = 3
        for created_at, purpose, inp, out in [(1, "routine", 7576, 30), (2, "summary", 368, 166)]:
            session.add(
                Inference(
                    job_id=job_id,
                    agent_id=agent_id,
                    model="test-model",
                    purpose=purpose,
                    status="ACCOUNTED",
                    reserved_tokens=inp + out,
                    reserved_cost=0.01,
                    input_tokens=inp,
                    output_tokens=out,
                    created_at=created_at,
                )
            )
    provider = ScriptedProvider(turns=[AgentTurn(result=result())])
    await Runtime(store, provider).execute(await store.claim("worker"))
    assert [tool["name"] for tool in provider.counts[-1][1]] == ["submit_result"]
    prompt_context = json.loads(provider.calls[-1][1][-1]["content"])
    assert prompt_context["execution_budget"]["finish_required"] is True
    assert prompt_context["execution_budget"]["remaining_tokens"] == 15429
    agent_view = (await store.snapshot(job_id))["agents"][0]
    assert agent_view["status"] == "COMPLETED" and agent_view["error"] is None


@pytest.mark.asyncio
async def test_count_endpoint_error_is_visible_and_never_generates(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(
            404,
            headers={"x-request-id": "req_count"},
            json={
                "error": {
                    "code": "model_not_found",
                    "message": "Configured model is unavailable",
                    "type": "invalid_request_error",
                }
            },
        )

    provider = RealProvider(
        store.settings,
        AsyncOpenAI(
            api_key="test-only",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )
    try:
        await Runtime(store, provider).execute(await store.claim("worker"))
        snapshot = await store.snapshot(job_id)
        assert snapshot["agents"][0]["error"]["code"] == "model_not_found"
        assert snapshot["agents"][0]["error"]["request_id"] == "req_count"
        assert requests == ["/v1/responses/input_tokens"]
        assert snapshot["metrics"]["tokens"] == snapshot["metrics"]["unknown_usage_calls"] == 0
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_invalid_token_count_cannot_authorize_generation(settings):
    def handler(request):
        return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 0})

    provider = RealProvider(
        settings,
        AsyncOpenAI(
            api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ),
    )
    try:
        with pytest.raises(ProviderError, match="invalid input token count"):
            await provider.count_input_tokens(messages("Instructions", "{}"), [], "test-model", "routine")
    finally:
        await provider.close()


def test_compaction_keeps_latest_tool_result_and_marks_omitted_history(store):
    runtime = Runtime(store, ScriptedProvider())
    context = {"tool_history": [{"output": "old" * 1000}, {"output": "latest source evidence"}]}
    compacted = json.loads(runtime.compact(context, 1000))
    assert compacted["tool_history"] == [{"output": "latest source evidence"}]
    assert compacted["older_tool_observations_omitted"] is True
