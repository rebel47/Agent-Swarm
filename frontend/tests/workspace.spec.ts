import {test, expect, type Page} from "@playwright/test";

const objective = "Review correctness and missing edge cases in the repository.";
const completed = {
  id: "review-example", objective, workspace_id: "source-example", mode: "adaptive", status: "COMPLETED",
  created_at: 1700000000, updated_at: 1700000135, ended_at: 1700000135, supervisor_steps: 6, trace_id: "example-trace",
  repository: {id: "source-example", kind: "git", location: "https://github.com/team/research-system.git",
    revision: "abc1234567", ref: null, status: "READY", file_count: 6, size_bytes: 17000, error: null, created_at: 1700000000},
  report: {summary: "The review identified an error-handling gap in the research workflow.",
    findings: [{title: "Scrape failures reach the report writer", severity: "medium",
      description: "A failed scrape is passed to the writer as research content. Return a structured failure and check it before constructing the report input.",
      uncertainty: "Runtime behavior was not tested.", verification: "source_observed",
      evidence: [{path: "pipeline.py", start_line: 32, end_line: 32, quote: "state['scrape_result'] = result"}]}],
    unresolved_questions: ["Should a partial failure stop the workflow?"]},
  error: null,
  agents: [
    {id: "done", role: "Pipeline investigator", objective: "Inspect pipeline error handling", status: "COMPLETED",
      tokens: 24050, cost_usd: 0.003, steps: 5, result: null, error: null},
    {id: "stopped", role: "App and tools investigator", objective: "Inspect application and tool edge cases", status: "FAILED",
      tokens: 23361, cost_usd: 0.003, steps: 4, result: null,
      error: {code: "agent_budget_exhausted", message: "Agent token allowance reached; supervisor may replan."}},
  ].map(agent => ({...agent, task_id: agent.id, parent_agent_id: null, depth: 0, allowed_tools: ["read_repository_file"],
    model: "gpt-6-luna", model_purpose: "routine", model_reason: "", dependencies: [],
    created_at: 1700000001, started_at: 1700000002, ended_at: 1700000120})),
  metrics: {total_agents: 2, tokens: 205772, estimated_cost_usd: 0.1454872, reserved_tokens: 0, reserved_cost_usd: 0,
    cached_input_tokens: 7152, cache_write_tokens: 0, reasoning_tokens: 1414, unknown_usage_calls: 0,
    model_allocation: {}, model_costs: {"gpt-6-luna": 0.017, "gpt-6-sol": 0.128},
    max_concurrency: 2, recoveries: 0, redundant_requests: 0,
    limits: {agents: 100, tokens: 1000000, cost_usd: 5, depth: 5, concurrency: 10},
    statuses: {COMPLETED: 1, FAILED: 1}},
};

async function mockWorkspace(page: Page, restore = true) {
  const posts: {path: string; body: Record<string, unknown>}[] = [];
  let created = {...completed, id: "created-review", status: "RUNNING", ended_at: null as number | null,
    report: null as typeof completed.report | null};
  if (restore) await page.addInitScript(() => sessionStorage.setItem("swarm-token", "browser-test-token"));
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace("/api/v1", "");
    const respond = (body: unknown, status = 200) => route.fulfill({status, contentType: "application/json", body: JSON.stringify(body)});
    if (request.headers().authorization !== "Bearer browser-test-token") return respond({detail: "Valid bearer authentication required"}, 401);
    if (request.method() === "POST") posts.push({path, body: request.postDataJSON()});
    if (path === "/workspaces") return respond({items: [{id: "sample", name: "sample", kind: "registered"}],
      local_roots: ["E:/projects"], git_hosts: ["github.com", "gitlab.com", "bitbucket.org"]});
    if (path === "/models") return respond({provider: "openai", connectivity_max_cost_usd: 0.1,
      allocation: {orchestrator: "gpt-6-sol", routine: "gpt-6-luna", verification: "gpt-6-sol", synthesis: "gpt-6-sol"},
      policies: {"gpt-6-sol": {input_per_million: 2, output_per_million: 10}, "gpt-6-luna": {input_per_million: 0.1, output_per_million: 0.5}}});
    if (path === "/jobs" && request.method() === "GET") return respond({items: [completed]});
    if (path === "/repositories" && request.method() === "POST") return respond({...completed.repository, id: "prepared-source"}, 201);
    if (path === "/jobs" && request.method() === "POST") {
      created = {...created, objective: request.postDataJSON().objective};
      return respond({id: "created-review", status: "RUNNING"}, 202);
    }
    if (path.endsWith("/events")) return route.fulfill({contentType: "text/event-stream",
      body: "event: snapshot\ndata: " + JSON.stringify(path.includes("created-review") ? created : completed) + "\n\n"});
    if (path.endsWith("/history")) return respond([{id: 1, type: "supervisor.decision", agent_id: null, created_at: 1700000130,
      data: {reason: "Source evidence is sufficient for a concise report."}}]);
    if (path.endsWith("/steps")) return respond({items: [{id: "step-1", name: "read_repository_file",
      arguments: {path: "app.py"}, output: {source: "example source"}, created_at: 1700000003}]});
    if (path === "/jobs/review-example") return respond(completed);
    if (path === "/jobs/created-review") return respond(created);
    return respond({detail: "Unexpected browser test endpoint: " + path}, 404);
  });
  return posts;
}

test("workspace connection exposes a focused review form and keeps advanced controls secondary", async ({page}) => {
  await mockWorkspace(page, false);
  await page.goto("/");
  await page.getByLabel("Workspace access token").fill("browser-test-token");
  await page.getByRole("button", {name: "Enter workspace"}).click();
  await expect(page.getByRole("heading", {name: "What could your code do better?"})).toBeVisible();
  await expect(page.getByRole("button", {name: "Start review"})).toBeDisabled();
  await expect(page.getByText("OpenAI models", {exact: true})).toHaveCount(0);
  await expect(page.getByLabel("Branch or tag")).toBeHidden();
  await expect(page.getByText("Agent graph", {exact: true})).toHaveCount(0);
  await page.screenshot({path: "test-results/new-review-desktop.png", fullPage: true});
  await page.getByRole("button", {name: "Workspace settings"}).click();
  await expect(page.getByRole("dialog", {name: "Workspace settings"})).toBeVisible();
  await expect(page.getByText("Sends a billable request", {exact: false})).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("a Git review submits the branch, brief and configured models without a real API call", async ({page}) => {
  const posts = await mockWorkspace(page);
  await page.goto("/");
  await page.getByLabel("Repository URL", {exact: true}).fill("https://github.com/team/project.git");
  await page.getByRole("button", {name: "Find bugs"}).click();
  await page.getByText("Review options", {exact: true}).click();
  await page.getByLabel("Branch or tag").fill("main");
  await page.getByLabel("Include suggested patches").check();
  await page.getByRole("button", {name: "Start review"}).click();
  await expect(page).toHaveURL(/job=created-review/);
  const preparation = posts.find(post => post.path === "/repositories");
  expect(preparation?.body).toEqual({location: "https://github.com/team/project.git", ref: "main"});
  const review = posts.find(post => post.path === "/jobs")?.body;
  expect(review?.workspace_id).toBe("prepared-source");
  expect(review?.allow_patch_proposals).toBe(true);
  expect(review?.model_overrides).toEqual({orchestrator: "gpt-6-sol", routine: "gpt-6-luna", verification: "gpt-6-sol", synthesis: "gpt-6-sol"});
  await expect(page.getByText("Your code is getting a closer look.")).toBeVisible();
});

test("local folders and saved snapshots use the correct source flow", async ({page}) => {
  const posts = await mockWorkspace(page);
  await page.goto("/");
  await page.getByRole("tab", {name: "Local folder"}).click();
  await page.getByLabel("Local project path", {exact: true}).fill("E:/projects/example");
  await page.getByRole("button", {name: "Edge cases", exact: true}).click();
  await page.getByRole("button", {name: "Start review"}).click();
  await expect(page).toHaveURL(/job=created-review/);
  expect(posts.find(post => post.path === "/repositories")?.body).toEqual({location: "E:/projects/example", ref: null});
  await page.getByRole("button", {name: "New review", exact: false}).click();
  await page.getByRole("tab", {name: "Saved", exact: true}).click();
  await page.getByLabel("Saved repository").selectOption("sample");
  await page.getByRole("button", {name: "Find bugs"}).click();
  await page.getByRole("button", {name: "Start review"}).click();
  await expect.poll(() => posts.filter(post => post.path === "/jobs").length).toBe(2);
  expect(posts.filter(post => post.path === "/repositories")).toHaveLength(1);
  expect(posts.filter(post => post.path === "/jobs")[1].body.workspace_id).toBe("sample");
});

test("completed reviews prioritize findings, with agent failures and diagnostics available on demand", async ({page}) => {
  await mockWorkspace(page);
  await page.goto("/?job=review-example");
  await expect(page.getByRole("heading", {name: "research-system", exact: true})).toBeVisible();
  await expect(page.getByRole("heading", {name: "What we found"})).toBeVisible();
  await expect(page.getByText("Agent token allowance reached", {exact: false})).toHaveCount(0);
  await expect(page.getByText("Accounted tokens", {exact: true})).toHaveCount(0);
  await page.screenshot({path: "test-results/review-findings-desktop.png", fullPage: true});
  await page.getByRole("tab", {name: "Team"}).click();
  await page.getByRole("button", {name: /App and tools investigator/}).click();
  await expect(page.getByRole("dialog", {name: "App and tools investigator"})).toBeVisible();
  await expect(page.getByText("This agent reached its token allowance.", {exact: true})).toBeVisible();
  await page.getByRole("button", {name: "Close panel"}).click();
  await page.getByRole("button", {name: "Details", exact: true}).click();
  await expect(page.getByRole("dialog", {name: "Review details"})).toBeVisible();
  await expect(page.getByText("Accounted tokens", {exact: true})).toBeVisible();
  await page.getByRole("button", {name: "Close panel"}).click();
  await page.getByRole("tab", {name: "Activity"}).click();
  await expect(page.getByText("Source evidence is sufficient for a concise report.")).toBeVisible();
});

test("mobile navigation, dialogs and the form fit a narrow screen", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockWorkspace(page);
  await page.goto("/");
  await expect(page.getByRole("heading", {name: "What could your code do better?"})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: "test-results/new-review-mobile.png", fullPage: true});
  await page.getByRole("button", {name: "Open navigation"}).click();
  await page.getByRole("button", {name: "Workspace settings"}).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await page.getByRole("dialog").evaluate(element => element.getBoundingClientRect().right <= window.innerWidth)).toBe(true);
});

test("source and review tabs support keyboard navigation", async ({page}) => {
  await mockWorkspace(page);
  await page.goto("/");
  await page.getByRole("tab", {name: "Git repository"}).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByLabel("Local project path", {exact: true})).toBeVisible();
  await expect(page.getByRole("tab", {name: "Local folder"})).toBeFocused();
  await page.goto("/?job=review-example");
  await page.getByRole("tab", {name: "Findings", exact: true}).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("heading", {name: "A team shaped by the review"})).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("heading", {name: "Behind the review"})).toBeVisible();
});

test("an accepted review stays open if the workspace list cannot refresh", async ({page}) => {
  const posts = await mockWorkspace(page);
  let workspaceLoads = 0;
  await page.route("**/api/v1/workspaces", async route => {
    workspaceLoads++;
    if (workspaceLoads === 1) return route.fallback();
    return route.fulfill({status: 503, contentType: "application/json", body: JSON.stringify({detail: "Temporarily unavailable"})});
  });
  await page.goto("/");
  await page.getByLabel("Repository URL", {exact: true}).fill("https://github.com/team/project.git");
  await page.getByRole("button", {name: "Find bugs"}).click();
  await page.getByRole("button", {name: "Start review"}).click();
  await expect(page).toHaveURL(/job=created-review/);
  await expect(page.getByRole("alert").filter({hasText: "Your review has started"})).toBeVisible();
  expect(posts.filter(post => post.path === "/jobs")).toHaveLength(1);
});
