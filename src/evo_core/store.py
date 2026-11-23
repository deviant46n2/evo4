from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3
import threading
import uuid

def utc_now():
    return datetime.now(timezone.utc).isoformat()

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})

def _like_pattern(term):
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"

class EvoStore:
    """Persistent state store. Uses SQLite WAL and FTS5 when the SQLite build supports it."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
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
            CREATE TABLE IF NOT EXISTS memory_relations (
              id TEXT PRIMARY KEY, source_memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
              target_memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
              relation_type TEXT NOT NULL CHECK(relation_type IN ('supersedes','contradicts','supports')),
              evidence TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
              CHECK(source_memory_id <> target_memory_id));
            CREATE INDEX IF NOT EXISTS idx_memory_relations_source ON memory_relations(source_memory_id);
            CREATE INDEX IF NOT EXISTS idx_memory_relations_target ON memory_relations(target_memory_id);
            CREATE TABLE IF NOT EXISTS schema_migrations (
              name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_candidates (
              id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general',
              source TEXT NOT NULL, conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
              project_id TEXT, workspace_id TEXT,
              confidence REAL NOT NULL DEFAULT 0.5, status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL, reviewed_at TEXT, memory_id TEXT REFERENCES memories(id));
            CREATE INDEX IF NOT EXISTS idx_memory_candidates_status ON memory_candidates(status,created_at);
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open', priority INTEGER NOT NULL DEFAULT 3,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status,priority,created_at);
            CREATE TABLE IF NOT EXISTS lessons (
              id TEXT PRIMARY KEY, trigger_text TEXT NOT NULL, lesson TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT 'general', source TEXT NOT NULL DEFAULT 'user',
              confidence REAL NOT NULL DEFAULT 1.0, status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL, access_count INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS idx_lessons_status_category ON lessons(status,category);
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
            CREATE TABLE IF NOT EXISTS run_feedback (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
              outcome TEXT NOT NULL CHECK(outcome IN ('success','partial','failure')),
              feedback TEXT NOT NULL DEFAULT '', lesson_id TEXT REFERENCES lessons(id) ON DELETE SET NULL,
              created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_run_feedback_run ON run_feedback(run_id,created_at);
            """)
            scope_columns = {
                "conversations": ("project_id", "workspace_id"),
                "memories": ("project_id", "workspace_id"),
                "memory_candidates": ("project_id", "workspace_id"),
                "lessons": ("project_id", "workspace_id"),
                "research_documents": ("project_id", "workspace_id"),
                "tasks": ("project_id", "workspace_id"),
            }
            for table, columns in scope_columns.items():
                existing = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
                for column in columns:
                    if column not in existing:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            try:
                self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, category, tags)")
                self.fts_available = True
            except sqlite3.OperationalError:
                self.fts_available = False
            # Older Evo builds stored supersession edges from the obsolete
            # record to its replacement, while retrieval interprets edges as
            # current record -> superseded record. Normalize existing history
            # once so provenance remains accurate after this upgrade.
            migration = "supersedes_direction_current_to_old_v1"
            applied = self.db.execute(
                "SELECT 1 FROM schema_migrations WHERE name=?", (migration,)
            ).fetchone()
            if not applied:
                self.db.execute(
                    """UPDATE memory_relations
                       SET source_memory_id=target_memory_id,
                           target_memory_id=source_memory_id
                       WHERE relation_type='supersedes'"""
                )
                self.db.execute(
                    "INSERT INTO schema_migrations(name,applied_at) VALUES(?,?)",
                    (migration, utc_now()),
                )
            self.db.commit()

    def create_conversation(self, title="New conversation", project_id=None, workspace_id=None):
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        cid, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            try:
                self.db.execute("INSERT INTO conversations(id,title,created_at,updated_at,project_id,workspace_id) VALUES(?,?,?,?,?,?)",
                                (cid, title[:120], now, now, project_id, workspace_id))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return cid

    def list_conversations(self, limit=20, query=None):
        with self.lock:
            if query and query.strip():
                pattern = _like_pattern(query.strip())
                return self.db.execute(
                    """SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count
                       FROM conversations c WHERE c.title LIKE ? ESCAPE '!'
                       OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id
                                  AND m.content LIKE ? ESCAPE '!')
                       ORDER BY c.updated_at DESC LIMIT ?""",
                    (pattern, pattern, max(1, min(int(limit), 500)))).fetchall()
            return self.db.execute(
                """SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count
                   FROM conversations c ORDER BY c.updated_at DESC LIMIT ?""",
                (max(1, min(int(limit), 500)),)).fetchall()

    def get_conversation(self, conversation_id):
        with self.lock:
            return self.db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()

    def rename_conversation(self, conversation_id, title):
        title = (title or "").strip()
        if not title:
            raise ValueError("Conversation title cannot be empty")
        if len(title) > 120:
            raise ValueError("Conversation title cannot exceed 120 characters")
        with self.lock:
            cur = self.db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?",
                                  (title, utc_now(), conversation_id))
            self.db.commit()
            return cur.rowcount == 1

    def delete_conversation(self, conversation_id):
        with self.lock:
            cur = self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            self.db.commit()
            return cur.rowcount == 1

    def validate_scope(self, project_id=None, workspace_id=None):
        if project_id is not None:
            if not isinstance(project_id, str) or not project_id.strip():
                raise ValueError("project_id must be None or a non-empty string")
            project_id = project_id.strip()
        if workspace_id is not None:
            if not isinstance(workspace_id, str) or not workspace_id.strip():
                raise ValueError("workspace_id must be None or a non-empty string")
            workspace_id = workspace_id.strip()
        if workspace_id is not None and project_id is None:
            raise ValueError("workspace_id requires project_id")
        from .scope_validation import validate_scope
        validate_scope(self, project_id, workspace_id)

    def add_message(self, conversation_id, role, content, metadata=None):
        now = utc_now()
        with self.lock:
            try:
                cur = self.db.execute("INSERT INTO messages(conversation_id,role,content,created_at,metadata_json) VALUES(?,?,?,?,?)",
                                      (conversation_id, role, content, now, json.dumps(metadata or {}, ensure_ascii=False)))
                if role == "user":
                    row = self.db.execute("SELECT title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
                    if row and row["title"] == "New conversation":
                        title = " ".join(content.strip().split())
                        if len(title) > 57:
                            title = title[:54].rstrip() + "..."
                        if title:
                            self.db.execute("UPDATE conversations SET title=? WHERE id=?", (title, conversation_id))
                self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
                self.db.commit()
                return cur.lastrowid
            except Exception:
                self.db.rollback()
                raise

    def get_messages(self, conversation_id, limit=16):
        with self.lock:
            rows = self.db.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                                   (conversation_id, max(1, limit))).fetchall()
        return list(reversed(rows))

    def add_memory(self, content, category="general", tags=None, source="user", confidence=1.0, metadata=None,
                   project_id=None, workspace_id=None):
        content = content.strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        mid, now = str(uuid.uuid4()), utc_now()
        tags = tags or []
        with self.lock:
            self.db.execute("""INSERT INTO memories(id,content,category,tags_json,source,confidence,created_at,updated_at,metadata_json,project_id,workspace_id)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (mid, content, category, json.dumps(tags), source, float(confidence), now, now,
                             json.dumps(metadata or {}, ensure_ascii=False), project_id, workspace_id))
            if self.fts_available:
                self.db.execute("INSERT INTO memories_fts(memory_id,content,category,tags) VALUES(?,?,?,?)",
                                (mid, content, category, " ".join(tags)))
            self.db.commit()
        return mid

    def search_memories(self, query, limit=8, category=None, record_access=True):
        """Hybrid lexical retrieval with inspectable evidence; embeddings are not used."""
        raw_query = (query or "").strip()
        if not raw_query:
            return []
        stop = {"a","an","and","are","as","at","be","been","by","can","could","did","do","does",
                "for","from","had","has","have","how","i","in","into","is","it","its","me","my",
                "of","on","or","our","please","should","that","the","their","them","there","this",
                "to","use","used","using","was","we","what","when","where","which","who","why",
                "will","with","would","you","your"}
        tokens = []
        for token in re.findall(r"[a-z0-9]+(?:[._'%-][a-z0-9]+)*%?", raw_query.casefold()):
            if len(token) > 1 and token not in stop and token not in tokens:
                tokens.append(token)
        tokens = tokens[:24]
        if not tokens:
            return []
        bounded = min(max(int(limit), 1), 100)
        pool_size = min(max(bounded * 12, 60), 240)
        with self.lock:
            candidates, fts_ranks = {}, {}
            if self.fts_available:
                match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
                sql = """SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.memory_id
                         WHERE memories_fts MATCH ? AND m.status='active'"""
                params = [match]
                if category:
                    sql += " AND m.category=?"; params.append(category)
                sql += " ORDER BY bm25(memories_fts),m.confidence DESC LIMIT ?"
                params.append(pool_size)
                try:
                    for rank, row in enumerate(self.db.execute(sql, params).fetchall(), 1):
                        candidates[row["id"]] = row
                        fts_ranks[row["id"]] = rank
                except sqlite3.OperationalError:
                    pass
            clauses, params = [], []
            for token in tokens:
                pattern = _like_pattern(token)
                clauses.append("(content LIKE ? ESCAPE '!' OR category LIKE ? ESCAPE '!' OR tags_json LIKE ? ESCAPE '!')")
                params.extend((pattern, pattern, pattern))
            sql = "SELECT * FROM memories WHERE status='active' AND (" + " OR ".join(clauses) + ")"
            if category:
                sql += " AND category=?"; params.append(category)
            sql += " ORDER BY updated_at DESC LIMIT ?"; params.append(pool_size)
            for row in self.db.execute(sql, params).fetchall():
                candidates.setdefault(row["id"], row)

            query_set = set(tokens)
            phrase = " ".join(tokens)
            ranked = []
            for memory_id, row in candidates.items():
                content = row["content"].casefold()
                try:
                    tags = json.loads(row["tags_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    tags = []
                tokenize = lambda value: set(re.findall(r"[a-z0-9]+(?:[._'%-][a-z0-9]+)*%?", value.casefold()))
                content_hits = query_set & tokenize(content)
                tag_hits = query_set & tokenize(" ".join(str(tag) for tag in tags))
                category_hits = query_set & tokenize(str(row["category"] or ""))
                matched = content_hits | tag_hits | category_hits
                if not matched:
                    continue
                coverage = len(matched) / len(query_set)
                content_coverage = len(content_hits) / len(query_set)
                tag_coverage = len(tag_hits) / len(query_set)
                exact = bool(phrase and phrase in content)
                rank = fts_ranks.get(memory_id)
                fts_bonus = 1.0 / (60 + rank) if rank else 0.0
                confidence = max(0.0, min(1.0, float(row["confidence"] or 0.0)))
                score = coverage*.62 + content_coverage*.18 + tag_coverage*.08 + (0.10 if exact else 0) + fts_bonus*3 + confidence*.02
                reasons = []
                if content_hits: reasons.append("content: " + ", ".join(sorted(content_hits)))
                if tag_hits: reasons.append("tags: " + ", ".join(sorted(tag_hits)))
                if category_hits: reasons.append("category: " + ", ".join(sorted(category_hits)))
                if exact: reasons.append("exact phrase")
                item = dict(row)
                item.update(retrieval_score=round(min(score,1.0),6), relevance=round(min(score,1.0),6), retrieval_coverage=round(coverage,4),
                            retrieval_matched_terms=sorted(matched),
                            retrieval_reason="; ".join(reasons) or "lexical candidate",
                            retrieval_method="hybrid-fts-like" if rank else "lexical-like")
                ranked.append(item)
            ranked.sort(key=lambda item:(item["retrieval_score"],float(item["confidence"] or 0),item["updated_at"]),reverse=True)
            selected = ranked[:bounded]
            if selected and record_access:
                now = utc_now()
                try:
                    self.db.executemany("UPDATE memories SET access_count=access_count+1,last_accessed_at=? WHERE id=?",
                                        [(now,item["id"]) for item in selected])
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            return selected

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

    def supersede_memory(self, memory_id, content, category=None, tags=None,
                         source="user", confidence=1.0, reason=""):
        content=(content or "").strip()
        if not content:
            raise ValueError("Replacement memory content cannot be empty")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        new_id,relation_id,now=str(uuid.uuid4()),str(uuid.uuid4()),utc_now()
        with self.lock:
            try:
                old=self.db.execute("SELECT * FROM memories WHERE id=? AND status='active'",
                                    (memory_id,)).fetchone()
                if not old:
                    raise ValueError("Active memory not found")
                metadata={"supersedes_memory_id":memory_id}
                if reason.strip():
                    metadata["supersession_reason"]=reason.strip()
                self.db.execute(
                    """INSERT INTO memories(id,content,category,tags_json,source,confidence,created_at,updated_at,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (new_id,content,category or old["category"],json.dumps(tags or []),source,
                     float(confidence),now,now,json.dumps(metadata,ensure_ascii=False)))
                if self.fts_available:
                    self.db.execute("INSERT INTO memories_fts(memory_id,content,category,tags) VALUES(?,?,?,?)",
                                    (new_id,content,category or old["category"]," ".join(tags or [])))
                self.db.execute(
                    """INSERT INTO memory_relations(id,source_memory_id,target_memory_id,relation_type,evidence,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (relation_id,new_id,memory_id,"supersedes",reason.strip(),now))
                self.db.execute("UPDATE memories SET status='superseded',updated_at=? WHERE id=?",
                                (now,memory_id))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return new_id

    def relate_memories(self, source_id, target_id, relation_type, evidence=""):
        if relation_type not in {"contradicts","supports"}:
            raise ValueError("relation_type must be contradicts or supports")
        if source_id==target_id:
            raise ValueError("A memory cannot be related to itself")
        relation_id,now=str(uuid.uuid4()),utc_now()
        with self.lock:
            try:
                found=self.db.execute(
                    "SELECT COUNT(*) FROM memories WHERE id IN (?,?)",(source_id,target_id)).fetchone()[0]
                if found!=2:
                    raise ValueError("Both memory IDs must exist")
                self.db.execute(
                    """INSERT INTO memory_relations(id,source_memory_id,target_memory_id,relation_type,evidence,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (relation_id,source_id,target_id,relation_type,(evidence or "").strip(),now))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return relation_id

    def get_memory_relations(self, memory_ids):
        ids=list(dict.fromkeys(memory_ids or []))
        if not ids:
            return []
        placeholders=",".join("?" for _ in ids)
        sql=f"""SELECT r.*,s.content AS source_content,t.content AS target_content
                FROM memory_relations r
                JOIN memories s ON s.id=r.source_memory_id
                JOIN memories t ON t.id=r.target_memory_id
                WHERE r.source_memory_id IN ({placeholders}) OR r.target_memory_id IN ({placeholders})
                ORDER BY r.created_at DESC"""
        with self.lock:
            return self.db.execute(sql,ids+ids).fetchall()

    def search_memory_relations(self, query, limit=5):
        terms=[term.strip(" \\t\\r\\n.,!?;:\"'()[]{}") for term in query.split()]
        terms=[term for term in terms if len(term)>1][:12]
        if not terms:
            return []
        clauses=[]
        where_params=[]
        score_parts=[]
        score_params=[]
        for term in terms:
            pattern=_like_pattern(term)
            clauses.append("(s.content LIKE ? ESCAPE '!' OR t.content LIKE ? ESCAPE '!' OR r.evidence LIKE ? ESCAPE '!')")
            where_params.extend((pattern,pattern,pattern))
            score_parts.append("(CASE WHEN s.content LIKE ? ESCAPE '!' THEN 2 ELSE 0 END + "
                               "CASE WHEN t.content LIKE ? ESCAPE '!' THEN 2 ELSE 0 END + "
                               "CASE WHEN r.evidence LIKE ? ESCAPE '!' THEN 1 ELSE 0 END)")
            score_params.extend((pattern,pattern,pattern))
        params=score_params+where_params+[max(1,min(int(limit),50))]
        sql=f"""SELECT r.*,s.content AS source_content,t.content AS target_content,
                ({' + '.join(score_parts)}) AS relevance
                FROM memory_relations r
                JOIN memories s ON s.id=r.source_memory_id
                JOIN memories t ON t.id=r.target_memory_id
                WHERE {' OR '.join(clauses)}
                ORDER BY relevance DESC,r.created_at DESC LIMIT ?"""
        with self.lock:
            return self.db.execute(sql,params).fetchall()

    def add_task(self, title, description="", priority=3, due_at=None, project_id=None, workspace_id=None):
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        tid, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("INSERT INTO tasks(id,title,description,priority,created_at,updated_at,due_at,project_id,workspace_id) VALUES(?,?,?,?,?,?,?,?,?)",
                            (tid, title.strip(), description, max(1,min(5,int(priority))), now, now, due_at, project_id, workspace_id))
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

    def propose_memory(self, content, category="general", source="conversation", conversation_id=None, confidence=0.5,
                       project_id=None, workspace_id=None):
        content = content.strip()
        if not content:
            raise ValueError("Candidate memory cannot be empty")
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        if conversation_id is not None:
            conversation = self.get_conversation(conversation_id)
            if conversation is None:
                raise ValueError("conversation_id does not refer to an existing conversation")
            if project_id is not None and project_id != conversation["project_id"]:
                raise ValueError("project_id does not match the source conversation")
            if workspace_id is not None and workspace_id != conversation["workspace_id"]:
                raise ValueError("workspace_id does not match the source conversation")
            if project_id is None:
                project_id = conversation["project_id"]
            if workspace_id is None:
                workspace_id = conversation["workspace_id"]
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        candidate_id, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            existing = self.db.execute(
                """SELECT id FROM memory_candidates
                   WHERE lower(content)=lower(?) AND status='pending'
                     AND project_id IS ? AND workspace_id IS ?""",
                (content, project_id, workspace_id)).fetchone()
            if existing:
                return existing["id"]
            self.db.execute("""INSERT INTO memory_candidates(id,content,category,source,conversation_id,project_id,workspace_id,confidence,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (candidate_id, content, category, source, conversation_id, project_id, workspace_id,
                             max(0.0, min(1.0, float(confidence))), now))
            self.db.commit()
        return candidate_id

    def list_memory_candidates(self, status="pending", limit=50):
        with self.lock:
            return self.db.execute("SELECT * FROM memory_candidates WHERE status=? ORDER BY created_at DESC LIMIT ?",
                                   (status,max(1,limit))).fetchall()

    def review_memory_candidate(self, candidate_id, accept):
        with self.lock:
            row = self.db.execute("SELECT * FROM memory_candidates WHERE id=? AND status='pending'",
                                  (candidate_id,)).fetchone()
            if not row:
                return None
            memory_id = None
            try:
                if accept:
                    memory_id = str(uuid.uuid4())
                    now = utc_now()
                    self.db.execute("""INSERT INTO memories(id,content,category,tags_json,source,confidence,created_at,updated_at,metadata_json,project_id,workspace_id)
                                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                    (memory_id, row["content"], row["category"], "[]", row["source"],
                                     row["confidence"], now, now, json.dumps({"candidate_id": candidate_id}),
                                     row["project_id"], row["workspace_id"]))
                    if self.fts_available:
                        self.db.execute("INSERT INTO memories_fts(memory_id,content,category,tags) VALUES(?,?,?,?)",
                                        (memory_id,row["content"],row["category"],""))
                self.db.execute("UPDATE memory_candidates SET status=?,reviewed_at=?,memory_id=? WHERE id=?",
                                ("accepted" if accept else "rejected",utc_now(),memory_id,candidate_id))
                self.db.commit()
                return memory_id if accept else False
            except Exception:
                self.db.rollback()
                raise

    def add_lesson(self, lesson, trigger_text="", category="general", source="user", confidence=1.0,
                   project_id=None, workspace_id=None):
        if not lesson.strip():
            raise ValueError("Lesson cannot be empty")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        lesson_id, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("""INSERT INTO lessons(id,trigger_text,lesson,category,source,confidence,created_at,project_id,workspace_id)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (lesson_id, trigger_text, lesson.strip(), category, source, float(confidence), now,
                             project_id, workspace_id))
            self.db.commit()
        return lesson_id

    def list_lessons(self, limit=50):
        with self.lock:
            return self.db.execute("SELECT * FROM lessons WHERE status='active' ORDER BY created_at DESC LIMIT ?",
                                   (max(1,limit),)).fetchall()

    def search_lessons(self, query, limit=5, category=None):
        terms=[term.strip(" \\t\\r\\n.,!?;:\"'()[]{}") for term in query.split()]
        terms=[term for term in terms if len(term)>1][:12]
        if not terms:
            return []
        clauses=[]
        where_params=[]
        score_parts=[]
        score_params=[]
        for term in terms:
            pattern=_like_pattern(term)
            clauses.append("(trigger_text LIKE ? ESCAPE '!' OR lesson LIKE ? ESCAPE '!')")
            where_params.extend((pattern,pattern))
            score_parts.append("(CASE WHEN trigger_text LIKE ? ESCAPE '!' THEN 3 ELSE 0 END + "
                               "CASE WHEN lesson LIKE ? ESCAPE '!' THEN 2 ELSE 0 END)")
            score_params.extend((pattern,pattern))
        sql=f"SELECT *,({' + '.join(score_parts)}) AS relevance FROM lessons WHERE status='active' AND ({' OR '.join(clauses)})"
        params=score_params+where_params
        if category:
            sql+=" AND category=?"; params.append(category)
        sql+=" ORDER BY relevance DESC,confidence DESC,created_at DESC LIMIT ?"; params.append(max(1,limit))
        with self.lock:
            rows=self.db.execute(sql,params).fetchall()
            if rows:
                self.db.executemany("UPDATE lessons SET access_count=access_count+1 WHERE id=?",
                                    [(row["id"],) for row in rows])
                self.db.commit()
            return rows

    def add_research_document(self, title, content, url=None, source_type="manual", metadata=None,
                             project_id=None, workspace_id=None):
        if not title.strip() or not content.strip():
            raise ValueError("Research title and content are required")
        from .scope_validation import validate_scope
        project_id, workspace_id = validate_scope(self, project_id, workspace_id)
        document_id, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("""INSERT INTO research_documents(id,title,url,content,source_type,captured_at,metadata_json,project_id,workspace_id)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (document_id, title.strip(), url, content, source_type, now,
                             json.dumps(metadata or {}, ensure_ascii=False), project_id, workspace_id))
            self.db.commit()
        return document_id

    def search_research(self, query, limit=10):
        terms = [term.strip(" \\t\\r\\n.,!?;:\"'()[]{}") for term in query.split()]
        terms = [term for term in terms if len(term)>1][:12]
        if not terms:
            return []
        clauses=[]
        where_params=[]
        score_parts=[]
        score_params=[]
        for term in terms:
            pattern=_like_pattern(term)
            clauses.append("(title LIKE ? ESCAPE '!' OR content LIKE ? ESCAPE '!')")
            where_params.extend((pattern,pattern))
            score_parts.append("(CASE WHEN title LIKE ? ESCAPE '!' THEN 3 ELSE 0 END + "
                               "CASE WHEN content LIKE ? ESCAPE '!' THEN 1 ELSE 0 END)")
            score_params.extend((pattern,pattern))
        params=score_params+where_params+[max(1,limit)]
        with self.lock:
            return self.db.execute(
                f"SELECT *,({' + '.join(score_parts)}) AS relevance FROM research_documents "
                f"WHERE {' OR '.join(clauses)} ORDER BY relevance DESC,captured_at DESC LIMIT ?",
                params).fetchall()

    def start_agent_run(self, kind, metadata=None):
        run_id, now = str(uuid.uuid4()), utc_now()
        with self.lock:
            self.db.execute("INSERT INTO agent_runs(id,kind,status,started_at,metadata_json) VALUES(?,?,?,?,?)",
                            (run_id,kind,"running",now,json.dumps(metadata or {},ensure_ascii=False)))
            self.db.commit()
        return run_id

    def finish_agent_run(self, run_id, status, summary=""):
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("Invalid agent run status")
        # Terminal outcomes are written once. Repeats are idempotent and a
        # conflicting terminal outcome is preserved instead of overwritten.
        with self.lock:
            cursor=self.db.execute(
                "UPDATE agent_runs SET status=?,finished_at=?,summary=? WHERE id=? "
                "AND status NOT IN ('completed','failed','cancelled','interrupted')",
                (status,utc_now(),summary,run_id))
            self.db.commit()
            return cursor.rowcount==1

    def apply_agent_run_decision(self, run_id, outcome, summary="", source="lifecycle"):
        """Mirror a durable finalization decision into the run record."""
        if outcome not in TERMINAL_RUN_STATUSES:
            raise ValueError("Invalid agent run status")
        with self.lock:
            row=self.db.execute("SELECT status FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return {"applied": False, "reason": "missing"}
            if row["status"] == outcome:
                return {"applied": False, "reason": "consistent"}
            if row["status"] in TERMINAL_RUN_STATUSES:
                return {"applied": False, "reason": "conflict", "existing": row["status"]}
            cursor=self.db.execute(
                "UPDATE agent_runs SET status=?,finished_at=?,summary=? WHERE id=? "
                "AND status NOT IN ('completed','failed','cancelled','interrupted')",
                (outcome,utc_now(),summary,run_id))
            self.db.commit()
            return {"applied": cursor.rowcount==1, "previous": row["status"]}

    def list_active_agent_runs(self):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM agent_runs WHERE status='running' ORDER BY started_at").fetchall()

    def update_agent_run_metadata(self, run_id, updates):
        if not isinstance(updates,dict):
            raise ValueError("Agent run metadata updates must be an object")
        with self.lock:
            row=self.db.execute("SELECT metadata_json FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return False
            try:
                metadata=json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata={}
            metadata.update(updates)
            self.db.execute("UPDATE agent_runs SET metadata_json=? WHERE id=?",
                            (json.dumps(metadata,ensure_ascii=False),run_id))
            self.db.commit()
            return True

    def record_tool_event(self, run_id, tool_name, arguments, output_summary, status):
        with self.lock:
            self.db.execute("""INSERT INTO tool_events(run_id,tool_name,input_json,output_summary,status,created_at)
                               VALUES(?,?,?,?,?,?)""",
                            (run_id,tool_name,json.dumps(arguments,ensure_ascii=False),
                             str(output_summary)[:4000],status,utc_now()))
            self.db.commit()

    def get_agent_run(self, run_id):
        with self.lock:
            return self.db.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()

    def list_agent_runs(self, limit=30, status=None):
        with self.lock:
            if status:
                return self.db.execute(
                    "SELECT * FROM agent_runs WHERE status=? ORDER BY started_at DESC LIMIT ?",
                    (status,max(1,min(int(limit),500)))).fetchall()
            return self.db.execute(
                "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?",
                (max(1,min(int(limit),500)),)).fetchall()

    def get_run_events(self, run_id, limit=100):
        with self.lock:
            return self.db.execute(
                "SELECT * FROM tool_events WHERE run_id=? ORDER BY id LIMIT ?",
                (run_id,max(1,min(int(limit),500)))).fetchall()

    def record_run_feedback(self, run_id, outcome, feedback="", lesson=None,
                            trigger_text="", category="coding"):
        if outcome not in {"success","partial","failure"}:
            raise ValueError("outcome must be success, partial, or failure")
        feedback=(feedback or "").strip()
        lesson=(lesson or "").strip()
        if not feedback and not lesson:
            raise ValueError("Provide feedback or a reusable lesson")
        now=utc_now()
        feedback_id=str(uuid.uuid4())
        lesson_id=None
        with self.lock:
            try:
                run=self.db.execute("SELECT id FROM agent_runs WHERE id=?", (run_id,)).fetchone()
                if not run:
                    raise ValueError(f"Unknown agent run: {run_id}")
                if lesson:
                    lesson_id=str(uuid.uuid4())
                    # The lesson text is explicitly supplied by the user; do not
                    # fabricate different confidence scores from the run outcome.
                    confidence=1.0
                    self.db.execute(
                        """INSERT INTO lessons(id,trigger_text,lesson,category,source,confidence,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (lesson_id,trigger_text.strip(),lesson,category,"user-run-feedback",confidence,now))
                self.db.execute(
                    """INSERT INTO run_feedback(id,run_id,outcome,feedback,lesson_id,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (feedback_id,run_id,outcome,feedback,lesson_id,now))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return {"feedback_id":feedback_id,"lesson_id":lesson_id}

    def agent_run_summary(self):
        with self.lock:
            runs=self.db.execute(
                "SELECT id,status,metadata_json FROM agent_runs WHERE kind='coding'").fetchall()
            feedback=self.db.execute(
                """SELECT f.outcome,COUNT(*) AS count FROM run_feedback f
                   JOIN agent_runs r ON r.id=f.run_id WHERE r.kind='coding' GROUP BY f.outcome""").fetchall()
            reviewed=self.db.execute(
                """SELECT COUNT(DISTINCT f.run_id) FROM run_feedback f
                   JOIN agent_runs r ON r.id=f.run_id WHERE r.kind='coding'""").fetchone()[0]
            lesson_count=self.db.execute(
                """SELECT COUNT(*) FROM lessons l
                   JOIN run_feedback f ON f.lesson_id=l.id
                   JOIN agent_runs r ON r.id=f.run_id
                   WHERE l.source='user-run-feedback' AND l.status='active' AND r.kind='coding'""").fetchone()[0]
        statuses={}
        verification={}
        tool_calls=[]
        for row in runs:
            statuses[row["status"]]=statuses.get(row["status"],0)+1
            try:
                metadata=json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata={}
            state=(metadata.get("verification") or {}).get("status")
            if state:
                verification[state]=verification.get(state,0)+1
            if isinstance(metadata.get("tool_calls"),int):
                tool_calls.append(metadata["tool_calls"])
        return {
            "coding_runs":len(runs),
            "run_statuses":statuses,
            "verification_statuses":verification,
            "reviewed_runs":int(reviewed),
            "feedback_outcomes":{row["outcome"]:row["count"] for row in feedback},
            "active_user_feedback_lessons":int(lesson_count),
            "average_tool_calls":round(sum(tool_calls)/len(tool_calls),2) if tool_calls else None,
            "runs_with_tool_call_metrics":len(tool_calls),
        }

    def list_run_feedback(self, run_id, limit=20):
        with self.lock:
            return self.db.execute(
                """SELECT f.*,l.lesson AS lesson_text,l.trigger_text AS lesson_trigger
                   FROM run_feedback f LEFT JOIN lessons l ON l.id=f.lesson_id
                   WHERE f.run_id=? ORDER BY f.created_at DESC LIMIT ?""",
                (run_id,max(1,min(int(limit),100)))).fetchall()

    def backup(self, destination):
        target=Path(destination).expanduser()
        if target.resolve()==self.path.resolve():
            raise ValueError("Backup destination must differ from the live database")
        target.parent.mkdir(parents=True,exist_ok=True)
        with self.lock:
            backup_db=sqlite3.connect(target)
            try:
                self.db.backup(backup_db)
            finally:
                backup_db.close()
        return target.resolve()

    def close(self):
        with self.lock:
            self.db.close()
