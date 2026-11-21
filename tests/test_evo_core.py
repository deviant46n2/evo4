import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import evo_core.cli as evo_cli
from evo_core.assistant import EvoAssistant
from evo_core.config import EvoConfig, load_config
from evo_core.store import EvoStore

class StubProvider:
    def __init__(self):
        self.calls=[]
    def chat(self,messages,max_tokens,temperature,on_token=None):
        self.calls.append(messages)
        if on_token: on_token("stub reply")
        return {"content":"stub reply","elapsed_seconds":0.01,"ttft_seconds":0.001,
                "prompt_tokens":10,"completion_tokens":2,"tokens_per_second":200.0}
    def list_models(self):
        return ["stub-model"]

class EvoCoreTests(unittest.TestCase):
    def make_config(self,path):
        return EvoConfig("http://127.0.0.1:1","no-key","stub-model",3,Path(path),
                         64,0.0,"You are Evo.",8,10)

    def test_memory_lifecycle_and_lexical_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            mid=store.add_memory("User prefers evidence-based coding recommendations",
                                 category="preferences",tags=["coding"],source="user",confidence=0.9)
            results=store.search_memories("coding recommendations")
            self.assertEqual(results[0]["id"],mid)
            self.assertEqual(results[0]["category"],"preferences")
            self.assertTrue(store.archive_memory(mid))
            self.assertEqual(store.search_memories("coding recommendations"),[])
            store.close()

    def test_conversation_persistence_and_memory_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            store=EvoStore(config.database)
            store.add_memory("The project is named Evo 4 and prioritizes local inference",
                             category="project",source="user",confidence=1.0)
            provider=StubProvider()
            assistant=EvoAssistant(config,store,provider)
            cid=assistant.new_conversation("test")
            assistant.turn(cid,"What is the project called?")
            self.assertEqual(len(provider.calls[0]),2)
            self.assertIn("Evo 4",provider.calls[0][0]["content"])
            self.assertEqual(provider.calls[0][-1]["content"],"What is the project called?")
            assistant.turn(cid,"And what is its priority?")
            self.assertEqual([m["role"] for m in provider.calls[1]],["system","user","assistant","user"])
            messages=store.get_messages(cid,10)
            self.assertEqual([m["role"] for m in messages],["user","assistant","user","assistant"])
            assistant.close()

    def test_automatic_memory_candidates_require_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            provider=StubProvider()
            assistant=EvoAssistant(config,EvoStore(config.database),provider)
            cid=assistant.new_conversation()
            assistant.turn(cid,"I prefer concise technical explanations with evidence.")
            candidates=assistant.store.list_memory_candidates()
            self.assertEqual(len(candidates),1)
            self.assertEqual(candidates[0]["category"],"preferences")
            self.assertEqual(assistant.store.list_memories(),[])
            memory_id=assistant.store.review_memory_candidate(candidates[0]["id"],True)
            self.assertIsInstance(memory_id,str)
            self.assertEqual(len(assistant.store.search_memories("concise technical evidence")),1)
            assistant.turn(cid,"Remember that Evo must prioritize local inference performance.")
            self.assertEqual(len(assistant.store.list_memories()),2)
            assistant.close()

    def test_lessons_are_retrieved_into_future_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            provider=StubProvider()
            assistant=EvoAssistant(config,EvoStore(config.database),provider)
            cid=assistant.new_conversation()
            assistant.store.add_lesson("Always run the repository tests before claiming a coding task is complete.",
                                       trigger_text="coding tests",category="coding",source="user",confidence=1.0)
            messages=assistant._build_messages(cid,"coding tests")
            self.assertIn("Always run the repository tests",messages[0]["content"])
            self.assertEqual(len(assistant.store.search_lessons("coding tests")),1)
            assistant.close()

    def test_database_backup_preserves_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=EvoStore(Path(tmp)/"source.db")
            source.add_memory("Backup integrity matters for persistent assistant data")
            with self.assertRaises(ValueError):
                source.backup(Path(tmp)/"source.db")
            destination=source.backup(Path(tmp)/"backup"/"evo.db")
            backup=EvoStore(destination)
            self.assertEqual(len(backup.list_memories()),1)
            backup.close()
            source.close()

    def test_saved_research_is_retrieved_into_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            assistant=EvoAssistant(config,EvoStore(config.database),StubProvider())
            cid=assistant.new_conversation()
            assistant.store.add_research_document("SQLite WAL concurrency",
                "Write-ahead logging allows readers and a writer to proceed concurrently.",
                "https://sqlite.org/wal.html","web")
            messages=assistant._build_messages(cid,"How does SQLite WAL concurrency work?")
            self.assertIn("SQLite WAL concurrency",messages[0]["content"])
            self.assertIn("https://sqlite.org/wal.html",messages[0]["content"])
            assistant.close()

    def test_tasks_persist_and_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            tid=store.add_task("Build coding workflow",priority=1)
            self.assertEqual(store.list_tasks()[0]["id"],tid)
            self.assertTrue(store.update_task_status(tid,"in_progress"))
            self.assertEqual(store.list_tasks("in_progress")[0]["title"],"Build coding workflow")
            self.assertFalse(store.update_task_status("missing","done"))
            store.close()

    def test_config_reads_assistant_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"config.toml"
            path.write_text('[server]\nmodel="qwen"\n[experiment]\ndatabase="state.db"\n[assistant]\nmax_tokens=1234\nmemory_limit=4\n',encoding="utf-8")
            from evo_core.config import load_config
            config=load_config(path)
            self.assertEqual(config.model,"qwen")
            self.assertEqual(config.max_tokens,1234)
            self.assertEqual(config.memory_limit,4)
            self.assertEqual(config.database,Path("state.db"))
            path.write_text(chr(10).join(['[workspace]','root="project"','allowed_commands=[["python","-m","unittest"]]']),encoding="utf-8")
            config=load_config(path)
            self.assertEqual(config.workspace_root,Path("project"))
            self.assertEqual(config.allowed_commands,(("python","-m","unittest"),))

    def test_allowed_commands_reject_string_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"config.toml"
            path.write_text('[workspace]\nallowed_commands=["pytest"]\n',encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_config_option_works_before_or_after_subcommand(self):
        parser=evo_cli.build_parser()
        self.assertEqual(parser.parse_args(["--config","a.toml","doctor"]).config,"a.toml")
        self.assertEqual(parser.parse_args(["doctor","--config","a.toml"]).config,"a.toml")
        self.assertEqual(parser.parse_args(["doctor"]).config,"config.toml")

    def test_doctor_and_backup_do_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path=Path(tmp)/"state"/"evo.sqlite3"
            config=Path(tmp)/"config.toml"
            config.write_text(f'[server]\nmodel="fake-model"\n[experiment]\ndatabase="{db_path}"\n',
                              encoding="utf-8")
            with patch("evo_core.provider.OpenAICompatibleProvider.list_models",
                       return_value=["fake-model"]):
                with patch.object(sys,"argv",["evo","--config",str(config),"doctor"]):
                    with patch("sys.stdout",new=io.StringIO()):
                        evo_cli.main()
            self.assertFalse(db_path.exists())
            with patch.object(sys,"argv",["evo","--config",str(config),"backup",
                                          str(Path(tmp)/"backup.sqlite3")]):
                with self.assertRaises(SystemExit) as raised:
                    with patch("sys.stderr",new=io.StringIO()):
                        evo_cli.main()
            self.assertEqual(raised.exception.code,2)
            self.assertFalse(db_path.exists())

    def test_like_search_treats_wildcards_literally(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            store.fts_available=False
            exact=store.add_memory("100% local inference")
            store.add_memory("100 local inference")
            self.assertEqual([r["id"] for r in store.search_memories("100%")],[exact])
            lesson=store.add_lesson("Use 100% coverage",trigger_text="100%")
            store.add_lesson("Use 100 coverage",trigger_text="100")
            self.assertEqual([r["id"] for r in store.search_lessons("100%")],[lesson])
            doc=store.add_research_document("100% coverage","100% coverage is required")
            store.add_research_document("100 coverage","100 coverage is required")
            self.assertEqual([r["id"] for r in store.search_research("100%")],[doc])
            store.close()

if __name__=="__main__":
    unittest.main()
