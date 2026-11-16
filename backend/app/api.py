"""Composition root: constructs adapters and use cases, then mounts HTTP transport."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .application.errors import ConnectivityFailure
from .application.investigations import InvestigationService
from .application.sources import SourceService
from .config import Settings
from .domain.errors import Rejected, RepositoryError
from .infrastructure.database import Database
from .infrastructure.diagnostics import ModelAccess, Readiness
from .infrastructure.openai_provider import RealProvider
from .infrastructure.persistence import Store
from .infrastructure.queue import Broker
from .infrastructure.read_models import SnapshotPreparer, SqlInvestigations, SqlSources
from .infrastructure.source_import import RepositoryImporter
from .interfaces.http import router
from .observability import configure


def create_app(settings: Settings | None = None):
    s = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s.validate_runtime()
        configure(s.otel_exporter_otlp_endpoint)
        database, queue = Database(s.database_url), Broker(s.redis_url)
        state = Store(database, s)
        sources = SourceService(SqlSources(state), SnapshotPreparer(RepositoryImporter(s)))
        app.state.store, app.state.broker = state, queue
        app.state.sources, app.state.preparations = sources, sources.tasks
        app.state.reviews = InvestigationService(SqlInvestigations(state), queue)
        app.state.readiness = Readiness(database, queue, s.lease_seconds)
        app.state.model_access = ModelAccess(s)
        try:
            await database.ping()
            if s.environment == "test":
                await database.create_test_schema()
            await database.check_schema()
            await database.ensure_user(s.tenant_id)
            await queue.ping()
            yield
        finally:
            await sources.close()
            await queue.close()
            await database.close()

    app = FastAPI(title="Agent Swarm", version="1.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[value.strip() for value in s.cors_origins.split(",") if value.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.exception_handler(RepositoryError)
    async def source_error(request: Request, exc: RepositoryError):
        return JSONResponse(
            status_code=exc.status, content={"detail": {"code": exc.code, "message": str(exc)}}
        )

    @app.exception_handler(Rejected)
    async def rejected(request: Request, exc: Rejected):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LookupError)
    async def missing(request: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConnectivityFailure)
    async def connection_error(request: Request, exc: ConnectivityFailure):
        return JSONResponse(status_code=exc.status, content={"detail": exc.details})

    app.include_router(router(s, lambda configuration: RealProvider(configuration)))
    return app
