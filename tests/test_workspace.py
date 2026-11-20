import tempfile
import unittest
from pathlib import Path
from evo_core.workspace import Workspace, WorkspaceError

class WorkspaceTests(unittest.TestCase):
    def test_file_operations_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            ws.write_file("src/example.py","print('Evo')\n")
            self.assertEqual(ws.read_file("src/example.py"),"print('Evo')\n")
            self.assertEqual(ws.search_text("evo")[0]["path"],"src/example.py")
            self.assertIn("src/example.py",ws.list_files())
            with self.assertRaises(WorkspaceError):
                ws.write_file("src/example.py","replacement")
            ws.write_file("src/example.py","replacement",overwrite=True)
            self.assertEqual(ws.read_file("src/example.py"),"replacement")

    def test_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            with self.assertRaises(WorkspaceError):
                ws.read_file("../outside.txt")
            with self.assertRaises(WorkspaceError):
                ws.write_file("../outside.txt","bad")

    def test_sensitive_local_config_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            (Path(tmp)/"config.toml").write_text('api_key = "secret"',encoding="utf-8")
            (Path(tmp)/".env").write_text("TOKEN=secret",encoding="utf-8")
            self.assertNotIn("config.toml",ws.list_files())
            self.assertNotIn(".env",ws.list_files())
            with self.assertRaises(WorkspaceError):
                ws.read_file("config.toml")

    def test_commands_require_explicit_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            with self.assertRaises(WorkspaceError):
                ws.run(["python","-c","print('unsafe')"])
            allowed=Workspace(tmp,allowed_commands=[["python","-m","unittest"]])
            result=allowed.run(["python","-m","unittest","--help"],timeout_seconds=5)
            self.assertEqual(result["returncode"],0)
            self.assertIn("unittest",result["stdout"])

if __name__=="__main__":
    unittest.main()
