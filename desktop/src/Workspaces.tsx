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
type RunDetail = Run & { events: Array<{ id: number; tool_name: string; input: Record<string, any>; output: string; status: string; created_at: string }>; pending_approval: null | { id: string; tool_name: string; arguments: Record<string, any> }; background_task?: {status:string;cancel_requested:boolean}; background_events?: Array<{id:number;type:string;payload:Record<string,any>;created_at:string}> };
type AgentPlanSummary = {id:string;title:string;summary:string;status:string;created_at:string;updated_at:string;run_id:string|null;error:string};
type AgentPlan = AgentPlanSummary & {request:string;workspace:string;workspace_id?:string|null;steps:Array<{id:string;position:number;title:string;description:string;expected_outcome:string;verification:string;verification_commands?:string[][];verification_status?:string;verification_checks?:Array<{id:number;command:string[];status:string;exit_code:number|null;stdout:string;stderr:string;created_at:string}>;status:string;result:string}>;verification_summary?:{passed:number;failed:number;not_run:number;not_configured:number};events:Array<{id:number;step_id:string|null;type:string;payload:Record<string,any>;created_at:string}>};
type RegistryWorkspace = {workspace_id:string;name:string;status:string;project_id:string;checkout_id:string|null;configuration_id:string;configuration_revision_id:string};
type ProjectSummary = {project_id:string;name:string;status:string};
type ConfigurationSummary = {configuration_id:string;name:string;status:string};
type CheckoutSummary = {checkout_id:string;canonical_path:string;availability_status:string};
type TaskWorkspaceReview = {operation_id:string;status:string;stable:boolean;unstable:boolean;source_revision:string;current_head:string;changed_files:Array<{status:string;path:string}>;changed_file_count:number;changed_files_omitted:number;excluded_files:string[];excluded_files_omitted:number;unreadable_files:Array<{path:string;reason:string}>;unreadable_files_omitted:number;patch:string;patch_bytes:number;truncated:boolean;truncation_reason:string|null;max_files:number;max_bytes:number;execution_evidence?:Array<{run_id:string;kind:string;status:string;started_at:string;finished_at:string|null;summary:string|null;verification_state:string;successful_file_writes:number|null;plan_id:string|null;plan_status:string|null;verification_summary:{passed:number;failed:number;not_run:number;not_configured:number}|null;steps:Array<{step_id:string;position:number;title:string;status:string;verification_status:string;verification_checks:Array<{id:number;command:string[];status:string;exit_code:number|null;created_at:string;execution_id:string|null;stdout:string;stderr:string}>}>}>};
type TaskWorkspaceOperation = {operation_id:string;task_id:string;parent_workspace_id:string;task_workspace_id:string|null;project_id:string;checkout_id:string|null;source_revision:string;destination_path:string;status:string;created_at:string;updated_at:string;error_recorded:boolean};
type TaskWorkspaceOperationDetail = TaskWorkspaceOperation & {filesystem:{path_exists:boolean;path_is_directory:boolean;path_is_symlink:boolean};recovery_guidance:string|null};
type TaskWorkspaceFileItem = {name:string;path:string;kind:"directory"|"file"|"symlink"|"other";size_bytes:number|null;modified_at_ns:number};
type TaskWorkspaceFileListing = {operation_id:string;source_revision:string;path:string;items:TaskWorkspaceFileItem[];total:number;truncated:boolean;limit:number};
type TaskWorkspaceFileContent = {operation_id:string;source_revision:string;path:string;size_bytes:number;sha256:string;content:string;truncated:boolean;max_bytes:number};
type TaskWorkspaceFileChange = {change_id:string;operation_id:string;source_revision:string;path:string;before_sha256:string|null;after_sha256:string;size_bytes:number;created_at:string;status:"pending"|"applied"|"failed"|"indeterminate";error_code:string|null;finalized_at:string|null};
type TaskWorkspaceFileChanges = {operation_id:string;source_revision:string;items:TaskWorkspaceFileChange[];total:number;truncated:boolean;limit:number};

export function MemoryWorkspace({ projectId, workspaceId }: { projectId: string | null; workspaceId: string | null }) {
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
  const scopeWorkspaceId = workspaceId;
  const scopeKey = `${projectId || "global"}:${scopeWorkspaceId || ""}`;
  const scopeKeyRef = useRef(scopeKey);
  scopeKeyRef.current = scopeKey;
  const refreshGeneration = useRef(0);
  const scopeParams = useCallback(() => {
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (scopeWorkspaceId) params.set("workspace_id", scopeWorkspaceId);
    return params;
  }, [projectId, scopeWorkspaceId]);
  const scopeSuffix = useCallback(() => {
    const params = scopeParams();
    return params.toString() ? "?" + params.toString() : "";
  }, [scopeParams]);
  const refresh = useCallback(async () => {
    const requestId = ++refreshGeneration.current;
    const requestedScope = scopeKey;
    try {
      const params = new URLSearchParams({ status, limit: "200" });
      if (query.trim()) params.set("q", query.trim());
      scopeParams().forEach((value, key) => params.set(key, value));
      const candidateParams = new URLSearchParams({ limit: "200" });
      scopeParams().forEach((value, key) => candidateParams.set(key, value));
      const [memoryRows, candidateRows] = await Promise.all([
        api<Memory[]>("/memories?" + params.toString()),
        api<Candidate[]>("/memory-candidates?" + candidateParams.toString()),
      ]);
      if (requestId !== refreshGeneration.current || scopeKeyRef.current !== requestedScope) return;
      setItems(memoryRows); setCandidates(candidateRows); setError("");
    } catch (e) {
      if (requestId === refreshGeneration.current && scopeKeyRef.current === requestedScope) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [query, status, scopeParams, scopeKey]);
  useEffect(() => {
    setRecallPreview(null);
    setReviewResults(null);
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
      scopeParams().forEach((value, key) => params.set(key, value));
      const requestedScope = scopeKey;
      const result = await api<RecallPreview>("/memories/search?" + params.toString());
      if (scopeKeyRef.current === requestedScope) setRecallPreview(result);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setRecallBusy(false); }
  }
  async function scanForDuplicates() {
    if (reviewBusy) return;
    setReviewBusy(true); setError(""); setReviewResults(null);
    const requestedScope = scopeKey;
    try {
      const result = await api<MemoryReview>("/memories/review?limit=30" + scopeSuffix());
      if (scopeKeyRef.current === requestedScope) setReviewResults(result);
    } catch (e) {
      if (scopeKeyRef.current === requestedScope) setError(e instanceof Error ? e.message : String(e));
    }
    finally { setReviewBusy(false); }
  }
  async function addMemory(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api("/memories", json({ content: content.trim(), category, source: "user", confidence: 1,
        ...(projectId ? { project_id: projectId } : {}),
        ...(workspaceId ? { workspace_id: workspaceId } : {}) }));
      setContent(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function archive(id: string) {
    try { await api("/memories/" + encodeURIComponent(id) + "/archive" + scopeSuffix(), { method: "POST" }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function supersede(id: string) {
    if (!replacement.trim()) return;
    try {
      await api("/memories/" + encodeURIComponent(id) + "/supersede" + scopeSuffix(), json({ content: replacement.trim(), reason: reason.trim() }));
      setReplacing(null); setReplacement(""); setReason(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function review(id: string, approved: boolean) {
    try { await api("/memory-candidates/" + encodeURIComponent(id) + "/review" + scopeSuffix(), json({ approved })); await refresh(); }
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

export function AgentsWorkspace({ projectId, workspaceId: scopeWorkspaceId, onScopeChange }: {
  projectId: string | null;
  workspaceId: string | null;
  onScopeChange: (projectId: string | null, workspaceId: string | null) => void;
}) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [request, setRequest] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [isolateWorkspace, setIsolateWorkspace] = useState(false);
  const [taskReview, setTaskReview] = useState<TaskWorkspaceReview | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [taskReviewError, setTaskReviewError] = useState("");
  const [taskOperations, setTaskOperations] = useState<TaskWorkspaceOperation[]>([]);
  const [taskOperationDetail, setTaskOperationDetail] = useState<TaskWorkspaceOperationDetail | null>(null);
  const [taskOperationBusy, setTaskOperationBusy] = useState(false);
  const [taskOperationError, setTaskOperationError] = useState("");
  const [taskFiles, setTaskFiles] = useState<TaskWorkspaceFileListing | null>(null);
  const [taskFileContent, setTaskFileContent] = useState<TaskWorkspaceFileContent | null>(null);
  const [taskFileDraft, setTaskFileDraft] = useState("");
  const [taskFileChanges, setTaskFileChanges] = useState<TaskWorkspaceFileChanges | null>(null);
  const taskFileGeneration = useRef(0);
  const taskFileChangesGeneration = useRef(0);
  const [newTaskFilePath, setNewTaskFilePath] = useState("");
  const [taskFileSaving, setTaskFileSaving] = useState(false);
  const [taskFilePath, setTaskFilePath] = useState("");
  const [taskFileBusy, setTaskFileBusy] = useState(false);
  const [taskFileError, setTaskFileError] = useState("");
  const taskReviewGeneration = useRef(0);
  const selectedRunRef = useRef<string | null>(selected);
  selectedRunRef.current = selected;
  const [registryWorkspaces, setRegistryWorkspaces] = useState<RegistryWorkspace[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [configurations, setConfigurations] = useState<ConfigurationSummary[]>([]);
  const [checkouts, setCheckouts] = useState<Record<string, CheckoutSummary>>({});
  const runDetailGeneration = useRef(0);
  const planDetailGeneration = useRef(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const scopeParams = useCallback(() => {
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (scopeWorkspaceId) params.set("workspace_id", scopeWorkspaceId);
    return params;
  }, [projectId, scopeWorkspaceId]);
  const scopeSuffix = useCallback(() => {
    const params = scopeParams();
    return params.toString() ? "?" + params.toString() : "";
  }, [scopeParams]);
  const scopeKey = `${projectId || "global"}:${scopeWorkspaceId || ""}`;
  const scopeKeyRef = useRef(scopeKey);
  scopeKeyRef.current = scopeKey;
  const runsGeneration = useRef(0);
  const plansGeneration = useRef(0);
  const [plans, setPlans] = useState<AgentPlanSummary[]>([]);
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const refresh = useCallback(async () => {
    const requestId = ++runsGeneration.current;
    const requestedScope = scopeKey;
    try {
      const rows = await api<Run[]>("/agents?limit=100" + scopeSuffix());
      if (requestId === runsGeneration.current && scopeKeyRef.current === requestedScope) setRuns(rows);
      const taskParams = new URLSearchParams({limit:"100"});
      if (projectId) taskParams.set("project_id", projectId);
      try {
        const taskRows = await api<{items:TaskWorkspaceOperation[]}>("/task-workspaces?" + taskParams.toString());
        if (requestId === runsGeneration.current && scopeKeyRef.current === requestedScope) {
          setTaskOperations(taskRows.items);
          setTaskOperationError("");
        }
      } catch (taskError) {
        if (requestId === runsGeneration.current && scopeKeyRef.current === requestedScope) {
          setTaskOperationError(taskError instanceof Error ? taskError.message : String(taskError));
        }
      }
    } catch (e) {
      if (requestId === runsGeneration.current && scopeKeyRef.current === requestedScope) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [scopeSuffix, scopeKey]);
  const refreshPlans = useCallback(async () => {
    const requestId = ++plansGeneration.current;
    const requestedScope = scopeKey;
    try {
      const rows = await api<AgentPlanSummary[]>("/agents/plans?limit=30" + scopeSuffix());
      if (requestId === plansGeneration.current && scopeKeyRef.current === requestedScope) setPlans(rows);
    } catch (e) {
      if (requestId === plansGeneration.current && scopeKeyRef.current === requestedScope) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [scopeSuffix, scopeKey]);
  const loadPlan = useCallback(async (id: string) => {
    const token = ++planDetailGeneration.current;
    try {
      const result = await api<AgentPlan>("/agents/plans/" + encodeURIComponent(id) + scopeSuffix());
      if (token !== planDetailGeneration.current) return;
      setPlan(result);
    } catch (e) {
      if (token !== planDetailGeneration.current) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [scopeSuffix]);
  const refreshDetail = useCallback(async (id: string) => {
    const token = ++runDetailGeneration.current;
    try {
      const result = await api<RunDetail>("/agents/" + encodeURIComponent(id) + scopeSuffix());
      if (token !== runDetailGeneration.current) return;
      setDetail(result);
    } catch (e) {
      if (token !== runDetailGeneration.current) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [scopeSuffix]);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [workspaceResult, projectResult, configurationResult] = await Promise.all([
          api<{items: RegistryWorkspace[]}>("/workspaces?status=active"),
          api<{items: ProjectSummary[]}>("/projects?status=active"),
          api<{items: ConfigurationSummary[]}>("/configurations?status=active"),
        ]);
        if (!alive) return;
        setRegistryWorkspaces(workspaceResult.items);
        setProjects(projectResult.items);
        setConfigurations(configurationResult.items);
        const checkoutIds = [...new Set(workspaceResult.items.map(item => item.checkout_id).filter(Boolean))] as string[];
        const checkoutEntries = await Promise.all(checkoutIds.map(async id => {
          try { return [id, await api<CheckoutSummary>("/checkouts/" + encodeURIComponent(id))] as const; }
          catch { return [id, null] as const; }
        }));
        if (!alive) return;
        const next: Record<string, CheckoutSummary> = {};
        for (const [id, checkout] of checkoutEntries) if (checkout) next[id] = checkout;
        setCheckouts(next);
      } catch (e) { if (alive) setError(e instanceof Error ? e.message : String(e)); }
    })();
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!selected) runDetailGeneration.current += 1;
    taskFileGeneration.current += 1;
    taskFileChangesGeneration.current += 1;
    setTaskFiles(null);
    setTaskFileContent(null);
    setTaskFileDraft("");
    setTaskFileChanges(null);
    setNewTaskFilePath("");
    setTaskFilePath("");
    setTaskFileError("");
    setTaskFileBusy(false);
    setTaskFileSaving(false);
  }, [selected]);
  useEffect(() => {
    void refresh(); void refreshPlans();
    const changed=()=>{void refresh();void refreshPlans();if(selected)void refreshDetail(selected);};
    window.addEventListener("evo-demo-data-changed",changed);
    const handle = window.setInterval(() => { void refresh(); void refreshPlans(); if (selected) void refreshDetail(selected); if (plan) void loadPlan(plan.id); }, 1800);
    return () => {window.clearInterval(handle);window.removeEventListener("evo-demo-data-changed",changed);};
  }, [refresh, refreshDetail, refreshPlans, loadPlan, selected, plan?.id]);
  async function inspectTaskOperation(operationId: string) {
    setTaskOperationBusy(true); setTaskOperationError(""); setTaskOperationDetail(null);
    try {
      const result = await api<TaskWorkspaceOperationDetail>("/task-workspaces/" + encodeURIComponent(operationId));
      setTaskOperationDetail(result);
    } catch (e) {
      setTaskOperationError(e instanceof Error ? e.message : String(e));
    } finally { setTaskOperationBusy(false); }
  }
  async function loadTaskFiles(operationId: string, path = "") {
    const token = ++taskFileGeneration.current;
    setTaskFileBusy(true); setTaskFileError(""); setTaskFileContent(null); setTaskFileDraft("");
    try {
      const params = new URLSearchParams({path, limit:"200"});
      const result = await api<TaskWorkspaceFileListing>("/task-workspaces/" + encodeURIComponent(operationId) + "/files?" + params.toString());
      if (token !== taskFileGeneration.current) return;
      setTaskFiles(result); setTaskFilePath(path); setTaskFileDraft("");
    } catch (e) {
      if (token === taskFileGeneration.current) setTaskFileError(e instanceof Error ? e.message : String(e));
    } finally { if (token === taskFileGeneration.current) setTaskFileBusy(false); }
  }
  async function openTaskFile(operationId: string, path: string) {
    const token = ++taskFileGeneration.current;
    setTaskFileBusy(true); setTaskFileError(""); setTaskFileContent(null);
    try {
      const params = new URLSearchParams({path, max_bytes:"262144"});
      const result = await api<TaskWorkspaceFileContent>("/task-workspaces/" + encodeURIComponent(operationId) + "/file?" + params.toString());
      if (token !== taskFileGeneration.current) return;
      setTaskFileContent(result); setTaskFileDraft(result.content);
    } catch (e) {
      if (token === taskFileGeneration.current) setTaskFileError(e instanceof Error ? e.message : String(e));
    } finally { if (token === taskFileGeneration.current) setTaskFileBusy(false); }
  }
  async function loadTaskChanges(operationId: string) {
    const token = ++taskFileChangesGeneration.current;
    try {
      const result = await api<TaskWorkspaceFileChanges>("/task-workspaces/" + encodeURIComponent(operationId) + "/changes?limit=100");
      if (token === taskFileChangesGeneration.current) setTaskFileChanges(result);
    } catch (e) {
      if (token === taskFileChangesGeneration.current) setTaskFileError(e instanceof Error ? e.message : String(e));
    }
  }
  async function createTaskFile(operationId: string) {
    const path = newTaskFilePath.trim();
    if (!path || taskFileSaving) return;
    if (!window.confirm("Create " + path + " inside this isolated task workspace?")) return;
    setTaskFileSaving(true); setTaskFileError("");
    try {
      const result = await api<TaskWorkspaceFileChange>(
        "/task-workspaces/" + encodeURIComponent(operationId) + "/file",
        json({path,content:"",expected_sha256:null,approved:true}),
      );
      setNewTaskFilePath("");
      await loadTaskFiles(operationId, taskFilePath);
      await openTaskFile(operationId, result.path);
      await loadTaskChanges(operationId);
    } catch (e) { setTaskFileError(e instanceof Error ? e.message : String(e)); }
    finally { setTaskFileSaving(false); }
  }
  async function saveTaskFile(operationId: string) {
    if (!taskFileContent || taskFileContent.operation_id !== operationId || taskFileSaving) return;
    if (!window.confirm("Apply the edited contents of " + taskFileContent.path + " to this isolated task workspace? This changes only the task worktree.")) return;
    setTaskFileSaving(true); setTaskFileError("");
    try {
      const result = await api<TaskWorkspaceFileChange>(
        "/task-workspaces/" + encodeURIComponent(operationId) + "/file",
        json({path:taskFileContent.path,content:taskFileDraft,expected_sha256:taskFileContent.sha256,approved:true}),
      );
      await loadTaskFiles(operationId, taskFilePath);
      await openTaskFile(operationId, result.path);
      await loadTaskChanges(operationId);
      await loadTaskReview(operationId);
    } catch (e) { setTaskFileError(e instanceof Error ? e.message : String(e)); }
    finally { setTaskFileSaving(false); }
  }
  async function loadTaskReview(operationId: string) {
    const token = ++taskReviewGeneration.current;
    const requestedRunId = selectedRunRef.current;
    setReviewBusy(true); setTaskReviewError(""); setTaskReview(null);
    try {
      const result = await api<TaskWorkspaceReview>("/task-workspaces/" + encodeURIComponent(operationId) + "/review");
      if (token !== taskReviewGeneration.current || selectedRunRef.current !== requestedRunId) return;
      setTaskReview(result);
    } catch (e) {
      if (token !== taskReviewGeneration.current || selectedRunRef.current !== requestedRunId) return;
      setTaskReviewError(e instanceof Error ? e.message : String(e));
    } finally {
      if (token === taskReviewGeneration.current) setReviewBusy(false);
    }
  }
  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!request.trim() || busy || !workspaceId) return;
    setBusy(true); setError("");
    try {
      const result = await api<{run_id: string;task_workspace_operation_id?:string}>("/agents", json({ request: request.trim(), workspace_id: workspaceId, isolate_workspace: isolateWorkspace }));
      setRequest(""); taskReviewGeneration.current += 1; setTaskReview(null); setTaskReviewError(""); setReviewBusy(false); setSelected(result.run_id); await refresh(); await refreshDetail(result.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function proposePlan() {
    planDetailGeneration.current += 1;
    if (!request.trim() || planning || busy || !workspaceId) return;
    setPlanning(true); setError(""); setPlan(null);
    try {
      const result = await api<AgentPlan>("/agents/plans", json({request:request.trim(),workspace_id:workspaceId}));
      setPlan(result); await refreshPlans();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setPlanning(false); }
  }
  async function approveAndExecutePlan() {
    if (!plan || !["proposed","approved"].includes(plan.status) || busy) return;
    if (!window.confirm("Approve this plan and start sequential execution? File writes and commands will still require separate approval.")) return;
    setBusy(true); setError("");
    try {
      if (plan.status === "proposed") await api("/agents/plans/" + encodeURIComponent(plan.id) + "/approve" + scopeSuffix(), json({}));
      const executeScope = scopeSuffix();
      const isolateQuery = isolateWorkspace ? (executeScope ? "&" : "?") + "isolate_workspace=true" : "";
      const result = await api<{plan_id:string;run_id:string}>("/agents/plans/" + encodeURIComponent(plan.id) + "/execute" + executeScope + isolateQuery, json({}));
      taskReviewGeneration.current += 1; setTaskReview(null); setTaskReviewError(""); setReviewBusy(false);
      setSelected(result.run_id); await loadPlan(plan.id); await refresh(); await refreshPlans(); await refreshDetail(result.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); await loadPlan(plan.id); }
    finally { setBusy(false); }
  }
  async function cancelRun() {
    if (!detail || !window.confirm("Request cancellation? Evo will stop at the next safe boundary. A provider call or tool action already in progress may need to finish or time out first.")) return;
    try { await api("/agents/" + encodeURIComponent(detail.id) + "/cancel" + scopeSuffix(), json({})); await refresh(); await refreshDetail(detail.id); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function decide(approved: boolean) {
    if (!detail) return;
    try {
      await api("/agents/" + encodeURIComponent(detail.id) + "/approval" + scopeSuffix(), json({ approved }));
      await refreshDetail(detail.id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  useEffect(() => {
    setWorkspaceId(scopeWorkspaceId || "");
  }, [scopeWorkspaceId]);
  useEffect(() => {
    runsGeneration.current += 1;
    plansGeneration.current += 1;
    runDetailGeneration.current += 1;
    planDetailGeneration.current += 1;
    setRuns([]);
    setPlans([]);
    setSelected(null);
    setDetail(null);
    taskReviewGeneration.current += 1;
    setTaskReview(null);
    setTaskReviewError("");
    setReviewBusy(false);
    setTaskOperations([]);
    setTaskOperationDetail(null);
    setTaskOperationError("");
    setTaskFiles(null); setTaskFileContent(null); setTaskFileDraft(""); setNewTaskFilePath(""); setTaskFilePath(""); setTaskFileError(""); setTaskFileSaving(false);
    setPlan(null);
    setError("");
    void refresh();
    void refreshPlans();
  }, [projectId, scopeWorkspaceId, refresh, refreshPlans]);
  const executableWorkspaces = registryWorkspaces.filter(workspace => {
    if (projectId && workspace.project_id !== projectId) return false;
    if (scopeWorkspaceId && workspace.workspace_id !== scopeWorkspaceId) return false;
    if (workspace.status !== "active" || !workspace.checkout_id) return false;
    const project = projects.find(item => item.project_id === workspace.project_id);
    if (!project || project.status !== "active") return false;
    const configuration = configurations.find(item => item.configuration_id === workspace.configuration_id);
    if (!configuration || configuration.status !== "active") return false;
    const checkout = checkouts[workspace.checkout_id];
    if (!checkout || checkout.availability_status !== "available") return false;
    return true;
  });
  useEffect(() => {
    if (workspaceId && !executableWorkspaces.some(item => item.workspace_id === workspaceId)) setWorkspaceId("");
  }, [workspaceId, executableWorkspaces]);
  return <div className="workspace-page">
    <DemoDataBanner/>
    <div className="workspace-heading"><div><div className="eyebrow">APPROVAL-GATED EXECUTION</div><h1>Agents</h1><p>Run Evo's existing coding agent, inspect its tool history, and approve every file write or command.</p></div><span className="workspace-count">{runs.length} runs</span></div>
    {error && <div className="workspace-error" role="alert">{error}</div>}
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Isolated task workspaces</h2><p>Provisioning and recovery records are retained for inspection. Evo never removes these worktrees automatically.</p></div><button className="quiet-button" onClick={()=>void refresh()}>Refresh</button></div>
      {taskOperationError&&<div className="workspace-error" role="alert">{taskOperationError}</div>}
      <div className="record-list">{taskOperations.map(item=><article className="record-card" key={item.operation_id}>
        <div className="record-top"><span className={"run-status "+item.status}>{item.status.replaceAll("_"," ")}</span><span>{item.task_id}</span><small>{new Date(item.updated_at).toLocaleString()}</small></div>
        <small>Source revision {item.source_revision.slice(0,12)} · {item.error_recorded?"Error recorded":"No error recorded"}</small>
        <div className="inline-actions"><button className="quiet-button" disabled={taskOperationBusy} onClick={()=>void inspectTaskOperation(item.operation_id)}>Inspect lifecycle</button></div>
        {taskOperationDetail?.operation_id===item.operation_id&&<div className="policy-note">
          <div>Destination: {taskOperationDetail.destination_path}</div>
          <div>Filesystem: {taskOperationDetail.filesystem.path_is_symlink?"symlink":taskOperationDetail.filesystem.path_is_directory?"directory":taskOperationDetail.filesystem.path_exists?"present, not a directory":"missing"}</div>
          {taskOperationDetail.recovery_guidance&&<p>{taskOperationDetail.recovery_guidance}</p>}
        </div>}
      </article>)}{taskOperations.length===0&&<div className="empty-state">No isolated task workspace operations recorded.</div>}</div>
    </section>
    <section className="workspace-panel">
      <h2>Start a coding task</h2>
      <form className="agent-launch" onSubmit={start}>
        <textarea value={request} onChange={e => setRequest(e.target.value)} rows={3} placeholder="Describe the task. Evo will inspect the workspace first, then request approval before writes or commands…"/>
        <div className="agent-launch-footer">
          <select value={workspaceId} onChange={e => {
            const nextId = e.target.value;
            setWorkspaceId(nextId);
            const selectedWorkspace = executableWorkspaces.find(item => item.workspace_id === nextId);
            if (selectedWorkspace) onScopeChange(selectedWorkspace.project_id, selectedWorkspace.workspace_id);
            else onScopeChange(projectId, null);
          }} disabled={executableWorkspaces.length === 0}>
            <option value="">Select an executable workspace…</option>
            {executableWorkspaces.map(item => (
              <option key={item.workspace_id} value={item.workspace_id}>
                {item.name} — {projects.find(project => project.project_id === item.project_id)?.name || item.project_id} — {checkouts[item.checkout_id || ""]?.canonical_path || item.checkout_id}
              </option>
            ))}
          </select>
          <button disabled={busy || !request.trim() || !workspaceId}>{busy ? "Starting…" : "Start agent"}</button>
        </div>
        <label className="policy-note" style={{display:"flex",alignItems:"center",gap:8,marginTop:10}}><input type="checkbox" checked={isolateWorkspace} onChange={event=>setIsolateWorkspace(event.target.checked)}/> Use a separate, revision-pinned task workspace for direct runs and plan execution (requires a clean source checkout)</label>
        {executableWorkspaces.length === 0 && <p className="policy-note">No executable registered workspaces are available. Register a project, checkout, configuration, and workspace first.</p>}
      </form>
      <div className="policy-note">Read-only inspection runs automatically. File writes and allowlisted commands require explicit approval. Execution is bounded. Cancellation is cooperative: an active model request or tool action may finish or time out before Evo reaches a safe stop point. Interrupted tasks are recorded, not automatically resumed.</div>
    </section>
    <section className="workspace-panel">
      <div className="panel-toolbar"><div><h2>Plan first</h2><p>Generate a structured proposal, inspect each step, then explicitly approve execution.</p></div><span className="run-status">HUMAN APPROVAL</span></div>
      <div className="inline-actions"><button className="quiet-button" type="button" disabled={planning||busy||!request.trim()} onClick={()=>void proposePlan()}>{planning?"Planning…":"Generate plan for this request"}</button></div>
      <div className="policy-note">The model's plan is untrusted until reviewed. Approval authorizes the listed sequence only; each file write and command still requires its existing per-action approval. Steps run sequentially. Failed steps stop the plan; interrupted plans are not replayed.</div>
      {plans.length>0&&<div className="run-list">{plans.map(item=><button key={item.id} className={"run-row "+(plan?.id===item.id?"selected":"")} onClick={()=>void loadPlan(item.id)}><span className={"run-status "+item.status}>{item.status}</span><strong>{item.title}</strong><small>{new Date(item.created_at).toLocaleString()}</small></button>)}</div>}
      {plan&&<div className="run-summary"><div className="record-top"><strong>{plan.title}</strong><span className={"run-status "+plan.status}>{plan.status}</span></div><p>{plan.summary}</p>
        <div className="event-list">{plan.steps.map(step=><article className="event-card" key={step.id}><div className="event-head"><strong>{step.position+1}. {step.title}</strong><span className={"run-status "+step.status}>{step.status}</span></div><p>{step.description}</p><small>Expected: {step.expected_outcome}</small><small>Verify: {step.verification}</small><small>Verification status: {step.verification_status||"unknown"}</small>{(step.verification_commands||[]).length>0&&<small>Verification commands: {(step.verification_commands||[]).map((command:any)=>command.join(" ")).join(" | ")}</small>}{(step.verification_checks||[]).length>0&&<pre>{(step.verification_checks||[]).map((check:any)=>`$ ${Array.isArray(check.command)?check.command.join(" "):""}\nexit ${check.exit_code}\n${check.stdout||""}${check.stderr?`\n${check.stderr}`:""}`).join("\n---\n")}</pre>}{step.result&&<pre>{step.result}</pre>}</article>)}</div>
        <h3>Plan event history</h3><div className="event-list">{plan.events.map(event=><article className="event-card" key={event.id}><div className="event-head"><strong>{event.type.replaceAll("_"," ")}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div>{Object.keys(event.payload).length>0&&<pre>{JSON.stringify(event.payload,null,2)}</pre>}</article>)}</div>
        {plan.error&&<p className="failed-note">{plan.error}</p>}
        {["proposed","approved"].includes(plan.status)&&<button disabled={busy||planning} onClick={()=>void approveAndExecutePlan()}>{plan.status==="proposed"?"Approve plan and execute":"Execute approved plan"}</button>}
        {plan.run_id&&<button className="quiet-button" onClick={()=>{taskReviewGeneration.current += 1;setTaskReview(null);setTaskReviewError("");setSelected(plan.run_id!);void refreshDetail(plan.run_id!);}}>Open execution run</button>}
      </div>}
    </section>
    <div className="agent-layout">
      <section className="workspace-panel run-list-panel"><div className="panel-toolbar"><div><h2>Run history</h2><p>Most recent first</p></div><button className="quiet-button" onClick={() => void refresh()}>Refresh</button></div>
        <div className="run-list">{runs.map(run => <button key={run.id} className={"run-row " + (selected === run.id ? "selected" : "")} onClick={() => { taskReviewGeneration.current += 1; setTaskReview(null); setTaskReviewError(""); setReviewBusy(false); setSelected(run.id); void refreshDetail(run.id); }}><span className={"run-status " + run.status}>{run.status}</span><strong>{String(run.metadata.request || run.summary || "Coding run").slice(0, 90)} {run.metadata.demo_seed&&<span className="demo-tag">SAMPLE</span>}</strong><small>{new Date(run.started_at).toLocaleString()}</small></button>)}{runs.length === 0 && <div className="empty-state">No agent runs yet.</div>}</div>
      </section>
      <section className="workspace-panel run-detail-panel"><div className="panel-toolbar"><div><h2>Execution details</h2><p>{detail ? detail.id : "Select a run to inspect its activity"}</p></div>{detail && <div className="inline-actions"><span className={"run-status " + (detail.background_task?.status || detail.status)}>{detail.background_task?.status || detail.status}</span>{detail.background_task && ["queued","running","awaiting_approval","cancel_requested"].includes(detail.background_task.status) && <button className="quiet-button danger" onClick={()=>void cancelRun()}>Request cancellation</button>}</div>}</div>
        {detail ? <><div className="run-summary"><strong>{detail.metadata.request || detail.summary || "Coding task"}</strong><small>Workspace: {detail.metadata.workspace || "—"} · Model: {detail.metadata.model || "—"}</small>{detail.summary && <p>{detail.summary}</p>}</div>
          {detail.metadata.task_workspace_operation_id && <section className="workspace-panel"><div className="panel-toolbar"><div><h3>Task workspace review</h3><p>Read-only snapshot of changes in this task’s isolated worktree.</p></div><button className="quiet-button" disabled={reviewBusy} onClick={()=>void loadTaskReview(String(detail.metadata.task_workspace_operation_id))}>{reviewBusy?"Reviewing…":taskReview?.operation_id===String(detail.metadata.task_workspace_operation_id)?"Refresh review":"Review changes"}</button></div>{taskReviewError&&<p className="workspace-error" role="alert">{taskReviewError}</p>}{taskReview?.operation_id===String(detail.metadata.task_workspace_operation_id)&&<><div className="policy-note">Pinned source {taskReview.source_revision.slice(0,12)} · Current HEAD {taskReview.current_head.slice(0,12)} · {taskReview.changed_file_count} changed files · {taskReview.patch_bytes.toLocaleString()} / {taskReview.max_bytes.toLocaleString()} patch bytes</div><div className="inline-actions"><span className={"run-status "+(taskReview.stable?"completed":"interrupted")}>{taskReview.stable?"Stable snapshot":taskReview.truncated?"Incomplete snapshot":"Snapshot changed during review"}</span>{taskReview.truncated&&<span className="run-status interrupted">Truncated: {taskReview.truncation_reason||"output limit"}</span>}</div>{taskReview.changed_files_omitted>0&&<p className="policy-note">{taskReview.changed_files_omitted} changed file entries omitted by the {taskReview.max_files}-file metadata limit.</p>}{taskReview.excluded_files.length>0&&<p className="policy-note">Excluded files: {taskReview.excluded_files.join(", ")}{taskReview.excluded_files_omitted>0?` · ${taskReview.excluded_files_omitted} more omitted`:""}</p>}{taskReview.unreadable_files.length>0&&<p className="policy-note">Unreadable files: {taskReview.unreadable_files.map(file=>`${file.path} (${file.reason})`).join(", ")}{taskReview.unreadable_files_omitted>0?` · ${taskReview.unreadable_files_omitted} more omitted`:""}</p>}<div className="event-list">{taskReview.changed_files.map(file=><div className="event-card" key={file.path}><strong>{file.status} · {file.path}</strong></div>)}{taskReview.changed_files.length===0&&<div className="empty-state">No reviewable changed files were found.</div>}</div><section className="workspace-panel"><div className="panel-toolbar"><div><h3>Execution and verification evidence</h3><p>Runs are included only when their task workspace, project, and pinned source revision match this review.</p></div></div>{(taskReview.execution_evidence||[]).length===0?<div className="empty-state">No matching agent execution evidence is recorded for this task workspace.</div>:(taskReview.execution_evidence||[]).map(run=><div className="event-card" key={run.run_id}><strong>Run {run.run_id.slice(0,12)} · {run.status}</strong><p>Verification: {run.verification_state}{run.plan_id?` · Plan ${run.plan_id.slice(0,12)} (${run.plan_status||"unknown"})`:""}</p>{run.verification_summary&&<p>{run.verification_summary.passed} passed · {run.verification_summary.failed} failed · {run.verification_summary.not_run} not run · {run.verification_summary.not_configured} not configured</p>}{run.steps.map(step=><div key={step.step_id}><strong>{step.position+1}. {step.title} · {step.verification_status}</strong>{step.verification_checks.map(check=><div className="policy-note" key={check.id}><code>{check.command.join(" ")}</code> · {check.status} · exit {check.exit_code===null?"—":check.exit_code}{check.execution_id?` · execution ${check.execution_id.slice(0,12)}`:""}<details><summary>Command output</summary><pre>{[check.stdout,check.stderr].filter(Boolean).join("\n\n")||"No output recorded."}</pre></details></div>)}</div>)}</div>)}</section><details><summary>View patch ({taskReview.patch_bytes.toLocaleString()} bytes)</summary><pre>{taskReview.patch||"No patch content."}</pre></details></>}
          {detail.metadata.task_workspace_operation_id&&<section className="workspace-panel">
            <div className="panel-toolbar"><div><h3>Browse task files</h3><p>Read-only text inspection. Each response includes the pinned source revision.</p></div><button className="quiet-button" disabled={taskFileBusy} onClick={()=>{void loadTaskFiles(String(detail.metadata.task_workspace_operation_id));void loadTaskChanges(String(detail.metadata.task_workspace_operation_id));}}>{taskFileBusy?"Loading…":"Open file browser"}</button></div>
            {taskFileError&&<p className="workspace-error" role="alert">{taskFileError}</p>}
            {taskFiles?.operation_id===String(detail.metadata.task_workspace_operation_id)&&<>
              <div className="inline-actions"><span className="policy-note">/{taskFilePath}</span>{taskFilePath&&<button className="quiet-button" disabled={taskFileBusy} onClick={()=>void loadTaskFiles(String(detail.metadata.task_workspace_operation_id),taskFilePath.split("/").slice(0,-1).join("/"))}>Parent directory</button>}<small>{taskFiles.total} entries{taskFiles.truncated?" · list truncated":""}</small></div>
              <div className="inline-actions"><input aria-label="New relative file path" placeholder="New file path (for example src/module.py)" value={newTaskFilePath} onChange={event=>setNewTaskFilePath(event.target.value)} /><button className="quiet-button" disabled={taskFileSaving||!newTaskFilePath.trim()} onClick={()=>void createTaskFile(String(detail.metadata.task_workspace_operation_id))}>Create file</button></div>
              <div className="event-list">{taskFiles.items.map(item=><div className="event-card" key={item.path}><div className="event-head"><strong>{item.kind==="directory"?"Folder":item.kind==="file"?"File":item.kind==="symlink"?"Symlink":"Other"} · {item.name}</strong><small>{item.size_bytes===null?"":item.size_bytes.toLocaleString()+" bytes"}</small></div>{(item.kind==="directory"||item.kind==="file")&&<button className="quiet-button" disabled={taskFileBusy} onClick={()=>item.kind==="directory"?void loadTaskFiles(String(detail.metadata.task_workspace_operation_id),item.path):void openTaskFile(String(detail.metadata.task_workspace_operation_id),item.path)}>{item.kind==="directory"?"Open folder":"Read text file"}</button>}</div>)}{taskFiles.items.length===0&&<div className="empty-state">This directory is empty.</div>}</div>
            </>}
              <section className="workspace-panel">
                <div className="panel-toolbar"><div><h4>File change history</h4><p>Recorded write attempts and their reconciled outcomes in this isolated task workspace.</p></div><button className="quiet-button" disabled={taskFileSaving} onClick={()=>void loadTaskChanges(String(detail.metadata.task_workspace_operation_id))}>Refresh history</button></div>
                {taskFileChanges?.operation_id===String(detail.metadata.task_workspace_operation_id)&&<>
                  <small>{taskFileChanges.total} recorded changes{taskFileChanges.truncated?" · showing latest "+taskFileChanges.limit:""}</small>
                  <div className="event-list">{taskFileChanges.items.map(change=><article className="event-card" key={change.change_id}>
                    <div className="event-head"><strong>{change.path}</strong><small>{new Date(change.created_at).toLocaleString()}</small></div>
                    <div className="inline-actions"><small>{change.before_sha256?"Updated existing file":"Created new file"} · {change.size_bytes.toLocaleString()} bytes</small><span className={"run-status "+(change.status==="applied"?"completed":change.status==="failed"?"failed":"interrupted")}>{change.status}</span></div>
                    <small>After SHA-256 {change.after_sha256}</small>
                    {change.error_code&&<small>Recovery note: {change.error_code.replaceAll("_"," ")}</small>}
                  </article>)}{taskFileChanges.items.length===0&&<div className="empty-state">No file changes recorded yet.</div>}</div>
                </>}
              </section>
            {taskFileContent?.operation_id===String(detail.metadata.task_workspace_operation_id)&&<div className="event-card"><div className="event-head"><strong>{taskFileContent.path}</strong><small>{taskFileContent.size_bytes.toLocaleString()} bytes · SHA-256 {taskFileContent.sha256.slice(0,12)}</small></div><textarea aria-label={"Edit "+taskFileContent.path} value={taskFileDraft} onChange={event=>setTaskFileDraft(event.target.value)} rows={16} spellCheck={false}/><div className="inline-actions"><span className="policy-note">{taskFileDraft===taskFileContent.content?"No unsaved edits":"Unsaved edits · compare-and-swap protected"}</span><button className="quiet-button" disabled={taskFileSaving||taskFileDraft===taskFileContent.content} onClick={()=>void saveTaskFile(String(detail.metadata.task_workspace_operation_id))}>{taskFileSaving?"Applying…":"Apply edited file"}</button></div></div>}
          </section>}
          </section>}
          {detail.pending_approval && <div className="approval-card"><div className="approval-title">Approval required · {detail.pending_approval.tool_name}</div><pre>{JSON.stringify(detail.pending_approval.arguments, null, 2)}</pre><div className="inline-actions"><button className="quiet-button danger" onClick={() => void decide(false)}>Deny</button><button onClick={() => void decide(true)}>Approve action</button></div></div>}
          <section className="workspace-panel"><h3>Task lifecycle</h3><div className="event-list">{(detail.background_events || []).map(event => <article className="event-card" key={"task-" + event.id}><div className="event-head"><strong>{event.type.replaceAll("_", " ")}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div><pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)}{!(detail.background_events || []).length && <div className="empty-state">No lifecycle events recorded.</div>}</div></section>
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
type WorkloadExecution = {id:string;job_id:string;argv:string[];workspace:string;status:string;timeout_seconds:number;pid:number|null;started_at:string|null;finished_at:string|null;returncode:number|null;elapsed_seconds:number|null;stdout:string;stderr:string;error:string};
function WorkloadSchedulerPanel() {
  const [data,setData]=useState<SchedulerResponse|null>(null);
  const [name,setName]=useState("");
  const [kind,setKind]=useState("benchmark");
  const [priority,setPriority]=useState("10");
  const [gpuHeavy,setGpuHeavy]=useState("auto");
  const [vram,setVram]=useState("");
  const [ram,setRam]=useState("");
  const [commandArgs,setCommandArgs]=useState("");
  const [timeout,setTimeout]=useState("300");
  const [executions,setExecutions]=useState<WorkloadExecution[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{try{const [queue,history]=await Promise.all([api<SchedulerResponse>("/hardware/scheduler"),api<WorkloadExecution[]>("/hardware/executions?limit=30")]);setData(queue);setExecutions(history);setError("");}catch(e){setError(e instanceof Error?e.message:String(e));}},[]);
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
  async function execute(job:ScheduledJob) {
    if(busy)return;
    const argv=commandArgs.split("\n").map(part=>part.trim()).filter(Boolean);
    if(!argv.length){setError("Enter an allowlisted command, one argument per line.");return;}
    if(!window.confirm("Execute this command inside Evo's configured workspace?\n\n"+JSON.stringify(argv)+"\n\nOnly configured command prefixes are accepted."))return;
    setBusy(true);setError("");
    try{await api("/hardware/scheduler/jobs/"+job.id+"/execute",json({argv,timeout_seconds:Number(timeout)}));await refresh();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const jobs=data?.jobs||[];
  return <section className="workspace-panel">
    <div className="panel-toolbar"><div><h2>Workload scheduler</h2><p>Persistent queue, resource reservations and explicit workload lifecycle.</p></div><span className="run-status">SUPERVISED EXECUTION</span></div>
    <p className="policy-copy">Dispatch reserves capacity using live telemetry. A reserved job can be started externally, or you can explicitly launch an allowlisted command that Evo supervises. Unstarted reservations expire after five minutes.</p>
    {error&&<div className="workspace-error" role="alert">{error}</div>}
    <form className="scheduler-form" onSubmit={create}>
      <label>Workload name<input value={name} onChange={e=>setName(e.target.value)} maxLength={120} required placeholder="e.g. Memory retrieval benchmark"/></label>
      <label>Type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="benchmark">Benchmark</option><option value="research">Research</option><option value="agent">Agent</option><option value="maintenance">Maintenance</option><option value="cpu">CPU-only</option><option value="background">General background</option></select></label>
      <label>Priority (1–100)<input type="number" min="1" max="100" value={priority} onChange={e=>setPriority(e.target.value)}/></label>
      <label>GPU use<select value={gpuHeavy} onChange={e=>setGpuHeavy(e.target.value)}><option value="auto">Assume GPU-heavy</option><option value="true">GPU-heavy</option><option value="false">CPU-only (declared)</option></select></label>
      <label>Estimated VRAM (MiB)<input type="number" min="0" max="1000000" value={vram} onChange={e=>setVram(e.target.value)} placeholder="Required for GPU jobs"/></label>
      <label>Estimated RAM (MiB)<input type="number" min="0" max="1000000" value={ram} onChange={e=>setRam(e.target.value)} placeholder="Required for background jobs"/></label>
      <label className="scheduler-command">Execution command (one argv item per line)<textarea value={commandArgs} onChange={e=>setCommandArgs(e.target.value)} rows={3} placeholder={"python\n-m\nunittest\ndiscover\n-s\ntests"}/></label>
      <label>Execution timeout (seconds)<input type="number" min="1" max="900" value={timeout} onChange={e=>setTimeout(e.target.value)}/></label>
      <div className="inline-actions"><button className="quiet-button" type="submit" disabled={busy||!name.trim()}>{busy?"Working…":"Add to queue"}</button><button className="quiet-button" type="button" disabled={busy} onClick={()=>void action("/hardware/scheduler/dispatch?limit=5")}>Evaluate queue and reserve</button><button className="quiet-button" type="button" disabled={busy} onClick={()=>void refresh()}>Refresh</button></div>
    </form>
    <p className="policy-copy">Execution uses argv exactly as entered—never a shell string. It is accepted only when it matches a command prefix in workspace.allowed_commands. Launching requires a separate confirmation. Evo runs only its own child process group, captures bounded output, and enforces the timeout. This is not a sandbox: commands run with Evo's user permissions, so execute only commands you trust. It does not attach to your model server.</p>
    <div className="scheduler-counts">{["queued","reserved","running","completed","failed","cancelled"].map(key=><span key={key}><b>{data?.counts[key]||0}</b><small>{key}</small></span>)}</div>
    <div className="scheduler-jobs">{jobs.map(job=><article className="scheduler-job" key={job.id}>
      <div className="record-top"><span className={"run-status "+job.status}>{job.status}</span><span>{job.kind}</span><span>Priority {job.priority}</span></div>
      <strong>{job.name}</strong>
      <small>VRAM {job.estimated_vram_mib==null?"unknown":mib(job.estimated_vram_mib)} · RAM {job.estimated_ram_mib==null?"unknown":mib(job.estimated_ram_mib)} · GPU {job.gpu_heavy===false?"CPU-only":job.gpu_heavy===true?"yes":"assumed"}</small>
      {job.last_decision?.reasons?.map((reason,index)=><small key={index}>{reason}</small>)}
      {job.status==="reserved"&&<small>Reservation expires: {job.lease_expires_at?new Date(job.lease_expires_at).toLocaleTimeString():"—"}</small>}
      {job.status==="running"&&<small>{executions.some(item=>item.job_id===job.id)?"Evo-managed command is supervised; completion is recorded automatically.":"External workload is user-confirmed; Evo does not monitor or control it."}</small>}
      <div className="inline-actions">
        {job.status==="reserved"&&<><button className="quiet-button" disabled={busy} onClick={()=>void execute(job)}>Execute allowlisted command</button><button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/start")}>Confirm external start</button></>}
        {job.status==="running"&&!executions.some(item=>item.job_id===job.id)&&<><button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/finish",{outcome:"completed"})}>Mark external job completed</button><button className="quiet-button" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/finish",{outcome:"failed",note:"Marked failed by user"})}>Mark external job failed</button></>}
        {(job.status==="queued"||job.status==="reserved")&&<button className="quiet-button danger" disabled={busy} onClick={()=>void action("/hardware/scheduler/jobs/"+job.id+"/cancel")}>Cancel queued job</button>}
      </div>
    </article>)}
    {!jobs.length&&<div className="empty-state">No scheduled workloads yet. Add a workload above to begin building a persistent queue.</div>}</div>
    <div className="panel-toolbar execution-history-head"><div><h3>Managed execution history</h3><p>Commands started by Evo, including captured output and restart recovery.</p></div><span className="workspace-count">{executions.length} records</span></div>
    <div className="execution-list">{executions.map(item=><article className="execution-card" key={item.id}>
      <div className="record-top"><span className={"run-status "+item.status}>{item.status}</span><span>Job {item.job_id.slice(0,8)}</span><span>{item.elapsed_seconds==null?"—":item.elapsed_seconds+"s"}</span>{item.returncode!==null&&<span>Exit {item.returncode}</span>}</div>
      <code>{item.argv.join(" ")}</code>
      <small>Workspace: {item.workspace} · PID: {item.pid??"—"} · Timeout: {item.timeout_seconds}s</small>
      {item.status==="launch_uncertain"&&<p className="failed-note">Launch outcome unknown: Evo restarted after requesting this subprocess but before recording its PID. Evo did not terminate or retry it. Inspect the process manually before retrying.</p>}
      {item.error&&<p className="failed-note">{item.error}</p>}
      {item.stdout&&<details><summary>Standard output</summary><pre>{item.stdout}</pre></details>}
      {item.stderr&&<details><summary>Standard error</summary><pre>{item.stderr}</pre></details>}
    </article>)}{!executions.length&&<div className="empty-state">No Evo-managed commands have been executed.</div>}</div>
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
