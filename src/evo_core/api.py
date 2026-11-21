"""Loopback-only HTTP API for the Evo desktop client."""
import asyncio
from datetime import datetime, timezone
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .assistant import EvoAssistant
from .coding_agent import CodingAgent
from . import background_agent, orchestration, agent_lifecycle
from .config import load_config
from .store import EvoStore
from .memory_review import find_duplicate_candidates
from .demo_data import seed_demo_data, demo_data_status, clear_demo_data
from evo_experiments.monitor import sample_nvidia_smi
from evo_experiments.db import ResultsDB
from evo_experiments.intelligence import assess_workload, discover_runtimes, estimate_runtime, initialize_profiles, list_profiles, save_profile
from evo_experiments.scheduler import initialize_scheduler, create_job, list_jobs, dispatch_jobs, start_job, finish_job, cancel_job
from evo_experiments.execution import initialize_execution, register_execution, list_executions, run_execution, recover_interrupted_executions


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


class MemorySupersede(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    reason: str = Field(default="", max_length=2000)


class AgentCreate(BaseModel):
    request: str = Field(min_length=1, max_length=20000)
    workspace: str | None = Field(default=None, max_length=2000)


class AgentApproval(BaseModel):
    approved: bool


class AgentPlanCreate(BaseModel):
    request: str = Field(min_length=1, max_length=12000)
    workspace: str | None = Field(default=None, max_length=2000)

class RuntimeProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(default="", max_length=200)
    model_file: str = Field(default="", max_length=1000)
    runtime: str = Field(default="", max_length=100)
    context_size: int | None = Field(default=None, ge=1, le=10000000)
    layers: int | None = Field(default=None, ge=1, le=10000)
    kv_heads: int | None = Field(default=None, ge=1, le=10000)
    head_dim: int | None = Field(default=None, ge=1, le=10000)
    key_bytes: int = Field(default=2, ge=1, le=16)
    value_bytes: int = Field(default=2, ge=1, le=16)
    gpu_layers: str = Field(default="", max_length=40)
    kv_cache_k: str = Field(default="", max_length=40)
    kv_cache_v: str = Field(default="", max_length=40)
    batch_size: int | None = Field(default=None, ge=1, le=1000000)
    ubatch_size: int | None = Field(default=None, ge=1, le=1000000)
    notes: str = Field(default="", max_length=4000)


class WorkloadAssessment(BaseModel):
    kind: str = Field(default="background", max_length=40)
    gpu_heavy: bool | None = None
    estimated_vram_mib: float | None = Field(default=None, ge=0, le=1000000)
    estimated_ram_mib: float | None = Field(default=None, ge=0, le=1000000)


class SchedulerJobInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    kind: str = Field(default="background", max_length=40)
    priority: int = Field(default=10, ge=1, le=100)
    gpu_heavy: bool | None = None
    estimated_vram_mib: float | None = Field(default=None, ge=0, le=1000000)
    estimated_ram_mib: float | None = Field(default=None, ge=0, le=1000000)


class SchedulerFinishInput(BaseModel):
    outcome: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=2000)


class WorkloadExecuteInput(BaseModel):
    argv: list[str] = Field(min_items=1, max_items=128)
    timeout_seconds: int = Field(default=300, ge=1, le=900)


def create_app(config_path="config.toml", provider_name=None):
    config = load_config(Path(config_path).resolve(), provider_name)
    store = EvoStore(config.database)
    lab_db = ResultsDB(config.database)
    assistant = EvoAssistant(config, store=store)
    app = FastAPI(title="Evo 4 Local API", version="0.1.0")
    app.state.config = config
    app.state.store = store
    app.state.lab_db = lab_db
    app.state.assistant = assistant
    initialize_profiles(lab_db.connection)
    initialize_scheduler(lab_db.connection)
    initialize_execution(lab_db.connection)
    background_agent.initialize(lab_db.connection)
    orchestration.initialize(lab_db.connection)
    agent_lifecycle.initialize(lab_db.connection)
    with lab_db.lock:
        recover_interrupted_executions(lab_db.connection)
        recovered_agent_tasks = background_agent.recover(lab_db.connection)
        orchestration.recover_plans(lab_db.connection)
        for recovered_id in recovered_agent_tasks:
            store.finish_agent_run(recovered_id, "interrupted", "Evo restarted; in-flight work was not resumed.")
        agent_lifecycle.reconcile(lab_db.connection, store)

    # Bound workers keep blocking provider calls off the ASGI event loop.
    # Shutdown waits for active turns before closing the shared SQLite store.
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evo-chat")
    app.state.chat_executor = executor
    execution_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evo-workload")
    execution_slots = threading.BoundedSemaphore(2)
    app.state.execution_executor = execution_executor
    app.state.execution_slots = execution_slots
    conversation_locks = {}
    locks_guard = threading.Lock()
    shutting_down = threading.Event()
    approval_guard = threading.Lock()
    pending_approvals = {}
    agent_stop_events = {}
    agent_futures = {}
    agent_registry_guard = threading.RLock()
    # Seed/clear touch both SQLite stores; serialize the cross-database operation.
    demo_data_guard = threading.Lock()

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


    @app.get("/api/v1/demo/status")
    def demo_status():
        with demo_data_guard:
            return demo_data_status(store, lab_db)

    @app.post("/api/v1/demo/seed")
    def demo_seed():
        with demo_data_guard:
            return seed_demo_data(store, lab_db)

    @app.delete("/api/v1/demo/seed")
    def demo_clear():
        with demo_data_guard:
            return clear_demo_data(store, lab_db)

    @app.get("/api/v1/hardware/current")
    def hardware_current():
        telemetry_error = None
        try:
            sample = sample_nvidia_smi()
        except Exception as exc:
            # Keep the dashboard usable even if an optional platform probe fails.
            sample = {"sampled_at": None, "gpu_name": None, "gpu_available": False,
                      "gpu_utilization_percent": None, "gpu_memory_used_mib": None,
                      "gpu_memory_total_mib": None, "gpu_memory_used_percent": None,
                      "gpu_temperature_c": None, "gpu_power_w": None, "gpu_processes": [],
                      "cpu_utilization_percent": None, "cpu_logical_cores": None,
                      "load_average_1m": None, "load_average_5m": None, "load_average_15m": None,
                      "ram_used_mib": None, "ram_used_percent": None,
                      "ram_total_bytes": None, "ram_available_bytes": None}
            telemetry_error = f"{type(exc).__name__}: {str(exc)[:240]}"
        warnings = []
        if sample.get("gpu_available"):
            vram = sample.get("gpu_memory_used_percent")
            if vram is not None and vram >= 90:
                warnings.append({"level": "warning", "code": "vram_pressure",
                                 "message": "GPU memory is above 90%; avoid starting another GPU-heavy workload."})
            temp = sample.get("gpu_temperature_c")
            if temp is not None and temp >= 85:
                warnings.append({"level": "critical", "code": "gpu_temperature",
                                 "message": "GPU temperature is at or above 85°C; reduce GPU load and inspect cooling."})
        ram = sample.get("ram_used_percent")
        if ram is not None and ram >= 90:
            warnings.append({"level": "warning", "code": "ram_pressure",
                             "message": "System memory is above 90%; defer large background tasks."})
        cpu = sample.get("cpu_utilization_percent")
        if cpu is not None and cpu >= 95:
            warnings.append({"level": "info", "code": "cpu_saturation",
                             "message": "CPU utilization is above 95%; consider reducing concurrent background work."})
        vram_free = None
        if sample.get("gpu_memory_total_mib") is not None and sample.get("gpu_memory_used_mib") is not None:
            vram_free = max(0, sample["gpu_memory_total_mib"] - sample["gpu_memory_used_mib"])
        ram_free_mib = (sample["ram_available_bytes"] / (1024 * 1024)
                        if sample.get("ram_available_bytes") is not None else None)
        pressure = bool(warnings)
        telemetry_known = sample.get("ram_used_percent") is not None
        background_work = "defer" if pressure else "limited" if telemetry_known else "unknown"
        budget_reason = ("Resource pressure detected; protect interactive inference." if pressure
                         else "System RAM telemetry is available; GPU headroom is " +
                              ("also available." if sample.get("gpu_available") else "unknown because NVIDIA telemetry is unavailable.")
                         if telemetry_known
                         else "System resource telemetry is unavailable; available headroom is unknown.")
        parsed_endpoint = urlsplit(config.base_url)
        hostname = parsed_endpoint.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = "[" + hostname + "]"
        if parsed_endpoint.port:
            hostname += ":" + str(parsed_endpoint.port)
        safe_endpoint = urlunsplit((parsed_endpoint.scheme, hostname, parsed_endpoint.path, "", ""))
        return {
            "sample": sample,
            "telemetry_error": telemetry_error,
            "runtime": {"provider": config.provider_name, "model": config.model,
                        "endpoint": safe_endpoint},
            "budget": {"vram_free_mib": vram_free, "ram_free_mib": ram_free_mib,
                       "background_work": background_work, "reason": budget_reason},
            "policy": {"mode": "observe_only", "actions_enabled": False,
                       "description": "Evo currently measures and recommends; it does not change processes, clocks, power limits, or services."},
            "warnings": warnings,
        }

    @app.get("/api/v1/hardware/runtimes")
    def hardware_runtimes():
        try:
            sample = sample_nvidia_smi()
        except Exception:
            sample = {"gpu_processes": []}
        endpoint = urlsplit(config.base_url)
        hostname = endpoint.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = "[" + hostname + "]"
        if endpoint.port:
            hostname += ":" + str(endpoint.port)
        safe_endpoint = urlunsplit((endpoint.scheme, hostname, endpoint.path, "", ""))
        return discover_runtimes(gpu_processes=sample.get("gpu_processes"),
            configured={"provider": config.provider_name, "model": config.model,
                        "endpoint": safe_endpoint})

    @app.get("/api/v1/hardware/profiles")
    def hardware_profiles():
        with lab_db.lock:
            return list_profiles(lab_db.connection)

    @app.post("/api/v1/hardware/profiles", status_code=201)
    def hardware_profile_create(payload: RuntimeProfileInput):
        try:
            with lab_db.lock:
                return save_profile(lab_db.connection, payload.dict())
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hardware/estimate")
    def hardware_estimate(payload: RuntimeProfileInput):
        try:
            sample = sample_nvidia_smi()
        except Exception:
            sample = {}
        profile = payload.dict()
        if profile.get("model_file"):
            try:
                profile["model_file_bytes"] = Path(profile["model_file"]).expanduser().stat().st_size
            except OSError:
                profile["model_file_bytes"] = None
        return estimate_runtime(profile, sample)

    @app.post("/api/v1/hardware/admission")
    def hardware_admission(payload: WorkloadAssessment):
        try:
            sample = sample_nvidia_smi()
        except Exception:
            sample = {}
        return assess_workload(sample, payload.dict())

    @app.get("/api/v1/hardware/scheduler")
    def hardware_scheduler():
        with lab_db.lock:
            return list_jobs(lab_db.connection)

    @app.post("/api/v1/hardware/scheduler/jobs", status_code=201)
    def hardware_scheduler_create(payload: SchedulerJobInput):
        try:
            with lab_db.lock:
                return create_job(lab_db.connection, payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Could not create workload job") from exc

    @app.post("/api/v1/hardware/scheduler/dispatch")
    def hardware_scheduler_dispatch(limit: int = 5):
        try:
            sample = sample_nvidia_smi()
        except Exception:
            sample = {}
        with lab_db.lock:
            return dispatch_jobs(lab_db.connection, sample, limit=limit)

    @app.post("/api/v1/hardware/scheduler/jobs/{job_id}/start")
    def hardware_scheduler_start(job_id: str):
        try:
            with lab_db.lock:
                return start_job(lab_db.connection, job_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hardware/scheduler/jobs/{job_id}/finish")
    def hardware_scheduler_finish(job_id: str, payload: SchedulerFinishInput):
        try:
            with lab_db.lock:
                managed = lab_db.connection.execute(
                    "SELECT status FROM workload_executions WHERE job_id=?", (job_id,)).fetchone()
                if managed and managed["status"] in {"queued", "launching", "running", "launch_uncertain"}:
                    raise HTTPException(
                        status_code=409,
                        detail="Evo-managed execution has an unresolved launch or run state and cannot be externally marked finished")
                return finish_job(lab_db.connection, job_id, payload.outcome, payload.note)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hardware/scheduler/jobs/{job_id}/cancel")
    def hardware_scheduler_cancel(job_id: str):
        try:
            with lab_db.lock:
                return cancel_job(lab_db.connection, job_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/hardware/executions")
    def hardware_executions(limit: int = 50):
        with lab_db.lock:
            return list_executions(lab_db.connection, limit)

    @app.post("/api/v1/hardware/scheduler/jobs/{job_id}/execute", status_code=202)
    def hardware_scheduler_execute(job_id: str, payload: WorkloadExecuteInput):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        if not execution_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Both managed execution slots are occupied; retry after a worker finishes")
        try:
            with lab_db.lock:
                execution = register_execution(
                    lab_db.connection, job_id, payload.argv, config.allowed_commands,
                    config.workspace_root.resolve(), payload.timeout_seconds)
        except ValueError as exc:
            execution_slots.release()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            future = execution_executor.submit(run_execution, lab_db.connection, lab_db.lock, execution["id"])
            future.add_done_callback(lambda _future: execution_slots.release())
        except Exception as exc:
            execution_slots.release()
            with lab_db.lock:
                lab_db.connection.execute(
                    "UPDATE workload_executions SET status='failed',finished_at=?,error=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), "Unable to queue execution worker", execution["id"]))
                finish_job(lab_db.connection, job_id, "failed", "Unable to queue execution worker")
                lab_db.connection.commit()
            raise HTTPException(status_code=503, detail="Unable to queue execution worker") from exc
        return {"execution_id": execution["id"], "job_id": job_id, "status": "queued"}

    @app.get("/api/v1/hardware/history")
    def hardware_history(limit: int = 180):
        bounded = min(max(limit, 1), 1000)
        try:
            with store.lock:
                rows = store.db.execute(
                    """SELECT rs.id,rs.experiment_id,rs.sampled_at,rs.gpu_utilization_percent,
                       rs.gpu_memory_used_mib,rs.gpu_memory_total_mib,rs.gpu_memory_used_percent,
                       rs.gpu_temperature_c,rs.gpu_power_w,rs.ram_used_mib,rs.ram_used_percent,
                       rs.cpu_utilization_percent,rs.load_average_1m,
                       CASE WHEN json_extract(e.config_json,'$.demo_seed')=1 THEN 1 ELSE 0 END AS is_demo
                       FROM resource_samples rs LEFT JOIN experiments e ON e.id=rs.experiment_id
                       ORDER BY rs.id DESC LIMIT ?""", (bounded,)
                ).fetchall()
            return [dict(row) for row in reversed(rows)]
        except sqlite3.OperationalError:
            return []

    @app.get("/api/v1/experiments")
    def experiments(limit: int = 30):
        bounded = min(max(limit, 1), 100)
        try:
            with store.lock:
                rows = store.db.execute(
                    """SELECT id,started_at,finished_at,task_id,category,repetition,
                       model,run_label,status,error,elapsed_seconds,
                       time_to_first_token_seconds,prompt_tokens,completion_tokens,
                       tokens_per_second,evaluation_status,evaluation_passed,evaluation_total,config_json
                       FROM experiments ORDER BY id DESC LIMIT ?""", (bounded,)
                ).fetchall()
                aggregates = store.db.execute(
                    """SELECT COALESCE(run_label,model) AS configuration,model,category,
                       MAX(CASE WHEN json_extract(experiments.config_json,'$.demo_seed')=1 THEN 1 ELSE 0 END) AS is_demo,
                       COUNT(*) AS runs,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                       ROUND(AVG(tokens_per_second),2) AS avg_tokens_per_second,
                       ROUND(AVG(time_to_first_token_seconds),3) AS avg_ttft_seconds,
                       MAX(samples.peak_vram_mib) AS peak_vram_mib,
                       MAX(samples.peak_ram_mib) AS peak_ram_mib
                       FROM experiments LEFT JOIN (
                         SELECT experiment_id,MAX(gpu_memory_used_mib) AS peak_vram_mib,
                                MAX(ram_used_mib) AS peak_ram_mib
                         FROM resource_samples GROUP BY experiment_id
                       ) samples ON samples.experiment_id=experiments.id
                       GROUP BY COALESCE(run_label,model),model,category
                       ORDER BY configuration,category"""
                ).fetchall()
            return {"available": True, "runs": [{**dict(row), "is_demo": bool(json.loads(row["config_json"] or "{}").get("demo_seed"))}
                             for row in rows],
                    "aggregates": [dict(row) for row in aggregates]}
        except sqlite3.OperationalError:
            return {"available": False, "runs": [], "aggregates": [],
                    "message": "No Evo Lab experiment database is available yet. Run evo-exp init-db or an experiment."}

    @app.get("/api/v1/health")
    def health():
        parsed_endpoint = urlsplit(config.base_url)
        hostname = parsed_endpoint.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = "[" + hostname + "]"
        if parsed_endpoint.port:
            hostname += ":" + str(parsed_endpoint.port)
        safe_endpoint = urlunsplit((parsed_endpoint.scheme, hostname, parsed_endpoint.path, "", ""))
        return {
            "status": "ok",
            "provider": config.provider_name,
            "model": config.model,
            "endpoint": safe_endpoint,
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
            "background_agent_tasks": True,
            "background_agent_cancellation": True,
            "background_agent_event_history": True,
            "background_agent_restart_recovery": True,
            "background_agent_resume": False,
            "agent_plan_proposals": True,
            "agent_plan_approval": True,
            "agent_plan_step_tracking": True,
            "agent_plan_step_retry": False,
            "agent_plan_resource_admission": False,
            "memory_browser": True,
            "memory_candidates": True,
            "memory_archive": True,
            "memory_supersede": True,
            "hardware_dashboard": True,
            "hardware_process_visibility": True,
            "resource_policy_advisory": True,
            "experiments": True,
            "demo_data": True,
            "hardware_diagnostics": True,
            "hardware_runtime_discovery": True,
            "hardware_runtime_profiles": True,
            "hardware_resource_estimates": True,
            "hardware_workload_admission": True,
            "hardware_workload_scheduler": True,
            "hardware_managed_execution": True,
            "hardware_process_control": False,
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

    @app.get("/api/v1/memories/review")
    def memory_review(limit: int = 20):
        bounded = min(max(limit, 1), 50)
        with store.lock:
            rows = store.db.execute(
                """SELECT id,content,category,source,confidence,updated_at
                   FROM memories WHERE status='active' ORDER BY updated_at DESC LIMIT 500"""
            ).fetchall()
        suggestions = find_duplicate_candidates(rows, limit=bounded)
        return {
            "count": len(suggestions),
            "analyzed_records": len(rows),
            "method": "lexical-overlap; no embeddings or semantic inference",
            "mutates_memory": False,
            "suggestions": suggestions,
            "note": "Suggestions are possible duplicates, not confirmed duplicates or contradictions. Inspect both records before taking action.",
        }

    @app.get("/api/v1/memories/search")
    def memory_search_preview(q: str, limit: int = 8):
        if not q.strip():
            raise HTTPException(status_code=422, detail="Search query cannot be empty")
        rows = store.search_memories(q, min(max(limit, 1), 20), record_access=False)
        return {
            "query": q, "count": len(rows),
            "retrieval": "hybrid lexical (FTS5 + LIKE candidates; no embeddings)",
            "matches": [{
                "id": row["id"], "content": row["content"], "category": row["category"],
                "source": row["source"], "confidence": row["confidence"],
                "score": row["retrieval_score"], "coverage": row["retrieval_coverage"],
                "matched_terms": row["retrieval_matched_terms"],
                "reason": row["retrieval_reason"], "method": row["retrieval_method"],
            } for row in rows],
        }

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


    @app.post("/api/v1/memories/{memory_id}/supersede")
    def supersede_memory(memory_id: str, payload: MemorySupersede):
        try:
            replacement_id = store.supersede_memory(
                memory_id, payload.content, source="user", confidence=1.0,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 422,
                                detail=str(exc)) from exc
        return {"id": replacement_id, "supersedes": memory_id}

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
        with lab_db.lock:
            task = background_agent.get(lab_db.connection, run_id)
            task_events = background_agent.events(lab_db.connection, run_id, limit=300) if task else []
        result["background_task"] = task
        result["background_events"] = task_events
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

    def _forget_agent_future(run_id, future):
        with agent_registry_guard:
            if agent_futures.get(run_id) is future:
                agent_futures.pop(run_id, None)

    @app.get("/api/v1/agents/plans")
    def agent_plans(limit: int = 50):
        with lab_db.lock:
            return orchestration.list_plans(lab_db.connection, limit)

    @app.post("/api/v1/agents/plans", status_code=201)
    def propose_agent_plan(payload: AgentPlanCreate):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        workspace = Path(payload.workspace).expanduser().resolve() if payload.workspace else config.workspace_root.resolve()
        try:
            proposal = orchestration.propose_with_model(
                assistant.provider, payload.request, str(workspace), max_tokens=min(config.max_tokens, 3000))
            with lab_db.lock:
                plan = orchestration.create_plan(lab_db.connection, payload.request, str(workspace), proposal)
            return plan
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Unable to generate a plan: {type(exc).__name__}: {str(exc)[:300]}") from exc

    @app.get("/api/v1/agents/plans/{plan_id}")
    def agent_plan_detail(plan_id: str):
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Agent plan not found")
        return plan

    @app.post("/api/v1/agents/plans/{plan_id}/approve")
    def approve_agent_plan(plan_id: str):
        try:
            with lab_db.lock:
                if orchestration.get_plan(lab_db.connection, plan_id) is None:
                    raise HTTPException(status_code=404, detail="Agent plan not found")
                return orchestration.approve_plan(lab_db.connection, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/agents/plans/{plan_id}/execute", status_code=202)
    def execute_agent_plan(plan_id: str):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Agent plan not found")
            if plan["status"] != "approved":
                raise HTTPException(status_code=409, detail="Approve the plan before execution")
            request_text = plan["request"]
            workspace = Path(plan["workspace"]).expanduser().resolve()
            run_id = store.start_agent_run("orchestrated", {
                "workspace": str(workspace), "model": config.model, "base_url": config.base_url,
                "request": request_text[:2000], "source": "approved-plan", "plan_id": plan_id,
            })
            try:
                background_agent.create(lab_db.connection, run_id)
                orchestration.attach_run(lab_db.connection, plan_id, run_id)
            except Exception:
                store.finish_agent_run(run_id, "failed", "Unable to attach orchestrated run")
                with lab_db.lock:
                    background_agent.decide_finalization(lab_db.connection, run_id, "failed", "Unable to attach orchestrated run", {"plan_id": plan_id})
                raise HTTPException(status_code=503, detail="Unable to start orchestrated worker")
        stop_event = threading.Event()
        with agent_registry_guard:
            agent_stop_events[run_id] = stop_event
        try:
            future = executor.submit(run_agent, run_id, request_text, workspace, stop_event, plan_id)
            with agent_registry_guard:
                agent_futures[run_id] = future
            future.add_done_callback(lambda _future: _forget_agent_future(run_id, future))
        except Exception as exc:
            store.finish_agent_run(run_id, "failed", "Unable to start orchestrated worker")
            with lab_db.lock:
                background_agent.decide_finalization(lab_db.connection, run_id, "failed", "Unable to start orchestrated worker", {"plan_id": plan_id})
                background_agent.transition(lab_db.connection, run_id, "failed", {"error": "Unable to start worker"})
                orchestration.finish_plan(lab_db.connection, plan_id, "failed", "Unable to start worker")
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
            raise HTTPException(status_code=503, detail="Unable to start orchestrated worker") from exc
        return {"plan_id": plan_id, "run_id": run_id, "status": "running"}

    @app.post("/api/v1/agents", status_code=202)
    def start_agent(payload: AgentCreate):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        workspace = Path(payload.workspace).expanduser().resolve() if payload.workspace else config.workspace_root.resolve()
        run_id = store.start_agent_run("coding", {
            "workspace": str(workspace), "model": config.model, "base_url": config.base_url,
            "request": payload.request[:2000], "source": "desktop",
        })
        stop_event = threading.Event()
        with agent_registry_guard:
            agent_stop_events[run_id] = stop_event
        try:
            with lab_db.lock:
                background_agent.create(lab_db.connection, run_id)
        except Exception:
            store.finish_agent_run(run_id, "failed", "Unable to create background task")
            with lab_db.lock:
                background_agent.decide_finalization(lab_db.connection, run_id, "failed", "Unable to create background task", {})
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
            raise HTTPException(status_code=503, detail="Unable to start agent worker")
        try:
            future = executor.submit(run_agent, run_id, payload.request, workspace, stop_event)
            with agent_registry_guard:
                agent_futures[run_id] = future
            future.add_done_callback(lambda _future: _forget_agent_future(run_id, future))
        except Exception as exc:
            store.finish_agent_run(run_id, "failed", "Unable to start agent worker")
            with lab_db.lock:
                background_agent.decide_finalization(lab_db.connection, run_id, "failed", "Unable to start agent worker", {})
                background_agent.transition(lab_db.connection, run_id, "failed", {"error": "Unable to start agent worker"})
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
            raise HTTPException(status_code=503, detail="Unable to start agent worker") from exc
        return {"run_id": run_id, "status": "running"}

    def run_agent(run_id, request_text, workspace, stop_event, plan_id=None):
        import uuid
        worker_token = uuid.uuid4().hex
        with lab_db.lock:
            claimed = background_agent.claim(lab_db.connection, run_id, worker_token)
        if not claimed:
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return
        def progress(event_type, payload):
            with lab_db.lock:
                background_agent.event(lab_db.connection, run_id, event_type, payload)
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
            with lab_db.lock:
                background_agent.transition(lab_db.connection, run_id, "awaiting_approval", {"tool_name": name, "arguments": arguments})
            deadline = datetime.now(timezone.utc).timestamp() + 600
            while not decision.wait(timeout=0.25):
                if stop_event.is_set() or shutting_down.is_set() or datetime.now(timezone.utc).timestamp() >= deadline:
                    break
            with approval_guard:
                pending_approvals.pop(approval_id, None)
            with lab_db.lock:
                task = background_agent.get(lab_db.connection, run_id)
                if task and task["status"] not in {"cancel_requested", "interrupted"}:
                    background_agent.transition(lab_db.connection, run_id, "running", {"approval": "resolved"})
            store.update_agent_run_metadata(run_id, {"lifecycle": "executing",
                                                      "pending_approval_id": None})
            return bool(item["approved"]) and not stop_event.is_set() and not shutting_down.is_set()

        try:
            conversation_id = assistant.new_conversation("Agent: " + request_text[:80])
            store.update_agent_run_metadata(run_id, {"conversation_id": conversation_id})
            agent = CodingAgent(assistant, workspace, config.allowed_commands)
            if plan_id is None:
                agent.run(conversation_id, request_text, approval, run_id=run_id,
                          stop_event=stop_event, on_progress=progress)
            else:
                with lab_db.lock:
                    plan = orchestration.get_plan(lab_db.connection, plan_id)
                for step in plan["steps"]:
                    if stop_event.is_set() or shutting_down.is_set():
                        raise RuntimeError("Orchestrated plan cancelled at a safe step boundary")
                    with lab_db.lock:
                        orchestration.start_step(lab_db.connection, plan_id, step["id"])
                    with lab_db.lock:
                        orchestration.record_event(lab_db.connection, plan_id, "step_progress",
                            {"title": step["title"], "verification": step["verification"]}, step["id"])
                    step_request = (
                        "Execute exactly this approved plan step as part of the user's larger request. "
                        "Do not perform work belonging to later steps.\n\n"
                        "Original user request:\n" + request_text[:12000] +
                        "\n\nApproved step " + str(step["position"] + 1) + ": " + step["title"] +
                        "\nDescription: " + step["description"] +
                        "\nExpected outcome: " + step["expected_outcome"] +
                        "\nVerification required: " + step["verification"] +
                        "\n\nInspect before changing files. Every write and command still requires user approval."
                    )
                    step_result = agent.run(conversation_id, step_request, approval, run_id=run_id,
                        stop_event=stop_event, on_progress=progress, finalize_run=False)
                    step_status = step_result.get("status")
                    step_outcome = "completed" if step_status == "completed" else "interrupted" if step_status == "cancelled" else "failed"
                    with lab_db.lock:
                        orchestration.finish_step(lab_db.connection, plan_id, step["id"], step_outcome,
                            step_result.get("content", step_status or "No result"))
                    if step_outcome != "completed":
                        raise RuntimeError("Plan stopped because step '" + step["title"] + "' did not complete")
                store.finish_agent_run(run_id, "completed", "All approved plan steps completed.")
            # Serialize cancellation against terminal completion. If cancellation
            # wins this lock, it wins the final state; if completion wins, later
            # cancellation sees a terminal task and is rejected.
            with agent_registry_guard:
                final = store.get_agent_run(run_id)
                if stop_event.is_set() and final and final["status"] != "interrupted":
                    store.finish_agent_run(run_id, "cancelled", "Cancellation was requested before terminal completion.")
                final = store.get_agent_run(run_id)
                final_status = final["status"] if final else "failed"
                target = final_status if final_status in {"completed", "failed", "cancelled"} else "failed"
                with lab_db.lock:
                    background_agent.decide_finalization(lab_db.connection, run_id, target,
                        final["summary"] if final else "", {"plan_id": plan_id})
                    task = background_agent.get(lab_db.connection, run_id)
                    if task and task["status"] not in {"interrupted"}:
                        background_agent.transition(lab_db.connection, run_id, target, {"summary": final["summary"] if final else ""})
                    if plan_id and task:
                        plan = orchestration.get_plan(lab_db.connection, plan_id)
                        if plan and plan["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
                            outcome = "completed" if target == "completed" else "cancelled" if target == "cancelled" else "failed"
                            orchestration.finish_plan(lab_db.connection, plan_id, outcome, final["summary"] if final else "")
        except Exception as exc:
            target = "cancelled" if stop_event.is_set() else "failed"
            store.finish_agent_run(run_id, target, f"{type(exc).__name__}: {exc}")
            with lab_db.lock:
                background_agent.decide_finalization(lab_db.connection, run_id, target,
                    f"{type(exc).__name__}: {exc}", {"plan_id": plan_id})
                task = background_agent.get(lab_db.connection, run_id)
                if task and task["status"] not in {"interrupted"}:
                    background_agent.transition(lab_db.connection, run_id, target, {"error": f"{type(exc).__name__}: {exc}"})
                if plan_id:
                    plan = orchestration.get_plan(lab_db.connection, plan_id)
                    if plan and plan["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
                        orchestration.finish_plan(lab_db.connection, plan_id, target, str(exc))
        finally:
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)

    @app.post("/api/v1/agents/{run_id}/cancel")
    def cancel_agent(run_id: str):
        # Same lock order as worker finalization prevents a late cancellation
        # from racing a completed terminal state.
        with agent_registry_guard:
            with lab_db.lock:
                task = background_agent.get(lab_db.connection, run_id)
                if task is None:
                    raise HTTPException(status_code=404, detail="Background agent task not found")
                previous_status = task["status"]
                if not background_agent.request_cancel(lab_db.connection, run_id):
                    return {"cancelled": False, "status": task["status"]}
                if previous_status == "queued":
                    store.finish_agent_run(run_id, "cancelled", "Cancelled before execution began.")
                    background_agent.decide_finalization(lab_db.connection, run_id, "cancelled", "Cancelled before execution began.", {})
                    background_agent.transition(lab_db.connection, run_id, "cancelled", {"reason": "Cancelled before worker claim"})
                    plan_row = lab_db.connection.execute("SELECT id FROM agent_plans WHERE run_id=?", (run_id,)).fetchone()
                    if plan_row:
                        orchestration.finish_plan(lab_db.connection, plan_row["id"], "cancelled",
                                                  "Cancelled before worker claim.")
            stop_event = agent_stop_events.get(run_id)
            if stop_event:
                stop_event.set()
        with approval_guard:
            for item in pending_approvals.values():
                if item["run_id"] == run_id:
                    item["approved"] = False
                    item["decision"].set()
        return {"cancelled": True, "status": "cancelled" if previous_status == "queued" else "cancel_requested"}

    @app.get("/api/v1/agents/{run_id}/events")
    def agent_background_events(run_id: str, after_id: int = 0, limit: int = 200):
        with lab_db.lock:
            if background_agent.get(lab_db.connection, run_id) is None:
                raise HTTPException(status_code=404, detail="Background agent task not found")
            return background_agent.events(lab_db.connection, run_id, after_id, limit)

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
            # Create and reserve in the same critical section too, so even a
            # second local client cannot delete the new conversation in between.
            with locks_guard:
                conversation_id = assistant.new_conversation()
                reservation = {"lock": threading.Lock(), "users": 1}
                conversation_locks[conversation_id] = reservation
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

        # Reserve before the SSE generator queues the worker, protecting queued
        # work as well as provider calls already in progress.
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
                            "finish_reason": result.get("finish_reason"),
                            "truncated": bool(result.get("truncated", False)),
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
        with agent_registry_guard:
            stop_events = list(agent_stop_events.values())
        for stop_event in stop_events:
            stop_event.set()
        # Never leave an agent worker blocked on a browser approval while the
        # executor is waiting to drain during application shutdown.
        with approval_guard:
            for item in pending_approvals.values():
                item["approved"] = False
                item["decision"].set()
            pending_approvals.clear()
        execution_executor.shutdown(wait=True, cancel_futures=False)
        executor.shutdown(wait=True, cancel_futures=False)
        assistant.close()
        lab_db.close()

    return app
