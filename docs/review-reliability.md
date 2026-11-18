# Review evidence and response recovery

Normal reviews use a shared token budget (`SHARED_AGENT_BUDGET=true`). The supervisor
cannot strand a specialist by assigning a small cumulative `token_budget` or turn count:
the runtime uses the review pool and administrator turn allowance. The default pool is
100 million tokens and $1,000, with 200 specialist turns, 400 supervisor turns and six
hours per review. A generous allowance is never an instruction to consume it.
Counting, generation reservations, context summaries, remaining-budget prompts and model
escalation all use the shared scope, including resumed checkpoints with older small specs.
Job limits still include concurrent reservations, actual usage, cache charges and unknown
outcomes. Provider context capacity remains independent of cumulative execution allowance.
`SHARED_AGENT_BUDGET=false` retains strict individual caps for intentional budget experiments.
Changing configuration does not rewrite completed review history or stored job-wide limits;
the higher job pool applies to new reviews. Update existing `.env` overrides before restarting.

Source observations are durable `ToolExecution` records. When an agent's older history is
summarized, the runtime also copies the exact numbered lines into a separate `source_evidence`
collection. This collection is deterministic: it does not depend on the summary model
reproducing quotations. Repeated reads merge by path and line number, preserving whitespace
and already-redacted text. The collection is saved in the same checkpoint as the prose summary
and restored after a worker restart.

The citation collection is bounded by `MAX_TOOL_OUTPUT_CHARS`. A separate index records earlier
read ranges, and omissions are explicit. Context compaction may remove excerpts to fit the
counted model allowance; agents are instructed to request the exact file and range again when
needed. Source-read output truncation preserves numbered lines and a continuation line rather
than slicing serialized JSON. A single oversized line produces a bounded error instead of a
misleading partial quotation. Final citations still pass the existing source-quote validator.

`list_repository_files` always reports `complete_repository_inventory: false`, even when its
returned list is not truncated. The listing describes authorized, reviewable snapshot files;
imports, excluded directories, file-type rules, size limits and scan limits can omit files.
An empty search or an unlisted path does not establish absence from the original repository.
The supervisor, investigator and synthesis instructions state this boundary. `.gitignore` is
now an authorized source file and is retained by new Git and local imports; secret files remain
excluded. Older saved snapshots retain the contents captured under their original import policy.

Malformed Responses API output retains reported usage for settlement before recovery. Safe
diagnostics distinguish incomplete output, unexpected call counts, invalid JSON, invalid result
fields and unoffered function names. The response ID and model are recorded; raw arguments and
source text are not added to diagnostics. Refusals and content-filter interruptions are not
retried. See the official [function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs) guidance.

For recoverable agent responses, an `invalid_response` observation provides format corrections
for the next leased execution turn. Each attempt consumes a step and its actual reported usage,
and the next request requires a fresh budget reservation. `MAX_RETRIES`, step limits, token and
cost limits, cancellation and lease fencing still apply. `llm.invalid_response` events and worker
warning logs record whether a retry was scheduled. A successful corrected turn clears the active
agent error. Structured supervisor/summary/synthesis failures also retain safe diagnostics and
use the existing bounded provider retry path.

The earlier review's generic failure message did not retain its response shape, so that exact
historical cause cannot be reconstructed. Offline SDK regression tests cover missing or wrapped
result fields, malformed JSON, multiple calls, incomplete responses, unoffered tools, refusal,
retry exhaustion and budget exhaustion without making paid inference requests.
