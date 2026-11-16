import asyncio
import logging
import signal
import time
import uuid


from .broker import Broker
from .config import Settings
from .database import Database
from .llm import RealProvider
from .models import Agent, Job
from .observability import configure
from .runtime import Runtime
from .store import Claim, Store

logger = logging.getLogger("swarm.worker")


class Worker:
    def __init__(self, store: Store, runtime: Runtime, broker: Broker | None = None):
        self.store, self.runtime = store, runtime
        self.broker = broker or Broker(store.settings.redis_url)
        self.id = uuid.uuid4().hex
        self.stopping = asyncio.Event()
        self.active: dict[asyncio.Task, Claim] = {}

    async def release(self, claim):
        async with self.store.db.locked(claim.job_id) as (session, job):
            agent = await session.get(Agent, claim.agent_id) if claim.agent_id else None
            if not self.store.valid_claim(job, agent, claim):
                return
            target = agent or job
            target.lease_owner, target.lease_until = None, None
            if agent:
                self.store.transition(session, job, agent, "QUEUED", {"reason": "worker_shutdown"})
            self.store.event(session, job, "worker.released", {"reason": "graceful_shutdown"}, claim.agent_id)

    async def reap(self):
        for task, claim in list(self.active.items()):
            if task.done():
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass  # Cancellation already persisted by API or graceful release.
                except Exception as exc:
                    logger.error(
                        "Turn infrastructure failure (%s); lease recovery will retry", type(exc).__name__
                    )
                del self.active[task]
                continue
            async with self.store.db.sessions() as session:
                job = await session.get(Job, claim.job_id)
                agent = await session.get(Agent, claim.agent_id) if claim.agent_id else None
                if not self.store.valid_claim(job, agent, claim):
                    task.cancel()

    async def run(self):
        last_heartbeat = 0
        try:
            while not self.stopping.is_set():
                await self.reap()
                if time.time() - last_heartbeat > 5:
                    await self.store.heartbeat(self.id)
                    last_heartbeat = time.time()
                for _ in range(self.store.settings.worker_slots - len(self.active)):
                    claim = await self.store.claim(self.id)
                    if not claim:
                        break
                    task = asyncio.create_task(self.runtime.execute(claim))
                    self.active[task] = claim
                if self.active:
                    try:
                        await asyncio.wait_for(self.stopping.wait(), self.store.settings.poll_seconds)
                    except TimeoutError:
                        pass
                else:
                    await self.broker.wait(self.store.settings.poll_seconds)
        finally:
            for task in self.active:
                task.cancel()
            await asyncio.gather(*self.active, return_exceptions=True)
            for claim in self.active.values():
                await self.release(claim)
            await self.broker.close()


async def main():
    settings = Settings()
    settings.validate_runtime()
    configure(settings.otel_exporter_otlp_endpoint)
    provider = RealProvider(settings)
    database = Database(settings.database_url)
    await database.ping()
    await database.check_schema()
    await database.ensure_user(settings.tenant_id)
    store = Store(database, settings)
    worker = Worker(store, Runtime(store, provider))
    await worker.broker.ping()
    from pathlib import Path
    import tempfile

    await asyncio.to_thread((Path(tempfile.gettempdir()) / "swarm-worker-id").write_text, worker.id)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stopping.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(worker.stopping.set))
    try:
        await worker.run()
    finally:
        await provider.close()
        await database.close()


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
