import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from evo_core.api import create_app, SchedulerJobInput, WorkloadExecuteInput
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "FastAPI desktop dependencies are not installed")
class ManagedExecutionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / "config.toml"
        self.config.write_text(
            f'[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{root}"\nallowed_commands=[["python","-c"]]\n',
            encoding="utf-8",
        )
        self.app = create_app(self.config)
        self.routes = {(route.path, method): route.endpoint
                       for route in self.app.routes if hasattr(route, "endpoint")
                       for method in (route.methods or [])}

    def tearDown(self):
        self.app.state.execution_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_api_rejects_commands_outside_configured_allowlist(self):
        create = self.routes[("/api/v1/hardware/scheduler/jobs", "POST")]
        job = create(SchedulerJobInput(name="CPU job", kind="cpu", gpu_heavy=False,
                                       estimated_ram_mib=128))
        with patch("evo_core.api.sample_nvidia_smi", return_value={
            "ram_available_bytes": 8 * 1024**3, "ram_used_percent": 40}):
            self.routes[("/api/v1/hardware/scheduler/dispatch", "POST")](limit=5)
        with self.assertRaises(HTTPException) as raised:
            self.routes[("/api/v1/hardware/scheduler/jobs/{job_id}/execute", "POST")](
                job["id"], WorkloadExecuteInput(argv=["sh", "-c", "echo unsafe"]))
        self.assertEqual(raised.exception.status_code, 409)

    def test_api_requires_reserved_job_and_explicitly_queues_managed_execution(self):
        create = self.routes[("/api/v1/hardware/scheduler/jobs", "POST")]
        job = create(SchedulerJobInput(name="CPU job", kind="cpu", gpu_heavy=False,
                                       estimated_ram_mib=128))
        with self.assertRaises(HTTPException) as raised:
            self.routes[("/api/v1/hardware/scheduler/jobs/{job_id}/execute", "POST")](
                job["id"], WorkloadExecuteInput(argv=["python", "-c", "print('ok')"]))
        self.assertEqual(raised.exception.status_code, 409)
        with patch("evo_core.api.sample_nvidia_smi", return_value={
            "ram_available_bytes": 8 * 1024**3, "ram_used_percent": 40}):
            self.routes[("/api/v1/hardware/scheduler/dispatch", "POST")](limit=5)
        with patch.object(self.app.state.execution_executor, "submit") as submit:
            result = self.routes[("/api/v1/hardware/scheduler/jobs/{job_id}/execute", "POST")](
                job["id"], WorkloadExecuteInput(argv=["python", "-c", "print('ok')"]))
        self.assertEqual(result["status"], "queued")
        submit.assert_called_once()
        executions = self.routes[("/api/v1/hardware/executions", "GET")]()
        self.assertEqual(executions[0]["id"], result["execution_id"])
        self.assertEqual(executions[0]["argv"], ["python", "-c", "print('ok')"])
        caps = self.routes[("/api/v1/capabilities", "GET")]()
        self.assertTrue(caps["hardware_managed_execution"])
        self.assertFalse(caps["hardware_process_control"])


if __name__ == "__main__":
    unittest.main()
