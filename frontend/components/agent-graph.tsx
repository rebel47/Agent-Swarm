"use client";
import {useEffect, useMemo, useState} from "react";
import ReactFlow, {Background, Controls, MarkerType, type Edge, type Node, type ReactFlowInstance} from "reactflow";
import type {Agent, Job} from "../lib/api";

export const statusColor: Record<string, string> = {
  CREATED: "#9eae90", QUEUED: "#a69cb5", RUNNING: "#7aa977", WAITING_FOR_CHILDREN: "#baa67f",
  COMPLETED: "#8da878", FAILED: "#c2a380", CANCELLED: "#abb49f", TIMED_OUT: "#c6ab80",
};

export function AgentGraph({job, select}: {job: Job | null; select: (agent: Agent) => void}) {
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const nodes: Node[] = useMemo(() => job ? [
    {id: "supervisor", position: {x: 0, y: 0}, data: {label: <div>
      <strong>Review coordinator</strong><small>{job.status.replaceAll("_", " ").toLowerCase()}</small></div>},
     style: {width: 200, background: "#eef5e7", color: "#799263", border: "1px solid #cbdcb9", borderRadius: 10}},
    ...job.agents.map((agent, i) => ({
      id: agent.id, position: {x: 310 * (agent.depth + 1), y: i * 125},
      data: {label: <div className="text-left"><strong>{agent.role}</strong>
        <small style={{color: statusColor[agent.status]}}>{agent.status.replaceAll("_", " ")}</small>
        <small>{agent.tokens.toLocaleString()} tokens · {agent.steps} steps</small></div>},
      style: {width: 245, background: "#ffffff", color: "#7c9465",
        border: "1px solid " + statusColor[agent.status], borderRadius: 12, padding: 12},
    })),
  ] : [], [job]);
  const edges: Edge[] = useMemo(() => job?.agents.map(agent => ({
    id: "parent-" + agent.id, source: agent.parent_agent_id || "supervisor", target: agent.id,
    style: {stroke: statusColor[agent.status]}, markerEnd: {type: MarkerType.ArrowClosed},
  })) || [], [job]);
  useEffect(() => {
    if (!flow || !nodes.length) return;
    const frame = requestAnimationFrame(() => void flow.fitView({padding: 0.25}));
    return () => cancelAnimationFrame(frame);
  }, [flow, nodes.length]);
  return <div className="graph">
    {!job && <div className="graph-empty">Submit an objective to see the live agent graph.<br />
      <span className="text-sm">Agents appear only after the runtime creates them.</span></div>}
    <ReactFlow nodes={nodes} edges={edges} onInit={setFlow} fitView fitViewOptions={{padding: 0.25}}
      nodesDraggable nodesConnectable={false} onNodeClick={(_, node) => {
        const agent = job?.agents.find(agent => agent.id === node.id);
        if (agent) select(agent);
      }} minZoom={0.1}>
      <Background color="#dfe8d4" gap={22} /><Controls showInteractive={false} />
    </ReactFlow>
  </div>;
}
