"use client";
import {useState} from "react";
import type {Result} from "../lib/api";
import {prioritizeFindings, severities} from "../lib/report";
import {Icon} from "./ui";

export function Findings({result}: {result: Result | null}) {
  const [severity, setSeverity] = useState("all"), [query, setQuery] = useState("");
  if (!result) return null;
  const search = query.trim().toLowerCase();
  const filtered = prioritizeFindings(result.findings).filter(({finding}) =>
    (severity === "all" || finding.severity === severity) &&
    (!search || [finding.title, finding.description, ...finding.evidence.map(item => item.path)]
      .some(value => value.toLowerCase().includes(search))));
  return <div className="findings">
    <section className="report-summary"><span className="eyebrow"><Icon name="file" size={14} />Review summary</span>
      <p>{result.summary}</p></section>
    <div className="findings-heading"><h2>{result.findings.length ? "What we found" : "No confirmed findings"}</h2>
      <span>{result.findings.length ? "Highest severity first" : "Within this review’s scope"}</span></div>
    {!!result.findings.length && <div className="finding-controls"><div className="severity-filters" aria-label="Filter findings by severity">
      {["all", ...severities.filter(value => result.findings.some(finding => finding.severity === value))].map(value =>
        <button key={value} aria-pressed={severity === value} className={severity === value ? "selected" : ""}
          onClick={() => setSeverity(value)}>{value === "all" ? "All findings" : value}<span>
            {value === "all" ? result.findings.length : result.findings.filter(finding => finding.severity === value).length}</span></button>)}</div>
      <div className="finding-search"><Icon name="search" size={15} /><input aria-label="Search findings"
        placeholder="Search findings or files..." value={query} onChange={event => setQuery(event.target.value)} /></div>
    </div>}
    {filtered.map(({finding, index}, position) => <details key={index} className="finding-card" open={position === 0}>
      <summary><span className="finding-index">{String(position + 1).padStart(2, "0")}</span>
        <span className="finding-title"><span className={"severity severity-" + finding.severity}>{finding.severity}</span>
          <h3>{finding.title}</h3><span className="finding-location"><Icon name="file" size={12} />
            {finding.evidence[0]?.path}:{finding.evidence[0]?.start_line}</span></span><Icon name="down" size={18} /></summary>
      <div className="finding-body"><p className="finding-description">{finding.description}</p>
        <details className="source-evidence" open={position === 0}><summary><span><Icon name="code" size={16} />
          Source evidence <span className="count-pill">{finding.evidence.length}</span></span><Icon name="down" size={14} /></summary>
          <div>{finding.evidence.map((evidence, i) => <div key={i} className="evidence">
            <div className="evidence-path"><Icon name="file" size={14} /><code>{evidence.path}:{evidence.start_line}
              {evidence.end_line !== evidence.start_line ? " to " + evidence.end_line : ""}</code>
              {evidence.symbol && <span>{evidence.symbol}</span>}</div><pre>{evidence.quote}</pre></div>)}</div>
        </details>
        {finding.uncertainty && <p className="uncertainty"><Icon name="alert" size={15} />{finding.uncertainty}</p>}
        <span className="verification-label"><Icon name="check" size={13} />{finding.verification.replaceAll("_", " ")}</span>
      </div></details>)}
    {!!result.findings.length && !filtered.length && <div className="findings-empty" role="status"><Icon name="search" size={23} />
      <h3>No matching findings</h3><p>Try another severity or search term.</p>
      <button className="text-button" onClick={() => {setSeverity("all"); setQuery("");}}>Clear filters<Icon name="refresh" size={14} /></button></div>}
    {!result.findings.length && <div className="findings-empty"><span className="empty-check"><Icon name="check" size={22} /></span>
      <h3>No findings to triage.</h3><p>Check the review summary and open questions for coverage gaps and remaining uncertainty.</p></div>}
    {!!result.unresolved_questions.length && <details className="open-questions"><summary><span><Icon name="alert" size={16} />
      {result.unresolved_questions.length} {result.unresolved_questions.length === 1 ? "question" : "questions"} to resolve</span>
      <Icon name="down" size={15} /></summary><ul>{result.unresolved_questions.map(question => <li key={question}>{question}</li>)}</ul></details>}
    {result.proposed_patch && <details className="source-evidence patch-proposal"><summary><span><Icon name="code" size={16} />
      Suggested patch</span><span className="muted">For your review <Icon name="down" size={14} /></span></summary>
      <pre className="codeblock">{result.proposed_patch}</pre></details>}
  </div>;
}
