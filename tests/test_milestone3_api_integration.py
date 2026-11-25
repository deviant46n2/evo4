import asyncio
import json as _json
import tempfile
import unittest
from pathlib import Path

from evo_core.api import create_app
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_project, register_checkout
from evo_core.ai_configurations import create_configuration
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



def schema2_workspace_definition():
    return {
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


class ConversationApiScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        class _P:
            def chat(self, messages, max_tokens=0, temperature=0, on_token=None, tools=None):
                if on_token:
                    on_token("stub reply")
                return {"content": "stub reply", "elapsed_seconds": 0.01, "ttft_seconds": 0.001,
                        "prompt_tokens": 10, "completion_tokens": 2, "finish_reason": "stop"}
        self.app.state.assistant.provider = _P()
        self.store = self.app.state.store
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])
        self.other = register_project(self.store, "Other")

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_project_conversation_creation_listing_history(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "proj", "project_id": self.project["project_id"],
                                     "workspace_id": self.workspace["workspace_id"]})
        self.assertEqual(status, 201)
        cid = body["id"]
        # listing with scope sees it
        status, rows = asgi_request(self.app, "GET", f"/api/v1/conversations?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)
        self.assertIn(cid, [r["id"] for r in rows])
        # history accessible with scope
        status, msgs = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)

    def test_cross_project_chat_and_history_rejected(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "proj", "project_id": self.project["project_id"]})
        cid = body["id"]
        # cross-project history rejected
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.other['project_id']}")
        self.assertEqual(status, 404)
        # cross-project chat rejected
        status, data = asgi_request(self.app, "POST", "/api/v1/chat",
                                    {"message": "hello", "conversation_id": cid, "project_id": self.other["project_id"]})
        self.assertEqual(status, 404)

    def test_workspace_conversation_access_without_workspace_rejected(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "ws", "project_id": self.project["project_id"],
                                     "workspace_id": self.workspace["workspace_id"]})
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.project['project_id']}")
        self.assertEqual(status, 404)

    def test_cross_workspace_conversation_access_rejected(self):
        other_dir = self.root / "other-checkout"
        other_dir.mkdir()
        other_checkout = register_checkout(self.store, self.project["project_id"], other_dir)
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg2")
        other_workspace = create_workspace(self.store, "OtherWS", self.project["project_id"],
                                          cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                          checkout_id=other_checkout["checkout_id"])
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "ws", "project_id": self.project["project_id"],
                                     "workspace_id": self.workspace["workspace_id"]})
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.project['project_id']}&workspace_id={other_workspace['workspace_id']}")
        self.assertEqual(status, 404)

    def test_global_conversation_behavior_unchanged(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations", {"title": "global"})
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages")
        self.assertEqual(status, 200)
        # global conversation is not visible with project scope
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.project['project_id']}")
        self.assertEqual(status, 404)

    def test_project_chat_matching_scope(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "proj", "project_id": self.project["project_id"]})
        cid = body["id"]
        result = self.app.state.assistant.turn(cid, "hello", project_id=self.project["project_id"])
        self.assertIn("content", result)

    def test_conversation_ownership_not_mutated(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "proj", "project_id": self.project["project_id"]})
        cid = body["id"]
        row = self.store.db.execute("SELECT project_id FROM conversations WHERE id=?", (cid,)).fetchone()
        self.assertEqual(row["project_id"], self.project["project_id"])
        # request with no scope does not mutate
        asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages")
        row2 = self.store.db.execute("SELECT project_id FROM conversations WHERE id=?", (cid,)).fetchone()
        self.assertEqual(row2["project_id"], self.project["project_id"])


if __name__ == "__main__":
    unittest.main()


class RunMetadataValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop",
            "elapsed_seconds": 0.01, "ttft_seconds": 0.001,
            "prompt_tokens": 10, "completion_tokens": 2,
        }
        self.store = self.app.state.store
        from evo_core.platform_registry import initialize_platform_registry
        from evo_core.project_checkouts import register_project, register_checkout
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, schema2_workspace_definition(), name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])
        import json
        self._json = json

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _run(self, metadata):
        run_id = self.store.start_agent_run("coding", metadata)
        from evo_core import background_agent
        background_agent.create(self.app.state.lab_db.connection, run_id)
        created = {"called": False}
        orig_new = self.app.state.assistant.new_conversation
        def fake_new(*a, **k):
            created["called"] = True
            return orig_new(*a, **k)
        self.app.state.assistant.new_conversation = fake_new
        import threading
        self.app.state.run_agent(run_id, "request", self.workspace["workspace_id"], threading.Event())
        self.app.state.assistant.new_conversation = orig_new
        return run_id, created

    def test_metadata_project_mismatch_rejects(self):
        metadata = {"workspace_id": self.workspace["workspace_id"], "project_id": "wrong-project", "request": "r"}
        run_id, created = self._run(metadata)
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])
        md = self._json.loads(run["metadata_json"])
        self.assertNotIn("conversation_id", md)

    def test_metadata_workspace_mismatch_rejects(self):
        metadata = {"workspace_id": "wrong-workspace", "project_id": self.project["project_id"], "request": "r"}
        run_id, created = self._run(metadata)
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])

    def test_missing_metadata_scope_rejects(self):
        metadata = {"request": "r"}
        run_id, created = self._run(metadata)
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])

    def test_valid_metadata_reaches_disabled_dispatch_gate(self):
        metadata = {"workspace_id": self.workspace["workspace_id"], "project_id": self.project["project_id"], "request": "r"}
        run_id, created = self._run(metadata)
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])
        self.assertIn("dispatchable", run["summary"] or "")

    def test_valid_approved_plan_metadata_reaches_disabled_dispatch_gate(self):
        from evo_core.orchestration import initialize, create_plan, approve_plan
        initialize(self.app.state.lab_db.connection)
        plan = create_plan(self.app.state.lab_db.connection, "request", self.workspace["workspace_id"],
                           str(self.directory), {"title": "t", "summary": "s",
                           "steps": [{"title": "a", "description": "b", "expected_outcome": "c", "verification": "d"}]},
                           project_id=self.project["project_id"], store=self.store)
        approve_plan(self.app.state.lab_db.connection, plan["id"])
        metadata = {"workspace_id": self.workspace["workspace_id"], "project_id": self.project["project_id"], "request": "r"}
        run_id = self.store.start_agent_run("orchestrated", metadata)
        from evo_core import background_agent
        background_agent.create(self.app.state.lab_db.connection, run_id)
        from evo_core.orchestration import attach_run
        attach_run(self.app.state.lab_db.connection, plan["id"], run_id)
        created = {"called": False}
        orig_new = self.app.state.assistant.new_conversation
        def fake_new(*a, **k):
            created["called"] = True
            return orig_new(*a, **k)
        self.app.state.assistant.new_conversation = fake_new
        import threading
        self.app.state.run_agent(run_id, "request", self.workspace["workspace_id"], threading.Event(), plan["id"])
        self.app.state.assistant.new_conversation = orig_new
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])
        self.assertIn("dispatchable", run["summary"] or "")


class ConversationScopeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop",
            "elapsed_seconds": 0.01, "ttft_seconds": 0.001,
            "prompt_tokens": 10, "completion_tokens": 2,
        }
        self.store = self.app.state.store
        from evo_core.platform_registry import initialize_platform_registry
        from evo_core.project_checkouts import register_project, register_checkout
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])
        self.other = register_project(self.store, "Other")
        other_dir = self.root / "other-checkout"
        other_dir.mkdir()
        other_checkout = register_checkout(self.store, self.other["project_id"], other_dir)
        other_cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg2")
        self.other_workspace = create_workspace(self.store, "OtherWS", self.other["project_id"],
                                               other_cfg["configuration"]["configuration_id"], other_cfg["revision"]["revision_id"],
                                               checkout_id=other_checkout["checkout_id"])

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_listing_invalid_project_422(self):
        status, data = asgi_request(self.app, "GET", "/api/v1/conversations?project_id=missing-project")
        self.assertEqual(status, 422)

    def test_listing_unknown_workspace_422(self):
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations?project_id={self.project['project_id']}&workspace_id=missing-workspace")
        self.assertEqual(status, 422)

    def test_listing_workspace_project_mismatch_422(self):
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations?project_id={self.project['project_id']}&workspace_id={self.other_workspace['workspace_id']}")
        self.assertEqual(status, 422)

    def test_listing_workspace_without_project_422(self):
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations?workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 422)

    def test_creation_invalid_scope_422(self):
        status, data = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "x", "project_id": "missing-project"})
        self.assertEqual(status, 422)

    def test_history_invalid_scope_422(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations", {"title": "g"})
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id=missing-project")
        self.assertEqual(status, 422)

    def test_rename_invalid_scope_422(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations", {"title": "g"})
        cid = body["id"]
        status, data = asgi_request(self.app, "PATCH", f"/api/v1/conversations/{cid}?project_id=missing-project",
                                    {"title": "new"})
        self.assertEqual(status, 422)

    def test_delete_invalid_scope_422(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations", {"title": "g"})
        cid = body["id"]
        status, data = asgi_request(self.app, "DELETE", f"/api/v1/conversations/{cid}?project_id=missing-project")
        self.assertEqual(status, 422)

    def test_valid_scoped_operations(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "ws", "project_id": self.project["project_id"],
                                     "workspace_id": self.workspace["workspace_id"]})
        self.assertEqual(status, 201)
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)
        status, data = asgi_request(self.app, "PATCH", f"/api/v1/conversations/{cid}?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}",
                                    {"title": "renamed"})
        self.assertEqual(status, 200)

    def test_global_backward_compat(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations", {"title": "global"})
        self.assertEqual(status, 201)
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages")
        self.assertEqual(status, 200)
        status, data = asgi_request(self.app, "GET", "/api/v1/conversations")
        self.assertEqual(status, 200)

    def test_cross_project_workspace_access_rejected(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/conversations",
                                    {"title": "proj", "project_id": self.project["project_id"]})
        cid = body["id"]
        status, data = asgi_request(self.app, "GET", f"/api/v1/conversations/{cid}/messages?project_id={self.other['project_id']}")
        self.assertEqual(status, 404)


class BackgroundRunMalformedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.app.state.assistant.provider.chat = lambda messages, **kwargs: {
            "content": "done", "tool_calls": [], "finish_reason": "stop",
            "elapsed_seconds": 0.01, "ttft_seconds": 0.001,
            "prompt_tokens": 10, "completion_tokens": 2,
        }
        self.store = self.app.state.store
        from evo_core.platform_registry import initialize_platform_registry
        from evo_core.project_checkouts import register_project, register_checkout
        from evo_core.ai_configurations import create_configuration
        from evo_core.workspaces import create_workspace
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, schema2_workspace_definition(), name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _run_with_metadata(self, metadata_raw):
        run_id = self.store.start_agent_run("coding", {"request": "r"})
        # overwrite metadata_json
        self.store.db.execute("UPDATE agent_runs SET metadata_json=? WHERE id=?", (metadata_raw, run_id))
        self.store.db.commit()
        # set proper workspace/project metadata by updating? For mismatch tests, set metadata
        from evo_core import background_agent
        background_agent.create(self.app.state.lab_db.connection, run_id)
        # update metadata to desired raw
        self.store.db.execute("UPDATE agent_runs SET metadata_json=? WHERE id=?", (metadata_raw, run_id))
        self.store.db.commit()
        created = {"called": False}
        orig_new = self.app.state.assistant.new_conversation
        def fake_new(*a, **k):
            created["called"] = True
            return orig_new(*a, **k)
        self.app.state.assistant.new_conversation = fake_new
        import threading
        # For metadata with scope, inject workspace/project into raw? We'll handle per test.
        self.app.state.run_agent(run_id, "request", self.workspace["workspace_id"], threading.Event())
        self.app.state.assistant.new_conversation = orig_new
        return run_id, created

    def test_invalid_json_rejected(self):
        run_id, created = self._run_with_metadata("{not json")
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])

    def test_non_object_json_rejected(self):
        import json
        run_id, created = self._run_with_metadata(json.dumps(["a", "b"]))
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])
        run_id2, created2 = self._run_with_metadata(json.dumps("scalar"))
        run2 = self.store.get_agent_run(run_id2)
        self.assertEqual(run2["status"], "failed")
        self.assertFalse(created2["called"])

    def test_missing_record_rejected(self):
        import threading
        created = {"called": False}
        orig_new = self.app.state.assistant.new_conversation
        def fake_new(*a, **k):
            created["called"] = True
            return orig_new(*a, **k)
        self.app.state.assistant.new_conversation = fake_new
        self.app.state.run_agent("missing-run-id", "request", self.workspace["workspace_id"], threading.Event())
        self.app.state.assistant.new_conversation = orig_new
        self.assertFalse(created["called"])

    def test_missing_metadata_scope_rejected(self):
        import json
        run_id, created = self._run_with_metadata(json.dumps({"request": "r"}))
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])

    def test_mismatched_scope_rejected(self):
        import json
        run_id, created = self._run_with_metadata(json.dumps({"workspace_id": self.workspace["workspace_id"], "project_id": "wrong", "request": "r"}))
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])

    def test_valid_metadata_reaches_disabled_dispatch_gate(self):
        import json
        run_id, created = self._run_with_metadata(json.dumps({"workspace_id": self.workspace["workspace_id"], "project_id": self.project["project_id"], "request": "r"}))
        run = self.store.get_agent_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertFalse(created["called"])
        self.assertIn("dispatchable", run["summary"] or "")



class MemoryApiScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.store = self.app.state.store
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])
        self.other = register_project(self.store, "Other")

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _create_memory(self, content, project_id=None, workspace_id=None):
        status, body = asgi_request(self.app, "POST", "/api/v1/memories", {
            "content": content, "project_id": project_id, "workspace_id": workspace_id,
        })
        self.assertEqual(status, 201, body)
        return body["id"]

    def test_memory_listing_is_global_project_and_workspace_scoped(self):
        global_id = self._create_memory("global alpha")
        project_id = self._create_memory("project alpha", self.project["project_id"])
        workspace_id = self._create_memory("workspace alpha", self.project["project_id"],
                                           self.workspace["workspace_id"])
        status, global_rows = asgi_request(self.app, "GET", "/api/v1/memories")
        self.assertEqual(status, 200)
        self.assertEqual({row["id"] for row in global_rows}, {global_id})
        status, project_rows = asgi_request(
            self.app, "GET", f"/api/v1/memories?project_id={self.project['project_id']}")
        self.assertEqual(status, 200)
        self.assertEqual({row["id"] for row in project_rows}, {global_id, project_id})
        status, workspace_rows = asgi_request(
            self.app, "GET", f"/api/v1/memories?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)
        self.assertEqual({row["id"] for row in workspace_rows}, {global_id, project_id, workspace_id})
        status, invalid = asgi_request(self.app, "GET", "/api/v1/memories?project_id=missing")
        self.assertEqual(status, 422)

    def test_memory_review_never_compares_across_private_project_boundary(self):
        self._create_memory("shared phrase global")
        self._create_memory("shared phrase project", self.project["project_id"])
        status, global_review = asgi_request(self.app, "GET", "/api/v1/memories/review")
        self.assertEqual(status, 200)
        self.assertEqual(global_review["analyzed_records"], 1)
        status, project_review = asgi_request(
            self.app, "GET", f"/api/v1/memories/review?project_id={self.project['project_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(project_review["analyzed_records"], 2)

    def test_memory_archive_and_supersede_require_scope_and_preserve_ownership(self):
        project_memory = self._create_memory("project source", self.project["project_id"])
        status, result = asgi_request(
            self.app, "POST", f"/api/v1/memories/{project_memory}/supersede",
            {"content": "replacement from project"})
        self.assertEqual(status, 404)
        status, result = asgi_request(
            self.app, "POST",
            f"/api/v1/memories/{project_memory}/supersede?project_id={self.project['project_id']}",
            {"content": "replacement from project"})
        self.assertEqual(status, 200)
        replacement_id = result["id"]
        row = self.store.db.execute(
            "SELECT project_id,workspace_id FROM memories WHERE id=?", (replacement_id,)).fetchone()
        self.assertEqual(row["project_id"], self.project["project_id"])
        self.assertIsNone(row["workspace_id"])
        status, result = asgi_request(
            self.app, "POST", f"/api/v1/memories/{replacement_id}/archive")
        self.assertEqual(status, 404)
        status, result = asgi_request(
            self.app, "POST",
            f"/api/v1/memories/{replacement_id}/archive?project_id={self.project['project_id']}")
        self.assertEqual(status, 200)

    def test_memory_candidate_routes_validate_and_enforce_scope(self):
        candidate_id = self.store.propose_memory(
            "workspace candidate", project_id=self.project["project_id"],
            workspace_id=self.workspace["workspace_id"])
        status, rows = asgi_request(self.app, "GET", "/api/v1/memory-candidates")
        self.assertEqual(status, 200)
        self.assertNotIn(candidate_id, [row["id"] for row in rows])
        status, rows = asgi_request(
            self.app, "GET",
            f"/api/v1/memory-candidates?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)
        self.assertIn(candidate_id, [row["id"] for row in rows])
        status, result = asgi_request(
            self.app, "POST", f"/api/v1/memory-candidates/{candidate_id}/review",
            {"approved": True})
        self.assertEqual(status, 404)
        status, result = asgi_request(
            self.app, "POST",
            f"/api/v1/memory-candidates/{candidate_id}/review?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}",
            {"approved": True})
        self.assertEqual(status, 200)



class AgentScopeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.store = self.app.state.store
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.other = register_project(self.store, "Other")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        cfg = create_configuration(self.store, {"schema_version": 1, "components": {}}, name="cfg")
        self.workspace = create_workspace(self.store, "Workspace", self.project["project_id"],
                                         cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
                                         checkout_id=self.checkout["checkout_id"])

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_agent_run_listing_and_detail_are_scope_filtered(self):
        from evo_core import background_agent
        global_run = self.store.start_agent_run("coding", {})
        scoped_run = self.store.start_agent_run("coding", {
            "project_id": self.project["project_id"],
            "workspace_id": self.workspace["workspace_id"],
            "request": "private workspace run",
        })
        background_agent.create(self.app.state.lab_db.connection, scoped_run)
        status, rows = asgi_request(self.app, "GET", "/api/v1/agents?limit=100")
        self.assertEqual(status, 200)
        self.assertEqual({row["id"] for row in rows}, {global_run})
        status, rows = asgi_request(
            self.app, "GET",
            f"/api/v1/agents?limit=100&project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)
        self.assertNotIn(global_run, {row["id"] for row in rows})
        self.assertIn(scoped_run, {row["id"] for row in rows})
        status, data = asgi_request(
            self.app, "GET",
            f"/api/v1/agents/{scoped_run}?project_id={self.other['project_id']}")
        self.assertEqual(status, 404)
        status, data = asgi_request(
            self.app, "GET",
            f"/api/v1/agents/{scoped_run}?project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}")
        self.assertEqual(status, 200)

    def test_agent_plan_listing_detail_and_approval_are_scope_filtered(self):
        from evo_core import orchestration
        plan = orchestration.create_plan(
            self.app.state.lab_db.connection, "private request",
            self.workspace["workspace_id"], str(self.directory),
            {"title": "Private plan", "summary": "Private summary", "steps": [{
                "title": "Step", "description": "Do work", "expected_outcome": "Done",
                "verification": "Check result",
            }]},
            project_id=self.project["project_id"], store=self.store)
        status, rows = asgi_request(self.app, "GET", "/api/v1/agents/plans?limit=30")
        self.assertEqual(status, 200)
        self.assertNotIn(plan["id"], {row["id"] for row in rows})
        scoped_query = f"project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}"
        status, rows = asgi_request(self.app, "GET", "/api/v1/agents/plans?limit=30&" + scoped_query)
        self.assertEqual(status, 200)
        self.assertIn(plan["id"], {row["id"] for row in rows})
        status, data = asgi_request(
            self.app, "GET",
            f"/api/v1/agents/plans/{plan['id']}?project_id={self.other['project_id']}")
        self.assertEqual(status, 404)
        status, data = asgi_request(
            self.app, "POST",
            f"/api/v1/agents/plans/{plan['id']}/approve?project_id={self.other['project_id']}", {})
        self.assertEqual(status, 404)
        status, data = asgi_request(
            self.app, "POST",
            f"/api/v1/agents/plans/{plan['id']}/approve?" + scoped_query, {})
        self.assertEqual(status, 200)


class ApiCancellationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.store = self.app.state.store
        initialize_platform_registry(self.store)
        self.project = register_project(self.store, "Project")
        self.directory = self.root / "checkout"
        self.directory.mkdir()
        self.checkout = register_checkout(self.store, self.project["project_id"], self.directory)
        definition = {
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
        cfg = create_configuration(self.store, definition, name="cfg")
        self.workspace = create_workspace(
            self.store, "Workspace", self.project["project_id"],
            cfg["configuration"]["configuration_id"], cfg["revision"]["revision_id"],
            checkout_id=self.checkout["checkout_id"],
        )

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _run(self, metadata=None):
        from evo_core import background_agent
        run_metadata = {
            "project_id": self.project["project_id"],
            "workspace_id": self.workspace["workspace_id"],
            "request": "lifecycle-only test",
        }
        if metadata:
            run_metadata.update(metadata)
        run_id = self.store.start_agent_run("coding", run_metadata)
        with self.app.state.lab_db.lock:
            background_agent.create(self.app.state.lab_db.connection, run_id)
        return run_id

    def _scoped_path(self, run_id):
        return (
            f"/api/v1/agents/{run_id}/cancel?"
            f"project_id={self.project['project_id']}&workspace_id={self.workspace['workspace_id']}"
        )

    def test_queued_cancellation_wins_without_starting_worker(self):
        from evo_core import background_agent
        run_id = self._run()
        status, result = asgi_request(self.app, "POST", self._scoped_path(run_id), {})
        self.assertEqual(status, 200)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["status"], "cancelled")
        with self.app.state.lab_db.lock:
            task = background_agent.get(self.app.state.lab_db.connection, run_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(self.store.get_agent_run(run_id)["status"], "cancelled")

    def test_terminal_outcome_wins_cancellation(self):
        from evo_core import background_agent
        run_id = self._run()
        with self.app.state.lab_db.lock:
            self.assertTrue(background_agent.finalize(
                self.app.state.lab_db.connection, run_id, "completed",
                {"source": "deterministic lifecycle test"},
            ))
        status, result = asgi_request(self.app, "POST", self._scoped_path(run_id), {})
        self.assertEqual(status, 200)
        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "completed")

    def test_workspace_worker_remains_unavailable_before_p35(self):
        before = len(self.store.list_agent_runs(limit=1000))
        status, result = asgi_request(self.app, "POST", "/api/v1/agents", {
            "request": "must not dispatch",
            "workspace_id": self.workspace["workspace_id"],
        })
        self.assertEqual(status, 503)
        self.assertIn("P3.5", result["detail"])
        self.assertEqual(len(self.store.list_agent_runs(limit=1000)), before)

    def test_repeated_cancellation_is_idempotent(self):
        from evo_core import background_agent
        run_id = self._run()
        first_status, first = asgi_request(self.app, "POST", self._scoped_path(run_id), {})
        second_status, second = asgi_request(self.app, "POST", self._scoped_path(run_id), {})
        self.assertEqual(first_status, 200)
        self.assertTrue(first["cancelled"])
        self.assertEqual(first["status"], "cancelled")
        self.assertEqual(second_status, 200)
        self.assertFalse(second["cancelled"])
        self.assertEqual(second["status"], "cancelled")
        with self.app.state.lab_db.lock:
            task_events = background_agent.events(self.app.state.lab_db.connection, run_id)
            task = background_agent.get(self.app.state.lab_db.connection, run_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual([event["type"] for event in task_events].count("cancel_requested"), 1)
