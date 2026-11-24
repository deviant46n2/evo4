import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from evo_core.api import create_app, AgentApproval
    from evo_core import orchestration
    from evo_core.project_checkouts import register_project, register_checkout
    from evo_core.ai_configurations import create_configuration
    from evo_core.workspaces import create_workspace
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
        store = self.app.state.store
        project = register_project(store, "Project")
        checkout_dir = root / "checkout"
        checkout_dir.mkdir()
        checkout = register_checkout(store, project["project_id"], checkout_dir)
        config_result = create_configuration(store, {"schema_version": 1, "components": {"command_policy": {"allowed_commands": [["python", "-c"]]}}}, name="cfg")
        configuration = config_result["configuration"]
        revision = config_result["revision"]
        workspace = create_workspace(
            store,
            "Workspace",
            project["project_id"],
            configuration["configuration_id"],
            revision["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.project = project
        self.workspace = workspace
        with self.app.state.lab_db.lock:
            self.plan = orchestration.create_plan(
                self.app.state.lab_db.connection,
                "Verify command", workspace["workspace_id"], str(checkout_dir),
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
                project_id=project["project_id"],
                store=store,
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
            body = self.routes[("/api/v1/agents/{run_id:uuid}", "GET")](
                run_id, project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            if body.get("pending_approval"):
                return body["pending_approval"]
            if body.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return None
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for a pending approval")

    def _wait_terminal(self, run_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.routes[("/api/v1/agents/{run_id:uuid}", "GET")](
                run_id, project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
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
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            self.assertEqual(result["status"], "running")
            run_id = result["run_id"]

            pending = self._wait_pending(run_id)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["tool_name"], "run_command")
            self.assertEqual(pending["arguments"]["argv"], ["python", "-c", "print('ok')"])

            approval = self.routes[("/api/v1/agents/{run_id}/approval", "POST")](
                run_id, AgentApproval(approved=True),
                project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            self.assertTrue(approval["approved"])

            run = self._wait_terminal(run_id)
            self.assertIn(run["status"], {"completed", "failed"})

            plan = self.routes[("/api/v1/agents/plans/{plan_id}", "GET")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            checks = plan["steps"][0]["verification_checks"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["status"], "passed")
            self.assertEqual(checks[0]["exit_code"], 0)
            self.assertEqual(checks[0]["stdout"], "ok\n")
            self.assertEqual(plan["steps"][0]["verification_status"], "passed")
            run_mock.assert_called_once_with(["python", "-c", "print('ok')"], 120)

    def test_rejected_verification_does_not_execute_and_is_denied(self):
        with patch("evo_core.workspace.Workspace.run", side_effect=AssertionError("workspace command must not run")):
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            self.assertEqual(result["status"], "running")
            run_id = result["run_id"]

            pending = self._wait_pending(run_id)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["tool_name"], "run_command")

            approval = self.routes[("/api/v1/agents/{run_id}/approval", "POST")](
                run_id, AgentApproval(approved=False),
                project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            self.assertFalse(approval["approved"])

            run = self._wait_terminal(run_id)
            self.assertIn(run["status"], {"completed", "failed", "cancelled"})

            plan = self.routes[("/api/v1/agents/plans/{plan_id}", "GET")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            checks = plan["steps"][0]["verification_checks"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["status"], "denied")
            self.assertEqual(plan["steps"][0]["verification_status"], "failed")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(AVAILABLE, "FastAPI desktop dependencies are not installed")
class CommandPolicyVerificationTests(unittest.TestCase):
    def _make_app(self, allowed_commands, revision_components):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / "config.toml"
        self.config.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{root}"\nallowed_commands={allowed_commands}\n',
            encoding="utf-8",
        )
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop"
        }
        self.routes = {(route.path, method): route.endpoint
                       for route in self.app.routes if hasattr(route, "endpoint")
                       for method in (route.methods or [])}
        store = self.app.state.store
        project = register_project(store, "Project")
        checkout_dir = root / "checkout"
        checkout_dir.mkdir()
        checkout = register_checkout(store, project["project_id"], checkout_dir)
        config_result = create_configuration(store, {"schema_version": 1, "components": revision_components}, name="cfg")
        configuration = config_result["configuration"]
        revision = config_result["revision"]
        workspace = create_workspace(
            store, "Workspace", project["project_id"],
            configuration["configuration_id"], revision["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.project = project
        self.workspace = workspace
        self.checkout_dir = checkout_dir
        with self.app.state.lab_db.lock:
            self.plan = orchestration.create_plan(
                self.app.state.lab_db.connection, "Verify command", workspace["workspace_id"], str(checkout_dir),
                {"title": "Verify command", "summary": "Run a verification command.",
                 "steps": [{"title": "Implement", "description": "Make a trivial change.",
                            "expected_outcome": "Implementation complete.",
                            "verification": "Run the configured check.",
                            "verification_commands": [["python", "-c", "print('ok')"]]}]},
                project_id=project["project_id"],
                store=store,
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, self.plan["id"])
        return self

    def tearDown(self):
        self.app.state.execution_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_missing_project_policy_denies_command(self):
        self._make_app([["python", "-c"]], {})
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            self.assertEqual(result["status"], "running")
            run_id = result["run_id"]
            run = self._wait_terminal(run_id)
            self.assertEqual(run["status"], "failed")
            store = self.app.state.store
            stored = store.get_agent_run(run_id)
            metadata = __import__("json").loads(stored["metadata_json"] or "{}")
            self.assertNotEqual(metadata.get("lifecycle"), "awaiting_approval")
            self.assertIsNone(metadata.get("pending_approval_id"))
            run_mock.assert_not_called()

    def test_empty_project_policy_denies_command(self):
        self._make_app([["python", "-c"]], {"command_policy": {"allowed_commands": []}})
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            run_id = result["run_id"]
            run = self._wait_terminal(run_id)
            self.assertEqual(run["status"], "failed")
            store = self.app.state.store
            stored = store.get_agent_run(run_id)
            metadata = __import__("json").loads(stored["metadata_json"] or "{}")
            self.assertNotEqual(metadata.get("lifecycle"), "awaiting_approval")
            self.assertIsNone(metadata.get("pending_approval_id"))
            run_mock.assert_not_called()

    def test_malformed_project_policy_fails_closed_before_execution(self):
        self._make_app([["python", "-c"]], {"command_policy": {"allowed_commands": "python"}})
        status = None
        try:
            self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
        except Exception as exc:
            status = getattr(exc, "status_code", None)
        self.assertEqual(status, 422)

    def test_project_policy_narrows_global_allowlist(self):
        self._make_app([["python", "-c"], ["python", "-m", "pytest"]],
                       {"command_policy": {"allowed_commands": [["python", "-c"]]}})
        # Persist a plan whose verification command is not in the effective project policy.
        with self.app.state.lab_db.lock:
            plan = orchestration.create_plan(
                self.app.state.lab_db.connection,
                "Verify command",
                self.workspace["workspace_id"],
                str(self.checkout_dir),
                {"title": "Verify command", "summary": "Run a verification command.",
                 "steps": [{"title": "Implement", "description": "Make a trivial change.",
                            "expected_outcome": "Implementation complete.",
                            "verification": "Run the configured check.",
                            "verification_commands": [["python", "-m", "pytest"]]}]},
                allowed_commands=[["python", "-c"], ["python", "-m", "pytest"]],
                project_id=self.project["project_id"],
                store=self.app.state.store,
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, plan["id"])
            self.plan = plan
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            run_id = result["run_id"]
            run = self._wait_terminal(run_id)
            self.assertEqual(run["status"], "failed")
            store = self.app.state.store
            stored = store.get_agent_run(run_id)
            metadata = __import__("json").loads(stored["metadata_json"] or "{}")
            self.assertNotEqual(metadata.get("lifecycle"), "awaiting_approval")
            self.assertIsNone(metadata.get("pending_approval_id"))
            run_mock.assert_not_called()

    def test_persisted_verification_command_no_longer_allowed(self):
        # Broad policy at proposal time, then a narrower persisted plan is simulated by
        # creating a plan whose verification command is not in the effective policy.
        self._make_app([["python", "-c"], ["python", "-m", "pytest"]],
                       {"command_policy": {"allowed_commands": [["python", "-c"]]}})
        with self.app.state.lab_db.lock:
            plan = orchestration.create_plan(
                self.app.state.lab_db.connection,
                "Verify command",
                self.workspace["workspace_id"],
                str(self.checkout_dir),
                {"title": "Verify command", "summary": "Run a verification command.",
                 "steps": [{"title": "Implement", "description": "Make a trivial change.",
                            "expected_outcome": "Implementation complete.",
                            "verification": "Run the configured check.",
                            "verification_commands": [["python", "-m", "pytest"]]}]},
                allowed_commands=[["python", "-c"], ["python", "-m", "pytest"]],
                project_id=self.project["project_id"],
                store=self.app.state.store,
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, plan["id"])
            self.plan = plan
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            result = self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                self.plan["id"], project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            run_id = result["run_id"]
            run = self._wait_terminal(run_id)
            self.assertEqual(run["status"], "failed")
            store = self.app.state.store
            stored = store.get_agent_run(run_id)
            metadata = __import__("json").loads(stored["metadata_json"] or "{}")
            self.assertNotEqual(metadata.get("lifecycle"), "awaiting_approval")
            self.assertIsNone(metadata.get("pending_approval_id"))
            run_mock.assert_not_called()

    def _wait_terminal(self, run_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = self.routes[("/api/v1/agents/{run_id:uuid}", "GET")](
                run_id, project_id=self.project["project_id"],
                workspace_id=self.workspace["workspace_id"])
            if body.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return body
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for terminal run")
