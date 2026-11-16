"""Redis wakeup queue. Lost hints are recovered by PostgreSQL queue scans."""

import asyncio
import logging

from redis.asyncio import Redis

logger = logging.getLogger("swarm.broker")


class Broker:
    def __init__(self, url: str):
        self.client = Redis.from_url(url, socket_connect_timeout=3, socket_timeout=5) if url else None

    async def ping(self):
        if self.client:
            await self.client.ping()

    async def wake(self, job_id: str):
        if self.client:
            try:
                pipeline = self.client.pipeline()
                pipeline.rpush("swarm:wake", job_id)
                pipeline.ltrim("swarm:wake", -1000, -1)
                await pipeline.execute()
            except Exception as exc:
                logger.warning(
                    "Redis wake failed (%s); PostgreSQL scan will recover dispatch", type(exc).__name__
                )

    async def wait(self, seconds: float):
        if self.client:
            try:
                await self.client.blpop("swarm:wake", timeout=max(1, int(seconds)))
                return
            except Exception as exc:
                logger.warning("Redis unavailable (%s); polling durable queue", type(exc).__name__)
        await asyncio.sleep(seconds)

    async def close(self):
        if self.client:
            await self.client.aclose()
