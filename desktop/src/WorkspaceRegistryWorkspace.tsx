import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

const API = "http://127.0.0.1:8765/api/v1";

type Workspace = {
  workspace_id: string;
  name: string;
  description: string;
  project_id: string;
  checkout_id: string | null;
  configuration_id: string;
  configuration_revision_id: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  version: number;
};

type Project = {
  project_id: string;
  name: string;
  status: "active" | "archived";
};

type Configuration = {
  configuration_id: string;
  name: string;
  status: "active" | "archived";
  current_revision_id: string;
};

type Revision = {
  revision_id: string;
  configuration_id: string;
  revision_number: number;
  change_summary: string;
  created_at: string;
};

type Checkout = {
  checkout_id: string;
  project_id: string;
  canonical_path: string;
  branch_or_ref: string | null;
  availability_status: string;
};

type ParticipantDescriptor = {
  participant_id: string;
  integration_id: string;
  participant_type: string;
  display_name: string;
  adapter_id: string;
  adapter_contract_version: number;
  adapter_implementation_version: string;
  capabilities: string[];
  execution_location: string;
  availability: string;
  availability_observed_at: string | null;
  resource_requirements: Record<string, string>;
  limits: Record<string, string | number>;
  configuration_revision_id: string;
};

type ParticipantAvailability = {
  availability: "available" | "unavailable" | "unknown";
  metadata_preflight?: string;
  transport_reachable: boolean | null;
  model_advertised: boolean | null;
  completion_verified: boolean | null;
  observed_at_utc: string;
  probe_kind: string;
  ephemeral: boolean;
};

type ListResult<T> = { items: T[]; total: number };

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
      // Preserve HTTP status text for non-JSON responses.
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

export function WorkspaceRegistryWorkspace() {
  const [filter, setFilter] = useState<"active" | "archived">("active");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Workspace | null>(null);

  const [projects, setProjects] = useState<Project[]>([]);
  const [configurations, setConfigurations] = useState<Configuration[]>([]);
  const [checkouts, setCheckouts] = useState<Checkout[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);

  const [mode, setMode] = useState<"view" | "create">("view");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [checkoutId, setCheckoutId] = useState("");
  const [configurationId, setConfigurationId] = useState("");
  const [revisionId, setRevisionId] = useState("");

  const [loading, setLoading] = useState(false);
  const [dependenciesLoading, setDependenciesLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [participants, setParticipants] = useState<ParticipantDescriptor[]>([]);
  const [participantLoading, setParticipantLoading] = useState(false);
  const [participantError, setParticipantError] = useState("");
  const [availability, setAvailability] = useState<Record<string, ParticipantAvailability>>({});
  const [availabilityLoadingId, setAvailabilityLoadingId] = useState<string | null>(null);

  const viewGeneration = useRef(0);
  const dependencyGeneration = useRef(0);
  const checkoutGeneration = useRef(0);
  const revisionGeneration = useRef(0);
  const participantGeneration = useRef(0);
  const availabilityGeneration = useRef(0);
  const savingRef = useRef(false);

  const fetchList = useCallback(async (status: "active" | "archived") => {
    const result = await api<ListResult<Workspace>>(
      `/workspaces?status=${status}`,
    );
    return result.items;
  }, []);

  const loadDetail = useCallback(async (id: string, token: number) => {
    const result = await api<Workspace>(
      `/workspaces/${encodeURIComponent(id)}`,
    );
    if (token !== viewGeneration.current) return null;
    setSelected(result);
    return result;
  }, []);

  const refresh = useCallback(async () => {
    if (loading) return;
    const token = ++viewGeneration.current;
    setLoading(true);
    setError("");
    try {
      const items = await fetchList(filter);
      if (token !== viewGeneration.current) return;
      setWorkspaces(items);
      if (selectedId && items.some(item => item.workspace_id === selectedId)) {
        await loadDetail(selectedId, token);
      } else {
        setSelectedId(null);
        setSelected(null);
        setMode("view");
      }
    } catch (e) {
      if (token === viewGeneration.current) setError(errorText(e));
    } finally {
      if (token === viewGeneration.current) setLoading(false);
    }
  }, [filter, selectedId, loading, fetchList, loadDetail]);

  useEffect(() => {
    const token = ++viewGeneration.current;
    let alive = true;
    setLoading(true);
    setError("");
    fetchList(filter)
      .then(items => {
        if (!alive || token !== viewGeneration.current) return;
        setWorkspaces(items);
        if (selectedId && items.some(item => item.workspace_id === selectedId)) {
          return loadDetail(selectedId, token);
        }
        setSelectedId(null);
        setSelected(null);
        setMode("view");
        return undefined;
      })
      .catch(e => {
        if (alive && token === viewGeneration.current) setError(errorText(e));
      })
      .finally(() => {
        if (alive && token === viewGeneration.current) setLoading(false);
      });
    return () => {
      alive = false;
      viewGeneration.current += 1;
    };
  // Filter changes reload the list; selection is reconciled by ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  useEffect(() => {
    const token = ++dependencyGeneration.current;
    let alive = true;
    setDependenciesLoading(true);
    Promise.all([
      api<ListResult<Project>>("/projects?status=active"),
      api<ListResult<Configuration>>("/configurations?status=active"),
    ])
      .then(([projectResult, configurationResult]) => {
        if (!alive || token !== dependencyGeneration.current) return;
        setProjects(projectResult.items);
        setConfigurations(configurationResult.items);
      })
      .catch(e => {
        if (alive && token === dependencyGeneration.current) {
          setError(`Unable to load workspace creation options: ${errorText(e)}`);
        }
      })
      .finally(() => {
        if (alive && token === dependencyGeneration.current) {
          setDependenciesLoading(false);
        }
      });
    return () => {
      alive = false;
      dependencyGeneration.current += 1;
    };
  }, []);

  useEffect(() => {
    const token = ++checkoutGeneration.current;
    let alive = true;
    setCheckouts([]);
    setCheckoutId("");
    if (!projectId) {
      return () => {
        alive = false;
        checkoutGeneration.current += 1;
      };
    }
    api<ListResult<Checkout>>(
      `/projects/${encodeURIComponent(projectId)}/checkouts`,
    )
      .then(result => {
        if (alive && token === checkoutGeneration.current) {
          setCheckouts(
            result.items.filter(item => item.availability_status === "available"),
          );
        }
      })
      .catch(e => {
        if (alive && token === checkoutGeneration.current) {
          setError(`Unable to load available checkouts: ${errorText(e)}`);
        }
      });
    return () => {
      alive = false;
      checkoutGeneration.current += 1;
    };
  }, [projectId]);

  useEffect(() => {
    const token = ++revisionGeneration.current;
    let alive = true;
    setRevisions([]);
    setRevisionId("");
    if (!configurationId) {
      return () => {
        alive = false;
        revisionGeneration.current += 1;
      };
    }
    api<ListResult<Revision>>(
      `/configurations/${encodeURIComponent(configurationId)}/revisions`,
    )
      .then(result => {
        if (!alive || token !== revisionGeneration.current) return;
        setRevisions(result.items);
        const configuration = configurations.find(
          item => item.configuration_id === configurationId,
        );
        const current = configuration?.current_revision_id;
        if (current && result.items.some(item => item.revision_id === current)) {
          setRevisionId(current);
        } else if (result.items.length > 0) {
          setRevisionId(result.items[0].revision_id);
        }
      })
      .catch(e => {
        if (alive && token === revisionGeneration.current) {
          setError(`Unable to load configuration revisions: ${errorText(e)}`);
        }
      });
    return () => {
      alive = false;
      revisionGeneration.current += 1;
    };
  }, [configurationId, configurations]);

  async function selectWorkspace(id: string) {
    const token = ++viewGeneration.current;
    setError("");
    setNotice("");
    setMode("view");
    setSelectedId(id);
    setSelected(null);
    setLoading(true);
    try {
      await loadDetail(id, token);
    } catch (e) {
      if (token === viewGeneration.current) {
        setError(errorText(e));
        setSelectedId(null);
        setSelected(null);
      }
    } finally {
      if (token === viewGeneration.current) setLoading(false);
    }
  }

  function beginCreate() {
    viewGeneration.current += 1;
    setSelectedId(null);
    setSelected(null);
    setName("");
    setDescription("");
    setProjectId("");
    setCheckoutId("");
    setConfigurationId("");
    setRevisionId("");
    setRevisions([]);
    setCheckouts([]);
    setMode("create");
    setError("");
    setNotice("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (savingRef.current) return;
    if (!name.trim() || !projectId || !configurationId || !revisionId) {
      setError("Name, project, configuration, and exact configuration revision are required.");
      return;
    }

    const token = viewGeneration.current;
    savingRef.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const created = await api<Workspace>(
        "/workspaces",
        json("POST", {
          name: name.trim(),
          description,
          project_id: projectId,
          configuration_id: configurationId,
          configuration_revision_id: revisionId,
          checkout_id: checkoutId || null,
        }),
      );
      if (token === viewGeneration.current) {
        setSelectedId(created.workspace_id);
        setSelected(created);
        setMode("view");
        setNotice("Workspace created. Its project and exact configuration revision are now pinned.");
        setFilter("active");
      }
    } catch (e) {
      if (token === viewGeneration.current) setError(errorText(e));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function changeStatus() {
    if (!selected || savingRef.current) return;
    const next = selected.status === "active" ? "archived" : "active";
    const action = next === "archived" ? "Archive" : "Reactivate";
    if (!window.confirm(`${action} workspace "${selected.name}"?`)) return;

    const token = ++viewGeneration.current;
    savingRef.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await api<Workspace>(
        `/workspaces/${encodeURIComponent(selected.workspace_id)}/${next === "archived" ? "archive" : "reactivate"}`,
        json("POST", { expected_version: selected.version }),
      );
      if (token === viewGeneration.current) {
        setNotice(`Workspace ${next}.`);
        setWorkspaces(previous => previous.filter(
          item => item.workspace_id !== updated.workspace_id,
        ));
        setSelectedId(null);
        setSelected(null);
        setMode("view");
        setFilter(next);
      }
    } catch (e) {
      if (token === viewGeneration.current) setError(errorText(e));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const projectName = (id: string) =>
    projects.find(item => item.project_id === id)?.name || id;

  const configurationName = (id: string) =>
    configurations.find(item => item.configuration_id === id)?.name || id;

  const selectedRevision = revisions.find(item => item.revision_id === revisionId);

  const loadParticipants = useCallback(async () => {
    if (!selected || selected.status !== "active") return;
    const token = ++participantGeneration.current;
    setParticipantLoading(true);
    setParticipantError("");
    try {
      const result = await api<{
        workspace_id: string;
        configuration_revision_id: string;
        dispatch_enabled: boolean;
        participants: ParticipantDescriptor[];
      }>(`/workspaces/${encodeURIComponent(selected.workspace_id)}/participants`);
      if (token !== participantGeneration.current) return;
      if (result.configuration_revision_id !== selected.configuration_revision_id) {
        throw new Error("Runtime inspection returned a different pinned configuration revision.");
      }
      setParticipants(result.participants);
      setAvailability({});
    } catch (e) {
      if (token === participantGeneration.current) {
        setParticipantError(errorText(e));
        setParticipants([]);
      }
    } finally {
      if (token === participantGeneration.current) setParticipantLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    participantGeneration.current += 1;
    availabilityGeneration.current += 1;
    setParticipants([]);
    setAvailability({});
    setAvailabilityLoadingId(null);
    setParticipantError("");
    if (selected?.status === "active") void loadParticipants();
    return () => {
      participantGeneration.current += 1;
      availabilityGeneration.current += 1;
    };
  }, [loadParticipants, selected?.workspace_id, selected?.status]);

  async function checkParticipantAvailability(participantId: string) {
    if (!selected || availabilityLoadingId) return;
    const token = ++availabilityGeneration.current;
    setAvailabilityLoadingId(participantId);
    setParticipantError("");
    try {
      const result = await api<ParticipantAvailability>(
        `/workspaces/${encodeURIComponent(selected.workspace_id)}/participants/${encodeURIComponent(participantId)}/availability?timeout_seconds=4`,
      );
      if (token === availabilityGeneration.current) {
        setAvailability(previous => ({ ...previous, [participantId]: result }));
      }
    } catch (e) {
      if (token === availabilityGeneration.current) setParticipantError(errorText(e));
    } finally {
      if (token === availabilityGeneration.current) setAvailabilityLoadingId(null);
    }
  }

  return (
    <div className="workspace-page configuration-page">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">WORKSPACE REGISTRY</div>
          <h1>Workspaces</h1>
          <p>Bind a project to an immutable AI configuration revision, with an optional available checkout.</p>
        </div>
        <button className="quiet-button" onClick={beginCreate}>＋ New workspace</button>
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
            <span>{workspaces.length}</span>
          </div>

          {loading && <div className="empty-state">Loading workspaces…</div>}

          {!loading && workspaces.map(item => (
            <button
              type="button"
              className={`configuration-list-item ${selectedId === item.workspace_id ? "selected" : ""}`}
              key={item.workspace_id}
              onClick={() => void selectWorkspace(item.workspace_id)}
            >
              <strong>{item.name}</strong>
              <small>Version {item.version} · {item.status}</small>
              <small>{item.description || "No description"}</small>
            </button>
          ))}

          {!loading && workspaces.length === 0 && (
            <div className="empty-state">
              {filter === "active" ? "No active workspaces. Create one to get started." : "No archived workspaces."}
            </div>
          )}

          <button
            className="quiet-button configuration-refresh"
            disabled={loading}
            onClick={() => void refresh()}
          >
            Refresh list
          </button>
        </aside>

        <section className="configuration-detail">
          {mode === "create" ? (
            <form className="configuration-editor" onSubmit={submit}>
              <div className="panel-toolbar">
                <div>
                  <h2>Create workspace</h2>
                  <p>A workspace pins one project and one exact immutable configuration revision.</p>
                </div>
                <span className="workspace-count">NEW</span>
              </div>

              <label>
                Workspace name
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  maxLength={200}
                  required
                />
              </label>

              <label>
                Description
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  maxLength={4000}
                  rows={3}
                />
              </label>

              <label>
                Project
                <select value={projectId} onChange={e => setProjectId(e.target.value)} required>
                  <option value="">Select an active project…</option>
                  {projects.map(item => (
                    <option key={item.project_id} value={item.project_id}>{item.name}</option>
                  ))}
                </select>
              </label>

              <label>
                Checkout (optional)
                <select
                  value={checkoutId}
                  onChange={e => setCheckoutId(e.target.value)}
                  disabled={!projectId}
                >
                  <option value="">No checkout</option>
                  {checkouts.map(item => (
                    <option key={item.checkout_id} value={item.checkout_id}>
                      {item.canonical_path}{item.branch_or_ref ? ` · ${item.branch_or_ref}` : ""}
                    </option>
                  ))}
                </select>
                <small className="policy-copy">Only checkouts currently reported as available are offered.</small>
              </label>

              <label>
                AI configuration
                <select
                  value={configurationId}
                  onChange={e => setConfigurationId(e.target.value)}
                  required
                >
                  <option value="">Select an active configuration…</option>
                  {configurations.map(item => (
                    <option key={item.configuration_id} value={item.configuration_id}>{item.name}</option>
                  ))}
                </select>
              </label>

              <label>
                Exact configuration revision
                <select
                  value={revisionId}
                  onChange={e => setRevisionId(e.target.value)}
                  disabled={!configurationId || revisions.length === 0}
                  required
                >
                  <option value="">Select a revision…</option>
                  {revisions.map(item => (
                    <option key={item.revision_id} value={item.revision_id}>
                      Revision {item.revision_number}{item.change_summary ? ` · ${item.change_summary}` : ""}
                    </option>
                  ))}
                </select>
                {selectedRevision && (
                  <small className="policy-copy">
                    Selected revision created {date(selectedRevision.created_at)}. This exact revision will be pinned.
                  </small>
                )}
              </label>

              {dependenciesLoading && <div className="empty-state">Loading projects and configurations…</div>}

              {!dependenciesLoading && projects.length === 0 && (
                <div className="empty-state">No active projects are available. Register or reactivate a project first.</div>
              )}

              {!dependenciesLoading && configurations.length === 0 && (
                <div className="empty-state">No active configurations are available. Create or reactivate a configuration first.</div>
              )}

              <div className="inline-actions">
                <button
                  className="quiet-button"
                  type="submit"
                  disabled={saving || dependenciesLoading || projects.length === 0 || configurations.length === 0 || !revisionId}
                >
                  {saving ? "Creating…" : "Create workspace"}
                </button>
                <button
                  className="quiet-button"
                  type="button"
                  disabled={saving}
                  onClick={() => setMode("view")}
                >
                  Cancel
                </button>
              </div>

              <p className="policy-copy">
                The backend revalidates the project, configuration, revision ownership, and optional checkout availability when creating the workspace. Workspace bindings are immutable; create another workspace to use a different binding.
              </p>
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
                <span>Created <strong>{date(selected.created_at)}</strong></span>
                <span>Updated <strong>{date(selected.updated_at)}</strong></span>
              </div>

              <div className="inline-actions configuration-actions">
                <button
                  className="quiet-button"
                  disabled={saving}
                  onClick={() => void changeStatus()}
                >
                  {selected.status === "active" ? "Archive" : "Reactivate"}
                </button>
                <button
                  className="quiet-button"
                  disabled={loading || saving}
                  onClick={() => void refresh()}
                >
                  Reload from server
                </button>
              </div>

              <section className="configuration-section">
                <div className="panel-toolbar">
                  <div>
                    <h3>Workspace bindings</h3>
                    <p>These references are fixed for this workspace.</p>
                  </div>
                </div>

                <div className="project-fields">
                  <div><small>Project ID</small><strong>{selected.project_id}</strong></div>
                  <div><small>Project name</small><strong>{projectName(selected.project_id)}</strong></div>
                  <div><small>Configuration ID</small><strong>{selected.configuration_id}</strong></div>
                  <div><small>Configuration name</small><strong>{configurationName(selected.configuration_id)}</strong></div>
                  <div><small>Configuration revision ID</small><strong>{selected.configuration_revision_id}</strong></div>
                  <div><small>Checkout ID</small><strong>{selected.checkout_id || "None"}</strong></div>
                </div>

                <p className="policy-copy">
                  The configuration revision is pinned by ID, not by the configuration's moving current-revision pointer. Archiving or reactivating a workspace does not rewrite its bindings.
                </p>
              </section>

              <section className="configuration-section">
                <div className="panel-toolbar">
                  <div>
                    <h3>Bound participants</h3>
                    <p>Runtime participants resolved from this workspace's exact pinned revision. Inspection does not authorize invocation.</p>
                  </div>
                  <button className="quiet-button" disabled={participantLoading || selected.status !== "active"} onClick={() => void loadParticipants()}>
                    {participantLoading ? "Inspecting…" : "Refresh participants"}
                  </button>
                </div>
                {participantError && <div className="workspace-error" role="alert">{participantError}</div>}
                {participantLoading && <div className="empty-state">Resolving the pinned runtime…</div>}
                {!participantLoading && participants.length === 0 && !participantError && (
                  <div className="empty-state">No executable participants are available for this workspace revision.</div>
                )}
                <div className="record-list">
                  {participants.map(participant => {
                    const observed = availability[participant.participant_id];
                    return <article className="record-card" key={participant.participant_id}>
                      <div className="record-top">
                        <span className="record-category">{participant.participant_type}</span>
                        <span>{participant.availability}</span>
                        <span>{participant.execution_location}</span>
                      </div>
                      <p><strong>{participant.display_name}</strong></p>
                      <div className="record-bottom">
                        <small>{participant.adapter_id} v{participant.adapter_contract_version} · {participant.adapter_implementation_version}</small>
                        <small>Capabilities: {participant.capabilities.join(", ") || "None declared"}</small>
                        <small>Component: {participant.component_key} v{participant.component_version}</small>
                        <small>Revision: {participant.configuration_revision_id}</small>
                      </div>
                      {participant.adapter_id === "openai_compatible_chat" && (
                        <div className="inline-actions">
                          <button className="quiet-button" disabled={availabilityLoadingId !== null} onClick={() => void checkParticipantAvailability(participant.participant_id)}>
                            {availabilityLoadingId === participant.participant_id ? "Checking…" : "Check metadata availability"}
                          </button>
                        </div>
                      )}
                      {observed && (
                        <div className="record-bottom">
                          <small>Participant availability: {observed.availability} · metadata: {observed.metadata_preflight || observed.probe_kind}</small>
                          <small>Transport reachable: {observed.transport_reachable === null ? "unknown" : observed.transport_reachable ? "yes" : "no"} · model advertised: {observed.model_advertised === null ? "unknown" : observed.model_advertised ? "yes" : "no"}</small>
                          <small>Completion verified: {observed.completion_verified === null ? "not tested" : observed.completion_verified ? "yes" : "no"} · observation: {date(observed.observed_at_utc)}</small>
                          <small>This metadata-only result is ephemeral and does not prove a completion will succeed.</small>
                        </div>
                      )}
                    </article>;
                  })}
                </div>
              </section>
            </>
          ) : (
            <div className="configuration-empty">
              <h2>{loading ? "Loading workspace…" : "Select a workspace"}</h2>
              <p>{loading ? "Retrieving the latest workspace record." : "Choose a workspace from the list, or create a new one."}</p>
              {!loading && (
                <button className="quiet-button" onClick={beginCreate}>＋ New workspace</button>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
