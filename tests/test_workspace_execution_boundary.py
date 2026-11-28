import asyncio
import json as _json
import tempfile
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.ai_configurations import create_configuration
from evo_core.api import create_app
from evo_core.orchestration import create_plan, approve_plan, get_plan
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project, refresh_checkout_availability
from evo_core.store import EvoStore
from evo_core.workspaces import (
    create_workspace,
    resolve_executable_workspace,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
    WorkspaceRelationshipError,
    WorkspaceNotExecutableError,
)

VALID_DEFINITION = {
    "schema_version": 2,
    "components": {
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
        "project_policy": {
            "type": "command_policy", "component_version": 1,
            "adapter": {"id": "evo_command_policy", "contract_version": 1},
            "settings": {"allowed_commands": [["python", "-c"]]},
        },
    },
    "entrypoints": {"assistant": "assistant_runtime"},
}


def make_config(root):
    config = root / "config.toml"
    config.write_text(
        '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
        f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
        f'[workspace]\nroot="{root}"\nallowed_commands=[["python","-c"]]\n',
        encoding="utf-8",
    )
    return config


def asgi_request(app, method, path, body=None):
    if "?" in path:
        path_part, query_part = path.split("?", 1)
    else:
        path_part, query_part = path, ""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path_part,
        "raw_path": path_part.encode(),
        "query_string": query_part.encode(),
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "state": {},
    }
    payload = b"" if body is None else _json.dumps(body).encode()
    messages = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = messages[0]["status"]
    raw = b"".join(m.get("body", b"") for m in messages if m.get("type") == "http.response.body")
    try:
        data = json.loads(raw)
    except Exception:
        data = raw
    return status, data


def make_fixtures(root):
    store = EvoStore(root / "evo.sqlite3")
    initialize_platform_registry(store)
    project = register_project(store, "Project")
    directory = root / "checkout"
    directory.mkdir()
    checkout = register_checkout(store, project["project_id"], directory)
    config_result = create_configuration(store, VALID_DEFINITION, name="cfg")
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
    return store, project, checkout, directory, configuration, revision, workspace


class WorkspaceExecutionResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store, self.project, self.checkout, self.directory, self.configuration, self.revision, self.workspace = make_fixtures(self.root)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_valid_resolves_canonical_path(self):
        binding = resolve_executable_workspace(self.store, self.workspace["workspace_id"])
        self.assertEqual(binding["path"], self.directory.resolve())
        self.assertEqual(binding.path, self.directory.resolve())
        self.assertEqual(binding["workspace_id"], self.workspace["workspace_id"])

    def test_unknown_workspace(self):
        with self.assertRaises(WorkspaceNotFoundError):
            resolve_executable_workspace(self.store, "missing")

    def test_blank_workspace_id(self):
        with self.assertRaises(WorkspaceValidationError):
            resolve_executable_workspace(self.store, "   ")

    def test_archived_workspace(self):
        from evo_core.workspaces import archive_workspace

        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=self.workspace["version"])
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])

    def test_inactive_project(self):
        from evo_core.project_checkouts import archive_project

        archive_project(self.store, self.project["project_id"], expected_version=self.project["version"])
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])

    def test_inactive_configuration(self):
        from evo_core.ai_configurations import archive_configuration

        archive_configuration(self.store, self.configuration["configuration_id"], expected_version=self.configuration["version"])
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])

    def test_invalid_pinned_revision(self):
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute(
                "UPDATE workspaces SET configuration_revision_id=? WHERE workspace_id=?",
                ("missing-revision", self.workspace["workspace_id"]),
            )
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])

    def test_workspace_without_checkout(self):
        workspace = create_workspace(
            self.store,
            "NoCheckout",
            self.project["project_id"],
            self.configuration["configuration_id"],
            self.revision["revision_id"],
        )
        with self.assertRaises(WorkspaceNotExecutableError):
            resolve_executable_workspace(self.store, workspace["workspace_id"])

    def test_checkout_wrong_project(self):
        other_project, other_checkout, _ = make_project(self.store, self.root) if False else (None, None, None)
        # Build a second project/checkout manually.
        from evo_core.project_checkouts import register_project, register_checkout

        other_project = register_project(self.store, "Other")
        other_dir = self.root / "other-checkout"
        other_dir.mkdir()
        other_checkout = register_checkout(self.store, other_project["project_id"], other_dir)
        with self.store.lock:
            self.store.db.execute("PRAGMA foreign_keys=OFF")
            self.store.db.execute(
                "UPDATE workspaces SET checkout_id=? WHERE workspace_id=?",
                (other_checkout["checkout_id"], self.workspace["workspace_id"]),
            )
            self.store.db.commit()
            self.store.db.execute("PRAGMA foreign_keys=ON")
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])

    def test_checkout_unavailable_stored(self):
        self.directory.rmdir()
        refresh_checkout_availability(self.store, self.checkout["checkout_id"])
        with self.assertRaises(WorkspaceRelationshipError):
            resolve_executable_workspace(self.store, self.workspace["workspace_id"])
        self.directory.mkdir()

    def test_checkout_live_unavailable(self):
        # Keep stored availability "available" but make the path a file.
        self.directory.rmdir()
        self.directory.write_text("not a directory")
        try:
            with self.assertRaises(WorkspaceRelationshipError):
                resolve_executable_workspace(self.store, self.workspace["workspace_id"])
        finally:
            self.directory.unlink()
            self.directory.mkdir()

    def test_canonical_path_mismatch(self):
        replacement = self.root / "replacement"
        replacement.mkdir()
        self.directory.rename(self.root / "original-checkout")
        self.directory.symlink_to(replacement)
        try:
            with self.assertRaises(WorkspaceRelationshipError):
                resolve_executable_workspace(self.store, self.workspace["workspace_id"])
        finally:
            self.directory.unlink()
            (self.root / "original-checkout").rename(self.directory)


def make_project(store, root):
    project = register_project(store, "Project")
    directory = root / f"checkout-{project['project_id']}"
    directory.mkdir()
    checkout = register_checkout(store, project["project_id"], directory)
    return project, checkout, directory


class WorkspaceExecutionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": json.dumps({
                "title": "Plan",
                "summary": "Summary",
                "steps": [
                    {
                        "title": "Step",
                        "description": "Do work",
                        "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('verified')"]],
                    }
                ],
            }),
            "tool_calls": [],
            "finish_reason": "stop",
        }
        self.store = self.app.state.store
        self.project, self.checkout, self.directory, self.configuration, self.revision, self.workspace = None, None, None, None, None, None
        project = register_project(self.store, "Project")
        directory = self.root / "checkout"
        directory.mkdir()
        checkout = register_checkout(self.store, project["project_id"], directory)
        config_result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        configuration = config_result["configuration"]
        revision = config_result["revision"]
        workspace = create_workspace(
            self.store,
            "Workspace",
            project["project_id"],
            configuration["configuration_id"],
            revision["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.project, self.checkout, self.directory, self.configuration, self.revision, self.workspace = (
            project, checkout, directory, configuration, revision, workspace
        )

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _scoped_path(self, path):
        separator = "&" if "?" in path else "?"
        return (f"{path}{separator}project_id={self.project['project_id']}"
                f"&workspace_id={self.workspace['workspace_id']}")

    def _run_status(self, run_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            status, body = asgi_request(
                self.app, "GET", self._scoped_path(f"/api/v1/agents/{run_id}"))
            if status == 200 and body.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return status, body
            time.sleep(0.05)
        status, body = asgi_request(
            self.app, "GET", self._scoped_path(f"/api/v1/agents/{run_id}"))
        return status, body

    def test_valid_schema2_workspace_is_denied_before_agent_run_creation(self):
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        self.assertIn("P3.5", body["detail"])
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), before)

    def test_missing_workspace_id_rejected(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {"request": "inspect"})
        self.assertEqual(status, 422)

    def test_raw_workspace_path_cannot_authorize(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace": str(self.root),
        })
        self.assertEqual(status, 422)

    def test_invalid_workspace_rejected_before_run_creation(self):
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": "missing",
        })
        self.assertEqual(status, 404)
        after = len(self.store.list_agent_runs(limit=1000))
        self.assertEqual(before, after)

    def test_archived_workspace_rejected(self):
        from evo_core.workspaces import archive_workspace

        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=self.workspace["version"])
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 409)
        after = len(self.store.list_agent_runs(limit=1000))
        self.assertEqual(before, after)

    def test_plan_proposal_is_denied_before_provider_dispatch(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        self.assertIn("P3.5", body["detail"])

    def test_plan_creation_uses_resolved_path(self):
        with patch("evo_core.orchestration.propose_with_model") as mocked:
            mocked.return_value = {
                "title": "Plan",
                "summary": "Summary",
                "steps": [
                    {
                        "title": "Step",
                        "description": "Do work",
                        "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('verified')"]],
                    }
                ],
            }
            status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
                "request": "plan",
                "workspace_id": self.workspace["workspace_id"],
            })
            self.assertEqual(status, 503)
            mocked.assert_not_called()

    def test_legacy_plan_cannot_execute(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "legacy",
                None,
                str(self.directory),
                {
                    "title": "Legacy",
                    "summary": "Legacy",
                    "steps": [
                        {
                            "title": "Step",
                            "description": "Do work",
                            "expected_outcome": "Done",
                            "verification": "Check",
                        }
                    ],
                },
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        status, body = asgi_request(self.app, "POST", f"/api/v1/agents/plans/{plan['id']}/execute", {})
        self.assertEqual(status, 409)

    def test_approved_plan_is_not_scheduled_before_dispatch_admission(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "approved plan",
                self.workspace["workspace_id"],
                str(self.directory.resolve()),
                {
                    "title": "Approved plan", "summary": "Plan used to test dispatch admission.",
                    "steps": [{
                        "title": "Step", "description": "Do work", "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('ok')"]],
                    }],
                },
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(
            self.app, "POST",
            self._scoped_path(f"/api/v1/agents/plans/{plan['id']}/execute"), {},
        )
        self.assertEqual(status, 503)
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), before)
        self.assertEqual(get_plan(self.app.state.lab_db.connection, plan["id"])["status"], "approved")

    def test_plan_workspace_invalidated_after_approval(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "approved plan",
                self.workspace["workspace_id"],
                str(self.directory.resolve()),
                {
                    "title": "Approved plan", "summary": "Plan used to test dispatch admission.",
                    "steps": [{
                        "title": "Step", "description": "Do work", "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('ok')"]],
                    }],
                },
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        from evo_core.workspaces import archive_workspace
        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=self.workspace["version"])
        status, body = asgi_request(
            self.app, "POST",
            self._scoped_path(f"/api/v1/agents/plans/{plan['id']}/execute"), {},
        )
        self.assertEqual(status, 409)

    def test_worker_is_not_submitted_before_dispatch_admission(self):
        with patch.object(self.app.state.execution_executor, "submit") as submit:
            status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
                "request": "inspect",
                "workspace_id": self.workspace["workspace_id"],
            })
        self.assertEqual(status, 503)
        submit.assert_not_called()

    def test_plan_remains_approved_when_dispatch_is_disabled(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "approved plan",
                self.workspace["workspace_id"],
                str(self.directory.resolve()),
                {
                    "title": "Approved plan", "summary": "Plan used to test dispatch admission.",
                    "steps": [{
                        "title": "Step", "description": "Do work", "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('ok')"]],
                    }],
                },
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        path = self._scoped_path(f"/api/v1/agents/plans/{plan['id']}/execute")
        first_status, _ = asgi_request(self.app, "POST", path, {})
        second_status, _ = asgi_request(self.app, "POST", path, {})
        self.assertEqual(first_status, 503)
        self.assertEqual(second_status, 503)
        self.assertEqual(get_plan(self.app.state.lab_db.connection, plan["id"])["status"], "approved")

    def test_plan_worker_is_not_submitted_before_dispatch_admission(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "approved plan",
                self.workspace["workspace_id"],
                str(self.directory.resolve()),
                {
                    "title": "Approved plan", "summary": "Plan used to test dispatch admission.",
                    "steps": [{
                        "title": "Step", "description": "Do work", "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('ok')"]],
                    }],
                },
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        with patch.object(self.app.state.execution_executor, "submit") as submit:
            status, body = asgi_request(
                self.app, "POST",
                self._scoped_path(f"/api/v1/agents/plans/{plan['id']}/execute"), {},
            )
        self.assertEqual(status, 503)
        submit.assert_not_called()
        self.assertEqual(get_plan(self.app.state.lab_db.connection, plan["id"])["status"], "approved")


    def _workspace_snapshots(self):
        from evo_core.runtime_invocation_snapshots import list_runtime_invocation_snapshots
        return list_runtime_invocation_snapshots(
            self.store, self.workspace["workspace_id"], limit=100,
        )

    def test_coding_agent_route_records_attempt_snapshot_before_disabled_gate(self):
        before = {row["invocation_id"] for row in self._workspace_snapshots()}
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        created = [row for row in self._workspace_snapshots()
                   if row["invocation_id"] not in before]
        self.assertEqual(len(created), 1)
        from evo_core.runtime_invocation_snapshots import get_runtime_invocation_snapshot
        record = get_runtime_invocation_snapshot(self.store, created[0]["invocation_id"])
        self.assertEqual(record["snapshot"]["invocation_kind"], "coding_agent")
        self.assertFalse(record["snapshot"]["dispatch_enabled"])
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), 0)

    def test_isolated_coding_agent_disabled_gate_does_not_provision_task_workspace(self):
        before = {row["invocation_id"] for row in self._workspace_snapshots()}
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": self.workspace["workspace_id"],
            "isolate_workspace": True,
        })
        self.assertEqual(status, 503)
        created = [row for row in self._workspace_snapshots()
                   if row["invocation_id"] not in before]
        self.assertEqual(len(created), 1)
        from evo_core.runtime_invocation_snapshots import get_runtime_invocation_snapshot
        record = get_runtime_invocation_snapshot(self.store, created[0]["invocation_id"])
        self.assertEqual(record["snapshot"]["workspace_id"], self.workspace["workspace_id"])
        self.assertFalse(record["snapshot"]["dispatch_enabled"])
        with self.store.lock:
            table = self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_workspaces'"
            ).fetchone()
            if table is not None:
                count = self.store.db.execute("SELECT COUNT(*) FROM task_workspaces").fetchone()[0]
                self.assertEqual(count, 0)
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), 0)

    def test_plan_proposal_route_records_typed_attempt_snapshot(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        rows = self._workspace_snapshots()
        self.assertEqual(len(rows), 1)
        from evo_core.runtime_invocation_snapshots import get_runtime_invocation_snapshot
        record = get_runtime_invocation_snapshot(self.store, rows[0]["invocation_id"])
        self.assertEqual(record["snapshot"]["invocation_kind"], "plan_proposal")
        self.assertFalse(record["snapshot"]["dispatch_enabled"])

    def test_plan_execution_route_records_typed_attempt_snapshot_after_validation(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "approved plan",
                self.workspace["workspace_id"],
                str(self.directory.resolve()),
                {
                    "title": "Approved plan",
                    "summary": "Plan used to verify execution snapshot wiring.",
                    "steps": [{
                        "title": "Step",
                        "description": "Do work",
                        "expected_outcome": "Done",
                        "verification": "Check",
                        "verification_commands": [["python", "-c", "print('ok')"]],
                    }],
                },
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        status, body = asgi_request(
            self.app, "POST",
            self._scoped_path(f"/api/v1/agents/plans/{plan['id']}/execute"), {},
        )
        self.assertEqual(status, 503)
        rows = self._workspace_snapshots()
        self.assertEqual(len(rows), 1)
        from evo_core.runtime_invocation_snapshots import get_runtime_invocation_snapshot
        record = get_runtime_invocation_snapshot(self.store, rows[0]["invocation_id"])
        self.assertEqual(record["snapshot"]["invocation_kind"], "plan_execution")
        self.assertFalse(record["snapshot"]["dispatch_enabled"])
        self.assertEqual(get_plan(self.app.state.lab_db.connection, plan["id"])["status"], "approved")
        self.assertEqual(self.store.list_agent_runs(limit=1000), [])

    def test_workspace_chat_route_records_attempt_snapshot(self):
        conversation_id = self.app.state.assistant.new_conversation(
            project_id=self.project["project_id"],
            workspace_id=self.workspace["workspace_id"],
        )
        status, body = asgi_request(self.app, "POST", "/api/v1/chat", {
            "conversation_id": conversation_id,
            "message": "Hello",
            "project_id": self.project["project_id"],
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        rows = self._workspace_snapshots()
        self.assertEqual(len(rows), 1)
        from evo_core.runtime_invocation_snapshots import get_runtime_invocation_snapshot
        record = get_runtime_invocation_snapshot(self.store, rows[0]["invocation_id"])
        self.assertEqual(record["snapshot"]["invocation_kind"], "workspace_chat")
        self.assertFalse(record["snapshot"]["dispatch_enabled"])

    def test_invalid_workspace_chat_conversation_creates_no_snapshot(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/chat", {
            "conversation_id": "not-a-conversation",
            "message": "Hello",
            "project_id": self.project["project_id"],
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 404)
        self.assertEqual(self._workspace_snapshots(), [])


    def test_coding_worker_fails_closed_if_workspace_is_rebound_after_api_admission(self):
        from concurrent.futures import Future
        from evo_core.workspace_binding_history import rebind_workspace

        submitted = []
        future = Future()

        def capture_submit(fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return future

        definition = json.loads(json.dumps(VALID_DEFINITION))
        definition["components"]["primary_model"]["settings"]["model"] = "rebound-model"
        rebound = create_configuration(self.store, definition, name="rebound-cfg")

        with patch(
            "evo_core.runtime_binding.RegistryBoundRuntime.require_dispatch_enabled",
            return_value=None,
        ), patch.object(self.app.state.chat_executor, "submit", side_effect=capture_submit):
            status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
                "request": "inspect",
                "workspace_id": self.workspace["workspace_id"],
            })
            self.assertEqual(status, 202)
            self.assertEqual(len(submitted), 1)

            rebind_workspace(
                self.store,
                self.workspace["workspace_id"],
                configuration_id=rebound["configuration"]["configuration_id"],
                configuration_revision_id=rebound["revision"]["revision_id"],
                checkout_id=self.checkout["checkout_id"],
                expected_version=self.workspace["version"],
                actor="test",
                reason="Verify worker rejects a changed runtime binding",
            )

            worker, args, kwargs = submitted[0]
            worker(*args, **kwargs)

        run = self.store.get_agent_run(body["run_id"])
        self.assertEqual(run["status"], "failed")
        self.assertIn("does not match", run["summary"])
        future.set_result(None)


    def test_agent_can_opt_into_task_isolated_workspace(self):
        import subprocess
        from evo_core.task_workspaces import get_task_workspace_for_task

        def git(*args):
            result = subprocess.run(
                ["git", "-C", str(self.directory), *args],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.rstrip("\n")

        git("init", "--initial-branch=main")
        git("config", "user.name", "Evo Test")
        git("config", "user.email", "evo-test@example.invalid")
        (self.directory / "tracked.txt").write_text("source\n", encoding="utf-8")
        git("add", "tracked.txt")
        git("commit", "-m", "source revision")
        source_revision = git("rev-parse", "HEAD")

        submitted = []

        def capture_submit(fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            from concurrent.futures import Future
            return Future()

        with patch(
            "evo_core.runtime_binding.RegistryBoundRuntime.require_dispatch_enabled",
            return_value=None,
        ), patch.object(self.app.state.chat_executor, "submit", side_effect=capture_submit):
            status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
                "request": "inspect the isolated checkout",
                "workspace_id": self.workspace["workspace_id"],
                "isolate_workspace": True,
            })

        self.assertEqual(status, 202)
        self.assertEqual(len(submitted), 1)
        task_workspace_id = submitted[0][1][2]
        run = self.store.get_agent_run(body["run_id"])
        metadata = json.loads(run["metadata_json"])
        self.assertEqual(metadata["workspace_id"], task_workspace_id)
        self.assertEqual(body["workspace_id"], task_workspace_id)
        self.assertEqual(body["task_workspace_operation_id"], metadata["task_workspace_operation_id"])
        self.assertEqual(body["source_revision"], source_revision)
        self.assertEqual(metadata["parent_workspace_id"], self.workspace["workspace_id"])
        self.assertEqual(metadata["task_workspace_source_revision"], source_revision)
        operation = get_task_workspace_for_task(
            self.store, self.project["project_id"], metadata["task_id"],
        )
        self.assertIsNotNone(operation)
        self.assertEqual(operation["operation_id"], metadata["task_workspace_operation_id"])
        self.assertEqual(operation["status"], "completed")
        task_binding = resolve_executable_workspace(self.store, task_workspace_id)
        self.assertEqual(str(task_binding["canonical_path"]), metadata["workspace"])
        self.assertEqual(git("rev-parse", "HEAD"), source_revision)
        self.assertEqual(git("status", "--porcelain"), "")


    def test_isolated_agent_rejects_dirty_parent_before_dispatch(self):
        import subprocess

        def git(*args):
            result = subprocess.run(
                ["git", "-C", str(self.directory), *args],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.rstrip("\n")

        git("init", "--initial-branch=main")
        git("config", "user.name", "Evo Test")
        git("config", "user.email", "evo-test@example.invalid")
        (self.directory / "tracked.txt").write_text("source\n", encoding="utf-8")
        git("add", "tracked.txt")
        git("commit", "-m", "source revision")
        (self.directory / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")

        submitted = []
        with patch(
            "evo_core.runtime_binding.RegistryBoundRuntime.require_dispatch_enabled",
            return_value=None,
        ), patch.object(self.app.state.chat_executor, "submit", side_effect=lambda *a, **k: submitted.append((a, k))):
            status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
                "request": "must not run",
                "workspace_id": self.workspace["workspace_id"],
                "isolate_workspace": True,
            })

        self.assertEqual(status, 409)
        self.assertIn("dirty", body["detail"])
        self.assertEqual(submitted, [])
        self.assertEqual(git("status", "--porcelain").count(" M tracked.txt"), 1)
