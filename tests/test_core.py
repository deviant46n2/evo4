import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from evo_experiments.client import ModelRequestError, list_models, stream_chat_completion
from evo_experiments.config import load_config
from evo_experiments.db import ResultsDB
from evo_experiments.evaluation import evaluate_task
from evo_experiments.runner import build_run_manifest, load_tasks, run_tasks

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/props":
            payload = {"build_info":{"version":"test-build"},"model_path":"/models/test.gguf",
                       "model_ftype":"IQ4_XS","n_ctx":102400,"total_slots":1,"secret":"must-not-record"}
        else:
            payload = {"data":[{"id":"fake-model"}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length","0"))
        self.server.last_payload = json.loads(self.rfile.read(length))
        events = [{"choices":[{"delta":{"content":"hello "}}]},
            {"choices":[{"delta":{"content":"world"}}]},
            {"choices":[{"delta":{},"finish_reason":getattr(self.server,"finish_reason","stop")}],
             "usage":{"prompt_tokens":8,"completion_tokens":2}}]
        body = "".join("data: "+json.dumps(event)+"\n\n" for event in events)+"data: [DONE]\n\n"
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Content-Length",str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
    def log_message(self, *args):
        pass

class PlainJSONHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length","0"))
        self.rfile.read(length)
        body = json.dumps({"choices":[{"message":{"role":"assistant","content":"plain"}}],
                           "usage":{"prompt_tokens":1,"completion_tokens":1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

class HarnessTests(unittest.TestCase):
    def test_config_load_and_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text('[server]\nmodel="test"\n[experiment]\nrepetitions=2\n[run]\ncontext_size=49152\n', encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.model, "test")
            self.assertEqual(config.base_url, "http://127.0.0.1:18997")
            self.assertEqual(config.repetitions, 2)
            self.assertIsNone(config.seed)
            self.assertEqual(build_run_manifest(config)["runtime_manifest"]["context_size"], 49152)

    def test_model_file_hash_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "tiny.gguf"
            model.write_bytes(b"fixture-model")
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[run]\nmodel_file="{model}"\n', encoding="utf-8")
            manifest = build_run_manifest(load_config(config_path))
            self.assertEqual(len(manifest["runtime_manifest"]["model_sha256"]), 64)

    def test_database_round_trip_aggregate_and_cross_thread_sample(self):
        with tempfile.TemporaryDirectory() as temp:
            db = ResultsDB(Path(temp) / "results.db")
            eid = db.create_experiment({"started_at":"now","task_id":"t","category":"test",
                "repetition":1,"model":"m","run_label":"baseline","base_url":"local",
                "config_json":"{}","prompt":"p","status":"running"})
            worker = threading.Thread(target=lambda: db.add_sample(eid, {
                "sampled_at":"now", "ram_used_mib":123.0, "gpu_memory_used_mib":456.0,
                "gpu_utilization_percent":70.0}))
            worker.start()
            worker.join()
            db.finish_experiment(eid, {"status":"completed","response":"answer",
                "evaluation_status":"passed","evaluation_details":"{}","elapsed_seconds":1.5,
                "evaluation_passed":1,"evaluation_total":1})
            self.assertEqual(db.summary()[0]["status"], "completed")
            self.assertEqual(db.summary()[0]["evaluation_status"], "passed")
            aggregate = db.aggregates()[0]
            self.assertEqual(aggregate["configuration"], "baseline")
            self.assertEqual(aggregate["checks_passed"], 1)
            self.assertEqual(aggregate["max_peak_vram_mib"], 456.0)
            self.assertEqual(aggregate["max_sampled_ram_mib"], 123.0)
            self.assertEqual(db.connection.execute("SELECT count(*) FROM resource_samples").fetchone()[0], 1)
            db.close()

    def test_existing_database_schema_migrates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE experiments (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                task_id TEXT NOT NULL, category TEXT NOT NULL, repetition INTEGER NOT NULL,
                model TEXT NOT NULL, base_url TEXT NOT NULL, config_json TEXT NOT NULL,
                prompt TEXT NOT NULL, response TEXT, status TEXT NOT NULL, error TEXT,
                elapsed_seconds REAL, time_to_first_token_seconds REAL, prompt_tokens INTEGER,
                completion_tokens INTEGER, tokens_per_second REAL)""")
            conn.commit()
            conn.close()
            db = ResultsDB(path)
            columns = {row[1] for row in db.connection.execute("PRAGMA table_info(experiments)")}
            self.assertTrue({"run_label","evaluation_status","evaluation_details","finish_reason","seed"}.issubset(columns))
            db.close()

    def test_legacy_evaluation_details_are_backfilled(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE experiments (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                task_id TEXT NOT NULL, category TEXT NOT NULL, repetition INTEGER NOT NULL,
                model TEXT NOT NULL, base_url TEXT NOT NULL, config_json TEXT NOT NULL,
                prompt TEXT NOT NULL, response TEXT, status TEXT NOT NULL, error TEXT,
                elapsed_seconds REAL, time_to_first_token_seconds REAL, prompt_tokens INTEGER,
                completion_tokens INTEGER, tokens_per_second REAL, evaluation_status TEXT,
                evaluation_details TEXT)""")
            conn.execute("""INSERT INTO experiments (started_at,task_id,category,repetition,model,
                base_url,config_json,prompt,status,evaluation_status,evaluation_details)
                VALUES ('now','t','test',1,'m','local','{}','p','completed','passed',
                '{"passed": 2, "total": 2}')""")
            conn.commit()
            conn.close()
            db = ResultsDB(path)
            self.assertEqual(db.summary()[0]["evaluation_passed"], 2)
            self.assertEqual(db.aggregates()[0]["checks_passed"], 2)
            self.assertEqual(db.aggregates()[0]["checks_scored"], 2)
            db.close()

    def test_jsonl_tasks_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            path.write_text(json.dumps({"id":"one","prompt":"hello"}) + "\n", encoding="utf-8")
            self.assertEqual(load_tasks(path)[0]["id"], "one")
            path.write_text('{"id":"dup","prompt":"a"}\n{"id":"dup","prompt":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate task id"):
                load_tasks(path)

    def test_explicit_task_evaluation(self):
        status, details = evaluate_task({"expected_contains":["9.6","seconds"]}, "It takes 9.6 seconds.")
        self.assertEqual(status, "passed")
        self.assertEqual(details["passed"], 2)
        self.assertEqual(evaluate_task({"expected_exact":"yes"}, "no")[0], "failed")
        self.assertEqual(evaluate_task({"id":"freeform"}, "anything"), (None, None))

    def test_openai_compatible_server_diagnostic_and_stream(self):
        server = ThreadingHTTPServer(("127.0.0.1",0), FakeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(list_models(base_url=base, api_key="test", timeout=3), ["fake-model"])
            result = stream_chat_completion(base_url=base, api_key="test", model="fake-model",
                system_prompt="system", prompt="prompt", max_tokens=20, temperature=0, timeout=3, seed=19)
            self.assertEqual(result["response"], "hello world")
            self.assertEqual(result["finish_reason"], "stop")
            self.assertFalse(result["truncated"])
            self.assertEqual(server.last_payload["seed"], 19)
            self.assertEqual(result["prompt_tokens"], 8)
            self.assertEqual(result["completion_tokens"], 2)
            self.assertIsNotNone(result["time_to_first_token_seconds"])
            self.assertEqual(server.last_payload["messages"][1]["content"], "prompt")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_runtime_props_are_snapshotted_with_an_allowlist(self):
        server = ThreadingHTTPServer(("127.0.0.1",0), FakeHandler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "config.toml"
                path.write_text(chr(10).join([
                    '[server]', f'base_url="http://127.0.0.1:{server.server_port}"'
                ]),encoding="utf-8")
                manifest = build_run_manifest(load_config(path))
                props = manifest["runtime_manifest"]["server_props"]
                self.assertTrue(manifest["runtime_manifest"]["server_props_available"])
                self.assertEqual(props["n_ctx"],102400)
                self.assertEqual(props["model_ftype"],"IQ4_XS")
                self.assertNotIn("secret",props)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_length_finish_reason_is_recorded_as_truncated_and_not_scored(self):
        server = ThreadingHTTPServer(("127.0.0.1",0),FakeHandler)
        server.finish_reason = "length"
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                config_path = Path(temp) / "config.toml"
                db_path = Path(temp) / "results.db"
                tasks_path = Path(temp) / "tasks.jsonl"
                config_path.write_text(chr(10).join([
                    '[server]', f'base_url="http://127.0.0.1:{server.server_port}"',
                    '[experiment]', f'database="{db_path}"', 'seed=41', 'max_tokens=20'
                ]),encoding="utf-8")
                tasks_path.write_text(json.dumps({"id":"t","prompt":"solve","expected_contains":"world"})+chr(10),
                                      encoding="utf-8")
                ids = run_tasks(load_config(config_path),tasks_path,repetitions=2)
                db = ResultsDB(db_path)
                try:
                    rows = db.connection.execute(
                        "SELECT status,finish_reason,seed,evaluation_status,evaluation_total FROM experiments ORDER BY id"
                    ).fetchall()
                    self.assertEqual([row["status"] for row in rows],["truncated","truncated"])
                    self.assertEqual([row["finish_reason"] for row in rows],["length","length"])
                    self.assertEqual([row["seed"] for row in rows],[41,42])
                    self.assertEqual([row["evaluation_status"] for row in rows],
                                     ["not_run_truncated","not_run_truncated"])
                    self.assertEqual([row["evaluation_total"] for row in rows],[None,None])
                    self.assertEqual(db.count_not_completed(ids),2)
                    self.assertEqual(server.last_payload["seed"],42)
                finally:
                    db.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_aggregates_use_only_completed_runs_and_report_median_and_stdev(self):
        with tempfile.TemporaryDirectory() as temp:
            db = ResultsDB(Path(temp) / "results.db")
            for index, (status, speed) in enumerate((("completed",10.0),("completed",20.0),
                                                       ("completed",30.0),("truncated",1000.0)),1):
                eid = db.create_experiment({"started_at":"now","task_id":"t","category":"test",
                    "repetition":index,"model":"m","run_label":"baseline","base_url":"local",
                    "config_json":"{}","prompt":"p","status":"running"})
                db.finish_experiment(eid,{"status":status,"tokens_per_second":speed,
                    "elapsed_seconds":float(index),"time_to_first_token_seconds":float(index)/10})
            aggregate = db.aggregates()[0]
            self.assertEqual(aggregate["runs"],4)
            self.assertEqual(aggregate["completed"],3)
            self.assertEqual(aggregate["truncated"],1)
            self.assertEqual(aggregate["avg_tokens_per_second"],20.0)
            self.assertEqual(aggregate["median_tokens_per_second"],20.0)
            self.assertEqual(aggregate["stdev_tokens_per_second"],10.0)
            self.assertEqual(aggregate["median_elapsed_seconds"],2.0)
            db.close()

    def test_aggregates_count_individual_checks_not_task_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            db = ResultsDB(Path(temp) / "results.db")
            for passed, total in ((2, 2), (1, 2)):
                eid = db.create_experiment({"started_at":"now","task_id":"t","category":"test",
                    "repetition":1,"model":"m","run_label":"baseline","base_url":"local",
                    "config_json":"{}","prompt":"p","status":"running"})
                db.finish_experiment(eid, {"status":"completed",
                    "evaluation_status":"passed" if passed == total else "failed",
                    "evaluation_passed":passed,"evaluation_total":total})
            aggregate = db.aggregates()[0]
            self.assertEqual(aggregate["checks_passed"], 3)
            self.assertEqual(aggregate["checks_scored"], 4)
            db.close()

    def test_run_exits_nonzero_when_all_runs_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.toml"
            config.write_text('[server]\nbase_url="http://127.0.0.1:1"\ntimeout_seconds=1\n'
                              '[experiment]\ndatabase="results.db"\nrepetitions=1\n', encoding="utf-8")
            tasks = Path(temp) / "tasks.jsonl"
            tasks.write_text('{"id":"t","prompt":"x"}\n', encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
            result = subprocess.run([sys.executable, "-m", "evo_experiments.cli", "run",
                                     "--config", str(config), "--tasks", str(tasks)],
                                    capture_output=True, text=True, env=env, cwd=temp, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("failed", (result.stdout + result.stderr).lower())

    def test_non_sse_response_is_rejected(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlainJSONHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(ModelRequestError):
                stream_chat_completion(base_url=f"http://127.0.0.1:{server.server_port}",
                    api_key="k", model="m", system_prompt="s", prompt="p",
                    max_tokens=5, temperature=0, timeout=3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_empty_report_and_summary_csv_have_headers(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.toml"
            config.write_text(f'[experiment]\ndatabase="{Path(temp)/"empty.db"}"\n', encoding="utf-8")
            for command, header in (("report", "id,started_at"), ("summary", "configuration,model")):
                result = subprocess.run([sys.executable, "-m", "evo_experiments.cli", command,
                                         "--config", str(config), "--csv"],
                                        capture_output=True, text=True, env=env, cwd=temp, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(header), result.stdout)

    def test_missing_config_and_tasks_report_clean_errors(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.toml"
            config.write_text(f'[server]\nbase_url="http://127.0.0.1:1"\ntimeout_seconds=1\n'
                              f'[experiment]\ndatabase="{Path(temp)/"x.db"}"\n', encoding="utf-8")
            commands = (
                ["doctor", "--config", str(Path(temp) / "missing.toml")],
                ["run", "--config", str(config), "--tasks", str(Path(temp) / "missing.jsonl")],
            )
            for command in commands:
                result = subprocess.run([sys.executable, "-m", "evo_experiments.cli", *command],
                                        capture_output=True, text=True, env=env, cwd=temp, timeout=30)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("Error:", result.stderr)

    def test_response_is_preserved_when_evaluation_raises(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                db_path = Path(temp) / "results.db"
                config = Path(temp) / "config.toml"
                config.write_text(f'[server]\nbase_url="http://127.0.0.1:{server.server_port}"\n'
                                  f'model="fake-model"\ntimeout_seconds=3\n'
                                  f'[experiment]\ndatabase="{db_path}"\n'
                                  f'sample_interval_seconds=0.2\nrepetitions=1\n', encoding="utf-8")
                tasks = Path(temp) / "tasks.jsonl"
                tasks.write_text('{"id":"t","prompt":"p"}\n', encoding="utf-8")
                with patch("evo_experiments.runner.evaluate_task", side_effect=RuntimeError("boom")):
                    run_tasks(load_config(config), tasks)
                db = ResultsDB(db_path)
                row = db.connection.execute(
                    "SELECT status,response,error FROM experiments").fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["response"], "hello world")
                self.assertIn("boom", row["error"])
                db.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__ == "__main__":
    unittest.main()
