import json
import logging
import re

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_SECRET = re.compile(
    r"(?i)(?:sk-[\w-]{12,}|AKIA[A-Z0-9]{16}|(?:api[_-]?key|password|secret|token)"
    r"\s*[:=]\s*[\"']?[^\s,\"'}]{4,})"
)


def redact(text: str) -> str:
    text = re.sub(
        r"-----BEGIN .*?PRIVATE KEY-----[\s\S]*?-----END .*?PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text
    )
    return _SECRET.sub("[REDACTED]", text)


def sanitize(value):
    """Redact values without corrupting JSON escaping or schema field names."""
    sensitive = {
        "api_key",
        "password",
        "secret",
        "authorization",
        "access_token",
        "aws_secret_access_key",
        "aws_session_token",
    }
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.casefold() in sensitive else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {"level": record.levelname, "logger": record.name, "message": redact(record.getMessage())}
        )


def configure(endpoint: str | None = None):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger("swarm").handlers = [handler]
    logging.getLogger("swarm").setLevel(logging.INFO)
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": "agent-swarm"}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces"))
        )
        trace.set_tracer_provider(provider)


tracer = trace.get_tracer("agent-swarm")
