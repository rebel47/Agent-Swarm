"use client";
import {useCallback, useEffect, useRef, useState} from "react";
import {api, type JobSummary, type Models, type Workspaces} from "../lib/api";
import {loadWorkspace} from "../lib/reviews";

export function useWorkspace(onError: (message: string) => void) {
  const [token, setToken] = useState(""), [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true), [models, setModels] = useState<Models | null>(null);
  const [sources, setSources] = useState<Workspaces>({items: [], local_roots: [], git_hosts: []});
  const [allocation, setAllocation] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<JobSummary[]>([]);
  const attempt = useRef(0);
  const connect = useCallback(async (key: string) => {
    const current = ++attempt.current;
    setLoading(true); onError("");
    try {
      const data = await loadWorkspace(key);
      if (attempt.current !== current) return;
      setSources(data.sources); setModels(data.models); setHistory(data.history);
      setAllocation(data.models.allocation); setToken(key); setConnected(true);
      sessionStorage.setItem("swarm-token", key);
    } catch (error) {
      if (attempt.current === current) {onError(String(error)); setConnected(false);}
    } finally {if (attempt.current === current) setLoading(false);}
  }, [onError]);
  useEffect(() => {
    const saved = sessionStorage.getItem("swarm-token");
    if (saved) void connect(saved); else setLoading(false);
  }, [connect]);
  const refreshHistory = useCallback(async () => {
    if (token) setHistory((await api<{items: JobSummary[]}>("/jobs?limit=50", token)).items);
  }, [token]);
  const refreshSources = useCallback(async () => {
    if (token) setSources(await api<Workspaces>("/workspaces", token));
  }, [token]);
  function disconnect() {
    attempt.current++; sessionStorage.removeItem("swarm-token");
    setToken(""); setConnected(false); setLoading(false); setHistory([]);
  }
  return {token, connected, loading, connect, disconnect, models, sources, allocation, setAllocation,
    history, refreshHistory, refreshSources};
}
