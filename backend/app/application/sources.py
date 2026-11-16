import asyncio

from ..domain.errors import RepositoryError
from .ports import SourcePreparer, SourceRepository


class SourceService:
    def __init__(self, repository: SourceRepository, preparer: SourcePreparer):
        self.repository, self.preparer = repository, preparer
        self.tasks: set[asyncio.Task] = set()

    async def list(self, owner: str):
        return await self.repository.list(owner)

    async def prepare(self, location: str, ref: str | None, owner: str):
        record = await self.repository.admit(location, ref, owner)
        task = asyncio.create_task(self._prepare(record))
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return await asyncio.shield(task)

    def _done(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _prepare(self, record):
        try:
            info = await self.preparer.prepare(record)
            return await self.repository.finish(record["id"], info=info)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, RepositoryError)
                else RepositoryError(
                    "Repository could not be prepared; check server storage and retry",
                    "repository_preparation_failed",
                    500,
                )
            )
            await self.repository.finish(record["id"], error={"code": error.code, "message": str(error)})
            raise error from None

    async def remove(self, source_id: str, owner: str):
        await self.repository.remove(source_id, owner)
        return {"id": source_id, "status": "DELETED"}

    async def close(self):
        await asyncio.gather(*self.tasks, return_exceptions=True)
