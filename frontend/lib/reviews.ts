import {api, type Models, type RepositoryInfo, type Workspaces} from "./api";

export type ReviewInput = {
  repositoryId: string; location: string; ref: string; objective: string;
  mode: string; fixedCount: number; propose: boolean;
};
export type PreparationStage = "" | "Preparing source" | "Starting review";
export const reviewPrompts = [
  {label: "Find bugs", text: "Review this repository for correctness bugs. Explain each issue's root cause, cite exact file paths and line numbers, and suggest a minimal fix. State any uncertainty."},
  {label: "Security review", text: "Review the repository for security weaknesses supported by source evidence and missing input validation. Cite exact file paths and line numbers, explain the conditions needed for each issue, and suggest a minimal fix."},
  {label: "Edge cases", text: "Find missing edge case handling in this repository, including empty inputs, errors, boundaries, and partial failures. Cite exact source lines and suggest minimal fixes. Distinguish observed code behavior from uncertainty."},
];

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
