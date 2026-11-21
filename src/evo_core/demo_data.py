"""Clearly labeled, reversible sample records for exploring Evo workspaces."""
from datetime import datetime, timedelta, timezone
import json
import uuid


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.isoformat()


def seed_demo_data(store, lab_db):
    """Insert an idempotent demo dataset; never overwrite or alter user records."""
    now = _now()
    counts = {"memories": 0, "candidates": 0, "agent_runs": 0,
              "tool_events": 0, "experiments": 0, "resource_samples": 0}

    memories = [
        ("Project direction", "Evo should maximize useful capability on the existing local workstation before expanding into autonomous self-development.", "project", ["evo", "direction"]),
        ("Hardware baseline", "Primary development machine: Ryzen 7 9800X3D, NVIDIA RTX 5070 Ti 16 GB VRAM, and approximately 32 GB system RAM.", "hardware", ["local-ai", "hardware"]),
        ("Model baseline", "The current local coding baseline is a Qwen3.8-27B GGUF served through an OpenAI-compatible llama.cpp endpoint.", "models", ["qwen", "llama.cpp"]),
        ("Approval policy", "Coding-agent file writes and shell commands must remain approval-gated; read-only inspection can run without approval.", "safety", ["coding-agent", "approval"]),
        ("Measurement principle", "Performance claims should be tied to reproducible experiments, exact model/configuration details, and recorded hardware telemetry.", "engineering", ["experiments", "provenance"]),
    ]
    with store.lock:
        for title, body, category, tags in memories:
            existing = store.db.execute(
                "SELECT id FROM memories WHERE source='demo-seed' AND content=?",
                (body,)).fetchone()
            if existing:
                continue
            mid = str(uuid.uuid4())
            store.db.execute(
                """INSERT INTO memories(id,content,category,tags_json,source,confidence,
                   created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)""",
                (mid, body, category, json.dumps(tags), "demo-seed", 1.0,
                 _stamp(now), _stamp(now), json.dumps({"demo_seed": True, "demo_title": title})))
            if store.fts_available:
                store.db.execute(
                    "INSERT INTO memories_fts(memory_id,content,category,tags) VALUES(?,?,?,?)",
                    (mid, body, category, " ".join(tags)))
            counts["memories"] += 1

        candidates = [
            ("Potential preference", "When comparing local models, prioritize coding reliability and usable context over headline parameter count.", "preferences", 0.72),
            ("Potential project requirement", "The desktop should make provenance visible so sample data, user-provided facts, and model inferences are never confused.", "project", 0.81),
        ]
        for body, category, confidence in candidates:
            exists = store.db.execute(
                "SELECT id FROM memory_candidates WHERE source='demo-seed' AND content=?",
                (body,)).fetchone()
            if exists:
                continue
            store.db.execute(
                """INSERT INTO memory_candidates(id,content,category,source,confidence,
                   status,created_at) VALUES(?,?,?,?,?,'pending',?)""",
                (str(uuid.uuid4()), body, category, "demo-seed", confidence, _stamp(now)))
            counts["candidates"] += 1

        runs = [
            ("completed", "Inspect the desktop API and summarize workspace capabilities",
             "Read-only inspection completed. No files changed.", [
                 ("list_files", "Completed", "Listed repository top-level files."),
                 ("read_file", "Completed", "Read API and desktop entry points."),
                 ("search_text", "Completed", "Located workspace route definitions."),
             ]),
            ("completed", "Add a small UI improvement to the dashboard",
             "Demo only: historical activity includes an approval checkpoint before a write.", [
                 ("read_file", "Completed", "Inspected the dashboard component."),
                 ("write_file", "Awaiting approval", "Illustrative event: a proposed patch was held for approval; no real action was pending."),
             ]),
            ("failed", "Run the frontend production build",
             "Demo only: illustrative failed run showing how errors appear in history.", [
                 ("run_command", "Failed", "Illustrative failure: command exited with code 1."),
             ]),
        ]
        run_ids = []
        for status, request, summary, events in runs:
            existing = store.db.execute(
                "SELECT id FROM agent_runs WHERE json_extract(metadata_json,'$.demo_seed')=1 AND json_extract(metadata_json,'$.request')=?",
                (request,)).fetchone()
            if existing:
                run_ids.append(existing["id"])
                continue
            run_id = str(uuid.uuid4())
            metadata = {"demo_seed": True, "request": request, "workspace": "sample://evo-demo",
                        "model": "sample-model (illustrative)", "source": "demo"}
            started = now - timedelta(minutes=18 - len(run_ids) * 6)
            finished = None if status == "awaiting_approval" else _stamp(started + timedelta(minutes=2))
            store.db.execute(
                """INSERT INTO agent_runs(id,kind,status,started_at,finished_at,summary,metadata_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, "coding", status, _stamp(started), finished, summary, json.dumps(metadata)))
            run_ids.append(run_id)
            counts["agent_runs"] += 1
            for tool_name, event_status, output in events:
                store.db.execute(
                    """INSERT INTO tool_events(run_id,tool_name,input_json,output_summary,status,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (run_id, tool_name, json.dumps({"demo": True, "request": request}),
                     output, event_status.lower().replace(" ", "_"), _stamp(started + timedelta(seconds=30))))
                counts["tool_events"] += 1
        store.db.commit()

    experiment_rows = [
        ("qwen27b-baseline", "coding", "completed", 41.8, 0.74, 1536, 384, 1, 1),
        ("qwen27b-baseline", "reasoning", "completed", 38.6, 0.91, 2048, 512, 1, 1),
        ("qwen27b-context-test", "coding", "failed", 0.0, 2.8, 4096, 0, 0, 1),
    ]
    with lab_db.lock:
        for index, (label, category, status, speed, ttft, prompt_tokens,
                    completion_tokens, passed, total) in enumerate(experiment_rows):
            task_id = f"demo-{category}-{index+1}"
            existing = lab_db.connection.execute(
                "SELECT id FROM experiments WHERE json_extract(config_json,'$.demo_seed')=1 AND task_id=?",
                (task_id,)).fetchone()
            if existing:
                continue
            started = now - timedelta(hours=3-index)
            ended = started + timedelta(seconds=(46 if status == "completed" else 12))
            config = {"demo_seed": True, "run_label": label, "note": "Illustrative sample; not measured on this machine."}
            cur = lab_db.connection.execute(
                """INSERT INTO experiments(started_at,finished_at,task_id,category,repetition,
                   model,run_label,base_url,config_json,prompt,response,status,error,elapsed_seconds,
                   time_to_first_token_seconds,prompt_tokens,completion_tokens,tokens_per_second,
                   evaluation_status,evaluation_details,evaluation_passed,evaluation_total)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_stamp(started), _stamp(ended), task_id, category, 1, "Qwen3.8-27B (sample)",
                 label, "sample://not-a-real-endpoint", json.dumps(config),
                 "Demonstration benchmark prompt.", "Illustrative sample output." if status == "completed" else None,
                 status, None if status == "completed" else "Illustrative context allocation failure.",
                 46.0 if status == "completed" else 12.0, ttft, prompt_tokens, completion_tokens,
                 speed if status == "completed" else None, "deterministic", "{}",
                 passed, total))
            experiment_id = int(cur.lastrowid)
            counts["experiments"] += 1
            for sample_index in range(4):
                sample_time = started + timedelta(seconds=sample_index * 12)
                gpu_used = [7800, 8420, 9010, 8750][sample_index] if status == "completed" else [14800, 15700, 0, 0][sample_index]
                ram_used = [9200, 9600, 10100, 9900][sample_index]
                lab_db.connection.execute(
                    """INSERT INTO resource_samples(experiment_id,sampled_at,gpu_name,
                       gpu_utilization_percent,gpu_memory_used_mib,gpu_memory_total_mib,
                       gpu_temperature_c,gpu_power_w,ram_used_mib,gpu_memory_used_percent,
                       ram_total_bytes,ram_available_bytes,ram_used_bytes,ram_used_percent,
                       cpu_utilization_percent,cpu_logical_cores,load_average_1m,load_average_5m,
                       load_average_15m,gpu_processes_json,gpu_available)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (experiment_id, _stamp(sample_time), "Sample NVIDIA GPU",
                     [72, 88, 94, 83][sample_index], gpu_used, 16303,
                     [61, 66, 69, 67][sample_index], [185, 224, 251, 219][sample_index],
                     ram_used, gpu_used / 16303 * 100, 32*1024**3,
                     (32*1024-ram_used)*1024**2, ram_used*1024**2,
                     ram_used/32768*100, [38, 57, 71, 49][sample_index],
                     16, 4.1, 3.8, 3.4, "[]", 1))
                counts["resource_samples"] += 1
        lab_db.connection.commit()
    return {"seeded": counts, "label": "DEMO DATA — illustrative, not real measurements"}


def demo_data_status(store, lab_db):
    with store.lock:
        memories = store.db.execute("SELECT COUNT(*) FROM memories WHERE source='demo-seed'").fetchone()[0]
        candidates = store.db.execute("SELECT COUNT(*) FROM memory_candidates WHERE source='demo-seed' AND status='pending'").fetchone()[0]
        runs = store.db.execute("SELECT COUNT(*) FROM agent_runs WHERE json_extract(metadata_json,'$.demo_seed')=1").fetchone()[0]
    with lab_db.lock:
        experiments = lab_db.connection.execute(
            "SELECT COUNT(*) FROM experiments WHERE json_extract(config_json,'$.demo_seed')=1").fetchone()[0]
    return {"active": bool(memories or candidates or runs or experiments),
            "memories": memories, "candidates": candidates, "agent_runs": runs,
            "experiments": experiments}


def clear_demo_data(store, lab_db):
    with store.lock:
        run_rows = store.db.execute(
            "SELECT id FROM agent_runs WHERE json_extract(metadata_json,'$.demo_seed')=1").fetchall()
        run_ids = [row["id"] for row in run_rows]
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            store.db.execute(f"DELETE FROM tool_events WHERE run_id IN ({placeholders})", run_ids)
            store.db.execute(f"DELETE FROM run_feedback WHERE run_id IN ({placeholders})", run_ids)
            store.db.execute(f"DELETE FROM agent_runs WHERE id IN ({placeholders})", run_ids)
        candidate_count = store.db.execute("SELECT COUNT(*) FROM memory_candidates WHERE source='demo-seed'").fetchone()[0]
        store.db.execute("DELETE FROM memory_candidates WHERE source='demo-seed'")
        demo_memories = store.db.execute("SELECT id FROM memories WHERE source='demo-seed'").fetchall()
        memory_ids = [row["id"] for row in demo_memories]
        if memory_ids:
            placeholders = ",".join("?" for _ in memory_ids)
            store.db.execute(f"DELETE FROM memory_relations WHERE source_memory_id IN ({placeholders}) OR target_memory_id IN ({placeholders})",
                             memory_ids + memory_ids)
            store.db.execute(f"DELETE FROM memories_fts WHERE memory_id IN ({placeholders})", memory_ids) if store.fts_available else None
            store.db.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", memory_ids)
        store.db.commit()
    with lab_db.lock:
        ids = [row["id"] for row in lab_db.connection.execute(
            "SELECT id FROM experiments WHERE json_extract(config_json,'$.demo_seed')=1").fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            lab_db.connection.execute(f"DELETE FROM resource_samples WHERE experiment_id IN ({placeholders})", ids)
            lab_db.connection.execute(f"DELETE FROM experiments WHERE id IN ({placeholders})", ids)
        lab_db.connection.commit()
    return {"removed": {"memories": len(memory_ids), "candidates": candidate_count,
                        "agent_runs": len(run_ids), "experiments": len(ids)}}
