import asyncio
import json as _json
import tempfile
import unittest
from pathlib import Path

from evo_core.api import create_app
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_project
from evo_core.store import EvoStore


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


class ProjectCheckoutApiTests(unittest.TestCase):
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

    def test_project_create_list_get(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        self.assertEqual(status, 201)
        self.assertEqual(body["status"], "active")
        pid = body["project_id"]
        status, body = asgi_request(self.app, "GET", f"/api/v1/projects/{pid}")
        self.assertEqual(status, 200)
        status, body = asgi_request(self.app, "GET", "/api/v1/projects")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)
        status, body = asgi_request(self.app, "GET", "/api/v1/projects?status=active")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)

    def test_project_update_archive_reactivate(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = body["project_id"]
        version = body["version"]
        status, body = asgi_request(self.app, "PATCH", f"/api/v1/projects/{pid}", {"name": "Renamed", "expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Renamed")
        version = body["version"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/archive", {"expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "archived")
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/reactivate", {"expected_version": body["version"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "active")

    def test_project_unknown_and_stale(self):
        status, body = asgi_request(self.app, "GET", "/api/v1/projects/missing")
        self.assertEqual(status, 404)
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = body["project_id"]
        version = body["version"]
        status, body = asgi_request(self.app, "PATCH", f"/api/v1/projects/{pid}", {"name": "X", "expected_version": 999})
        self.assertEqual(status, 409)

    def test_project_invalid_body(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "   "})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project", "foo": 1})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "GET", "/api/v1/projects?status=bogus")
        self.assertEqual(status, 422)

    def test_checkout_register_list_get(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        d = self.root / "checkout"
        d.mkdir()
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        self.assertEqual(status, 201)
        self.assertEqual(body["availability_status"], "available")
        cid = body["checkout_id"]
        status, body = asgi_request(self.app, "GET", f"/api/v1/checkouts/{cid}")
        self.assertEqual(status, 200)
        status, body = asgi_request(self.app, "GET", f"/api/v1/projects/{pid}/checkouts")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)

    def test_checkout_update_refresh_unregister(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        d = self.root / "checkout"
        d.mkdir()
        status, checkout = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        cid = checkout["checkout_id"]
        version = checkout["version"]
        status, body = asgi_request(self.app, "PATCH", f"/api/v1/checkouts/{cid}", {"branch_or_ref": "main", "expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["branch_or_ref"], "main")
        status, body = asgi_request(self.app, "POST", f"/api/v1/checkouts/{cid}/refresh-availability")
        self.assertEqual(status, 200)
        self.assertEqual(body["availability_status"], "available")
        status, body = asgi_request(self.app, "POST", f"/api/v1/checkouts/{cid}/unregister", {"expected_version": body["version"]})
        self.assertEqual(status, 200)
        self.assertTrue(body["unregistered"])
        self.assertTrue(d.exists())

    def test_checkout_invalid_path_and_conflict(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(self.root / "missing")})
        self.assertEqual(status, 422)
        d = self.root / "checkout"
        d.mkdir()
        asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        self.assertEqual(status, 409)

    def test_checkout_archived_project_rejected(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        version = project["version"]
        asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/archive", {"expected_version": version})
        d = self.root / "checkout"
        d.mkdir()
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        self.assertEqual(status, 422)

    def test_checkout_in_use(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        d = self.root / "checkout"
        d.mkdir()
        status, checkout = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d)})
        cid = checkout["checkout_id"]
        # Seed a workspace reference directly.
        now = "2026-01-01T00:00:00Z"
        cfg_id = "cfg-ref"
        rev_id = "rev-ref"
        store = self.app.state.store
        with store.lock:
            store.db.execute("BEGIN IMMEDIATE")
            try:
                store.db.execute(
                    "INSERT INTO ai_configurations(configuration_id,name,status,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cfg_id, "cfg", "active", rev_id, now, now),
                )
                store.db.execute(
                    "INSERT INTO ai_configuration_revisions(revision_id,configuration_id,revision_number,schema_version,definition_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (rev_id, cfg_id, 1, 1, "{}", "hash", now),
                )
                store.db.execute(
                    "INSERT INTO workspaces(workspace_id,name,project_id,checkout_id,configuration_id,configuration_revision_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("ws-ref", "ws", pid, cid, cfg_id, rev_id, "active", now, now),
                )
                store.db.commit()
            except Exception:
                store.db.rollback()
                raise
        status, body = asgi_request(self.app, "POST", f"/api/v1/checkouts/{cid}/unregister", {"expected_version": checkout["version"]})
        self.assertEqual(status, 409)

    def test_unknown_checkout(self):
        status, body = asgi_request(self.app, "GET", "/api/v1/checkouts/missing")
        self.assertEqual(status, 404)

    def test_unknown_field_rejected(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project", "foo": 1})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", "/api/v1/projects/does-not-matter/checkouts", {"path": "/tmp", "foo": 1}) if False else (422, {})
        # checkout unknown field tested with valid project below
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project2"})
        pid = project["project_id"]
        d = self.root / "checkout2"
        d.mkdir()
        status, body = asgi_request(self.app, "POST", f"/api/v1/projects/{pid}/checkouts", {"path": str(d), "foo": 1})
        self.assertEqual(status, 422)

    def test_expected_version_strict(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        for value in [True, 1.0, "1", 0, -1]:
            status, body = asgi_request(self.app, "PATCH", f"/api/v1/projects/{pid}", {"name": "X", "expected_version": value})
            self.assertEqual(status, 422)



    def test_project_description_null_rejected(self):
        status, project = asgi_request(self.app, "POST", "/api/v1/projects", {"name": "Project"})
        pid = project["project_id"]
        version = project["version"]
        original_description = project["description"]
        status, body = asgi_request(self.app, "PATCH", f"/api/v1/projects/{pid}", {"description": None, "expected_version": version})
        self.assertEqual(status, 422)
        status, fetched = asgi_request(self.app, "GET", f"/api/v1/projects/{pid}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["description"], original_description)
        self.assertEqual(fetched["version"], version)


if __name__ == "__main__":
    unittest.main()
