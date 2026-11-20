import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from evo_experiments.client import list_models, stream_chat_completion
from evo_experiments.config import load_config
from evo_experiments.db import ResultsDB
from evo_experiments.runner import build_run_manifest, load_tasks

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data":[{"id":"fake-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length","0"))
        self.server.last_payload = json.loads(self.rfile.read(length))
        events = [
            {"choices":[{"delta":{"content":"hello "}}]},
            {"choices":[{"delta":{"content":"world"}}]},
            {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":2}},
        ]
        body = "".join("data: "+json.dumps(event)+"\n\n" for event in events)+"data: [DONE]\n\n"
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Content-Length",str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        pass

class HarnessTests(unittest.TestCase):
    def test_config_load_and_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text('[server]\nmodel="test"\n[experiment]\nrepetitions=2\n[run]\ncontext_size=49152\n', encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.model, "test")
            self.assertEqual(config.repetitions, 2)
            manifest = build_run_manifest(config)
            self.assertEqual(manifest["runtime_manifest"]["context_size"], 49152)

    def test_model_file_hash_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "tiny.gguf"
            model.write_bytes(b"fixture-model")
            config_path = Path(temp) / "config.toml"
            config_path.write_text(f'[run]\nmodel_file="{model}"\n', encoding="utf-8")
            manifest = build_run_manifest(load_config(config_path))
            self.assertEqual(len(manifest["runtime_manifest"]["model_sha256"]), 64)

    def test_database_round_trip_and_cross_thread_sample(self):
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
            self.assertEqual(db.connection.execute("SELECT count(*) FROM resource_samples").fetchone()[0], 1)
            db.close()

    def test_jsonl_tasks_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            path.write_text(json.dumps({"id":"one","prompt":"hello"}) + "\n", encoding="utf-8")
            self.assertEqual(load_tasks(path)[0]["id"], "one")
            path.write_text('{"id":"dup","prompt":"a"}\n{"id":"dup","prompt":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate task id"):
                load_tasks(path)

    def test_openai_compatible_server_diagnostic_and_stream(self):
        server = ThreadingHTTPServer(("127.0.0.1",0), FakeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(list_models(base_url=base, api_key="test", timeout=3), ["fake-model"])
            result = stream_chat_completion(base_url=base, api_key="test", model="fake-model",
                system_prompt="system", prompt="prompt", max_tokens=20, temperature=0, timeout=3)
            self.assertEqual(result["response"], "hello world")
            self.assertEqual(result["prompt_tokens"], 8)
            self.assertEqual(result["completion_tokens"], 2)
            self.assertIsNotNone(result["time_to_first_token_seconds"])
            self.assertEqual(server.last_payload["messages"][1]["content"], "prompt")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__ == "__main__":
    unittest.main()
