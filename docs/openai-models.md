# OpenAI model configuration

All inference uses the official OpenAI Python SDK and Responses endpoint at
https://api.openai.com/v1. LangGraph owns supervisor transitions. No inference request
is sent at startup; startup validates credentials, all configured policies, tool-calling
capabilities, reasoning settings, database, Redis and registered directories.

## Defaults

```ini
OPENAI_API_KEY=
ORCHESTRATOR_MODEL=gpt-6-sol
SUBAGENT_MODEL=gpt-6-luna
VERIFICATION_MODEL=gpt-6-sol
SYNTHESIS_MODEL=gpt-6-sol
MAX_TOTAL_AGENTS=100
MAX_CONCURRENT_AGENTS=10
MAX_AGENT_DEPTH=5
MAX_TOTAL_COST_USD=5
ORCHESTRATOR_REASONING_EFFORT=medium
SUBAGENT_REASONING_EFFORT=low
VERIFICATION_REASONING_EFFORT=high
SYNTHESIS_REASONING_EFFORT=medium
```

The [Sol model page](https://developers.openai.com/api/docs/models/gpt-6-sol) and
[Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) document Responses,
function calling, streaming and prompt caching. Verified 2026-11-16. Documentation support
does not establish access for your OpenAI project.

Model identifiers are centralized in backend configuration. MODEL_POLICIES is an administrator
allowlist with pricing, context/output caps and capabilities. The supplied defaults use a
64,000-token runtime context cap and 4,096 output cap. MAX_AGENT_TOKENS defaults to 64,000;
it is a ceiling for reported usage plus conservative reservations, not an output target.
Agent allowances cover cumulative input and output across turns, including repeated context
and summaries. They are separate from a model's per-request context window. The supervisor
is instructed to use the configured agent allowance for multi-turn reviews, controlling cost
through focused work, economical models and step limits.
All four configured role models must have policies. To add another OpenAI model, add its
policy and select it through environment settings or the dashboard's new-job selectors.
New jobs freeze their model allocation; changes to environment defaults do not rewrite past jobs.

Standard short-context prices per million tokens, verified against the
[OpenAI pricing page](https://developers.openai.com/api/docs/pricing), are:

| Model | Ordinary input | Output (including reasoning) | Cached input | 30-minute cache write |
|---|---:|---:|---:|---:|
| gpt-6-sol | $2.00 | $10.00 | $0.20 | $2.50 |
| gpt-6-luna | $0.10 | $0.50 | $0.01 | $0.125 |

Rates are configurable. Refresh them for your account before deployment. The transport pins
Standard service tier and 30-minute explicit caching. Policies cap context at 272,000 tokens
to avoid crossing the documented long-context pricing boundary. Other OpenAI models may
require different capabilities, reasoning efforts or cache configuration; set those explicitly.
An empty reasoning-effort string omits the reasoning parameter.

Example policy shape:

```json
{"your-openai-model":{"input_per_million":2,"output_per_million":10,"cached_input_per_million":0.2,"cache_write_multiplier":1.25,"prompt_caching":"explicit","context_tokens":64000,"max_output_tokens":4096,"tool_calling":true,"streaming":true,"reasoning_efforts":["none","low","medium","high","xhigh","max"]}}
```

The numbers in this shape correspond to the Sol rates above; obtain the selected model's
own rates. Use prompt_caching=automatic for earlier OpenAI models that only support automatic
caching; configure an appropriate conservative cache_write_multiplier. Explicit caching uses
the documented prompt_cache_options and a breakpoint after stable developer instructions.
No cache hit is assumed when reserving cost. See
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Explicit connectivity test

The dashboard's **Test OpenAI connectivity** button makes one real, billable request for
the selected allowlisted model and requires a completed function call. It never tries another
model. CONNECTIVITY_MAX_COST_USD defaults to $0.10 per requested test. The separate test
allowance is checked against a conservative input/output reservation before sending.

CLI, from backend/:

```powershell
.venv\Scripts\python.exe -m app.connectivity --model gpt-6-sol
```

Authenticated API:

```text
GET /api/v1/models
POST /api/v1/models/connectivity
Authorization: Bearer <application API_TOKEN>
Content-Type: application/json

{"model":"gpt-6-sol"}
```

Success includes configured/reported model, response ID, actual token usage, cache details
and a dollar estimate. Failure includes the actual OpenAI error code/message, HTTP status,
request ID and requested model, with credentials redacted. A missing model or denied project
access never triggers substitution. Select another allowlisted OpenAI model for the relevant
new-job roles, or update environment settings and restart backend and workers.

## Allocation and cost controls

Before generation, the runtime uses the official
[Responses input token counting API](https://developers.openai.com/api/docs/guides/token-counting)
with the same messages, function schemas, model, reasoning effort and tool choice as the
generation request. It reserves that count plus 256 input tokens of formatting headroom and
the configured maximum output, using the cache-write rate without assuming cache hits.
The reservation is atomic and reconciled with reported usage. Known exhausted job or agent
allowances are rejected before token counting; a counting failure never triggers generation.
Context compaction preserves the latest tool observation and marks omitted older history.
An exhausted agent fails its own branch so the supervisor can replan; exhausting the overall
job token or cost allowance cancels the investigation.
Agents receive their remaining steps and cumulative tokens. On the last allowed step, or
when less than two recent request allowances remain, only submit_result is exposed, so the
model can finish from evidence already read and explicitly report coverage gaps. Summaries
refresh the continuation allowance before the next action.
The finishing estimate uses the most recent full agent request, excluding summary requests
whose smaller input would underestimate the following action. Summary usage still counts
toward the cumulative allowance. Token-exhaustion errors include remaining and required
tokens when an input count is available. Source quotes remain validated; prompt guidance
asks for short exact excerpts to avoid accidental whitespace rewrites.

The model decides agent count, objectives, tools and recursion. Agent specs default to
model_purpose=routine, using SUBAGENT_MODEL. Complex work uses ORCHESTRATOR_MODEL; critical
verification uses VERIFICATION_MODEL. Stronger allocations require a substantive model_reason.
REQUEST_VERIFICATION routes its proposed agents to the verification tier. Final reporting runs
a separate, accounted LangGraph synthesis node using SYNTHESIS_MODEL.

Authorized agents can call request_model_escalation with purpose, reason and expected benefit.
The runtime checks the next call's worst-case context/output allowance against remaining
job and agent budgets. Approval records an audit event and updates that agent's model.
Each subsequent API call still requires an atomic reservation; another worker cannot consume
the same remaining budget twice. Rejected escalation returns a tool observation.

Every planning, investigation, summary and synthesis request reserves tokens and dollars
under the job lock. Cost bounds include tool schemas, instructions, context, maximum output
and cache-write premiums. Cached reads, writes by lifetime and reasoning tokens come from
OpenAI usage. Reasoning tokens are already part of output usage and are not charged twice.
Per-inference pricing snapshots prevent later configuration edits from changing settled prices.

Successful usage replaces the reservation. Unknown outcomes after timeout, crash or
cancellation retain their conservative charge. If actual usage arrives later, it replaces
the unknown estimate exactly once, even after cancellation. OpenAI Responses normally reports
tokens rather than an invoice dollar amount: the UI labels dollars as estimates derived from
those reported tokens and configured rates. Inference rows retain response IDs for reconciliation
with account billing. Invoice discounts and account-specific adjustments are outside this ledger.

Before an unaffordable job-level generation call, the job is cancelled with budget_exhausted and active branches
are cancelled. Reported usage above a reservation stops further work. Concurrency, depth, total
agents, per-agent steps/tokens and total lifetime remain enforced independently.

Tool output is bounded. Long tool histories are summarized by the economical OpenAI model
when they reach eight observations or SUMMARY_TRIGGER_CHARS (default 16,000). The latest
observation remains verbatim; summaries and their watermarks are persisted, original steps
remain available, and later turns reuse the summary. These requests have the same hard budget
checks as other calls. ENABLE_CONTEXT_SUMMARIZATION can disable this optimization. Additional
context compaction explicitly marks omissions; it does not invent agent reasoning.

The dashboard streams accounted/reserved/remaining dollars, cached reads, cache writes,
reasoning tokens, unknown outcomes, per-model totals and individual agent costs. Allocation
and escalation reasons remain visible in agent details and the lifecycle audit.
