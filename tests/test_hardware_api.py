import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import FastAPI
    from evo_core.api import create_app
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI desktop dependencies are not installed")
class HardwareApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / "config.toml"
        self.config.write_text(
            f'[server]\nbase_url="http://user:secret@127.0.0.1:18997/v1?api_key=secret"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n',
            encoding="utf-8",
        )
        self.app = create_app(self.config)
        self.routes = {route.path: route.endpoint for route in self.app.routes if hasattr(route, "endpoint")}

    def tearDown(self):
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_memory_search_preview_exposes_ranked_evidence(self):
        store = self.app.state.assistant.store
        store.add_memory("The local Qwen model uses CUDA for inference",
                         category="models", tags=["llama.cpp"], source="user")
        endpoint = self.routes["/api/v1/memories/search"]
        payload = endpoint(q="Qwen CUDA inference", limit=5)
        self.assertEqual(payload["count"], 1)
        self.assertIn("no embeddings", payload["retrieval"])
        self.assertIn("content:", payload["matches"][0]["reason"])
        self.assertGreater(payload["matches"][0]["coverage"], 0)

    def test_memory_review_endpoint_is_read_only_and_labels_lexical_suggestions(self):
        store = self.app.state.assistant.store
        first = store.add_memory("RTX 5070 Ti has 16 GB VRAM and CUDA support",
                                 category="hardware", source="user")
        second = store.add_memory("RTX 5070 Ti has 16 GB VRAM with CUDA support",
                                  category="hardware", source="user")
        before = {row["id"]: row["access_count"] for row in store.list_memories(10)}
        payload = self.routes["/api/v1/memories/review"](limit=10)
        self.assertFalse(payload["mutates_memory"])
        self.assertIn("no embeddings", payload["method"])
        self.assertEqual(payload["count"], 1)
        pair = payload["suggestions"][0]
        self.assertEqual({pair["left"]["id"], pair["right"]["id"]}, {first, second})
        after = {row["id"]: row["access_count"] for row in store.list_memories(10)}
        self.assertEqual(before, after)

    def test_hardware_endpoint_is_observe_only_and_surfaces_pressure(self):
        sample = {
            "sampled_at": "2026-11-21T12:00:00+00:00",
            "gpu_available": True, "gpu_memory_used_percent": 95,
            "gpu_temperature_c": 86, "ram_used_percent": 92,
            "cpu_utilization_percent": 97, "gpu_processes": [],
        }
        with patch("evo_core.api.sample_nvidia_smi", return_value=sample):
            payload = self.routes["/api/v1/hardware/current"]()
        self.assertEqual(payload["policy"]["mode"], "observe_only")
        self.assertEqual(payload["runtime"]["endpoint"], "http://127.0.0.1:18997/v1")
        self.assertNotIn("secret", payload["runtime"]["endpoint"])
        self.assertFalse(payload["policy"]["actions_enabled"])
        self.assertEqual(
            {item["code"] for item in payload["warnings"]},
            {"vram_pressure", "gpu_temperature", "ram_pressure", "cpu_saturation"},
        )

    def test_experiments_endpoint_reports_empty_initialized_lab_database(self):
        payload = self.routes["/api/v1/experiments"](limit=30)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["runs"], [])


    def test_experiment_and_resource_history_are_read_from_shared_database(self):
        lab = self.app.state.lab_db
        experiment_id = lab.create_experiment({
            "started_at": "2026-11-21T12:00:00+00:00", "task_id": "local-smoke",
            "category": "coding", "repetition": 1, "model": "test-model",
            "run_label": "test-config", "base_url": "http://127.0.0.1:18997",
            "config_json": "{}", "prompt": "hello", "status": "completed",
            "tokens_per_second": 42.5, "time_to_first_token_seconds": 0.4,
        })
        lab.add_sample(experiment_id, {
            "sampled_at": "2026-11-21T12:00:01+00:00",
            "gpu_memory_used_mib": 4096, "gpu_memory_total_mib": 16384,
            "ram_used_mib": 8192, "cpu_utilization_percent": 35,
        })
        experiments = self.routes["/api/v1/experiments"](limit=30)
        self.assertTrue(experiments["available"])
        self.assertEqual(experiments["runs"][0]["task_id"], "local-smoke")
        self.assertEqual(experiments["aggregates"][0]["avg_tokens_per_second"], 42.5)
        history = self.routes["/api/v1/hardware/history"](limit=180)
        self.assertEqual(history[0]["experiment_id"], experiment_id)
        self.assertEqual(history[0]["cpu_utilization_percent"], 35)

    def test_hardware_history_is_empty_before_first_experiment(self):
        payload = self.routes["/api/v1/hardware/history"](limit=180)
        self.assertEqual(payload, [])

    def test_hardware_probe_exception_returns_partial_dashboard_payload(self):
        with patch("evo_core.api.sample_nvidia_smi", side_effect=RuntimeError("probe unavailable")):
            payload = self.routes["/api/v1/hardware/current"]()
        self.assertFalse(payload["sample"]["gpu_available"])
        self.assertIn("RuntimeError", payload["telemetry_error"])
        self.assertEqual(payload["budget"]["background_work"], "unknown")

    def test_cpu_ram_only_telemetry_is_not_reported_as_unknown(self):
        sample = {
            "sampled_at": "2026-11-21T12:00:00+00:00",
            "gpu_available": False, "gpu_processes": [],
            "ram_used_percent": 42, "ram_available_bytes": 8 * 1024**3,
            "cpu_utilization_percent": 18,
        }
        with patch("evo_core.api.sample_nvidia_smi", return_value=sample):
            payload = self.routes["/api/v1/hardware/current"]()
        self.assertEqual(payload["budget"]["background_work"], "limited")
        self.assertIn("GPU headroom is unknown", payload["budget"]["reason"])

    def test_demo_seed_endpoints_are_reversible_and_label_experiment_data(self):
        seed_endpoint = next(route.endpoint for route in self.app.routes
                             if getattr(route, "path", None) == "/api/v1/demo/seed" and "POST" in (getattr(route, "methods", None) or set()))
        clear_endpoint = next(route.endpoint for route in self.app.routes
                              if getattr(route, "path", None) == "/api/v1/demo/seed" and "DELETE" in (getattr(route, "methods", None) or set()))
        seeded = seed_endpoint()
        self.assertGreater(seeded["seeded"]["memories"], 0)
        status = self.routes["/api/v1/demo/status"]()
        self.assertTrue(status["active"])
        experiments = self.routes["/api/v1/experiments"](limit=30)
        self.assertTrue(all(row["is_demo"] for row in experiments["runs"]))
        self.assertTrue(all(row["is_demo"] for row in experiments["aggregates"]))
        history = self.routes["/api/v1/hardware/history"](limit=180)
        self.assertTrue(history)
        self.assertTrue(all(row["is_demo"] for row in history))
        removed = clear_endpoint()
        self.assertGreater(removed["removed"]["agent_runs"], 0)
        self.assertFalse(self.routes["/api/v1/demo/status"]()["active"])


if __name__ == "__main__":
    unittest.main()
