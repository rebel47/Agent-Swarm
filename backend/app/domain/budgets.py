"""Budget admission and usage pricing are independent of persistence and providers."""

from dataclasses import dataclass
from typing import Protocol

from .errors import AgentBudgetExhausted, BudgetExhausted, Rejected


class Pricing(Protocol):
    input_per_million: float
    output_per_million: float
    cache_write_multiplier: float
    cached_input_per_million: float | None


@dataclass(frozen=True)
class InferenceCharge:
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def tokens(self):
        return self.input_tokens + self.output_tokens

    @classmethod
    def estimate(cls, inp: int, out: int, pricing: Pricing):
        return cls(
            inp,
            out,
            (
                inp * pricing.input_per_million * pricing.cache_write_multiplier
                + out * pricing.output_per_million
            )
            / 1e6,
        )


@dataclass(frozen=True)
class BudgetAccount:
    token_limit: int
    used_tokens: int
    reserved_tokens: int
    cost_limit: float
    used_cost: float
    reserved_cost: float

    def authorize(self, charge: InferenceCharge, context_limit: int, agent_remaining: int | None = None):
        if min(charge.input_tokens, charge.output_tokens, charge.cost_usd) < 0:
            raise Rejected("Inference reservations cannot be negative")
        if charge.tokens > context_limit:
            raise Rejected("Context exceeds configured model capability; reduce context/output limits")
        if self.used_tokens + self.reserved_tokens + charge.tokens > self.token_limit:
            raise BudgetExhausted("Job token budget exhausted")
        if self.used_cost + self.reserved_cost + charge.cost_usd > self.cost_limit:
            raise BudgetExhausted("Job estimated cost budget exhausted")
        if agent_remaining is not None and charge.tokens > agent_remaining:
            raise AgentBudgetExhausted("Agent token budget exhausted; supervisor may replan")


def usage_cost(policy: Pricing, inp: int, out: int, details=None):
    details = details or {}
    cached, writes = details.get("cached_tokens", 0), details.get("cache_write_tokens", 0)
    long_writes = (details.get("cache_write_tokens_details", {}) or {}).get("ttl_12h_tokens", 0) or 0
    short_writes = writes - long_writes
    if min(inp, out, cached, writes, short_writes, long_writes) < 0 or cached + writes > inp:
        raise ValueError("Invalid OpenAI cache usage")
    cached_rate = policy.cached_input_per_million
    return (
        (inp - cached - writes) * policy.input_per_million
        + cached * (cached_rate if cached_rate is not None else policy.input_per_million)
        + short_writes * policy.input_per_million * policy.cache_write_multiplier
        + long_writes * policy.input_per_million * max(2.5, policy.cache_write_multiplier)
        + out * policy.output_per_million
    ) / 1e6
