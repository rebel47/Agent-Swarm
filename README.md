# Adaptive Agent Swarm

An OpenAI-powered repository investigation service built with FastAPI, LangGraph, PostgreSQL,
Redis, Next.js, React Flow and Tailwind. The supervisor decides which specialists are useful;
specialists can request children. The runtime enforces permissions and resource limits.

The product interface keeps new reviews focused on a repository and a brief. Completed
reviews open directly to findings; the team, activity, usage details and model settings are
available when needed. See [interface guide](docs/product-ui.md).

The backend uses domain-driven design: framework-free budget/review rules, application use
cases behind repository and queue ports, infrastructure adapters, and thin HTTP routes.
See [backend architecture](docs/backend-architecture.md) for boundaries and extension points.

There is **no production mock mode**. Missing OpenAI credentials, pricing, database settings
or the application access token produce configuration errors. Test doubles live under tests/.

## Architecture

~~~mermaid
flowchart LR
  UI["Next.js chat, graph and dashboard"] -->|Bearer-authenticated API| API[FastAPI]
  API --> PG[(PostgreSQL state and events)]
  API --> R[(Redis wakeup queue)]
  W["Workers: leased execution turns"] --> R
  W --> PG
  W --> G["LangGraph: observe ? decide ? synthesize ? validate/apply"]
  G --> L["OpenAI Responses API"]
  G --> F["Validated dynamic agent factory"]
  F --> PG
  W --> A["Agents: native tool calls and child requests"]
  A --> L
  A --> T["Capability-scoped repository tools"]
  T --> FS["Authorized repository mounts: read only"]
  PG -->|Persisted event replay and snapshots| API
  API -->|SSE| UI
~~~

A supervisor graph invocation performs one bounded, recoverable transition. Its validated
decision is saved as a checkpoint artifact. Agent turns, child waits, outputs, tool history,
budgets and events are durable. PostgreSQL is authoritative; Redis messages only wake workers.
Workers rescan the database if a wakeup is lost. Parent waits consume no execution slot.

Every spawn batch takes the job row lock. Concurrent workers cannot bypass job budgets.
PostgreSQL transaction advisory locks serialize global concurrency admission. Claims carry
unique lease tokens, so late results from expired or cancelled workers cannot overwrite state.
Scheduling rotates across jobs and favors agents with fewer completed turns.

Deep Agents is deliberately not used: a second delegation engine would conflict with this
scheduler's ownership, permissions and budgets.

## Requirements and configuration

Use Python 3.11+, Node.js 22 for development, PostgreSQL 17, and Redis 7.
Docker Desktop with Linux containers is an alternative to installing infrastructure locally.

Copy .env.example to .env. Generate an application token:

    python -c "import secrets; print(secrets.token_urlsafe(48))"

Set these required values in .env:

- API_TOKEN: a random application access token, at least 32 characters.
- DATABASE_URL: postgresql+psycopg://user:password@host:5432/database.
- REDIS_URL: redis://host:6379/0.
- OPENAI_API_KEY and the four model role settings in .env.example.
- MODEL_POLICIES: model allowlist, current USD rates per million tokens, context and output limits.
- WORKSPACES: JSON mapping workspace names to existing absolute directories.

MODEL_POLICIES supplies pricing and capabilities for all configured OpenAI models. Defaults use
gpt-6-sol for orchestration, critical verification and synthesis, and gpt-6-luna for routine agents.
The initial job cap is $5, 100 logical agents, 10 concurrent execution turns and depth 5.
Rates and capabilities were verified against official documentation on 2026-11-16.
All model identifiers, prices, reasoning efforts and limits are configurable.
See [OpenAI model configuration](docs/openai-models.md) for exact defaults, caching, accounting,
escalation, pricing sources, model selection and real connectivity tests.

WORKSPACES example for Windows:

    {"project":"E:/code/project","small":"E:/agent-swarm-mvp/agent-swarm/benchmarks/fixtures/small"}

Repositories can be supplied as a public HTTPS Git URL, a local project folder under the
configured projects root, or a saved/registered repository from the dropdown. The backend
prepares an owned source snapshot before starting an investigation. The browser receives source
metadata; OpenAI keys and managed cache paths stay on the backend. The application access token is entered by the user
and retained in sessionStorage for the current browser tab. Job selection persists on refresh.

### OpenAI model access

The official OpenAI Python SDK uses Responses for native function calls and Pydantic validation.
Startup validates local configuration without making a paid API request. To test actual project
access and tool calling, click **Test OpenAI connectivity** in the authenticated dashboard, or run
python -m app.connectivity --model gpt-6-sol from backend/. This is an explicit billable test.
The actual API error is reported if the selected model is unavailable. No fallback model is used.
Choose another allowlisted model for each new-job role in the dashboard, or edit the environment
and restart backend and workers. The OpenAI key stays on the backend.

## Give the app your repository

Select **Git URL or local project folder**, enter a URL such as https://github.com/owner/repo
or a local path, write your objective and click **Investigate**. Git URLs support an optional
branch/tag. Public GitHub, GitLab and Bitbucket repositories are enabled by default. Source
snapshots retain their revision and are shared read-only with workers.

For Docker local paths, set LOCAL_PROJECTS_PATH to your absolute host projects directory,
using forward slashes on Windows, then run docker compose up -d. The UI shows the available
root. Each project underneath it can be submitted without additional Compose edits.
Private repositories can be cloned locally and reviewed by folder path.

See [repository input and configuration](docs/repository-input.md) for examples, API routes,
limits, supported hosts, snapshot management and native-backend configuration.

## Local startup

From the project root, after configuring .env and starting PostgreSQL/Redis:

    cd backend
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.lock
    .venv\Scripts\alembic.exe upgrade head
    .venv\Scripts\python.exe -m app.server

In a second terminal:

    cd backend
    .venv\Scripts\python.exe -m app.worker

In a third terminal:

    cd frontend
    npm ci
    npm run dev

On Linux/macOS use .venv/bin/python and .venv/bin/alembic.
The app.server entry point also selects the event loop required by psycopg on Windows.
Standard Linux startup can use uvicorn app.main:app --host 127.0.0.1 --port 8000.

Open http://localhost:3000, enter API_TOKEN, enter a repository URL/local path or select a saved repository, and submit an objective:

> Analyze this repository, identify performance bottlenecks, investigate the root causes,
> and provide an evidence-backed report.

The frontend proxies /api/v1 to the backend. API_INTERNAL_URL is server-side configuration,
not a provider secret. Set it at build time for a production frontend using another API host.

An illustrative execution might create API and database investigators, with the database
investigator requesting a query specialist. This is **not** a fixed team or a recorded result:
actual roles, counts and delegation depend on real model decisions and your resource policy.
Every accepted/rejected spawn request and lifecycle transition appears in the audit panel.
Click a graph node to inspect authorized tools, child agents, tool steps, costs and errors.

## Docker Compose

Configure .env, then:

    docker compose build
    docker compose up -d
    docker compose logs -f backend worker

Services are frontend, backend, worker, postgres, redis and a one-shot migration service.
Database and Redis data use persistent volumes. Backend and worker run as non-root users,
with read-only filesystems and read-only repository mounts. Health checks and startup
dependencies are defined. Local ports bind to loopback.

The default Compose file registers the small and complex benchmark fixtures. Replace the
read-only volume mappings and WORKSPACES entries together to authorize your repositories.
Do not mount provider credential directories as investigation workspaces.

    docker compose --env-file .env.example config --quiet

This validates configuration syntax without requiring real credentials. It does not prove
provider access. To run more workers:

    docker compose up -d --scale worker=3

All workers must use the same resource configuration and PostgreSQL/Redis services.

For an internet-facing deployment, configure DOMAIN and deploy behind HTTPS:

    docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build

The production overlay removes direct frontend/backend port publications and uses Caddy TLS.
Public DNS and inbound ports 80/443 are required. The bearer token protects application data;
the liveness endpoint intentionally exposes only process health.

## APIs and cancellation

All application endpoints require Authorization: Bearer <API_TOKEN>.
The only unauthenticated API is GET /api/v1/health.

- POST /api/v1/jobs; optional Idempotency-Key header.
- GET /api/v1/jobs with offset/limit; GET /api/v1/jobs/{id}.
- POST /api/v1/jobs/{id}/cancel.
- GET /api/v1/jobs/{id}/agents and /agents/{agent_id}.
- GET /api/v1/jobs/{id}/agents/{agent_id}/steps.
- GET /api/v1/jobs/{id}/results, /artifacts and /history.
- GET /api/v1/jobs/{id}/events; Last-Event-ID or after cursor supported.
- GET /api/v1/workspaces, /api/v1/ready and /api/v1/models.
- POST/GET /api/v1/repositories; DELETE /api/v1/repositories/{id}.
- POST /api/v1/models/connectivity: explicit, bounded, billable OpenAI function-call test.

Job ownership is checked before returning state, artifacts or events. Unknown and unauthorized
job IDs both return 404. SSE sends persisted events with IDs plus authoritative snapshots on
connection and completion. The frontend reconnects with its cursor and resynchronizes state.

Job cancellation propagates to all active branches. Workers interrupt local awaits when
cancellation is observed; network cancellation cannot guarantee that a provider stops billing.
On shutdown, workers release claimed turns. On a crash, expired leases are recovered.
Provider errors use bounded retries with exponential backoff and jitter.

## Tools, evidence and optional patches

Tools support file listing, bounded numbered reads, literal search, manifest inspection,
Python AST/syntax analysis, optional git history, model escalation, child requests and same-job agent results.
They never expose arbitrary filesystem or shell access. Links, junctions, hardlinks, secret
directories, environment files, binary files and oversized files are rejected.
Tool outputs are marked untrusted and bounded; common credential formats are redacted.

Source quotes and line ranges are checked against the authorized repository before results
are accepted. This validates the cited text, not the model's interpretation of it.
The runtime rejects claims of test verification because repository execution is disabled.

The optional proposal mode retains unified diffs as unapplied artifacts for human review.
Original files are never written. **Patch application and run_tests are disabled** because no
secure execution sandbox is provisioned. No code is committed, pushed or deployed by agents.

## Budgets and observability

Set MAX_TOTAL_AGENTS, MAX_CONCURRENT_AGENTS, MAX_AGENT_DEPTH, MAX_TOTAL_TOKENS,
MAX_TOTAL_COST_USD, MAX_AGENT_STEPS, MAX_AGENT_TOKENS and MAX_SUPERVISOR_STEPS.
These are administrator limits, not heuristics for choosing an adaptive team size.
Normal reviews default to `SHARED_AGENT_BUDGET=true`: specialists draw from a shared
100,000,000-token / $1,000 review pool instead of model-chosen individual token caps.
The runtime assigns each specialist the administrator's 200-turn allowance, regardless
of smaller limits proposed by the supervisor or a delegating parent. Reviews have up
to 400 supervisor turns and six hours. These generous allowances are ceilings, not
spending targets; agents should finish as soon as the evidence is sufficient.
`MAX_AGENT_TOKENS` applies as an individual cap only with `SHARED_AGENT_BUDGET=false`,
which preserves strict per-agent limits for controlled benchmarks.
Existing `.env` values override defaults: update them along with `.env.example` when upgrading.
MAX_JOB_SECONDS and MAX_ACTIVE_JOBS bound overall lifetime and admission.
WORKER_SLOTS controls each worker's local capacity.

Each inference atomically reserves a conservative input/output token and cost bound before
calling the provider. Actual reported usage settles the reservation. Unknown outcomes after
timeouts/crashes are charged at the reserved bound instead of being treated as free calls.
Cached input, cache writes and reasoning usage are reconciled against immutable pricing snapshots.
Late reported usage replaces unknown charges once. Unaffordable job-level calls cancel the job before
network inference. Costs are estimates using administrator-configured rates, not a guarantee about the provider's
invoice, discounts or provider-side billing. Bounds include schema and context overhead.
Generation reservations use the OpenAI input token counting endpoint plus formatting headroom,
rather than treating bytes as tokens. In strict mode, an individual agent's exhausted allowance
fails that branch so the supervisor can replan. Agents see the allowance's scope and their remaining steps/tokens and must submit
a result on their final turn or when their remaining tokens require finishing.
Long tool histories use budgeted economical-model summaries, persisted with continuation
watermarks. Context is also bounded explicitly; original outputs remain in artifact rows.

JSON logs and database audit events carry job/agent IDs, decisions, errors and usage.
OTEL_EXPORTER_OTLP_ENDPOINT enables OTLP HTTP tracing. Do not enable third-party prompt
logging without an appropriate data-handling policy.

## Tests and validation

Standard tests never make paid API requests. Their scripted providers and HTTP transports
are confined to explicit test configuration.

    cd backend
    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\ruff.exe check app tests migrations
    .venv\Scripts\ruff.exe format --check app tests migrations
    cd ../frontend
    npm run typecheck
    npm run lint
    npm run build

Optional infrastructure tests use disposable migrated services:

    $env:TEST_POSTGRES_URL="postgresql+psycopg://user:password@localhost:5432/test_database"
    $env:TEST_REDIS_URL="redis://localhost:6379/15"
    .venv\Scripts\python.exe -m pytest -q

TEST_POSTGRES_URL must never refer to a production database. PostgreSQL tests create and
cancel jobs. Redis tests use the swarm:wake queue in the selected database.

Optional paid provider connectivity test, only after configuring real credentials:

    $env:RUN_REAL_LLM_TESTS="1"
    .venv\Scripts\python.exe -m pytest tests/test_config_and_tools.py -k optional_real_provider -q

## Benchmarks

First validate known-defect fixtures without inference:

    backend\.venv\Scripts\python.exe benchmarks/run.py

Real evaluations require an explicit flag and a running configured application:

    $env:SWARM_API_TOKEN="your-application-token"
    backend\.venv\Scripts\python.exe benchmarks/run.py --real --repeats 3 --fixed-agents 3

Each fixture uses identical objectives and the same configured limits across single, fixed
and adaptive modes. Single uses one LLM investigator. Fixed asks the LLM to allocate exactly
the supplied count, without further delegation. Adaptive has no predefined team size.
Ground truth is denied to investigation tools.

Results contain actual job status, elapsed time, tokens, estimated cost, agent counts, peak
concurrency, duplicate rejections and lease recoveries. JSON, CSV and a Markdown summary are
written under benchmarks/results. Location/quote matches measure coverage of known defects;
unmatched findings are flagged for human review. False-positive counts remain null until
reviewed. No benchmark performance numbers are fabricated.

## Troubleshooting and remaining hardening

- Configuration errors: check required variables, JSON formatting, registered directories,
  model policy rates and provider credentials. Production never falls back to a fake model.
- Not ready: migrate the database, check Redis and start a worker. Readiness needs a recent
  worker heartbeat; liveness alone does not indicate an operational investigation service.
- API 401: use the application token, not a provider API key.
- Context/budget exhausted: inspect whether the limit belongs to an agent or the whole job.
  Agent allowances include repeated input and output across all turns; a single exhausted
  agent no longer cancels the entire investigation. Generation still requires a reservation
  covering counted input, formatting headroom and the configured output maximum.
- Windows build trace lock: stop the dev server before building into the same .next folder.
- Provider rate limits/model access: inspect structured error codes and provider account
  permissions. Select another allowlisted OpenAI model when project access is unavailable.
- SSE proxy buffering: preserve streaming and disable intermediary buffering; Caddy's
  production configuration flushes the event stream.

This is a substantial production-oriented implementation, **not a claim of production
certification**. Deployment-specific security review, secret management/rotation, backup and
restore drills, migration rollout procedures, load tests, retention limits, per-user identity,
tenant administration, external rate limiting and operational alerting remain necessary.
One shared bearer token is suitable only for the initial trusted single-tenant deployment.

Prompt-injection defenses enforce concrete tool boundaries; they cannot guarantee that an
LLM's semantic conclusions are correct. Workspace contents can change between reads; use an
immutable read-only snapshot when reproducible evidence matters. Git history is optional and
disabled by default. Static syntax analysis is not a security audit.

Inference is at-least-once after a worker crash, so provider requests may repeat; state changes
are fenced and tool records are idempotent. The global advisory lock trades admission
throughput for correct shared concurrency. This system supports 100 logical agents but has
not been certified for a production throughput/SLA. Long investigations may need larger model
contexts and tuned budgets. Paid OpenAI validation requires
credentials; container startup alone cannot validate an LLM provider.

Validation results and known incomplete capability: [delivery notes](docs/delivery.md).
Full source change inventory: [file manifest](docs/file-manifest.md).
