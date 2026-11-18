"use client";
import {useState, type FormEvent} from "react";
import {Brand, Icon} from "./ui";

export function ConnectWorkspace({connect, loading}: {connect: (token: string) => Promise<void>; loading: boolean}) {
  const [token, setToken] = useState("");
  function submit(event: FormEvent) {event.preventDefault(); if (token.trim()) void connect(token.trim());}
  return <main className="connect-page"><header><Brand /><span className="connect-tag"><Icon name="code" size={14} />Code review, with perspective.</span></header>
    <div className="connect-grid"><section className="connect-story"><span className="eyebrow"><span className="online-dot" />
      A second set of eyes</span><h1>Good code.<br /><span>Greater confidence.</span></h1>
      <p>Find the issues worth fixing. A focused team reviews your repository and brings back findings you can trace to the source.</p>
      <div className="connect-features"><span><Icon name="git" />Your repository</span><span><Icon name="code" />Source evidence</span>
        <span><Icon name="check" />Actionable findings</span></div>
      <div className="connect-note"><span className="connect-note-mark"><Icon name="layers" size={20} /></span>
        <p>From a broad question<br /><strong>to a clear next step.</strong></p><span className="connect-note-line" /><Icon name="arrow" size={18} /></div>
    </section><section className="connect-card"><span className="connect-symbol"><Icon name="key" size={24} /></span>
      <span className="eyebrow">Your workspace</span><h2>Welcome back.</h2><p className="muted">Connect to start your next code review.</p>
      <form onSubmit={submit}><label htmlFor="access-token">Workspace access token</label>
        <input id="access-token" type="password" autoComplete="off" value={token} disabled={loading}
          placeholder="Enter your access token" onChange={event => setToken(event.target.value)} required />
        <p className="field-help">Use the token provided for this workspace.</p>
        <button className="button button-primary" disabled={loading || !token.trim()}>
          {loading ? "Connecting..." : "Enter workspace"}<Icon name="arrow" size={17} /></button></form>
      <p className="connect-privacy"><Icon name="shield" size={14} />Reviews use an isolated source snapshot.</p>
    </section></div><footer className="connect-footer"><span>A little perspective goes a long way.</span><span>Built for thoughtful shipping.</span></footer>
  </main>;
}
