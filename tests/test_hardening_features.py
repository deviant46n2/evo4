import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.assistant import EvoAssistant
from evo_core.coding_agent import is_test_command
from evo_core.config import EvoConfig, load_config
from evo_core.store import EvoStore
from evo_core.workspace import Workspace, WorkspaceError, is_test_path


class HardeningFeatureTests(unittest.TestCase):
    def test_sqlite_connections_enable_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"state.sqlite3")
            try:
                self.assertEqual(store.db.execute("PRAGMA busy_timeout").fetchone()[0],30000)
                self.assertEqual(store.db.execute("PRAGMA journal_mode").fetchone()[0].lower(),"wal")
            finally:
                store.close()

    def test_test_files_require_explicit_workspace_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Workspace(tmp)
            self.assertTrue(is_test_path("tests/test_feature.py"))
            self.assertTrue(is_test_path("src/widget_test.py"))
            self.assertFalse(is_test_path("src/testing_helpers.py"))
            self.assertTrue(is_test_path("src/widget.test.js"))
            self.assertTrue(is_test_path("src/widget.spec.tsx"))
            self.assertTrue(is_test_path("src/__tests__/widget.js"))
            with self.assertRaises(WorkspaceError):
                workspace.write_file("tests/test_feature.py","def test_it(): pass")
            token=workspace.approve_test_write("tests/test_feature.py")
            workspace.write_file("tests/test_feature.py","def test_it(): pass",test_approval=token)
            with self.assertRaises(WorkspaceError):
                workspace.write_file("tests/test_feature.py","def test_it(): pass",test_approval=token)
            self.assertTrue((Path(tmp)/"tests/test_feature.py").is_file())

    def test_project_specific_secret_names_are_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            names=("deploy_api_token.txt","database_password.yaml","private_key_backup.pem","api_key_backup.txt")
            for name in names:
                (root/name).write_text("not-for-model",encoding="utf-8")
            workspace=Workspace(root)
            visible=workspace.list_files()
            for name in names:
                self.assertNotIn(name,visible)
                with self.assertRaises(WorkspaceError):
                    workspace.read_file(name)
            for ordinary in ("auth_helpers.py","private_types.py","tokenizer.py"):
                (root/ordinary).write_text("safe source",encoding="utf-8")
            visible=set(workspace.list_files())
            for ordinary in ("auth_helpers.py","private_types.py","tokenizer.py"):
                self.assertIn(ordinary,visible)

    def test_only_test_runners_count_as_test_verification(self):
        self.assertTrue(is_test_command(["pytest","-q"]))
        self.assertTrue(is_test_command(["python","-m","unittest"]))
        self.assertTrue(is_test_command(["cargo","test"]))
        self.assertTrue(is_test_command(["npm","run","test:unit"]))
        self.assertFalse(is_test_command(["ruff","check","."]))
        self.assertFalse(is_test_command(["git","diff","--check"]))
        self.assertFalse(is_test_command(["python","script.py"]))

    def test_context_budget_preserves_system_policy_and_current_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=EvoConfig("http://localhost","no-key","fake",30,Path(tmp)/"state.db",
                128,0.0,"BASE POLICY",8,8,context_window_tokens=4096)
            assistant=EvoAssistant(config,EvoStore(config.database),provider=object())
            try:
                messages=[
                    {"role":"system","content":"BASE POLICY\n"+"retrieved memory "*300},
                    {"role":"user","content":"oldest "*1000},
                    {"role":"assistant","content":"middle "*2000},
                    {"role":"user","content":"newest history"},
                    {"role":"user","content":"CURRENT REQUEST"},
                ]
                fitted=assistant._fit_context(messages)
                self.assertTrue(fitted[0]["content"].startswith("BASE POLICY"))
                self.assertEqual(fitted[-1]["content"],"CURRENT REQUEST")
                self.assertNotIn("oldest",str(fitted))
                self.assertIn("newest history",str(fitted))
            finally:
                assistant.close()

    def test_named_provider_profile_uses_environment_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"config.toml"
            path.write_text(
                '[server]\nmodel="legacy"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:18997"\nmodel="qwen"\n'
                '[providers.cloud]\nbase_url="https://example.invalid/v1"\nmodel="free-model"\napi_key_env="EVO_TEST_API_KEY"\n',
                encoding="utf-8")
            with patch.dict(os.environ,{"EVO_TEST_API_KEY":"test-secret"}):
                config=load_config(path,"cloud")
            self.assertEqual(config.provider_name,"cloud")
            self.assertEqual(config.model,"free-model")
            self.assertEqual(config.api_key,"test-secret")
            self.assertEqual(config.base_url,"https://example.invalid/v1")

    def test_unknown_provider_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"config.toml"
            path.write_text('[server]\nmodel="legacy"\n',encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Unknown provider profile"):
                load_config(path,"missing")

    def test_oversized_current_request_is_rejected_instead_of_silently_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=EvoConfig("http://localhost","no-key","fake",30,Path(tmp)/"state.db",128,0.0,
                "BASE POLICY",8,8,context_window_tokens=4096)
            assistant=EvoAssistant(config,EvoStore(config.database),provider=object())
            try:
                with self.assertRaisesRegex(ValueError,"current request exceed"):
                    assistant._fit_context([{"role":"system","content":"BASE POLICY"},
                        {"role":"user","content":"x"*20000}])
            finally:
                assistant.close()

    def test_named_provider_profile_accepts_direct_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"config.toml"
            path.write_text('[server]\nmodel="legacy"\n[providers.local]\nmodel="qwen"\napi_key="direct-secret"\n',encoding="utf-8")
            config=load_config(path,"local")
            self.assertEqual(config.api_key,"direct-secret")

    def test_retrieved_context_sections_are_kept_or_omitted_as_a_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=EvoConfig("http://localhost","no-key","fake",30,Path(tmp)/"state.db",128,0.0,
                "BASE POLICY",8,8,context_window_tokens=4096)
            assistant=EvoAssistant(config,EvoStore(config.database),provider=object())
            try:
                oversized_section="\n\nResearch record title\n"+"payload-"*1800
                fitted=assistant._fit_context([
                    {"role":"system","content":"BASE POLICY"+oversized_section},
                    {"role":"user","content":"current request"}])
                system=fitted[0]["content"]
                self.assertNotIn("Research record title",system)
                self.assertNotIn("payload-",system)
                self.assertIn("Context notice",system)
            finally:
                assistant.close()

    def test_output_reserve_cannot_consume_entire_context_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=EvoConfig("http://localhost","no-key","fake",30,Path(tmp)/"state.db",4096,0.0,
                "BASE POLICY",8,8,context_window_tokens=4096)
            assistant=EvoAssistant(config,EvoStore(config.database),provider=object())
            try:
                with self.assertRaisesRegex(ValueError,"configured context budget"):
                    assistant._fit_context([
                        {"role":"system","content":"BASE POLICY"},
                        {"role":"user","content":"small request"}])
            finally:
                assistant.close()


if __name__=="__main__":
    unittest.main()
