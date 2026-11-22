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

    def test_project_overview_is_bounded_and_filters_sensitive_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"README.md").write_text("# Example\\n",encoding="utf-8")
            (root/"app.py").write_text("print('ok')\\n",encoding="utf-8")
            (root/".env").write_text("TOKEN=secret-value",encoding="utf-8")
            (root/".git").mkdir()
            (root/".git"/"config").write_text("secret remote",encoding="utf-8")
            ws=Workspace(root)
            overview=ws.project_overview()
            self.assertIn("README.md",overview["project_instructions_and_manifests"])
            self.assertIn("app.py",overview["files"])
            self.assertNotIn(".env",[entry["name"] for entry in overview["top_level"]])
            self.assertNotIn("secret-value",str(overview))
            self.assertNotIn(".git/config",overview["files"])

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


import os

class WorkspaceBoundaryTests(unittest.TestCase):
    def test_ignored_directories_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ignored = root / ".git"
            ignored.mkdir()
            (ignored / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "visible.txt").write_text("visible", encoding="utf-8")
            ws = Workspace(root)
            self.assertIn("visible.txt", ws.list_files())
            self.assertNotIn(".git/secret.txt", ws.list_files())
            self.assertNotIn("secret", str(ws.list_files(include_status=True)))

    def test_symlink_directory_is_not_traversed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "link").symlink_to(outside)
            ws = Workspace(root)
            self.assertNotIn("link/secret.txt", ws.list_files())
            self.assertNotIn("link", ws.list_files())

    def test_sqlite_and_result_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            for name in ("data.sqlite", "data.sqlite3", "state.db", "app.log", "result.json"):
                (Path(tmp) / name).write_text("secret", encoding="utf-8")
            listing = ws.list_files()
            for name in ("data.sqlite", "data.sqlite3", "state.db", "app.log"):
                self.assertNotIn(name, listing)
                with self.assertRaises(WorkspaceError):
                    ws.read_file(name)
            (Path(tmp) / "results").mkdir()
            (Path(tmp) / "results" / "out.txt").write_text("secret", encoding="utf-8")
            self.assertNotIn("results/out.txt", ws.list_files())

    def test_ambiguous_source_files_remain_accessible(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            (Path(tmp) / "token_parser.py").write_text("value=1\n", encoding="utf-8")
            (Path(tmp) / "authorization.py").write_text("value=2\n", encoding="utf-8")
            self.assertIn("token_parser.py", ws.list_files())
            self.assertIn("authorization.py", ws.list_files())
            self.assertEqual(ws.read_file("token_parser.py"), "value=1\n")

    def test_listing_reports_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                (root / f"file{i}.txt").write_text("x", encoding="utf-8")
            ws = Workspace(root)
            result = ws.list_files(include_status=True, limit=2)
            self.assertEqual(len(result["files"]), 2)
            self.assertFalse(result["complete"])
            self.assertTrue(result["truncated"])
            self.assertTrue(result["limit_reached"])

    def test_search_reports_match_and_scope_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                (root / f"file{i}.txt").write_text("needle\n", encoding="utf-8")
            ws = Workspace(root)
            result = ws.search_text("needle", limit=1, include_status=True)
            self.assertEqual(len(result["matches"]), 1)
            self.assertTrue(result["match_limit_reached"])
            self.assertFalse(result["complete"])

    def test_unauthorized_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            with self.assertRaises(WorkspaceError):
                ws.run(["python", "-c", "print('unsafe')"])

    def test_authorized_command_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Workspace(tmp, allowed_commands=[["python", "-c"]])
            result = allowed.run(["python", "-c", "print('ok')"])
            self.assertEqual(result["returncode"], 0)
            self.assertIn("ok", result["stdout"])

    def test_command_environment_filters_sensitive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["EVO_WORKSPACE_SECRET_TOKEN"] = "secret-value"
            try:
                allowed = Workspace(tmp, allowed_commands=[["python", "-c"]])
                result = allowed.run(["python", "-c", "import os; print(os.environ.get('EVO_WORKSPACE_SECRET_TOKEN'))"])
                self.assertEqual(result["returncode"], 0)
                self.assertNotIn("secret-value", result["stdout"])
            finally:
                del os.environ["EVO_WORKSPACE_SECRET_TOKEN"]

    def test_test_write_approval_still_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_example.py").write_text("old", encoding="utf-8")
            ws = Workspace(root)
            with self.assertRaises(WorkspaceError):
                ws.write_file("tests/test_example.py", "new", overwrite=True)
