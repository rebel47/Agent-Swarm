import {api, type Job, type Models, type RepositoryInfo, type Workspaces} from "./api";

export type ReviewInput = {
  repositoryId: string; location: string; ref: string; objective: string;
  mode: string; fixedCount: number; propose: boolean;
};
export type ReviewDraft = Partial<ReviewInput> & {sourceType?: "git" | "local" | "saved"};
export type PreparationStage = "" | "Preparing source" | "Starting review";
export const reviewPrompts = [
  {label: "General review", text: "Review this repository for actionable correctness bugs, security weaknesses, and missing error handling. Prioritize issues with concrete impact. For each finding, explain the trigger, root cause, and minimal fix, and cite exact source lines. Check surrounding code and callers before reporting an issue. Avoid style preferences and speculative findings. State uncertainty and coverage gaps."},
  {label: "Find bugs", text: "Review this repository for correctness bugs. Explain each issue's root cause, cite exact file paths and line numbers, and suggest a minimal fix. State any uncertainty."},
  {label: "Security review", text: "Review the repository for security weaknesses supported by source evidence and missing input validation. Cite exact file paths and line numbers, explain the conditions needed for each issue, and suggest a minimal fix."},
  {label: "Performance", text: "Investigate performance bottlenecks supported by repository source, including unnecessary repeated work, unbounded operations, inefficient queries, and resource leaks. Explain when each issue matters and suggest a minimal fix with exact source citations. Distinguish source-based hypotheses from measured performance; do not claim benchmarks were run."},
  {label: "Edge cases", text: "Find missing edge case handling in this repository, including empty inputs, errors, boundaries, and partial failures. Cite exact source lines and suggest minimal fixes. Distinguish observed code behavior from uncertainty."},
];

export function draftFromReview(job: Job): ReviewDraft {
  const sourceType = job.repository ? job.repository.kind === "git" ? "git" : "local" : "saved";
  return {sourceType, repositoryId: sourceType === "saved" ? job.workspace_id : "",
    location: job.repository?.location || "", ref: job.repository?.ref || "", objective: job.objective,
    mode: job.mode, propose: !!job.report?.proposed_patch};
}

export async function startReview(token: string, input: ReviewInput, allocation: Models["allocation"],
  stage: (value: PreparationStage) => void) {
  let repositoryId = input.repositoryId;
  if (!repositoryId) {
    stage("Preparing source");
    const source = await api<RepositoryInfo>("/repositories", token, {method: "POST",
      body: JSON.stringify({location: input.location.trim(), ref: input.ref.trim() || null})});
    repositoryId = source.id;
  }
  stage("Starting review");
  return api<{id: string}>("/jobs", token, {method: "POST",
    headers: {"Idempotency-Key": crypto.randomUUID()},
    body: JSON.stringify({objective: input.objective.trim(), workspace_id: repositoryId, mode: input.mode,
      fixed_agent_count: input.mode === "fixed" ? input.fixedCount : null,
      allow_patch_proposals: input.propose,
      model_overrides: Object.fromEntries(Object.entries(allocation).filter(([role]) =>
        ["orchestrator", "routine", "verification", "synthesis"].includes(role)))})});
}

export async function loadWorkspace(token: string) {
  const [sources, models, history] = await Promise.all([
    api<Workspaces>("/workspaces", token), api<Models>("/models", token),
    api<{items: import("./api").JobSummary[]}>("/jobs?limit=50", token),
  ]);
  return {sources, models, history: history.items};
}
