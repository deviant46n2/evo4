import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

const API = "http://127.0.0.1:8765/api/v1";

type Project = {
  project_id: string;
  name: string;
  description: string;
  git_remote: string | null;
  default_ref: string | null;
  project_type: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  version: number;
};

type Checkout = {
  checkout_id: string;
  project_id: string;
  canonical_path: string;
  branch_or_ref: string | null;
  last_known_commit: string | null;
  availability_status: "available" | "missing" | "unavailable" | string;
  created_at: string;
  updated_at: string;
  version: number;
};

type ProjectList = { items: Project[]; total: number };
type CheckoutList = { items: Checkout[]; total: number };

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API + path, init);
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Preserve the HTTP status text for non-JSON responses.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return `Conflict: ${error.message}. The server state may have changed. Reload before retrying.`;
  }
  return error instanceof Error ? error.message : String(error);
}

function date(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function nullable(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function ProjectsWorkspace({ onStartTask }: { onStartTask?: (projectId: string) => void } = {}) {
  const [filter, setFilter] = useState<"active" | "archived">("active");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Project | null>(null);
  const [checkouts, setCheckouts] = useState<Checkout[]>([]);
  const [selectedCheckout, setSelectedCheckout] = useState<Checkout | null>(null);

  const [projectMode, setProjectMode] = useState<"view" | "create" | "edit">("view");
  const [provisionMode, setProvisionMode] = useState(false);
  const [provisionName, setProvisionName] = useState("");
  const [provisionDescription, setProvisionDescription] = useState("");
  const [parentPath, setParentPath] = useState("");
  const [provisionConfigId, setProvisionConfigId] = useState("");
  const [provisionRevisionId, setProvisionRevisionId] = useState("");
  const [provisionConfigurations, setProvisionConfigurations] = useState<Array<{configuration_id:string;name:string;status:string;current_revision_id:string}>>([]);
  const [provisionRevisions, setProvisionRevisions] = useState<Array<{revision_id:string;revision_number:number;change_summary:string}>>([]);
  const [provisioning, setProvisioning] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [gitRemote, setGitRemote] = useState("");
  const [defaultRef, setDefaultRef] = useState("");
  const [projectType, setProjectType] = useState("");

  const [checkoutMode, setCheckoutMode] = useState<"view" | "register" | "edit">("view");
  const [checkoutPath, setCheckoutPath] = useState("");
  const [checkoutBranch, setCheckoutBranch] = useState("");
  const [checkoutCommit, setCheckoutCommit] = useState("");

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);

  const fetchProjects = useCallback(async (status: "active" | "archived") => {
    const result = await api<ProjectList>(`/projects?status=${status}`);
    return result.items;
  }, []);

  const loadDetail = useCallback(async (id: string, token: number) => {
    const [project, checkoutResult] = await Promise.all([
      api<Project>(`/projects/${encodeURIComponent(id)}`),
      api<CheckoutList>(`/projects/${encodeURIComponent(id)}/checkouts`),
    ]);
    if (token !== generation.current) return null;
    setSelected(project);
    setCheckouts(checkoutResult.items);
    return { project, checkouts: checkoutResult.items };
  }, []);

  const refresh = useCallback(async () => {
    if (loading) return;
    const token = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const items = await fetchProjects(filter);
      if (token !== generation.current) return;
      setProjects(items);
      if (selectedId && items.some(item => item.project_id === selectedId)) {
        await loadDetail(selectedId, token);
      } else {
        setSelectedId(null);
        setSelected(null);
        setCheckouts([]);
        setSelectedCheckout(null);
        setProjectMode("view");
        setCheckoutMode("view");
      }
    } catch (e) {
      if (token === generation.current) setError(errorText(e));
    } finally {
      if (token === generation.current) setLoading(false);
    }
  }, [filter, selectedId, loading, fetchProjects, loadDetail]);

  useEffect(() => {
    const token = ++generation.current;
    let alive = true;
    setLoading(true);
    setError("");
    fetchProjects(filter)
      .then(items => {
        if (!alive || token !== generation.current) return;
        setProjects(items);
        if (selectedId && items.some(item => item.project_id === selectedId)) {
          return loadDetail(selectedId, token);
        }
        setSelectedId(null);
        setSelected(null);
        setCheckouts([]);
        setSelectedCheckout(null);
        setProjectMode("view");
        setCheckoutMode("view");
        return undefined;
      })
      .catch(e => {
        if (alive && token === generation.current) setError(errorText(e));
      })
      .finally(() => {
        if (alive && token === generation.current) setLoading(false);
      });
    return () => {
      alive = false;
      generation.current += 1;
    };
  // Filter changes reload the list; selection is reconciled by ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function selectProject(id: string) {
    const token = ++generation.current;
    setError("");
    setNotice("");
    setSelectedCheckout(null);
    setProjectMode("view");
    setCheckoutMode("view");
    setSelectedId(id);
    setLoading(true);
    try {
      await loadDetail(id, token);
    } catch (e) {
      if (token === generation.current) {
        setError(errorText(e));
        setSelectedId(null);
        setSelected(null);
        setCheckouts([]);
      }
    } finally {
      if (token === generation.current) setLoading(false);
    }
  }

  function beginCreateProject() {
    generation.current += 1;
    setSelectedId(null);
    setSelected(null);
    setCheckouts([]);
    setSelectedCheckout(null);
    setProjectName("");
    setProjectDescription("");
    setGitRemote("");
    setDefaultRef("");
    setProjectType("");
    setProjectMode("create");
    setCheckoutMode("view");
    setError("");
    setNotice("");
  }

  function beginEditProject() {
    if (!selected) return;
    setProjectName(selected.name);
    setProjectDescription(selected.description);
    setGitRemote(selected.git_remote || "");
    setDefaultRef(selected.default_ref || "");
    setProjectType(selected.project_type || "");
    setProjectMode("edit");
    setError("");
    setNotice("");
  }

  useEffect(() => {
    if (!provisionMode) return;
    let alive = true;
    api<{items: Array<{configuration_id:string;name:string;status:string;current_revision_id:string}>}>("/configurations?status=active")
      .then(result => { if (alive) setProvisionConfigurations(result.items); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [provisionMode]);

  useEffect(() => {
    if (!provisionMode || !provisionConfigId) {
      setProvisionRevisions([]);
      setProvisionRevisionId("");
      return;
    }
    let alive = true;
    api<{items: Array<{revision_id:string;revision_number:number;change_summary:string}>}>(`/configurations/${encodeURIComponent(provisionConfigId)}/revisions`)
      .then(result => {
        if (!alive) return;
        setProvisionRevisions(result.items);
        const configuration = provisionConfigurations.find(item => item.configuration_id === provisionConfigId);
        const current = configuration?.current_revision_id;
        if (current && result.items.some(item => item.revision_id === current)) {
          setProvisionRevisionId(current);
        } else if (result.items.length > 0) {
          setProvisionRevisionId(result.items[0].revision_id);
        } else {
          setProvisionRevisionId("");
        }
      })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [provisionMode, provisionConfigId, provisionConfigurations]);

  async function submitProvision(event: FormEvent) {
    event.preventDefault();
    if (provisioning) return;
    if (!provisionName.trim() || !parentPath.trim()) {
      setError("Project name and parent directory are required.");
      return;
    }
    setProvisioning(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{operation_id:string;status:string;canonical_path:string;project:Project;checkout:any;workspace:any;workspace_bound:boolean}>(
        "/projects/provision",
        json("POST", {
          name: provisionName.trim(),
          parent_path: parentPath.trim(),
          description: provisionDescription,
          configuration_id: provisionConfigId || null,
          configuration_revision_id: provisionRevisionId || null,
        }),
      );
      setProvisionMode(false);
      setProvisionName("");
      setProvisionDescription("");
      setParentPath("");
      setProvisionConfigId("");
      setProvisionRevisionId("");
      setProvisionRevisions([]);
      setNotice(`Project provisioned at ${result.canonical_path}. ${result.workspace_bound ? "Bound to a workspace." : "Not bound to a workspace."}`);
      const items = await api<{items:Project[];total:number}>("/projects?status=" + filter);
      setProjects(items.items);
      if (result.project) {
        const token = ++generation.current;
        setSelectedId(result.project.project_id);
        await loadDetail(result.project.project_id, token);
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setProvisioning(false);
    }
  }

  async function submitProject(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    if (!projectName.trim()) {
      setError("Project name is required.");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    const mutationGeneration = ++generation.current;
    try {
      let result: Project;
      if (projectMode === "create") {
        result = await api<Project>("/projects", json("POST", {
          name: projectName.trim(),
          description: projectDescription,
          git_remote: nullable(gitRemote),
          default_ref: nullable(defaultRef),
          project_type: nullable(projectType),
        }));
        if (mutationGeneration === generation.current) setNotice("Project created.");
      } else if (projectMode === "edit" && selected) {
        result = await api<Project>(
          `/projects/${encodeURIComponent(selected.project_id)}`,
          json("PATCH", {
            name: projectName.trim(),
            description: projectDescription,
            git_remote: nullable(gitRemote),
            default_ref: nullable(defaultRef),
            project_type: nullable(projectType),
            expected_version: selected.version,
          }),
        );
        if (mutationGeneration === generation.current) setNotice("Project updated.");
      } else {
        return;
      }
      if (mutationGeneration === generation.current) {
        setSelectedId(result.project_id);
        setSelected(result);
        setProjectMode("view");
        const items = await fetchProjects(filter);
        if (mutationGeneration === generation.current) {
          setProjects(items);
        }
        await loadDetail(result.project_id, mutationGeneration);
      }
    } catch (e) {
      if (mutationGeneration === generation.current) setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function changeProjectStatus() {
    if (!selected || saving) return;
    const next = selected.status === "active" ? "archived" : "active";
    const action = next === "archived" ? "Archive" : "Reactivate";
    if (!window.confirm(`${action} project "${selected.name}"?`)) return;

    const token = ++generation.current;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await api<Project>(
        `/projects/${encodeURIComponent(selected.project_id)}/${next === "archived" ? "archive" : "reactivate"}`,
        json("POST", { expected_version: selected.version }),
      );
      if (token === generation.current) {
        setNotice(`Project ${next}.`);
        setSelected(updated);
        setProjects(previous => previous.filter(item => item.project_id !== updated.project_id));
        setSelectedId(null);
        setSelected(null);
        setCheckouts([]);
        setSelectedCheckout(null);
        setProjectMode("view");
        setCheckoutMode("view");
      }
    } catch (e) {
      if (token === generation.current) setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  function beginRegisterCheckout() {
    if (!selected || selected.status !== "active") return;
    setSelectedCheckout(null);
    setCheckoutPath("");
    setCheckoutBranch("");
    setCheckoutCommit("");
    setCheckoutMode("register");
    setError("");
    setNotice("");
  }

  function beginEditCheckout(checkout: Checkout) {
    setSelectedCheckout(checkout);
    setCheckoutBranch(checkout.branch_or_ref || "");
    setCheckoutCommit(checkout.last_known_commit || "");
    setCheckoutMode("edit");
    setError("");
    setNotice("");
  }

  async function submitCheckout(event: FormEvent) {
    event.preventDefault();
    if (!selected || saving) return;
    setSaving(true);
    setError("");
    setNotice("");
    const mutationGeneration = ++generation.current;
    try {
      if (checkoutMode === "register") {
        if (!checkoutPath.trim()) {
          setError("A checkout directory path is required.");
          return;
        }
        const created = await api<Checkout>(
          `/projects/${encodeURIComponent(selected.project_id)}/checkouts`,
          json("POST", {
            path: checkoutPath.trim(),
            branch_or_ref: nullable(checkoutBranch),
            last_known_commit: nullable(checkoutCommit),
          }),
        );
        if (mutationGeneration === generation.current) {
          setCheckouts(previous => [...previous, created]);
          setSelectedCheckout(created);
          setCheckoutMode("view");
          setNotice("Checkout registered. The directory was validated by the backend; no files were changed.");
        }
      } else if (checkoutMode === "edit" && selectedCheckout) {
        const updated = await api<Checkout>(
          `/checkouts/${encodeURIComponent(selectedCheckout.checkout_id)}`,
          json("PATCH", {
            branch_or_ref: nullable(checkoutBranch),
            last_known_commit: nullable(checkoutCommit),
            expected_version: selectedCheckout.version,
          }),
        );
        if (mutationGeneration === generation.current) {
          setCheckouts(previous => previous.map(item =>
            item.checkout_id === updated.checkout_id ? updated : item,
          ));
          setSelectedCheckout(updated);
          setCheckoutMode("view");
          setNotice("Checkout metadata updated.");
        }
      }
    } catch (e) {
      if (mutationGeneration === generation.current) setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function refreshAvailability(checkout: Checkout) {
    if (saving) return;
    setSaving(true);
    setError("");
    setNotice("");
    const mutationGeneration = ++generation.current;
    try {
      const updated = await api<Checkout>(
        `/checkouts/${encodeURIComponent(checkout.checkout_id)}/refresh-availability`,
        { method: "POST" },
      );
      if (mutationGeneration === generation.current) {
        setCheckouts(previous => previous.map(item =>
          item.checkout_id === updated.checkout_id ? updated : item,
        ));
        setSelectedCheckout(current =>
          current?.checkout_id === updated.checkout_id ? updated : current,
        );
        setNotice(`Availability refreshed: ${updated.availability_status}.`);
      }
    } catch (e) {
      if (mutationGeneration === generation.current) setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function unregisterCheckout(checkout: Checkout) {
    if (saving) return;
    if (!window.confirm(
      `Unregister this checkout?\n\n${checkout.canonical_path}\n\nThis removes only Evo's registration. It does not delete or modify the directory.`,
    )) return;

    setSaving(true);
    setError("");
    setNotice("");
    const mutationGeneration = ++generation.current;
    try {
      await api<{ checkout_id: string; unregistered: boolean }>(
        `/checkouts/${encodeURIComponent(checkout.checkout_id)}/unregister`,
        json("POST", { expected_version: checkout.version }),
      );
      if (mutationGeneration === generation.current) {
        setCheckouts(previous => previous.filter(item => item.checkout_id !== checkout.checkout_id));
        setSelectedCheckout(current =>
          current?.checkout_id === checkout.checkout_id ? null : current,
        );
        setCheckoutMode("view");
        setNotice("Checkout unregistered. The directory was not changed.");
      }
    } catch (e) {
      if (mutationGeneration === generation.current) setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="workspace-page projects-page">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">PROJECT REGISTRY</div>
          <h1>Projects and checkouts</h1>
          <p>Organize projects and register existing working directories for Evo to reference.</p>
        </div>
        <button className="quiet-button" onClick={() => { setProvisionMode(true); setProvisionName(""); setProvisionDescription(""); setParentPath(""); setProvisionConfigId(""); setProvisionRevisionId(""); setProvisionRevisions([]); setError(""); setNotice(""); }}>＋ Provision project</button>
      </div>

      {error && <div className="workspace-error" role="alert">{error}</div>}
      {notice && <div className="configuration-notice" role="status">{notice}</div>}

      <div className="configuration-layout">
        <aside className="configuration-list-panel">
          <div className="configuration-list-head">
            <div className="configuration-filters">
              <button className={filter === "active" ? "selected" : ""} onClick={() => setFilter("active")}>Active</button>
              <button className={filter === "archived" ? "selected" : ""} onClick={() => setFilter("archived")}>Archived</button>
            </div>
            <span>{projects.length}</span>
          </div>
          {loading && <div className="empty-state">Loading projects…</div>}
          {!loading && projects.map(project => (
            <button
              type="button"
              className={`configuration-list-item ${selectedId === project.project_id ? "selected" : ""}`}
              key={project.project_id}
              onClick={() => void selectProject(project.project_id)}
            >
              <strong>{project.name}</strong>
              <small>Version {project.version} · {project.status}</small>
              <small>{project.project_type || "General project"}</small>
            </button>
          ))}
          {!loading && projects.length === 0 && (
            <div className="empty-state">
              {filter === "active" ? "No active projects. Create one to get started." : "No archived projects."}
            </div>
          )}
          <button className="quiet-button configuration-refresh" disabled={loading} onClick={() => void refresh()}>Refresh list</button>
        </aside>

        <section className="configuration-detail">
          {provisionMode ? (
            <form className="configuration-editor" onSubmit={submitProvision}>
              <div className="panel-toolbar">
                <div>
                  <h2>Provision project</h2>
                  <p>Create a dedicated directory, initialize Git, and register the project and checkout.</p>
                </div>
              </div>
              <label>
                Project name
                <input value={provisionName} onChange={e => setProvisionName(e.target.value)} maxLength={200} required />
              </label>
              <label>
                Parent directory
                <input value={parentPath} onChange={e => setParentPath(e.target.value)} maxLength={4096} placeholder="/path/to/parent" required />
              </label>
              <label>
                Description
                <textarea value={provisionDescription} onChange={e => setProvisionDescription(e.target.value)} maxLength={4000} rows={3} />
              </label>
              <label>
                AI configuration (optional)
                <select value={provisionConfigId} onChange={e => setProvisionConfigId(e.target.value)}>
                  <option value="">No configuration; leave unbound</option>
                  {provisionConfigurations.map(item => <option key={item.configuration_id} value={item.configuration_id}>{item.name}</option>)}
                </select>
              </label>
              {provisionConfigId && (
                <label>
                  Exact configuration revision
                  <select value={provisionRevisionId} onChange={e => setProvisionRevisionId(e.target.value)} disabled={provisionRevisions.length === 0}>
                    <option value="">Select a revision…</option>
                    {provisionRevisions.map(item => <option key={item.revision_id} value={item.revision_id}>Revision {item.revision_number}{item.change_summary ? ` · ${item.change_summary}` : ""}</option>)}
                  </select>
                </label>
              )}
              <div className="inline-actions">
                <button className="quiet-button" type="submit" disabled={provisioning}>{provisioning ? "Provisioning…" : "Provision project"}</button>
                <button className="quiet-button" type="button" disabled={provisioning} onClick={() => setProvisionMode(false)}>Cancel</button>
              </div>
            </form>
          ) : projectMode === "create" || projectMode === "edit" ? (
            <form className="configuration-editor" onSubmit={submitProject}>
              <div className="panel-toolbar">
                <div>
                  <h2>{projectMode === "create" ? "Create project" : "Edit project"}</h2>
                  <p>{projectMode === "create" ? "Register a project in Evo." : `Update project metadata using version ${selected?.version}.`}</p>
                </div>
              </div>
              <label>
                Name
                <input value={projectName} onChange={e => setProjectName(e.target.value)} maxLength={200} required />
              </label>
              <label>
                Description
                <textarea value={projectDescription} onChange={e => setProjectDescription(e.target.value)} maxLength={4000} rows={3} />
              </label>
              <label>
                Git remote (optional)
                <input value={gitRemote} onChange={e => setGitRemote(e.target.value)} maxLength={2048} placeholder="https://… or SSH remote" />
              </label>
              <label>
                Default ref (optional)
                <input value={defaultRef} onChange={e => setDefaultRef(e.target.value)} maxLength={512} placeholder="main" />
              </label>
              <label>
                Project type (optional)
                <input value={projectType} onChange={e => setProjectType(e.target.value)} maxLength={100} placeholder="e.g. software" />
              </label>
              <div className="inline-actions">
                <button className="quiet-button" type="submit" disabled={saving}>{saving ? "Saving…" : projectMode === "create" ? "Create project" : "Save changes"}</button>
                <button className="quiet-button" type="button" disabled={saving} onClick={() => setProjectMode("view")}>Cancel</button>
              </div>
            </form>
          ) : selected ? (
            <>
              <div className="panel-toolbar">
                <div>
                  <h2>{selected.name}</h2>
                  <p>{selected.description || "No description"}</p>
                </div>
                <span className={`run-status ${selected.status}`}>{selected.status}</span>
              </div>

              <div className="configuration-meta">
                <span>Version <strong>{selected.version}</strong></span>
                <span>Type <strong>{selected.project_type || "Not set"}</strong></span>
                <span>Default ref <strong>{selected.default_ref || "Not set"}</strong></span>
                <span>Created <strong>{date(selected.created_at)}</strong></span>
              </div>

              <div className="configuration-section">
                <div className="panel-toolbar">
                  <div><h3>Project metadata</h3><p>Registry metadata only; no Git operations are performed here.</p></div>
                </div>
                <div className="project-fields">
                  <div><small>Git remote</small><strong>{selected.git_remote || "Not set"}</strong></div>
                  <div><small>Project ID</small><strong>{selected.project_id}</strong></div>
                  <div><small>Updated</small><strong>{date(selected.updated_at)}</strong></div>
                </div>
              </div>

              <div className="inline-actions configuration-actions">
                <button className="quiet-button" disabled={saving} onClick={beginEditProject}>Edit project</button>
                <button className="quiet-button" disabled={saving} onClick={() => void changeProjectStatus()}>{selected.status === "active" ? "Archive project" : "Reactivate project"}</button>
                <button className="quiet-button" disabled={loading || saving} onClick={() => void refresh()}>Reload from server</button>
              </div>

              <section className="configuration-section">
                <div className="panel-toolbar">
                  <div><h3>Registered checkouts</h3><p>Existing directories registered with this project. Registration does not create or modify files.</p></div>
                  <div className="inline-actions">
                    <span className="workspace-count">{checkouts.length} checkouts</span>
                    {selected.status === "active" && <button className="quiet-button" disabled={saving} onClick={beginRegisterCheckout}>＋ Register checkout</button>}
                  </div>
                </div>

                <div className="project-checkouts">
                  {checkouts.map(checkout => (
                    <article className={`project-checkout ${selectedCheckout?.checkout_id === checkout.checkout_id ? "selected" : ""}`} key={checkout.checkout_id}>
                      <div className="project-checkout-main">
                        <strong>{checkout.canonical_path}</strong>
                        <small>{checkout.branch_or_ref || "Ref not recorded"} · {checkout.last_known_commit || "Commit not recorded"}</small>
                        <span className={`checkout-availability ${checkout.availability_status}`}>{checkout.availability_status}</span>
                        <small>Version {checkout.version} · Updated {date(checkout.updated_at)}</small>
                      </div>
                      <div className="inline-actions">
                        <button className="quiet-button" disabled={saving} onClick={() => beginEditCheckout(checkout)}>Edit metadata</button>
                        <button className="quiet-button" disabled={saving} onClick={() => void refreshAvailability(checkout)}>Refresh availability</button>
                        <button className="quiet-button danger" disabled={saving} onClick={() => void unregisterCheckout(checkout)}>Unregister</button>
                      </div>
                    </article>
                  ))}
                  {checkouts.length === 0 && <div className="empty-state">No checkouts registered to this project.</div>}
                </div>
              </section>

              {checkoutMode === "register" || checkoutMode === "edit" ? (
                <section className="configuration-section">
                  <form className="configuration-editor" onSubmit={submitCheckout}>
                    <div className="panel-toolbar">
                      <div>
                        <h3>{checkoutMode === "register" ? "Register existing checkout" : "Edit checkout metadata"}</h3>
                        <p>{checkoutMode === "register" ? "The backend validates that this path exists and is a directory." : `Update metadata using checkout version ${selectedCheckout?.version}.`}</p>
                      </div>
                    </div>
                    {checkoutMode === "register" && (
                      <label>
                        Existing directory path
                        <input value={checkoutPath} onChange={e => setCheckoutPath(e.target.value)} maxLength={4096} placeholder="/path/to/working-directory" required />
                      </label>
                    )}
                    <label>
                      Branch or ref (optional)
                      <input value={checkoutBranch} onChange={e => setCheckoutBranch(e.target.value)} maxLength={512} />
                    </label>
                    <label>
                      Last known commit (optional)
                      <input value={checkoutCommit} onChange={e => setCheckoutCommit(e.target.value)} maxLength={128} />
                    </label>
                    <div className="inline-actions">
                      <button className="quiet-button" type="submit" disabled={saving}>{saving ? "Saving…" : checkoutMode === "register" ? "Register checkout" : "Save metadata"}</button>
                      <button className="quiet-button" type="button" disabled={saving} onClick={() => setCheckoutMode("view")}>Cancel</button>
                    </div>
                  </form>
                </section>
              ) : null}
            </>
          ) : (
            <div className="configuration-empty">
              <div className="eyebrow">PROJECT REGISTRY</div>
              <h2>Select a project</h2>
              <p>Choose a project on the left, or register a new project.</p>
              <button className="quiet-button" onClick={beginCreateProject}>Create project</button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
