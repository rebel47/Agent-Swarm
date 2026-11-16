"use client";
import {useState, type FormEvent} from "react";
import {Brand, Icon} from "./ui";

export function ConnectWorkspace({connect, loading}: {connect: (token: string) => Promise<void>; loading: boolean}) {
  const [token, setToken] = useState("");
  function submit(event: FormEvent) {event.preventDefault(); if (token.trim()) void connect(token.trim());}
  return <main className="connect-page"><header><Brand /><span className="muted">Repository intelligence</span></header>
    <div className="connect-grid"><section className="connect-story"><span className="eyebrow"><span className="online-dot" />
      A second perspective</span><h1>Less guesswork.<br /><span>Better code.</span></h1>
      <p>Give your repository a focused review. Get clear findings, grounded in your source, with a path to the fix.</p>
      <div className="connect-features"><span><Icon name="git" />Your repository</span><i /><span><Icon name="team" />
        A focused team</span><i /><span><Icon name="check" />Actionable findings</span></div>
    </section><section className="connect-card"><span className="connect-symbol"><Icon name="key" size={24} /></span>
      <h2>Welcome to your workspace</h2><p className="muted">Connect to start your next code review.</p>
      <form onSubmit={submit}><label htmlFor="access-token">Workspace access token</label>
        <input id="access-token" type="password" autoComplete="off" value={token} disabled={loading}
          placeholder="Enter your access token" onChange={event => setToken(event.target.value)} required />
        <p className="field-help">Use the token provided for this workspace.</p>
        <button className="button button-primary" disabled={loading || !token.trim()}>
          {loading ? "Connecting..." : "Enter workspace"}<Icon name="arrow" size={17} /></button></form>
      <p className="connect-privacy"><Icon name="shield" size={14} />Reviews use an isolated source snapshot.</p>
    </section></div><footer className="connect-footer">A little perspective goes a long way.</footer>
  </main>;
}
