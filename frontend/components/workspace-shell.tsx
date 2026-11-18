"use client";
import {useState, type ReactNode} from "react";
import type {JobSummary} from "../lib/api";
import {dateLabel, statusLabel} from "../lib/format";
import {Brand, Icon} from "./ui";

export function WorkspaceShell({children, history, currentId, select, newReview, settings, disconnect, connected}: {
  children: ReactNode; history: JobSummary[]; currentId: string; select: (id: string) => void;
  newReview: () => void; settings: () => void; disconnect: () => void; connected: boolean;
}) {
  const [open, setOpen] = useState(false), [query, setQuery] = useState("");
  const visible = history.filter(item => item.objective.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="workspace">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <header className="mobile-header"><Brand /><button className="icon-button" aria-label="Open navigation"
      onClick={() => setOpen(true)}><Icon name="menu" /></button></header>
    {open && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={"sidebar " + (open ? "sidebar-open" : "")}>
      <div className="sidebar-top"><button className="brand-link" onClick={() => {
        newReview(); setOpen(false);
      }} aria-label="Swarm home"><Brand /></button><span className="workspace-tag"><Icon name="code" size={14} />Code review workspace</span></div>
      <button className="new-review-button" onClick={() => {newReview(); setOpen(false);}}>
        <Icon name="plus" size={17} /> New review<Icon name="arrow" size={15} /></button>
      <div className="sidebar-label"><span>Recent reviews</span><span>{history.length || ""}</span></div>
      {!!history.length && <div className="history-search"><Icon name="search" size={14} />
        <input aria-label="Search reviews" placeholder="Search reviews..." value={query} onChange={event => setQuery(event.target.value)} /></div>}
      <nav className="review-history" aria-label="Recent reviews">
        {!history.length && <p className="history-empty">Your reviews will live here.</p>}
        {!!history.length && !visible.length && <p className="history-empty">No matching reviews.</p>}
        {visible.map(item => <button key={item.id} className={"history-item " + (item.id === currentId ? "active" : "")}
          aria-current={item.id === currentId ? "page" : undefined}
          onClick={() => {select(item.id); setOpen(false);}}>
          <span className={"history-status history-" + item.status.toLowerCase()} />
          <span className="history-copy"><span>{item.objective}</span>
            <small>{dateLabel(item.created_at)} <span>&middot;</span> {statusLabel(item.status)}</small></span>
        </button>)}
      </nav>
      <div className="sidebar-bottom"><button className="sidebar-action" onClick={() => {settings(); setOpen(false);}}>
        <Icon name="settings" /> Workspace settings</button>
        <div className="workspace-account"><span className="avatar"><Icon name="layers" size={17} /></span><div><strong>My workspace</strong>
          <small><span className="online-dot" />{connected ? "Connected" : "Offline"}</small></div>
          <button className="icon-button" onClick={disconnect} aria-label="Disconnect workspace" title="Disconnect">
            <Icon name="logout" size={17} /></button></div>
      </div>
    </aside>
    <main className="main-content" id="main-content"><div className="topbar"><span><Icon name="code" size={15} />Code review <span className="breadcrumb-divider">/</span>
      <strong>{currentId ? "Review report" : "New review"}</strong></span><span className="topbar-note"><span className="online-dot" />
      {connected ? "Workspace connected" : "Offline"}</span></div><div className="content-inner">{children}</div>
      <footer className="app-footer"><span><Icon name="shield" size={13} />Your source stays read only.</span><span>Built for thoughtful shipping.</span></footer>
    </main>
  </div>;
}
