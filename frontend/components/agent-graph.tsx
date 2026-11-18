"use client";
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import ReactFlow, {applyNodeChanges, Background, Controls, Handle, MarkerType, Position, useUpdateNodeInternals,
  type Edge, type Node, type NodeChange, type NodeProps, type ReactFlowInstance} from "reactflow";
import type {Agent, AuditEvent, Job} from "../lib/api";
import {statusLabel} from "../lib/format";
import {Icon} from "./ui";

const toolLabels: Record<string, string> = {
  read_repository_file: "Source file inspected", search_repository: "Source searched",
  list_repository_files: "Repository explored", retrieve_agent_result: "Specialist findings collected",
  get_agent_status: "Team progress checked", spawn_agent: "Specialist delegated",
};

function activityLabel(event: AuditEvent) {
  if (event.type === "tool.completed") return event.data.error ? "Source inspection returned an error" :
    toolLabels[String(event.data.name)] || String(event.data.name || "Source inspected").replaceAll("_", " ");
  if (event.type === "agent.status") return statusLabel(String(event.data.status));
  if (event.type === "job.status") return "Review " + statusLabel(String(event.data.status)).toLowerCase();
  return ({"llm.started": "Model request started", "agent.created": "Joined the review",
    "supervisor.decision": "Review plan updated", "context.summarized": "Review context summarized",
    "execution.error": "Execution stopped"} as Record<string, string>)[event.type] || "Review updated";
}

type ReviewNodeData = {
  title: string; status: string; tone: string; moving: boolean; coordinator?: boolean;
  activity: string; steps: number; tokens: number; side?: "left" | "right"; inspect?: () => void;
};

function ReviewNode({id, data}: NodeProps<ReviewNodeData>) {
  const updateNode = useUpdateNodeInternals();
  useEffect(() => {updateNode(id);}, [id, data.side, updateNode]);
  const content = <><strong>{data.title}</strong><span className="review-node-activity" title={data.activity}>{data.activity}</span>
    <span className="review-node-footer"><span>{data.steps} steps<span className="review-node-divider">·</span>
      {data.tokens.toLocaleString()} {data.coordinator ? "total tokens" : "tokens"}</span>{data.inspect && <Icon name="arrow" size={14} />}</span></>;
  return <div className={`review-node node-${data.tone}${data.moving ? " node-working" : ""}${data.coordinator ? " node-coordinator" : ""}`}>
    {!data.coordinator && <Handle type="target" position={data.side === "left" ? Position.Right : Position.Left} />}
    <div className="review-node-grip" title="Drag to rearrange">
      <span className="review-node-icon"><Icon name={data.coordinator ? "layers" : "code"} size={15} /></span>
      <span className="review-node-status"><i />{data.status}</span><span className="review-node-drag"><Icon name="menu" size={12} /></span>
    </div>
    {data.inspect ? <button className="review-node-body nodrag nopan" onClick={data.inspect}
      aria-label={`View ${data.title}'s work`}>{content}</button> : <div className="review-node-body">{content}</div>}
    {(data.coordinator || data.side !== "left") && <Handle id="right" type="source" position={Position.Right} />}
    {(data.coordinator || data.side === "left") && <Handle id="left" type="source" position={Position.Left} />}
  </div>;
}
const nodeTypes = {review: ReviewNode};

// Spread larger teams across both sides; keep delegated branches on their parent's side.
function teamPositions(agents: Agent[]) {
  const ids = new Set(agents.map(agent => agent.id)), positions = new Map<string, {x: number; y: number}>();
  const children = new Map<string, Agent[]>();
  for (const agent of agents) {
    const parent = agent.parent_agent_id && ids.has(agent.parent_agent_id) ? agent.parent_agent_id : "supervisor";
    children.set(parent, [...(children.get(parent) || []), agent]);
  }
  const roots = children.get("supervisor") || [];
  const split = roots.length > 3 ? Math.ceil(roots.length / 2) : roots.length;
  const layout = (branch: Agent[], direction: number) => {
    let lane = 0;
    const placed: string[] = [];
    const visit = (agent: Agent, depth: number): number => {
      const rows = (children.get(agent.id) || []).map(child => visit(child, depth + 1));
      const y = rows.length ? (rows[0] + rows[rows.length - 1]) / 2 : lane++ * 174;
      positions.set(agent.id, {x: direction * depth * 330, y}); placed.push(agent.id);
      return y;
    };
    branch.forEach(agent => visit(agent, 1));
    return {lanes: lane, placed};
  };
  const right = layout(roots.slice(0, split), 1), left = layout(roots.slice(split), -1);
  const lanes = Math.max(right.lanes, left.lanes, 1);
  for (const side of [right, left]) for (const id of side.placed) {
    const point = positions.get(id)!;
    positions.set(id, {...point, y: point.y + (lanes - side.lanes) * 174 / 2});
  }
  positions.set("supervisor", {x: 0, y: (lanes - 1) * 174 / 2});
  return positions;
}

export function AgentGraph({job, audit, connection, select}: {
  job: Job; audit: AuditEvent[]; connection: string; select: (id: string) => void;
}) {
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const [nodes, setNodes] = useState<Node<ReviewNodeData>[]>([]);
  const arranged = useRef(new Map<string, {x: number; y: number}>());
  const running = job.status === "RUNNING", live = running && connection === "Live";
  const active = job.agents.filter(agent => agent.status === "RUNNING");
  const finished = job.agents.filter(agent => agent.status === "COMPLETED").length;
  const topology = JSON.stringify([job.id, ...job.agents.map(agent => [agent.id, agent.parent_agent_id])]);
  const positions = useMemo(() => teamPositions(job.agents), [job.agents]);
  const recent = useMemo(() => audit.filter(event => !["llm.usage", "llm.invalid_response"].includes(event.type)), [audit]);
  const latest = recent[recent.length - 1];
  const latestRole = latest?.agent_id ? job.agents.find(agent => agent.id === latest.agent_id)?.role || "Specialist" : "Review coordinator";
  const nextNodes: Node<ReviewNodeData>[] = useMemo(() => [
    {id: "supervisor", type: "review", position: positions.get("supervisor")!,
      dragHandle: ".review-node-grip", data: {title: "Review coordinator", coordinator: true,
        status: running ? job.agents.length ? "Coordinating" : "Planning" : statusLabel(job.status),
        tone: running ? "active" : job.status === "COMPLETED" ? "done" : "stopped", moving: live,
        activity: running ? job.agents.length ? "Connecting the team's findings" : "Shaping the review team" : "Review session ended",
        steps: job.supervisor_steps, tokens: job.metrics.tokens}},
    ...job.agents.map(agent => {
      const last = [...recent].reverse().find(event => event.agent_id === agent.id && event.type !== "agent.status");
      const stopped = !running && ["RUNNING", "QUEUED", "CREATED", "WAITING_FOR_CHILDREN"].includes(agent.status);
      const tone = stopped ? "stopped" : ({RUNNING: "active", COMPLETED: "done", FAILED: "warning", TIMED_OUT: "warning", CANCELLED: "stopped",
        WAITING_FOR_CHILDREN: "waiting"} as Record<string, string>)[agent.status] || "queued";
      return {id: agent.id, type: "review", position: positions.get(agent.id) || {x: 330, y: 0},
        dragHandle: ".review-node-grip", data: {title: agent.role, tone, side: positions.get(agent.id)!.x < 0 ? "left" as const : "right" as const,
          moving: live && agent.status === "RUNNING",
          status: stopped ? "Stopped" : agent.error?.code === "agent_budget_exhausted" ? "Budget reached" :
            agent.status === "RUNNING" ? "Reviewing" : statusLabel(agent.status),
          activity: last ? activityLabel(last) : agent.status === "QUEUED" ? "Waiting for a turn" : agent.objective,
          steps: agent.steps, tokens: agent.tokens, inspect: () => select(agent.id)}};
    }),
  ], [job, positions, recent, running, live, select]);

  // Keep user-arranged positions and the viewport when token counts or activity change.
  useEffect(() => {
    setNodes(previous => nextNodes.map(node => {
      const existing = previous.find(item => item.id === node.id);
      return {...existing, ...node, position: arranged.current.get(node.id) || node.position};
    }));
  }, [nextNodes]);
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    for (const change of changes) if (change.type === "position" && change.position) arranged.current.set(change.id, change.position);
    setNodes(current => applyNodeChanges(changes, current));
  }, []);
  useEffect(() => {
    if (!flow) return;
    const frame = requestAnimationFrame(() => void flow.fitView({padding: 0.12, maxZoom: 1}));
    return () => cancelAnimationFrame(frame);
  }, [flow, topology]);
  const edges: Edge[] = job.agents.map(agent => {
    const moving = live && agent.status === "RUNNING";
    return {id: "parent-" + agent.id, source: job.agents.some(parent => parent.id === agent.parent_agent_id) ? agent.parent_agent_id! : "supervisor",
      sourceHandle: positions.get(agent.id)!.x < 0 ? "left" : "right",
      target: agent.id, type: "smoothstep", animated: moving, className: moving ? "review-edge-active" : "",
      style: {stroke: moving ? "#8c79df" : agent.status === "COMPLETED" ? "#a8c3b5" : "#dad9e5", strokeWidth: moving ? 2 : 1.5},
      markerEnd: {type: MarkerType.ArrowClosed, color: moving ? "#8c79df" : "#c3c1d2"}};
  });

  return <section className="team-network" aria-label="Review team graph">
    <div className="network-toolbar"><div><span className={`network-connection${live ? " network-live" : ""}`}>
      <i />{running ? live ? "Live review" : connection === "Connecting" ? "Connecting" : "Reconnecting" : job.status === "COMPLETED" ? "Review complete" : "Review ended"}</span>
      <span className="network-summary">{running ? `${active.length} reviewing` : `${finished} completed`}<span> / {job.agents.length} specialists</span></span>
    </div><div className="network-actions"><button disabled={!active.length || !running} onClick={() => void flow?.fitView({
      nodes: active.map(agent => ({id: agent.id})), padding: 0.35, maxZoom: 1})}>
      <Icon name="activity" size={13} />Focus active</button><button onClick={() => void flow?.fitView({padding: 0.12, maxZoom: 1})}>
      <Icon name="layers" size={13} />Fit team</button></div></div>
    <div className="graph" aria-label="Interactive agent map">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onInit={setFlow} onNodesChange={onNodesChange}
        nodesDraggable nodesConnectable={false} nodesFocusable={false} edgesFocusable={false} elementsSelectable={false}
        fitView fitViewOptions={{padding: 0.12, maxZoom: 1}} minZoom={0.1} maxZoom={1.5} proOptions={{hideAttribution: true}}>
        <Background color="#dedee9" gap={22} size={1} /><Controls showInteractive={false} />
      </ReactFlow>
      {!job.agents.length && <div className="network-preparing">{running ? "Specialists appear as the coordinator delegates work." : "No specialists were created for this review."}</div>}
    </div>
    <div className="network-caption"><span><Icon name="code" size={13} />Select a specialist to see its work. Drag to arrange.</span>
      <span className="network-legend"><span><i className="legend-active" />Reviewing</span><span><i className="legend-done" />Completed</span><span><i className="legend-warning" />Stopped</span></span></div>
    <div className="network-activity" aria-label="Latest team activity" aria-live="polite" aria-atomic="true">
      <span className="network-activity-icon"><Icon name="activity" size={15} /></span><div><span>Latest recorded activity</span>
        <p>{latest ? <><strong>{latestRole}</strong><span> · </span>{activityLabel(latest)}</> :
          running ? "Waiting for the first review update…" : "No recorded activity is available."}</p></div>
      {latest && <time dateTime={new Date(latest.created_at * 1000).toISOString()}>{new Date(latest.created_at * 1000)
        .toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</time>}
    </div>
  </section>;
}
