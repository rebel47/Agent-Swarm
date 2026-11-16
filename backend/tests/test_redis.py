import os
import uuid

import pytest

from app.broker import Broker


@pytest.mark.asyncio
async def test_redis_wakeup_queue_integration():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to a disposable Redis instance")
    broker = Broker(url)
    try:
        await broker.ping()
        job_id = str(uuid.uuid4())
        await broker.wake(job_id)
        _, value = await broker.client.blpop("swarm:wake", timeout=1)
        assert value.decode() == job_id
    finally:
        await broker.close()
