import asyncio
import time
from pathlib import Path

from .config import Settings
from .database import Database
from .models import WorkerHeartbeat


async def check():
    database = Database(Settings().database_url)
    try:
        async with database.sessions() as session:
            worker_id = (await asyncio.to_thread(Path("/tmp/swarm-worker-id").read_text)).strip()
            heartbeat = await session.get(WorkerHeartbeat, worker_id)
            if not heartbeat or time.time() - heartbeat.updated_at > 30:
                raise SystemExit(1)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(check())
