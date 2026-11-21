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


if __name__ == "__main__":
    unittest.main()
