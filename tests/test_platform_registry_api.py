import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from evo_core.api import create_app
from evo_core.platform_registry_api import build_configuration_router

VALID_DEFINITION = {"schema_version": 1, "components": {"model": {"provider": "p", "model": "m"}}}


def make_config(root):
    config = root / "config.toml"
    config.write_text(
        '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
        f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
        f'[workspace]\nroot="{root}"\nallowed_commands=[]\n',
        encoding="utf-8",
    )
    return config


def endpoint(app, method, path):
    candidates = list(app.routes)
    for route in list(candidates):
        if hasattr(route, "routes"):
            candidates.extend(route.routes)
        if getattr(route, "original_router", None) is not None:
            candidates.extend(getattr(route.original_router, "routes", []))
    for route in candidates:
        if getattr(route, "path", None) == path and method in (route.methods or []):
            return route.endpoint
    raise RuntimeError(f"route not found: {method} {path}")


class PlatformRegistryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)
        self.store = self.app.state.store
        self.router = build_configuration_router(self.store)

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def _call(self, method, path, **kwargs):
        ep = endpoint(self.app, method, path)
        try:
            return ep(**kwargs), None
        except HTTPException as exc:
            return None, exc

    def test_create_and_response_contract(self):
        ep = endpoint(self.app, "POST", "/api/v1/configurations")
        result, err = None, None
        try:
            result = ep(payload=__import__("evo_core.platform_registry_api", fromlist=["ConfigurationCreateRequest"]).ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg", change_summary="init"))
        except HTTPException as exc:
            err = exc
        self.assertIsNone(err)
        self.assertEqual(result.configuration.name, "cfg")
        self.assertEqual(result.configuration.status, "active")
        self.assertEqual(result.revision.revision_number, 1)
        self.assertIsNone(result.revision.parent_revision_id)

    def test_list_and_status_filter(self):
        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        from evo_core.platform_registry_api import ConfigurationCreateRequest

        ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="a"))
        created_b = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="b")).configuration
        ep_archive = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/archive")
        ep_archive(configuration_id=created_b.configuration_id, payload=__import__("evo_core.platform_registry_api", fromlist=["ConfigurationUpdateRequest"]).ConfigurationUpdateRequest(status="archived", expected_version=created_b.version))
        ep_list = endpoint(self.app, "GET", "/api/v1/configurations")
        all_items = ep_list()
        self.assertEqual(all_items.total, 2)
        archived = ep_list(status="archived")
        self.assertEqual(archived.total, 1)

    def test_get_configuration(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        ep_get = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}")
        result = ep_get(configuration_id=cid)
        self.assertEqual(result.configuration_id, cid)

    def test_revision_list_and_get(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        rid = created.revision.revision_id
        ep_list = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}/revisions")
        listed = ep_list(configuration_id=cid)
        self.assertEqual(listed.total, 1)
        ep_get = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}/revisions/{revision_id}")
        one = ep_get(configuration_id=cid, revision_id=rid)
        self.assertEqual(one.revision_id, rid)

    def test_create_revision(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest, RevisionCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        new_def = {"schema_version": 1, "components": {"model": {"provider": "p2", "model": "m2"}}}
        ep_rev = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/revisions")
        result = ep_rev(configuration_id=cid, payload=RevisionCreateRequest(definition=new_def, expected_version=1, change_summary="update"))
        self.assertEqual(result.revision.revision_number, 2)
        ep_get = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}")
        cfg = ep_get(configuration_id=cid)
        self.assertEqual(cfg.current_revision_id, result.revision.revision_id)
        self.assertEqual(cfg.version, 2)

    def test_restore_revision(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest, RevisionCreateRequest, RestoreRevisionRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        rid = created.revision.revision_id
        new_def = {"schema_version": 1, "components": {"model": {"provider": "p2", "model": "m2"}}}
        ep_rev = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/revisions")
        ep_rev(configuration_id=cid, payload=RevisionCreateRequest(definition=new_def, expected_version=1))
        ep_restore = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/restore/{revision_id}")
        restored = ep_restore(configuration_id=cid, revision_id=rid, payload=RestoreRevisionRequest(expected_version=2, change_summary="restore"))
        self.assertEqual(restored.revision.revision_number, 3)
        self.assertEqual(restored.configuration.current_revision_id, restored.revision.revision_id)
        ep_list = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}/revisions")
        history = ep_list(configuration_id=cid)
        self.assertEqual(history.total, 3)

    def test_patch_archive_and_reactivate(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest, ConfigurationUpdateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        version = created.configuration.version
        ep_patch = endpoint(self.app, "PATCH", "/api/v1/configurations/{configuration_id}")
        archived = ep_patch(configuration_id=cid, payload=ConfigurationUpdateRequest(status="archived", expected_version=version))
        self.assertEqual(archived.status, "archived")
        reactivated = ep_patch(configuration_id=cid, payload=ConfigurationUpdateRequest(status="active", expected_version=archived.version))
        self.assertEqual(reactivated.status, "active")

    def test_archive_endpoint(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest, ConfigurationUpdateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        version = created.configuration.version
        from evo_core.platform_registry_api import ArchiveRequest

        ep_archive = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/archive")
        response = ep_archive(configuration_id=cid, payload=ArchiveRequest(expected_version=version))
        self.assertEqual(response.status, "archived")

    def test_invalid_expected_version(self):
        from pydantic import ValidationError

        from evo_core.platform_registry_api import RevisionCreateRequest

        for value in [True, 1.0, "1", 0, -1, None]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    RevisionCreateRequest(definition=VALID_DEFINITION, expected_version=value)

    def test_unknown_configuration(self):
        ep_get = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}")
        try:
            ep_get(configuration_id="does-not-exist")
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 404)
        ep_rev = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/revisions")
        try:
            ep_rev(configuration_id="does-not-exist", payload=__import__("evo_core.platform_registry_api", fromlist=["RevisionCreateRequest"]).RevisionCreateRequest(definition=VALID_DEFINITION, expected_version=1))
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 404)

    def test_unknown_revision(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        ep_get = endpoint(self.app, "GET", "/api/v1/configurations/{configuration_id}/revisions/{revision_id}")
        try:
            ep_get(configuration_id=cid, revision_id="does-not-exist")
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 404)

    def test_invalid_definition(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        try:
            ep_create(payload=ConfigurationCreateRequest(definition={"schema_version": 1, "components": {"a": {"api_key": "secret"}}}, name="cfg"))
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 422)
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        from evo_core.platform_registry_api import RevisionCreateRequest

        ep_rev = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/revisions")
        try:
            ep_rev(configuration_id=cid, payload=RevisionCreateRequest(definition={"schema_version": 2, "components": {}}, expected_version=1))
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 422)

    def test_stale_version_conflict(self):
        from evo_core.platform_registry_api import ConfigurationCreateRequest, RevisionCreateRequest

        ep_create = endpoint(self.app, "POST", "/api/v1/configurations")
        created = ep_create(payload=ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg"))
        cid = created.configuration.configuration_id
        ep_rev = endpoint(self.app, "POST", "/api/v1/configurations/{configuration_id}/revisions")
        try:
            ep_rev(configuration_id=cid, payload=RevisionCreateRequest(definition=VALID_DEFINITION, expected_version=999))
            self.fail("expected HTTPException")
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 409)

    def test_unknown_request_field_rejected(self):
        from pydantic import ValidationError

        from evo_core.platform_registry_api import ConfigurationCreateRequest

        with self.assertRaises(ValidationError):
            ConfigurationCreateRequest(definition=VALID_DEFINITION, name="cfg", foo=1)

    def test_whitespace_name_rejected(self):
        from pydantic import ValidationError

        from evo_core.platform_registry_api import ConfigurationCreateRequest

        with self.assertRaises(ValidationError):
            ConfigurationCreateRequest(definition=VALID_DEFINITION, name="   ")



import asyncio
import json as _json


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


class PlatformRegistryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)
        self.app = create_app(self.config)

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_create_http(self):
        status, body = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})
        self.assertEqual(status, 201)
        self.assertIn("configuration", body)
        self.assertIn("revision", body)
        self.assertEqual(body["configuration"]["status"], "active")

    def test_list_and_status_filter_http(self):
        asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "a"})
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "b"})[1]
        cid = created["configuration"]["configuration_id"]
        version = created["configuration"]["version"]
        asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/archive", {"expected_version": version})
        status, body = asgi_request(self.app, "GET", "/api/v1/configurations")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        status, body = asgi_request(self.app, "GET", "/api/v1/configurations?status=archived")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)

    def test_revision_create_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        new_def = {"schema_version": 1, "components": {"model": {"provider": "p2", "model": "m2"}}}
        status, body = asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/revisions", {"definition": new_def, "expected_version": 1})
        self.assertEqual(status, 201)
        self.assertEqual(body["revision"]["revision_number"], 2)
        self.assertEqual(body["configuration"]["version"], 2)

    def test_restore_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        rid = created["revision"]["revision_id"]
        new_def = {"schema_version": 1, "components": {"model": {"provider": "p2", "model": "m2"}}}
        asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/revisions", {"definition": new_def, "expected_version": 1})
        status, body = asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/restore/{rid}", {"expected_version": 2})
        self.assertEqual(status, 201)
        self.assertEqual(body["revision"]["revision_number"], 3)
        self.assertEqual(body["configuration"]["current_revision_id"], body["revision"]["revision_id"])

    def test_archive_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        version = created["configuration"]["version"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/archive", {"expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "archived")

    def test_patch_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        version = created["configuration"]["version"]
        status, body = asgi_request(self.app, "PATCH", f"/api/v1/configurations/{cid}", {"status": "archived", "expected_version": version})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "archived")

    def test_invalid_body_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/revisions", {"definition": VALID_DEFINITION, "expected_version": "bad"})
        self.assertEqual(status, 422)
        status, body = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg", "foo": 1})
        self.assertEqual(status, 422)

    def test_unknown_http(self):
        status, body = asgi_request(self.app, "GET", "/api/v1/configurations/does-not-exist")
        self.assertEqual(status, 404)
        status, body = asgi_request(self.app, "GET", "/api/v1/configurations/does-not-exist/revisions/does-not-exist")
        self.assertEqual(status, 404)

    def test_stale_version_http(self):
        created = asgi_request(self.app, "POST", "/api/v1/configurations", {"definition": VALID_DEFINITION, "name": "cfg"})[1]
        cid = created["configuration"]["configuration_id"]
        status, body = asgi_request(self.app, "POST", f"/api/v1/configurations/{cid}/revisions", {"definition": VALID_DEFINITION, "expected_version": 999})
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
