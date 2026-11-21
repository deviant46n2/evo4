import json
import sqlite3
import statistics
import threading
from pathlib import Path
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS experiments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
 task_id TEXT NOT NULL, category TEXT NOT NULL, repetition INTEGER NOT NULL,
 model TEXT NOT NULL, run_label TEXT, base_url TEXT NOT NULL, config_json TEXT NOT NULL,
 prompt TEXT NOT NULL, response TEXT, status TEXT NOT NULL, error TEXT,
 elapsed_seconds REAL, time_to_first_token_seconds REAL, prompt_tokens INTEGER,
 completion_tokens INTEGER, tokens_per_second REAL, finish_reason TEXT, seed INTEGER, evaluation_status TEXT, evaluation_details TEXT,
 evaluation_passed INTEGER, evaluation_total INTEGER
);
CREATE TABLE IF NOT EXISTS resource_samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
 sampled_at TEXT NOT NULL, gpu_name TEXT, gpu_utilization_percent REAL,
 gpu_memory_used_mib REAL, gpu_memory_total_mib REAL, gpu_temperature_c REAL,
 gpu_power_w REAL, ram_used_mib REAL,
 gpu_memory_used_percent REAL, ram_total_bytes REAL, ram_available_bytes REAL,
 ram_used_bytes REAL, ram_used_percent REAL, cpu_utilization_percent REAL,
 cpu_logical_cores INTEGER, load_average_1m REAL, load_average_5m REAL,
 load_average_15m REAL, gpu_processes_json TEXT, gpu_available INTEGER
);
"""
class ResultsDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(SCHEMA)
        self._migrate()
        self.connection.commit()
        self.lock = threading.RLock()
    def _migrate(self):
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(experiments)")}
        for name, column_type in (("evaluation_status", "TEXT"), ("evaluation_details", "TEXT"),
                                  ("evaluation_passed", "INTEGER"), ("evaluation_total", "INTEGER"),
                                  ("run_label", "TEXT"), ("finish_reason", "TEXT"), ("seed", "INTEGER")):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE experiments ADD COLUMN {name} {column_type}")
        legacy = self.connection.execute(
            "SELECT id,evaluation_details FROM experiments "
            "WHERE evaluation_details IS NOT NULL AND evaluation_passed IS NULL").fetchall()
        for row in legacy:
            try:
                details = json.loads(row["evaluation_details"])
                passed, total = details.get("passed"), details.get("total")
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
            if isinstance(passed, int) and isinstance(total, int):
                self.connection.execute(
                    "UPDATE experiments SET evaluation_passed=?,evaluation_total=? WHERE id=?",
                    (passed, total, row["id"]))
        sample_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(resource_samples)")}
        sample_migrations = (
            ("gpu_memory_used_percent", "REAL"), ("ram_total_bytes", "REAL"),
            ("ram_available_bytes", "REAL"), ("ram_used_bytes", "REAL"),
            ("ram_used_percent", "REAL"), ("cpu_utilization_percent", "REAL"),
            ("cpu_logical_cores", "INTEGER"), ("load_average_1m", "REAL"),
            ("load_average_5m", "REAL"), ("load_average_15m", "REAL"),
            ("gpu_processes_json", "TEXT"), ("gpu_available", "INTEGER"),
        )
        for name, column_type in sample_migrations:
            if name not in sample_columns:
                self.connection.execute(f"ALTER TABLE resource_samples ADD COLUMN {name} {column_type}")
    def create_experiment(self, values):
        keys = list(values)
        with self.lock:
            cur = self.connection.execute(
                f"INSERT INTO experiments ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                [values[k] for k in keys])
            self.connection.commit()
            return int(cur.lastrowid)
    def finish_experiment(self, experiment_id, values):
        assignments = ", ".join(f"{key}=?" for key in values)
        with self.lock:
            self.connection.execute(f"UPDATE experiments SET {assignments} WHERE id=?",
                                    [*values.values(), experiment_id])
            self.connection.commit()
    def add_sample(self, experiment_id, values):
        row = {"experiment_id": experiment_id, **values}
        if "gpu_processes" in row:
            row["gpu_processes_json"] = json.dumps(row.pop("gpu_processes"), ensure_ascii=False)
        if "gpu_available" in row:
            row["gpu_available"] = int(bool(row["gpu_available"]))
        with self.lock:
            columns = {item[1] for item in self.connection.execute("PRAGMA table_info(resource_samples)")}
            row = {key: value for key, value in row.items() if key in columns}
            keys = list(row)
            self.connection.execute(
                f"INSERT INTO resource_samples ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                [row[k] for k in keys])
            self.connection.commit()
    def summary(self, limit=20):
        with self.lock:
            return self.connection.execute(
                "SELECT id,started_at,task_id,category,repetition,model,run_label,status,elapsed_seconds,"
                "time_to_first_token_seconds,prompt_tokens,completion_tokens,tokens_per_second,finish_reason,seed,"
                "evaluation_status,evaluation_details,evaluation_passed,evaluation_total,error FROM experiments "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    def aggregates(self):
        with self.lock:
            groups = self.connection.execute(
                "SELECT COALESCE(run_label,model) AS configuration, model, category, COUNT(*) AS runs, "
                "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, "
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
                "SUM(CASE WHEN status='truncated' THEN 1 ELSE 0 END) AS truncated, "
                "SUM(CASE WHEN status='incomplete' THEN 1 ELSE 0 END) AS incomplete, "
                "SUM(CASE WHEN status='unknown' THEN 1 ELSE 0 END) AS unknown, "
                "SUM(COALESCE(evaluation_passed,0)) AS checks_passed, "
                "SUM(COALESCE(evaluation_total,0)) AS checks_scored, "
                "ROUND(AVG(CASE WHEN status='completed' THEN elapsed_seconds END),3) AS avg_elapsed_seconds, "
                "ROUND(AVG(CASE WHEN status='completed' THEN time_to_first_token_seconds END),3) AS avg_ttft_seconds, "
                "ROUND(AVG(CASE WHEN status='completed' THEN tokens_per_second END),2) AS avg_tokens_per_second, "
                "ROUND(AVG(samples.peak_vram_mib),1) AS avg_peak_vram_mib, "
                "MAX(samples.peak_vram_mib) AS max_peak_vram_mib, "
                "ROUND(AVG(samples.avg_gpu_utilization),1) AS avg_gpu_utilization_percent, "
                "MAX(samples.peak_ram_mib) AS max_sampled_ram_mib "
                "FROM experiments LEFT JOIN ("
                "SELECT experiment_id, MAX(gpu_memory_used_mib) AS peak_vram_mib, "
                "AVG(gpu_utilization_percent) AS avg_gpu_utilization, "
                "MAX(ram_used_mib) AS peak_ram_mib FROM resource_samples GROUP BY experiment_id"
                ") AS samples ON samples.experiment_id=experiments.id "
                "GROUP BY COALESCE(run_label,model), model, category "
                "ORDER BY configuration, category").fetchall()
            measurements = self.connection.execute(
                "SELECT COALESCE(run_label,model) AS configuration,model,category,"
                "elapsed_seconds,time_to_first_token_seconds,tokens_per_second "
                "FROM experiments WHERE status='completed'").fetchall()
        grouped = {}
        for value in measurements:
            key = (value["configuration"], value["model"], value["category"])
            grouped.setdefault(key, []).append(value)
        result = []
        for row in groups:
            item = dict(row)
            values = grouped.get((row["configuration"], row["model"], row["category"]), [])
            for field, label, digits in (
                ("elapsed_seconds", "elapsed_seconds", 3),
                ("time_to_first_token_seconds", "ttft_seconds", 3),
                ("tokens_per_second", "tokens_per_second", 2),
            ):
                samples = [float(value[field]) for value in values if value[field] is not None]
                item["median_" + label] = round(statistics.median(samples), digits) if samples else None
                item["stdev_" + label] = round(statistics.stdev(samples), digits) if len(samples) > 1 else None
            result.append(item)
        return result
    def count_failed(self, ids):
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.lock:
            return int(self.connection.execute(
                f"SELECT COUNT(*) FROM experiments WHERE status='failed' AND id IN ({placeholders})",
                list(ids)).fetchone()[0])
    def count_not_completed(self, ids):
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.lock:
            return int(self.connection.execute(
                f"SELECT COUNT(*) FROM experiments WHERE status<>'completed' AND id IN ({placeholders})",
                list(ids)).fetchone()[0])
    def close(self):
        with self.lock:
            self.connection.close()
