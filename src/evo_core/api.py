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
from .config import load_config
from .store import EvoStore


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=200000)


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
        allow_methods=["GET", "POST", "OPTIONS"],
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
            "streaming": True,
            "stop_generation": False,
            "agents": False,
            "memory_browser": False,
            "hardware_dashboard": False,
            "experiments": False,
            "provider_selection": False,
        }

    @app.get("/api/v1/conversations")
    def conversations(limit: int = 30):
        rows = store.list_conversations(min(max(limit, 1), 100))
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

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        if not any(
            row["id"] == conversation_id for row in store.list_conversations(10000)
        ):
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
        elif not any(
            row["id"] == conversation_id for row in store.list_conversations(10000)
        ):
            raise HTTPException(status_code=404, detail="Conversation not found")

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
                entry = acquire_conversation_lock(conversation_id)
                try:
                    with entry["lock"]:
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
                    release_conversation_lock(conversation_id, entry)
                    publish(sentinel)

            try:
                yield (
                    "event: start\ndata: "
                    + json.dumps({"conversation_id": conversation_id})
                    + "\n\n"
                )
                try:
                    executor.submit(run_turn)
                except Exception as exc:
                    yield (
                        "event: error\\ndata: "
                        + json.dumps({
                            "type": type(exc).__name__,
                            "message": "Unable to start chat worker",
                        })
                        + "\\n\\n"
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

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.on_event("shutdown")
    def shutdown():
        shutting_down.set()
        executor.shutdown(wait=True, cancel_futures=False)
        assistant.close()

    return app
