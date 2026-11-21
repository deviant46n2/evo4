import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

const API = "http://127.0.0.1:8765/api/v1";
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API + path, init);
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try { const body = await response.json(); detail = body.detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
const json = (value: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
});

type Memory = { id: string; content: string; category: string; source: string; confidence: number; status: string; created_at: string; access_count: number };
type Candidate = { id: string; content: string; category: string; source: string; confidence: number; created_at: string };
type Run = { id: string; kind: string; status: string; started_at: string; finished_at?: string; summary?: string; metadata: Record<string, any> };
type RunDetail = Run & { events: Array<{ id: number; tool_name: string; input: Record<string, any>; output: string; status: string; created_at: string }>; pending_approval: null | { id: string; tool_name: string; arguments: Record<string, any> } };

export function MemoryWorkspace() {
  const [items, setItems] = useState<Memory[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("active");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("general");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const params = new URLSearchParams({ status, limit: "200" });
      if (query.trim()) params.set("q", query.trim());
      const [memoryRows, candidateRows] = await Promise.all([
        api<Memory[]>("/memories?" + params.toString()),
        api<Candidate[]>("/memory-candidates?limit=200"),
      ]);
      setItems(memoryRows); setCandidates(candidateRows); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [query, status]);
  useEffect(() => { void refresh(); }, [refresh]);
  async function addMemory(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api("/memories", json({ content: content.trim(), category, source: "user", confidence: 1 }));
      setContent(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function archive(id: string) {
    try { await api("/memories/" + encodeURIComponent(id) + "/archive", { method: "POST" }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function review(id: string, approved: boolean) {
    try { await api("/memory-candidates/" + encodeURIComponent(id) + "/review", json({ approved })); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <div className="workspace-page">
    <div className="workspace-heading"><div><div className="eyebrow">PERSISTENT KNOWLEDGE</div><h1>Memory</h1><p>Review what Evo has stored, where it came from, and what is still awaiting your approval.</p></div><span className="workspace-count">{items.length} records</span></div>
    {error && <div className="workspace-error" role="alert">{error}</div>}
    <section className="workspace-panel">
      <h2>Add a memory</h2>
      <form className="memory-add" onSubmit={addMemory}>
        <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="A fact, preference, project decision, or correction you want Evo to retain…" rows={3}/>
        <div className="memory-add-footer"><input aria-label="Memory category" value={category} onChange={e => setCategory(e.target.value)} placeholder="Category"/><button disabled={busy || !content.trim()}>{busy ? "Saving…" : "Save memory"}</button></div>
      </form>
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Saved records</h2><p>Explicitly stored facts and user-approved candidates</p></div><div className="memory-filters"><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search memories…"/><select value={status} onChange={e => setStatus(e.target.value)}><option value="active">Active</option><option value="archived">Archived</option><option value="superseded">Superseded</option></select></div></div>
      <div className="record-list">{items.map(item => <article className="record-card" key={item.id}><div className="record-top"><span className="record-category">{item.category}</span><span>{item.source}</span><span>{Math.round(item.confidence * 100)}% confidence</span></div><p>{item.content}</p><div className="record-bottom"><small>Added {new Date(item.created_at).toLocaleString()} · Retrieved {item.access_count} times</small>{item.status === "active" && <button className="quiet-button danger" onClick={() => void archive(item.id)}>Archive</button>}</div></article>)}{items.length === 0 && <div className="empty-state">No {status} memories match this view.</div>}</div>
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Awaiting review</h2><p>Heuristically detected candidates are not used as trusted memories until accepted.</p></div><span className="workspace-count">{candidates.length} pending</span></div>
      <div className="record-list">{candidates.map(item => <article className="record-card candidate-card" key={item.id}><div className="record-top"><span className="record-category">{item.category}</span><span>{item.source}</span><span>{Math.round(item.confidence * 100)}% candidate confidence</span></div><p>{item.content}</p><div className="record-bottom"><small>Detected {new Date(item.created_at).toLocaleString()}</small><div className="inline-actions"><button className="quiet-button" onClick={() => void review(item.id, false)}>Reject</button><button onClick={() => void review(item.id, true)}>Accept</button></div></div></article>)}{candidates.length === 0 && <div className="empty-state">Nothing needs review.</div>}</div>
    </section>
  </div>;
}

export function AgentsWorkspace() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [request, setRequest] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try { setRuns(await api<Run[]>("/agents?limit=100")); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  const refreshDetail = useCallback(async (id: string) => {
    try { setDetail(await api<RunDetail>("/agents/" + encodeURIComponent(id))); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => {
    void refresh();
    const handle = window.setInterval(() => { void refresh(); if (selected) void refreshDetail(selected); }, 1800);
    return () => window.clearInterval(handle);
  }, [refresh, refreshDetail, selected]);
  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!request.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const result = await api<{run_id: string}>("/agents", json({ request: request.trim(), workspace: workspace.trim() || null }));
      setRequest(""); setSelected(result.run_id); await refresh(); await refreshDetail(result.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function decide(approved: boolean) {
    if (!detail) return;
    try {
      await api("/agents/" + encodeURIComponent(detail.id) + "/approval", json({ approved }));
      await refreshDetail(detail.id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <div className="workspace-page">
    <div className="workspace-heading"><div><div className="eyebrow">APPROVAL-GATED EXECUTION</div><h1>Agents</h1><p>Run Evo's existing coding agent, inspect its tool history, and approve every file write or command.</p></div><span className="workspace-count">{runs.length} runs</span></div>
    {error && <div className="workspace-error" role="alert">{error}</div>}
    <section className="workspace-panel">
      <h2>Start a coding task</h2>
      <form className="agent-launch" onSubmit={start}>
        <textarea value={request} onChange={e => setRequest(e.target.value)} rows={3} placeholder="Describe the task. Evo will inspect the workspace first, then request approval before writes or commands…"/>
        <div className="agent-launch-footer"><input value={workspace} onChange={e => setWorkspace(e.target.value)} placeholder="Workspace path (blank uses configured workspace)"/><button disabled={busy || !request.trim()}>{busy ? "Starting…" : "Start agent"}</button></div>
      </form>
      <div className="policy-note">Read-only inspection runs automatically. File writes and allowlisted commands require explicit approval. Execution is bounded; background cancellation is not yet supported.</div>
    </section>
    <div className="agent-layout">
      <section className="workspace-panel run-list-panel"><div className="panel-toolbar"><div><h2>Run history</h2><p>Most recent first</p></div><button className="quiet-button" onClick={() => void refresh()}>Refresh</button></div>
        <div className="run-list">{runs.map(run => <button key={run.id} className={"run-row " + (selected === run.id ? "selected" : "")} onClick={() => { setSelected(run.id); void refreshDetail(run.id); }}><span className={"run-status " + run.status}>{run.status}</span><strong>{String(run.metadata.request || run.summary || "Coding run").slice(0, 90)}</strong><small>{new Date(run.started_at).toLocaleString()}</small></button>)}{runs.length === 0 && <div className="empty-state">No agent runs yet.</div>}</div>
      </section>
      <section className="workspace-panel run-detail-panel"><div className="panel-toolbar"><div><h2>Execution details</h2><p>{detail ? detail.id : "Select a run to inspect its activity"}</p></div>{detail && <span className={"run-status " + detail.status}>{detail.status}</span>}</div>
        {detail ? <><div className="run-summary"><strong>{detail.metadata.request || detail.summary || "Coding task"}</strong><small>Workspace: {detail.metadata.workspace || "—"} · Model: {detail.metadata.model || "—"}</small>{detail.summary && <p>{detail.summary}</p>}</div>
          {detail.pending_approval && <div className="approval-card"><div className="approval-title">Approval required · {detail.pending_approval.tool_name}</div><pre>{JSON.stringify(detail.pending_approval.arguments, null, 2)}</pre><div className="inline-actions"><button className="quiet-button danger" onClick={() => void decide(false)}>Deny</button><button onClick={() => void decide(true)}>Approve action</button></div></div>}
          <div className="event-list">{detail.events.map(event => <article className="event-card" key={event.id}><div className="event-head"><strong>{event.tool_name}</strong><span className={"run-status " + event.status}>{event.status}</span></div><pre>{JSON.stringify(event.input, null, 2)}</pre><p>{event.output}</p><small>{new Date(event.created_at).toLocaleString()}</small></article>)}{detail.events.length === 0 && <div className="empty-state">No tool activity recorded yet.</div>}</div>
        </> : <div className="empty-state detail-empty">Choose an agent run to see its plan, approvals, and recorded tool events.</div>}
      </section>
    </div>
  </div>;
}
