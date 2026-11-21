import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from evo_core.store import EvoStore
from evo_experiments.db import ResultsDB


class ConnectionProxy:
    def __init__(self, connection, predicate):
        self._connection = connection
        self._predicate = predicate

    def execute(self, sql, *args, **kwargs):
        if self._predicate(sql):
            raise sqlite3.OperationalError("forced failure")
        return self._connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class PersistenceAtomicityTests(unittest.TestCase):
    def test_add_message_failure_does_not_persist_message_or_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvoStore(Path(tmp) / "evo.db")
            conversation_id = store.create_conversation("New conversation")
            original_connection = store.db
            proxy = ConnectionProxy(original_connection, lambda sql: "UPDATE conversations SET title" in sql)
            store.db = proxy
            with self.assertRaises(sqlite3.OperationalError):
                store.add_message(conversation_id, "user", "hello world from an atomicity test")
            store.db = original_connection

            self.assertEqual(store.get_messages(conversation_id), [])
            conversation = store.get_conversation(conversation_id)
            self.assertEqual(conversation["title"], "New conversation")
            self.assertEqual(store.db.execute("SELECT 1").fetchone()[0], 1)
            store.close()

    def test_review_memory_candidate_failure_does_not_persist_memory_or_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvoStore(Path(tmp) / "evo.db")
            candidate_id = store.propose_memory("atomic candidate memory", confidence=0.7)
            original_connection = store.db
            proxy = ConnectionProxy(original_connection, lambda sql: "UPDATE memory_candidates SET status" in sql)
            store.db = proxy
            with self.assertRaises(sqlite3.OperationalError):
                store.review_memory_candidate(candidate_id, True)
            store.db = original_connection

            self.assertEqual(store.list_memories(), [])
            candidate = store.db.execute(
                "SELECT status FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
            self.assertEqual(candidate["status"], "pending")
            self.assertEqual(store.db.execute("SELECT 1").fetchone()[0], 1)
            store.close()

    def test_concurrent_conversation_creation_is_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvoStore(Path(tmp) / "evo.db")
            barrier = threading.Barrier(8)
            results = []

            def worker():
                barrier.wait()
                results.append(store.create_conversation("Concurrent"))

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(results), 8)
            self.assertEqual(len(set(results)), 8)
            self.assertEqual(len(store.list_conversations(100)), 8)
            store.close()

    def test_aggregate_snapshot_is_internally_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = ResultsDB(Path(tmp) / "experiments.db")
            completed_id = db.create_experiment({
                "started_at": "2026-01-01T00:00:00+00:00",
                "task_id": "task-1",
                "category": "latency",
                "repetition": 1,
                "model": "model-a",
                "run_label": "config-a",
                "base_url": "http://127.0.0.1:18997",
                "config_json": "{}",
                "prompt": "prompt",
                "status": "running",
            })
            db.finish_experiment(completed_id, {
                "finished_at": "2026-01-01T00:00:02+00:00",
                "response": "response",
                "status": "completed",
                "finish_reason": "stop",
                "elapsed_seconds": 2.0,
                "time_to_first_token_seconds": 1.0,
                "tokens_per_second": 10.0,
                "evaluation_status": "passed",
                "evaluation_details": "{}",
                "evaluation_passed": 1,
                "evaluation_total": 1,
            })
            truncated_id = db.create_experiment({
                "started_at": "2026-01-01T00:00:00+00:00",
                "task_id": "task-2",
                "category": "latency",
                "repetition": 1,
                "model": "model-a",
                "run_label": "config-a",
                "base_url": "http://127.0.0.1:18997",
                "config_json": "{}",
                "prompt": "prompt",
                "status": "running",
            })
            db.finish_experiment(truncated_id, {
                "finished_at": "2026-01-01T00:00:01+00:00",
                "response": "response",
                "status": "truncated",
                "finish_reason": "length",
            })

            aggregate = db.aggregates()[0]
            self.assertEqual(aggregate["runs"], 2)
            self.assertEqual(aggregate["completed"], 1)
            self.assertEqual(aggregate["truncated"], 1)
            self.assertEqual(aggregate["avg_elapsed_seconds"], 2.0)
            self.assertEqual(aggregate["median_elapsed_seconds"], 2.0)
            self.assertIsNone(aggregate["stdev_elapsed_seconds"])
            db.close()


if __name__ == "__main__":
    unittest.main()
