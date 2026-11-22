from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from .client import get_runtime_props, stream_chat_completion
from .db import ResultsDB
from .evaluation import evaluate_task
from .monitor import ResourceMonitor
def load_tasks(path):
    tasks, seen_ids = [], set()
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"].strip() or not isinstance(task.get("prompt"), str):
                raise ValueError(f"{path}:{line_no}: task requires a nonempty string id and string prompt")
            if task["id"] in seen_ids:
                raise ValueError(f"{path}:{line_no}: duplicate task id {task['id']!r}")
            if "expected_contains" in task and not isinstance(task["expected_contains"], (str, list)):
                raise ValueError(f"{path}:{line_no}: expected_contains must be a string or list")
            seen_ids.add(task["id"])
            tasks.append(task)
    return tasks
def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
def build_run_manifest(config):
    metadata = dict(config.run_metadata)
    model_file = metadata.get("model_file")
    if model_file:
        path = Path(model_file).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Configured model_file does not exist: {path}")
        metadata["model_file"] = str(path.resolve())
        metadata["model_sha256"] = _file_sha256(path)
    props = get_runtime_props(base_url=config.base_url, api_key=config.api_key,
                              timeout=min(config.timeout_seconds, 2))
    metadata["server_props_available"] = props is not None
    if props is not None:
        metadata["server_props"] = props
    return {"base_url": config.base_url, "model_api_id": config.model,
        "max_tokens": config.max_tokens, "temperature": config.temperature,
        "seed": config.seed, "timeout_seconds": config.timeout_seconds,
        "system_prompt": config.system_prompt, "runtime_manifest": metadata}
def run_tasks(config, tasks_path, repetitions=None):
    tasks = load_tasks(tasks_path)
    if not tasks:
        raise ValueError("No tasks found")
    count = repetitions if repetitions is not None else config.repetitions
    if count < 1:
        raise ValueError("Repetitions must be at least one")
    if config.seed is not None and config.seed + count - 1 > 2147483647:
        raise ValueError("experiment.seed plus repetitions exceeds the supported 32-bit seed range")
    manifest = build_run_manifest(config)
    run_label = str(config.run_metadata.get("label") or config.model)
    db = ResultsDB(config.database)
    ids = []
    active_interrupt = None
    try:
        for repetition in range(1, count + 1):
            for task in tasks:
                run_seed = config.seed + repetition - 1 if config.seed is not None else None
                run_manifest = {**manifest, "run_seed": run_seed}
                eid = None
                monitor = None
                finished = False
                result = None
                try:
                    eid = db.create_experiment({"started_at": datetime.now(timezone.utc).isoformat(),
                        "task_id": task["id"], "category": str(task.get("category", "uncategorized")),
                        "repetition": repetition, "model": config.model, "run_label": run_label,
                        "base_url": config.base_url, "config_json": json.dumps(run_manifest, sort_keys=True),
                        "prompt": task["prompt"], "seed": run_seed, "status": "running"})
                    ids.append(eid)
                    monitor = ResourceMonitor(config.sample_interval_seconds,
                        lambda sample, experiment_id=eid: db.add_sample(experiment_id, sample))
                    monitor.start()
                    try:
                        result = stream_chat_completion(base_url=config.base_url, api_key=config.api_key,
                            model=config.model, system_prompt=config.system_prompt, prompt=task["prompt"],
                            max_tokens=config.max_tokens, temperature=config.temperature,
                            timeout=config.timeout_seconds, seed=run_seed)
                        finish_reason = result.get("finish_reason")
                        if finish_reason == "stop":
                            status = "completed"
                            evaluation_status, evaluation_details = evaluate_task(task, result["response"])
                        elif finish_reason == "length":
                            status = "truncated"
                            evaluation_status = "not_run_truncated"
                            evaluation_details = {"reason": "Server stopped generation at the completion token limit."}
                        elif finish_reason is None:
                            status = "unknown"
                            evaluation_status = "not_run_unknown_finish_reason"
                            evaluation_details = {"reason": "Server did not report a completion finish_reason."}
                        else:
                            status = "incomplete"
                            evaluation_status = "not_run_" + str(finish_reason)
                            evaluation_details = {"reason": "Server reported a non-success finish_reason.",
                                                  "finish_reason": finish_reason}
                        db.finish_experiment(eid, {"finished_at": datetime.now(timezone.utc).isoformat(),
                            "response": result["response"], "status": status, "finish_reason": finish_reason,
                            "elapsed_seconds": result["elapsed_seconds"],
                            "time_to_first_token_seconds": result["time_to_first_token_seconds"],
                            "prompt_tokens": result["prompt_tokens"], "completion_tokens": result["completion_tokens"],
                            "tokens_per_second": result["tokens_per_second"], "evaluation_status": evaluation_status,
                            "evaluation_details": json.dumps(evaluation_details) if evaluation_details else None,
                            "evaluation_passed": evaluation_details["passed"] if evaluation_status in ("passed","failed") and evaluation_details else None,
                            "evaluation_total": evaluation_details["total"] if evaluation_status in ("passed","failed") and evaluation_details else None})
                        finished = True
                    except Exception as exc:
                        failure = {"finished_at": datetime.now(timezone.utc).isoformat(),
                            "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                        if result is not None:
                            failure.update({"response": result["response"],
                                "finish_reason": result.get("finish_reason"),
                                "elapsed_seconds": result["elapsed_seconds"],
                                "time_to_first_token_seconds": result["time_to_first_token_seconds"],
                                "prompt_tokens": result["prompt_tokens"],
                                "completion_tokens": result["completion_tokens"],
                                "tokens_per_second": result["tokens_per_second"]})
                        db.finish_experiment(eid, failure)
                        finished = True
                    except KeyboardInterrupt as exc:
                        active_interrupt = exc
                        if not finished:
                            interrupted = {"finished_at": datetime.now(timezone.utc).isoformat(),
                                "status": "interrupted",
                                "error": "KeyboardInterrupt: experiment interrupted by user"}
                            if result is not None:
                                interrupted.update({"response": result.get("response"),
                                    "finish_reason": result.get("finish_reason"),
                                    "elapsed_seconds": result.get("elapsed_seconds"),
                                    "time_to_first_token_seconds": result.get("time_to_first_token_seconds"),
                                    "prompt_tokens": result.get("prompt_tokens"),
                                    "completion_tokens": result.get("completion_tokens"),
                                    "tokens_per_second": result.get("tokens_per_second")})
                            try:
                                db.finish_experiment_if_running(eid, interrupted)
                                finished = True
                            except Exception as cleanup_exc:
                                import sys, traceback
                                sys.stderr.write(f"Secondary experiment cleanup failure: {type(cleanup_exc).__name__}: {cleanup_exc}\n")
                                traceback.print_exception(type(cleanup_exc), cleanup_exc, cleanup_exc.__traceback__, file=sys.stderr)
                        raise
                except KeyboardInterrupt as exc:
                    active_interrupt = exc
                    if eid is not None and not finished:
                        interrupted = {"finished_at": datetime.now(timezone.utc).isoformat(),
                            "status": "interrupted",
                            "error": "KeyboardInterrupt: experiment interrupted by user"}
                        try:
                            db.finish_experiment_if_running(eid, interrupted)
                            finished = True
                        except Exception as cleanup_exc:
                            import sys, traceback
                            sys.stderr.write(f"Secondary experiment cleanup failure: {type(cleanup_exc).__name__}: {cleanup_exc}\n")
                            traceback.print_exception(type(cleanup_exc), cleanup_exc, cleanup_exc.__traceback__, file=sys.stderr)
                    raise
                finally:
                    if monitor is not None:
                        cleanup_exc = None
                        interrupted = False
                        try:
                            monitor.stop()
                        except KeyboardInterrupt:
                            interrupted = True
                        except Exception as exc:
                            cleanup_exc = exc
                            import sys, traceback
                            sys.stderr.write(f"Secondary monitor cleanup failure: {type(exc).__name__}: {exc}\n")
                            traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
                        thread = monitor.thread
                        while thread is not None and thread.is_alive():
                            try:
                                thread.join()
                            except KeyboardInterrupt:
                                interrupted = True
                        if interrupted:
                            if active_interrupt is None:
                                active_interrupt = KeyboardInterrupt()
                            raise active_interrupt
                        if cleanup_exc is not None:
                            raise cleanup_exc
    finally:
        try:
            db.close()
        except Exception as close_exc:
            if active_interrupt is not None:
                import sys, traceback
                sys.stderr.write(f"Secondary database close failure: {type(close_exc).__name__}: {close_exc}\n")
                traceback.print_exception(type(close_exc), close_exc, close_exc.__traceback__, file=sys.stderr)
            else:
                raise
    return ids
