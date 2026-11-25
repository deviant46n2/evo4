import io
import json
import sqlite3
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
    def test_interactive_cli_requires_local_only_acknowledgement(self):
        parser = evo_cli.build_parser()
        with self.assertRaises(SystemExit) as missing:
            parser.parse_args(["chat"])
        self.assertEqual(missing.exception.code, 2)
        args = parser.parse_args(["chat", "--i-understand-local-only"])
        self.assertTrue(args.i_understand_local_only)
        code_args = parser.parse_args(["code", "--i-understand-local-only", "--workspace", "/tmp/work"])
        self.assertEqual(code_args.workspace, "/tmp/work")

    def make_config(self,path):
        return EvoConfig("http://127.0.0.1:1","no-key","stub-model",3,Path(path),
                         64,0.0,"You are Evo.",8,10)

    def test_assistant_persists_provider_finish_reason_and_truncation(self):
        class TruncatedProvider(StubProvider):
            def chat(self,messages,max_tokens,temperature,on_token=None):
                if on_token:
                    on_token("partial answer")
                return {"content":"partial answer","elapsed_seconds":0.01,"ttft_seconds":0.001,
                        "prompt_tokens":10,"completion_tokens":2,"tokens_per_second":200.0,
                        "finish_reason":"length","truncated":True}
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"state.db")
            store=EvoStore(config.database)
            assistant=EvoAssistant(config,store,TruncatedProvider())
            cid=assistant.new_conversation()
            result=assistant.turn(cid,"Please answer")
            self.assertTrue(result["truncated"])
            row=store.db.execute(
                "SELECT metadata_json FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
                (cid,)).fetchone()
            metadata=json.loads(row["metadata_json"])
            self.assertEqual(metadata["finish_reason"],"length")
            self.assertTrue(metadata["truncated"])
            assistant.close()

    def test_assistant_persists_runtime_invocation_id_on_both_turn_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            store=EvoStore(config.database)
            assistant=EvoAssistant(config,store,StubProvider())
            cid=assistant.new_conversation()
            assistant.turn(cid,"Workspace-scoped turn",invocation_id="invocation-123")
            rows=store.db.execute(
                "SELECT role,metadata_json FROM messages WHERE conversation_id=? ORDER BY id",
                (cid,)).fetchall()
            self.assertEqual([row["role"] for row in rows],["user","assistant"])
            for row in rows:
                metadata=json.loads(row["metadata_json"] or "{}")
                self.assertEqual(metadata["runtime_invocation_id"],"invocation-123")

            global_cid=assistant.new_conversation()
            assistant.turn(global_cid,"Global turn")
            global_rows=store.db.execute(
                "SELECT metadata_json FROM messages WHERE conversation_id=? ORDER BY id",
                (global_cid,)).fetchall()
            for row in global_rows:
                metadata=json.loads(row["metadata_json"] or "{}")
                self.assertNotIn("runtime_invocation_id",metadata)
            assistant.close()
            store.close()

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

    def test_memory_supersession_preserves_old_record_and_retrieves_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            old_id=store.add_memory("The project uses an older model runtime setting","environment")
            new_id=store.supersede_memory(old_id,
                "The project now uses Qwen configuration profile B",
                reason="User corrected the previous configuration.")
            old=store.db.execute("SELECT status FROM memories WHERE id=?",(old_id,)).fetchone()
            new=store.db.execute("SELECT status FROM memories WHERE id=?",(new_id,)).fetchone()
            self.assertEqual(old["status"],"superseded")
            self.assertEqual(new["status"],"active")
            self.assertEqual([row["id"] for row in store.search_memories("Qwen configuration profile")],[new_id])
            relation=store.get_memory_relations([new_id])[0]
            self.assertEqual(relation["relation_type"],"supersedes")
            self.assertEqual(relation["source_memory_id"],new_id)
            self.assertIn("User corrected",relation["evidence"])
            config=self.make_config(Path(tmp)/"evo.db")
            assistant=EvoAssistant(config,store,StubProvider())
            cid=assistant.new_conversation()
            self.assertEqual(store.search_memories("older model runtime setting"),[])
            messages=assistant._build_messages(cid,"older model runtime setting")
            self.assertIn("supersedes an older memory",messages[1]["content"])
            self.assertIn("Qwen configuration profile B",messages[1]["content"])
            assistant.close()

    def test_memory_relation_history_is_ranked_by_query_relevance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            old=store.add_memory("The service endpoint was port 18997")
            new=store.add_memory("The service endpoint is now port 18997")
            store.relate_memories(old,new,"supports","Same endpoint confirmed.")
            other_old=store.add_memory("The endpoint previously used port 8080")
            other_new=store.add_memory("The endpoint now uses port 8080")
            store.relate_memories(other_old,other_new,"supports","Old configuration.")
            rows=store.search_memory_relations("endpoint 18997",limit=1)
            self.assertEqual(rows[0]["source_memory_id"],old)
            self.assertGreater(rows[0]["relevance"],0)
            store.close()

    def test_explicit_contradiction_is_injected_into_assistant_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            assistant=EvoAssistant(config,EvoStore(config.database),StubProvider())
            cid=assistant.new_conversation()
            first=assistant.store.add_memory("The local server uses port 18997","environment")
            second=assistant.store.add_memory("The local server uses port 8080","environment")
            assistant.store.relate_memories(first,second,"contradicts","The user supplied conflicting endpoint values.")
            messages=assistant._build_messages(cid,"local server port")
            self.assertIn("explicitly marked as contradictory",messages[1]["content"])
            self.assertIn("18997",messages[1]["content"])
            self.assertIn("8080",messages[1]["content"])
            assistant.close()

    def test_failed_supersession_rolls_back_new_memory_and_status_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            old_id=store.add_memory("Old active record")
            store.db.execute(
                "CREATE TRIGGER reject_relation BEFORE INSERT ON memory_relations BEGIN SELECT RAISE(ABORT,'forced failure'); END")
            store.db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                store.supersede_memory(old_id,"Replacement record")
            old=store.db.execute("SELECT status FROM memories WHERE id=?",(old_id,)).fetchone()
            self.assertEqual(old["status"],"active")
            self.assertEqual(len(store.list_memories()),1)
            store.close()

    def test_superseding_unknown_memory_does_not_create_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            with self.assertRaisesRegex(ValueError,"Active memory not found"):
                store.supersede_memory("missing","Replacement content")
            self.assertEqual(store.list_memories(),[])
            store.close()

    def test_lexical_fallback_ranks_relevant_memories_before_recent_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            store.fts_available=False
            relevant=store.add_memory("RTX 5070 Ti has 16 GB VRAM","hardware",["gpu"])
            store.add_memory("Pasta with tomato and basil","food",["cooking"])
            store.add_memory("General computer acceleration notes","general",["computer"])
            rows=store.search_memories("RTX VRAM",limit=1)
            self.assertEqual(rows[0]["id"],relevant)
            self.assertGreater(rows[0]["relevance"],0)
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
            self.assertEqual(len(provider.calls[0]),3)
            self.assertIn("Evo 4",provider.calls[0][1]["content"])
            self.assertIn("untrusted",provider.calls[0][0]["content"].lower())
            self.assertEqual(provider.calls[0][-1]["content"],"What is the project called?")
            assistant.turn(cid,"And what is its priority?")
            self.assertEqual(provider.calls[1][0]["role"],"system")
            self.assertEqual(provider.calls[1][-1]["role"],"user")
            self.assertEqual(provider.calls[1][-1]["content"],"And what is its priority?")
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

    def test_lesson_retrieval_prefers_trigger_relevance_over_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            relevant=store.add_lesson("Use pinned CUDA memory measurements.",
                                      trigger_text="CUDA memory profiling",confidence=0.4)
            store.add_lesson("General memory organization advice.",
                             trigger_text="memory",confidence=1.0)
            rows=store.search_lessons("CUDA memory",limit=1)
            self.assertEqual(rows[0]["id"],relevant)
            self.assertGreater(rows[0]["relevance"],0)
            store.close()

    def test_research_retrieval_prefers_title_relevance_over_recency(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"evo.db")
            relevant=store.add_research_document("CUDA memory optimization",
                "A technical note on GPU memory behavior.")
            store.add_research_document("Memory tips","General notes about remembering information.")
            rows=store.search_research("CUDA memory",limit=1)
            self.assertEqual(rows[0]["id"],relevant)
            self.assertGreater(rows[0]["relevance"],0)
            store.close()

    def test_lessons_are_retrieved_into_future_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.make_config(Path(tmp)/"evo.db")
            provider=StubProvider()
            assistant=EvoAssistant(config,EvoStore(config.database),provider)
            cid=assistant.new_conversation()
            assistant.store.add_lesson("Always run the repository tests before claiming a coding task is complete.",
                                       trigger_text="coding tests",category="coding",source="user",confidence=1.0)
            messages=assistant._build_messages(cid,"coding tests")
            self.assertIn("Always run the repository tests",messages[1]["content"])
            self.assertEqual(len(assistant.store.search_lessons("coding tests")),1)
            assistant.close()

    def test_database_backup_preserves_memory_relationships(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=EvoStore(Path(tmp)/"source.db")
            old_id=source.add_memory("The endpoint used to be port 8080")
            new_id=source.supersede_memory(old_id,"The endpoint now uses port 18997",
                                           reason="User verified the new server port.")
            destination=source.backup(Path(tmp)/"backup.sqlite3")
            backup=EvoStore(destination)
            try:
                relation=backup.get_memory_relations([new_id])[0]
                self.assertEqual(relation["source_memory_id"],new_id)
                self.assertEqual(relation["target_memory_id"],old_id)
                self.assertEqual(relation["relation_type"],"supersedes")
            finally:
                backup.close()
                source.close()

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
            self.assertIn("SQLite WAL concurrency",messages[1]["content"])
            self.assertIn("https://sqlite.org/wal.html",messages[1]["content"])
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


    def test_legacy_supersession_edges_are_migrated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"evo.db"
            store=EvoStore(path)
            old_id=store.add_memory("Old project configuration")
            new_id=store.supersede_memory(old_id,"Corrected project configuration")
            # Simulate a database written by the earlier, reversed convention.
            store.db.execute(
                "UPDATE memory_relations SET source_memory_id=?,target_memory_id=? WHERE relation_type='supersedes'",
                (old_id,new_id))
            store.db.execute(
                "DELETE FROM schema_migrations WHERE name='supersedes_direction_current_to_old_v1'")
            store.db.commit()
            store.close()
            migrated=EvoStore(path)
            try:
                relation=migrated.get_memory_relations([new_id])[0]
                self.assertEqual(relation["source_memory_id"],new_id)
                self.assertEqual(relation["target_memory_id"],old_id)
                marker=migrated.db.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE name='supersedes_direction_current_to_old_v1'"
                ).fetchone()[0]
                self.assertEqual(marker,1)
            finally:
                migrated.close()

if __name__=="__main__":
    unittest.main()
