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

    def test_workspace_root_under_ignored_directory_name_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"build"/"project"; root.mkdir(parents=True)
            (root/"ok.txt").write_text("hello",encoding="utf-8")
            ws=Workspace(root)
            self.assertIn("ok.txt",ws.list_files())
            self.assertEqual(ws.read_file("ok.txt"),"hello")
            ws.write_file("new.txt","x")
            self.assertEqual(ws.read_file("new.txt"),"x")

    def test_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            with self.assertRaises(WorkspaceError):
                ws.read_file("../outside.txt")
            with self.assertRaises(WorkspaceError):
                ws.write_file("../outside.txt","bad")

    def test_symlinks_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            outside=Path(tmp)/"outside.txt"; outside.write_text("private",encoding="utf-8")
            (root/"leak.txt").symlink_to(outside)
            ws=Workspace(root)
            self.assertNotIn("leak.txt",ws.list_files())
            with self.assertRaises(WorkspaceError):
                ws.read_file("leak.txt")

    def test_sensitive_local_config_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(tmp)
            for name in (".env",".env.development",".env.staging","id_ecdsa",
                         "config.toml","config.local.toml","secrets.yaml"):
                (Path(tmp)/name).write_text("TOKEN=secret",encoding="utf-8")
                self.assertNotIn(name,ws.list_files())
                with self.assertRaises(WorkspaceError):
                    ws.read_file(name)
            (Path(tmp)/".git").mkdir()
            (Path(tmp)/".git"/"config").write_text("[remote]",encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                ws.read_file(".git/config")
            with self.assertRaises(WorkspaceError):
                ws.write_file(".git/config","overwrite",overwrite=True)

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
