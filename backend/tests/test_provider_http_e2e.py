"""Full supervisor/worker/native-tools flow through the installed SDK, with test-only HTTP responses."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.llm import RealProvider
from app.runtime import Runtime
from app.schemas import SubagentRequest, SupervisorDecision
from app.worker import Worker
from tests.conftest import new_job
from tests.test_runtime import decision, result
from tests.responses import response_payload


@pytest.mark.asyncio
async def test_sdk_worker_recursive_workflow(settings, store, spec):
    settings.max_concurrent_agents = 1
    job_id = await new_job(store)
    requests = []
    child = spec.model_copy(
        update={
            "task_key": "sdk-child",
            "role": "Independent verifier",
            "objective": "Independently verify arithmetic source evidence",
        }
    )

    async def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/v1/responses/input_tokens":
            assert body["tools"] and body["parallel_tool_calls"] is False
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 100})
        context = json.loads(body["input"][-1]["content"])
        index = len(requests)
        requests.append(body)
        if index == 0:
            name, args = "SupervisorDecision", decision([spec]).model_dump()
        elif index == 1:
            name = "request_subagents"
            args = SubagentRequest(
                reason="Independent verification requires separate source inspection",
                expected_benefit="Cross-check arithmetic evidence",
                agents=[child],
            ).model_dump()
        elif index == 2:
            name, args = "read_repository_file", {"path": "app.py"}
        elif index in (3, 5):
            name, args = "submit_result", result().model_dump()
        elif index == 4:
            child_id = next(a["id"] for a in context["agents"] if a["parent_agent_id"])
            name, args = "retrieve_agent_result", {"agent_id": child_id}
        elif index == 7:
            name, args = "AgentResult", result().model_dump()
        else:
            name = "SupervisorDecision"
            args = SupervisorDecision(
                action="FINISH",
                reason="Independent findings match actual source evidence",
                expected_benefit="Deliver the completed investigation",
                report=result(),
            ).model_dump()
        return httpx.Response(
            200,
            json=response_payload(name, args, index),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealProvider(
        settings,
        AsyncOpenAI(
            api_key="test-only", base_url="https://api.openai.com/v1", max_retries=0, http_client=client
        ),
    )
    worker = Worker(store, Runtime(store, provider))
    running = asyncio.create_task(worker.run())
    try:
        async with asyncio.timeout(15):
            while (await store.snapshot(job_id))["status"] == "RUNNING":  # noqa: ASYNC110 -- durable state polling
                await asyncio.sleep(0.05)
        snapshot = await store.snapshot(job_id)
        assert snapshot["status"] == "COMPLETED", snapshot.get("error")
        assert len(snapshot["agents"]) == 2
        assert snapshot["agents"][1]["parent_agent_id"] == snapshot["agents"][0]["id"]
        assert all(a["status"] == "COMPLETED" for a in snapshot["agents"])
        assert snapshot["metrics"]["tokens"] == 1200
        assert snapshot["metrics"]["max_concurrency"] == 1
        assert len(requests) == 8
        assert requests[0]["tool_choice"]["name"] == "SupervisorDecision"
        assert any(t["name"] == "read_repository_file" for t in requests[2]["tools"])
        assert snapshot["report"]["findings"][0]["evidence"][0]["path"] == "app.py"
    finally:
        worker.stopping.set()
        await running
        await client.aclose()
