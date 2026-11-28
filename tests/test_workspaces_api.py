import asyncio
import json as _json
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.api import create_app
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace

VALID_DEFINITION = {"schema_version": 1, "components": {}}


def make_config(root):
    config = root / "config.toml"
    config.write_text(
        '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
        f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
        f'[workspace]\nroot="{root}"\nallowed_commands=[]\n',
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
        data = _json.loads(raw)
    except Exception:
        data = raw
    return status, data


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.store = self.app.state.store

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _make_fixtures(self):
        project = register_project(self.store, "Project")
        directory = self.root / "checkout"
        directory.mkdir()
        checkout = register_checkout(self.store, project["project_id"], directory)
        config_result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        configuration = config_result["configuration"]
        revision = config_result["revision"]
        return project, checkout, directory, configuration, revision

    def test_create_without_checkout(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "Workspace",
            "project_id": project["project_id"],
            "configuration_id": configuration["configuration_id"],
            "configuration_revision_id": revision["revision_id"],
        })
        self.assertEqual(status, 201)
        self.assertIsNone(body["checkout_id"])
        self.assertEqual(body["configuration_revision_id"], revision["revision_id"])

    def test_create_with_checkout(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "Workspace",
            "project_id": project["project_id"],
            "configuration_id": configuration["configuration_id"],
            "configuration_revision_id": revision["revision_id"],
            "checkout_id": checkout["checkout_id"],
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["checkout_id"], checkout["checkout_id"])

    def test_get_and_list_filters(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "Workspace",
            "project_id": project["project_id"],
            "configuration_id": configuration["configuration_id"],
            "configuration_revision_id": revision["revision_id"],
            "checkout_id": checkout["checkout_id"],
        })
        self.assertEqual(status, 201)
        wid = ws["workspace_id"]
        status, body = asgi_request(self.app, "GET", f"/api/v1/workspaces/{wid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["workspace_id"], wid)
        status, body = asgi_request(self.app, "GET", "/api/v1/workspaces")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)
        status, body = asgi_request(self.app, "GET", f"/api/v1/workspaces?project_id={project['project_id']}")
        self.assertEqual(body["total"], 1)
        status, body = asgi_request(self.app, "GET", f"/api/v1/workspaces?configuration_id={configuration['configuration_id']}")
        self.assertEqual(body["total"], 1)
        status, body = asgi_request(self.app, "GET", "/api/v1/workspaces?status=active")
        self.assertEqual(body["total"], 1)
        status, body = asgi_request(self.app, "GET", f"/api/v1/workspaces?project_id={project['project_id']}&configuration_id={configuration['configuration_id']}&status=active")
        self.assertEqual(body["total"], 1)

    def test_archive_reactivate(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "Workspace",
            "project_id": project["project_id"],
            "configuration_id": configuration["configuration_id"],
            "configuration_revision_id": revision["revision_id"],
            "checkout_id": checkout["checkout_id"],
        })
        wid = ws["workspace_id"]
        version = ws["version"]
        original_revision = ws["configuration_revision_id"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/archive", {"expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "archived")
        self.assertEqual(body["configuration_revision_id"], original_revision)
        status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/reactivate", {"expected_version": body["version"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["configuration_revision_id"], original_revision)

    def test_stale_version(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "Workspace",
            "project_id": project["project_id"],
            "configuration_id": configuration["configuration_id"],
            "configuration_revision_id": revision["revision_id"],
        })
        wid = ws["workspace_id"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/archive", {"expected_version": 999})
        self.assertEqual(status, 409)

    def test_missing_workspace(self):
        status, body = asgi_request(self.app, "GET", "/api/v1/workspaces/missing")
        self.assertEqual(status, 404)
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces/missing/archive", {"expected_version": 1})
        self.assertEqual(status, 404)

    def test_invalid_bodies(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {"name": "   ", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {"name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "foo": 1})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {"name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "description": None})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "GET", "/api/v1/workspaces?status=bogus")
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/does-not-matter/archive", {"expected_version": "bad"})
        self.assertEqual(status, 422)

    def test_invalid_relationships(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        other_project, other_checkout, _ = make_project(self.store, self.root)
        other_config, other_revision = make_configuration(self.store)
        other_config, other_revision = make_configuration(self.store)

        # nonexistent project
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": "missing", "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]
        })
        self.assertEqual(status, 422)
        # archived project
        from evo_core.project_checkouts import archive_project

        archive_project(self.store, project["project_id"], expected_version=project["version"])
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]
        })
        self.assertEqual(status, 422)
        # reactivate project for later
        from evo_core.project_checkouts import reactivate_project

        reactivate_project(self.store, project["project_id"], expected_version=project["version"] + 1)

        # nonexistent config
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": "missing", "configuration_revision_id": revision["revision_id"]
        })
        self.assertEqual(status, 422)
        # archived config
        from evo_core.ai_configurations import archive_configuration

        archive_configuration(self.store, configuration["configuration_id"], expected_version=configuration["version"])
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]
        })
        self.assertEqual(status, 422)
        from evo_core.ai_configurations import reactivate_configuration

        reactivate_configuration(self.store, configuration["configuration_id"], expected_version=configuration["version"] + 1)

        # nonexistent revision
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": "missing"
        })
        self.assertEqual(status, 422)
        # revision from other config
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": other_revision["revision_id"]
        })
        self.assertEqual(status, 422)

        # checkout wrong project
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": other_checkout["checkout_id"]
        })
        self.assertEqual(status, 422)

        # checkout missing/unavailable
        directory.rmdir() if False else None
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
        directory.write_text("not dir")
        from evo_core.project_checkouts import refresh_checkout_availability

        refresh_checkout_availability(self.store, checkout["checkout_id"])
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": checkout["checkout_id"]
        })
        self.assertEqual(status, 422)
        # restore
        directory.unlink()
        directory.mkdir()
        (directory / "file.txt").write_text("data", encoding="utf-8")
        refresh_checkout_availability(self.store, checkout["checkout_id"])

    def test_shared_checkout(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws1", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": checkout["checkout_id"]
        })
        self.assertEqual(status, 201)
        status, body = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws2", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": checkout["checkout_id"]
        })
        self.assertEqual(status, 201)

    def test_reactivation_dependency_failures(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": checkout["checkout_id"]
        })
        wid = ws["workspace_id"]
        version = ws["version"]
        asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/archive", {"expected_version": version})
        # archive project
        from evo_core.project_checkouts import archive_project

        archive_project(self.store, project["project_id"], expected_version=project["version"])
        status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/reactivate", {"expected_version": version + 1})
        self.assertEqual(status, 422)
        # restore project
        from evo_core.project_checkouts import reactivate_project

        reactivate_project(self.store, project["project_id"], expected_version=project["version"] + 1)

    def test_pinned_revision_unchanged(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]
        })
        wid = ws["workspace_id"]
        original = ws["configuration_revision_id"]
        version = ws["version"]
        asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/archive", {"expected_version": version})
        asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/reactivate", {"expected_version": version + 1})
        status, body = asgi_request(self.app, "GET", f"/api/v1/workspaces/{wid}")
        self.assertEqual(body["configuration_revision_id"], original)

    def test_failed_creation_no_partial_row(self):
        before_status, before_body = asgi_request(self.app, "GET", "/api/v1/workspaces")
        before = before_body["total"]
        asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "bad", "project_id": "missing", "configuration_id": "x", "configuration_revision_id": "y"
        })
        status, body = asgi_request(self.app, "GET", "/api/v1/workspaces")
        self.assertEqual(body["total"], before)

    def test_checkout_filesystem_unchanged(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        before = sorted(p.name for p in directory.iterdir())
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"], "checkout_id": checkout["checkout_id"]
        })
        self.assertEqual(status, 201)
        after = sorted(p.name for p in directory.iterdir())
        self.assertEqual(before, after)

    def test_invalid_expected_version(self):
        project, checkout, directory, configuration, revision = self._make_fixtures()
        status, ws = asgi_request(self.app, "POST", "/api/v1/workspaces", {
            "name": "ws", "project_id": project["project_id"], "configuration_id": configuration["configuration_id"], "configuration_revision_id": revision["revision_id"]
        })
        wid = ws["workspace_id"]
        for value in [True, 1.0, "1", 0, -1]:
            status, body = asgi_request(self.app, "POST", f"/api/v1/workspaces/{wid}/archive", {"expected_version": value})
            self.assertEqual(status, 422)

    def test_task_workspace_review_api_returns_isolated_bounded_artifact(self):
        import subprocess
        from evo_core.task_workspaces import create_task_workspace

        project, checkout, directory, configuration, revision = self._make_fixtures()
        subprocess.run(["git", "-C", str(directory), "init", "--initial-branch=main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(directory), "config", "user.name", "Evo Test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(directory), "config", "user.email", "evo-test@example.invalid"], check=True, capture_output=True)
        (directory / "README.md").write_text("baseline\\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(directory), "add", "README.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(directory), "commit", "-m", "baseline"], check=True, capture_output=True)
        workspace = create_workspace(
            self.store, "Parent workspace", project["project_id"],
            configuration["configuration_id"], revision["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        task = create_task_workspace(
            self.store, workspace["workspace_id"], "api-review-task", self.root,
        )
        task_path = Path(task["canonical_path"])
        (task_path / "result.txt").write_text("isolated result\\n", encoding="utf-8")

        status, body = asgi_request(
            self.app, "GET",
            f"/api/v1/task-workspaces/{task['operation_id']}/review",
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["operation_id"], task["operation_id"])
        self.assertTrue(body["stable"])
        self.assertEqual(body["changed_file_count"], 1)
        self.assertEqual(body["changed_files"], [{"status": "A", "path": "result.txt"}])
        self.assertIn("+isolated result", body["patch"])
        self.assertFalse((directory / "result.txt").exists())
        source_status = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain"],
            check=True, capture_output=True, text=True,
        ).stdout
        self.assertEqual(source_status, "")

    def test_task_workspace_review_api_error_mapping_is_safe(self):
        from unittest.mock import patch
        from evo_core.task_workspaces import TaskWorkspaceProvisioningError

        status, body = asgi_request(
            self.app, "GET", "/api/v1/task-workspaces/missing/review"
        )
        self.assertEqual(status, 404)

        with patch(
            "evo_core.api.get_task_workspace_review",
            side_effect=TaskWorkspaceProvisioningError(
                "private git stderr and /home/user/private/path"
            ),
        ):
            status, body = asgi_request(
                self.app, "GET", "/api/v1/task-workspaces/failure/review"
            )
        self.assertEqual(status, 503)
        self.assertNotIn("private", str(body))
        self.assertNotIn("/home/user", str(body))

        with patch(
            "evo_core.api.get_task_workspace_review",
            side_effect=RuntimeError("secret internal path /private/data"),
        ):
            status, body = asgi_request(
                self.app, "GET", "/api/v1/task-workspaces/unexpected/review"
            )
        self.assertEqual(status, 500)
        self.assertNotIn("secret", str(body))
        self.assertNotIn("/private/data", str(body))


def make_configuration(store):
    from evo_core.ai_configurations import create_configuration

    result = create_configuration(store, {"schema_version": 1, "components": {}}, name="cfg")
    return result["configuration"], result["revision"]


def make_project(store, temp_root):
    from evo_core.project_checkouts import register_project, register_checkout

    project = register_project(store, "Project")
    directory = temp_root / f"checkout-{project['project_id']}"
    directory.mkdir()
    checkout = register_checkout(store, project["project_id"], directory)
    return project, checkout, directory


if __name__ == "__main__":
    unittest.main()
