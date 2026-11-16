# Architecture audit - 2026-11-16

The original repository contained two backend modules, two frontend components, two tests,
and a CSV benchmark. There were no migrations, persistent stores, worker services,
authentication, tool permissions, or deployment files.

- `Engine.run` selected the same backend/data/configuration roles for every objective.
- Adaptive spawning used output length divided by 400 and one fixed verification wave.
- `investigate` slept and searched regex patterns. Optional Deep Agents received only an
  objective, without access to the target repository. Neither path supported real delegation.
- LangGraph only cleared findings and concatenated strings; its planning node erased inputs.
- Asyncio tasks and dictionaries held all state. Cancellation did not interrupt inference.
- SSE polled snapshots for ten minutes without event IDs or replay.
- React Flow displayed dictionaries but lost history on refresh.
- Benchmark scores measured text length, not correctness.
- Dependencies were broad ranges; Python 3.11 and Node 20 are available. Docker CLI exists,
  but its daemon was initially stopped. No LLM credentials were present in the environment.

## Replacement architecture

Keep FastAPI, LangGraph, Next.js and React Flow. Run one bounded supervisor transition at
a time, loading PostgreSQL state before inference and persisting decisions before dispatch.
Workers claim durable database work with leases. Redis is a wakeup queue, never the source
of truth. Agents yield worker slots after each turn, including while waiting for children.
No overlapping Deep Agents delegation layer is needed.

LLM schemas describe proposals; transactions enforce permissions, ownership, dependencies,
deduplication, leases and resource reservations. Repository content is untrusted data.
Host execution and patch application are disabled without a provisioned sandbox. Patch
proposals are retained as reviewable artifacts.

SQLite is used only in explicitly configured tests. Production requires PostgreSQL, Redis,
an API bearer token and real provider configuration. Missing configuration is an error,
never a switch to a mock model.

## API references

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

## OpenAI-only update

The inference boundary now uses the official OpenAI Python SDK Responses API. The four role
models are centrally configured; routine work defaults to the economical model, critical work
needs a reason, and escalation has runtime budget approval. LangGraph includes a separate
synthesis node. All model decisions, tool calls, recursive requests and summaries remain real
LLM operations. No deterministic model substitute is present.

New migrations persist job model allocations and inference usage metadata, pricing snapshots,
request purpose, response ID and reported model. Cache reads/writes and reasoning usage are
accounted without double charging. Conservative unknown outcomes can be reconciled with late
actual usage after cancellation. Full model access tests are explicit paid operations.

See [OpenAI configuration and sources](openai-models.md) for verified model support and prices.

## Repository acquisition

Authenticated source import accepts allowlisted public HTTPS Git URLs and local paths under
administrator-mounted roots. A managed, bounded snapshot is prepared before job admission.
Repository ownership, preparation status, revision and file counts are persistent. Workers
resolve these sources from shared read-only snapshot storage. Git uses no checkout, hooks,
filters or submodule execution. Source removal is serialized against job admission and is
blocked for active investigations. Existing registered fixtures and benchmark modes remain.
