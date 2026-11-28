import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.api import create_app
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.task_workspaces import create_task_workspace
from evo_core.workspaces import create_workspace


DEFINITION = {"schema_version": 1, "components": {}}


def request(app, path):
    path_part, _, query = path.partition("?")
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path_part,
        "raw_path": path_part.encode(), "query_string": query.encode(),
        "root_path": "", "headers": [], "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765), "state": {},
    }
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    asyncio.run(app(scope, receive, send))
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return messages[0]["status"], json.loads(body)


class TaskWorkspaceFilesApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "config.toml"
        config_path.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{self.root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{self.root}"\nallowed_commands=[]\n',
            encoding="utf-8",
        )
        self.app = create_app(config_path)
        store = self.app.state.store
        project = register_project(store, "API files")
        self.source = self.root / "source"
        self.source.mkdir()
        self._git(self.source, "init", "--initial-branch=main")
        self._git(self.source, "config", "user.name", "Test")
        self._git(self.source, "config", "user.email", "test@example.invalid")
        (self.source / "readme.txt").write_text("API inspection works\n")
        self._git(self.source, "add", "readme.txt")
        self._git(self.source, "commit", "-m", "initial")
        revision = self._git(self.source, "rev-parse", "HEAD")
        checkout = register_checkout(store, project["project_id"], self.source,
                                      branch_or_ref="main", last_known_commit=revision)
        cfg = create_configuration(store, DEFINITION, name="api")
        parent = create_workspace(store, "Parent", project["project_id"],
                                  cfg["configuration"]["configuration_id"],
                                  cfg["revision"]["revision_id"], checkout_id=checkout["checkout_id"])
        destination = self.root / "task-worktrees"
        destination.mkdir()
        self.operation = create_task_workspace(store, parent["workspace_id"], "api-task", destination)
        self.task_root = Path(self.operation["canonical_path"])

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    @staticmethod
    def _git(path, *args):
        result = subprocess.run(["git", "-C", str(path), *args],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def test_file_listing_and_read_routes(self):
        (self.task_root / "note.txt").write_text("API text")
        operation_id = self.operation["operation_id"]
        status, listing = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/files")
        self.assertEqual(status, 200)
        self.assertIn("note.txt", {item["name"] for item in listing["items"]})
        status, result = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/file?path=note.txt")
        self.assertEqual(status, 200)
        self.assertEqual(result["content"], "API text")
        self.assertEqual(result["source_revision"], self.operation["source_revision"])

    def test_invalid_file_paths_are_rejected(self):
        status, body = request(
            self.app,
            "/api/v1/task-workspaces/" + self.operation["operation_id"] + "/file?path=..%2Foutside",
        )
        self.assertEqual(status, 404)
        self.assertIn("detail", body)


if __name__ == "__main__":
    unittest.main()
