"use client";
import {useCallback, useEffect, useState} from "react";
import {api, events, type AuditEvent, type Job} from "../lib/api";

export function useReviewSelection() {
  const [id, setId] = useState("");
  useEffect(() => {
    const restore = () => setId(new URLSearchParams(window.location.search).get("job") || "");
    restore(); window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const select = useCallback((value: string) => {
    setId(value);
    const url = new URL(window.location.href);
    if (value) url.searchParams.set("job", value); else url.searchParams.delete("job");
    window.history.pushState(null, "", url.pathname + url.search + url.hash);
  }, []);
  return {id, select};
}

export function useReview(id: string, token: string, onError: (message: string) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [connection, setConnection] = useState("Connecting");
  const [now, setNow] = useState(Date.now());
  const refresh = useCallback(async () => {
    if (id && token) setJob(await api<Job>("/jobs/" + id, token));
  }, [id, token]);
  useEffect(() => {
    setJob(null); setAudit([]);
    if (!id || !token) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fail = (error: unknown) => {if (!controller.signal.aborted) onError(String(error));};
    const merge = (incoming: AuditEvent[]) => setAudit(current =>
      Array.from(new Map([...current, ...incoming].map(event => [event.id, event])).values())
        .sort((a, b) => a.id - b.id).slice(-100));
    const reload = async () => {
      const data = await api<Job>("/jobs/" + id, token, {signal: controller.signal});
      if (!controller.signal.aborted) setJob(data);
    };
    void reload().catch(fail);
    void api<AuditEvent[]>("/jobs/" + id + "/history?limit=100&latest=true", token, {signal: controller.signal})
      .then(items => {if (!controller.signal.aborted) merge(items);}).catch(fail);
    void events(id, token, controller.signal, data => {
      if (!controller.signal.aborted) setJob(data);
    }, event => {
      if (controller.signal.aborted) return;
      merge([event]);
      if (!timer) timer = setTimeout(() => {timer = undefined; void reload().catch(fail);}, 180);
    }, message => {if (!controller.signal.aborted) setConnection(message);});
    return () => {controller.abort(); if (timer) clearTimeout(timer);};
  }, [id, token, onError]);
  useEffect(() => {
    if (job?.status !== "RUNNING") return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job?.status]);
  return {job, audit, connection, refresh, now};
}
