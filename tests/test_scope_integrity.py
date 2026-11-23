import asyncio
import json as _json
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.api import create_app
from evo_core.orchestration import approve_plan, create_plan, get_plan
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace


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
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path_part, "raw_path": path_part.encode(),
        "query_string": query_part.encode(), "root_path": "", "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "state": {},
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


class AgentPlanScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop"
        }
        self.store = self.app.state.store
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        config_result = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        self.configuration = config_result["configuration"]
        self.revision = config_result["revision"]
        self.workspace = create_workspace(
            self.store, "Workspace", self.project["project_id"],
            self.configuration["configuration_id"], self.revision["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_matching_scope_executes(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "request",
                self.workspace["workspace_id"],
                str(self.directory),
                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                project_id=self.project["project_id"],
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        status, body = asgi_request(self.app, "POST", f"/api/v1/agents/plans/{plan['id']}/execute?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}", {})
        self.assertEqual(status, 202)
        run = self.store.get_agent_run(body["run_id"])
        metadata = _json.loads(run["metadata_json"])
        self.assertEqual(metadata.get("project_id"), self.project["project_id"])
        self.assertEqual(metadata.get("workspace_id"), self.workspace["workspace_id"])

    def test_mismatched_scope_is_rejected(self):
        other_project = register_project(self.store, "Other")
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "request",
                self.workspace["workspace_id"],
                str(self.directory),
                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                project_id=other_project["project_id"],
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(self.app, "POST", f"/api/v1/agents/plans/{plan['id']}/execute?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}", {})
        # The plan is owned by another project and is therefore invisible in
        # this scope. Visibility is checked before execution-binding mismatch.
        self.assertEqual(status, 404)
        after = len(self.store.list_agent_runs(limit=1000))
        self.assertEqual(before, after)
        with self.app.state.lab_db.lock:
            unchanged = get_plan(self.app.state.lab_db.connection, plan["id"])
        self.assertEqual(unchanged["project_id"], other_project["project_id"])
        self.assertEqual(unchanged["status"], "approved")
