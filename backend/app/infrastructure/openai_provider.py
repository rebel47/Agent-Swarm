"""OpenAI Responses transport. All network inference is explicit and budgeted by the caller."""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from ..config import Settings
from ..observability import redact
from ..schemas import AgentResult, AgentTurn, ContextSummary, SupervisorDecision, ToolCall

OPENAI_API_URL = "https://api.openai.com/v1"


class ProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        status: int | None = None,
        request_id: str | None = None,
        diagnostics: dict | None = None,
    ):
        super().__init__(message)
        self.code, self.retryable, self.status, self.request_id = code, retryable, status, request_id
        self.diagnostics = diagnostics or {}


@dataclass
class Reply:
    payload: Any
    input_tokens: int
    output_tokens: int
    usage_details: dict = field(default_factory=dict)
    response_id: str | None = None
    reported_model: str | None = None


class Provider(Protocol):
    async def count_input_tokens(
        self, messages: list[dict], tools: list[dict], model: str, purpose: str, choice="required"
    ) -> int: ...
    async def decide(self, messages: list[dict], model: str) -> Reply: ...
    async def act(
        self, messages: list[dict], tools: list[dict], model: str, purpose: str = "routine"
    ) -> Reply: ...
    async def structured(self, messages: list[dict], schema: type, model: str, purpose: str) -> Reply: ...


def messages(system: str, context: str) -> list[dict]:
    return [{"role": "developer", "content": system}, {"role": "user", "content": context}]


def structured_tool(schema: type) -> dict:
    return {
        "name": schema.__name__,
        "description": "Return the requested structured result.",
        "parameters": schema.model_json_schema(),
    }


def result_tool() -> dict:
    return {
        "name": "submit_result",
        "description": "Finish with evidence-backed results. Pass summary, findings and other "
        "AgentResult fields directly as arguments; do not wrap them in a result object.",
        "parameters": AgentResult.model_json_schema(),
    }


class RealProvider:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        settings.validate_runtime()
        self.settings = settings
        # Pin the official endpoint, including when OPENAI_BASE_URL exists in the process.
        self.client = client or AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=OPENAI_API_URL,
            max_retries=0,
            timeout=settings.request_timeout_seconds,
        )

    async def close(self):
        await self.client.close()

    @staticmethod
    def usage(raw) -> tuple[int, int, dict]:
        usage = raw.usage
        if not usage:
            raise ProviderError(
                "usage_missing",
                "OpenAI did not report token usage; the reservation is conservatively charged",
            )
        details = usage.input_tokens_details.model_dump() if usage.input_tokens_details else {}
        output = usage.output_tokens_details.model_dump() if usage.output_tokens_details else {}
        inp, out = usage.input_tokens, usage.output_tokens
        cached, writes = details.get("cached_tokens", 0) or 0, details.get("cache_write_tokens", 0) or 0
        reasoning = output.get("reasoning_tokens", 0) or 0
        if (
            min(inp, out, cached, writes, reasoning) < 0
            or inp + out == 0
            or cached + writes > inp
            or reasoning > out
        ):
            raise ProviderError("usage_invalid", "OpenAI returned invalid token usage")
        return (
            inp,
            out,
            {
                "cached_tokens": cached,
                "cache_write_tokens": writes,
                "cache_write_tokens_details": details.get("cache_write_tokens_details") or {},
                "reasoning_tokens": reasoning,
            },
        )

    def request_params(self, items, tools, model, purpose, choice="required"):
        policy = self.settings.policy(model)
        effort = self.settings.effort(purpose)
        if effort and effort not in policy.reasoning_efforts:
            raise ProviderError(
                "reasoning_unsupported", f"Reasoning effort {effort!r} is not configured for {model!r}"
            )
        params = dict(
            model=model,
            input=items,
            tools=[{"type": "function", "strict": False, **t} for t in tools],
            tool_choice=choice,
            parallel_tool_calls=False,
            max_output_tokens=policy.max_output_tokens,
            store=False,
            truncation="disabled",
            service_tier="default",
        )
        if effort:
            params["reasoning"] = {"effort": effort}
        if policy.prompt_caching == "explicit":
            params["input"] = [dict(x) for x in items]
            static = params["input"][0]
            static["content"] = [
                {
                    "type": "input_text",
                    "text": static["content"],
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ]
            params["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}
        # Stable routing key contains no credentials or request-specific IDs.
        if policy.prompt_caching != "disabled":
            params["prompt_cache_key"] = hashlib.sha256(
                (self.settings.tenant_id + ":" + purpose + ":" + model).encode()
            ).hexdigest()
        return params

    def api_error(self, exc: APIStatusError) -> ProviderError:
        body = exc.body if isinstance(exc.body, dict) else {}
        body = body.get("error", body)
        code = str(body.get("code") or body.get("type") or type(exc).__name__)
        message = str(body.get("message") or exc.message)
        message = message.replace(self.settings.openai_api_key.get_secret_value(), "[REDACTED]")
        return ProviderError(
            code,
            redact(message)[:2000],
            exc.status_code in (408, 409, 429) or exc.status_code >= 500,
            exc.status_code,
            exc.request_id,
        )

    async def count_input_tokens(self, items, tools, model, purpose, choice="required"):
        params = self.request_params(items, tools, model, purpose, choice)
        # Count the same messages, function schemas, reasoning and choice sent to Responses.
        # This endpoint does not generate a completion. Reservation still gates generation.
        params = {
            key: value
            for key, value in params.items()
            if key
            in {"model", "input", "tools", "tool_choice", "parallel_tool_calls", "reasoning", "truncation"}
        }
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                count = await self.client.responses.input_tokens.count(**params)
            if type(count.input_tokens) is not int or count.input_tokens < 1:
                raise ProviderError("token_count_invalid", "OpenAI returned an invalid input token count")
            return count.input_tokens
        except APIStatusError as exc:
            raise self.api_error(exc) from None
        except (APIConnectionError, APITimeoutError, TimeoutError) as exc:
            raise ProviderError(
                type(exc).__name__, f"OpenAI token counting failed ({type(exc).__name__})", True
            ) from None

    async def invoke(self, items: list[dict], tools: list[dict], model: str, purpose: str, choice="required"):
        policy = self.settings.policy(model)
        params = self.request_params(items, tools, model, purpose, choice)
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                if self.settings.stream_llm and policy.streaming:
                    async with self.client.responses.stream(**params) as stream:
                        return await stream.get_final_response()
                return await self.client.responses.create(**params)
        except APIStatusError as exc:
            raise self.api_error(exc) from None
        except (APIConnectionError, APITimeoutError, TimeoutError) as exc:
            raise ProviderError(
                type(exc).__name__, f"OpenAI request failed ({type(exc).__name__})", True
            ) from None

    async def structured(self, items, schema, model, purpose):
        name = schema.__name__
        raw = await self.invoke(
            items,
            [structured_tool(schema)],
            model,
            purpose,
            {"type": "function", "name": name},
        )
        inp, out, details = self.usage(raw)
        try:
            calls = [x for x in raw.output if x.type == "function_call"]
            if raw.status != "completed" or len(calls) != 1 or calls[0].name != name:
                raise ValueError("Expected one completed structured tool call")
            payload = schema.model_validate_json(calls[0].arguments)
        except ValueError as exc:
            payload = self.invalid_response(raw, f"Invalid {name} structured output", exc)
        return Reply(payload, inp, out, details, raw.id, raw.model)

    async def decide(self, items, model):
        return await self.structured(items, SupervisorDecision, model, "orchestrator")

    async def act(self, items, tools, model, purpose="routine"):
        raw = await self.invoke(items, [*tools, result_tool()], model, purpose)
        inp, out, details = self.usage(raw)
        try:
            calls = [x for x in raw.output if x.type == "function_call"]
            if raw.status != "completed" or len(calls) != 1:
                raise ValueError("Expected exactly one completed tool call")
            call = calls[0]
            if getattr(call, "status", "completed") != "completed":
                raise ValueError("Function call was not completed")
            if call.name not in {tool["name"] for tool in tools} | {"submit_result"}:
                raise ValueError("Function name was not among the offered tools")
            if call.name == "submit_result":
                payload = AgentTurn(result=AgentResult.model_validate_json(call.arguments))
            else:
                payload = AgentTurn(call=ToolCall(name=call.name, arguments=json.loads(call.arguments)))
        except ValueError as exc:
            payload = self.invalid_response(raw, "Expected exactly one valid tool call or submit_result", exc)
        return Reply(payload, inp, out, details, raw.id, raw.model)

    @staticmethod
    def invalid_response(raw, message, error):
        """Return billable usage alongside safe diagnostics, never raw arguments or source."""
        reason = getattr(getattr(raw, "incomplete_details", None), "reason", None)
        refused = any(
            getattr(part, "type", None) == "refusal"
            for item in raw.output
            for part in (getattr(item, "content", None) or [])
        )
        retryable = not refused and (raw.status == "completed" or reason == "max_output_tokens")
        payload = {
            "code": "response_refused"
            if refused
            else ("response_incomplete" if raw.status != "completed" else "invalid_tool_response"),
            "validation_error": message,
            "response_status": raw.status,
            "incomplete_reason": reason,
            "function_call_count": sum(item.type == "function_call" for item in raw.output),
            "response_id": raw.id,
            "reported_model": raw.model,
            "retryable": retryable,
        }
        if isinstance(error, ValidationError):
            payload["validation_errors"] = error.errors(
                include_input=False, include_context=False, include_url=False
            )[:10]
        elif isinstance(error, json.JSONDecodeError):
            payload["parse_error"] = {"type": "invalid_json", "line": error.lineno, "column": error.colno}
        else:
            payload["parse_error"] = {"type": "unexpected_call_shape", "message": str(error)[:200]}
        return payload

    async def connectivity(self, model: str):
        policy = self.settings.policy(model)
        # Include schemas and metadata in the conservative byte-to-token bound.
        bound = 12000
        estimated = (
            bound * policy.input_per_million * policy.cache_write_multiplier
            + policy.max_output_tokens * policy.output_per_million
        ) / 1e6
        if (
            bound + policy.max_output_tokens > policy.context_tokens
            or estimated > self.settings.connectivity_max_cost_usd
        ):
            raise ValueError("Connectivity test exceeds its configured token or cost allowance")
        reply = await self.structured(
            messages(
                "Connectivity test. Call ContextSummary with summary 'connected'.",
                "Return a minimal summary; no repository work or tools are requested.",
            ),
            ContextSummary,
            model,
            "summary",
        )
        if not isinstance(reply.payload, ContextSummary):
            raise ProviderError(
                "tool_calling_failed", "OpenAI response did not complete the required function call"
            )
        return reply
