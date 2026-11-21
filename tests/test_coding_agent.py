import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from evo_core.assistant import EvoAssistant
from evo_core.coding_agent import CodingAgent, is_verification_command
from evo_core.config import EvoConfig
from evo_core.store import EvoStore

class ToolProvider:
    def __init__(self,calls):
        self.calls=list(calls)
        self.messages=[]
    def chat(self,messages,max_tokens,temperature,on_token=None,tools=None):
        self.messages.append(messages)
        result=self.calls.pop(0)
        if on_token and result.get("content"):
            on_token(result["content"])
        return result

def call(name,args,call_id="call-1"):
    return {"id":call_id,"type":"function","function":{"name":name,"arguments":args}}

class CodingAgentTests(unittest.TestCase):
    def make_assistant(self,tmp,provider):
        config=EvoConfig("http://localhost","no-key","fake",3,Path(tmp)/"state.db",100,0,
                         "You are a coding agent.",8,8)
        return EvoAssistant(config,EvoStore(config.database),provider)

    def test_read_tool_then_final_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            (root/"hello.py").write_text("print('hello')\n",encoding="utf-8")
            provider=ToolProvider([
                {"content":"","tool_calls":[call("read_file",{"path":"hello.py"})]},
                {"content":"The file prints hello.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Inspect the project",lambda *_:False)
            self.assertEqual(result["content"],"The file prints hello.")
            self.assertEqual(result["tool_rounds"],2)
            self.assertIn("print('hello')",provider.messages[1][-1]["content"])
            assistant.close()

    def test_project_inspection_is_available_and_policy_is_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            (root/"README.md").write_text("# Demo project\\n",encoding="utf-8")
            (root/"main.py").write_text("print('ok')\\n",encoding="utf-8")
            (root/".env").write_text("TOKEN=must-not-leak",encoding="utf-8")
            provider=ToolProvider([
                {"content":"","tool_calls":[call("inspect_project",{})]},
                {"content":"I inspected the project structure.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Inspect this project",lambda *_:False)
            self.assertEqual(result["status"],"completed")
            self.assertIn("Coding-agent operating rules",provider.messages[0][0]["content"])
            tool_result=provider.messages[1][-1]["content"]
            self.assertIn("README.md",tool_result)
            self.assertIn("main.py",tool_result)
            self.assertNotIn("must-not-leak",tool_result)
            assistant.close()

    def test_max_tool_rounds_marks_run_failed_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("list_files",{})]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,max_tool_rounds=1)
            result=agent.run(cid,"Inspect the project",lambda *_:False)
            self.assertEqual(result["status"],"max_rounds_reached")
            self.assertEqual(result["tool_calls"],1)
            row=assistant.store.db.execute("SELECT status FROM agent_runs WHERE id=?",
                                            (result["run_id"],)).fetchone()
            self.assertEqual(row["status"],"failed")
            assistant.close()

    def test_verification_command_detection_is_conservative(self):
        self.assertTrue(is_verification_command(["python","-m","pytest","-q"]))
        self.assertTrue(is_verification_command(["cargo","test"]))
        self.assertTrue(is_verification_command(["npm","run","test:unit"]))
        self.assertFalse(is_verification_command(["python","main.py"]))
        self.assertFalse(is_verification_command(["git","status"]))

    def test_successful_post_edit_check_is_reported_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"main.py","content":"print(5)","overwrite":False})]},
                {"content":"","tool_calls":[call("run_command",{"argv":["python","-m","unittest"]})]},
                {"content":"Implemented the change and ran the test suite.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["python","-m","unittest"]])
            with patch.object(agent.workspace,"run",return_value={"argv":["python","-m","unittest"],"returncode":0,"stdout":"OK","stderr":"","elapsed_seconds":0.1}):
                result=agent.run(cid,"Create and verify main.py",lambda *_:True)
            self.assertEqual(result["verification"],"passed")
            self.assertIn("Verification signal: PASSED",result["content"])
            run=assistant.store.get_agent_run(result["run_id"])
            import json
            metadata=json.loads(run["metadata_json"])
            self.assertEqual(metadata["verification"]["status"],"passed")
            assistant.close()

    def test_file_change_without_post_edit_check_is_explicitly_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"main.py","content":"print(5)"})]},
                {"content":"Created the file.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Create main.py",lambda *_:True)
            self.assertEqual(result["verification"],"not_run")
            self.assertIn("Verification signal: NOT RUN",result["content"])
            assistant.close()

    def test_failed_post_edit_check_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"main.py","content":"print(5)"})]},
                {"content":"","tool_calls":[call("run_command",{"argv":["pytest","-q"]})]},
                {"content":"The test failed.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["pytest"]])
            with patch.object(agent.workspace,"run",return_value={"argv":["pytest","-q"],"returncode":1,"stdout":"","stderr":"failed","elapsed_seconds":0.1}):
                result=agent.run(cid,"Create and test main.py",lambda *_:True)
            self.assertEqual(result["verification"],"failed")
            self.assertIn("Verification signal: FAILED",result["content"])
            assistant.close()

    def test_write_requires_approval_and_denial_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"new.py","content":"print(1)"})]},
                {"content":"I did not write the file because approval was denied.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Create new.py",lambda *_:False)
            self.assertFalse((root/"new.py").exists())
            event=assistant.store.db.execute("SELECT status FROM tool_events").fetchone()
            self.assertEqual(event["status"],"denied")
            self.assertEqual(result["tool_rounds"],2)
            assistant.close()

if __name__=="__main__":
    unittest.main()
