# File manifest

## Updated existing files

- .gitignore
- README.md
- backend/app/core.py
- backend/app/main.py
- backend/requirements.txt
- benchmarks/run.py
- frontend/app/layout.tsx
- frontend/app/page.tsx
- frontend/package-lock.json
- frontend/package.json

## Created files

- .env.example
- .github/workflows/ci.yml
- backend/.dockerignore
- backend/Dockerfile
- backend/alembic.ini
- backend/app/__init__.py
- backend/app/api.py
- backend/app/broker.py
- backend/app/config.py
- backend/app/database.py
- backend/app/llm.py
- backend/app/models.py
- backend/app/observability.py
- backend/app/runtime.py
- backend/app/schemas.py
- backend/app/server.py
- backend/app/store.py
- backend/app/tools.py
- backend/app/worker.py
- backend/app/worker_health.py
- backend/migrations/env.py
- backend/migrations/script.py.mako
- backend/migrations/versions/1d24e2f71509_initial_durable_execution_schema.py
- backend/migrations/versions/af87f7d9d383_supervisor_progress_watermark.py
- backend/pyproject.toml
- backend/requirements.lock
- backend/tests/__init__.py
- backend/tests/conftest.py
- backend/tests/fakes.py
- backend/tests/test_api.py
- backend/tests/test_config_and_tools.py
- backend/tests/test_lifecycle.py
- backend/tests/test_postgres.py
- backend/tests/test_provider_http_e2e.py
- backend/tests/test_redis.py
- backend/tests/test_runtime.py
- benchmarks/evaluate.py
- benchmarks/fixtures/complex/database.py
- benchmarks/fixtures/complex/ground_truth.json
- benchmarks/fixtures/complex/service.py
- benchmarks/fixtures/small/calculator.py
- benchmarks/fixtures/small/ground_truth.json
- benchmarks/test_fixtures.py
- deploy/Caddyfile
- docker-compose.production.yml
- docker-compose.yml
- docs/architecture-audit.md
- docs/delivery.md
- docs/file-manifest.md
- frontend/.dockerignore
- frontend/Dockerfile
- frontend/app/globals.css
- frontend/components/agent-graph.tsx
- frontend/components/findings.tsx
- frontend/eslint.config.mjs
- frontend/lib/api.ts
- frontend/next.config.mjs
- frontend/postcss.config.mjs
- frontend/tailwind.config.ts

## Replaced tests

- Removed backend/tests/test_core.py; its scaffold-only checks were replaced by the provider, runtime, lifecycle, API and infrastructure suites.

## OpenAI-only update

Updated: .env.example, README.md, backend/app/api.py, config.py, llm.py, models.py,
runtime.py, schemas.py, store.py, tools.py, worker.py, both Python requirements files,
backend/tests/conftest.py, fakes.py, test_api.py, test_config_and_tools.py,
test_lifecycle.py, test_provider_http_e2e.py, test_runtime.py, benchmarks/run.py,
frontend/app/page.tsx, frontend/lib/api.ts, docs/architecture-audit.md and docs/delivery.md.

Added:

- backend/app/connectivity.py
- backend/migrations/versions/b73164ec93ac_openai_usage_accounting.py
- backend/tests/responses.py
- backend/tests/test_openai.py
- docs/openai-models.md

Unused model-provider packages were removed from the dependency files and synchronized
out of the local Python environment. LangGraph retains its required transitive core packages.

## Repository URL and local-path input

Added backend/app/repositories.py, backend/tests/test_repositories.py,
backend/migrations/versions/c9b38f62a19d_repository_snapshots.py and docs/repository-input.md.
Updated backend configuration, schemas, models, store, API, runtime source resolution and
schema startup checks; Docker Git installation, cache volume and local-project mounts;
frontend input, preparation state, saved-snapshot controls and source metadata; test fixtures,
.env.example, .gitignore and README. The local .env gained only LOCAL_PROJECTS_PATH.

## Review execution budget correction

Updated backend/app/llm.py, runtime.py and store.py for exact OpenAI input counts, matching
request schemas, branch-scoped token exhaustion, smaller prompt contexts, preserved latest
observations, refreshed continuation allowances and enforced finishing turns. Added
backend/tests/test_token_capacity.py and updated the scripted/SDK workflow test fixtures.
Updated README, docs/openai-models.md and delivery.md. No credential or dependency changes.

## Product UI and domain-driven backend

Added app/domain (review values, agent allowances, reservation rules, usage pricing, errors),
app/application (ports and investigation/source use cases), app/infrastructure (SQL models,
transactional store, read models, queue, OpenAI, source acquisition, execution and diagnostics),
and app/interfaces/http.py. app/api.py is the composition root. The original module names
are explicit compatibility facades for workers, migrations and integrations.

Added backend/tests/test_domain_architecture.py for rule admission, ownership, persist-before-wake
ordering, preparation cancellation/shutdown and dependency direction.

Replaced the monolithic frontend page with transport/submission modules, workspace and review
hooks, a workspace shell, source/brief form, findings/team/activity views, native dialog drawers,
settings and a responsive light-theme stylesheet. Added keyboard tab navigation and on-demand
graph loading. Added Playwright configuration and seven test-only browser flows. Playwright is
a development dependency; production contains no fixture-based reasoning or fake review data.

Added docs/backend-architecture.md and docs/product-ui.md; updated README, metadata, ignores,
package scripts/lockfile and delivery notes. Existing credentials and database schema are preserved.
