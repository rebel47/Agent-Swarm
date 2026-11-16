import time
from sqlalchemy import func, select

from ..application.errors import ConnectivityFailure
from ..domain.budgets import usage_cost
from .models import WorkerHeartbeat
from .openai_provider import ProviderError


class Readiness:
    def __init__(self, database, queue, lease_seconds):
        self.database, self.queue, self.lease_seconds = database, queue, lease_seconds

    async def check(self):
        await self.database.ping()
        await self.queue.ping()
        async with self.database.sessions() as session:
            recent = await session.scalar(select(func.max(WorkerHeartbeat.updated_at)))
        if not recent or time.time() - recent > self.lease_seconds:
            raise ValueError("No recent worker heartbeat")


class ModelAccess:
    def __init__(self, settings):
        self.settings = settings

    async def test(self, model, factory):
        provider = factory(self.settings)
        try:
            reply = await provider.connectivity(model)
            return {
                "model": model,
                "reported_model": reply.reported_model,
                "connected": True,
                "tool_calling": True,
                "response_id": reply.response_id,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "usage_details": reply.usage_details,
                "estimated_cost_usd": usage_cost(
                    self.settings.policy(model), reply.input_tokens, reply.output_tokens, reply.usage_details
                ),
            }
        except ProviderError as exc:
            raise ConnectivityFailure(
                502,
                {
                    "code": exc.code,
                    "message": str(exc),
                    "status": exc.status,
                    "request_id": exc.request_id,
                    "model": model,
                    "retryable": exc.retryable,
                },
            ) from None
        except ValueError as exc:
            raise ConnectivityFailure(400, str(exc)) from None
        finally:
            await provider.close()
