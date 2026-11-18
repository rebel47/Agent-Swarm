import {useEffect, useRef, type ReactNode, type KeyboardEvent} from "react";
import {statusLabel} from "../lib/format";

const paths = {
  plus: ["M12 5v14M5 12h14"], arrow: ["M5 12h14m-6-6 6 6-6 6"],
  chevron: ["m9 5 7 7-7 7"], down: ["m6 9 6 6 6-6"],
  code: ["m8 8-4 4 4 4m8-8 4 4-4 4m-3-11-2 22"],
  folder: ["M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"],
  git: ["M7 7v10m0-5h7a3 3 0 0 0 3-3V7"],
  settings: ["M4 7h16M4 17h16M9 4v6m6 4v6"],
  check: ["m5 12 4 4L19 6"], close: ["m6 6 12 12M6 18 18 6"],
  clock: ["M12 8v5l3 2", "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"],
  shield: ["m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z", "m8 12 3 3 5-6"],
  activity: ["M3 12h4l3-8 4 16 3-8h4"],
  team: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87", "M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0m5-3a4 4 0 0 1 0 8"],
  file: ["M14 2H5v20h14V7Zm0 0v6h5M8 12h8m-8 4h5"],
  menu: ["M4 6h16M4 12h16M4 18h16"],
  logout: ["M9 4H4v16h5m5-12 4 4-4 4m-5-4h13"],
  key: ["M10 14 3 21m3-3 3 3m5-11a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z"],
  alert: ["m12 3 10 18H2Zm0 6v5m0 3h.01"],
  refresh: ["M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"],
  search: ["M21 21l-5-5", "M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0"],
  download: ["M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"],
  spark: ["m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"],
  layers: ["m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"],
};
export type IconName = keyof typeof paths;
export function navigateTabs(event: KeyboardEvent<HTMLElement>) {
  if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'));
  const current = tabs.indexOf(document.activeElement as HTMLButtonElement);
  if (current < 0 || !tabs.length) return;
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
    (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault(); tabs[next].focus(); tabs[next].click();
}
export function Icon({name, size = 18}: {name: IconName; size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths[name].map((path, index) => <path d={path} key={index} />)}</svg>;
}
export function Brand() {
  return <span className="brand"><span className="brand-mark"><i /><i /><i /></span>swarm<span className="brand-dot">.</span></span>;
}
export function StatusBadge({status, budget = false}: {status: string; budget?: boolean}) {
  return <span className={"status status-" + status.toLowerCase()}>
    <span className="status-dot" />{budget ? "Budget reached" : statusLabel(status)}</span>;
}
export function Drawer({title, subtitle, children, close}: {
  title: string; subtitle?: string; children: ReactNode; close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const target = ref.current, previous = document.activeElement;
    target?.showModal();
    return () => {target?.close(); if (previous instanceof HTMLElement) previous.focus();};
  }, []);
  return <dialog ref={ref} className="drawer" aria-label={title} onCancel={close}
    onClick={event => {if (event.target === event.currentTarget) close();}}>
    <div className="drawer-surface"><header className="drawer-header"><div><h2>{title}</h2>
      {subtitle && <p className="muted">{subtitle}</p>}</div>
      <button className="icon-button" aria-label="Close panel" onClick={close}><Icon name="close" /></button></header>
      <div className="drawer-content">{children}</div></div>
  </dialog>;
}
