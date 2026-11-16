class Rejected(ValueError):
    """An operation violates an investigation invariant."""


class BudgetExhausted(Rejected):
    """No further inference may be admitted for this job."""


class AgentBudgetExhausted(Rejected):
    """This agent must stop; its supervisor may recover the investigation."""


class RepositoryError(ValueError):
    def __init__(self, message, code="repository_invalid", status=422):
        super().__init__(message)
        self.code, self.status = code, status
