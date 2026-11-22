import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./style.css";
import { AgentsWorkspace, MemoryWorkspace, HardwareWorkspace, ExperimentsWorkspace } from "./Workspaces";

type Conversation = { id: string; title: string; updated_at?: string; message_count?: number };
type Message = { role: "user" | "assistant"; content: string; created_at?: string };
type Health = { status: string; provider: string; model: string; endpoint: string; backend_started_at?: string; backend_revision?: string; backend_build_id?: string | null; backend_dirty?: boolean | null; build?: { backend_started_at?: string; backend_revision?: string; backend_build_id?: string | null; backend_dirty?: boolean | null } };
type StreamEvent = { event: string; data: unknown };
const API = "http://127.0.0.1:8765/api/v1";
const FRONTEND_BUILD_TIME = __BUILD_TIME__;
const FRONTEND_BUILD_COMMIT = __BUILD_COMMIT__;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API + path, init);
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try { const body = await response.json(); detail = body.detail || detail; } catch { /* non-JSON error */ }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function parseSseFrame(frame: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  const raw = data.join("\n");
  try { return { event, data: JSON.parse(raw) }; }
  catch { return { event, data: raw }; }
}


function formatBuildTime(value: string): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleString();
}

function Markdown({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    a: ({ href, children, ...props }) => <a href={href} target="_blank" rel="noreferrer" {...props}>{children}</a>,
    pre: ({ children }) => <pre className="code-block">{children}</pre>,
    code: ({ className, children, ...props }) => {
      const block = Boolean(className);
      return block
        ? <code className={className} {...props}>{children}</code>
        : <code className="inline-code" {...props}>{children}</code>;
    },
    table: ({ children }) => <div className="table-wrap"><table>{children}</table></div>,
  }}>{content}</ReactMarkdown>;
}

export default function App() {
  const [view, setView] = useState<"chat" | "agents" | "memory" | "hardware" | "experiments">("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<"connecting" | "connected" | "offline">("connecting");
  const [health, setHealth] = useState<Health | null>(null);
  const [search, setSearch] = useState("");
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const activeRef = useRef<string | null>(null);

  const refreshConversations = useCallback(async (query = search) => {
    const params = new URLSearchParams({ limit: "100" });
    if (query.trim()) params.set("q", query.trim());
    const items = await request<Conversation[]>(`/conversations?${params.toString()}`);
    setConversations(items);
  }, [search]);

  const openConversation = useCallback(async (id: string) => {
    setLoadingMessages(true);
    setError("");
    try {
      const rows = await request<Message[]>(`/conversations/${encodeURIComponent(id)}/messages`);
      activeRef.current = id;
      setActive(id);
      setMessages(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoadingMessages(false); }
  }, []);

  const createConversation = useCallback(async () => {
    try {
      const conversation = await request<Conversation>("/conversations", { method: "POST" });
      activeRef.current = conversation.id;
      setActive(conversation.id);
      setMessages([]);
      setDraft("");
      await refreshConversations();
      draftRef.current?.focus();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [refreshConversations]);

  const healthInFlight = useRef(false);
  const refreshHealth = useCallback(async () => {
    if (healthInFlight.current) return;
    healthInFlight.current = true;
    try {
      const info = await request<Health>("/health");
      setHealth(info);
      setStatus("connected");
      return info;
    } catch {
      setHealth(null);
      setStatus("offline");
      return null;
    } finally {
      healthInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const guardedRefresh = async () => {
      if (!alive) return;
      const info = await refreshHealth();
      if (alive && info) {
        try { await refreshConversations(""); } catch { /* keep the last conversation list */ }
      }
    };
    void guardedRefresh();
    const interval = window.setInterval(() => { void refreshHealth(); }, 15000);
    const onFocus = () => { void refreshHealth(); };
    window.addEventListener("focus", onFocus);
    return () => {
      alive = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshHealth, refreshConversations]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      refreshConversations(search).catch(e => setError(e instanceof Error ? e.message : String(e)));
    }, 180);
    return () => window.clearTimeout(handle);
  }, [search, refreshConversations]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!busy) void createConversation();
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [busy, createConversation]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setError("");
    let conversationId = activeRef.current;
    try {
      if (!conversationId) {
        const created = await request<Conversation>("/conversations", { method: "POST" });
        conversationId = created.id;
        activeRef.current = conversationId;
        setActive(conversationId);
      }
      setDraft("");
      setBusy(true);
      setMessages(previous => [...previous, { role: "user", content: text }, { role: "assistant", content: "" }]);
      const response = await fetch(API + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ conversation_id: conversationId, message: text }),
      });
      if (!response.ok || !response.body) {
        let detail = "Chat request failed";
        try { const body = await response.json(); detail = body.detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const handleFrame = (frame: string) => {
        const event = parseSseFrame(frame);
        if (!event) return;
        if (event.event === "token") {
          const token = typeof event.data === "string" ? event.data : String(event.data ?? "");
          setMessages(previous => {
            const next = [...previous];
            const last = next[next.length - 1];
            if (last?.role === "assistant") next[next.length - 1] = { ...last, content: last.content + token };
            return next;
          });
        } else if (event.event === "error") {
          const data = event.data as { message?: string };
          throw new Error(data?.message || "Evo encountered an error");
        }
      };
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) handleFrame(frame);
        if (done) break;
      }
      if (buffer.trim()) handleFrame(buffer);
      // Reconcile with the durable transcript after the stream closes. The
      // database is authoritative if a provider emits unusual chunk framing.
      if (conversationId && activeRef.current === conversationId) {
        const persisted = await request<Message[]>(`/conversations/${encodeURIComponent(conversationId)}/messages`);
        setMessages(persisted);
      }
      await refreshConversations();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      setMessages(previous => {
        const next = [...previous];
        if (next[next.length - 1]?.role === "assistant" && !next[next.length - 1].content) next.pop();
        return next;
      });
    } finally {
      setBusy(false);
      refreshConversations().catch(() => undefined);
    }
  }

  async function renameConversation(conversation: Conversation) {
    const title = window.prompt("Rename conversation", conversation.title);
    if (title === null || !title.trim() || title.trim() === conversation.title) return;
    try {
      await request(`/conversations/${encodeURIComponent(conversation.id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }),
      });
      await refreshConversations();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  async function removeConversation(conversation: Conversation) {
    if (!window.confirm(`Delete “${conversation.title}”? This also deletes its messages.`)) return;
    try {
      await request(`/conversations/${encodeURIComponent(conversation.id)}`, { method: "DELETE" });
      if (activeRef.current === conversation.id) {
        activeRef.current = null; setActive(null); setMessages([]);
      }
      await refreshConversations();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  async function copyMessage(index: number, content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(index);
      window.setTimeout(() => setCopied(current => current === index ? null : current), 1400);
    } catch { setError("Clipboard access was denied by the browser."); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">E</div><div><strong>Evo</strong><small>PERSONAL AI WORKSPACE</small></div></div>
      <button className="new-chat" onClick={createConversation} disabled={busy}>＋ <span>New conversation</span><kbd>⌘ K</kbd></button>
      <div className="nav-label">WORKSPACE</div>
      <button className={"nav-item " + (view === "chat" ? "selected" : "")} onClick={() => setView("chat")}><span className="nav-icon">◫</span> Chat {view === "chat" && <span className="nav-current">CURRENT</span>}</button>
      <button className={"nav-item " + (view === "agents" ? "selected" : "")} onClick={() => setView("agents")}><span className="nav-icon">⌘</span> Agents {view === "agents" && <span className="nav-current">CURRENT</span>}</button>
      <button className={"nav-item " + (view === "memory" ? "selected" : "")} onClick={() => setView("memory")}><span className="nav-icon">◈</span> Memory {view === "memory" && <span className="nav-current">CURRENT</span>}</button>
      <button className={"nav-item " + (view === "hardware" ? "selected" : "")} onClick={() => setView("hardware")}><span className="nav-icon">▥</span> Hardware {view === "hardware" && <span className="nav-current">CURRENT</span>}</button>
      <button className={"nav-item " + (view === "experiments" ? "selected" : "")} onClick={() => setView("experiments")}><span className="nav-icon">⌁</span> Experiments {view === "experiments" && <span className="nav-current">CURRENT</span>}</button>
      <div className="history-head"><span>CONVERSATIONS</span><span>{conversations.length}</span></div>
      <div className="search-wrap"><span>⌕</span><input aria-label="Search conversations" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search chats…" /></div>
      <div className="history">
        {conversations.map(conversation => <div key={conversation.id} className={active === conversation.id ? "history-row active" : "history-row"}>
          <button className="history-item" onClick={() => openConversation(conversation.id)} disabled={busy}>
            <span className="history-title">{conversation.title}</span>
            <small>{conversation.message_count ?? 0} messages</small>
          </button>
          <div className="history-actions">
            <button aria-label={`Rename ${conversation.title}`} title="Rename" onClick={() => renameConversation(conversation)}>···</button>
            <button aria-label={`Delete ${conversation.title}`} title="Delete" onClick={() => removeConversation(conversation)}>×</button>
          </div>
        </div>)}
        {conversations.length === 0 && <div className="history-empty">{search ? "No matching conversations" : "Your conversations will appear here"}</div>}
      </div>
      <div className="sidebar-bottom"><span className={status === "connected" ? "status-dot" : "status-dot offline"}/><div><strong>{status === "connected" ? "Evo connected" : status === "offline" ? "API unavailable" : "Connecting…"}</strong><small>{health?.provider || "Local provider"}{health?.model ? ` · ${health.model}` : ""}</small></div></div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>{view === "chat" ? "Chat" : view === "agents" ? "Agents" : view === "memory" ? "Memory" : view === "hardware" ? "Hardware" : "Experiments"}</strong></div>
        <div className="topbar-right"><span className="privacy-label"><span/> LOCAL API</span><div className="model-pill">{health?.model || "Model unavailable"}</div><div className="build-pill" title={`Frontend build: ${FRONTEND_BUILD_TIME || "unknown"} (${FRONTEND_BUILD_COMMIT || "unknown"})\nBackend started: ${health?.backend_started_at || health?.build?.backend_started_at || "unknown"}\nBackend revision: ${health?.backend_revision || health?.build?.backend_revision || "unknown"}${(health?.backend_dirty ?? health?.build?.backend_dirty) ? " (dirty)" : ""}`}>{import.meta.env.DEV ? "FE DEV SERVER" : `FE ${formatBuildTime(FRONTEND_BUILD_TIME)}`} <span className="build-separator">/</span> {health ? (health.backend_revision || health.build?.backend_revision || "BE unknown") : "BE unavailable"}</div></div>
      </header>
      {view === "chat" ? <section className="chat-area">
        {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
        {loadingMessages ? <div className="loading-state">Loading conversation…</div> : messages.length === 0 ? <div className="welcome">
          <div className="welcome-icon">E</div><div className="eyebrow">YOUR PRIVATE WORKSPACE</div><h1>What are we working on?</h1>
          <p>Ask a question, explore an idea, or continue building Evo.</p>
          <div className="welcome-note"><span>✳</span> Persistent conversations · Local-first · You stay in control</div>
        </div> : <div className="message-list">
          {messages.map((message, index) => <article key={`${message.created_at || index}-${index}`} className={`message ${message.role}`}>
            <div className="avatar">{message.role === "user" ? "Y" : "E"}</div>
            <div className="message-body">
              <div className="message-heading"><span>{message.role === "user" ? "You" : "Evo"}</span>
                {message.role === "assistant" && message.content && <button className="copy-button" onClick={() => copyMessage(index, message.content)}>{copied === index ? "Copied" : "Copy"}</button>}
              </div>
              <div className="message-content">{message.content ? <Markdown content={message.content}/> : busy && index === messages.length - 1 ? <span className="thinking"><i/><i/><i/> Thinking</span> : null}</div>
            </div>
          </article>)}<div ref={endRef}/>
        </div>}
        <div className="composer-wrap">
          <div className="composer"><textarea ref={draftRef} aria-label="Message Evo" value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} placeholder="Message Evo…" rows={2} disabled={status !== "connected" || busy}/>
            <button className="send-button" onClick={() => void send()} disabled={busy || !draft.trim() || status !== "connected"} aria-label="Send message">↑</button>
          </div>
          <div className="composer-footer"><span>Enter to send <b>·</b> Shift + Enter for a new line</span><span>Generation cannot yet be stopped from the desktop client</span></div>
        </div>
      </section> : view === "agents" ? <AgentsWorkspace/> : view === "memory" ? <MemoryWorkspace/> : view === "hardware" ? <HardwareWorkspace/> : <ExperimentsWorkspace/>}
    </main>
  </div>;
}
