from fastapi.testclient import TestClient

from app.api import create_app


def test_api_auth_ownership_pagination_cancellation_and_sse(settings):
    app = create_app(settings)
    auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/jobs").status_code == 401
        assert client.get("/api/v1/workspaces", headers=auth).json()["items"][0]["id"] == "test"
        body = {"objective": "Inspect repository correctness", "workspace_id": "test"}
        created = client.post("/api/v1/jobs", headers={**auth, "Idempotency-Key": "api-test"}, json=body)
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        assert (
            client.post("/api/v1/jobs", headers={**auth, "Idempotency-Key": "api-test"}, json=body).json()[
                "id"
            ]
            == job_id
        )
        assert len(client.get("/api/v1/jobs?limit=1", headers=auth).json()["items"]) == 1
        assert client.get("/api/v1/jobs?limit=1001", headers=auth).status_code == 422
        assert client.get("/api/v1/jobs/unknown", headers=auth).status_code == 404
        assert client.get(f"/api/v1/jobs/{job_id}/agents/unknown", headers=auth).status_code == 404
        assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth).json()["status"] == "CANCELLED"
        history = client.get(f"/api/v1/jobs/{job_id}/history", headers=auth).json()
        first_id = history[0]["id"]
        stream = client.get(f"/api/v1/jobs/{job_id}/events", headers={**auth, "Last-Event-ID": str(first_id)})
        assert stream.status_code == 200
        assert "event: snapshot" in stream.text
        ids = [int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")]
        assert ids and all(event_id > first_id for event_id in ids)
        assert '"status": "CANCELLED"' in stream.text
        assert (
            client.get(f"/api/v1/jobs/{job_id}/events", headers={**auth, "Last-Event-ID": "bad"}).status_code
            == 422
        )
        assert client.get("/api/v1/ready", headers=auth).status_code == 503


def test_job_owner_is_enforced(settings):
    app = create_app(settings)
    auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
    with TestClient(app) as client:
        from app.schemas import JobRequest

        async def insert():
            return await app.state.store.create_job(
                JobRequest(objective="Other tenant's private objective", workspace_id="test"),
                "another-tenant",
            )

        # Use TestClient's event-loop portal to avoid crossing async database event loops.
        job_id = client.portal.call(insert)
        assert client.get(f"/api/v1/jobs/{job_id}", headers=auth).status_code == 404
        assert client.get(f"/api/v1/jobs/{job_id}/events", headers=auth).status_code == 404
        assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth).status_code == 404
        assert client.get("/api/v1/jobs", headers=auth).json()["items"] == []


def test_job_schema_rejects_arbitrary_paths_and_extra_permissions(settings):
    with TestClient(create_app(settings)) as client:
        auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
        response = client.post(
            "/api/v1/jobs",
            headers=auth,
            json={"objective": "Inspect repository correctness", "workspace_id": "../../etc"},
        )
        assert response.status_code == 409
        assert (
            client.post(
                "/api/v1/jobs",
                headers=auth,
                json={
                    "objective": "Inspect repository correctness",
                    "workspace_id": "test",
                    "allowed_tools": ["shell"],
                },
            ).status_code
            == 422
        )


def test_model_configuration_and_explicit_connectivity(settings, monkeypatch):
    import httpx
    from openai import AsyncOpenAI
    from app.llm import RealProvider
    from tests.responses import response_payload

    requests = []

    def handler(request):
        import json

        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload("ContextSummary", {"summary": "connected"}))

    def factory(configuration):
        return RealProvider(
            configuration,
            AsyncOpenAI(
                api_key="test-only",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            ),
        )

    monkeypatch.setattr("app.api.RealProvider", factory)
    auth = {"Authorization": "Bearer " + settings.api_token.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        assert not requests
        assert client.get("/api/v1/models").status_code == 401
        configuration = client.get("/api/v1/models", headers=auth).json()
        assert configuration["provider"] == "openai"
        assert configuration["allocation"]["routine"] == "test-model"
        assert not requests
        response = client.post("/api/v1/models/connectivity", headers=auth, json={"model": "unapproved"})
        assert response.status_code == 400 and not requests
        response = client.post("/api/v1/models/connectivity", headers=auth, json={"model": "test-model"})
        assert response.status_code == 200, response.text
        assert response.json()["connected"] and response.json()["tool_calling"]
        assert response.json()["input_tokens"] == 100
        assert len(requests) == 1 and requests[0]["model"] == "test-model"
        response = client.post(
            "/api/v1/jobs",
            headers=auth,
            json={
                "objective": "Inspect reliability",
                "workspace_id": "test",
                "model_overrides": {"routine": "unapproved"},
            },
        )
        assert response.status_code == 409
