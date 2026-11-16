"""SQL read models and adapters for the application repository ports."""

import asyncio
from sqlalchemy import select

from ..domain.investigations import ReviewBrief
from ..domain.errors import Rejected
from ..schemas import JobRequest, RepositoryRequest
from .models import Artifact, Job, ToolExecution
from .persistence import Store
from .source_import import RepositoryImporter


class SqlInvestigations:
    def __init__(self, store: Store):
        self.store = store

    async def create(self, brief: ReviewBrief, owner, key):
        request = JobRequest(
            objective=brief.objective,
            workspace_id=brief.repository_id,
            mode=brief.mode,
            fixed_agent_count=brief.fixed_agent_count,
            allow_patch_proposals=brief.allow_patch_proposals,
            model_overrides=brief.model_overrides,
        )
        try:
            return await self.store.create_job(request, owner, key)
        except ValueError as exc:
            raise Rejected(str(exc)) from None

    async def get(self, job_id, owner):
        return await self.store.snapshot(job_id, owner)

    async def cancel(self, job_id, owner):
        await self.store.cancel(job_id, owner)

    async def list(self, owner, offset, limit):
        async with self.store.db.sessions() as session:
            rows = await session.scalars(
                select(Job)
                .where(Job.owner_id == owner)
                .order_by(Job.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [
                    {
                        "id": row.id,
                        "objective": row.objective,
                        "workspace_id": row.workspace_id,
                        "status": row.status,
                        "created_at": row.created_at,
                    }
                    for row in rows
                ],
                "offset": offset,
                "limit": limit,
            }

    async def steps(self, job_id, agent_id, offset, limit):
        async with self.store.db.sessions() as session:
            rows = await session.scalars(
                select(ToolExecution)
                .where(ToolExecution.job_id == job_id, ToolExecution.agent_id == agent_id)
                .order_by(ToolExecution.created_at)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "arguments": row.arguments,
                        "output": row.output,
                        "created_at": row.created_at,
                    }
                    for row in rows
                ],
                "offset": offset,
                "limit": limit,
            }

    async def patches(self, job_id, offset, limit):
        async with self.store.db.sessions() as session:
            rows = await session.scalars(
                select(Artifact)
                .where(Artifact.job_id == job_id, Artifact.kind == "patch_proposal")
                .order_by(Artifact.created_at)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [
                    {"id": row.id, "agent_id": row.agent_id, "kind": row.kind, **row.content} for row in rows
                ],
                "offset": offset,
                "limit": limit,
            }

    async def events(self, job_id, after=0, limit=200, latest=False):
        return await self.store.events(job_id, after, limit, latest)


class SqlSources:
    def __init__(self, store: Store):
        self.store = store

    async def list(self, owner):
        return await self.store.repository_sources(owner)

    async def admit(self, location, ref, owner):
        return await self.store.admit_repository(RepositoryRequest(location=location, ref=ref), owner)

    async def finish(self, source_id, info=None, error=None):
        return await self.store.finish_repository(source_id, info, error)

    async def remove(self, source_id, owner):
        await self.store.delete_repository(source_id, owner)


class SnapshotPreparer:
    def __init__(self, importer: RepositoryImporter):
        self.importer = importer

    async def prepare(self, record):
        return await asyncio.to_thread(self.importer.prepare, record["id"], record)
