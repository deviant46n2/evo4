from datetime import datetime, timezone
import json
from pathlib import Path
from .client import stream_chat_completion
from .db import ResultsDB
from .monitor import ResourceMonitor

def load_tasks(path):
    tasks = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(task, dict) or not task.get("id") or "prompt" not in task:
                raise ValueError(f"{path}:{line_no}: task requires nonempty id and prompt")
            tasks.append(task)
    return tasks

def run_tasks(config, tasks_path, repetitions=None):
    tasks = load_tasks(tasks_path)
    if not tasks:
        raise ValueError("No tasks found")
    count = repetitions if repetitions is not None else config.repetitions
    if count < 1:
        raise ValueError("Repetitions must be at least one")
    db = ResultsDB(config.database)
    ids = []
    try:
        for repetition in range(1, count + 1):
            for task in tasks:
                started = datetime.now(timezone.utc).isoformat()
                snapshot = {"base_url": config.base_url, "model": config.model,
                    "max_tokens": config.max_tokens, "temperature": config.temperature,
                    "timeout_seconds": config.timeout_seconds, "system_prompt": config.system_prompt}
                eid = db.create_experiment({"started_at": started, "task_id": str(task["id"]),
                    "category": str(task.get("category", "uncategorized")), "repetition": repetition,
                    "model": config.model, "base_url": config.base_url,
                    "config_json": json.dumps(snapshot, sort_keys=True), "prompt": str(task["prompt"]),
                    "status": "running"})
                ids.append(eid)
                monitor = ResourceMonitor(config.sample_interval_seconds,
                    lambda sample, experiment_id=eid: db.add_sample(experiment_id, sample))
                monitor.start()
                try:
                    result = stream_chat_completion(base_url=config.base_url, api_key=config.api_key,
                        model=config.model, system_prompt=config.system_prompt, prompt=str(task["prompt"]),
                        max_tokens=config.max_tokens, temperature=config.temperature,
                        timeout=config.timeout_seconds)
                    db.finish_experiment(eid, {"finished_at": datetime.now(timezone.utc).isoformat(),
                        "response": result["response"], "status": "completed",
                        "elapsed_seconds": result["elapsed_seconds"],
                        "time_to_first_token_seconds": result["time_to_first_token_seconds"],
                        "prompt_tokens": result["prompt_tokens"],
                        "completion_tokens": result["completion_tokens"],
                        "tokens_per_second": result["tokens_per_second"]})
                except Exception as exc:
                    db.finish_experiment(eid, {"finished_at": datetime.now(timezone.utc).isoformat(),
                        "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    monitor.stop()
    finally:
        db.close()
    return ids
