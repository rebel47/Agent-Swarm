"""Thin, authenticated HTTP routes. No SQL queries or transaction ownership here."""

import asyncio
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..domain.investigations import ReviewBrief
from ..schemas import (
    AgentView,
    ConnectivityRequest,
    EventView,
    JobCreated,
    JobRequest,
    JobView,
    Page,
    RepositoryRequest,
    RepositoryView,
    WorkspacesView,
)


def router(settings, provider_factory):
    routes = APIRouter(prefix="/api/v1")
    security = HTTPBearer(auto_error=False)

    async def owner(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if not credentials or not hmac.compare_digest(
            credentials.credentials, settings.api_token.get_secret_value()
        ):
            raise HTTPException(
                401, "Valid bearer authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        return settings.tenant_id

    def reviews(request: Request):
        return request.app.state.reviews

    def sources(request: Request):
        return request.app.state.sources

    @routes.get("/health")
    async def health():
        return {"status": "alive"}

    @routes.get("/ready", dependencies=[Depends(owner)])
    async def ready(request: Request):
        try:
            await request.app.state.readiness.check()
        except Exception as exc:
            raise HTTPException(
                503, f"Not ready ({type(exc).__name__}); check database, Redis and workers"
            ) from None
        return {
            "status": "ready",
            "provider": "openai",
            "models": settings.model_allocation,
            "connectivity_verified": False,
        }

    @routes.get("/models", dependencies=[Depends(owner)])
    async def models():
        return {
            "provider": "openai",
            "allocation": settings.model_allocation,
            "policies": {name: policy.model_dump() for name, policy in settings.model_policies.items()},
            "connectivity_max_cost_usd": settings.connectivity_max_cost_usd,
        }

    @routes.post("/models/connectivity", dependencies=[Depends(owner)])
    async def connectivity(body: ConnectivityRequest, request: Request):
        return await request.app.state.model_access.test(body.model, provider_factory)

    @routes.get("/workspaces", response_model=WorkspacesView)
    async def workspaces(user: str = Depends(owner), service=Depends(sources)):
        records = await service.list(user)
        return {
            "items": [{"id": key, "name": key, "kind": "registered"} for key in sorted(settings.workspaces)]
            + [
                {
                    "id": source["id"],
                    "name": source["location"] + " @ " + source["revision"][:12],
                    "kind": source["kind"],
                }
                for source in records
                if source["status"] == "READY"
            ],
            "execution_enabled": False,
            "patch_application_enabled": False,
            "local_roots": list(settings.local_repository_roots),
            "git_hosts": settings.repository_git_hosts,
        }

    @routes.get("/repositories", response_model=list[RepositoryView])
    async def repositories(user: str = Depends(owner), service=Depends(sources)):
        return await service.list(user)

    @routes.post("/repositories", response_model=RepositoryView, status_code=201)
    async def prepare(body: RepositoryRequest, user: str = Depends(owner), service=Depends(sources)):
        return await service.prepare(body.location, body.ref, user)

    @routes.delete("/repositories/{source_id}")
    async def remove(source_id: str, user: str = Depends(owner), service=Depends(sources)):
        return await service.remove(source_id, user)

    @routes.post("/jobs", response_model=JobCreated, status_code=202)
    async def start(
        body: JobRequest,
        user: str = Depends(owner),
        service=Depends(reviews),
        idempotency_key: str | None = Header(default=None),
    ):
        brief = ReviewBrief(
            body.objective,
            body.workspace_id,
            body.mode,
            body.fixed_agent_count,
            body.allow_patch_proposals,
            body.model_overrides,
        )
        return await service.start(brief, user, idempotency_key)

    @routes.get("/jobs", response_model=Page)
    async def listing(
        user: str = Depends(owner),
        service=Depends(reviews),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        return await service.list(user, offset, limit)

    @routes.get("/jobs/{job_id}", response_model=JobView)
    async def get(job_id: str, user: str = Depends(owner), service=Depends(reviews)):
        return await service.get(job_id, user)

    @routes.post("/jobs/{job_id}/cancel", response_model=JobCreated)
    async def cancel(job_id: str, user: str = Depends(owner), service=Depends(reviews)):
        return await service.cancel(job_id, user)

    @routes.get("/jobs/{job_id}/agents", response_model=list[AgentView])
    async def agents(job_id: str, user: str = Depends(owner), service=Depends(reviews)):
        return (await service.get(job_id, user))["agents"]

    @routes.get("/jobs/{job_id}/agents/{agent_id}", response_model=AgentView)
    async def agent(job_id: str, agent_id: str, user: str = Depends(owner), service=Depends(reviews)):
        return await service.agent(job_id, agent_id, user)

    @routes.get("/jobs/{job_id}/agents/{agent_id}/steps", response_model=Page)
    async def steps(
        job_id: str,
        agent_id: str,
        user: str = Depends(owner),
        service=Depends(reviews),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ):
        return await service.steps(job_id, agent_id, user, offset, limit)

    @routes.get("/jobs/{job_id}/results")
    async def results(job_id: str, user: str = Depends(owner), service=Depends(reviews)):
        return await service.results(job_id, user)

    @routes.get("/jobs/{job_id}/artifacts", response_model=Page)
    async def patches(
        job_id: str,
        user: str = Depends(owner),
        service=Depends(reviews),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        return await service.patches(job_id, user, offset, limit)

    @routes.get("/jobs/{job_id}/history", response_model=list[EventView])
    async def history(
        job_id: str,
        user: str = Depends(owner),
        service=Depends(reviews),
        after: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=500),
        latest: bool = False,
    ):
        return await service.history(job_id, user, after, limit, latest)

    @routes.get("/jobs/{job_id}/events")
    async def events(
        job_id: str,
        request: Request,
        user: str = Depends(owner),
        service=Depends(reviews),
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(default=None),
    ):
        await service.get(job_id, user)
        try:
            cursor = max(after, int(last_event_id or "0"))
            if cursor < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "Last-Event-ID must be a nonnegative event ID") from None

        async def stream():
            nonlocal cursor
            yield "retry: 1500\n\n"
            yield "event: snapshot\ndata: " + json.dumps(await service.get(job_id, user)) + "\n\n"
            while not await request.is_disconnected():
                batch = await service.history(job_id, user, cursor)
                for item in batch:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: update\ndata: {json.dumps(item)}\n\n"
                if len(batch) == 200:
                    continue
                data = await service.get(job_id, user)
                if data["status"] != "RUNNING":
                    yield "event: snapshot\ndata: " + json.dumps(data) + "\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(settings.poll_seconds)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    return routes
