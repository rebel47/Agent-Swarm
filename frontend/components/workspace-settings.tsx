"use client";
import {useState} from "react";
import {api, type Models} from "../lib/api";
import {money} from "../lib/format";
import {Drawer, Icon} from "./ui";

export function WorkspaceSettings({models, allocation, change, token, close}: {
  models: Models | null; allocation: Record<string, string>; change: (value: Record<string, string>) => void;
  token: string; close: () => void;
}) {
  const [testModel, setTestModel] = useState(allocation.orchestrator || ""), [testing, setTesting] = useState(false);
  const [status, setStatus] = useState(""), [failed, setFailed] = useState(false);
  async function test() {
    setTesting(true); setStatus(""); setFailed(false);
    try {
      const result = await api<{model: string; estimated_cost_usd: number}>("/models/connectivity", token,
        {method: "POST", body: JSON.stringify({model: testModel})});
      setStatus(result.model + " connected successfully (" + money(result.estimated_cost_usd) + ")");
    } catch (error) {setStatus(String(error)); setFailed(true);} finally {setTesting(false);}
  }
  return <Drawer title="Workspace settings" subtitle="Customize how new reviews run." close={close}>
    <section className="settings-section"><div className="settings-heading"><span className="soft-icon"><Icon name="code" /></span>
      <div><h3>OpenAI models</h3><p>Use economical models for investigation and stronger models for critical decisions.</p></div></div>
      <div className="setting-fields">{[["orchestrator", "Planning"], ["routine", "Investigation"],
        ["verification", "Verification"], ["synthesis", "Final report"]].map(([role, label]) =>
        <label key={role}>{label}<select value={allocation[role] || ""}
          onChange={event => change({...allocation, [role]: event.target.value})}>
          {Object.keys(models?.policies || {}).map(name => <option key={name} value={name}>{name}</option>)}</select></label>)}</div>
      <p className="field-help"><Icon name="check" size={14} />Selections apply to your next review.</p>
    </section>
    <section className="settings-section"><h3>Test a model connection</h3><p className="muted small">
      Sends a billable request, limited to {money(models?.connectivity_max_cost_usd || 0)} per test.</p>
      <label className="sr-only" htmlFor="test-model">Connection test model</label>
      <select id="test-model" value={testModel} onChange={event => setTestModel(event.target.value)}>
        {Object.keys(models?.policies || {}).map(name => <option key={name} value={name}>{name}</option>)}</select>
      <button className="button button-secondary" disabled={testing || !testModel} onClick={() => void test()}>
        <Icon name="activity" size={16} />{testing ? "Testing connection..." : "Test connection"}</button>
      {status && <p role="status" className={"inline-message " + (failed ? "message-error" : "message-success")}>{status}</p>}
    </section>
    <div className="settings-note"><Icon name="shield" /><p>Source access and spending limits are managed by your workspace configuration.</p></div>
  </Drawer>;
}
