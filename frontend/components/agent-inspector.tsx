"use client";
import {useEffect, useState} from "react";
import {api, type Agent, type Step} from "../lib/api";
import {money} from "../lib/format";
import {Drawer, Icon, StatusBadge} from "./ui";
import {Findings} from "./findings";

export function AgentInspector({agent, jobId, token, close, onError}: {
  agent: Agent; jobId: string; token: string; close: () => void; onError: (message: string) => void;
}) {
  const [steps, setSteps] = useState<Step[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    void api<{items: Step[]}>("/jobs/" + jobId + "/agents/" + agent.id + "/steps?limit=100", token,
      {signal: controller.signal}).then(data => setSteps(data.items)).catch(error => {
        if (!controller.signal.aborted) onError(String(error));
      });
    return () => controller.abort();
  }, [jobId, agent.id, agent.steps, token, onError]);
  return <Drawer title={agent.role} subtitle="A closer look at this specialist's work." close={close}>
    <StatusBadge status={agent.status} budget={agent.error?.code === "agent_budget_exhausted"} />
    <p className="agent-objective">{agent.objective}</p>
    {agent.error && <div className="inline-message message-error"><strong>{agent.error.code === "agent_budget_exhausted" ?
      "This agent reached its token allowance." : "This agent stopped before finishing."}</strong>
      <p>{agent.error.message}</p><code>{agent.error.code}</code></div>}
    <dl className="detail-list"><div><dt>Model</dt><dd>{agent.model}</dd></div>
      <div><dt>Steps</dt><dd>{agent.steps}</dd></div><div><dt>Tokens</dt><dd>{agent.tokens.toLocaleString()}</dd></div>
      <div><dt>Estimated cost</dt><dd>{money(agent.cost_usd)}</dd></div></dl>
    {agent.result && <Findings result={agent.result} />}
    <details className="technical-details"><summary>Execution steps <span className="count-pill">{steps.length}</span>
      <Icon name="down" size={14} /></summary>
      {steps.map(step => <details className="tool-step" key={step.id}><summary>{step.name.replaceAll("_", " ")}
        <Icon name="down" size={14} /></summary><pre className="codeblock">{JSON.stringify({input: step.arguments, output: step.output}, null, 2)}</pre></details>)}
    </details>
    <details className="technical-details"><summary>Agent configuration<Icon name="down" size={14} /></summary>
      <dl className="detail-list"><div><dt>Model purpose</dt><dd>{agent.model_purpose}</dd></div>
        <div><dt>Allowed tools</dt><dd>{agent.allowed_tools.join(", ") || "None"}</dd></div>
        <div><dt>Agent ID</dt><dd>{agent.id}</dd></div></dl>
      {agent.model_reason && <p className="muted small">{agent.model_reason}</p>}</details>
  </Drawer>;
}
