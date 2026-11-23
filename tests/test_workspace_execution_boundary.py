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

VALID_DEFINITION = {"schema_version": 1, "components": {}}


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
                        "verification_commands": [],
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

    def test_valid_workspace_starts_run(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "inspect",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 202)
        run = self.store.get_agent_run(body["run_id"])
        metadata = json.loads(run["metadata_json"])
        self.assertEqual(metadata.get("workspace_id"), self.workspace["workspace_id"])

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

    def test_plan_persists_workspace_id(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["workspace_id"], self.workspace["workspace_id"])

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
                        "verification_commands": [],
                    }
                ],
            }
            status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
                "request": "plan",
                "workspace_id": self.workspace["workspace_id"],
            })
            self.assertEqual(status, 201)
            self.assertEqual(mocked.call_args.args[2], str(self.directory.resolve()))

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

    def test_plan_execution_uses_workspace_id(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 201)
        plan_id = body["id"]
        with self.app.state.lab_db.lock:
            approve_plan(self.app.state.lab_db.connection, plan_id)
        status, body = asgi_request(self.app, "POST", self._scoped_path(f"/api/v1/agents/plans/{plan_id}/execute"), {})
        self.assertEqual(status, 202)
        run = self.store.get_agent_run(body["run_id"])
        metadata = json.loads(run["metadata_json"])
        self.assertEqual(metadata.get("workspace_id"), self.workspace["workspace_id"])

    def test_plan_workspace_invalidated_after_approval(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        plan_id = body["id"]
        with self.app.state.lab_db.lock:
            approve_plan(self.app.state.lab_db.connection, plan_id)
        from evo_core.workspaces import archive_workspace

        archive_workspace(self.store, self.workspace["workspace_id"], expected_version=self.workspace["version"])
        status, body = asgi_request(self.app, "POST", self._scoped_path(f"/api/v1/agents/plans/{plan_id}/execute"), {})
        self.assertEqual(status, 409)

    def test_worker_revalidation_failure_finalizes_run(self):
        calls = {"count": 0}
        original = __import__("evo_core.workspaces", fromlist=["resolve_executable_workspace"]).resolve_executable_workspace

        def flaky(store, workspace_id):
            calls["count"] += 1
            if calls["count"] == 1:
                return original(store, workspace_id)
            raise __import__("evo_core.workspaces", fromlist=["WorkspaceRelationshipError"]).WorkspaceRelationshipError("invalidated")

        with patch("evo_core.api.workspace_registry.resolve_executable_workspace", side_effect=flaky):
            status, body = asgi_request(self.app, "POST", "/api/v1/agents", {
                "request": "inspect",
                "workspace_id": self.workspace["workspace_id"],
            })
            self.assertEqual(status, 202)
            run_id = body["run_id"]
            run_status, run_body = self._run_status(run_id)
            self.assertEqual(run_status, 200)
            self.assertEqual(run_body["status"], "failed")

    def test_plan_cannot_execute_twice(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
            "request": "plan",
            "workspace_id": self.workspace["workspace_id"],
        })
        plan_id = body["id"]
        with self.app.state.lab_db.lock:
            approve_plan(self.app.state.lab_db.connection, plan_id)
        status, body = asgi_request(self.app, "POST", self._scoped_path(f"/api/v1/agents/plans/{plan_id}/execute"), {})
        self.assertEqual(status, 202)
        status, body = asgi_request(self.app, "POST", self._scoped_path(f"/api/v1/agents/plans/{plan_id}/execute"), {})
        self.assertEqual(status, 409)

    def test_plan_worker_revalidation_finalizes_plan(self):
        calls = {"count": 0}
        original = __import__("evo_core.workspaces", fromlist=["resolve_executable_workspace"]).resolve_executable_workspace

        def flaky(store, workspace_id):
            calls["count"] += 1
            if calls["count"] < 3:
                return original(store, workspace_id)
            raise __import__("evo_core.workspaces", fromlist=["WorkspaceRelationshipError"]).WorkspaceRelationshipError("invalidated")

        with patch("evo_core.api.workspace_registry.resolve_executable_workspace", side_effect=flaky):
            status, body = asgi_request(self.app, "POST", "/api/v1/agents/plans", {
                "request": "plan",
                "workspace_id": self.workspace["workspace_id"],
            })
            self.assertEqual(status, 201)
            plan_id = body["id"]
            with self.app.state.lab_db.lock:
                approve_plan(self.app.state.lab_db.connection, plan_id)
            status, body = asgi_request(self.app, "POST", self._scoped_path(f"/api/v1/agents/plans/{plan_id}/execute"), {})
            self.assertEqual(status, 202)
            run_id = body["run_id"]
            self._run_status(run_id)
            with self.app.state.lab_db.lock:
                plan = get_plan(self.app.state.lab_db.connection, plan_id)
            self.assertEqual(plan["status"], "failed")
