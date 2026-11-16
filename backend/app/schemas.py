from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_CHILDREN = "WAITING_FOR_CHILDREN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
ACTIVE = {"CREATED", "QUEUED", "RUNNING", "WAITING_FOR_CHILDREN"}


class AgentSpec(StrictModel):
    task_key: str = Field(min_length=1, max_length=100)
    parent_agent_id: str | None = None
    role: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=5, max_length=4000)
    system_instructions: str = Field(min_length=5, max_length=6000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=20)
    model: str | None = None
    model_purpose: Literal["routine", "complex", "verification"] = "routine"
    model_reason: str = Field(default="", max_length=2000)
    max_steps: int = Field(default=20, ge=1)
    token_budget: int = Field(default=64000, ge=100)
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    success_criteria: list[str] = Field(default_factory=list, max_length=20)
    expected_output_schema: dict[str, Any] | None = None


class Evidence(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=1500)
    symbol: str | None = None

    @model_validator(mode="after")
    def lines(self):
        if self.end_line < self.start_line or self.end_line - self.start_line > 100:
            raise ValueError("Evidence line range must be ordered and at most 101 lines")
        return self


class Finding(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    severity: Literal["info", "low", "medium", "high", "critical"]
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    verification: Literal["source_observed", "test_verified", "uncertain"] = "source_observed"
    uncertainty: str = Field(default="", max_length=2000)


class AgentResult(StrictModel):
    summary: str = Field(min_length=1, max_length=12000)
    findings: list[Finding] = Field(default_factory=list, max_length=50)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=30)
    output: dict[str, Any] | None = None
    proposed_patch: str | None = Field(default=None, max_length=60000)


class SupervisorDecision(StrictModel):
    action: Literal[
        "EXECUTE_DIRECTLY",
        "CREATE_TASKS",
        "SPAWN_AGENTS",
        "WAIT_FOR_RESULTS",
        "REQUEST_VERIFICATION",
        "REPLAN",
        "CANCEL_AGENT",
        "SYNTHESIZE_RESULTS",
        "FINISH",
    ]
    reason: str = Field(min_length=5, max_length=2000)
    expected_benefit: str = Field(min_length=3, max_length=2000)
    agents: list[AgentSpec] = Field(default_factory=list, max_length=100)
    cancel_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    report: AgentResult | None = None


class SubagentRequest(StrictModel):
    reason: str = Field(min_length=5, max_length=2000)
    expected_benefit: str = Field(min_length=3, max_length=2000)
    agents: list[AgentSpec] = Field(min_length=1, max_length=100)


class ModelEscalationRequest(StrictModel):
    purpose: Literal["complex", "verification"]
    reason: str = Field(min_length=10, max_length=2000)
    expected_benefit: str = Field(min_length=10, max_length=2000)


class ContextSummary(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=20)
    evidence_references: list[str] = Field(default_factory=list, max_length=30)


class ConnectivityRequest(StrictModel):
    model: str = Field(min_length=1, max_length=200)


class RepositoryRequest(StrictModel):
    location: str = Field(min_length=1, max_length=2000)
    ref: str | None = Field(default=None, min_length=1, max_length=200)


class RepositoryView(BaseModel):
    id: str
    kind: str
    location: str
    ref: str | None
    revision: str | None
    status: str
    file_count: int
    size_bytes: int
    error: dict[str, Any] | None
    created_at: float


class ToolCall(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(StrictModel):
    call: ToolCall | None = None
    result: AgentResult | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.call is None) == (self.result is None):
            raise ValueError("Return exactly one tool call or final result")
        return self


class JobRequest(StrictModel):
    objective: str = Field(min_length=5, max_length=8000)
    workspace_id: str = Field(min_length=1, max_length=100)
    mode: Literal["single", "fixed", "adaptive"] = "adaptive"
    fixed_agent_count: int | None = Field(default=None, ge=1, le=10000)
    allow_patch_proposals: bool = False
    model_overrides: dict[Literal["orchestrator", "routine", "verification", "synthesis"], str] = Field(
        default_factory=dict
    )


class JobCreated(BaseModel):
    id: str
    status: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AgentView(BaseModel):
    id: str
    task_id: str
    parent_agent_id: str | None
    role: str
    objective: str
    status: str
    depth: int
    allowed_tools: list[str]
    model: str
    model_purpose: str = "routine"
    model_reason: str = ""
    steps: int
    tokens: int
    cost_usd: float
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    dependencies: list[str]
    created_at: float
    started_at: float | None
    ended_at: float | None


class JobView(BaseModel):
    id: str
    objective: str
    workspace_id: str
    repository: RepositoryView | None = None
    mode: str
    status: str
    created_at: float
    updated_at: float
    ended_at: float | None
    report: dict[str, Any] | None
    error: dict[str, Any] | None
    trace_id: str
    supervisor_steps: int
    metrics: dict[str, Any]
    agents: list[AgentView]


class EventView(BaseModel):
    id: int
    type: str
    agent_id: str | None
    created_at: float
    data: dict[str, Any]


class Page(BaseModel):
    items: list[dict[str, Any]]
    offset: int
    limit: int


class WorkspacesView(BaseModel):
    items: list[dict[str, str]]
    execution_enabled: bool = False
    patch_application_enabled: bool = False
    local_roots: list[str] = Field(default_factory=list)
    git_hosts: list[str] = Field(default_factory=list)
