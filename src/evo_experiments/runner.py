from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from .client import stream_chat_completion
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
    return {"base_url": config.base_url, "model_api_id": config.model,
        "max_tokens": config.max_tokens, "temperature": config.temperature,
        "timeout_seconds": config.timeout_seconds, "system_prompt": config.system_prompt,
        "runtime_manifest": metadata}
def run_tasks(config, tasks_path, repetitions=None):
    tasks = load_tasks(tasks_path)
    if not tasks:
        raise ValueError("No tasks found")
    count = repetitions if repetitions is not None else config.repetitions
    if count < 1:
        raise ValueError("Repetitions must be at least one")
    manifest = build_run_manifest(config)
    run_label = str(config.run_metadata.get("label") or config.model)
    db = ResultsDB(config.database)
    ids = []
    try:
        for repetition in range(1, count + 1):
            for task in tasks:
                eid = db.create_experiment({"started_at": datetime.now(timezone.utc).isoformat(),
                    "task_id": task["id"], "category": str(task.get("category", "uncategorized")),
                    "repetition": repetition, "model": config.model, "run_label": run_label,
                    "base_url": config.base_url, "config_json": json.dumps(manifest, sort_keys=True),
                    "prompt": task["prompt"], "status": "running"})
                ids.append(eid)
                monitor = ResourceMonitor(config.sample_interval_seconds,
                    lambda sample, experiment_id=eid: db.add_sample(experiment_id, sample))
                monitor.start()
                try:
                    result = stream_chat_completion(base_url=config.base_url, api_key=config.api_key,
                        model=config.model, system_prompt=config.system_prompt, prompt=task["prompt"],
                        max_tokens=config.max_tokens, temperature=config.temperature,
                        timeout=config.timeout_seconds)
                    evaluation_status, evaluation_details = evaluate_task(task, result["response"])
                    db.finish_experiment(eid, {"finished_at": datetime.now(timezone.utc).isoformat(),
                        "response": result["response"], "status": "completed",
                        "elapsed_seconds": result["elapsed_seconds"],
                        "time_to_first_token_seconds": result["time_to_first_token_seconds"],
                        "prompt_tokens": result["prompt_tokens"], "completion_tokens": result["completion_tokens"],
                        "tokens_per_second": result["tokens_per_second"], "evaluation_status": evaluation_status,
                        "evaluation_details": json.dumps(evaluation_details) if evaluation_details else None,
                        "evaluation_passed": evaluation_details["passed"] if evaluation_details else None,
                        "evaluation_total": evaluation_details["total"] if evaluation_details else None})
                except Exception as exc:
                    db.finish_experiment(eid, {"finished_at": datetime.now(timezone.utc).isoformat(),
                        "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    monitor.stop()
    finally:
        db.close()
    return ids
