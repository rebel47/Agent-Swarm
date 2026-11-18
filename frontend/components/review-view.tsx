"use client";
import dynamic from "next/dynamic";
import {useState} from "react";
import type {AuditEvent, Job} from "../lib/api";
import {dateLabel, elapsed, money, repositoryName, statusLabel} from "../lib/format";
import {downloadReview} from "../lib/report";
import {Findings} from "./findings";
import {AgentInspector} from "./agent-inspector";
import {ReviewDetails} from "./review-details";
import {Icon, StatusBadge, navigateTabs} from "./ui";

const AgentGraph = dynamic(() => import("./agent-graph").then(module => module.AgentGraph),
  {ssr: false, loading: () => <div className="graph graph-loading"><span className="spinner" />Loading team...</div>});

export function ReviewView({job, audit, now, token, connection, onError, cancel, again}: {
  job: Job; audit: AuditEvent[]; now: number; token: string; onError: (message: string) => void;
  connection: string; cancel: () => Promise<void>; again: () => void;
}) {
  const [tab, setTab] = useState("findings"), [selectedId, setSelectedId] = useState("");
  const [details, setDetails] = useState(false), [showRequests, setShowRequests] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const selected = job.agents.find(agent => agent.id === selectedId);
  const seconds = Math.max(0, Math.floor((job.ended_at || now / 1000) - job.created_at));
  const spent = job.metrics.estimated_cost_usd, reserved = job.metrics.reserved_cost_usd;
  const finished = job.agents.filter(agent => agent.status === "COMPLETED").length;
  const active = job.agents.filter(agent => agent.status === "RUNNING" || agent.status === "QUEUED");
  const sourceSteps = job.agents.reduce((total, agent) => total + agent.steps, 0);
  const priorityCount = job.report?.findings.filter(finding => ["critical", "high"].includes(finding.severity)).length || 0;
  const title = repositoryName(job.repository?.location || job.workspace_id);
  const timeline = audit.filter(event => showRequests || !event.type.startsWith("llm."));
  function eventTitle(event: AuditEvent) {
    const role = job.agents.find(agent => agent.id === event.agent_id)?.role;
    if (event.type === "agent.status") return (role || "Agent") + ": " + statusLabel(String(event.data.status || ""));
    return ({"supervisor.decision": "Review plan updated", "agent.created": "A specialist joined the team",
      "job.status": "Review " + statusLabel(String(event.data.status || "")).toLowerCase(),
      "tool.completed": "Source inspection", "execution.error": "Agent stopped",
      "llm.started": "Model request started", "llm.usage": "Model usage recorded"} as Record<string, string>)[event.type] || event.type.replaceAll(".", " ");
  }
  return <div className="review-view"><header className="review-header"><div><div className="review-heading-meta">
    <StatusBadge status={job.status} /><span>{dateLabel(job.created_at)}</span></div><h1>{title}</h1>
    <p className="review-brief">{job.objective}</p><div className="review-source-meta"><Icon name="git" size={14} />
      <span>{job.repository?.revision?.slice(0, 7) || "Workspace source"}</span><span>&middot;</span>
      <Icon name="clock" size={14} /><span>{elapsed(seconds)}</span>
      {job.repository && <><span>&middot;</span><span>{job.repository.file_count} source files</span></>}</div></div>
    <div className="review-actions">{job.report && <button className="button button-secondary" onClick={() => downloadReview(job)}>
      <Icon name="download" size={15} />Export report</button>}<button className="button button-secondary" onClick={() => setDetails(true)}>
      <Icon name="settings" size={16} />Details</button>{job.status === "RUNNING" ?
      <button className="button button-quiet" disabled={cancelling} onClick={async () => {
        setCancelling(true); try {await cancel();} finally {setCancelling(false);}
      }}>
        {cancelling ? "Stopping..." : "Stop review"}</button> :
      <button className="button button-quiet" onClick={again}>Review again<Icon name="arrow" size={16} /></button>}</div>
    </header>
    {job.error && <div className="inline-message message-error" role="alert"><strong>{job.error.code.replaceAll("_", " ")}</strong>
      <p>{job.error.message}</p></div>}
    <section className="review-overview" aria-label="Review overview"><div><span className="overview-label">Findings</span>
      <strong>{job.report ? job.report.findings.length : "Pending"}</strong><span className="overview-note">
        {job.report ? priorityCount ? `${priorityCount} high or critical` : "Source evidence attached" : "Review in progress"}</span></div>
      <div><span className="overview-label">Review team</span><strong>{finished}<span> / {job.agents.length}</span></strong>
        <button className="overview-link" onClick={() => setTab("team")}>specialists completed<Icon name="chevron" size={12} /></button></div>
      <div><span className="overview-label">Estimated spend</span><strong>{money(spent)}</strong>
        <span className="overview-note">of {money(job.metrics.limits.cost_usd)} budget</span>
        <meter className="budget-meter" min={0} max={job.metrics.limits.cost_usd}
          value={Math.min(spent + reserved, job.metrics.limits.cost_usd)} aria-label="Review budget used" /></div>
    </section>
    <div className="review-tabbar"><div className="review-tabs" role="tablist" aria-label="Review sections" onKeyDown={navigateTabs}>
      {[["findings", "file", "Findings"], ["team", "team", "Team"], ["activity", "activity", "Activity"]].map(([value, icon, label]) =>
        <button key={value} role="tab" aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} className={tab === value ? "active" : ""}
          onClick={() => setTab(value)}><Icon name={icon as "file" | "team" | "activity"} size={16} />{label}
          {value === "team" && <span className="count-pill">{job.agents.length}</span>}</button>)}</div>
      {job.status === "RUNNING" && <span className="live-indicator" title={connection}><span className="online-dot" />
        {connection === "Live" ? "Live" : "Reconnecting..."}</span>}</div>
    <section className="review-tab-content" role="tabpanel" aria-label={tab}>
      {tab === "findings" && (job.report ? <Findings result={job.report} /> :
        <div className="review-progress"><div className={"progress-orbit " + (job.status === "RUNNING" ? "orbit-active" : "")}>
          <Icon name={job.status === "RUNNING" ? "code" : "file"} size={28} /><i /><i /><i /></div>
          <h2>{job.status === "RUNNING" ? job.agents.length ? "Your code is getting a closer look." : "Putting the right team together." :
            "This review ended before a report was ready."}</h2><p>{job.status === "RUNNING" ?
            "Specialists are following the evidence. Findings will appear here when the review is ready." :
            "You can inspect the team's work or start a new review."}</p>
          <div className="progress-stages"><span className="done"><Icon name="check" size={14} />Repository ready</span><i />
            <span className={job.status === "RUNNING" ? "current" : ""}>Inspecting source</span><i /><span>Final report</span></div>
          {!!job.agents.length && <div className="progress-work" aria-label="Review progress"><div className="progress-work-heading">
            <span>{finished} of {job.agents.length} specialists completed</span><span>{sourceSteps} execution steps</span></div>
            <div className="specialist-progress" role="progressbar" aria-label="Specialists completed" aria-valuemin={0}
              aria-valuemax={job.agents.length} aria-valuenow={finished}><span style={{width: `${finished / job.agents.length * 100}%`}} /></div>
            {!!active.length && <p><span className="online-dot" />{active.slice(0, 2).map(agent => agent.role).join(" · ")}
              {active.length > 2 ? ` +${active.length - 2} more` : ""}</p>}</div>}
          <button className="text-button" onClick={() => setTab("team")}>See the team at work<Icon name="arrow" size={14} /></button></div>)}
      {tab === "team" && <div className="team-view"><div className="section-title"><div><h2>A team shaped by the review</h2>
        <p>Each specialist follows a focused line of investigation.</p></div><span>{job.agents.length} specialists</span></div>
        <AgentGraph key={job.id} job={job} audit={audit} connection={connection} select={setSelectedId} />
        <div className="agent-list">{job.agents.map(agent => <button key={agent.id} className="agent-row" onClick={() => setSelectedId(agent.id)}>
          <span className="agent-avatar"><Icon name="code" size={17} /></span><span className="agent-row-copy"><strong>{agent.role}</strong>
            <small>{agent.objective}</small></span><StatusBadge status={agent.status} budget={agent.error?.code === "agent_budget_exhausted"} />
            <Icon name="chevron" size={16} /></button>)}</div>
      </div>}
      {tab === "activity" && <div className="activity-view"><div className="section-title"><div><h2>Behind the review</h2>
        <p>The team&apos;s decisions, source inspections, and milestones.</p></div>
        <label className="checkbox-label"><input type="checkbox" checked={showRequests}
          onChange={event => setShowRequests(event.target.checked)} />Model requests</label></div>
        <ol className="timeline">{[...timeline].reverse().map(event => <li key={event.id}>
          <span className={"timeline-dot " + (event.type === "execution.error" ? "timeline-warning" : "")} />
          <div><strong>{eventTitle(event)}</strong>{!!(event.data.reason || event.data.message || event.data.name) &&
            <p>{String(event.data.reason || event.data.message || event.data.name).replaceAll("_", " ")}</p>}</div>
          <time>{new Date(event.created_at * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}</time>
        </li>)}</ol>{!timeline.length && <p className="empty-note">The first review updates will appear here.</p>}</div>}
    </section>
    {details && <ReviewDetails job={job} close={() => setDetails(false)} />}
    {selected && <AgentInspector agent={selected} jobId={job.id} token={token} close={() => setSelectedId("")} onError={onError} />}
  </div>;
}
