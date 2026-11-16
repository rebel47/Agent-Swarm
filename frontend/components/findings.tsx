import type {Result} from "../lib/api";
import {Icon} from "./ui";

export function Findings({result}: {result: Result | null}) {
  if (!result) return null;
  return <div className="findings">
    <section className="report-summary"><span className="eyebrow">The short version</span>
      <p>{result.summary}</p></section>
    <div className="findings-heading"><h2>{result.findings.length ? "What we found" : "No confirmed findings"}</h2>
      <span>{result.findings.length} {result.findings.length === 1 ? "finding" : "findings"}</span></div>
    {result.findings.map((finding, index) => <details key={index} className="finding-card" open={index === 0}>
      <summary><span className="finding-index">{String(index + 1).padStart(2, "0")}</span>
        <span className="finding-title"><span className={"severity severity-" + finding.severity}>{finding.severity}</span>
          <h3>{finding.title}</h3></span><Icon name="down" size={18} /></summary>
      <div className="finding-body"><p className="finding-description">{finding.description}</p>
        <details className="source-evidence"><summary><span><Icon name="code" size={16} />
          Source evidence <span className="count-pill">{finding.evidence.length}</span></span><Icon name="down" size={14} /></summary>
          <div>{finding.evidence.map((evidence, i) => <div key={i} className="evidence">
            <div className="evidence-path"><Icon name="file" size={14} /><code>{evidence.path}:{evidence.start_line}
              {evidence.end_line !== evidence.start_line ? " to " + evidence.end_line : ""}</code>
              {evidence.symbol && <span>{evidence.symbol}</span>}</div><pre>{evidence.quote}</pre></div>)}</div>
        </details>
        {finding.uncertainty && <p className="uncertainty"><Icon name="alert" size={15} />{finding.uncertainty}</p>}
        <span className="verification-label"><Icon name="check" size={13} />{finding.verification.replaceAll("_", " ")}</span>
      </div></details>)}
    {!!result.unresolved_questions.length && <details className="open-questions"><summary><span><Icon name="alert" size={16} />
      {result.unresolved_questions.length} {result.unresolved_questions.length === 1 ? "question" : "questions"} to resolve</span>
      <Icon name="down" size={15} /></summary><ul>{result.unresolved_questions.map(question => <li key={question}>{question}</li>)}</ul></details>}
    {result.proposed_patch && <details className="source-evidence patch-proposal"><summary><span><Icon name="code" size={16} />
      Suggested patch</span><span className="muted">For your review <Icon name="down" size={14} /></span></summary>
      <pre className="codeblock">{result.proposed_patch}</pre></details>}
  </div>;
}
