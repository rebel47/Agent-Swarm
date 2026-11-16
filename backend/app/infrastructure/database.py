import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .models import Base, Job, RepositorySource, User


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def sqlite_pragmas(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        # Only used to emulate row-lock serialisation in SQLite tests.
        self.test_lock = asyncio.Lock() if url.startswith("sqlite") else None

    async def create_test_schema(self):
        if self.engine.dialect.name != "sqlite":
            raise RuntimeError("Production schemas must be created through Alembic")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def ensure_user(self, owner_id: str):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
        async with self.sessions.begin() as session:
            await session.execute(insert(User).values(id=owner_id, name=owner_id).on_conflict_do_nothing())

    @asynccontextmanager
    async def locked(self, job_id: str):
        if self.test_lock:
            await self.test_lock.acquire()
        try:
            async with self.sessions.begin() as session:
                job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if job is None:
                    raise LookupError("Job not found")
                yield session, job
        finally:
            if self.test_lock:
                self.test_lock.release()

    async def ping(self):
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))

    async def check_schema(self):
        try:
            async with self.sessions() as session:
                await session.execute(select(Job).limit(0))
                await session.execute(select(RepositorySource).limit(0))
        except Exception:
            raise RuntimeError("Database schema is unavailable; run alembic upgrade head") from None

    async def close(self):
        await self.engine.dispose()
