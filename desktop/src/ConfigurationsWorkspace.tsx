import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

const API = "http://127.0.0.1:8765/api/v1";

type Configuration = {
  configuration_id: string;
  name: string;
  description: string;
  status: "active" | "archived";
  current_revision_id: string;
  created_at: string;
  updated_at: string;
  version: number;
};

type Revision = {
  revision_id: string;
  configuration_id: string;
  revision_number: number;
  schema_version: number;
  definition: Record<string, unknown>;
  content_hash: string;
  parent_revision_id: string | null;
  change_summary: string;
  created_at: string;
  provenance: Record<string, unknown>;
};

type RevisionResult = {
  configuration: Configuration;
  revision: Revision;
};

type ConfigurationList = { items: Configuration[]; total: number };
type RevisionList = { items: Revision[]; total: number };

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
      // Keep the HTTP status text when the response is not JSON.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return `Version conflict: ${error.message}. Your local edits have been preserved. Reload the configuration before attempting another change.`;
  }
  return error instanceof Error ? error.message : String(error);
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseDefinition(source: string): Record<string, unknown> {
  const value: unknown = JSON.parse(source);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("The configuration definition must be a JSON object.");
  }
  return value as Record<string, unknown>;
}

function date(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function ConfigurationsWorkspace() {
  const [filter, setFilter] = useState<"active" | "archived">("active");
  const [configurations, setConfigurations] = useState<Configuration[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Configuration | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<Revision | null>(null);

  const [definition, setDefinition] = useState("{}");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const [mode, setMode] = useState<"view" | "create" | "edit">("view");
  const detailGeneration = useRef(0);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadConfigurations = useCallback(async (status: "active" | "archived") => {
    const result = await api<ConfigurationList>(
      `/configurations?status=${status}`,
    );
    setConfigurations(result.items);
    return result.items;
  }, []);

  const loadDetail = useCallback(async (id: string, generation: number) => {
    const [configuration, history] = await Promise.all([
      api<Configuration>(`/configurations/${encodeURIComponent(id)}`),
      api<RevisionList>(`/configurations/${encodeURIComponent(id)}/revisions`),
    ]);
    if (generation !== detailGeneration.current) return null;
    setSelected(configuration);
    setRevisions(history.items);
    return { configuration, revisions: history.items };
  }, []);

  const refresh = useCallback(async () => {
    if (loading) return;
    const generation = ++detailGeneration.current;
    setLoading(true);
    setError("");
    try {
      const items = await loadConfigurations(filter);
      if (generation !== detailGeneration.current) return;
      if (selectedId && items.some(item => item.configuration_id === selectedId)) {
        await loadDetail(selectedId, generation);
      } else {
        setSelectedId(null);
        setSelected(null);
        setRevisions([]);
        setSelectedRevision(null);
        setMode("view");
      }
    } catch (e) {
      if (generation === detailGeneration.current) setError(errorText(e));
    } finally {
      if (generation === detailGeneration.current) setLoading(false);
    }
  }, [filter, selectedId, loading, loadConfigurations, loadDetail]);

  useEffect(() => {
    const generation = ++detailGeneration.current;
    let alive = true;
    setLoading(true);
    setError("");
    loadConfigurations(filter)
      .then(items => {
        if (!alive || generation !== detailGeneration.current) return;
        if (selectedId && items.some(item => item.configuration_id === selectedId)) {
          return loadDetail(selectedId, generation);
        }
        setSelectedId(null);
        setSelected(null);
        setRevisions([]);
        setSelectedRevision(null);
        setMode("view");
        return undefined;
      })
      .catch(e => {
        if (alive && generation === detailGeneration.current) setError(errorText(e));
      })
      .finally(() => {
        if (alive && generation === detailGeneration.current) setLoading(false);
      });
    return () => {
      alive = false;
      detailGeneration.current += 1;
    };
  // Filter changes intentionally reload the list; selection is reconciled by ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function selectConfiguration(id: string) {
    const generation = ++detailGeneration.current;
    setError("");
    setNotice("");
    setSelectedRevision(null);
    setMode("view");
    setSelectedId(id);
    setLoading(true);
    try {
      await loadDetail(id, generation);
    } catch (e) {
      if (generation === detailGeneration.current) {
        setError(errorText(e));
        setSelectedId(null);
        setSelected(null);
      }
    } finally {
      if (generation === detailGeneration.current) setLoading(false);
    }
  }

  function beginCreate() {
    detailGeneration.current += 1;
    setError("");
    setNotice("");
    setSelectedId(null);
    setSelected(null);
    setRevisions([]);
    setSelectedRevision(null);
    setName("");
    setDescription("");
    setChangeSummary("");
    setDefinition("{}");
    setMode("create");
  }

  function beginRevision() {
    if (!selected || selected.status !== "active") return;
    const current = revisions.find(item => item.revision_id === selected.current_revision_id);
    setDefinition(pretty(current?.definition ?? {}));
    setName(selected.name);
    setDescription(selected.description);
    setChangeSummary("");
    setSelectedRevision(null);
    setMode("edit");
    setError("");
    setNotice("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;

    let parsed: Record<string, unknown>;
    try {
      parsed = parseDefinition(definition);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (mode === "create") {
        const result = await api<RevisionResult>("/configurations", json({
          name: name.trim(),
          description,
          change_summary: changeSummary,
          definition: parsed,
        }));
        setSelectedId(result.configuration.configuration_id);
        setSelected(result.configuration);
        setRevisions([result.revision]);
        setSelectedRevision(result.revision);
        setMode("view");
        setNotice("Configuration created.");
        await loadConfigurations(filter);
      } else if (mode === "edit" && selected) {
        const result = await api<RevisionResult>(
          `/configurations/${encodeURIComponent(selected.configuration_id)}/revisions`,
          json({
            definition: parsed,
            expected_version: selected.version,
            parent_revision_id: selected.current_revision_id,
            change_summary: changeSummary,
            name: name.trim(),
            description,
          }),
        );
        setSelected(result.configuration);
        setRevisions(previous => [result.revision, ...previous]);
        setSelectedRevision(result.revision);
        setMode("view");
        setNotice(`Revision ${result.revision.revision_number} created.`);
        await loadConfigurations(filter);
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function inspectRevision(revision: Revision) {
    setError("");
    setNotice("");
    try {
      const full = await api<Revision>(
        `/configurations/${encodeURIComponent(revision.configuration_id)}/revisions/${encodeURIComponent(revision.revision_id)}`,
      );
      setSelectedRevision(full);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function restoreRevision(revision: Revision) {
    if (!selected || saving) return;
    const summary = window.prompt(
      `Restore revision ${revision.revision_number} as a new current revision.\n\nDescribe this change:`,
      `Restore revision ${revision.revision_number}`,
    );
    if (summary === null) return;

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await api<RevisionResult>(
        `/configurations/${encodeURIComponent(selected.configuration_id)}/restore/${encodeURIComponent(revision.revision_id)}`,
        json({
          expected_version: selected.version,
          change_summary: summary,
        }),
      );
      setSelected(result.configuration);
      setRevisions(previous => [result.revision, ...previous]);
      setSelectedRevision(result.revision);
      setNotice(`Restored as new revision ${result.revision.revision_number}. Previous revisions remain intact.`);
      await loadConfigurations(filter);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus() {
    if (!selected || saving) return;
    const nextStatus = selected.status === "active" ? "archived" : "active";
    const action = nextStatus === "archived" ? "Archive" : "Reactivate";
    if (!window.confirm(`${action} "${selected.name || "Untitled configuration"}"?`)) return;

    detailGeneration.current += 1;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await api<Configuration>(
        `/configurations/${encodeURIComponent(selected.configuration_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: nextStatus, expected_version: selected.version }),
        },
      );
      setSelected(updated);
      setNotice(`Configuration ${nextStatus}.`);
      setFilter(nextStatus);
      setConfigurations(previous => previous.filter(item => item.configuration_id !== updated.configuration_id));
      setSelectedId(null);
      setSelected(null);
      setRevisions([]);
      setSelectedRevision(null);
      setMode("view");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  const currentRevision = revisions.find(
    item => item.revision_id === selected?.current_revision_id,
  );

  return (
    <div className="workspace-page configuration-page">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">MODEL AND AGENT SETUP</div>
          <h1>AI Configurations</h1>
          <p>Versioned, immutable configuration definitions. Changes create revisions; they never overwrite history.</p>
        </div>
        <button className="quiet-button" onClick={beginCreate}>＋ New configuration</button>
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
            <span>{configurations.length}</span>
          </div>
          {loading && <div className="empty-state">Loading configurations…</div>}
          {!loading && configurations.map(item => (
            <button
              type="button"
              className={`configuration-list-item ${selectedId === item.configuration_id ? "selected" : ""}`}
              key={item.configuration_id}
              onClick={() => void selectConfiguration(item.configuration_id)}
            >
              <strong>{item.name || "Untitled configuration"}</strong>
              <small>Version {item.version} · {item.status}</small>
              <small>{item.description || "No description"}</small>
            </button>
          ))}
          {!loading && configurations.length === 0 && (
            <div className="empty-state">
              {filter === "active" ? "No active configurations. Create one to get started." : "No archived configurations."}
            </div>
          )}
          <button className="quiet-button configuration-refresh" disabled={loading} onClick={() => void refresh()}>Refresh list</button>
        </aside>

        <section className="configuration-detail">
          {mode === "create" || mode === "edit" ? (
            <form className="configuration-editor" onSubmit={submit}>
              <div className="panel-toolbar">
                <div>
                  <h2>{mode === "create" ? "Create configuration" : "Create new revision"}</h2>
                  <p>{mode === "create" ? "A new configuration starts at revision 1." : `Saving creates a new immutable revision from version ${selected?.version}.`}</p>
                </div>
                <span className="workspace-count">{mode === "create" ? "NEW" : "VERSIONED"}</span>
              </div>

              <label>
                Name
                <input value={name} onChange={e => setName(e.target.value)} maxLength={200} placeholder="e.g. Local coding agent" />
              </label>
              <label>
                Description
                <textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={4000} rows={2} />
              </label>
              <label>
                Change summary
                <input value={changeSummary} onChange={e => setChangeSummary(e.target.value)} maxLength={2000} placeholder="What does this configuration change?" />
              </label>
              <label>
                Configuration definition (JSON object)
                <textarea
                  className="configuration-json-editor"
                  value={definition}
                  onChange={e => setDefinition(e.target.value)}
                  spellCheck={false}
                  rows={18}
                  required
                />
              </label>
              <div className="inline-actions">
                <button className="quiet-button" type="submit" disabled={saving}>{saving ? "Saving…" : mode === "create" ? "Create configuration" : "Create revision"}</button>
                <button className="quiet-button" type="button" disabled={saving} onClick={() => setMode("view")}>Cancel</button>
              </div>
              <p className="policy-copy">Definitions are stored as JSON. Do not put passwords, API keys, or other raw credentials in this editor; use the backend's supported secret-reference mechanism.</p>
            </form>
          ) : selected ? (
            <>
              <div className="panel-toolbar">
                <div>
                  <h2>{selected.name || "Untitled configuration"}</h2>
                  <p>{selected.description || "No description"}</p>
                </div>
                <span className={`run-status ${selected.status}`}>{selected.status}</span>
              </div>

              <div className="configuration-meta">
                <span>Version <strong>{selected.version}</strong></span>
                <span>Revisions <strong>{revisions.length}</strong></span>
                <span>Created <strong>{date(selected.created_at)}</strong></span>
              </div>

              <div className="inline-actions configuration-actions">
                {selected.status === "active" && <button className="quiet-button" disabled={saving} onClick={beginRevision}>＋ New revision</button>}
                <button className="quiet-button" disabled={saving} onClick={() => void changeStatus()}>{selected.status === "active" ? "Archive" : "Reactivate"}</button>
                <button className="quiet-button" disabled={loading || saving} onClick={() => void refresh()}>Reload from server</button>
              </div>

              <section className="configuration-section">
                <div className="panel-toolbar">
                  <div><h3>Current revision</h3><p>{currentRevision ? `Revision ${currentRevision.revision_number} · ${currentRevision.change_summary || "No change summary"}` : "Current revision details"}</p></div>
                </div>
                {currentRevision ? (
                  <pre className="configuration-json">{pretty(currentRevision.definition)}</pre>
                ) : (
                  <div className="empty-state">Loading current revision details, or no revision is available.</div>
                )}
              </section>

              <section className="configuration-section">
                <div className="panel-toolbar">
                  <div><h3>Revision history</h3><p>Select a revision to inspect it or restore it as a new revision.</p></div>
                  <span className="workspace-count">{revisions.length} revisions</span>
                </div>
                <div className="configuration-revisions">
                  {revisions.map(revision => (
                    <article className={`configuration-revision ${selectedRevision?.revision_id === revision.revision_id ? "selected" : ""}`} key={revision.revision_id}>
                      <button className="configuration-revision-main" onClick={() => void inspectRevision(revision)}>
                        <strong>Revision {revision.revision_number}</strong>
                        <small>{date(revision.created_at)}</small>
                        <small>{revision.change_summary || "No change summary"}</small>
                        {revision.revision_id === selected.current_revision_id && <span className="revision-current">CURRENT</span>}
                      </button>
                      <div className="inline-actions">
                        <button className="quiet-button" onClick={() => void inspectRevision(revision)}>Inspect</button>
                        {selected.status === "active" && revision.revision_id !== selected.current_revision_id && (
                          <button className="quiet-button" disabled={saving} onClick={() => void restoreRevision(revision)}>Restore as new revision</button>
                        )}
                      </div>
                    </article>
                  ))}
                  {revisions.length === 0 && <div className="empty-state">No revision history returned.</div>}
                </div>
              </section>

              {selectedRevision && (
                <section className="configuration-section">
                  <div className="panel-toolbar">
                    <div><h3>Revision {selectedRevision.revision_number} details</h3><p>Immutable revision content and provenance.</p></div>
                    <button className="quiet-button" onClick={() => setSelectedRevision(null)}>Close</button>
                  </div>
                  <div className="configuration-meta">
                    <span>Schema <strong>{selectedRevision.schema_version}</strong></span>
                    <span>Hash <strong>{selectedRevision.content_hash.slice(0, 16)}…</strong></span>
                    <span>Parent <strong>{selectedRevision.parent_revision_id || "None"}</strong></span>
                  </div>
                  <pre className="configuration-json">{pretty(selectedRevision.definition)}</pre>
                  <details className="configuration-provenance">
                    <summary>Provenance metadata</summary>
                    <pre className="configuration-json">{pretty(selectedRevision.provenance)}</pre>
                  </details>
                </section>
              )}
            </>
          ) : (
            <div className="configuration-empty">
              <div className="eyebrow">CONFIGURATION REGISTRY</div>
              <h2>Select a configuration</h2>
              <p>Choose an item on the left, or create a new versioned configuration.</p>
              <button className="quiet-button" onClick={beginCreate}>Create configuration</button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
