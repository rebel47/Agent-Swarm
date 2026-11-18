"use client";
import {useState, type FormEvent} from "react";
import type {Workspaces} from "../lib/api";
import {repositoryName} from "../lib/format";
import {reviewPrompts, type PreparationStage, type ReviewDraft, type ReviewInput} from "../lib/reviews";
import {Icon, navigateTabs} from "./ui";

export function NewReview({sources, stage, start, remove, initial}: {
  sources: Workspaces; stage: PreparationStage; start: (input: ReviewInput) => Promise<void>;
  remove: (id: string) => Promise<boolean>; initial?: ReviewDraft;
}) {
  const [sourceType, setSourceType] = useState<"git" | "local" | "saved">(initial?.sourceType || "git");
  const [location, setLocation] = useState(initial?.location || ""), [repositoryId, setRepositoryId] = useState(initial?.repositoryId || "");
  const [objective, setObjective] = useState(initial?.objective || reviewPrompts[0].text), [ref, setRef] = useState(initial?.ref || "");
  const [mode, setMode] = useState(initial?.mode || "adaptive"), [fixedCount, setFixedCount] = useState(initial?.fixedCount || 3);
  const [propose, setPropose] = useState(initial?.propose || false), [removing, setRemoving] = useState(false);
  const busy = !!stage || removing;
  const validSource = sourceType === "saved" ? !!repositoryId : !!location.trim();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !validSource || objective.trim().length < 5) return;
    void start({repositoryId: sourceType === "saved" ? repositoryId : "", location, ref: sourceType === "git" ? ref : "",
      objective, mode, fixedCount, propose});
  }
  return <div className="new-review-view">
    <div className="page-intro"><span className="eyebrow"><Icon name="spark" size={14} />A fresh perspective</span><h1>Ship with a second opinion.</h1>
      <p>A focused code review. Clear findings. A path to the fix.</p></div>
    <div className="review-setup">
    <form className="review-composer" onSubmit={submit}>
      <section className="composer-section"><div className="section-heading"><span className="step-number">01</span>
        <div><h2>Your repository</h2><p>Choose the code you want a fresh pair of eyes on.</p></div></div>
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
        <div><h2>Review focus</h2><p>Start with a preset, then make the brief your own.</p></div></div>
        <div className="prompt-presets" aria-label="Review focus presets">{reviewPrompts.map(prompt =>
          <button type="button" key={prompt.label} className={objective === prompt.text ? "selected" : ""}
            aria-pressed={objective === prompt.text} disabled={busy} onClick={() => setObjective(prompt.text)}>
            {objective === prompt.text && <Icon name="check" size={13} />}{prompt.label}</button>)}</div>
        <div className="brief-label"><label htmlFor="review-objective">Review brief</label><span>Editable</span></div>
        <textarea id="review-objective" value={objective} disabled={busy} maxLength={8000} minLength={5} required
          placeholder="Find correctness bugs and missing edge cases. Explain the root cause and suggest a minimal fix..."
          onChange={event => setObjective(event.target.value)} />
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
      <footer className="composer-footer"><span><Icon name="shield" size={15} />Your code stays untouched</span>
        <button className="button button-primary" disabled={busy || !validSource || objective.trim().length < 5}>
          {stage ? <><span className="spinner" />{stage}...</> : <>Start review<Icon name="arrow" size={17} /></>}</button></footer>
    </form>
    <aside className="review-guide" aria-label="About your review"><span className="guide-label">A little more confidence.</span>
      <h2>Less noise.<br />More signal.</h2><p>Get to the issues that deserve your attention.</p>
      <div className="guide-points"><div><span><Icon name="code" size={17} /></span><div><h3>Grounded in source</h3>
        <p>Findings link to exact files and lines, with the evidence attached.</p></div></div>
        <div><span><Icon name="team" size={17} /></span><div><h3>A focused team</h3>
          <p>Specialists follow the questions your review needs answered.</p></div></div>
        <div><span><Icon name="check" size={17} /></span><div><h3>A practical next step</h3>
          <p>Understand the impact, the uncertainty, and a suggested fix.</p></div></div></div>
      <div className="guide-tip"><Icon name="spark" size={16} /><p><strong>Make it specific.</strong> Mention a feature, a risky flow, or a concern to help focus the review.</p></div>
      <span className="guide-footnote"><Icon name="shield" size={13} />Patches are suggestions for you to review.</span>
    </aside></div>
  </div>;
}
