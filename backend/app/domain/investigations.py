from dataclasses import dataclass, field

from .errors import Rejected


@dataclass(frozen=True)
class ReviewBrief:
    objective: str
    repository_id: str
    mode: str = "adaptive"
    fixed_agent_count: int | None = None
    allow_patch_proposals: bool = False
    model_overrides: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not 5 <= len(self.objective.strip()) <= 8000 or not self.repository_id:
            raise Rejected("A review needs a repository and a clear objective")
        if self.mode not in {"adaptive", "single", "fixed"}:
            raise Rejected("Unknown investigation mode")
        if self.fixed_agent_count is not None and self.fixed_agent_count < 1:
            raise Rejected("A fixed team must contain at least one agent")


@dataclass(frozen=True)
class AgentAllowance:
    remaining_steps: int
    remaining_tokens: int
    recent_action_input: int
    output_limit: int

    @property
    def finish_required(self) -> bool:
        return self.remaining_steps <= 1 or (
            self.recent_action_input > 0
            and self.remaining_tokens < 2 * (self.recent_action_input + self.output_limit + 256)
        )


@dataclass(frozen=True)
class Claim:
    job_id: str
    agent_id: str | None
    worker_id: str
