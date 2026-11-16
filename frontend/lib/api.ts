export type Finding = {
  title: string; description: string; severity: string; uncertainty: string; verification: string;
  evidence: {path: string; start_line: number; end_line: number; quote: string; symbol?: string}[];
};
export type Result = {
  summary: string; findings: Finding[]; unresolved_questions: string[]; proposed_patch?: string;
};
export type Agent = {
  id: string; task_id: string; parent_agent_id: string | null; role: string; objective: string;
  status: string; depth: number; allowed_tools: string[]; model: string; model_purpose: string; model_reason: string; steps: number;
  tokens: number; cost_usd: number; result: Result | null;
  error: {code: string; message: string; retryable?: boolean} | null;
  dependencies: string[]; created_at: number; started_at: number | null; ended_at: number | null;
};
export type Job = {
  id: string; objective: string; workspace_id: string; mode: string; status: string;
  created_at: number; updated_at: number; ended_at: number | null; supervisor_steps: number;
  trace_id: string; repository: RepositoryInfo | null; report: Result | null; error: {code: string; message: string} | null;
  agents: Agent[]; metrics: {
    total_agents: number; tokens: number; estimated_cost_usd: number; reserved_tokens: number;
    cached_input_tokens: number; cache_write_tokens: number; reasoning_tokens: number; unknown_usage_calls: number;
    model_allocation: Record<string, string>; model_costs: Record<string, number>;
    reserved_cost_usd: number; max_concurrency: number; recoveries: number; redundant_requests: number;
    limits: {agents: number; tokens: number; cost_usd: number; depth: number; concurrency: number};
    statuses: Record<string, number>;
  };
};
export type AuditEvent = {
  id: number; type: string; agent_id: string | null; created_at: number;
  data: Record<string, unknown>;
};
export type Step = {
  id: string; name: string; arguments: Record<string, unknown>;
  output: Record<string, unknown>; created_at: number;
};
export type JobSummary = {id: string; objective: string; status: string; created_at: number};
const base = "/api/v1";

export async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + path, {
    ...init, cache: "no-store",
    headers: {"Content-Type": "application/json", Authorization: "Bearer " + token, ...init?.headers},
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: response.statusText}));
    const detail = error.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ?
      detail.map((item: {msg?: string}) => item.msg || "Invalid request").join(". ") :
      detail?.message || "The request could not be completed. Please try again.");
  }
  return response.json();
}

export async function events(
  jobId: string, token: string, signal: AbortSignal,
  snapshot: (job: Job) => void, update: (event: AuditEvent) => void,
  connection: (message: string) => void,
) {
  let cursor = Number(sessionStorage.getItem("swarm-cursor-" + jobId) || 0);
  let failures = 0;
  while (!signal.aborted) {
    try {
      const response = await fetch(base + "/jobs/" + jobId + "/events?after=" + cursor, {
        signal, cache: "no-store", headers: {Authorization: "Bearer " + token, Accept: "text/event-stream"},
      });
      if (!response.ok || !response.body) {
        if (response.status === 401 || response.status === 404) {
          connection("Event access failed (" + response.status + "); reconnect your session.");
          return;
        }
        throw new Error("Event stream returned " + response.status);
      }
      connection("Live"); failures = 0;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "", terminal = false;
      try {
        while (!signal.aborted) {
          const {value, done} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream: true}).replace(/\r\n/g, "\n");
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
            const lines = block.split("\n");
            const type = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
            const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
            const id = lines.find(line => line.startsWith("id:"))?.slice(3).trim();
            if (!data) continue;
            if (type === "snapshot") {
              const job = JSON.parse(data) as Job;
              snapshot(job); terminal = job.status !== "RUNNING";
            } else if (type === "update") {
              update(JSON.parse(data) as AuditEvent);
            }
            if (id) {
              cursor = Number(id);
              sessionStorage.setItem("swarm-cursor-" + jobId, String(cursor));
            }
          }
        }
      } finally {
        await reader.cancel().catch(() => {});
      }
      if (terminal) { connection("History synced"); return; }
      throw new Error("Stream closed; reconnecting");
    } catch (error) {
      if (signal.aborted) return;
      failures++;
      connection(error instanceof Error ? error.message : "Reconnecting");
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, Math.min(10000, 1000 * 2 ** Math.min(failures, 4)));
        signal.addEventListener("abort", () => {clearTimeout(timer); resolve();}, {once: true});
      });
    }
  }
}


export type Models = {provider: string; allocation: Record<string, string>; policies: Record<string, {input_per_million: number; output_per_million: number}>; connectivity_max_cost_usd: number};

export type RepositoryInfo = {
  id: string; kind: string; location: string; ref: string | null; revision: string | null;
  status: string; file_count: number; size_bytes: number; error: {code: string; message: string} | null;
  created_at: number;
};
export type Workspaces = {
  items: {id: string; name: string; kind: string}[];
  local_roots: string[]; git_hosts: string[];
};
