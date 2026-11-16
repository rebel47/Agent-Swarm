# Delivery and validation - 2026-11-16

The application now uses OpenAI exclusively through the official Python SDK Responses API.
The requested role defaults and $5 job budget are implemented in central configuration.
LangGraph still manages real model decisions, execution state and dependency-aware transitions.
Production has no simulated reasoning path. Test doubles and HTTP fixtures exist only in tests.

## Six-phase implementation

| Phase | OpenAI-only implementation | Verification |
|---|---|---|
| 1. Orchestrator and factory | Responses function calling generates structured plans, roles, tools, tasks and model purposes; economical default with justified stronger allocations | SDK HTTP workflow, schema validation, allocation and model-error tests |
| 2. Durable execution | PostgreSQL reservations include cache-write premiums; immutable prices reconcile actual usage, with global concurrency and fenced claims | Real PostgreSQL concurrency tests, token/cost admission, migrations and schema drift check |
| 3. Recursion and lifecycle | Model-created children, dependencies, retries and cancellation; budget-approved model escalation; refreshed leases between bounded requests | Recursive SDK worker workflow, dependency/cycle/depth checks, escalation approval/denial, crash recovery and cancellation |
| 4. Live visualization | Model selectors, explicit connectivity test, graph, agent allocation reasons, SSE costs, reservations, remaining budget, cache and reasoning usage | Frontend lint/typecheck/build; authenticated API tests; HTTP screen and static assets |
| 5. Software investigation | Capability-scoped source tools and exact citations; critical verification tier; separate OpenAI synthesis; persisted economical context summaries | Source/evidence/security tests, synthesis model accounting, summary persistence and continuation |
| 6. Adaptive policy and benchmarks | Runtime-enforced model/cost policy, OpenAI-only dependency lock, observed per-model/cache/reasoning metrics in reproducible benchmarks | Fixture validation, 100-agent lifecycle test, dependency sync and installed SDK integration |

Patch proposals remain unapplied review artifacts. Repository code execution and patch application
require a separately provisioned secure sandbox and are disabled. This update does not claim
that source inspection executed repository tests.

## Validation actually executed

| Check | Result |
|---|---|
| Final Linux suite, non-root/read-only runtime with real PostgreSQL and Redis | **63 passed, 1 skipped** in 20.64 seconds |
| OpenAI model allocation/caching/error/usage tests on Windows | 14 passed |
| Windows targeted OpenAI/API/lifecycle checks | 28 passed |
| Native SDK Responses recursion and native tool workflow | Passed using test-only HTTP transport; eight accounted calls including separate synthesis |
| OpenAI Responses streaming event parsing | Passed using actual SDK and test-only SSE events |
| Python lint and formatting | Passed |
| Frontend ESLint and TypeScript | Passed |
| Next.js production build | Passed locally and in Node 22 Docker image |
| npm production audit | 0 reported vulnerabilities |
| OpenAI-only Python lock generation and environment sync | Passed; unused integration packages removed |
| Backend/frontend Docker image builds | Passed |
| PostgreSQL migration and Alembic drift check | Passed, including existing development database upgrade |
| Base and HTTPS production Compose configuration | Passed; example.com supplied only for configuration validation |
| Updated frontend HTTP and authentication screen | HTTP 200; all 9 referenced static assets returned 200 |
| Local application bootstrap | Generated missing application/database credentials, preserved the existing OpenAI key, started the full Compose stack |
| Actual paid OpenAI connectivity/tool-calling request | Skipped; explicit paid-test flag not enabled and account access unverified |
| Paid single/fixed/adaptive benchmark evaluations | Not run; require explicit authorization and configured OpenAI access |
| Interactive browser verification | Not rerun; HTTP/build checks do not establish interactive browser correctness |

The 63-test suite includes benchmark fixture checks and real PostgreSQL/Redis tests.
The disposable PostgreSQL test database was removed afterward. SDK fixtures establish
transport/schema/runtime integration, not the quality of actual model decisions.
No model availability for the user's OpenAI project or paid benchmark score is claimed.

The official model pages document Responses/function calling for both requested defaults.
See [OpenAI model configuration](openai-models.md) for sources, verified prices, all settings
and the explicit connectivity command. A 404 or access-denied error preserves the actual
OpenAI message and never triggers a model substitution.

## Start and test

1. Copy .env.example to .env; set OPENAI_API_KEY, a generated API_TOKEN, database credentials
   and authorized workspace mappings. Review the supplied Standard pricing for your account.
2. Run docker compose build, then docker compose up -d. Open http://localhost:3000.
3. Authenticate using API_TOKEN. Select role models and a repository for a new investigation.
4. Use Test OpenAI connectivity only when you want to authorize a real billable test.

CLI connectivity from backend/: python -m app.connectivity --model gpt-6-sol.
No startup, health, readiness or model-list request performs paid inference.
The full local stack is running: frontend, backend, worker, PostgreSQL and Redis. The existing OpenAI key in .env was preserved. Missing application/database credentials were generated locally, and the local PostgreSQL role password was updated to match. No paid request was made. Use API_TOKEN from .env to sign into the dashboard.

Migration b73164ec93ac adds frozen job allocations and inference usage/pricing metadata.
Stop older workers before upgrading; review or cancel unfinished jobs using removed configuration
before restarting with new model policies. Retained historical agent models are not rewritten.

Deployment still needs account credentials, operational load testing, billing reconciliation,
secret management, backups, retention and identity controls appropriate to its environment.

## Repository URL and local-path input update

Added the authenticated repository preparation/list/removal API, persistent owned snapshots,
source metadata in job responses, and direct URL/path input beside the objective. Public HTTPS
GitHub, GitLab and Bitbucket repositories are enabled by default. Other trusted Git hosts can
be configured. Private repositories can be cloned locally and imported by folder path.

Local projects are mounted read-only under one configured host root. This workspace uses
E:/agent-swarm-mvp. The backend writes only to its managed snapshot volume; workers mount that
volume read-only. Hooks, checkout filters, submodules and Git LFS execution are disabled.
Imports use byte/file/deadline/concurrency limits and credentials are not passed to Git.
Saved snapshots cannot be removed while an investigation uses them. A source revision remains
visible in historical reports after removal. Existing static fixtures remain available.

Validation for this update:

- Full Linux suite with real PostgreSQL/Redis: **87 passed, 1 skipped** in 22.57 seconds.
- Full native Windows suite: **85 passed, 3 skipped** in 32.71 seconds.
- Native repository module tests cover URL validation, Windows path mapping, ownership,
  snapshot immutability, secrets/links/binary exclusions, size bounds, branch selection with
  installed Git, preparation failure/capacity recovery, removal and runtime source resolution.
- Real deployed API local-folder import: READY, source digest and file count recorded;
  listing and removal passed.
- Real deployed API public GitHub import of octocat/Hello-World: READY at commit
  7fd1a60b01f91b314f59955a4e4d4e80d8edf11d; listing and removal passed.
- Worker snapshot-volume read-only mount verified using Docker inspection.
- Database migration and Alembic drift check passed. Disposable test database/role removed.
- Python lint/format, frontend TypeScript/ESLint and Docker builds passed during implementation.
- No paid model call was made by repository import validation; real LLM smoke test remains opt-in.

Next.js proxyTimeout is raised to 180 seconds so imports can use the default 120-second backend
preparation allowance. Form inputs stay fixed while preparation/submission is pending.
See [repository input guide](repository-input.md) for usage and deployment configuration.

Final deployed verification: all five long-running Compose services are healthy. The updated
frontend bundle and all 9 referenced static assets returned HTTP 200. Authenticated readiness
through the frontend proxy passed, as did a fresh public GitHub import/list/removal through
that proxy. Local projects/fixture mounts are read-only for backend and worker; only the
backend's managed snapshot volume is writable. The final branch-selection repository module
run passed all 24 tests. The app is available at http://localhost:3000.

## Review execution failure correction

The reported GitHub source import was successful. Reviews failed because byte-sized request
reservations were compared with cumulative agent token allowances, and an exhausted agent
cancelled the entire job despite ample job budget. Generation now uses the official OpenAI
input token counter with matching messages, tools and reasoning configuration, plus 256 tokens
of headroom. Atomic reservations, configured output caps and reported-usage reconciliation
remain enforced. Agent exhaustion is branch-scoped and visible to the supervisor.

Prompt contexts omit UI bookkeeping and unrelated full reports; compaction preserves the
latest observation and explicitly marks older omissions. Agents receive remaining allowances,
with only submit_result available on the last turn or when tokens require finishing. Summary
usage refreshes that allowance. Citation instructions require exact short source quotations.

Validation: Python lint passed; the full native suite passed **89 tests, 3 skipped**. The six
new regression cases cover counted-token reservations with large source context, final-turn
and token-driven finishing, branch recovery without sibling cancellation, counting failures
without generation, invalid token counts, and preservation of the latest source observation.
The installed-SDK recursive worker workflow also passes with token counting requests.

Real investigation 5b495ba2-f232-438c-9efd-66aeb33514dc reviewed
https://github.com/rebel47/Multi-Agent-Research-System.git at its prepared snapshot. It completed
with two source-validated findings, six agents, 279,311 accounted tokens and an estimated
cost of $0.2036012. All usage was reported; no unknown outcomes or outstanding reservations
remain. Budget defaults, models, credentials and dependencies were unchanged.

Follow-up: the next completed review had one agent_budget_exhausted branch. The app/tools
agent's allowance was 30,000 tokens; it used 23,361, leaving 6,639, which could not fit another
counted request plus the 4,096 output reservation. All provider requests succeeded. A small
summary (368 input tokens) had incorrectly replaced the previous full agent input (7,576)
in the finishing estimate, allowing an additional source read instead of an earlier report.
The context query now excludes summaries from that estimate while still charging their usage.
Future exhaustion messages include available and required token counts where known.

The new regression reproduces the recorded post-summary allowance, fails against the old
guard and passes with the corrected guard: only submit_result is exposed and the agent
completes. Full native validation: **90 passed, 3 skipped**, plus Python lint and Docker build.
No further billable review was started for this diagnosis. The completed review and its
historical failed branch remain unchanged.

## Product interface and domain-driven architecture

The interface now separates starting a review from reading one. A new review has two primary
steps: repository and brief. Git/local/saved source tabs, focus presets and one primary action
replace the always-visible configuration dashboard. Advanced options are collapsed. Models
and the explicit billable connectivity test live in a settings drawer.

Review pages default to findings, with three summary measures. Team and Activity are separate
tabs; graph code loads on demand. Source excerpts, individual agent errors, tool steps, costs
and runtime identifiers are available through expandable evidence or detail drawers. The layout
supports mobile navigation, keyboard tab movement, native modal focus and reduced motion.
An accepted review remains selected if a subsequent workspace-list refresh fails.

The backend now has framework-free domain rules, port-based application services, explicit
infrastructure adapters, thin HTTP transport and a composition root. Business-critical budget
admission and early-finishing rules are domain policies exercised by the transactional execution
store. SQL queries and source-task ownership no longer live in route handlers. Public imports,
API URLs and database schema are compatible. See backend-architecture.md for dependency rules.

Validation completed:

- Full native backend suite: **97 passed, 3 skipped** (paid provider test remains opt-in).
- Real PostgreSQL concurrency and Redis checks in an isolated database: **2 passed**;
  temporary database and role removed afterward.
- Final deployed Playwright suite: **7 passed**, covering connection, Git branches, local/saved
  sources, model allocation, findings, agent errors, details, mobile, keyboard and refresh failure.
- Desktop, report and mobile screenshots rendered and inspected; static-label encoding corrected.
- Python lint, frontend TypeScript/ESLint and production Docker builds passed.
- Authenticated readiness, models, review history and repositories returned HTTP 200 through
  the frontend proxy. The frontend and all seven referenced static assets returned HTTP 200.
- Alembic check: no new upgrade operations. All five long-running services are healthy.

No new billable investigation or model connectivity test was started for this work. Browser
fixtures intercept API calls only inside the test suite; production reasoning remains OpenAI-driven.
The app is available at http://localhost:3000.
