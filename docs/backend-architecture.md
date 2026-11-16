# Backend architecture

The backend uses domain-driven design with explicit application, infrastructure, and HTTP
boundaries. Its two main concerns are repository investigations (including agents and budgets)
and source acquisition. The domain is deliberately small: it models rules, not copies of SQL tables.

```text
app/
  domain/
    investigations.py   ReviewBrief, AgentAllowance, fenced Claim values
    budgets.py          BudgetAccount, InferenceCharge, reported-usage pricing
    errors.py           Rejected operations and exhausted allowances
  application/
    ports.py            Investigation/source repository, preparation and queue contracts
    investigations.py   Start, retrieve, cancel, inspect and list investigation use cases
    sources.py          Prepare/remove sources and own preparation-task lifetimes
  infrastructure/
    models.py           SQLAlchemy persistence models
    database.py         Sessions, migration checks and per-job transaction boundaries
    persistence.py      Durable execution store; atomic admission, leases and settlement
    read_models.py      SQL query adapters and source-repository adapters
    execution.py        LangGraph/OpenAI execution adapter
    openai_provider.py  Official OpenAI Responses transport
    source_import.py    Bounded Git and local snapshot acquisition
    queue.py            Redis wakeups
    diagnostics.py      Infrastructure readiness and explicit connectivity
  interfaces/http.py    Authenticated routes, DTO mapping, pagination and SSE transport
  api.py                Composition root and transport error mapping
  worker.py             Worker-process composition and scheduling
```

The domain imports only Python's standard library. Application services depend on domain
values and narrow Protocol ports. They cannot import SQLAlchemy, FastAPI, Redis, OpenAI or
concrete infrastructure. Architecture tests enforce this direction. HTTP routes contain no
SQL; they map validated requests to use cases and shape their responses.

The infrastructure adapters implement the ports. SQL read models return explicit projections;
they do not pretend that ORM records are domain entities. The execution store remains the
transaction coordinator for the investigation aggregate: a job row lock covers budget
admission, reservations, agent creation and lifecycle changes. Pure reservation and finishing
rules delegate to the domain. This keeps invariant checks inside the same transaction while
allowing them to be tested without a database.

AgentAllowance preserves the distinction between cumulative agent tokens and per-request
context capacity. Its recent-input estimate excludes summary requests. BudgetAccount checks
reported and reserved usage together before authorizing an inference charge. Immutable pricing,
late reconciliation, fenced leases and model selection retain their existing behavior.

SourceService owns its task registry. Client disconnection does not abandon an admitted import:
the task is shielded, persists its outcome and is awaited during application shutdown. Import
policy, filesystem/Git calls and SQL are adapters rather than HTTP responsibilities.

The former app.store, app.models, app.database, app.runtime, app.llm, app.repositories and
app.broker modules are explicit compatibility facades. Existing workers, migrations and
integrations can keep their imports. The API URLs and database schema are unchanged.

SOLID is applied through focused responsibilities, substitutable Protocol ports, dependency
injection at process composition, and separate read models. A new repository or queue adapter
can be introduced without changing use cases. Business-rule tests, use-case tests, API ownership
checks, SDK execution tests and database integration checks cover different boundaries.

## Validation

From the repository root:

    .\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
    .\backend\.venv\Scripts\ruff.exe check backend

Domain/use-case tests use in-memory fakes. Production has no fake model or deterministic
replacement for autonomous reasoning. The existing opt-in paid provider test remains opt-in.
