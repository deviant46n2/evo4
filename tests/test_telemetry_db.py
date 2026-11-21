import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_experiments.db import ResultsDB


class TelemetryPersistenceTests(unittest.TestCase):
    def test_expanded_sample_persists_processes_and_system_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = ResultsDB(Path(tmp) / "results.sqlite3")
            try:
                experiment_id = db.create_experiment({
                    "started_at": "2026-11-21T12:00:00+00:00", "task_id": "smoke",
                    "category": "test", "repetition": 1, "model": "test-model",
                    "base_url": "http://127.0.0.1:18997", "config_json": "{}",
                    "prompt": "hello", "status": "running",
                })
                db.add_sample(experiment_id, {
                    "sampled_at": "2026-11-21T12:00:01+00:00",
                    "gpu_memory_used_mib": 4096, "gpu_memory_used_percent": 25,
                    "gpu_processes": [{"pid": 123, "process_name": "llama-server"}],
                    "gpu_available": True, "cpu_utilization_percent": 40,
                    "cpu_logical_cores": 16, "ram_used_mib": 8192,
                    "ram_total_bytes": 32 * 1024**3, "ram_available_bytes": 24 * 1024**3,
                    "ram_used_bytes": 8 * 1024**3, "ram_used_percent": 25,
                    "load_average_1m": 1.2, "load_average_5m": 1.1,
                    "load_average_15m": 0.9,
                })
                row = db.connection.execute("SELECT * FROM resource_samples").fetchone()
                self.assertEqual(row["cpu_utilization_percent"], 40)
                self.assertEqual(row["gpu_memory_used_percent"], 25)
                self.assertEqual(json.loads(row["gpu_processes_json"])[0]["pid"], 123)
                self.assertEqual(row["gpu_available"], 1)
            finally:
                db.close()

    def test_existing_resource_sample_schema_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE experiments (
                    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
                    task_id TEXT NOT NULL, category TEXT NOT NULL,
                    repetition INTEGER NOT NULL, model TEXT NOT NULL,
                    base_url TEXT NOT NULL, config_json TEXT NOT NULL,
                    prompt TEXT NOT NULL, status TEXT NOT NULL
                );
                CREATE TABLE resource_samples (
                    id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL,
                    sampled_at TEXT NOT NULL, gpu_name TEXT,
                    gpu_utilization_percent REAL, gpu_memory_used_mib REAL,
                    gpu_memory_total_mib REAL, gpu_temperature_c REAL,
                    gpu_power_w REAL, ram_used_mib REAL
                );
            """)
            connection.close()
            db = ResultsDB(path)
            try:
                columns = {row[1] for row in db.connection.execute("PRAGMA table_info(resource_samples)")}
                self.assertIn("cpu_utilization_percent", columns)
                self.assertIn("gpu_processes_json", columns)
                self.assertIn("ram_used_percent", columns)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
