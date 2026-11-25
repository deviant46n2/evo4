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
        config_result = create_configuration(
            self.store,
            {
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
            },
            name="cfg",
        )
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

    def test_matching_scope_is_validated_before_disabled_dispatch(self):
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "request",
                self.workspace["workspace_id"],
                str(self.directory),
                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d", "verification_commands": [["python", "-c", "print('ok')"]]}]},
                project_id=self.project["project_id"],
                store=self.store,
            )
            approve_plan(self.app.state.lab_db.connection, plan["id"])
        before = len(self.store.list_agent_runs(limit=1000))
        status, body = asgi_request(self.app, "POST", f"/api/v1/agents/plans/{plan['id']}/execute?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}", {})
        self.assertEqual(status, 503)
        self.assertIn("P3.5", body["detail"])
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), before)
        self.assertEqual(get_plan(self.app.state.lab_db.connection, plan["id"])["status"], "approved")

    def test_list_plans_filters_before_limit(self):
        from evo_core.orchestration import create_plan, list_plans
        for _ in range(105):
            with self.app.state.lab_db.lock:
                create_plan(
                    self.app.state.lab_db.connection, "global request", None, str(self.directory),
                    {"title": "Global plan", "summary": "Global summary", "steps": [
                        {"title": "Step", "description": "Do work", "expected_outcome": "Done", "verification": "Check"}]},
                )
        with self.app.state.lab_db.lock:
            scoped = create_plan(
                self.app.state.lab_db.connection, "scoped request", self.workspace["workspace_id"], str(self.directory),
                {"title": "Scoped plan", "summary": "Scoped summary", "steps": [
                    {"title": "Step", "description": "Do work", "expected_outcome": "Done", "verification": "Check"}]},
                project_id=self.project["project_id"], store=self.store)
        scoped_rows = list_plans(
            self.app.state.lab_db.connection, limit=1,
            project_id=self.project["project_id"], workspace_id=self.workspace["workspace_id"],
            store=self.store)
        self.assertEqual([row["id"] for row in scoped_rows], [scoped["id"]])

    def test_mismatched_scope_is_rejected(self):
        other_project = register_project(self.store, "Other")
        other_directory = self.root / "other-checkout"
        other_directory.mkdir()
        other_checkout = register_checkout(self.store, other_project["project_id"], other_directory)
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        other_config = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="other-cfg")
        other_workspace = create_workspace(
            self.store, "OtherWorkspace", other_project["project_id"],
            other_config["configuration"]["configuration_id"], other_config["revision"]["revision_id"],
            checkout_id=other_checkout["checkout_id"])
        with self.app.state.lab_db.lock:
            plan = create_plan(
                self.app.state.lab_db.connection,
                "request",
                other_workspace["workspace_id"],
                str(other_directory),
                {"title": "t", "summary": "s", "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                project_id=other_project["project_id"],
                store=self.store,
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
