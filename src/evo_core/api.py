"""Loopback-only HTTP API for the Evo desktop client."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .assistant import EvoAssistant
from .coding_agent import CodingAgent
from .config import load_config
from .store import EvoStore


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=200000)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    category: str = Field(default="general", max_length=80)
    source: str = Field(default="user", max_length=80)
    confidence: float = Field(default=1.0, ge=0, le=1)


class AgentCreate(BaseModel):
    request: str = Field(min_length=1, max_length=20000)
    workspace: str | None = Field(default=None, max_length=2000)


class AgentApproval(BaseModel):
    approved: bool


def create_app(config_path="config.toml", provider_name=None):
    config = load_config(Path(config_path).resolve(), provider_name)
    store = EvoStore(config.database)
    assistant = EvoAssistant(config, store=store)
    app = FastAPI(title="Evo 4 Local API", version="0.1.0")
    app.state.config = config
    app.state.store = store
    app.state.assistant = assistant

    # Bound workers keep blocking provider calls off the ASGI event loop.
    # Shutdown waits for active turns before closing the shared SQLite store.
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evo-chat")
    app.state.chat_executor = executor
    conversation_locks = {}
    locks_guard = threading.Lock()
    shutting_down = threading.Event()
    approval_guard = threading.Lock()
    pending_approvals = {}

    @app.middleware("http")
    async def local_host_only(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse(
                status_code=403,
                content={"detail": "Evo API accepts loopback hosts only"},
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    def acquire_conversation_lock(conversation_id):
        with locks_guard:
            entry = conversation_locks.get(conversation_id)
            if entry is None:
                entry = {"lock": threading.Lock(), "users": 0}
                conversation_locks[conversation_id] = entry
            entry["users"] += 1
            return entry

    def release_conversation_lock(conversation_id, entry):
        with locks_guard:
            entry["users"] -= 1
            if entry["users"] == 0 and conversation_locks.get(conversation_id) is entry:
                del conversation_locks[conversation_id]

    @app.get("/api/v1/health")
    def health():
        return {
            "status": "ok",
            "provider": config.provider_name,
            "model": config.model,
            "endpoint": config.base_url,
        }

    @app.get("/api/v1/capabilities")
    def capabilities():
        return {
            "chat": True,
            "conversation_history": True,
            "conversation_search": True,
            "conversation_rename": True,
            "conversation_delete": True,
            "automatic_titles": True,
            "streaming": True,
            "stop_generation": False,
            "agents": True,
            "agent_approval": True,
            "agent_run_history": True,
            "memory_browser": True,
            "memory_candidates": True,
            "memory_archive": True,
            "hardware_dashboard": False,
            "experiments": False,
            "provider_selection": False,
        }


    @app.get("/api/v1/memories")
    def memories(q: str | None = None, status: str = "active", limit: int = 100):
        bounded = min(max(limit, 1), 200)
        if status not in {"active", "archived", "superseded"}:
            raise HTTPException(status_code=422, detail="Invalid memory status")
        with store.lock:
            if q and q.strip():
                pattern = "%" + q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                rows = store.db.execute(
                    """SELECT * FROM memories WHERE status=? AND
                       (content LIKE ? ESCAPE '!' OR category LIKE ? ESCAPE '!' OR tags_json LIKE ? ESCAPE '!')
                       ORDER BY updated_at DESC LIMIT ?""",
                    (status, pattern, pattern, pattern, bounded),
                ).fetchall()
            else:
                rows = store.db.execute(
                    "SELECT * FROM memories WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, bounded),
                ).fetchall()
        return [{
            "id": row["id"], "content": row["content"], "category": row["category"],
            "tags": json.loads(row["tags_json"] or "[]"), "source": row["source"],
            "confidence": row["confidence"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "access_count": row["access_count"],
        } for row in rows]

    @app.post("/api/v1/memories", status_code=201)
    def create_memory(payload: MemoryCreate):
        try:
            memory_id = store.add_memory(payload.content, payload.category, source=payload.source,
                                         confidence=payload.confidence)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": memory_id}

    @app.get("/api/v1/memory-candidates")
    def memory_candidates(limit: int = 100):
        rows = store.list_memory_candidates("pending", min(max(limit, 1), 200))
        return [{
            "id": row["id"], "content": row["content"], "category": row["category"],
            "source": row["source"], "confidence": row["confidence"],
            "created_at": row["created_at"], "conversation_id": row["conversation_id"],
        } for row in rows]

    @app.post("/api/v1/memory-candidates/{candidate_id}/review")
    def review_memory_candidate(candidate_id: str, payload: AgentApproval):
        result = store.review_memory_candidate(candidate_id, payload.approved)
        if result is None:
            raise HTTPException(status_code=404, detail="Pending memory candidate not found")
        return {"accepted": bool(payload.approved), "memory_id": result if payload.approved else None}

    @app.post("/api/v1/memories/{memory_id}/archive")
    def archive_memory(memory_id: str):
        if not store.archive_memory(memory_id):
            raise HTTPException(status_code=404, detail="Active memory not found")
        return {"archived": True, "id": memory_id}

    def serialize_run(row):
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return {
            "id": row["id"], "kind": row["kind"], "status": row["status"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
            "summary": row["summary"], "metadata": metadata,
        }

    @app.get("/api/v1/agents")
    def agent_runs(limit: int = 50, status: str | None = None):
        return [serialize_run(row) for row in store.list_agent_runs(min(max(limit, 1), 100), status)]

    @app.get("/api/v1/agents/{run_id}")
    def agent_run(run_id: str):
        row = store.get_agent_run(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Agent run not found")
        result = serialize_run(row)
        result["events"] = [{
            "id": event["id"], "tool_name": event["tool_name"],
            "input": json.loads(event["input_json"] or "{}"),
            "output": event["output_summary"], "status": event["status"],
            "created_at": event["created_at"],
        } for event in store.get_run_events(run_id, 200)]
        with approval_guard:
            result["pending_approval"] = next(
                ({"id": key, "tool_name": value["tool_name"], "arguments": value["arguments"]}
                 for key, value in pending_approvals.items() if value["run_id"] == run_id), None)
        return result

    @app.post("/api/v1/agents", status_code=202)
    def start_agent(payload: AgentCreate):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        workspace = Path(payload.workspace).expanduser().resolve() if payload.workspace else config.workspace_root.resolve()
        run_id = store.start_agent_run("coding", {
            "workspace": str(workspace), "model": config.model, "base_url": config.base_url,
            "request": payload.request[:2000], "source": "desktop",
        })
        try:
            executor.submit(run_agent, run_id, payload.request, workspace)
        except Exception as exc:
            store.finish_agent_run(run_id, "failed", "Unable to start agent worker")
            raise HTTPException(status_code=503, detail="Unable to start agent worker") from exc
        return {"run_id": run_id, "status": "running"}

    def run_agent(run_id, request_text, workspace):
        conversation_id = assistant.new_conversation("Agent: " + request_text[:80])
        store.update_agent_run_metadata(run_id, {"conversation_id": conversation_id})

        def approval(name, arguments):
            import uuid
            approval_id = uuid.uuid4().hex
            decision = threading.Event()
            item = {"run_id": run_id, "tool_name": name, "arguments": arguments,
                    "decision": decision, "approved": False}
            with approval_guard:
                pending_approvals[approval_id] = item
            store.update_agent_run_metadata(run_id, {"lifecycle": "awaiting_approval",
                                                      "pending_approval_id": approval_id})
            decision.wait(timeout=600)
            with approval_guard:
                pending_approvals.pop(approval_id, None)
            store.update_agent_run_metadata(run_id, {"lifecycle": "executing",
                                                      "pending_approval_id": None})
            return bool(item["approved"])

        try:
            agent = CodingAgent(assistant, workspace, config.allowed_commands)
            agent.run(conversation_id, request_text, approval, run_id=run_id)
        except Exception as exc:
            store.finish_agent_run(run_id, "failed", f"{type(exc).__name__}: {exc}")

    @app.post("/api/v1/agents/{run_id}/approval")
    def decide_agent_approval(run_id: str, payload: AgentApproval):
        with approval_guard:
            match = next(((key, value) for key, value in pending_approvals.items()
                          if value["run_id"] == run_id), None)
            if match is None:
                raise HTTPException(status_code=404, detail="No pending approval for this run")
            _, item = match
            item["approved"] = payload.approved
            item["decision"].set()
        return {"decided": True, "approved": payload.approved}

    @app.get("/api/v1/conversations")
    def conversations(limit: int = 30, q: str | None = None):
        rows = store.list_conversations(min(max(limit, 1), 100), query=q)
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    @app.post("/api/v1/conversations", status_code=201)
    def create_conversation():
        return {"id": assistant.new_conversation(), "title": "New conversation"}

    @app.patch("/api/v1/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, payload: ConversationUpdate):
        try:
            updated = store.rename_conversation(conversation_id, payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"id": conversation_id, "title": payload.title.strip()}

    @app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str):
        if store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # The reservation check and deletion must be atomic with respect to chat
        # registration. Queued turns are reserved before executor submission.
        with locks_guard:
            entry = conversation_locks.get(conversation_id)
            if entry and entry["users"]:
                raise HTTPException(status_code=409, detail="Conversation is currently active")
            if not store.delete_conversation(conversation_id):
                raise HTTPException(status_code=404, detail="Conversation not found")
        return None

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        if store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in store.get_messages(conversation_id, 500)
            if row["role"] in {"user", "assistant"}
        ]

    @app.post("/api/v1/chat")
    async def chat(payload: ChatRequest):
        text = payload.message.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Message cannot be empty")
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")

        conversation_id = payload.conversation_id
        if conversation_id is None:
            conversation_id = assistant.new_conversation()
        else:
            # Existence validation and reservation share the deletion lock. A
            # delete can therefore happen either before this check or after the
            # reservation is released, never in the middle.
            with locks_guard:
                if store.get_conversation(conversation_id) is None:
                    raise HTTPException(status_code=404, detail="Conversation not found")
                reservation = conversation_locks.get(conversation_id)
                if reservation is None:
                    reservation = {"lock": threading.Lock(), "users": 0}
                    conversation_locks[conversation_id] = reservation
                reservation["users"] += 1

        # Reserve before the SSE generator queues the worker. This prevents
        # deletion during the gap between executor submission and worker start.
        if payload.conversation_id is None:
            reservation = acquire_conversation_lock(conversation_id)
        submitted = threading.Event()

        async def events():
            loop = asyncio.get_running_loop()
            queue = asyncio.Queue()
            connected = threading.Event()
            connected.set()
            sentinel = object()

            def publish(item):
                if connected.is_set() and loop.is_running():
                    try:
                        loop.call_soon_threadsafe(queue.put_nowait, item)
                    except RuntimeError:
                        # The ASGI loop may already be closing during shutdown.
                        connected.clear()

            def run_turn():
                try:
                    with reservation["lock"]:
                        if shutting_down.is_set():
                            raise RuntimeError("Evo is shutting down")
                        result = assistant.turn(
                            conversation_id, text,
                            on_token=lambda token: publish(
                                {"event": "token", "data": token}
                            ),
                        )
                    publish({
                        "event": "complete",
                        "data": {
                            "conversation_id": conversation_id,
                            "elapsed_seconds": result.get("elapsed_seconds"),
                            "ttft_seconds": result.get("ttft_seconds"),
                            "prompt_tokens": result.get("prompt_tokens"),
                            "completion_tokens": result.get("completion_tokens"),
                            "tokens_per_second": result.get("tokens_per_second"),
                        },
                    })
                except Exception as exc:
                    publish({
                        "event": "error",
                        "data": {"type": type(exc).__name__, "message": str(exc)},
                    })
                finally:
                    release_conversation_lock(conversation_id, reservation)
                    publish(sentinel)

            try:
                yield (
                    "event: start\ndata: "
                    + json.dumps({"conversation_id": conversation_id})
                    + "\n\n"
                )
                try:
                    executor.submit(run_turn)
                    submitted.set()
                except Exception as exc:
                    release_conversation_lock(conversation_id, reservation)
                    yield (
                        "event: error\ndata: "
                        + json.dumps({
                            "type": type(exc).__name__,
                            "message": "Unable to start chat worker",
                        })
                        + "\n\n"
                    )
                    return
                while True:
                    item = await queue.get()
                    if item is sentinel:
                        break
                    yield (
                        f"event: {item['event']}\ndata: "
                        f"{json.dumps(item['data'], ensure_ascii=False)}\n\n"
                    )
            finally:
                # Provider calls currently cannot be interrupted safely. Stop
                # forwarding tokens to a departed client; the turn may finish
                # and persist its result in the background.
                connected.clear()
                if not submitted.is_set():
                    with locks_guard:
                        still_reserved = conversation_locks.get(conversation_id) is reservation
                    if still_reserved:
                        release_conversation_lock(conversation_id, reservation)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.on_event("shutdown")
    def shutdown():
        shutting_down.set()
        # Never leave an agent worker blocked on a browser approval while the
        # executor is waiting to drain during application shutdown.
        with approval_guard:
            for item in pending_approvals.values():
                item["approved"] = False
                item["decision"].set()
            pending_approvals.clear()
        executor.shutdown(wait=True, cancel_futures=False)
        assistant.close()

    return app
