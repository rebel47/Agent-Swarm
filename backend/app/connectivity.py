"""Explicit billable OpenAI model/function-calling connectivity check."""

import argparse
import asyncio
import json

from .config import Settings
from .llm import ProviderError, RealProvider
from .store import usage_cost


async def run(model):
    settings = Settings()
    provider = RealProvider(settings)
    try:
        selected = model or settings.orchestrator_model
        reply = await provider.connectivity(selected)
        print(
            json.dumps(
                {
                    "connected": True,
                    "tool_calling": True,
                    "model": selected,
                    "reported_model": reply.reported_model,
                    "response_id": reply.response_id,
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                    "usage_details": reply.usage_details,
                    "estimated_cost_usd": usage_cost(
                        settings.policy(selected),
                        reply.input_tokens,
                        reply.output_tokens,
                        reply.usage_details,
                    ),
                },
                indent=2,
            )
        )
    except ProviderError as exc:
        print(
            json.dumps(
                {
                    "connected": False,
                    "code": exc.code,
                    "message": str(exc),
                    "status": exc.status,
                    "request_id": exc.request_id,
                    "model": selected,
                },
                indent=2,
            )
        )
        raise SystemExit(1) from None
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Allowlisted OpenAI model; defaults to ORCHESTRATOR_MODEL")
    args = parser.parse_args()
    asyncio.run(run(args.model))
