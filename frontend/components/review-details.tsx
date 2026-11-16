import type {Job} from "../lib/api";
import {money} from "../lib/format";
import {Drawer, Icon} from "./ui";

export function ReviewDetails({job, close}: {job: Job; close: () => void}) {
  const metrics = job.metrics;
  return <Drawer title="Review details" subtitle="Source, usage, and execution limits." close={close}>
    <h3>Repository snapshot</h3><dl className="detail-list"><div><dt>Source</dt><dd>{job.repository?.location || job.workspace_id}</dd></div>
      {job.repository && <><div><dt>Revision</dt><dd><code>{job.repository.revision}</code></dd></div>
        <div><dt>Files</dt><dd>{job.repository.file_count}</dd></div></>}</dl>
    <section className="settings-section"><h3>Usage &amp; budget</h3><dl className="detail-list">
      {[["Estimated spend", money(metrics.estimated_cost_usd)], ["Reserved for active requests", money(metrics.reserved_cost_usd)],
        ["Review budget", money(metrics.limits.cost_usd)], ["Accounted tokens", metrics.tokens.toLocaleString()],
        ["Cached input", metrics.cached_input_tokens.toLocaleString()], ["Cache writes", metrics.cache_write_tokens.toLocaleString()],
        ["Reasoning tokens", metrics.reasoning_tokens.toLocaleString()], ["Unreported usage calls", metrics.unknown_usage_calls],
        ["Peak concurrent agents", metrics.max_concurrency]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p className="field-help">Cost estimates use reported token usage and configured rates. Unreported requests retain their reservation.</p>
      <div className="model-costs">{Object.entries(metrics.model_costs).map(([model, cost]) =>
        <div key={model}><span>{model}</span><strong>{money(cost)}</strong></div>)}</div>
    </section>
    <details className="technical-details"><summary>Runtime configuration<Icon name="down" size={14} /></summary>
      <dl className="detail-list">{[["Mode", job.mode], ["Agent limit", metrics.limits.agents],
        ["Token limit", metrics.limits.tokens.toLocaleString()], ["Depth limit", metrics.limits.depth],
        ["Concurrency limit", metrics.limits.concurrency], ["Review ID", job.id], ["Trace", job.trace_id]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>
  </Drawer>;
}
