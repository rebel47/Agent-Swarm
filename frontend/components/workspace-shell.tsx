"use client";
import {useState, type ReactNode} from "react";
import type {JobSummary} from "../lib/api";
import {dateLabel, statusLabel} from "../lib/format";
import {Brand, Icon} from "./ui";

export function WorkspaceShell({children, history, currentId, select, newReview, settings, disconnect, connected}: {
  children: ReactNode; history: JobSummary[]; currentId: string; select: (id: string) => void;
  newReview: () => void; settings: () => void; disconnect: () => void; connected: boolean;
}) {
  const [open, setOpen] = useState(false);
  return <div className="workspace">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <header className="mobile-header"><Brand /><button className="icon-button" aria-label="Open navigation"
      onClick={() => setOpen(true)}><Icon name="menu" /></button></header>
    {open && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={"sidebar " + (open ? "sidebar-open" : "")}>
      <div className="sidebar-top"><button className="brand-link" onClick={() => {
        newReview(); setOpen(false);
      }} aria-label="Swarm home"><Brand /></button><span className="workspace-tag">WORKSPACE</span></div>
      <button className="new-review-button" onClick={() => {newReview(); setOpen(false);}}>
        <Icon name="plus" size={17} /> New review</button>
      <div className="sidebar-label"><span>RECENT REVIEWS</span><span>{history.length || ""}</span></div>
      <nav className="review-history" aria-label="Recent reviews">
        {!history.length && <p className="history-empty">Your reviews will live here.</p>}
        {history.map(item => <button key={item.id} className={"history-item " + (item.id === currentId ? "active" : "")}
          aria-current={item.id === currentId ? "page" : undefined}
          onClick={() => {select(item.id); setOpen(false);}}>
          <span className={"history-status history-" + item.status.toLowerCase()} />
          <span className="history-copy"><span>{item.objective}</span>
            <small>{dateLabel(item.created_at)} <span>&middot;</span> {statusLabel(item.status)}</small></span>
        </button>)}
      </nav>
      <div className="sidebar-bottom"><button className="sidebar-action" onClick={() => {settings(); setOpen(false);}}>
        <Icon name="settings" /> Workspace settings</button>
        <div className="workspace-account"><span className="avatar">W</span><div><strong>My workspace</strong>
          <small><span className="online-dot" />{connected ? "Connected" : "Offline"}</small></div>
          <button className="icon-button" onClick={disconnect} aria-label="Disconnect workspace" title="Disconnect">
            <Icon name="logout" size={17} /></button></div>
      </div>
    </aside>
    <main className="main-content" id="main-content"><div className="topbar"><span>Workspace <span className="breadcrumb-divider">/</span>
      <strong>{currentId ? "Review" : "New review"}</strong></span><span className="topbar-note"><Icon name="shield" size={14} />
      Private workspace</span></div><div className="content-inner">{children}</div>
      <footer className="app-footer"><span>Made for a clearer view of your code.</span><span>Powered by OpenAI</span></footer>
    </main>
  </div>;
}
