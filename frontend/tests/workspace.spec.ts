import {test, expect, type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";
import type {Job} from "../lib/api";

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

async function mockWorkspace(page: Page, restore = true, overrides: Partial<Job> = {}) {
  const existing = {...completed, ...overrides};
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
    if (path === "/jobs" && request.method() === "GET") return respond({items: [existing]});
    if (path === "/repositories" && request.method() === "POST") return respond({...completed.repository, id: "prepared-source"}, 201);
    if (path === "/jobs" && request.method() === "POST") {
      created = {...created, objective: request.postDataJSON().objective};
      return respond({id: "created-review", status: "RUNNING"}, 202);
    }
    if (path.endsWith("/events")) return route.fulfill({contentType: "text/event-stream",
      body: "event: snapshot\ndata: " + JSON.stringify(path.includes("created-review") ? created : existing) + "\n\n"});
    if (path.endsWith("/history")) return respond([{id: 1, type: "supervisor.decision", agent_id: null, created_at: 1700000130,
      data: {reason: "Source evidence is sufficient for a concise report."}}]);
    if (path.endsWith("/steps")) return respond({items: [{id: "step-1", name: "read_repository_file",
      arguments: {path: "app.py"}, output: {source: "example source"}, created_at: 1700000003}]});
    if (path === "/jobs/review-example") return respond(existing);
    if (path === "/jobs/created-review") return respond(created);
    return respond({detail: "Unexpected browser test endpoint: " + path}, 404);
  });
  return posts;
}

// Exercise the real SSE reader with a stream that stays open between updates.
async function liveStream(page: Page, initial: Job) {
  await page.addInitScript(snapshot => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.includes("/events?")) return originalFetch(input, init);
      const encoder = new TextEncoder();
      let cleanup = () => {};
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          const send = (type: string, data: unknown) => controller.enqueue(encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`));
          const emit = (event: Event) => {
            const {type, data} = (event as CustomEvent<{type: string; data: unknown}>).detail;
            send(type, data);
          };
          const disconnect = () => {cleanup(); controller.close();};
          cleanup = () => {
            window.removeEventListener("test-review-event", emit);
            window.removeEventListener("test-review-disconnect", disconnect);
            init?.signal?.removeEventListener("abort", disconnect);
          };
          window.addEventListener("test-review-event", emit);
          window.addEventListener("test-review-disconnect", disconnect);
          init?.signal?.addEventListener("abort", disconnect, {once: true});
          send("snapshot", snapshot);
        },
        cancel() {cleanup();},
      });
      return Promise.resolve(new Response(body, {headers: {"Content-Type": "text/event-stream"}}));
    };
  }, initial);
}

const inProgress: Job = {...completed, status: "RUNNING", ended_at: null, report: null,
  agents: completed.agents.map((agent, index) => ({...agent, status: index ? "QUEUED" : "RUNNING", error: null, ended_at: null}))};

test("the default live view shows the graph and becomes findings when the report arrives", async ({page}) => {
  let current = structuredClone(inProgress);
  await mockWorkspace(page, true, current);
  await liveStream(page, current);
  await page.route("**/api/v1/jobs/review-example", route => route.fulfill({contentType: "application/json", body: JSON.stringify(current)}));
  await page.goto("/?job=review-example");
  await expect(page.getByRole("tab", {name: "Live review", exact: true})).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("tabpanel", {name: "Live review"});
  const graph = panel.getByRole("region", {name: "Review team graph"});
  await expect(graph).toBeVisible();
  await expect(page.getByRole("region", {name: "Review team graph"})).toHaveCount(1);
  await expect(graph.locator(".react-flow__edge.animated")).toHaveCount(1);
  await expect(page.locator(".review-brief")).toBeHidden();
  await page.locator(".live-review-brief>summary").click();
  await expect(page.locator(".review-brief")).toHaveText(objective);
  await expect(page.locator(".review-brief")).toBeVisible();
  await page.locator(".live-review-brief>summary").click();
  const position = await graph.boundingBox();
  expect(position!.y).toBeLessThan(700);
  await page.screenshot({path: "test-results/live-review-desktop.png", fullPage: true});
  await graph.getByRole("button", {name: "View Pipeline investigator's work"}).click();
  await expect(page.getByRole("dialog", {name: "Pipeline investigator"})).toBeVisible();
  await page.keyboard.press("Escape");
  current = {...current, status: "COMPLETED", ended_at: 1700000135, report: completed.report,
    agents: current.agents.map(agent => ({...agent, status: "COMPLETED", ended_at: 1700000135}))};
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})), current);
  await expect(page.getByRole("heading", {name: "What we found"})).toBeVisible();
  await expect(page.getByRole("tab", {name: "Findings", exact: true})).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", {name: "Live review", exact: true})).toHaveCount(0);
  await expect(page.getByRole("region", {name: "Review team graph"})).toHaveCount(0);
  await page.getByRole("tab", {name: "Team"}).click();
  await expect(page.getByRole("region", {name: "Review team graph"})).toBeVisible();
  await expect(page.locator(".agent-row")).toHaveCount(2);
});

test("a report arriving preserves a user's selected activity tab", async ({page}) => {
  await mockWorkspace(page, true, inProgress);
  await liveStream(page, inProgress);
  await page.goto("/?job=review-example");
  await expect(page.getByRole("tab", {name: "Live review", exact: true})).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", {name: "Activity", exact: true}).click();
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})), completed);
  await expect(page.getByRole("tab", {name: "Findings", exact: true})).toHaveAttribute("aria-selected", "false");
  await expect(page.getByRole("tab", {name: "Activity", exact: true})).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", {name: "Activity", exact: true})).toBeFocused();
  await expect(page.getByRole("heading", {name: "Behind the review"})).toBeVisible();
});

test("a stopped review without a report keeps the graph available on the main tab", async ({page}) => {
  const stopped = {...inProgress, status: "CANCELLED", ended_at: 1700000135,
    agents: inProgress.agents.map(agent => ({...agent, status: "CANCELLED"}))};
  await mockWorkspace(page, true, stopped);
  await page.goto("/?job=review-example");
  await expect(page.getByRole("heading", {name: "This review ended before a report was ready."})).toBeVisible();
  const graph = page.getByRole("region", {name: "Review team graph"});
  await expect(graph).toBeVisible();
  await expect(graph.getByText("Review ended", {exact: true})).toBeVisible();
  await expect(graph.locator(".node-working, .react-flow__edge.animated")).toHaveCount(0);
  await expect(page.getByRole("button", {name: "View specialists"})).toBeVisible();
});

test("the team graph follows streamed review activity, keeps dragged positions and stops motion when finished", async ({page}) => {
  let current = structuredClone(inProgress);
  await mockWorkspace(page, true, current);
  await liveStream(page, current);
  await page.route("**/api/v1/jobs/review-example", route => route.fulfill({contentType: "application/json", body: JSON.stringify(current)}));
  await page.goto("/?job=review-example");
  await page.getByRole("tab", {name: "Team"}).click();
  const graph = page.getByRole("region", {name: "Review team graph"});
  const investigator = graph.locator('.react-flow__node[data-id="done"]');
  await expect(graph.getByText("Live review", {exact: true})).toBeVisible();
  await expect(investigator.locator(".node-working")).toHaveCount(1);
  await expect(graph.locator(".react-flow__edge.animated")).toHaveCount(1);
  await expect(graph.locator('.react-flow__node[data-id="stopped"] .node-working')).toHaveCount(0);
  await graph.getByRole("button", {name: "Focus active"}).click();
  await graph.getByRole("button", {name: "Fit team"}).click();
  const before = await investigator.getAttribute("style");
  const grip = await investigator.locator(".review-node-grip").boundingBox();
  expect(grip).not.toBeNull();
  await page.mouse.move(grip!.x + 15, grip!.y + 12);
  await page.mouse.down();
  await page.mouse.move(grip!.x + 55, grip!.y + 35, {steps: 8});
  await page.mouse.up();
  await expect.poll(() => investigator.getAttribute("style")).not.toBe(before);
  const arranged = await investigator.getAttribute("style");
  current = {...current, agents: current.agents.map(agent => agent.id === "done" ? {...agent, steps: 6, tokens: 25000} : agent)};
  await page.evaluate(job => {
    window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}}));
    window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "update", data: {
      id: 2, agent_id: "done", type: "tool.completed", created_at: 1700000131, data: {name: "read_repository_file"},
    }}}));
  }, current);
  await expect(investigator.getByText("Source file inspected", {exact: true})).toBeVisible();
  await expect(investigator.getByText(/6 steps.*25,000 tokens/)).toBeVisible();
  await expect(investigator).toHaveAttribute("style", arranged!);
  await expect(graph.getByLabel("Latest team activity")).toContainText("Pipeline investigator · Source file inspected");
  await page.screenshot({path: "test-results/team-live-desktop.png", fullPage: true});
  await graph.getByRole("button", {name: "View Pipeline investigator's work", exact: true}).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", {name: "Pipeline investigator"})).toBeVisible();
  await page.keyboard.press("Escape");
  current = {...current, status: "COMPLETED", ended_at: 1700000135, report: completed.report,
    agents: current.agents.map(agent => ({...agent, status: "COMPLETED", ended_at: 1700000135}))};
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})), current);
  await expect(graph.getByText("Review complete", {exact: true})).toBeVisible();
  await expect(graph.locator(".node-working, .react-flow__edge.animated")).toHaveCount(0);
  await expect(graph.getByRole("button", {name: "Focus active"})).toBeDisabled();
});

test("the graph pauses live motion when the event stream disconnects", async ({page}) => {
  await mockWorkspace(page, true, inProgress);
  await liveStream(page, inProgress);
  await page.goto("/?job=review-example");
  await page.getByRole("tab", {name: "Team"}).click();
  const graph = page.getByRole("region", {name: "Review team graph"});
  await expect(graph.getByText("Live review", {exact: true})).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("test-review-disconnect")));
  await expect(graph.getByText("Reconnecting", {exact: true})).toBeVisible();
  await expect(graph.locator(".node-working, .react-flow__edge.animated")).toHaveCount(0);
  await expect(graph.getByRole("button", {name: "View Pipeline investigator's work"})).toBeVisible();
});

test("growing teams keep connections when specialists change sides or delegate work", async ({page}) => {
  const third = {...inProgress.agents[0], id: "security", role: "Security investigator"};
  const initial = {...inProgress, agents: [...inProgress.agents, third]};
  const warnings: string[] = [];
  page.on("console", message => {if (message.text().includes("Couldn't create edge")) warnings.push(message.text());});
  await mockWorkspace(page, true, initial);
  await liveStream(page, initial);
  await page.goto("/?job=review-example");
  await page.getByRole("tab", {name: "Team"}).click();
  const graph = page.getByRole("region", {name: "Review team graph"});
  const security = graph.locator('.react-flow__node[data-id="security"]');
  await expect(security.locator('.react-flow__handle-left.target')).toHaveCount(1);
  const fourth = {...third, id: "verification", role: "Evidence investigator"};
  const expanded = {...initial, agents: [...initial.agents, fourth]};
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})), expanded);
  await expect(security.locator('.react-flow__handle-right.target')).toHaveCount(1);
  await expect(graph.locator(".react-flow__edge-path")).toHaveCount(4);
  const child = {...third, id: "child", parent_agent_id: third.id, depth: 1, role: "Citation verifier"};
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})),
    {...expanded, agents: [...expanded.agents, child]});
  await expect(graph.locator(".react-flow__node")).toHaveCount(6);
  await expect(graph.locator(".react-flow__edge-path")).toHaveCount(5);
  await graph.getByRole("button", {name: "Fit team"}).click();
  const cards = await graph.locator(".review-node").evaluateAll(nodes => nodes.map(node => {
    const {x, y, width, height} = node.getBoundingClientRect(); return {x, y, width, height};
  }));
  for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) {
    const a = cards[i], b = cards[j];
    expect(a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y).toBe(false);
  }
  expect(warnings).toEqual([]);
});

test("the default mobile graph shows team assembly and respects reduced motion", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.emulateMedia({reducedMotion: "reduce"});
  const planning = {...inProgress, agents: []};
  await mockWorkspace(page, true, planning);
  await liveStream(page, planning);
  await page.goto("/?job=review-example");
  await expect(page.getByRole("tab", {name: "Live review", exact: true})).toHaveAttribute("aria-selected", "true");
  const graph = page.getByRole("region", {name: "Review team graph"});
  await expect(graph.getByText("Planning", {exact: true})).toBeVisible();
  await expect(graph.locator(".react-flow__node")).toHaveCount(1);
  const position = await graph.boundingBox();
  expect(position!.y).toBeLessThan(700);
  await expect(graph.getByRole("button", {name: "Focus active"})).toBeDisabled();
  await page.evaluate(job => window.dispatchEvent(new CustomEvent("test-review-event", {detail: {type: "snapshot", data: job}})), inProgress);
  await expect(graph.locator(".react-flow__node")).toHaveCount(3);
  await graph.getByRole("button", {name: "Focus active"}).click();
  const active = graph.locator('.react-flow__node[data-id="done"] .review-node-status>i');
  await expect(active).toHaveCSS("animation-name", "none");
  await expect(graph.locator(".react-flow__edge.animated path").first()).toHaveCSS("animation-name", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: "test-results/live-review-mobile.png", fullPage: true});
  await graph.getByRole("button", {name: "View Pipeline investigator's work"}).click();
  await expect(page.getByRole("dialog", {name: "Pipeline investigator"})).toBeVisible();
});

test("workspace connection exposes a focused review form and keeps advanced controls secondary", async ({page}) => {
  await mockWorkspace(page, false);
  await page.goto("/");
  await expect(page.getByRole("heading", {name: "Welcome back."})).toBeVisible();
  await page.screenshot({path: "test-results/connect-desktop.png", fullPage: true});
  await page.getByLabel("Workspace access token").fill("browser-test-token");
  await page.getByRole("button", {name: "Enter workspace"}).click();
  await expect(page.getByRole("heading", {name: "Ship with a second opinion."})).toBeVisible();
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
  await expect(page.getByRole("heading", {name: "Reviewing your code"})).toBeVisible();
  await expect(page.getByRole("tab", {name: "Live review", exact: true})).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", {name: "Review team graph"})).toBeVisible();
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
  await page.locator(".agent-row").filter({hasText: "App and tools investigator"}).click();
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
  await expect(page.getByRole("heading", {name: "Ship with a second opinion."})).toBeVisible();
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

test("the default brief is ready to use and progress reflects actual specialists", async ({page}) => {
  const posts = await mockWorkspace(page);
  await page.goto("/");
  await expect(page.getByRole("button", {name: "General review", exact: true})).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Repository URL", {exact: true}).fill("https://github.com/team/project.git");
  await expect(page.getByRole("button", {name: "Start review"})).toBeEnabled();
  await page.getByRole("button", {name: "Start review"}).click();
  await expect(page.getByRole("progressbar", {name: "Specialists completed"})).toHaveAttribute("aria-valuenow", "1");
  await expect(page.getByRole("progressbar", {name: "Specialists completed"})).toHaveAttribute("aria-valuemax", "2");
  expect(posts.find(post => post.path === "/jobs")?.body.objective).toContain("Check surrounding code and callers");
});

test("findings sort by severity and combine severity filters with file search", async ({page}) => {
  const medium = completed.report.findings[0];
  await mockWorkspace(page, true, {report: {...completed.report, findings: [medium,
    {...medium, title: "Untrusted input reaches a query", severity: "critical", evidence: [{...medium.evidence[0], path: "database.py"}]},
    {...medium, title: "Authorization missing from export", severity: "high", evidence: [{...medium.evidence[0], path: "exports.py"}]},
  ]}});
  await page.goto("/?job=review-example");
  await expect(page.locator(".finding-title h3")).toHaveText([
    "Untrusted input reaches a query", "Authorization missing from export", medium.title,
  ]);
  await page.getByRole("button", {name: /^high/i}).click();
  await expect(page.locator(".finding-title h3")).toHaveText(["Authorization missing from export"]);
  await page.getByLabel("Search findings").fill("database.py");
  await expect(page.getByRole("status").filter({hasText: "No matching findings"})).toBeVisible();
  await page.getByRole("button", {name: "Clear filters"}).click();
  await page.getByLabel("Search findings").fill("DATABASE.PY");
  await expect(page.locator(".finding-title h3")).toHaveText(["Untrusted input reaches a query"]);
  await expect(page.getByText("state['scrape_result'] = result", {exact: true})).toBeVisible();
});

test("Markdown export includes source, evidence, uncertainty, questions, and unapplied patches", async ({page}) => {
  await mockWorkspace(page, true, {report: {...completed.report,
    findings: [...completed.report.findings, {...completed.report.findings[0], title: "A separate high priority issue", severity: "high"}],
    proposed_patch: "--- a/file.py\n+++ b/file.py\n+value = '```'"}});
  await page.goto("/?job=review-example");
  await page.getByRole("button", {name: /^medium/i}).click();
  await expect(page.getByRole("heading", {name: "A separate high priority issue"})).toHaveCount(0);
  const pending = page.waitForEvent("download");
  await page.getByRole("button", {name: "Export report"}).click();
  const download = await pending;
  expect(download.suggestedFilename()).toBe("research-system-review.md");
  const path = await download.path();
  expect(path).not.toBeNull();
  const markdown = await readFile(path!, "utf8");
  for (const text of ["# Code review: research-system", "abc1234567", objective, "pipeline.py:32-32",
    "state['scrape_result'] = result", "Runtime behavior was not tested.", "Should a partial failure stop the workflow?",
    "Proposed for human review; not applied.", "````diff", "A separate high priority issue"]) expect(markdown).toContain(text);
});

test("review again restores a Git repository, branch, and brief", async ({page}) => {
  await mockWorkspace(page, true, {repository: {...completed.repository, ref: "release/next"}});
  await page.goto("/?job=review-example");
  await page.getByRole("button", {name: "Review again"}).click();
  await expect(page.getByLabel("Repository URL", {exact: true})).toHaveValue(completed.repository.location);
  await expect(page.getByLabel("Review brief", {exact: true})).toHaveValue(objective);
  await page.getByText("Review options", {exact: true}).click();
  await expect(page.getByLabel("Branch or tag")).toHaveValue("release/next");
});

test("review again keeps local folders and registered sources in their correct source tabs", async ({page}) => {
  await mockWorkspace(page, true, {repository: {...completed.repository, kind: "local", location: "E:/projects/example"}});
  await page.goto("/?job=review-example");
  await page.getByRole("button", {name: "Review again"}).click();
  await expect(page.getByRole("tab", {name: "Local folder"})).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Local project path", {exact: true})).toHaveValue("E:/projects/example");
  await page.route("**/api/v1/jobs/review-example", route => route.fulfill({contentType: "application/json",
    body: JSON.stringify({...completed, workspace_id: "sample", repository: null})}));
  await page.route("**/api/v1/jobs/review-example/events?*", route => route.fulfill({contentType: "text/event-stream", body: ""}));
  await page.goto("/?job=review-example");
  await page.getByRole("button", {name: "Review again"}).click();
  await expect(page.getByRole("tab", {name: "Saved", exact: true})).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Saved repository")).toHaveValue("sample");
});

test("history search narrows reviews without changing the current review", async ({page}) => {
  await mockWorkspace(page);
  await page.goto("/?job=review-example");
  await page.getByLabel("Search reviews").fill("nothing matches");
  await expect(page.getByText("No matching reviews.", {exact: true})).toBeVisible();
  await expect(page.getByRole("heading", {name: "research-system", exact: true})).toBeVisible();
  await page.getByLabel("Search reviews").fill("CORRECTNESS");
  await expect(page.getByRole("navigation", {name: "Recent reviews"}).getByRole("button")).toHaveCount(1);
});

test("completed findings and the signed-out page fit a mobile screen", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockWorkspace(page);
  await page.goto("/?job=review-example");
  await expect(page.getByRole("heading", {name: "What we found"})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: "test-results/review-findings-mobile.png", fullPage: true});
  await page.getByRole("button", {name: "Open navigation"}).click();
  await page.getByRole("button", {name: "Disconnect workspace"}).click();
  await expect(page.getByRole("heading", {name: "Welcome back."})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: "test-results/connect-mobile.png", fullPage: true});
});

test("a report without findings keeps coverage limitations visible", async ({page}) => {
  await mockWorkspace(page, true, {report: {...completed.report, findings: []}});
  await page.goto("/?job=review-example");
  await expect(page.getByRole("heading", {name: "No confirmed findings"})).toBeVisible();
  await expect(page.getByText("Check the review summary and open questions", {exact: false})).toBeVisible();
  await expect(page.getByRole("button", {name: "Export report"})).toBeEnabled();
});
