from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import threading
import uuid

def utc_now():
    return datetime.now(timezone.utc).isoformat()

class EvoStore:
    """Persistent state store. Uses SQLite WAL and FTS5 when the SQLite build supports it."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self.fts_available = False
        self._initialize()

    def _initialize(self):
        with self.lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL
                REFERENCES conversations(id) ON DELETE CASCADE,
              role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
              content TEXT NOT NULL, created_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,id);
            CREATE TABLE IF NOT EXISTS memories (
              id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general',
              tags_json TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'user',
              confidence REAL NOT NULL DEFAULT 1.0, status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_accessed_at TEXT,
              access_count INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_memories_status_category ON memories(status,category);
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open', priority INTEGER NOT NULL DEFAULT 3,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status,priority,created_at);
            CREATE TABLE IF NOT EXISTS research_documents (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, content TEXT NOT NULL,
              source_type TEXT NOT NULL DEFAULT 'manual', captured_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS agent_runs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
              started_at TEXT NOT NULL, finished_at TEXT, summary TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS tool_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, tool_name TEXT NOT NULL,
              input_json TEXT NOT NULL, output_summary TEXT, status TEXT NOT NULL,
              created_at TEXT NOT NULL);
            """)
            try:
                self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, category, tags)")
                self.fts_available = True
            except sqlite3.OperationalError:
                self.fts_available = False
            self.db.commit()

    def create_conversation(self, title="New conversation"):
        cid, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                            (cid, title[:120], now, now))
            self.db.commit()
        return cid

    def list_conversations(self, limit=20):
        with self.lock:
            return self.db.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                                    (max(1, limit),)).fetchall()

    def add_message(self, conversation_id, role, content, metadata=None):
        now = utc_now()
        with self.lock:
            cur = self.db.execute("INSERT INTO messages(conversation_id,role,content,created_at,metadata_json) VALUES(?,?,?,?,?)",
                                  (conversation_id, role, content, now, json.dumps(metadata or {}, ensure_ascii=False)))
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            self.db.commit()
            return cur.lastrowid

    def get_messages(self, conversation_id, limit=16):
        with self.lock:
            rows = self.db.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                                   (conversation_id, max(1, limit))).fetchall()
        return list(reversed(rows))

    def add_memory(self, content, category="general", tags=None, source="user", confidence=1.0, metadata=None):
        content = content.strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        mid, now = str(uuid.uuid4()), utc_now()
        tags = tags or []
        with self.lock:
            self.db.execute("""INSERT INTO memories(id,content,category,tags_json,source,confidence,created_at,updated_at,metadata_json)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (mid, content, category, json.dumps(tags), source, float(confidence), now, now,
                             json.dumps(metadata or {}, ensure_ascii=False)))
            if self.fts_available:
                self.db.execute("INSERT INTO memories_fts(memory_id,content,category,tags) VALUES(?,?,?,?)",
                                (mid, content, category, " ".join(tags)))
            self.db.commit()
        return mid

    def search_memories(self, query, limit=8, category=None):
        terms = [part.strip(" \t\r\n.,!?;:\"'()[]{}") for part in query.split()]
        terms = [term for term in terms if len(term) > 1][:12]
        if not terms:
            return []
        with self.lock:
            rows = []
            if self.fts_available:
                match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
                sql = """SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.memory_id
                         WHERE memories_fts MATCH ? AND m.status='active'"""
                params = [match]
                if category:
                    sql += " AND m.category=?"; params.append(category)
                sql += " ORDER BY bm25(memories_fts),m.confidence DESC LIMIT ?"; params.append(max(1,limit))
                try:
                    rows = self.db.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                clauses = " OR ".join("content LIKE ?" for _ in terms)
                params = [f"%{term}%" for term in terms]
                sql = f"SELECT * FROM memories WHERE status='active' AND ({clauses})"
                if category:
                    sql += " AND category=?"; params.append(category)
                sql += " ORDER BY confidence DESC,updated_at DESC LIMIT ?"; params.append(max(1,limit))
                rows = self.db.execute(sql, params).fetchall()
            if rows:
                self.db.executemany("UPDATE memories SET access_count=access_count+1,last_accessed_at=? WHERE id=?",
                                    [(utc_now(), row["id"]) for row in rows])
                self.db.commit()
            return rows

    def list_memories(self, limit=50):
        with self.lock:
            return self.db.execute("SELECT * FROM memories WHERE status='active' ORDER BY updated_at DESC LIMIT ?",
                                    (max(1,limit),)).fetchall()

    def archive_memory(self, memory_id):
        with self.lock:
            cur = self.db.execute("UPDATE memories SET status='archived',updated_at=? WHERE id=?",
                                  (utc_now(), memory_id))
            self.db.commit()
            return cur.rowcount == 1

    def add_task(self, title, description="", priority=3, due_at=None):
        tid, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("INSERT INTO tasks(id,title,description,priority,created_at,updated_at,due_at) VALUES(?,?,?,?,?,?,?)",
                            (tid, title.strip(), description, max(1,min(5,int(priority))), now, now, due_at))
            self.db.commit()
        return tid

    def list_tasks(self, status=None, limit=100):
        with self.lock:
            if status:
                return self.db.execute("SELECT * FROM tasks WHERE status=? ORDER BY priority,created_at LIMIT ?",
                                        (status,max(1,limit))).fetchall()
            return self.db.execute("SELECT * FROM tasks ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,priority,created_at LIMIT ?",
                                   (max(1,limit),)).fetchall()

    def update_task_status(self, task_id, status):
        if status not in {"open","in_progress","blocked","done","cancelled"}:
            raise ValueError("Invalid task status")
        with self.lock:
            cur = self.db.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?",
                                  (status,utc_now(),task_id))
            self.db.commit()
            return cur.rowcount == 1

    def add_research_document(self, title, content, url=None, source_type="manual", metadata=None):
        if not title.strip() or not content.strip():
            raise ValueError("Research title and content are required")
        document_id, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("""INSERT INTO research_documents(id,title,url,content,source_type,captured_at,metadata_json)
                               VALUES(?,?,?,?,?,?,?)""",
                            (document_id,title.strip(),url,content,source_type,now,
                             json.dumps(metadata or {},ensure_ascii=False)))
            self.db.commit()
        return document_id

    def search_research(self, query, limit=10):
        terms = [term.strip(" \\t\\r\\n.,!?;:\"'()[]{}") for term in query.split()]
        terms = [term for term in terms if len(term)>1][:12]
        if not terms:
            return []
        clauses = " OR ".join("(title LIKE ? OR content LIKE ?)" for _ in terms)
        params = []
        for term in terms:
            params.extend((f"%{term}%",f"%{term}%"))
        params.append(max(1,limit))
        with self.lock:
            return self.db.execute(f"SELECT * FROM research_documents WHERE {clauses} ORDER BY captured_at DESC LIMIT ?",
                                   params).fetchall()

    def close(self):
        with self.lock:
            self.db.close()
