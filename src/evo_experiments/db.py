import sqlite3
import threading
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS experiments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
 task_id TEXT NOT NULL, category TEXT NOT NULL, repetition INTEGER NOT NULL,
 model TEXT NOT NULL, base_url TEXT NOT NULL, config_json TEXT NOT NULL,
 prompt TEXT NOT NULL, response TEXT, status TEXT NOT NULL, error TEXT,
 elapsed_seconds REAL, time_to_first_token_seconds REAL, prompt_tokens INTEGER,
 completion_tokens INTEGER, tokens_per_second REAL
);
CREATE TABLE IF NOT EXISTS resource_samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER NOT NULL REFERENCES experiments(id),
 sampled_at TEXT NOT NULL, gpu_name TEXT, gpu_utilization_percent REAL,
 gpu_memory_used_mib REAL, gpu_memory_total_mib REAL, gpu_temperature_c REAL,
 gpu_power_w REAL, ram_used_mib REAL
);
"""

class ResultsDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()
        self.lock = threading.RLock()

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
        keys = list(row)
        with self.lock:
            self.connection.execute(
                f"INSERT INTO resource_samples ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                [row[k] for k in keys])
            self.connection.commit()

    def summary(self, limit=20):
        with self.lock:
            return self.connection.execute(
                "SELECT id,started_at,task_id,category,repetition,model,status,elapsed_seconds,"
                "time_to_first_token_seconds,prompt_tokens,completion_tokens,tokens_per_second,error "
                "FROM experiments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def close(self):
        with self.lock:
            self.connection.close()
