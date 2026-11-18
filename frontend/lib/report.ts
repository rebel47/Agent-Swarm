import type {Finding, Job} from "./api";
import {money, repositoryName, statusLabel} from "./format";

export const severities = ["critical", "high", "medium", "low", "info"] as const;

export function prioritizeFindings(findings: Finding[]) {
  return findings.map((finding, index) => ({finding, index})).sort((a, b) => {
    const rank = (severity: string) => {
      const position = severities.findIndex(value => value === severity);
      return position < 0 ? severities.length : position;
    };
    return rank(a.finding.severity) - rank(b.finding.severity) || a.index - b.index;
  });
}

function fenced(text: string, language = "") {
  const longest = Math.max(0, ...Array.from(text.matchAll(/`+/g), match => match[0].length));
  const fence = "`".repeat(Math.max(3, longest + 1));
  return `${fence}${language}\n${text}\n${fence}`;
}

export function reviewMarkdown(job: Job) {
  const report = job.report;
  if (!report) return "";
  const lines = [
    `# Code review: ${repositoryName(job.repository?.location || job.workspace_id)}`,
    "", `- Status: ${statusLabel(job.status)}`,
    `- Source: ${job.repository?.location || job.workspace_id}`,
    ...(job.repository?.revision ? [`- Revision: ${job.repository.revision}`] : []),
    `- Started: ${new Date(job.created_at * 1000).toISOString()}`,
    `- Estimated spend: ${money(job.metrics.estimated_cost_usd)}`,
    "", "## Review brief", "", job.objective,
    "", "## Summary", "", report.summary,
    "", `## Findings (${report.findings.length})`,
  ];
  for (const {finding} of prioritizeFindings(report.findings)) {
    lines.push("", `### [${finding.severity.toUpperCase()}] ${finding.title}`, "", finding.description,
      "", `Verification: ${finding.verification.replaceAll("_", " ")}`);
    for (const evidence of finding.evidence) {
      lines.push("", `Source: ${evidence.path}:${evidence.start_line}-${evidence.end_line}`,
        ...(evidence.symbol ? [`Symbol: ${evidence.symbol}`] : []), "", fenced(evidence.quote));
    }
    if (finding.uncertainty) lines.push("", `Uncertainty: ${finding.uncertainty}`);
  }
  if (!report.findings.length) lines.push("", "No findings were reported. This does not establish that the repository is free of defects.");
  if (report.unresolved_questions.length) {
    lines.push("", "## Unresolved questions", "", ...report.unresolved_questions.map(question => `- ${question}`));
  }
  if (report.proposed_patch) {
    lines.push("", "## Suggested patch", "", "Proposed for human review; not applied.", "", fenced(report.proposed_patch, "diff"));
  }
  return lines.join("\n") + "\n";
}

export function downloadReview(job: Job) {
  if (!job.report) return;
  const url = URL.createObjectURL(new Blob([reviewMarkdown(job)], {type: "text/markdown;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  const name = repositoryName(job.repository?.location || job.workspace_id).replace(/[^a-zA-Z0-9._-]/g, "-");
  link.download = `${name || "repository"}-review.md`;
  document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
