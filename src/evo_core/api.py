"""Loopback-only HTTP API for the Evo desktop client."""
import asyncio
import json
import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    app.state.config, app.state.store, app.state.assistant = config, store, assistant
    @app.middleware("http")
    async def local_host_only(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            raise HTTPException(status_code=403, detail="Evo API accepts loopback hosts only")
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173"],
        allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"])

    conversation_locks = {}
    locks_guard = threading.Lock()

    @app.get("/api/v1/health")
    def health():
        return {"status":"ok","provider":config.provider_name,"model":config.model,"endpoint":config.base_url}

    @app.get("/api/v1/capabilities")
    def capabilities():
        return {"chat":True,"conversation_history":True,"streaming":True,
                "stop_generation":False,"agents":False,"memory_browser":False,
                "hardware_dashboard":False,"experiments":False,"provider_selection":False}

    @app.get("/api/v1/conversations")
    def conversations(limit: int = 30):
        return [{"id":r["id"],"title":r["title"],"created_at":r["created_at"],"updated_at":r["updated_at"]}
                for r in store.list_conversations(min(max(limit,1),100))]

    @app.post("/api/v1/conversations", status_code=201)
    def create_conversation():
        return {"id":assistant.new_conversation(),"title":"New conversation"}

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        if not any(r["id"] == conversation_id for r in store.list_conversations(10000)):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return [{"role":r["role"],"content":r["content"],"created_at":r["created_at"]}
                for r in store.get_messages(conversation_id,500) if r["role"] in {"user","assistant"}]

    @app.post("/api/v1/chat")
    async def chat(payload: ChatRequest):
        text = payload.message.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Message cannot be empty")
        cid = payload.conversation_id
        if cid is None:
            cid = assistant.new_conversation()
        elif not any(r["id"] == cid for r in store.list_conversations(10000)):
            raise HTTPException(status_code=404, detail="Conversation not found")

        async def events():
            loop = asyncio.get_running_loop()
            queue = asyncio.Queue()
            sentinel = object()
            def on_token(token):
                loop.call_soon_threadsafe(queue.put_nowait, {"event":"token","data":token})
            def run_turn():
                try:
                    with locks_guard:
                        turn_lock = conversation_locks.setdefault(cid, threading.Lock())
                    with turn_lock:
                        result = assistant.turn(cid,text,on_token=on_token)
                    loop.call_soon_threadsafe(queue.put_nowait, {"event":"complete","data":{
                        "conversation_id":cid,"elapsed_seconds":result.get("elapsed_seconds"),
                        "ttft_seconds":result.get("ttft_seconds"),"prompt_tokens":result.get("prompt_tokens"),
                        "completion_tokens":result.get("completion_tokens"),
                        "tokens_per_second":result.get("tokens_per_second")}})
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"event":"error","data":{
                        "type":type(exc).__name__,"message":str(exc)}})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait,sentinel)
            threading.Thread(target=run_turn,daemon=True).start()
            yield "event: start\ndata: " + json.dumps({"conversation_id":cid}) + "\n\n"
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'],ensure_ascii=False)}\n\n"
        return StreamingResponse(events(),media_type="text/event-stream",
            headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    @app.on_event("shutdown")
    def shutdown():
        assistant.close()
    return app
