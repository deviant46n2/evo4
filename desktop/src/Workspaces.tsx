import { useCallback, useEffect, useRef, useState } from "react";
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

type DemoStatus = {active:boolean;memories:number;candidates:number;agent_runs:number;experiments:number};
function DemoDataBanner() {
  const [status,setStatus]=useState<DemoStatus|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const refresh=useCallback(async()=>{try{setStatus(await api<DemoStatus>("/demo/status"));setError("");}catch(e){setError(e instanceof Error?e.message:String(e));}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  async function change(seed:boolean) {
    setBusy(true);setError("");
    try { await api("/demo/seed",seed?json({}):{method:"DELETE"}); await refresh(); window.dispatchEvent(new Event("evo-demo-data-changed")); }
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  return <section className="demo-data-banner">
    <div><div className="demo-data-title"><span className="demo-tag">SAMPLE DATA</span><strong>Explore populated workspaces</strong></div>
      <p>Clearly labeled illustrative memories, agent activity, experiment results, and historical telemetry. These are not real measurements or completed work.</p>
      {status&&status.active&&<small>{status.memories} memories · {status.candidates} candidates · {status.agent_runs} agent runs · {status.experiments} experiments</small>}
      {error&&<small className="workspace-error">{error}</small>}
    </div>
    <div className="inline-actions">
      <button className="quiet-button" disabled={busy||!!status?.active} onClick={()=>void change(true)}>{busy?"Working…":"Load sample data"}</button>
      {status?.active&&<button className="quiet-button danger" disabled={busy} onClick={()=>{if(window.confirm("Remove only Evo sample records? Your real data will not be touched."))void change(false);}}>Remove samples</button>}
    </div>
  </section>;
}

type Memory = { id: string; content: string; category: string; source: string; confidence: number; status: string; created_at: string; access_count: number };
type Candidate = { id: string; content: string; category: string; source: string; confidence: number; created_at: string };
type RecallPreview = { query:string; count:number; retrieval:string; matches:Array<{id:string;content:string;category:string;source:string;confidence:number;score:number;coverage:number;matched_terms:string[];reason:string;method:string}> };
type MemoryReview = {count:number;analyzed_records:number;method:string;mutates_memory:boolean;note:string;suggestions:Array<{left:{id:string;content:string;category:string;source:string;confidence:number};right:{id:string;content:string;category:string;source:string;confidence:number};similarity:number;jaccard:number;containment:number;shared_terms:string[];reason:string;method:string}>};
type Run = { id: string; kind: string; status: string; started_at: string; finished_at?: string; summary?: string; metadata: Record<string, any> };
type RunDetail = Run & { events: Array<{ id: number; tool_name: string; input: Record<string, any>; output: string; status: string; created_at: string }>; pending_approval: null | { id: string; tool_name: string; arguments: Record<string, any> } };

export function MemoryWorkspace() {
  const [items, setItems] = useState<Memory[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [query, setQuery] = useState("");
  const [recallQuery, setRecallQuery] = useState("");
  const [recallPreview, setRecallPreview] = useState<RecallPreview | null>(null);
  const [recallBusy, setRecallBusy] = useState(false);
  const [reviewResults, setReviewResults] = useState<MemoryReview | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [status, setStatus] = useState("active");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("general");
  const [replacing, setReplacing] = useState<string | null>(null);
  const [replacement, setReplacement] = useState("");
  const [reason, setReason] = useState("");
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
  useEffect(() => {
    void refresh();
    const changed=()=>void refresh();
    window.addEventListener("evo-demo-data-changed",changed);
    return ()=>window.removeEventListener("evo-demo-data-changed",changed);
  }, [refresh]);
  async function previewRecall(event: FormEvent) {
    event.preventDefault();
    if (!recallQuery.trim() || recallBusy) return;
    setRecallBusy(true); setError(""); setRecallPreview(null);
    try {
      const params = new URLSearchParams({ q: recallQuery.trim(), limit: "8" });
      setRecallPreview(await api<RecallPreview>("/memories/search?" + params.toString()));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setRecallBusy(false); }
  }
  async function scanForDuplicates() {
    if (reviewBusy) return;
    setReviewBusy(true); setError(""); setReviewResults(null);
    try { setReviewResults(await api<MemoryReview>("/memories/review?limit=30")); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setReviewBusy(false); }
  }
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
  async function supersede(id: string) {
    if (!replacement.trim()) return;
    try {
      await api("/memories/" + encodeURIComponent(id) + "/supersede", json({ content: replacement.trim(), reason: reason.trim() }));
      setReplacing(null); setReplacement(""); setReason(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function review(id: string, approved: boolean) {
    try { await api("/memory-candidates/" + encodeURIComponent(id) + "/review", json({ approved })); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <div className="workspace-page">
    <DemoDataBanner/>
    <div className="workspace-heading"><div><div className="eyebrow">PERSISTENT KNOWLEDGE</div><h1>Memory</h1><p>Review what Evo has stored, where it came from, and what is still awaiting your approval.</p></div><span className="workspace-count">{items.length} records</span></div>
    {error && <div className="workspace-error" role="alert">{error}</div>}
    <section className="workspace-panel">
      <h2>Test memory recall</h2>
      <p>Preview the records Evo would retrieve for a prompt, including why each result matched.</p>
      <form className="memory-add" onSubmit={previewRecall}>
        <div className="memory-add-footer"><input value={recallQuery} onChange={e => setRecallQuery(e.target.value)} placeholder="Try a natural-language question or topic…" aria-label="Memory recall query"/><button disabled={recallBusy || !recallQuery.trim()}>{recallBusy ? "Searching…" : "Preview recall"}</button></div>
      </form>
      {recallPreview && <div className="record-list">
        <small>{recallPreview.count} results · {recallPreview.retrieval}</small>
        {recallPreview.matches.map((match,index)=><article className="record-card" key={match.id}>
          <div className="record-top"><span className="record-category">#{index+1} · {match.category}</span><span>{match.source}</span><span>rank score {match.score.toFixed(3)}</span></div>
          <p>{match.content}</p>
          <div className="record-bottom"><small>{match.reason} · {Math.round(match.coverage*100)}% query-term coverage</small></div>
        </article>)}
        {recallPreview.count===0 && <div className="empty-state">No active memories matched this query.</div>}
      </div>}
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Review possible duplicates</h2><p>Find records with substantial shared wording. This scan is read-only and never merges or changes memories.</p></div><button className="quiet-button" disabled={reviewBusy} onClick={()=>void scanForDuplicates()}>{reviewBusy?"Scanning…":"Scan memories"}</button></div>
      {reviewResults && <><small>{reviewResults.count} suggestions from {reviewResults.analyzed_records} active records · {reviewResults.method}</small><p className="policy-note">{reviewResults.note}</p>
        <div className="record-list">{reviewResults.suggestions.map((pair,index)=><article className="record-card" key={pair.left.id+":"+pair.right.id}>
          <div className="record-top"><span className="record-category">Possible duplicate #{index+1}</span><span>similarity {pair.similarity.toFixed(2)}</span></div>
          <p><strong>{pair.left.category} · {pair.left.source}</strong><br/>{pair.left.content}</p>
          <p><strong>{pair.right.category} · {pair.right.source}</strong><br/>{pair.right.content}</p>
          <div className="record-bottom"><small>Shared terms: {pair.shared_terms.join(", ")}</small></div>
        </article>)}{reviewResults.count===0&&<div className="empty-state">No strong lexical-overlap candidates found. This does not rule out paraphrases or semantic duplicates.</div>}</div>
      </>}
    </section>
    <section className="workspace-panel">
      <h2>Add a memory</h2>
      <form className="memory-add" onSubmit={addMemory}>
        <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="A fact, preference, project decision, or correction you want Evo to retain…" rows={3}/>
        <div className="memory-add-footer"><input aria-label="Memory category" value={category} onChange={e => setCategory(e.target.value)} placeholder="Category"/><button disabled={busy || !content.trim()}>{busy ? "Saving…" : "Save memory"}</button></div>
      </form>
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Saved records</h2><p>Explicitly stored facts and user-approved candidates</p></div><div className="memory-filters"><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search memories…"/><select value={status} onChange={e => setStatus(e.target.value)}><option value="active">Active</option><option value="archived">Archived</option><option value="superseded">Superseded</option></select></div></div>
      <div className="record-list">{items.map(item => <article className="record-card" key={item.id}><div className="record-top"><span className="record-category">{item.category}</span><span>{item.source}</span>{item.source==="demo-seed"&&<span className="demo-tag">SAMPLE</span>}<span>{Math.round(item.confidence * 100)}% confidence</span></div><p>{item.content}</p><div className="record-bottom"><small>Added {new Date(item.created_at).toLocaleString()} · Retrieved {item.access_count} times</small>{item.status === "active" && <div className="inline-actions"><button className="quiet-button" onClick={() => { setReplacing(replacing === item.id ? null : item.id); setReplacement(""); setReason(""); }}>Correct / replace</button><button className="quiet-button danger" onClick={() => void archive(item.id)}>Archive</button></div>}</div>{replacing === item.id && <div className="supersede-editor"><textarea value={replacement} onChange={e => setReplacement(e.target.value)} placeholder="Enter the corrected memory…" rows={2}/><input value={reason} onChange={e => setReason(e.target.value)} placeholder="Why is this replacing the old record? (optional)"/><div className="inline-actions"><button className="quiet-button" onClick={() => setReplacing(null)}>Cancel</button><button disabled={!replacement.trim()} onClick={() => void supersede(item.id)}>Save correction</button></div></div>}</article>)}{items.length === 0 && <div className="empty-state">No {status} memories match this view.</div>}</div>
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Awaiting review</h2><p>Heuristically detected candidates are not used as trusted memories until accepted.</p></div><span className="workspace-count">{candidates.length} pending</span></div>
      <div className="record-list">{candidates.map(item => <article className="record-card candidate-card" key={item.id}><div className="record-top"><span className="record-category">{item.category}</span><span>{item.source}</span>{item.source==="demo-seed"&&<span className="demo-tag">SAMPLE</span>}<span>{Math.round(item.confidence * 100)}% candidate confidence</span></div><p>{item.content}</p><div className="record-bottom"><small>Detected {new Date(item.created_at).toLocaleString()}</small><div className="inline-actions"><button className="quiet-button" onClick={() => void review(item.id, false)}>Reject</button><button onClick={() => void review(item.id, true)}>Accept</button></div></div></article>)}{candidates.length === 0 && <div className="empty-state">Nothing needs review.</div>}</div>
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
    const changed=()=>{void refresh();if(selected)void refreshDetail(selected);};
    window.addEventListener("evo-demo-data-changed",changed);
    const handle = window.setInterval(() => { void refresh(); if (selected) void refreshDetail(selected); }, 1800);
    return () => {window.clearInterval(handle);window.removeEventListener("evo-demo-data-changed",changed);};
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
    <DemoDataBanner/>
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
        <div className="run-list">{runs.map(run => <button key={run.id} className={"run-row " + (selected === run.id ? "selected" : "")} onClick={() => { setSelected(run.id); void refreshDetail(run.id); }}><span className={"run-status " + run.status}>{run.status}</span><strong>{String(run.metadata.request || run.summary || "Coding run").slice(0, 90)} {run.metadata.demo_seed&&<span className="demo-tag">SAMPLE</span>}</strong><small>{new Date(run.started_at).toLocaleString()}</small></button>)}{runs.length === 0 && <div className="empty-state">No agent runs yet.</div>}</div>
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


type HardwareSample = {
  sampled_at: string; gpu_name: string | null; gpu_available: boolean;
  gpu_utilization_percent: number | null; gpu_memory_used_mib: number | null;
  gpu_memory_total_mib: number | null; gpu_memory_used_percent: number | null;
  gpu_temperature_c: number | null; gpu_power_w: number | null;
  gpu_processes: Array<{pid:number;process_name:string;memory_used_mib:number}>;
  cpu_utilization_percent: number | null; cpu_logical_cores: number | null;
  load_average_1m: number | null; load_average_5m: number | null; load_average_15m: number | null;
  ram_used_mib: number | null; ram_used_percent: number | null;
  ram_total_bytes: number | null; ram_available_bytes: number | null;
};
type HardwareResponse = {telemetry_error?:string|null;sample:HardwareSample;runtime:{provider:string;model:string;endpoint:string};budget:{vram_free_mib:number|null;ram_free_mib:number|null;background_work:string;reason:string};policy:{mode:string;actions_enabled:boolean;description:string};warnings:Array<{level:string;code:string;message:string}>};
type HardwareHistory = {id:number;experiment_id:number;is_demo?:boolean;sampled_at:string;gpu_utilization_percent:number|null;gpu_memory_used_mib:number|null;gpu_temperature_c:number|null;ram_used_mib:number|null;cpu_utilization_percent:number|null;ram_used_percent:number|null;gpu_memory_used_percent:number|null};
type ExperimentRun = {id:number;is_demo?:boolean;started_at:string;finished_at:string|null;task_id:string;category:string;repetition:number;model:string;run_label:string|null;status:string;error:string|null;elapsed_seconds:number|null;time_to_first_token_seconds:number|null;prompt_tokens:number|null;completion_tokens:number|null;tokens_per_second:number|null;evaluation_status:string|null;evaluation_passed:number|null;evaluation_total:number|null};
type ExperimentAggregate = {configuration:string;is_demo?:boolean;model:string;category:string;runs:number;completed:number;failed:number;avg_tokens_per_second:number|null;avg_ttft_seconds:number|null;peak_vram_mib:number|null;peak_ram_mib:number|null};

function Metric({label,value,detail,percent}:{label:string;value:string;detail?:string;percent?:number|null}) {
  const width = percent == null || !Number.isFinite(percent) ? 0 : Math.max(0,Math.min(100,percent));
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong>{percent != null && <div className="metric-track"><i style={{width:width+"%"}}/></div>}{detail && <small>{detail}</small>}</article>;
}
function fmt(value:number|null|undefined,digits=1) { return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits); }
function mib(value:number|null|undefined) { return value == null ? "—" : value >= 1024 ? (value/1024).toFixed(1)+" GiB" : Math.round(value)+" MiB"; }
function HistoryLine({samples,field,label}:{samples:HardwareHistory[];field:"gpu_utilization_percent"|"gpu_memory_used_mib"|"gpu_temperature_c"|"ram_used_mib"|"cpu_utilization_percent";label:string}) {
  const values=samples.map(item=>item[field]).filter((value):value is number=>value!=null&&Number.isFinite(value));
  const max=Math.max(1,...values);
  const points=values.map((value,index)=>`${values.length<2?0:index/(values.length-1)*600},${92-value/max*82}`).join(" ");
  return <div className="history-chart"><div className="history-chart-head"><strong>{label}</strong><small>{values.length} recorded samples{samples.some(item=>item.is_demo)?" · includes samples":""}</small></div>{values.length>1?<svg viewBox="0 0 600 100" preserveAspectRatio="none" role="img" aria-label={label+" history"}><line x1="0" y1="92" x2="600" y2="92"/><polyline points={points}/></svg>:<div className="chart-empty">Run an Evo Lab experiment to record resource history.</div>}</div>;
}


type ScheduledJob = {id:string;name:string;description:string;kind:string;status:string;priority:number;gpu_heavy:boolean|null;estimated_vram_mib:number|null;estimated_ram_mib:number|null;created_at:string;lease_expires_at:string|null;last_decision: {decision?:string;reasons?:string[]};outcome_note:string};
type SchedulerResponse = {jobs:ScheduledJob[];counts:Record<string,number>;lease_seconds:number;process_control:boolean};
function WorkloadSchedulerPanel() {
  const [data,setData]=useState<SchedulerResponse|null>(null);
  const [name,setName]=useState("");
  const [kind,setKind]=useState("benchmark");
  const [priority,setPriority]=useState("10");
  const [gpuHeavy,setGpuHeavy]=useState("auto");
  const [vram,setVram]=useState("");
  const [ram,setRam]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{try{setData(await api<SchedulerResponse>("/hardware/scheduler"));setError("");}catch(e){setError(e instanceof Error?e.message:String(e));}},[]);
  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),5000);return()=>window.clearInterval(id);},[refresh]);
  async function create(event:FormEvent) {
    event.preventDefault();if(!name.trim()||busy)return;setBusy(true);setError("");
    try {
      await api("/hardware/scheduler/jobs",json({name:name.trim(),kind,priority:Number(priority),
        gpu_heavy:gpuHeavy==="auto"?null:gpuHeavy==="true",
        estimated_vram_mib:vram.trim()?Number(vram):null,
        estimated_ram_mib:ram.trim()?Number(ram):null}));
      setName("");await refresh();
    } catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function action(path:string,body?:unknown) {
    if(busy)return;setBusy(true);setError("");
    try{await api(path,body===undefined?{method:"POST"}:json(body));await refresh();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const jobs=data?.jobs||[];
  return <section className="workspace-panel">
    <div className="panel-toolbar"><div><h2>Workload scheduler</h2><p>Persistent queue, resource reservations and explicit workload lifecycle.</p></div><span className="run-status">RESERVATION ONLY</span></div>
    <p className="policy-copy">Evo never launches, kills or reconfigures processes. Dispatch reserves capacity using live telemetry; you start the workload yourself and confirm when it finishes. Unstarted reservations expire after five minutes.</p>
    {error&&<div className="workspace-error" role="alert">{error}</div>}
    <form className="scheduler-form" onSubmit={create}>
      <label>Workload name<input value={name} onChange={e=>setName(e.target.value)} maxLength={120} required placeholder="e.g. Memory retrieval benchmark"/></label>
      <label>Type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="benchmark">Benchmark</option><option value="research">Research</option><option value="agent">Agent</option><option value="maintenance">Maintenance</option><option value="cpu">CPU-only</option><option value="background">General background</option></select></label>
      <label>Priority (1–100)<input type="number" min="1" max="100" value={priority} onChange={e=>setPriority(e.target.value)}/></label>
      <label>GPU use<select value={gpuHeavy} onChange={e=>setGpuHeavy(e.target.value)}><option value="auto">Assume GPU-heavy</option><option value="true">GPU-heavy</option><option value="false">CPU-only (declared)</option></select></label>
      <label>Estimated VRAM (MiB)<input type="number" min="0" max="1000000" value={vram} onChange={e=>setVram(e.target.value)} placeholder="Required for GPU jobs"/></label>
      <label>Estimated RAM (MiB)<input type="number" min="0" max="1000000" value={ram} onChange={e=>setRam(e.target.value)} placeholder="Required for background jobs"/></label>
      <div className="inline-actions"><button className="primary-button" type="submit" disabled={busy||!name.trim()}>{busy?"Working…":"Add to queue"}</button><button className="quiet-button" type="button" disabled={busy} onClick={()=>void action("/hardware/scheduler/dispatch?limit=5")}>Evaluate queue and reserve</button><button className="quiet-button" type="button" disabled={busy} onClick={()=>void refresh()}>Refresh</button></div>
    </form>
    <div className="scheduler-counts">{["queued","reserved","running","completed","failed","cancelled"].map(key=><span key={key}><b>{data?.counts[key]||0}</b><small>{key}</small></span>)}</div>
    <div className="scheduler-jobs">{jobs.map(job=><article className="scheduler-job" key={job.id}>
      <div className="record-top"><span className={"run-status "+job.status}>{job.status}</span><span>{job.kind}</span><span>Priority {job.priority}</span></div>
      <strong>{job.name}</strong>
      <small>VRAM {job.estimated_vram_mib==null?"unknown":mib(job.estimated_vram_mib)} · RAM {job.estimated_ram_mib==null?"unknown":mib(job.estimated_ram_mib)} · GPU {job.gpu_heavy===false?"CPU-only":job.gpu_heavy===true?"yes":"assumed"}</small>
      {job.last_decision?.reasons?.map((reason,index)=><small key={index}>{reason}</small>)}
      {job.status==="reserved"&&<small>Reservation expires: {job.lease_expires_at?new Date(job.lease_expires_at).toLocaleTimeString():"—"}</small>}
      {job.status==="running"&&<small>Running is user-confirmed; Evo does not monitor or control the external process.</small>}
      <div className="inline-actions">
        {job.status==="reserved"&&<button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/start")}>Confirm external start</button>}
        {job.status==="running"&&<><button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/finish",{outcome:"completed"})}>Mark completed</button><button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/finish",{outcome:"failed",note:"Marked failed by user"})}>Mark failed</button></>}
        {(job.status==="queued"||job.status==="reserved")&&<button className="quiet-button danger" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/cancel")}>Cancel queued job</button>}
      </div>
    </article>)}
    {!jobs.length&&<div className="empty-state">No scheduled workloads yet. Add a workload above to begin building a persistent queue.</div>}</div>
  </section>;
}

export function HardwareWorkspace() {
  const [data,setData]=useState<HardwareResponse|null>(null);
  const [history,setHistory]=useState<HardwareHistory[]>([]);
  const [error,setError]=useState("");
  const [historyError,setHistoryError]=useState("");
  const refreshing=useRef(false);
  const refresh=useCallback(async()=>{
    if(refreshing.current)return;
    refreshing.current=true;
    try {
      const [current,series]=await Promise.allSettled([
        api<HardwareResponse>("/hardware/current"),
        api<HardwareHistory[]>("/hardware/history?limit=180"),
      ]);
      if(current.status==="fulfilled"){setData(current.value);setError("");}
      else setError(current.reason instanceof Error?current.reason.message:String(current.reason));
      if(series.status==="fulfilled"){setHistory(series.value);setHistoryError("");}
      else setHistoryError(series.reason instanceof Error?series.reason.message:String(series.reason));
    } finally {refreshing.current=false;}
  },[]);
  useEffect(()=>{void refresh();const changed=()=>void refresh();window.addEventListener("evo-demo-data-changed",changed);const id=window.setInterval(()=>void refresh(),3000);return()=>{window.clearInterval(id);window.removeEventListener("evo-demo-data-changed",changed);};},[refresh]);
  const s=data?.sample;
  return <div className="workspace-page telemetry-page">
    <DemoDataBanner/>
    <div className="workspace-heading"><div><div className="eyebrow">LIVE SYSTEM OBSERVABILITY</div><h1>Hardware</h1><p>Live resource telemetry, GPU workloads, and conservative pressure warnings.</p></div><div className="telemetry-heading-right">{data?<span className="live-indicator">LIVE · 3s</span>:<span className="workspace-count">{error?"API OFFLINE":"CONNECTING"}</span>}<button className="quiet-button" onClick={()=>void refresh()}>Refresh</button></div></div>
    {error&&<div className="workspace-error" role="alert">Hardware API request failed: {error}. Check that the backend serving this page is the current Evo build and is listening on 127.0.0.1:8765.</div>}
    {historyError&&<div className="workspace-error" role="alert">Historical telemetry is unavailable: {historyError}. Live hardware metrics can still be used.</div>}
    {data?.telemetry_error&&<div className="workspace-error" role="alert">A hardware probe failed: {data.telemetry_error}. Other available metrics are still shown.</div>}
    {!data&&!error&&<div className="empty-state">Connecting to Evo local hardware API…</div>}
    <div className="telemetry-grid">
      <Metric label="GPU utilization" value={s?.gpu_utilization_percent==null?"—":fmt(s.gpu_utilization_percent,0)+"%"} detail={s?.gpu_name||"NVIDIA telemetry unavailable"} percent={s?.gpu_utilization_percent}/>
      <Metric label="VRAM in use" value={s?.gpu_memory_used_mib==null?"—":mib(s.gpu_memory_used_mib)} detail={s?.gpu_memory_total_mib==null?"No GPU detected":mib(s.gpu_memory_total_mib)+" total"} percent={s?.gpu_memory_used_percent}/>
      <Metric label="GPU temperature" value={s?.gpu_temperature_c==null?"—":fmt(s.gpu_temperature_c,0)+"°C"} detail={s?.gpu_power_w==null?"Power unavailable":fmt(s.gpu_power_w,0)+" W board draw"}/>
      <Metric label="CPU utilization" value={s?.cpu_utilization_percent==null?"Sampling…":fmt(s.cpu_utilization_percent,0)+"%"} detail={(s?.cpu_logical_cores??"—")+" logical cores"} percent={s?.cpu_utilization_percent}/>
      <Metric label="System RAM" value={s?.ram_used_mib==null?"—":mib(s.ram_used_mib)} detail={s?.ram_used_percent==null?"Memory unavailable":fmt(s.ram_used_percent,0)+"% used"} percent={s?.ram_used_percent}/>
      <Metric label="Load average" value={fmt(s?.load_average_1m,2)} detail={"5m "+fmt(s?.load_average_5m,2)+" · 15m "+fmt(s?.load_average_15m,2)}/>
    </div>
    <section className="workspace-panel"><div className="panel-toolbar"><div><h2>Active inference runtime</h2><p>Provider identity from Evo configuration; endpoint shown without credentials.</p></div><span className="workspace-count">{data?.runtime.provider||"—"}</span></div><div className="runtime-details"><div><small>MODEL</small><strong>{data?.runtime.model||"—"}</strong></div><div><small>ENDPOINT</small><strong>{data?.runtime.endpoint||"—"}</strong></div></div></section>
    <section className="workspace-panel"><div className="panel-toolbar"><div><h2>Resource policy</h2><p>Observe-first guardrails. No process control is enabled in this milestone.</p></div><span className="run-status">ADVISORY ONLY</span></div><p className="policy-copy">{data?.policy.description||"Waiting for telemetry…"}</p><div className="budget-recommendation"><strong>{data?.budget.background_work==="defer"?"Defer background work":"Limited background work"}</strong><span>{data?.budget.reason||"Waiting for telemetry…"}</span><small>Free VRAM: {mib(data?.budget.vram_free_mib)} · Available RAM: {mib(data?.budget.ram_free_mib)}</small></div>{data?.warnings.length?<div className="warning-list">{data.warnings.map(w=><div className={"resource-warning "+w.level} key={w.code}><strong>{w.level.toUpperCase()}</strong><span>{w.message}</span></div>)}</div>:<div className="healthy-state">No resource pressure thresholds currently triggered.</div>}</section>
    <WorkloadSchedulerPanel/>\n    <div className="history-grid"><HistoryLine samples={history} field="gpu_utilization_percent" label="GPU utilization"/><HistoryLine samples={history} field="gpu_memory_used_mib" label="VRAM allocation"/><HistoryLine samples={history} field="ram_used_mib" label="System RAM"/><HistoryLine samples={history} field="cpu_utilization_percent" label="CPU utilization"/><HistoryLine samples={history} field="gpu_temperature_c" label="GPU temperature"/></div>
    <section className="workspace-panel"><div className="panel-toolbar"><div><h2>GPU compute processes</h2><p>Process identity, PID, and VRAM reported by NVIDIA's driver. Command-line arguments are intentionally hidden.</p></div><span className="workspace-count">{s?.gpu_processes.length??0} processes</span></div><div className="process-table"><div className="process-row process-header"><span>Process</span><span>PID</span><span>VRAM</span></div>{s?.gpu_processes.map(p=><div className="process-row" key={p.pid}><strong>{p.process_name}</strong><span>{p.pid}</span><span>{mib(p.memory_used_mib)}</span></div>)}{s?.gpu_processes.length===0&&<div className="empty-state">{s?.gpu_available?"No compute processes reported.":"NVIDIA telemetry unavailable; install/use nvidia-smi to expose GPU processes."}</div>}</div></section>
    <div className="policy-note">Live metrics come from this machine. Historical charts may include clearly labeled sample experiment data until you run your own Evo Lab experiments.</div>
  </div>;
}

export function ExperimentsWorkspace() {
  const [runs,setRuns]=useState<ExperimentRun[]>([]);
  const [aggregates,setAggregates]=useState<ExperimentAggregate[]>([]);
  const [available,setAvailable]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const refreshing=useRef(false);
  const refresh=useCallback(async()=>{
    if(refreshing.current)return;
    refreshing.current=true;
    try {const result=await api<{available:boolean;runs:ExperimentRun[];aggregates:ExperimentAggregate[];message?:string}>("/experiments?limit=100");setRuns(result.runs);setAggregates(result.aggregates);setAvailable(result.available);setMessage(result.message||"");setError("");}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{refreshing.current=false;}
  },[]);
  useEffect(()=>{void refresh();const changed=()=>void refresh();window.addEventListener("evo-demo-data-changed",changed);const id=window.setInterval(()=>void refresh(),10000);return()=>{window.clearInterval(id);window.removeEventListener("evo-demo-data-changed",changed);};},[refresh]);
  return <div className="workspace-page">
    <DemoDataBanner/>
    <div className="workspace-heading"><div><div className="eyebrow">REPRODUCIBLE PERFORMANCE</div><h1>Experiments</h1><p>Compare model configurations using measured speed, latency, evaluation outcomes, and resource peaks.</p></div><button className="quiet-button" onClick={()=>void refresh()}>Refresh</button></div>
    {error&&<div className="workspace-error" role="alert">{error}</div>}
    {!available&&<section className="workspace-panel"><div className="empty-state">{message||"No experiment database found."} Use the Evo Lab CLI to initialize the database and run a task suite; this screen only displays recorded results.</div></section>}
    {available&&<><section className="workspace-panel"><div className="panel-toolbar"><div><h2>Configuration comparisons</h2><p>Aggregated by configuration label, model, and task category.</p></div><span className="workspace-count">{aggregates.length} groups</span></div>{aggregates.length?<div className="aggregate-grid">{aggregates.map((a,i)=><article className="aggregate-card" key={a.configuration+"-"+a.category+"-"+i}><div className="record-top"><span className="record-category">{a.category}</span><span>{a.runs} runs</span>{a.is_demo&&<span className="demo-tag">SAMPLE</span>}</div><strong>{a.configuration}</strong><small>{a.model}</small><div className="aggregate-metrics"><span><b>{fmt(a.avg_tokens_per_second,1)}</b><small>tok/s avg</small></span><span><b>{fmt(a.avg_ttft_seconds,2)}s</b><small>TTFT avg</small></span><span><b>{a.completed}/{a.runs}</b><small>completed</small></span><span><b>{mib(a.peak_vram_mib)}</b><small>peak VRAM</small></span></div>{a.failed>0&&<div className="failed-note">{a.failed} failed runs</div>}</article>)}</div>:<div className="empty-state">No aggregate results yet.</div>}</section>
    <section className="workspace-panel"><div className="panel-toolbar"><div><h2>Recent runs</h2><p>Individual experiment records from the shared Evo Lab database.</p></div><span className="workspace-count">{runs.length} runs</span></div><div className="experiment-list">{runs.map(run=><article className="experiment-row" key={run.id}><div className="experiment-main"><div className="record-top"><span className={"run-status "+run.status}>{run.status}</span><span>{run.category}</span><span>#{run.id}</span>{run.is_demo&&<span className="demo-tag">SAMPLE</span>}</div><strong>{run.task_id}</strong><small>{run.run_label||run.model} · repetition {run.repetition} · {new Date(run.started_at).toLocaleString()}</small>{run.error&&<p className="failed-note">{run.error}</p>}</div><div className="experiment-stats"><span><b>{fmt(run.tokens_per_second,1)}</b><small>tok/s</small></span><span><b>{fmt(run.time_to_first_token_seconds,2)}s</b><small>TTFT</small></span><span><b>{run.evaluation_passed==null?"—":run.evaluation_passed+"/"+run.evaluation_total}</b><small>checks</small></span></div></article>)}{runs.length===0&&<div className="empty-state">No experiment runs recorded yet.</div>}</div></section></>}
  </div>;
}
