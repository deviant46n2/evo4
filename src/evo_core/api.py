"""Loopback-only HTTP API for the Evo desktop client."""
import asyncio
from datetime import datetime, timezone
import json
import threading
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .assistant import EvoAssistant
from .runtime_binding import (
    RegistryDispatchDisabledError,
    RuntimeBindingError,
    build_workspace_runtime,
)
from .runtime_invocation_snapshots import (
    RuntimeSnapshotError,
    assert_runtime_matches_snapshot,
    create_runtime_invocation_snapshot,
)
from .coding_agent import CodingAgent
from .task_workspaces import (
    create_task_workspace,
    get_task_workspace_operation_status,
    list_task_workspace_operations,
    get_task_workspace_review,
    get_task_workspace_fingerprint,
    TaskWorkspaceConflictError,
    TaskWorkspaceProvisioningError,
    TaskWorkspaceValidationError,
)
from .task_workspace_files import (
    list_task_workspace_files, read_task_workspace_file,
    apply_task_workspace_file, list_task_workspace_file_changes,
)
from . import background_agent, lifecycle, orchestration
from . import workspaces as workspace_registry
from .config import load_config
from .command_policy import CommandPolicyError, effective_project_command_prefixes
from .store import EvoStore
from . import platform_registry
from .memory_review import find_duplicate_candidates
from .demo_data import seed_demo_data, demo_data_status, clear_demo_data
from evo_experiments.monitor import sample_nvidia_smi
from evo_experiments.db import ResultsDB
from evo_experiments.intelligence import assess_workload, discover_runtimes, estimate_runtime, initialize_profiles, list_profiles, save_profile
from evo_experiments.scheduler import initialize_scheduler, create_job, list_jobs, dispatch_jobs, start_job, finish_job, cancel_job
from evo_experiments.execution import initialize_execution, register_execution, list_executions, run_execution, recover_interrupted_executions


_BACKEND_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _git_value(args, timeout=2.0):
    try:
        result = subprocess.run(
            ["git", *args], text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _backend_identity():
    build_id = (os.environ.get("EVO_BUILD_ID") or os.environ.get("EVO_REVISION") or "").strip() or None
    revision = None
    dirty = None
    if build_id is not None:
        revision = "env:" + build_id
    else:
        sha = _git_value(["rev-parse", "HEAD"])
        if sha is not None:
            revision = "git:" + sha
            porcelain = _git_value(["status", "--porcelain"])
            dirty = bool(porcelain)
        else:
            revision = "unknown"
    return {
        "backend_started_at": _BACKEND_STARTED_AT,
        "backend_revision": revision,
        "backend_build_id": build_id,
        "backend_dirty": dirty,
    }


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=200000)
    project_id: str | None = None
    workspace_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=120)
    project_id: str | None = None
    workspace_id: str | None = None


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    category: str = Field(default="general", max_length=80)
    source: str = Field(default="user", max_length=80)
    confidence: float = Field(default=1.0, ge=0, le=1)
    project_id: str | None = None
    workspace_id: str | None = None


class MemorySupersede(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    reason: str = Field(default="", max_length=2000)


class AgentCreate(BaseModel):
    request: str = Field(min_length=1, max_length=20000)
    workspace_id: str = Field(min_length=1, max_length=128)
    isolate_workspace: bool = False


class AgentApproval(BaseModel):
    approved: bool


class TaskWorkspaceFileApply(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    content: str = Field(min_length=0, max_length=1048576)
    expected_sha256: str | None = None
    approved: bool = False


class AgentPlanCreate(BaseModel):
    request: str = Field(min_length=1, max_length=12000)
    workspace_id: str = Field(min_length=1, max_length=128)

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
    try:
        platform_registry.initialize_platform_registry(store)
    except Exception:
        store.db.close()
        raise
    lab_db = ResultsDB(config.database)
    assistant = EvoAssistant(config, store=store)
    app = FastAPI(title="Evo 4 Local API", version="0.1.0")
    from .platform_registry_api import build_configuration_router
    app.include_router(build_configuration_router(store))
    from .project_checkouts_api import build_project_checkout_router
    app.include_router(build_project_checkout_router(store))
    from .workspaces_api import build_workspace_router
    app.include_router(build_workspace_router(store))
    from .project_provisioning_api import build_project_provisioning_router
    app.include_router(build_project_provisioning_router(store))
    app.state.config = config
    app.state.store = store
    app.state.lab_db = lab_db
    app.state.assistant = assistant
    backend_identity = _backend_identity()
    app.state.backend_identity = backend_identity
    initialize_profiles(lab_db.connection)
    initialize_scheduler(lab_db.connection)
    initialize_execution(lab_db.connection)
    background_agent.initialize(lab_db.connection)
    orchestration.initialize(lab_db.connection)
    with lab_db.lock:
        recover_interrupted_executions(lab_db.connection)
    # Converge every lifecycle record onto one durable terminal decision. This is
    # repeatable: already-repaired records are left alone and completed records
    # are never downgraded. Nothing is replayed and no process is signalled.
    # Background tasks and plans are intentionally not pre-finalized here; the
    # reconciler owns their terminal convergence from durable evidence.
    lifecycle.initialize(lab_db.connection)
    app.state.lifecycle_report = lifecycle.reconcile(store, lab_db)

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

    def _resolve_workspace_for_execution(workspace_id):
        try:
            return workspace_registry.resolve_executable_workspace(store, workspace_id)
        except workspace_registry.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except workspace_registry.WorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except workspace_registry.WorkspaceRelationshipError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except workspace_registry.WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _build_workspace_runtime_for_request(workspace_id):
        try:
            runtime = build_workspace_runtime(store, config, workspace_id)
            runtime.assert_current(store)
        except workspace_registry.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeBindingError, workspace_registry.WorkspaceValidationError,
                workspace_registry.WorkspaceRelationshipError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return runtime

    def _record_workspace_invocation(runtime, invocation_kind):
        try:
            return create_runtime_invocation_snapshot(
                store, runtime, invocation_id=str(uuid4()),
                invocation_kind=invocation_kind,
            )
        except (RuntimeBindingError, RuntimeSnapshotError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _require_workspace_dispatch(runtime):
        try:
            runtime.require_dispatch_enabled()
        except RegistryDispatchDisabledError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _create_task_execution_workspace(parent_workspace_id, task_id):
        try:
            return create_task_workspace(
                store, parent_workspace_id, task_id, config.workspace_root,
            )
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TaskWorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TaskWorkspaceProvisioningError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Task workspace provisioning requires recovery",
                    "operation_id": exc.operation_id,
                    "status": exc.status,
                },
            ) from exc

    @app.get("/api/v1/task-workspaces")
    def task_workspace_operations(project_id: str | None = None,
                                  status: str | None = None,
                                  limit: int = 100):
        try:
            items = list_task_workspace_operations(
                store, project_id=project_id, status=status, limit=limit,
            )
            return {"items": items, "total": len(items)}
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace listing failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.get("/api/v1/task-workspaces/{operation_id}")
    def task_workspace_operation(operation_id: str):
        try:
            return get_task_workspace_operation_status(store, operation_id)
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace inspection failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.get("/api/v1/task-workspaces/{operation_id}/files")
    def task_workspace_files(operation_id: str, path: str = "", limit: int = 200):
        try:
            return list_task_workspace_files(store, operation_id, path=path, limit=limit)
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace file listing failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.get("/api/v1/task-workspaces/{operation_id}/file")
    def task_workspace_file(operation_id: str, path: str, max_bytes: int = 262144):
        try:
            return read_task_workspace_file(store, operation_id, path, max_bytes=max_bytes)
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace file read failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.post("/api/v1/task-workspaces/{operation_id}/file")
    def apply_task_workspace_file_route(operation_id: str, request: TaskWorkspaceFileApply):
        try:
            return apply_task_workspace_file(
                store, operation_id, request.path,
                request.content, expected_sha256=request.expected_sha256,
                approved=request.approved,
            )
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace file apply failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.get("/api/v1/task-workspaces/{operation_id}/changes")
    def task_workspace_file_changes(operation_id: str, limit: int = 100):
        try:
            return list_task_workspace_file_changes(store, operation_id, limit=limit)
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace file change listing failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    def _task_workspace_execution_evidence(operation):
        """Join isolated-workspace reviews to only the runs and plans that own them."""
        with store.lock:
            rows = store.db.execute(
                """SELECT id,kind,status,started_at,finished_at,summary,metadata_json
                   FROM agent_runs
                   WHERE json_valid(metadata_json)
                     AND json_type(metadata_json, '$')='object'
                     AND json_extract(metadata_json, '$.task_workspace_operation_id')=?
                   ORDER BY started_at DESC LIMIT 20""",
                (operation["operation_id"],),
            ).fetchall()
        from evo_experiments.execution import get_execution, managed_executions_for_parent

        def matching_managed_execution(execution_id, command, run_id):
            if not isinstance(execution_id, str) or not execution_id:
                return None
            with lab_db.lock:
                record = get_execution(lab_db.connection, execution_id)
            if record is None or (
                record.get("agent_run_id") != run_id
                or record.get("workspace_id") != operation.get("task_workspace_id")
                or record.get("project_id") != operation.get("project_id")
                or record.get("source_revision") != operation.get("source_revision")
                or record.get("workspace") != operation.get("destination_path")
                or record.get("argv") != command
            ):
                return None
            approval = record.get("approval_evidence") or {}
            return {
                "id": record["id"],
                "status": record.get("status"),
                "argv": record.get("argv"),
                "effective_command_policy": record.get("allowed_commands"),
                "working_directory": record.get("workspace"),
                "source_revision": record.get("source_revision"),
                "timeout_seconds": record.get("timeout_seconds"),
                "requested_at": record.get("requested_at"),
                "started_at": record.get("started_at"),
                "finished_at": record.get("finished_at"),
                "returncode": record.get("returncode"),
                "elapsed_seconds": record.get("elapsed_seconds"),
                "approval_source": approval.get("approval_source"),
                "approved_at": approval.get("approved_at"),
                "argv_sha256": approval.get("argv_sha256"),
            }

        evidence = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if (
                metadata.get("task_workspace_operation_id") != operation["operation_id"]
                or metadata.get("project_id") != operation["project_id"]
                or metadata.get("workspace_id") != operation.get("task_workspace_id")
                or metadata.get("task_workspace_source_revision") != operation["source_revision"]
            ):
                continue
            item = {
                "run_id": row["id"], "kind": row["kind"], "status": row["status"],
                "started_at": row["started_at"], "finished_at": row["finished_at"],
                "summary": row["summary"],
                "verification_state": metadata.get("verification_state", "not_available"),
                "successful_file_writes": metadata.get("successful_file_writes"),
                "plan_id": None, "plan_status": None, "verification_summary": None,
                "managed_executions": [],
                "steps": [],
            }
            # Include only executions whose complete persisted provenance matches
            # this task workspace and the owning agent run.
            with lab_db.lock:
                executions = managed_executions_for_parent(lab_db.connection, row["id"])
            executions = [
                execution for execution in executions
                if (
                    execution.get("agent_run_id") == row["id"]
                    and execution.get("workspace_id") == operation.get("task_workspace_id")
                    and execution.get("project_id") == operation.get("project_id")
                    and execution.get("source_revision") == operation.get("source_revision")
                    and execution.get("workspace") == operation.get("destination_path")
                )
            ]
            item["managed_executions_omitted"] = max(0, len(executions) - 10)
            executions = executions[-10:]
            def bounded_execution_output(value, limit=8192):
                data = str(value or "").encode("utf-8", errors="replace")
                truncated = len(data) > limit
                if truncated:
                    data = data[-limit:]
                return data.decode("utf-8", errors="replace"), truncated
            for execution in executions:
                approval = execution.get("approval_evidence") or {}
                stdout, stdout_truncated = bounded_execution_output(execution.get("stdout", ""))
                stderr, stderr_truncated = bounded_execution_output(execution.get("stderr", ""))
                item["managed_executions"].append({
                    "id": execution["id"],
                    "status": execution.get("status"),
                    "argv": execution.get("argv", []),
                    "effective_command_policy": execution.get("allowed_commands", []),
                    "working_directory": execution.get("workspace"),
                    "source_revision": execution.get("source_revision"),
                    "timeout_seconds": execution.get("timeout_seconds"),
                    "requested_at": execution.get("requested_at"),
                    "started_at": execution.get("started_at"),
                    "finished_at": execution.get("finished_at"),
                    "returncode": execution.get("returncode"),
                    "elapsed_seconds": execution.get("elapsed_seconds"),
                    "stdout": stdout,
                    "stdout_truncated": stdout_truncated,
                    "stderr": stderr,
                    "stderr_truncated": stderr_truncated,
                    "error": execution.get("error", ""),
                    "approval_source": approval.get("approval_source"),
                    "approved_at": approval.get("approved_at"),
                    "argv_sha256": approval.get("argv_sha256"),
                })
            plan_id = metadata.get("plan_id")
            if isinstance(plan_id, str) and plan_id:
                with lab_db.lock:
                    plan = orchestration.get_plan(lab_db.connection, plan_id)
                if (
                    plan is not None and plan.get("run_id") == row["id"]
                    and plan.get("project_id") == operation["project_id"]
                    and plan.get("workspace_id") == operation.get("parent_workspace_id")
                    and metadata.get("parent_workspace_id") == operation.get("parent_workspace_id")
                ):
                    item["plan_id"] = plan_id
                    item["plan_status"] = plan["status"]
                    item["verification_summary"] = plan["verification_summary"]
                    item["verification_evidence_summary"] = plan["verification_evidence_summary"]
                    item["verification_state"] = orchestration.plan_verification_state(plan["steps"])
                    item["steps"] = [{
                        "step_id": step["id"], "position": step["position"],
                        "title": step["title"], "status": step["status"],
                        "verification_status": step["verification_status"],
                        "verification_checks": [{
                            "id": check["id"], "command": check["command"],
                            "status": check["status"], "exit_code": check["exit_code"],
                            "created_at": check["created_at"],
                            "execution_id": check.get("execution_id"),
                            "managed_execution": matching_managed_execution(
                                check.get("execution_id"), check["command"], row["id"]),
                            "workspace_fingerprint_before": check.get("workspace_fingerprint_before"),
                            "workspace_fingerprint_after": check.get("workspace_fingerprint_after"),
                            "workspace_snapshot_stable": (None if check.get("workspace_snapshot_stable") is None else bool(check.get("workspace_snapshot_stable"))),
                            "stdout": bounded_execution_output(check.get("stdout", ""))[0],
                            "stdout_truncated": bool(check.get("stdout_truncated")) or bounded_execution_output(check.get("stdout", ""))[1],
                            "stderr": bounded_execution_output(check.get("stderr", ""))[0],
                            "stderr_truncated": bool(check.get("stderr_truncated")) or bounded_execution_output(check.get("stderr", ""))[1],
                        } for check in step.get("verification_checks", [])],
                    } for step in plan["steps"]]
            evidence.append(item)
        return evidence

    @app.get("/api/v1/task-workspaces/{operation_id}/review")
    def task_workspace_review(operation_id: str):
        try:
            review = get_task_workspace_review(store, operation_id)
            operation = get_task_workspace_operation_status(store, operation_id)
            review["execution_evidence"] = _task_workspace_execution_evidence(operation)
            return review
        except TaskWorkspaceValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (workspace_registry.WorkspaceNotFoundError,
                workspace_registry.WorkspaceRelationshipError) as exc:
            raise HTTPException(status_code=404, detail="Task workspace binding not found") from exc
        except TaskWorkspaceProvisioningError as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace review provisioning failed")
            raise HTTPException(status_code=503, detail="Task workspace review is temporarily unavailable") from exc
        except Exception as exc:
            import logging
            logging.getLogger("evo.api").exception("task workspace review failed")
            raise HTTPException(status_code=500, detail="internal error") from exc

    @app.get("/api/v1/workspaces/{workspace_id}/runtime-binding")
    def workspace_runtime_binding_info(workspace_id: str):
        """Expose only non-secret runtime identity needed for operator policy setup."""
        runtime = _build_workspace_runtime_for_request(workspace_id)
        from .provider_endpoint import normalize_provider_origin
        from .provider_approvals import find_provider_approval
        origin = normalize_provider_origin(
            f"{urlsplit(runtime.bound_participant.endpoint).scheme}://"
            f"{urlsplit(runtime.bound_participant.endpoint).netloc}"
        )
        approval = find_provider_approval(
            config.provider_approvals, origin,
            runtime.participant.adapter_id, "chat_completion",
        )
        return {
            "workspace_id": runtime.workspace_id,
            "project_id": runtime.project_id,
            "configuration_id": runtime.configuration_id,
            "configuration_revision_id": runtime.revision_id,
            "revision_hash": runtime.revision_hash,
            "participant_id": runtime.participant.participant_id,
            "integration_id": runtime.participant.integration_id,
            "adapter_id": runtime.participant.adapter_id,
            "model": runtime.participant.display_name,
            "origin": origin,
            "dispatch_enabled": runtime.dispatch_enabled,
            "provider_budget_configured": any(
                item.integration_id == runtime.participant.integration_id
                for item in config.provider_budgets
            ),
            "local_resource_profile_configured": any(
                integration_id == runtime.participant.integration_id
                for integration_id, _profile in config.local_resource_profiles
            ),
            "provider_approval_status": approval.status if approval is not None else "unknown",
        }

    @app.get("/api/v1/workspaces/{workspace_id}/participants")
    def workspace_participants(workspace_id: str):
        """List the non-secret participant contracts bound to this exact workspace revision."""
        runtime = _build_workspace_runtime_for_request(workspace_id)
        participants = []
        for descriptor in runtime.participants:
            participants.append({
                "participant_id": descriptor.participant_id,
                "integration_id": descriptor.integration_id,
                "participant_type": descriptor.participant_type,
                "display_name": descriptor.display_name,
                "adapter_id": descriptor.adapter_id,
                "adapter_contract_version": descriptor.adapter_contract_version,
                "adapter_implementation_version": descriptor.adapter_implementation_version,
                "capabilities": list(descriptor.capabilities),
                "input_contract_versions": list(descriptor.input_contract_versions),
                "output_contract_versions": list(descriptor.output_contract_versions),
                "execution_location": descriptor.execution_location,
                "availability": descriptor.availability,
                "availability_observed_at": descriptor.availability_observed_at,
                "resource_requirements": dict(descriptor.resource_requirements),
                "limits": dict(descriptor.limits),
                "configuration_id": descriptor.configuration_id,
                "configuration_revision_id": descriptor.configuration_revision_id,
                "component_key": descriptor.component_key,
                "component_version": descriptor.component_version,
                "compliance_reference": descriptor.compliance_reference,
            })
        return {
            "workspace_id": runtime.workspace_id,
            "project_id": runtime.project_id,
            "configuration_id": runtime.configuration_id,
            "configuration_revision_id": runtime.revision_id,
            "revision_hash": runtime.revision_hash,
            "dispatch_enabled": runtime.dispatch_enabled,
            "participants": participants,
        }

    @app.get("/api/v1/workspaces/{workspace_id}/participants/{participant_id}/availability")
    def workspace_participant_availability(
        workspace_id: str, participant_id: str, timeout_seconds: int = 3,
    ):
        """Perform bounded, ephemeral metadata preflight; never issue a completion."""
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 10:
            raise HTTPException(status_code=422, detail="timeout_seconds must be between 1 and 10")
        runtime = _build_workspace_runtime_for_request(workspace_id)
        descriptor = next(
            (item for item in runtime.participants if item.participant_id == participant_id),
            None,
        )
        if descriptor is None:
            raise HTTPException(status_code=404, detail="participant is not bound to this workspace revision")
        bindings = {
            getattr(bound, "participant_id", None): (adapter, bound)
            for adapter, bound in runtime.participant_bindings
        }
        binding = bindings.get(participant_id)
        if binding is None:
            raise HTTPException(status_code=409, detail="participant binding is unavailable")
        adapter, bound = binding
        if descriptor.adapter_id == "evo_deterministic_verifier":
            # This adapter is local code, not a remote service. Its presence in
            # the freshly built immutable runtime is the only availability check.
            return {
                "workspace_id": runtime.workspace_id,
                "participant_id": participant_id,
                "availability": "available",
                "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "probe_kind": "local_binding",
                "probe_performed": False,
                "transport_reachable": None,
                "model_advertised": None,
                "completion_verified": None,
                "ephemeral": True,
            }
        preflight = getattr(adapter, "preflight", None)
        if not callable(preflight):
            raise HTTPException(status_code=501, detail="participant adapter has no metadata preflight")
        try:
            evidence = preflight(bound, timeout_seconds=timeout_seconds)
        except Exception as exc:
            # Do not return provider exception text, which may contain endpoint
            # details or other integration diagnostics.
            raise HTTPException(status_code=502, detail="participant metadata preflight failed safely") from exc
        # A metadata-only model-list response cannot establish that a
        # completion will succeed. Keep the participant unavailable when the
        # endpoint/model is explicitly absent; otherwise completion availability
        # remains unknown until a separately admitted operator probe verifies it.
        state = (
            "unavailable"
            if evidence.transport_reachable is False or evidence.model_advertised is False
            else "unknown"
        )
        return {
            "workspace_id": runtime.workspace_id,
            "participant_id": participant_id,
            "availability": state,
            "metadata_preflight": (
                "model_advertised"
                if evidence.transport_reachable is True and evidence.model_advertised is True
                else "not_advertised"
                if evidence.model_advertised is False
                else "reachable_unverified"
                if evidence.transport_reachable is True
                else "unknown"
            ),
            "transport_reachable": evidence.transport_reachable,
            "model_advertised": evidence.model_advertised,
            "completion_verified": None,
            "observed_at_utc": evidence.observed_at_utc,
            "evidence_reference": evidence.evidence_reference,
            "probe_kind": "metadata_only",
            "probe_performed": True,
            "timeout_seconds": timeout_seconds,
            "ephemeral": True,
        }

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
        identity = backend_identity
        return {
            "status": "ok",
            "provider": config.provider_name,
            "model": config.model,
            "endpoint": safe_endpoint,
            "backend_started_at": identity["backend_started_at"],
            "backend_revision": identity["backend_revision"],
            "backend_build_id": identity["backend_build_id"],
            "backend_dirty": identity["backend_dirty"],
            "build": identity,
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


    def _memory_scope_filter(project_id, workspace_id):
        if project_id is None:
            return "(project_id IS NULL AND workspace_id IS NULL)", []
        if workspace_id is None:
            return "((project_id IS NULL AND workspace_id IS NULL) OR (project_id=? AND workspace_id IS NULL))", [project_id]
        return (
            "((project_id IS NULL AND workspace_id IS NULL) OR "
            "(project_id=? AND workspace_id IS NULL) OR (project_id=? AND workspace_id=?))",
            [project_id, project_id, workspace_id],
        )

    @app.get("/api/v1/memories")
    def memories(q: str | None = None, status: str = "active", limit: int = 100,
                 project_id: str | None = None, workspace_id: str | None = None):
        bounded = min(max(limit, 1), 200)
        if status not in {"active", "archived", "superseded"}:
            raise HTTPException(status_code=422, detail="Invalid memory status")
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scope_sql, scope_params = _memory_scope_filter(project_id, workspace_id)
        with store.lock:
            params = [status] + scope_params
            sql = "SELECT * FROM memories WHERE status=? AND " + scope_sql
            if q and q.strip():
                pattern = "%" + q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                sql += " AND (content LIKE ? ESCAPE '!' OR category LIKE ? ESCAPE '!' OR tags_json LIKE ? ESCAPE '!')"
                params.extend((pattern, pattern, pattern))
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(bounded)
            rows = store.db.execute(sql, params).fetchall()
        return [{
            "id": row["id"], "content": row["content"], "category": row["category"],
            "tags": json.loads(row["tags_json"] or "[]"), "source": row["source"],
            "confidence": row["confidence"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "access_count": row["access_count"],
        } for row in rows]

    @app.get("/api/v1/memories/review")
    def memory_review(limit: int = 20, project_id: str | None = None, workspace_id: str | None = None):
        bounded = min(max(limit, 1), 50)
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scope_sql, scope_params = _memory_scope_filter(project_id, workspace_id)
        with store.lock:
            rows = store.db.execute(
                "SELECT id,content,category,source,confidence,updated_at FROM memories "
                "WHERE status='active' AND " + scope_sql + " ORDER BY updated_at DESC LIMIT 500",
                scope_params,
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
    def memory_search_preview(q: str, limit: int = 8, project_id: str | None = None, workspace_id: str | None = None):
        if not q.strip():
            raise HTTPException(status_code=422, detail="Search query cannot be empty")
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
            rows = store.search_memories(q, min(max(limit, 1), 20), record_access=False,
                                        project_id=project_id, workspace_id=workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            project_id, workspace_id = store.validate_scope(payload.project_id, payload.workspace_id)
            memory_id = store.add_memory(payload.content, payload.category, source=payload.source,
                                         confidence=payload.confidence, project_id=project_id,
                                         workspace_id=workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": memory_id}

    @app.get("/api/v1/memory-candidates")
    def memory_candidates(limit: int = 100, project_id: str | None = None, workspace_id: str | None = None):
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
            rows = store.list_memory_candidates("pending", min(max(limit, 1), 200),
                                                 project_id=project_id, workspace_id=workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [{
            "id": row["id"], "content": row["content"], "category": row["category"],
            "source": row["source"], "confidence": row["confidence"],
            "created_at": row["created_at"], "conversation_id": row["conversation_id"],
        } for row in rows]

    @app.post("/api/v1/memory-candidates/{candidate_id}/review")
    def review_memory_candidate(candidate_id: str, payload: AgentApproval,
                                project_id: str | None = None, workspace_id: str | None = None):
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
            result = store.review_memory_candidate(candidate_id, payload.approved,
                                                   project_id=project_id, workspace_id=workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Pending memory candidate not found")
        return {"accepted": bool(payload.approved), "memory_id": result if payload.approved else None}

    @app.post("/api/v1/memories/{memory_id}/supersede")
    def supersede_memory(memory_id: str, payload: MemorySupersede,
                         project_id: str | None = None, workspace_id: str | None = None):
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
            replacement_id = store.supersede_memory(
                memory_id, payload.content, source="user", confidence=1.0,
                reason=payload.reason, project_id=project_id, workspace_id=workspace_id)
        except ValueError as exc:
            message = str(exc)
            raise HTTPException(status_code=404 if "not found" in message.lower() else 422,
                                detail=message) from exc
        return {"id": replacement_id, "supersedes": memory_id}

    @app.post("/api/v1/memories/{memory_id}/archive")
    def archive_memory(memory_id: str, project_id: str | None = None, workspace_id: str | None = None):
        try:
            project_id, workspace_id = store.validate_scope(project_id, workspace_id)
            archived = store.archive_memory(memory_id, project_id=project_id, workspace_id=workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not archived:
            raise HTTPException(status_code=404, detail="Active memory not found")
        return {"archived": True, "id": memory_id}



    def _validated_api_scope(project_id=None, workspace_id=None):
        try:
            return store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _run_visible_in_scope(row, project_id, workspace_id):
        from .scope_validation import owned_scope_visible
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(metadata, dict):
            return False
        record_project = metadata.get("project_id")
        record_workspace = metadata.get("workspace_id")
        if record_workspace is not None and record_project is None:
            return False
        try:
            record_project, record_workspace = store.validate_scope(record_project, record_workspace)
        except ValueError:
            return False
        return owned_scope_visible(record_project, record_workspace, project_id, workspace_id)

    def _plan_visible_in_scope(plan, project_id, workspace_id):
        from .scope_validation import owned_scope_visible
        try:
            record_project, record_workspace = store.validate_scope(
                plan.get("project_id"), plan.get("workspace_id"))
        except ValueError:
            return False
        return owned_scope_visible(record_project, record_workspace, project_id, workspace_id)

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
    def agent_runs(limit: int = 50, status: str | None = None,
                   project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        rows = store.list_agent_runs(min(max(limit, 1), 100), status, project_id=project_id, workspace_id=workspace_id)
        return [serialize_run(row) for row in rows]

    @app.get("/api/v1/agents/{run_id:uuid}")
    def agent_run(run_id: UUID, project_id: str | None = None, workspace_id: str | None = None):
        run_id = str(run_id)
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        row = store.get_agent_run(run_id)
        if row is None or not _run_visible_in_scope(row, project_id, workspace_id):
            raise HTTPException(status_code=404, detail="Agent run not found in this scope")
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
    def agent_plans(limit: int = 50, project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        with lab_db.lock:
            rows = orchestration.list_plans(lab_db.connection, min(max(limit, 1), 100),
                                           project_id=project_id, workspace_id=workspace_id, store=store)
        return [dict(row) for row in rows]



    @app.post("/api/v1/agents/plans", status_code=201)
    def propose_agent_plan(payload: AgentPlanCreate):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        binding = _resolve_workspace_for_execution(payload.workspace_id)
        workspace_id = payload.workspace_id.strip()
        runtime = _build_workspace_runtime_for_request(workspace_id)
        workspace = binding["path"] if isinstance(binding, dict) else binding.path
        try:
            effective_allowed_commands = runtime.effective_allowed_commands
        except CommandPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        invocation = _record_workspace_invocation(runtime, "plan_proposal")
        _require_workspace_dispatch(runtime)
        try:
            proposal = orchestration.propose_with_model(
                runtime.assistant.provider, payload.request, str(workspace), max_tokens=min(runtime.assistant.config.max_tokens, 3000),
                allowed_commands=effective_allowed_commands)
            with lab_db.lock:
                plan = orchestration.create_plan(
                    lab_db.connection, payload.request, workspace_id, str(workspace), proposal,
                    allowed_commands=effective_allowed_commands,
                    project_id=binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None),
                    store=store, proposal_invocation_id=invocation["invocation_id"])
            return plan
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Unable to generate a plan: {type(exc).__name__}: {str(exc)[:300]}") from exc

    @app.get("/api/v1/agents/plans/{plan_id}")
    def agent_plan_detail(plan_id: str, project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
        if plan is None or not _plan_visible_in_scope(plan, project_id, workspace_id):
            raise HTTPException(status_code=404, detail="Agent plan not found in this scope")
        return plan

    @app.post("/api/v1/agents/plans/{plan_id}/approve")
    def approve_agent_plan(plan_id: str, project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        try:
            with lab_db.lock:
                plan = orchestration.get_plan(lab_db.connection, plan_id)
                if plan is None or not _plan_visible_in_scope(plan, project_id, workspace_id):
                    raise HTTPException(status_code=404, detail="Agent plan not found in this scope")
                return orchestration.approve_plan(lab_db.connection, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc



    def _finalize_agent_run(run_id, outcome, reason, plan_id=None):
        """Record one durable decision, then mirror it into dependent records.

        The decision is committed before any mirror update, so a crash between
        the two is repaired by the next startup reconciliation.
        """
        with lab_db.lock:
            result = lifecycle.decide(lab_db.connection, run_id, outcome,
                                      source="worker", reason=reason)
            decision = result["decision"]
        lifecycle.apply_decision(store, decision)
        with lab_db.lock:
            lifecycle.apply_background_from_decision(lab_db.connection, decision)
            if plan_id:
                lifecycle.apply_plan_decision(lab_db.connection, plan_id, decision)
        return decision

    @app.post("/api/v1/agents/plans/{plan_id}/execute", status_code=202)
    def execute_agent_plan(
        plan_id: str, project_id: str | None = None,
        workspace_id: str | None = None, isolate_workspace: bool = False,
    ):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
            if plan is None or not _plan_visible_in_scope(plan, project_id, workspace_id):
                raise HTTPException(status_code=404, detail="Agent plan not found in this scope")
            if plan["status"] != "approved":
                raise HTTPException(status_code=409, detail="Approve the plan before execution")
        workspace_id = plan.get("workspace_id")
        if not workspace_id:
            raise HTTPException(status_code=409, detail="Legacy plan has no registered workspace binding and cannot be executed")
        binding = _resolve_workspace_for_execution(workspace_id)
        runtime = _build_workspace_runtime_for_request(workspace_id)
        workspace_path = binding["path"] if isinstance(binding, dict) else binding.path
        plan_project_id = plan.get("project_id")
        binding_project_id = binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None)
        if plan_project_id != binding_project_id:
            raise HTTPException(status_code=409, detail="Plan workspace binding does not match its persisted project scope")
        try:
            effective_allowed_commands = runtime.effective_allowed_commands
        except CommandPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        from evo_experiments.execution import command_allowed
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Agent plan not found")
            if plan["status"] != "approved":
                raise HTTPException(status_code=409, detail="Approve the plan before execution")
            for step in plan["steps"]:
                commands = step.get("verification_commands") or []
                if not commands:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Plan step '{step['title']}' has no configured verification command and cannot be executed safely.",
                    )
                if any(not command_allowed(command, effective_allowed_commands) for command in commands):
                    raise HTTPException(
                        status_code=409,
                        detail=f"Plan step '{step['title']}' contains a verification command outside the current effective allowlist.",
                    )
            request_text = plan["request"]

        parent_workspace_id = workspace_id
        task_workspace_info = None
        # Admission must pass on the parent before provisioning can create a
        # detached worktree. The task runtime is checked again after binding.
        parent_invocation = _record_workspace_invocation(runtime, "plan_execution")
        _require_workspace_dispatch(runtime)
        invocation = parent_invocation
        if isolate_workspace:
            task_id = str(uuid4())
            task_workspace_info = _create_task_execution_workspace(parent_workspace_id, task_id)
            workspace_id = task_workspace_info["workspace"]["workspace_id"]
            binding = _resolve_workspace_for_execution(workspace_id)
            runtime = _build_workspace_runtime_for_request(workspace_id)
            workspace_path = binding["path"] if isinstance(binding, dict) else binding.path
            task_project_id = binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None)
            if task_project_id != plan_project_id:
                raise HTTPException(status_code=409, detail="Task workspace project does not match the approved plan")
            effective_allowed_commands = runtime.effective_allowed_commands
            invocation = _record_workspace_invocation(runtime, "plan_execution")
            _require_workspace_dispatch(runtime)
        run_metadata = {
            "invocation_id": invocation["invocation_id"],
            "proposal_invocation_id": plan.get("proposal_invocation_id"),
            "workspace_id": workspace_id,
            "project_id": binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None),
            "workspace": str(workspace_path), "model": runtime.assistant.config.model,
            "base_url": runtime.assistant.config.base_url,
            "request": request_text[:2000], "source": "approved-plan", "plan_id": plan_id,
        }
        if task_workspace_info is not None:
            run_metadata.update({
                "parent_workspace_id": parent_workspace_id,
                "task_id": task_workspace_info["task_id"],
                "task_workspace_operation_id": task_workspace_info["operation_id"],
                "task_workspace_source_revision": task_workspace_info["source_revision"],
            })
        with lab_db.lock:
            plan = orchestration.get_plan(lab_db.connection, plan_id)
            if plan is None:
                raise HTTPException(status_code=404, detail="Agent plan not found")
            if plan["status"] != "approved":
                raise HTTPException(status_code=409, detail="Approve the plan before execution")
            run_id = store.start_agent_run("orchestrated", run_metadata)
            background_agent.create(lab_db.connection, run_id)
            try:
                orchestration.attach_run(lab_db.connection, plan_id, run_id)
            except ValueError as exc:
                attached = False
                attach_error = exc
            else:
                attached = True
                attach_error = None
        if not attached:
            _finalize_agent_run(run_id, "failed", "Plan is not approved or has already been started", plan_id)
            raise HTTPException(status_code=409, detail="Plan is not approved or has already been started") from attach_error
        stop_event = threading.Event()
        with agent_registry_guard:
            agent_stop_events[run_id] = stop_event
        try:
            future = executor.submit(run_agent, run_id, request_text, workspace_id, stop_event, plan_id)
            with agent_registry_guard:
                agent_futures[run_id] = future
            future.add_done_callback(lambda _future: _forget_agent_future(run_id, future))
        except Exception as exc:
            _finalize_agent_run(run_id, "failed", "Unable to start orchestrated worker", plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
            raise HTTPException(status_code=503, detail="Unable to start orchestrated worker") from exc
        response = {"plan_id": plan_id, "run_id": run_id, "status": "running"}
        if task_workspace_info is not None:
            response.update({
                "workspace_id": workspace_id,
                "task_workspace_operation_id": task_workspace_info["operation_id"],
                "source_revision": task_workspace_info["source_revision"],
            })
        return response

    @app.post("/api/v1/agents", status_code=202)
    def start_agent(payload: AgentCreate):
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")
        parent_workspace_id = payload.workspace_id.strip()
        binding = _resolve_workspace_for_execution(parent_workspace_id)
        runtime = _build_workspace_runtime_for_request(parent_workspace_id)
        # Record the admission attempt against the parent before enforcing the
        # dispatch gate. A rejected request must not provision a task worktree.
        parent_invocation = _record_workspace_invocation(runtime, "coding_agent")
        _require_workspace_dispatch(runtime)
        task_workspace_info = None
        workspace_id = parent_workspace_id
        invocation = parent_invocation
        if payload.isolate_workspace:
            task_id = str(uuid4())
            task_workspace_info = _create_task_execution_workspace(parent_workspace_id, task_id)
            workspace_id = task_workspace_info["workspace"]["workspace_id"]
            binding = _resolve_workspace_for_execution(workspace_id)
            runtime = _build_workspace_runtime_for_request(workspace_id)
            # The worker must be pinned to a snapshot of the isolated runtime,
            # not merely the parent runtime used for admission.
            invocation = _record_workspace_invocation(runtime, "coding_agent")
            _require_workspace_dispatch(runtime)
        workspace = binding["path"] if isinstance(binding, dict) else binding.path
        run_metadata = {
            "invocation_id": invocation["invocation_id"],
            "workspace_id": workspace_id,
            "project_id": binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None),
            "workspace": str(workspace), "model": runtime.assistant.config.model,
            "base_url": runtime.assistant.config.base_url,
            "request": payload.request[:2000], "source": "desktop",
        }
        if task_workspace_info is not None:
            run_metadata.update({
                "parent_workspace_id": parent_workspace_id,
                "task_id": task_workspace_info["task_id"],
                "task_workspace_operation_id": task_workspace_info["operation_id"],
                "task_workspace_source_revision": task_workspace_info["source_revision"],
            })
        run_id = store.start_agent_run("coding", run_metadata)
        stop_event = threading.Event()
        with agent_registry_guard:
            agent_stop_events[run_id] = stop_event
        with lab_db.lock:
            background_agent.create(lab_db.connection, run_id)
        try:
            future = executor.submit(run_agent, run_id, payload.request, workspace_id, stop_event)
            with agent_registry_guard:
                agent_futures[run_id] = future
            future.add_done_callback(lambda _future: _forget_agent_future(run_id, future))
        except Exception as exc:
            _finalize_agent_run(run_id, "failed", "Unable to start agent worker")
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
            raise HTTPException(status_code=503, detail="Unable to start agent worker") from exc
        response = {"run_id": run_id, "status": "running"}
        if task_workspace_info is not None:
            response.update({
                "workspace_id": workspace_id,
                "task_workspace_operation_id": task_workspace_info["operation_id"],
                "source_revision": task_workspace_info["source_revision"],
            })
        return response

    def run_agent(run_id, request_text, workspace_id, stop_event, plan_id=None):
        import uuid
        worker_token = uuid.uuid4().hex
        workspace = None
        authoritative_workspace_id = None
        authoritative_project_id = None
        if isinstance(workspace_id, str) and workspace_id.strip():
            try:
                binding = workspace_registry.resolve_executable_workspace(store, workspace_id)
                workspace = binding["path"] if isinstance(binding, dict) else binding.path
                authoritative_workspace_id = binding.get("workspace_id") if isinstance(binding, dict) else getattr(binding, "workspace_id", None)
                authoritative_project_id = binding.get("project_id") if isinstance(binding, dict) else getattr(binding, "project_id", None)
            except Exception as exc:
                _finalize_agent_run(run_id, "failed", f"Workspace validation failed: {exc}", plan_id)
                with agent_registry_guard:
                    agent_stop_events.pop(run_id, None)
                    agent_futures.pop(run_id, None)
                return
        else:
            _finalize_agent_run(run_id, "failed", "Agent run has no registered workspace binding", plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return

        run_record = store.get_agent_run(run_id)
        if run_record is None:
            _finalize_agent_run(run_id, "failed", "Agent run record is missing", plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return
        run_metadata = {}
        metadata_error = None
        try:
            decoded = __import__("json").loads(run_record["metadata_json"] or "{}")
        except Exception:
            decoded = None
            metadata_error = "Agent run metadata is not valid JSON"
        if metadata_error is None and not isinstance(decoded, dict):
            metadata_error = "Agent run metadata is not a JSON object"
        if metadata_error is not None:
            _finalize_agent_run(run_id, "failed", metadata_error, plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return
        run_metadata = decoded
        metadata_workspace_id = run_metadata.get("workspace_id")
        metadata_project_id = run_metadata.get("project_id")
        if "workspace_id" not in run_metadata or "project_id" not in run_metadata:
            _finalize_agent_run(run_id, "failed", "Agent run metadata is missing required project/workspace scope", plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return
        if (metadata_workspace_id != authoritative_workspace_id
                or metadata_project_id != authoritative_project_id):
            _finalize_agent_run(
                run_id, "failed",
                "Agent run metadata scope does not match the resolved workspace binding",
                plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return

        try:
            runtime = build_workspace_runtime(store, config, workspace_id)
            runtime.assert_current(store)
            invocation_id = run_metadata.get("invocation_id")
            if not isinstance(invocation_id, str) or not invocation_id:
                raise RuntimeSnapshotError("Agent run has no runtime invocation snapshot reference")
            assert_runtime_matches_snapshot(
                store, runtime, invocation_id,
                expected_kind="plan_execution" if plan_id else "coding_agent",
            )
            runtime.require_dispatch_enabled()
            effective_allowed_commands = runtime.effective_allowed_commands
        except (RuntimeBindingError, RuntimeSnapshotError, RegistryDispatchDisabledError, CommandPolicyError) as exc:
            _finalize_agent_run(
                run_id, "failed", f"Workspace runtime binding is not dispatchable: {exc}", plan_id)
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            return

        conversation_project_id = authoritative_project_id
        conversation_workspace_id = authoritative_workspace_id

        with lab_db.lock:
            claimed = background_agent.claim(lab_db.connection, run_id, worker_token)
        if not claimed:
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)
            with lab_db.lock:
                decision = lifecycle.finalize_unclaimed(lab_db.connection, run_id)
            lifecycle.apply_decision(store, decision)
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
            conversation_id = runtime.assistant.new_conversation(
                "Agent: " + request_text[:80],
                project_id=conversation_project_id,
                workspace_id=conversation_workspace_id,
            )
            store.update_agent_run_metadata(run_id, {"conversation_id": conversation_id})
            agent = CodingAgent(
                runtime.assistant, workspace, effective_allowed_commands,
                task_workspace_operation_id=run_metadata.get("task_workspace_operation_id"),
            )
            if plan_id is None:
                agent.run(conversation_id, request_text, approval, run_id=run_id,
                          source_revision=run_metadata.get("task_workspace_source_revision"),
                          stop_event=stop_event, on_progress=progress,
                          project_id=conversation_project_id,
                          workspace_id=conversation_workspace_id)
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
                        source_revision=run_metadata.get("task_workspace_source_revision"),
                        stop_event=stop_event, on_progress=progress, finalize_run=False,
                        project_id=conversation_project_id,
                        workspace_id=conversation_workspace_id)
                    step_status = step_result.get("status")
                    agent_verification = step_result.get("verification", "not_configured")
                    if agent_verification not in {"passed", "failed", "not_run", "not_required", "not_configured"}:
                        agent_verification = "not_configured"
                    commands = step.get("verification_commands") or []
                    if commands:
                        verification_status = "passed"
                        if agent_verification == "failed":
                            verification_status = "failed"
                        for command in commands:
                            if stop_event.is_set() or shutting_down.is_set():
                                break
                            from evo_experiments.execution import command_allowed
                            if not command_allowed(command, effective_allowed_commands):
                                with lab_db.lock:
                                    orchestration.record_verification(lab_db.connection, plan_id, step["id"], command, "failed", None, "", "Verification command is not allowed by the effective project command policy.")
                                verification_status = "failed"
                                continue
                            approved = approval("run_command", {"argv": command, "timeout_seconds": 120})
                            if not approved:
                                with lab_db.lock:
                                    orchestration.record_verification(lab_db.connection, plan_id, step["id"], command, "denied", None, "", "Verification command was denied.")
                                verification_status = "failed"
                                continue
                            try:
                                from evo_experiments.execution import initialize_execution, register_managed_execution, run_execution
                                with lab_db.lock:
                                    initialize_execution(lab_db.connection)
                                    execution = register_managed_execution(
                                        lab_db.connection,
                                        workspace=str(agent.workspace.root),
                                        argv=list(command),
                                        allowed_commands=agent.workspace.allowed_commands,
                                        timeout_seconds=120,
                                        agent_run_id=run_id,
                                        workspace_id=conversation_workspace_id,
                                        project_id=conversation_project_id,
                                        approval_evidence={"approval": "approved", "approval_source": "plan_verification_approval", "approved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "source": "plan_verification", "argv_sha256": __import__("hashlib").sha256(__import__("json").dumps(list(command), sort_keys=True).encode("utf-8")).hexdigest(), "policy": [list(p) for p in agent.workspace.allowed_commands]},
                                        source_revision=run_metadata.get("task_workspace_source_revision"),
                                    )
                                execution_id = execution["id"]
                                operation_id = run_metadata.get("task_workspace_operation_id")
                                try:
                                    snapshot_before = get_task_workspace_fingerprint(store, operation_id)
                                except Exception as snapshot_error:
                                    snapshot_before = {"fingerprint": None, "complete": False,
                                                       "reason": type(snapshot_error).__name__}
                                result = run_execution(lab_db.connection, lab_db.lock, execution_id)
                                try:
                                    snapshot_after = get_task_workspace_fingerprint(store, operation_id)
                                except Exception as snapshot_error:
                                    snapshot_after = {"fingerprint": None, "complete": False,
                                                      "reason": type(snapshot_error).__name__}
                                snapshot_stable = (
                                    snapshot_before["complete"] and snapshot_after["complete"]
                                    and snapshot_before["fingerprint"] == snapshot_after["fingerprint"]
                                )
                                status = "passed" if result.get("returncode") == 0 else "failed"
                                with lab_db.lock:
                                    orchestration.record_verification(
                                        lab_db.connection, plan_id, step["id"], command, status,
                                        result.get("returncode"), result.get("stdout", ""), result.get("stderr", ""),
                                        execution_id=execution_id,
                                        workspace_fingerprint_before=snapshot_before["fingerprint"],
                                        workspace_fingerprint_after=snapshot_after["fingerprint"],
                                        workspace_snapshot_stable=snapshot_stable)
                                if status != "passed":
                                    verification_status = "failed"
                            except Exception as exc:
                                with lab_db.lock:
                                    orchestration.record_verification(lab_db.connection, plan_id, step["id"], command, "error", None, "", str(exc))
                                verification_status = "failed"
                    else:
                        verification_status = agent_verification
                    if verification_status in {"failed", "not_run", "not_configured"}:
                        step_outcome = "failed"
                    else:
                        step_outcome = "completed" if step_status == "completed" else "interrupted" if step_status == "cancelled" else "failed"
                    with lab_db.lock:
                        orchestration.finish_step(lab_db.connection, plan_id, step["id"], step_outcome,
                            step_result.get("content", step_status or "No result"), verification_status=verification_status)
                    if step_outcome != "completed":
                        raise RuntimeError("Plan stopped because step '" + step["title"] + "' did not complete")
            if plan_id is None:
                final = store.get_agent_run(run_id)
                outcome = final["status"] if final and final["status"] in lifecycle.TERMINAL else "failed"
                reason = (final["summary"] if final and final["summary"] else "Agent run finished.")
            else:
                outcome = "completed"
                reason = "All approved plan steps completed."
            if stop_event.is_set() and outcome == "completed":
                outcome = "cancelled"
                reason = "Cancellation was requested before terminal completion."
            # One durable decision wins; the background task and plan are mirrored
            # from it and never overwrite a competing terminal record.
            _finalize_agent_run(run_id, outcome, reason, plan_id)
        except Exception as exc:
            _finalize_agent_run(run_id, "cancelled" if stop_event.is_set() else "failed",
                                f"{type(exc).__name__}: {exc}", plan_id)
        finally:
            with agent_registry_guard:
                agent_stop_events.pop(run_id, None)
                agent_futures.pop(run_id, None)

    @app.post("/api/v1/agents/{run_id}/cancel")
    def cancel_agent(run_id: str, project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        run_row = store.get_agent_run(run_id)
        if run_row is None or not _run_visible_in_scope(run_row, project_id, workspace_id):
            raise HTTPException(status_code=404, detail="Agent run not found in this scope")
        queued = False
        plan_id = None
        with agent_registry_guard:
            with lab_db.lock:
                task = background_agent.get(lab_db.connection, run_id)
                if task is None:
                    raise HTTPException(status_code=404, detail="Background agent task not found")
                previous_status = task["status"]
                if not background_agent.request_cancel(lab_db.connection, run_id):
                    return {"cancelled": False, "status": task["status"]}
                from evo_experiments.execution import managed_executions_for_parent, request_cancel_managed_execution
                for execution in managed_executions_for_parent(lab_db.connection, run_id):
                    if execution.get("status") in {"queued", "launching", "running", "cancel_requested"}:
                        try:
                            request_cancel_managed_execution(lab_db.connection, execution["id"])
                        except ValueError:
                            pass
                queued = previous_status == "queued"
                if queued:
                    plan_row = lab_db.connection.execute("SELECT id FROM agent_plans WHERE run_id=?", (run_id,)).fetchone()
                    plan_id = plan_row["id"] if plan_row else None
            stop_event = agent_stop_events.get(run_id)
            if stop_event:
                stop_event.set()
        decision = None
        if queued:
            decision = _finalize_agent_run(run_id, "cancelled", "Cancelled before execution began.", plan_id)
        else:
            with lab_db.lock:
                decision = lifecycle.get_decision(lab_db.connection, run_id)
        with approval_guard:
            for item in pending_approvals.values():
                if item["run_id"] == run_id:
                    item["approved"] = False
                    item["decision"].set()
        with lab_db.lock:
            latest_decision = lifecycle.get_decision(lab_db.connection, run_id)
        if latest_decision is not None:
            outcome = latest_decision["outcome"]
            return {"cancelled": outcome == "cancelled", "status": outcome}
        if queued:
            return {"cancelled": True, "status": "cancelled"}
        return {"cancelled": True, "status": "cancel_requested"}

    @app.get("/api/v1/agents/{run_id}/events")
    def agent_background_events(run_id: str, after_id: int = 0, limit: int = 200,
                                 project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        run_row = store.get_agent_run(run_id)
        if run_row is None or not _run_visible_in_scope(run_row, project_id, workspace_id):
            raise HTTPException(status_code=404, detail="Agent run not found in this scope")
        with lab_db.lock:
            if background_agent.get(lab_db.connection, run_id) is None:
                raise HTTPException(status_code=404, detail="Background agent task not found")
            return background_agent.events(lab_db.connection, run_id, after_id, limit)

    @app.post("/api/v1/agents/{run_id}/approval")
    def decide_agent_approval(run_id: str, payload: AgentApproval,
                              project_id: str | None = None, workspace_id: str | None = None):
        project_id, workspace_id = _validated_api_scope(project_id, workspace_id)
        run_row = store.get_agent_run(run_id)
        if run_row is None or not _run_visible_in_scope(run_row, project_id, workspace_id):
            raise HTTPException(status_code=404, detail="Agent run not found in this scope")
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
    def conversations(limit: int = 30, q: str | None = None, project_id: str | None = None, workspace_id: str | None = None):
        try:
            validated_project_id, validated_workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        rows = store.list_conversations(min(max(limit, 1), 100), query=q, project_id=validated_project_id, workspace_id=validated_workspace_id)
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
    def create_conversation(payload: ConversationCreate | None = None, project_id: str | None = None, workspace_id: str | None = None):
        data = payload or ConversationCreate()
        selected_project = project_id if project_id is not None else data.project_id
        selected_workspace = workspace_id if workspace_id is not None else data.workspace_id
        try:
            validated_project_id, validated_workspace_id = store.validate_scope(selected_project, selected_workspace)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conversation_id = assistant.new_conversation(data.title or "New conversation", project_id=validated_project_id, workspace_id=validated_workspace_id)
        return {"id": conversation_id, "title": (data.title or "New conversation")[:120]}

    @app.patch("/api/v1/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, payload: ConversationUpdate, project_id: str | None = None, workspace_id: str | None = None):
        try:
            validated_project_id, validated_workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if store.get_conversation(conversation_id, project_id=validated_project_id, workspace_id=validated_workspace_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        try:
            updated = store.rename_conversation(conversation_id, payload.title, project_id=validated_project_id, workspace_id=validated_workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"id": conversation_id, "title": payload.title.strip()}

    @app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str, project_id: str | None = None, workspace_id: str | None = None):
        try:
            validated_project_id, validated_workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if store.get_conversation(conversation_id, project_id=validated_project_id, workspace_id=validated_workspace_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # The reservation check and deletion must be atomic with respect to chat
        # registration. Queued turns are reserved before executor submission.
        with locks_guard:
            entry = conversation_locks.get(conversation_id)
            if entry and entry["users"]:
                raise HTTPException(status_code=409, detail="Conversation is currently active")
            if not store.delete_conversation(conversation_id, project_id=validated_project_id, workspace_id=validated_workspace_id):
                raise HTTPException(status_code=404, detail="Conversation not found")
        return None

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, project_id: str | None = None, workspace_id: str | None = None):
        try:
            validated_project_id, validated_workspace_id = store.validate_scope(project_id, workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if store.get_conversation(conversation_id, project_id=validated_project_id, workspace_id=validated_workspace_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in store.get_messages(conversation_id, 500, project_id=validated_project_id, workspace_id=validated_workspace_id)
            if row["role"] in {"user", "assistant"}
        ]

    @app.post("/api/v1/chat")
    async def chat(payload: ChatRequest):
        text = payload.message.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Message cannot be empty")
        if shutting_down.is_set():
            raise HTTPException(status_code=503, detail="Evo is shutting down")

        try:
            validated_project_id, validated_workspace_id = store.validate_scope(payload.project_id, payload.workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if validated_workspace_id is not None and payload.conversation_id is not None:
            with locks_guard:
                if store.get_conversation(
                    payload.conversation_id,
                    project_id=validated_project_id,
                    workspace_id=validated_workspace_id,
                ) is None:
                    raise HTTPException(status_code=404, detail="Conversation not found")
        runtime = None
        invocation_id = None
        if validated_workspace_id is not None:
            runtime = _build_workspace_runtime_for_request(validated_workspace_id)
            invocation = _record_workspace_invocation(runtime, "workspace_chat")
            invocation_id = invocation["invocation_id"]
            _require_workspace_dispatch(runtime)
        turn_assistant = runtime.assistant if runtime is not None else assistant

        conversation_id = payload.conversation_id
        if conversation_id is None:
            # Create and reserve in the same critical section too, so even a
            # second local client cannot delete the new conversation in between.
            with locks_guard:
                conversation_id = turn_assistant.new_conversation(project_id=validated_project_id, workspace_id=validated_workspace_id)
                reservation = {"lock": threading.Lock(), "users": 1}
                conversation_locks[conversation_id] = reservation
        else:
            # Existence validation and reservation share the deletion lock. A
            # delete can therefore happen either before this check or after the
            # reservation is released, never in the middle.
            with locks_guard:
                if store.get_conversation(conversation_id, project_id=validated_project_id, workspace_id=validated_workspace_id) is None:
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
                        result = turn_assistant.turn(
                            conversation_id, text,
                            on_token=lambda token: publish(
                                {"event": "token", "data": token}
                            ),
                            project_id=validated_project_id,
                            workspace_id=validated_workspace_id,
                            invocation_id=invocation_id,
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

    app.state.run_agent = run_agent
    return app
