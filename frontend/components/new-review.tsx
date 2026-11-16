"use client";
import {useState, type FormEvent} from "react";
import type {Workspaces} from "../lib/api";
import {repositoryName} from "../lib/format";
import {reviewPrompts, type PreparationStage, type ReviewInput} from "../lib/reviews";
import {Icon, navigateTabs} from "./ui";

export function NewReview({sources, stage, start, remove, initial}: {
  sources: Workspaces; stage: PreparationStage; start: (input: ReviewInput) => Promise<void>;
  remove: (id: string) => Promise<boolean>; initial?: {location: string; objective: string};
}) {
  const [sourceType, setSourceType] = useState<"git" | "local" | "saved">("git");
  const [location, setLocation] = useState(initial?.location || ""), [repositoryId, setRepositoryId] = useState("");
  const [objective, setObjective] = useState(initial?.objective || ""), [ref, setRef] = useState("");
  const [mode, setMode] = useState("adaptive"), [fixedCount, setFixedCount] = useState(3);
  const [propose, setPropose] = useState(false), [removing, setRemoving] = useState(false);
  const busy = !!stage || removing;
  const validSource = sourceType === "saved" ? !!repositoryId : !!location.trim();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !validSource || objective.trim().length < 5) return;
    void start({repositoryId: sourceType === "saved" ? repositoryId : "", location, ref: sourceType === "git" ? ref : "",
      objective, mode, fixedCount, propose});
  }
  return <div className="new-review-view">
    <div className="page-intro"><span className="eyebrow">A fresh perspective</span><h1>What could your code do better?</h1>
      <p>Bring a repository. Set a focus. We&apos;ll take a closer look.</p></div>
    <form className="review-composer" onSubmit={submit}>
      <section className="composer-section"><div className="section-heading"><span className="step-number">01</span>
        <div><h2>Choose your repository</h2><p>A public Git URL, local folder, or saved snapshot.</p></div></div>
        <div className="source-tabs" role="tablist" aria-label="Repository source" onKeyDown={navigateTabs}>
          {([["git", "git", "Git repository"], ["local", "folder", "Local folder"], ["saved", "clock", "Saved"]] as const)
            .map(([value, icon, label]) => <button key={value} type="button" role="tab" aria-selected={sourceType === value}
              tabIndex={sourceType === value ? 0 : -1}
              disabled={busy} className={sourceType === value ? "selected" : ""} onClick={() => {
                setSourceType(value); setLocation(""); setRepositoryId(""); setRef("");
              }}><Icon name={icon} size={16} />{label}</button>)}</div>
        {sourceType === "saved" ? <div className="saved-source-row"><label className="sr-only" htmlFor="saved-source">Saved repository</label>
          <select id="saved-source" value={repositoryId} disabled={busy} onChange={event => setRepositoryId(event.target.value)}>
            <option value="">Select a saved repository</option>{sources.items.map(source =>
              <option key={source.id} value={source.id}>{repositoryName(source.name)}{source.kind === "registered" ? " (Sample)" : ""}</option>)}
          </select>{repositoryId && sources.items.find(item => item.id === repositoryId)?.kind !== "registered" &&
            <button type="button" className="text-button" disabled={busy} onClick={async () => {
              setRemoving(true); try {if (await remove(repositoryId)) setRepositoryId("");} finally {setRemoving(false);}
            }}>Remove</button>}</div> : <>
          <label className="sr-only" htmlFor="repository-location">{sourceType === "git" ? "Repository URL" : "Local project path"}</label>
          <div className="input-with-icon"><Icon name={sourceType === "git" ? "git" : "folder"} />
            <input id="repository-location" value={location} disabled={busy} maxLength={2000} required
              placeholder={sourceType === "git" ? "https://github.com/your-team/your-project" :
                (sources.local_roots[0] || "/projects") + "/your-project"}
              onChange={event => setLocation(event.target.value)} /></div>
          <p className="field-help">{sourceType === "git" ? "Public repositories on " + sources.git_hosts.join(", ") + "." :
            "Choose a folder under " + (sources.local_roots.join(", ") || "your configured projects directory") + "."}</p>
        </>}
      </section>
      <section className="composer-section"><div className="section-heading"><span className="step-number">02</span>
        <div><h2>Set the focus</h2><p>What would you like a second opinion on?</p></div></div>
        <label className="sr-only" htmlFor="review-objective">Review brief</label>
        <textarea id="review-objective" value={objective} disabled={busy} maxLength={8000} minLength={5} required
          placeholder="Find correctness bugs and missing edge cases. Explain the root cause and suggest a minimal fix..."
          onChange={event => setObjective(event.target.value)} />
        <div className="prompt-presets"><span>Try a focus</span>{reviewPrompts.map(prompt =>
          <button type="button" key={prompt.label} className={objective === prompt.text ? "selected" : ""}
            disabled={busy} onClick={() => setObjective(prompt.text)}>{prompt.label}<Icon name="plus" size={12} /></button>)}</div>
      </section>
      <details className="review-options"><summary><span><Icon name="settings" size={16} />Review options</span>
        <Icon name="down" size={15} /></summary><div className="options-grid">
        {sourceType === "git" && <label>Branch or tag<input value={ref} placeholder="Default branch" disabled={busy}
          onChange={event => setRef(event.target.value)} maxLength={200} /></label>}
        <label>Team allocation<select value={mode} disabled={busy} onChange={event => setMode(event.target.value)}>
          <option value="adaptive">Automatic</option><option value="single">Single agent</option>
          <option value="fixed">Fixed team</option></select></label>
        {mode === "fixed" && <label>Team size<input type="number" min={1} max={10000} disabled={busy}
          value={fixedCount} onChange={event => setFixedCount(Number(event.target.value))} /></label>}
        <label className="checkbox-label"><input type="checkbox" checked={propose} disabled={busy}
          onChange={event => setPropose(event.target.checked)} />Include suggested patches</label>
      </div></details>
      <footer className="composer-footer"><span><Icon name="shield" size={15} />Read only source review</span>
        <button className="button button-primary" disabled={busy || !validSource || objective.trim().length < 5}>
          {stage ? <><span className="spinner" />{stage}...</> : <>Start review<Icon name="arrow" size={17} /></>}</button></footer>
    </form>
    <div className="how-it-works"><div><span>01</span><h3>Share the context</h3><p>Tell us where to look and what matters.</p></div>
      <div><span>02</span><h3>A team takes a look</h3><p>Specialists follow the evidence in your code.</p></div>
      <div><span>03</span><h3>Leave with clarity</h3><p>Get findings with source references and fixes.</p></div></div>
  </div>;
}
