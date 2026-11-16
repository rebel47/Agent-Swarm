"""Public compatibility facade; adapters live in the infrastructure layer."""

from .infrastructure.openai_provider import (
    OPENAI_API_URL,
    ProviderError,
    Reply,
    Provider,
    RealProvider,
    messages,
    structured_tool,
    result_tool,
)

__all__ = [
    "OPENAI_API_URL",
    "ProviderError",
    "Reply",
    "Provider",
    "RealProvider",
    "messages",
    "structured_tool",
    "result_tool",
]
