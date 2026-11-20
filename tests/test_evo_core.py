import tempfile
import unittest
from pathlib import Path
from evo_core.assistant import EvoAssistant
from evo_core.config import EvoConfig
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

if __name__=="__main__":
    unittest.main()
