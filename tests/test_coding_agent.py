import tempfile
import unittest
from pathlib import Path
from evo_core.assistant import EvoAssistant
from evo_core.coding_agent import CodingAgent
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
