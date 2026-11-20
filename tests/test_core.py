import json
import tempfile
import unittest
from pathlib import Path
from evo_experiments.config import load_config
from evo_experiments.db import ResultsDB
from evo_experiments.runner import load_tasks

class HarnessTests(unittest.TestCase):
    def test_config_load(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text('[server]\nmodel="test"\n[experiment]\nrepetitions=2\n', encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.model, "test")
            self.assertEqual(config.repetitions, 2)

    def test_database_round_trip_and_cross_thread_sample(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            db = ResultsDB(Path(temp) / "results.db")
            eid = db.create_experiment({"started_at":"now","task_id":"t","category":"test",
                "repetition":1,"model":"m","base_url":"local","config_json":"{}",
                "prompt":"p","status":"running"})
            worker = threading.Thread(target=lambda: db.add_sample(eid, {
                "sampled_at":"now", "ram_used_mib":123.0}))
            worker.start()
            worker.join()
            db.finish_experiment(eid, {"status":"completed","response":"answer"})
            self.assertEqual(db.summary()[0]["status"], "completed")
            count = db.connection.execute("SELECT count(*) FROM resource_samples").fetchone()[0]
            self.assertEqual(count, 1)
            db.close()

    def test_jsonl_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            path.write_text(json.dumps({"id":"one","prompt":"hello"}) + "\n", encoding="utf-8")
            self.assertEqual(load_tasks(path)[0]["id"], "one")

if __name__ == "__main__":
    unittest.main()
