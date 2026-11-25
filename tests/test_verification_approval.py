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

    def test_schema1_approved_verification_is_rejected_before_execution(self):
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
        self.assertEqual(raised.exception.status_code, 409)
        run_mock.assert_not_called()

    def test_schema1_rejected_verification_is_also_non_executable(self):
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
        self.assertEqual(raised.exception.status_code, 409)
        run_mock.assert_not_called()


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
        components = {
            "primary_model": {
                "type": "model", "component_version": 1,
                "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
                "settings": {"endpoint": "http://127.0.0.1:18997/v1", "model": "test-model", "timeout_seconds": 30},
            },
            "assistant_runtime": {
                "type": "assistant_runtime", "component_version": 1,
                "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                "settings": {
                    "model_component": "primary_model", "persona_prompt": "",
                    "max_output_tokens": 256, "temperature": 0.0,
                    "context_window_tokens": 4096, "history_messages": 4,
                    "max_history_chars": 4000, "memory_limit": 2,
                },
            },
        }
        legacy_policy = revision_components.get("command_policy")
        if legacy_policy is not None:
            components["project_policy"] = {
                "type": "command_policy", "component_version": 1,
                "adapter": {"id": "evo_command_policy", "contract_version": 1},
                "settings": {"allowed_commands": legacy_policy.get("allowed_commands")},
            }
        definition = {
            "schema_version": 2,
            "components": components,
            "entrypoints": {"assistant": "assistant_runtime"},
        }
        config_result = create_configuration(store, definition, name="cfg")
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
        if hasattr(self, "app"):
            self.app.state.execution_executor.shutdown(wait=True, cancel_futures=False)
            self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
            self.app.state.assistant.close()
            self.app.state.lab_db.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_missing_project_policy_denies_command(self):
        self._make_app([["python", "-c"]], {})
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
            self.assertEqual(raised.exception.status_code, 409)
            run_mock.assert_not_called()

    def test_empty_project_policy_denies_command(self):
        self._make_app([["python", "-c"]], {"command_policy": {"allowed_commands": []}})
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
            self.assertEqual(raised.exception.status_code, 409)
            run_mock.assert_not_called()

    def test_malformed_project_policy_fails_closed_before_execution(self):
        from evo_core.command_policy import CommandPolicyError, project_command_prefixes
        with self.assertRaises(CommandPolicyError):
            project_command_prefixes({
                "definition": {
                    "schema_version": 1,
                    "components": {"command_policy": {"allowed_commands": "python"}},
                }
            })

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
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
            self.assertEqual(raised.exception.status_code, 409)
            run_mock.assert_not_called()

    def test_plan_without_verification_commands_is_rejected_before_execution(self):
        self._make_app([["python", "-c"]], {"command_policy": {"allowed_commands": [["python", "-c"]]}})
        with self.app.state.lab_db.lock:
            plan = orchestration.create_plan(
                self.app.state.lab_db.connection,
                "Unverified plan",
                self.workspace["workspace_id"],
                str(self.checkout_dir),
                {"title": "Unverified plan", "summary": "Change files without a verification command.",
                 "steps": [{"title": "Implement", "description": "Create a file.",
                            "expected_outcome": "The file exists.",
                            "verification": "No command supplied.",
                            "verification_commands": []}]},
                project_id=self.project["project_id"],
                store=self.app.state.store,
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, plan["id"])
            self.plan = plan
        with patch("evo_core.workspace.Workspace.run") as run_mock:
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("no configured verification command", raised.exception.detail)
            run_mock.assert_not_called()

    def test_persisted_verification_command_no_longer_allowed(self):
        # A previously valid plan must be revalidated against the current effective allowlist.
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
            with self.assertRaises(HTTPException) as raised:
                self.routes[("/api/v1/agents/plans/{plan_id}/execute", "POST")](
                    self.plan["id"], project_id=self.project["project_id"],
                    workspace_id=self.workspace["workspace_id"])
            self.assertEqual(raised.exception.status_code, 409)
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
