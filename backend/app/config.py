"""Environment-driven configuration. No production mock provider exists."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    input_per_million: float = Field(gt=0)
    output_per_million: float = Field(gt=0)
    cached_input_per_million: float | None = Field(default=None, ge=0)
    cache_write_multiplier: float = Field(default=1, ge=1)
    prompt_caching: Literal["automatic", "explicit", "disabled"] = "automatic"
    reasoning_efforts: list[str] = Field(
        default_factory=lambda: ["none", "low", "medium", "high", "xhigh", "max"]
    )
    context_tokens: int = Field(default=32000, ge=1024, le=272000)
    max_output_tokens: int = Field(default=4096, ge=128)
    tool_calling: bool = True
    streaming: bool = True

    @model_validator(mode="after")
    def capacity(self):
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("Model output limit must be smaller than context capacity")
        if self.prompt_caching == "explicit" and self.cache_write_multiplier < 1.25:
            raise ValueError("Explicit 30m caching requires a cache write multiplier of at least 1.25")
        if (
            self.cached_input_per_million is not None
            and self.cached_input_per_million > self.input_per_million * self.cache_write_multiplier
        ):
            raise ValueError("Cached input rate must not exceed the reservation input rate")
        return self


# Standard short-context prices verified against the OpenAI pricing page, 2026-11-16.
# The deliberately smaller runtime context cap keeps reservations below long-context pricing.
DEFAULT_ORCHESTRATOR_MODEL = "gpt-6-sol"
DEFAULT_SUBAGENT_MODEL = "gpt-6-luna"


def default_policies():
    return {
        DEFAULT_ORCHESTRATOR_MODEL: ModelPolicy(
            input_per_million=2,
            output_per_million=10,
            cached_input_per_million=0.2,
            context_tokens=64000,
            prompt_caching="explicit",
            cache_write_multiplier=1.25,
        ),
        DEFAULT_SUBAGENT_MODEL: ModelPolicy(
            input_per_million=0.1,
            output_per_million=0.5,
            cached_input_per_million=0.01,
            context_tokens=64000,
            prompt_caching="explicit",
            cache_write_multiplier=1.25,
        ),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore", case_sensitive=False, validate_assignment=True
    )
    environment: Literal["development", "production", "test"] = "development"
    database_url: str = ""
    redis_url: str = ""
    api_token: SecretStr = SecretStr("")
    tenant_id: str = "default"
    orchestrator_model: str = DEFAULT_ORCHESTRATOR_MODEL
    subagent_model: str = DEFAULT_SUBAGENT_MODEL
    verification_model: str = DEFAULT_ORCHESTRATOR_MODEL
    synthesis_model: str = DEFAULT_ORCHESTRATOR_MODEL
    openai_api_key: SecretStr = SecretStr("")
    model_policies: dict[str, ModelPolicy] = Field(default_factory=default_policies)
    orchestrator_reasoning_effort: str = "medium"
    subagent_reasoning_effort: str = "low"
    verification_reasoning_effort: str = "high"
    synthesis_reasoning_effort: str = "medium"
    enable_context_summarization: bool = True
    summary_trigger_chars: int = Field(default=16000, ge=2000)
    connectivity_max_cost_usd: float = Field(default=0.1, gt=0)
    workspaces: dict[str, str] = Field(default_factory=dict)
    local_repository_roots: dict[str, str] = Field(default_factory=dict)
    repository_cache_dir: str = str(REPO_ROOT / "repository-cache")
    repository_git_hosts: list[str] = Field(
        default_factory=lambda: ["github.com", "gitlab.com", "bitbucket.org"]
    )
    max_repository_bytes: int = Field(default=52428800, ge=1024)
    max_repository_snapshots: int = Field(default=20, ge=1)
    max_repository_preparations: int = Field(default=2, ge=1)
    repository_prepare_seconds: int = Field(default=120, ge=5)
    cors_origins: str = "http://localhost:3000"
    max_total_agents: int = Field(default=100, ge=1, le=10000)
    max_concurrent_agents: int = Field(default=10, ge=1)
    max_agent_depth: int = Field(default=5, ge=0, le=30)
    shared_agent_budget: bool = True
    max_total_tokens: int = Field(default=100000000, ge=100)
    max_total_cost_usd: float = Field(default=1000, gt=0)
    max_agent_steps: int = Field(default=200, ge=1)
    max_supervisor_steps: int = Field(default=400, ge=1)
    max_agent_tokens: int = Field(default=5000000, ge=100)
    max_active_jobs: int = Field(default=20, ge=1)
    max_job_seconds: int = Field(default=21600, ge=1)
    request_timeout_seconds: float = Field(default=90, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    worker_slots: int = Field(default=10, ge=1)
    lease_seconds: int = Field(default=180, ge=10)
    poll_seconds: float = Field(default=1, gt=0)
    max_tool_output_chars: int = Field(default=16000, ge=100)
    max_file_bytes: int = Field(default=262144, ge=100)
    max_repository_files: int = Field(default=2000, ge=1)
    allow_git_history: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    fixed_agent_count: int = Field(default=3, ge=1)
    stream_llm: bool = False

    @model_validator(mode="after")
    def invariants(self):
        if self.lease_seconds <= self.request_timeout_seconds:
            raise ValueError("LEASE_SECONDS must exceed REQUEST_TIMEOUT_SECONDS")
        return self

    def validate_runtime(self) -> None:
        errors = []
        if self.environment != "test" and not self.database_url.startswith("postgresql+psycopg://"):
            errors.append("DATABASE_URL must use postgresql+psycopg://")
        if not self.database_url:
            errors.append("DATABASE_URL is required")
        if self.environment != "test" and not self.redis_url:
            errors.append("REDIS_URL is required")
        if len(self.api_token.get_secret_value()) < 32:
            errors.append("API_TOKEN must contain at least 32 characters")
        if self.api_token.get_secret_value().startswith("replace-"):
            errors.append("Generate a random API_TOKEN; example placeholder tokens are rejected")
        if not self.openai_api_key.get_secret_value():
            errors.append("OPENAI_API_KEY is required")
        for purpose, model in self.model_allocation.items():
            try:
                policy = self.policy(model)
                effort = self.effort(purpose)
                if effort and effort not in policy.reasoning_efforts:
                    errors.append(f"Unsupported {purpose} reasoning effort {effort!r} for {model!r}")
            except ValueError as exc:
                errors.append(f"MODEL_POLICIES must include pricing and capabilities: {exc}")
        for alias, path in self.workspaces.items():
            if not alias or not Path(path).is_absolute() or not Path(path).is_dir():
                errors.append(f"WORKSPACES contains an invalid directory for alias {alias!r}")
        for alias, path in self.local_repository_roots.items():
            if not alias or not Path(path).is_absolute() or not Path(path).is_dir():
                errors.append(f"LOCAL_REPOSITORY_ROOTS contains an invalid directory for {alias!r}")
        if not Path(self.repository_cache_dir).is_absolute():
            errors.append("REPOSITORY_CACHE_DIR must be absolute")
        if errors:
            raise ValueError("Configuration error: " + "; ".join(errors))

    @property
    def model_allocation(self) -> dict[str, str]:
        return {
            "orchestrator": self.orchestrator_model,
            "routine": self.subagent_model,
            "complex": self.orchestrator_model,
            "verification": self.verification_model,
            "synthesis": self.synthesis_model,
            "summary": self.subagent_model,
        }

    def effort(self, purpose: str) -> str:
        key = {"routine": "subagent", "summary": "subagent", "complex": "orchestrator"}.get(purpose, purpose)
        return getattr(self, f"{key}_reasoning_effort")

    def allocate(
        self, purpose: str, model: str | None = None, reason: str = "", routine_model: str | None = None
    ) -> str:
        selected = model or self.model_allocation[purpose]
        self.policy(selected)
        if (
            selected != (routine_model or self.subagent_model)
            and purpose in {"routine", "complex", "verification"}
            and len(reason.strip()) < 10
        ):
            raise ValueError("A substantive allocation reason is required for a stronger agent model")
        effort = self.effort(purpose)
        if effort and effort not in self.policy(selected).reasoning_efforts:
            raise ValueError(f"Unsupported reasoning effort {effort!r} for {selected!r}")
        return selected

    def policy(self, model: str | None = None) -> ModelPolicy:
        name = model or self.subagent_model
        if name not in self.model_policies:
            raise ValueError(f"Model {name!r} is not in the administrator's MODEL_POLICIES allowlist")
        policy = self.model_policies[name]
        if not policy.tool_calling:
            raise ValueError(f"Model {name!r} must support tool calling")
        return policy
