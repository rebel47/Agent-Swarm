"""OpenAI allocation, actual SDK requests, caching, accounting and budget enforcement."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import ModelPolicy, Settings
from app.llm import ProviderError, RealProvider, Reply, messages
from app.models import Agent, Artifact, Budget, Inference, ToolExecution
from app.runtime import Runtime
from app.schemas import AgentTurn, JobRequest, ModelEscalationRequest, ToolCall
from app.store import Rejected
from app.tools import definitions
from tests.conftest import add_agent, new_job
from tests.fakes import ScriptedProvider
from tests.responses import response_payload
from tests.test_runtime import drain, result, decision


def configure_tiers(settings):
    settings.model_policies = {
        "economical": ModelPolicy(
            input_per_million=0.1, output_per_million=0.5, context_tokens=64000, max_output_tokens=1024
        ),
        "strong": ModelPolicy(
            input_per_million=2, output_per_million=10, context_tokens=64000, max_output_tokens=1024
        ),
    }
    settings.subagent_model = "economical"
    settings.orchestrator_model = settings.verification_model = settings.synthesis_model = "strong"


def sdk(settings, handler):
    return RealProvider(
        settings,
        AsyncOpenAI(
            api_key="test-only",
            base_url="https://api.openai.com/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )


@pytest.mark.asyncio
async def test_sdk_tools_caching_reasoning_usage(settings):
    settings.model_policies["test-model"] = ModelPolicy(
        input_per_million=1,
        output_per_million=2,
        cached_input_per_million=0.1,
        cache_write_multiplier=1.25,
        prompt_caching="explicit",
        context_tokens=64000,
        max_output_tokens=1024,
    )
    seen = []

    def handler(request):
        assert request.url.host == "api.openai.com" and request.url.path == "/v1/responses"
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json=response_payload(
                "read_repository_file",
                {"path": "app.py"},
                details={
                    "cached_tokens": 40,
                    "cache_write_tokens": 20,
                    "cache_write_tokens_details": {"ttl_30m_tokens": 20, "ttl_12h_tokens": 0},
                },
            ),
        )

    provider = sdk(settings, handler)
    try:
        reply = await provider.act(
            messages("Stable instructions", "{}"), definitions(["read_repository_file"]), "test-model"
        )
        assert reply.payload.call.arguments == {"path": "app.py"}
        assert reply.input_tokens == 100 and reply.output_tokens == 50
        assert reply.usage_details["cached_tokens"] == 40
        assert reply.usage_details["reasoning_tokens"] == 10
        assert seen[0]["reasoning"] == {"effort": "low"}
        assert seen[0]["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        assert seen[0]["input"][0]["content"][0]["prompt_cache_breakpoint"]["mode"] == "explicit"
        assert seen[0]["store"] is False and seen[0]["parallel_tool_calls"] is False
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_unavailable_model_reports_actual_error_without_fallback(settings):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(
            404,
            headers={"x-request-id": "req_unavailable"},
            json={
                "error": {
                    "message": "The model test-model does not exist or you do not have access to it.",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                    "param": "model",
                }
            },
        )

    provider = sdk(settings, handler)
    try:
        with pytest.raises(ProviderError, match="does not exist or you do not have access") as info:
            await provider.connectivity("test-model")
        assert info.value.code == "model_not_found"
        assert info.value.status == 404 and info.value.request_id == "req_unavailable"
        assert not info.value.retryable and calls == ["test-model"]
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_malformed_structured_response_still_has_billable_usage(settings):
    def handler(request):
        response = response_payload("SupervisorDecision", {"bad": True})
        return httpx.Response(200, json=response)

    provider = sdk(settings, handler)
    try:
        reply = await provider.decide(messages("Instructions", "{}"), "test-model")
        assert reply.payload["validation_error"]
        assert reply.input_tokens == 100
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_sdk_stream_final_usage(settings):
    settings.stream_llm = True

    def handler(request):
        assert json.loads(request.content)["stream"]
        payload = response_payload("read_repository_file", {"path": "app.py"})
        initial = {**payload, "output": [], "status": "in_progress", "usage": None}
        item = payload["output"][0]
        events = [
            {"type": "response.created", "response": initial},
            {"type": "response.output_item.added", "output_index": 0, "item": {**item, "arguments": ""}},
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": item["id"],
                "delta": item["arguments"],
            },
            {
                "type": "response.function_call_arguments.done",
                "output_index": 0,
                "item_id": item["id"],
                "arguments": item["arguments"],
                "name": item["name"],
            },
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": payload},
        ]
        text = "".join(
            "event: " + e["type"] + "\ndata: " + json.dumps({**e, "sequence_number": i}) + "\n\n"
            for i, e in enumerate(events)
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    provider = sdk(settings, handler)
    try:
        reply = await provider.act(
            messages("Instructions", "{}"), definitions(["read_repository_file"]), "test-model"
        )
        assert reply.payload.call.name == "read_repository_file"
        assert reply.input_tokens == 100 and reply.output_tokens == 50
    finally:
        await provider.close()


def test_missing_usage_is_never_free():
    with pytest.raises(ProviderError, match="token usage"):
        RealProvider.usage(SimpleNamespace(usage=None))


def test_defaults_and_startup_validate_all_allocations(settings):
    defaults = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="",
        api_token="test-only",
        openai_api_key="test-only",
    )
    assert (
        defaults.orchestrator_model == defaults.verification_model == defaults.synthesis_model == "gpt-6-sol"
    )
    assert defaults.subagent_model == "gpt-6-luna" and defaults.max_total_cost_usd == 1000
    assert defaults.shared_agent_budget is True
    assert defaults.max_total_tokens == 100000000
    assert defaults.max_agent_steps == 200 and defaults.max_supervisor_steps == 400
    assert (defaults.max_total_agents, defaults.max_concurrent_agents, defaults.max_agent_depth) == (
        100,
        10,
        5,
    )
    settings.synthesis_model = "unlisted"
    with pytest.raises(ValueError, match="unlisted"):
        settings.validate_runtime()


def test_invalid_reasoning_and_cache_policies_fail_startup(settings):
    settings.subagent_reasoning_effort = "unbounded"
    with pytest.raises(ValueError, match="reasoning effort"):
        settings.validate_runtime()
    with pytest.raises(ValidationError, match="cache write"):
        ModelPolicy(input_per_million=1, output_per_million=2, prompt_caching="explicit")


@pytest.mark.asyncio
async def test_routine_default_stronger_reason_required_and_job_override(store, spec):
    configure_tiers(store.settings)
    job_id = await new_job(store)
    routine = await add_agent(store, job_id, spec)
    assert (await store.snapshot(job_id))["agents"][0]["model"] == "economical"
    with pytest.raises(ValueError, match="allocation reason"):
        await add_agent(
            store,
            job_id,
            spec.model_copy(
                update={
                    "task_key": "v",
                    "objective": "Verify a distinct critical issue",
                    "model_purpose": "verification",
                }
            ),
        )
    verifier = spec.model_copy(
        update={
            "task_key": "v",
            "objective": "Verify a distinct critical issue",
            "model_purpose": "verification",
            "model_reason": "Critical independent validation requires stronger reasoning",
        }
    )
    await add_agent(store, job_id, verifier)
    snapshot = await store.snapshot(job_id)
    assert {a["model"] for a in snapshot["agents"]} == {"economical", "strong"}
    assert routine
    other = await new_job(
        store,
        JobRequest(
            objective="Inspect another repository question",
            workspace_id="test",
            model_overrides={"routine": "strong"},
        ),
    )
    await add_agent(store, other, spec)
    assert (await store.snapshot(other))["agents"][0]["model"] == "strong"
    assert store.settings.subagent_model == "economical"


@pytest.mark.asyncio
async def test_escalation_is_reasoned_budget_checked_and_used_on_next_call(store, spec):
    configure_tiers(store.settings)
    spec = spec.model_copy(update={"allowed_tools": [*spec.allowed_tools, "request_model_escalation"]})
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    request = ModelEscalationRequest(
        purpose="complex",
        reason="Cross-module invariants need deeper reasoning",
        expected_benefit="Resolve a contradictory source interpretation",
    )
    provider = ScriptedProvider(
        turns=[
            AgentTurn(call=ToolCall(name="request_model_escalation", arguments=request.model_dump())),
            AgentTurn(result=result()),
        ]
    )
    runtime = Runtime(store, provider)
    await runtime.execute(await store.claim("worker"))
    assert (await store.snapshot(job_id))["agents"][0]["model"] == "strong"
    await runtime.execute(await store.claim("worker"))
    assert provider.models_used == ["economical", "strong"]
    assert any(e["type"] == "model.escalated" for e in await store.events(job_id))


@pytest.mark.asyncio
async def test_escalation_cannot_spend_insufficient_budget(store, spec):
    configure_tiers(store.settings)
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        budget.max_cost_usd = 0.001
        agent = await session.get(Agent, agent_id)
        with pytest.raises(Rejected, match="remaining budget"):
            await store.escalate(
                session,
                job,
                agent,
                ModelEscalationRequest(
                    purpose="complex",
                    reason="Deep reasoning required for conflicting invariants",
                    expected_benefit="Resolve contradictions reliably",
                ),
            )
        assert agent.spec["model"] == "economical"


@pytest.mark.asyncio
async def test_budget_exhaustion_cancels_before_sdk_call(store, spec):
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        budget = await session.get(Budget, job_id)
        budget.max_cost_usd = 0.00000001
    provider = ScriptedProvider()
    await Runtime(store, provider).execute(await store.claim("worker"))
    snapshot = await store.snapshot(job_id)
    assert snapshot["status"] == "CANCELLED" and snapshot["error"]["code"] == "budget_exhausted"
    assert not provider.calls and not provider.counts and snapshot["metrics"]["reserved_cost_usd"] == 0


@pytest.mark.asyncio
async def test_cached_usage_and_late_settlement_reconcile_immutable_pricing(store, spec):
    store.settings.model_policies["test-model"].cached_input_per_million = 0.1
    store.settings.model_policies["test-model"].cache_write_multiplier = 1.25
    job_id = await new_job(store)
    await add_agent(store, job_id, spec)
    claim = await store.claim("worker")
    reservation = await store.reserve(claim, "test-model", 1000, 1000)
    store.settings.model_policies["test-model"].input_per_million = 999
    await store.cancel(job_id, "default")
    await store.settle(
        reservation,
        Reply(None, 100, 50, {"cached_tokens": 40, "cache_write_tokens": 20, "reasoning_tokens": 10}),
    )
    snapshot = await store.snapshot(job_id)
    assert snapshot["metrics"]["tokens"] == 150
    assert snapshot["metrics"]["estimated_cost_usd"] == pytest.approx(0.000169)
    assert snapshot["metrics"]["cached_input_tokens"] == 40 and snapshot["metrics"]["reasoning_tokens"] == 10
    assert snapshot["metrics"]["unknown_usage_calls"] == 0
    assert snapshot["status"] == "CANCELLED"
    await store.settle(reservation, Reply(None, 100, 50))
    assert (await store.snapshot(job_id))["metrics"]["tokens"] == 150


@pytest.mark.asyncio
async def test_synthesis_uses_configured_model_and_accounting(store, spec):
    configure_tiers(store.settings)
    job_id = await new_job(store)
    from app.schemas import SupervisorDecision

    provider = ScriptedProvider(
        decisions=[
            decision([spec]),
            SupervisorDecision(
                action="FINISH",
                reason="Evidence is sufficient for final reporting",
                expected_benefit="Deliver findings",
                report=result(),
            ),
        ],
        turns=[AgentTurn(result=result())],
    )
    await drain(store, Runtime(store, provider))
    assert provider.models_used == ["strong", "economical", "strong", "strong"]
    assert (await store.snapshot(job_id))["metrics"]["tokens"] == 600
    async with store.db.sessions() as session:
        from sqlalchemy import select

        synthesis = await session.scalar(
            select(Inference).where(Inference.job_id == job_id, Inference.purpose == "synthesis")
        )
        assert synthesis.model == "strong"


@pytest.mark.asyncio
async def test_model_summarization_is_persisted_reused_and_accounted(store, spec):
    job_id = await new_job(store)
    agent_id = await add_agent(store, job_id, spec)
    async with store.db.locked(job_id) as (session, job):
        for index in range(8):
            session.add(
                ToolExecution(
                    job_id=job_id,
                    agent_id=agent_id,
                    idempotency_key=f"seed:{index}",
                    name="read_repository_file",
                    arguments={"path": "app.py"},
                    output={"source": "return a / b"},
                    created_at=index + 1,
                )
            )
    provider = ScriptedProvider(turns=[AgentTurn(result=result())])
    await Runtime(store, provider).execute(await store.claim("worker"))
    assert [c[0] for c in provider.calls] == ["summary", "agent"]
    context = await store.context(job_id, agent_id)
    assert context["context_summary"]["evidence_references"] == ["app.py:2"]
    assert len(context["tool_history"]) == 1
    assert (await store.snapshot(job_id))["agents"][0]["tokens"] == 300
    async with store.db.sessions() as session:
        from sqlalchemy import select

        assert await session.scalar(
            select(Artifact).where(Artifact.agent_id == agent_id, Artifact.kind == "context_summary")
        )
