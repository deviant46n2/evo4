import tempfile
import time
import unittest
from pathlib import Path

try:
    from evo_core.api import create_app
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "FastAPI desktop dependencies are not installed")
class BuildIdentityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = root / "config.toml"
        self.config.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{root}"\nallowed_commands=[]\n',
            encoding="utf-8",
        )
        self.app = create_app(self.config)

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_health_exposes_backend_identity(self):
        started = self.app.state.backend_identity["backend_started_at"]
        health = self.app.state.routes if False else None
        # Call through the registered endpoint by locating it.
        endpoint = None
        for route in self.app.routes:
            if getattr(route, "path", None) == "/api/v1/health" and "GET" in (route.methods or []):
                endpoint = route.endpoint
        self.assertIsNotNone(endpoint)
        body = endpoint()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["backend_started_at"], started)
        self.assertIn("backend_revision", body)
        self.assertIn("backend_build_id", body)
        self.assertIn("backend_dirty", body)
        self.assertIn("build", body)
        self.assertEqual(body["build"]["backend_started_at"], started)

    def test_process_start_time_is_stable(self):
        endpoint = None
        for route in self.app.routes:
            if getattr(route, "path", None) == "/api/v1/health" and "GET" in (route.methods or []):
                endpoint = route.endpoint
        first = endpoint()["backend_started_at"]
        time.sleep(0.05)
        second = endpoint()["backend_started_at"]
        self.assertEqual(first, second)


class BuildIdentityConfigTests(unittest.TestCase):
    def test_vite_config_injects_build_metadata(self):
        config_path = Path(__file__).resolve().parents[1] / "desktop" / "vite.config.ts"
        text = config_path.read_text(encoding="utf-8")
        self.assertIn("__BUILD_TIME__", text)
        self.assertIn("__BUILD_COMMIT__", text)
        self.assertIn("JSON.stringify", text)

    def test_app_distinguishes_dev_and_disconnected_backend(self):
        app_path = Path(__file__).resolve().parents[1] / "desktop" / "src" / "App.tsx"
        text = app_path.read_text(encoding="utf-8")
        self.assertIn("import.meta.env.DEV ? \"FE DEV SERVER\"", text)
        self.assertIn("BE unavailable", text)


if __name__ == "__main__":
    unittest.main()
