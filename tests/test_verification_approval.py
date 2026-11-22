import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from evo_core.api import create_app, AgentApproval
    from evo_core import orchestration
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "FastAPI desktop dependencies are not installed")
class VerificationApprovalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / "config.toml"
        self.config.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{root}"\nallowed_commands=[["python","-c"]]\n',
            encoding="utf-8",
        )
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop"
        }
        self.routes = {(route.path, method): route.endpoint
                       for route in self.app.routes if hasattr(route, "endpoint")
                       for method in (route.methods or [])}
        with self.app.state.lab_db.lock:
            self.plan = orchestration.create_plan(
                self.app.state.lab_db.connection,
                "Verify command", str(root),
                {
                    "title": "Verify command",
                    "summary": "Run a verification command.",
                    "steps": [
                        {
                            "title": "Implement",
                            "description": "Make a trivial change.",
                            "expected_outcome": "Implementation complete.",
                            "verification": "Run the configured check.",
                            "verification_commands": [["python", "-c", "print('ok')"]],
                        }
                    ],
                },
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, self.plan["id"])

    def tearDown(self):
        self.app.state.execution_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _wait_pending(self, run_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.routes[("/api/v1/agents/{run_id}", "GET")](run_id)
            if body.get("pending_approval"):
                return body["pending_approval"]
            if body.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return None
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for a pending approval")

    def _wait_terminal(self, run_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.routes[("/api/v1/agents/{run_id}", "GET")](run_id)
            if body.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return body
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for terminal run status")

    def test_approved_verification_executes_and_persists_evidence(self):
        fake_result = {
            "argv": ["python", "-c", "print('ok')"],
            "returncode": 0,
            "stdout": "ok\n",
            "stderr": "",
            "elapsed_seconds": 0.01,
        }
        with patch("evo_core.workspace.Workspace.run", return_value=fake_result) as run_mock:
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](self.plan["id"])
            self.assertEqual(result["status"], "running")
            run_id = result["run_id"]

            pending = self._wait_pending(run_id)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["tool_name"], "run_command")
            self.assertEqual(pending["arguments"]["argv"], ["python", "-c", "print('ok')"])

            approval = self.routes[("/api/v1/agents/{run_id}/approval", "POST")](run_id, AgentApproval(approved=True))
            self.assertTrue(approval["approved"])

            run = self._wait_terminal(run_id)
            self.assertIn(run["status"], {"completed", "failed"})

            plan = self.routes[("/api/v1/agents/plans/{plan_id}", "GET")](self.plan["id"])
            checks = plan["steps"][0]["verification_checks"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["status"], "passed")
            self.assertEqual(checks[0]["exit_code"], 0)
            self.assertEqual(checks[0]["stdout"], "ok\n")
            self.assertEqual(plan["steps"][0]["verification_status"], "passed")
            run_mock.assert_called_once_with(["python", "-c", "print('ok')"], 120)

    def test_rejected_verification_does_not_execute_and_is_denied(self):
        with patch("evo_core.workspace.Workspace.run", side_effect=AssertionError("workspace command must not run")):
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](self.plan["id"])
            self.assertEqual(result["status"], "running")
            run_id = result["run_id"]

            pending = self._wait_pending(run_id)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["tool_name"], "run_command")

            approval = self.routes[("/api/v1/agents/{run_id}/approval", "POST")](run_id, AgentApproval(approved=False))
            self.assertFalse(approval["approved"])

            run = self._wait_terminal(run_id)
            self.assertIn(run["status"], {"completed", "failed", "cancelled"})

            plan = self.routes[("/api/v1/agents/plans/{plan_id}", "GET")](self.plan["id"])
            checks = plan["steps"][0]["verification_checks"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["status"], "denied")
            self.assertEqual(plan["steps"][0]["verification_status"], "failed")


if __name__ == "__main__":
    unittest.main()
