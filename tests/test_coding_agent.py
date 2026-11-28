import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from evo_core.assistant import EvoAssistant
from evo_core.coding_agent import CodingAgent, is_test_command
from evo_core.provider import InvalidToolCallError, ProviderError
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

    def test_truncated_model_response_does_not_execute_proposed_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {
                    "content":"I will write the file, but this response was cut off.",
                    "tool_calls":[call("write_file",{"path":"main.py","content":"print('unsafe')"})],
                    "finish_reason":"length","truncated":True
                },
                {"content":"No further action is needed.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            approvals=[]
            result=agent.run(cid,"Create main.py",lambda *args:approvals.append(args) or True)
            self.assertEqual(result["status"],"completed")
            self.assertEqual(approvals,[])
            self.assertFalse((root/"main.py").exists())
            run=assistant.store.get_agent_run(result["run_id"])
            self.assertEqual(run["status"],"completed")
            metadata=run["metadata"] if "metadata" in run else None
            assistant.close()

    def test_truncated_response_recovers_with_fresh_tool_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {
                    "content":"I will write unsafe content, but this response was cut off.",
                    "tool_calls":[call("write_file",{"path":"main.py","content":"print('unsafe')"}, "call-unsafe")],
                    "finish_reason":"length",
                },
                {
                    "content":"Writing the correct file now.",
                    "tool_calls":[call("write_file",{"path":"main.py","content":"print('safe')"}, "call-safe")],
                    "finish_reason":"stop",
                },
                {"content":"Done.","tool_calls":[]},
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            approvals=[]
            def approval(name,args):
                approvals.append((name,args))
                return True
            result=agent.run(cid,"Create main.py",approval)
            self.assertEqual(result["status"],"completed")
            self.assertEqual(len(provider.messages),3)
            self.assertEqual(len(approvals),1)
            self.assertEqual(approvals[0][1]["content"],"print('safe')")
            self.assertEqual((root/"main.py").read_text(encoding="utf-8"),"print('safe')")
            run=assistant.store.get_agent_run(result["run_id"])
            self.assertEqual(run["status"],"completed")
            metadata=json.loads(run["metadata_json"] or "{}")
            self.assertEqual(metadata.get("provider_response_attempts"),3)
            self.assertEqual(metadata.get("truncated_responses"),1)
            self.assertEqual(metadata.get("continuation_attempts"),1)
            self.assertEqual(metadata.get("tool_calls_processed"),1)
            assistant.close()

    def test_repeated_truncation_executes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {
                    "content":"First truncated response.",
                    "tool_calls":[call("write_file",{"path":"first.py","content":"first"}, "call-first")],
                    "finish_reason":"length",
                },
                {
                    "content":"Second truncated response.",
                    "tool_calls":[call("write_file",{"path":"second.py","content":"second"}, "call-second")],
                    "finish_reason":"length",
                },
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            approvals=[]
            result=agent.run(cid,"Create files",lambda *args:approvals.append(args) or True)
            self.assertEqual(result["status"],"truncated")
            self.assertEqual(len(provider.messages),2)
            self.assertEqual(approvals,[])
            self.assertFalse((root/"first.py").exists())
            self.assertFalse((root/"second.py").exists())
            run=assistant.store.get_agent_run(result["run_id"])
            self.assertEqual(run["status"],"failed")
            metadata=json.loads(run["metadata_json"] or "{}")
            self.assertEqual(metadata.get("provider_response_attempts"),2)
            self.assertEqual(metadata.get("truncated_responses"),2)
            self.assertEqual(metadata.get("continuation_attempts"),1)
            self.assertEqual(metadata.get("tool_calls_processed"),0)
            assistant.close()

    def test_malformed_tool_call_recovers_with_fresh_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            class MalformedProvider:
                def __init__(self):
                    self.calls=0
                def chat(self,messages,max_tokens,temperature,on_token=None,tools=None):
                    self.calls+=1
                    if self.calls==1:
                        raise InvalidToolCallError("bad json", finish_reason="tool_calls")
                    if self.calls==2:
                        return {"content":"","tool_calls":[call("write_file",{"path":"main.py","content":"print('safe')"})],"finish_reason":"stop"}
                    return {"content":"Done.","tool_calls":[]}
            provider=MalformedProvider()
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            approvals=[]
            def approval(name,args):
                approvals.append((name,args))
                return True
            result=agent.run(cid,"Create main.py",approval)
            self.assertEqual(result["status"],"completed")
            self.assertEqual(len(approvals),1)
            self.assertEqual(approvals[0][1]["content"],"print('safe')")
            self.assertEqual((root/"main.py").read_text(encoding="utf-8"),"print('safe')")
            run=assistant.store.get_agent_run(result["run_id"])
            metadata=json.loads(run["metadata_json"] or "{}")
            self.assertEqual(metadata.get("provider_response_attempts"),3)
            self.assertEqual(metadata.get("malformed_tool_call_retries"),1)
            self.assertEqual(metadata.get("tool_calls_processed"),1)
            assistant.close()

    def test_repeated_malformed_tool_calls_fail_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            class MalformedProvider:
                def __init__(self):
                    self.calls=0
                def chat(self,messages,max_tokens,temperature,on_token=None,tools=None):
                    self.calls+=1
                    raise InvalidToolCallError("bad json", finish_reason="tool_calls")
            provider=MalformedProvider()
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            approvals=[]
            result=agent.run(cid,"Create main.py",lambda *args:approvals.append(args) or True)
            self.assertEqual(result["status"],"failed")
            self.assertEqual(approvals,[])
            self.assertFalse((root/"main.py").exists())
            run=assistant.store.get_agent_run(result["run_id"])
            self.assertEqual(run["status"],"failed")
            metadata=json.loads(run["metadata_json"] or "{}")
            self.assertEqual(metadata.get("provider_response_attempts"),2)
            self.assertEqual(metadata.get("malformed_tool_call_retries"),1)
            self.assertEqual(metadata.get("tool_calls_processed"),0)
            self.assertEqual(metadata.get("last_finish_reason"), "tool_calls")
            self.assertEqual(metadata.get("truncated_responses"), 0)
            assistant.close()

    def test_generic_provider_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            class FailingProvider:
                def __init__(self):
                    self.calls=0
                def chat(self,messages,max_tokens,temperature,on_token=None,tools=None):
                    self.calls+=1
                    raise ProviderError("network down")
            provider=FailingProvider()
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            with self.assertRaises(ProviderError):
                agent.run(cid,"Create main.py",lambda *_:True)
            self.assertEqual(provider.calls,1)
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

    def test_verification_must_happen_after_the_latest_successful_write(self):
        report=CodingAgent._verification_state(2,4,{
            "tool_call":3,"status":"completed","returncode":0,"argv":["pytest"]})
        self.assertEqual(report["status"],"not_run")
        self.assertEqual(CodingAgent._verification_state(0,0,None)["status"],"not_required")

    def test_test_command_detection_is_conservative(self):
        self.assertTrue(is_test_command(["python","-m","pytest","-q"]))
        self.assertTrue(is_test_command(["cargo","test"]))
        self.assertTrue(is_test_command(["npm","run","test:unit"]))
        self.assertFalse(is_test_command(["python","main.py"]))
        self.assertFalse(is_test_command(["git","status"]))
        self.assertFalse(is_test_command(["python","script.py","/tmp/build"]))
        self.assertFalse(is_test_command(["git","diff","--check"]))
        self.assertFalse(is_test_command(["npx","eslint","."]))

    def test_run_command_approval_displays_and_binds_complete_execution_specification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("run_command",{
                    "argv":["python","-m","unittest"], "timeout_seconds":45,
                    "resource_limits":{"cpu_seconds":30}, "expected_artifacts":["coverage.xml"],
                    "output_limit_bytes":4096,
                    "environment_contract":{"inherit_safe_environment":False,"variables":{"MODE":"test"}},
                })]},
                {"content":"The check completed.","tool_calls":[]},
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["python","-m","unittest"]])
            approvals=[]
            def approve(name,args):
                approvals.append((name,args))
                return True
            def complete_execution(db,lock,execution_id):
                with lock:
                    db.execute(
                        "UPDATE workload_executions SET status='completed',returncode=0,stdout='OK',finished_at='2026-01-01T00:00:00Z' WHERE id=?",
                        (execution_id,),
                    )
                    db.commit()
            with patch("evo_experiments.execution.run_execution",side_effect=complete_execution):
                result=agent.run(cid,"Run tests with the requested execution contract.",approve)
            self.assertEqual(result["status"],"completed")
            approved_args=approvals[0][1]
            spec=approved_args["execution_specification"]
            self.assertEqual(spec["resource_limits"],{"cpu_seconds":30})
            self.assertEqual(spec["expected_artifacts"],["coverage.xml"])
            self.assertEqual(spec["environment_contract"]["variables"],{"MODE":"test"})
            from evo_experiments.execution import get_execution
            execution_id=assistant.store.db.execute("SELECT id FROM workload_executions").fetchone()["id"]
            record=get_execution(assistant.store.db,execution_id)
            self.assertEqual(record["approval_evidence"]["execution_specification_sha256"],
                             approved_args["execution_specification_sha256"])
            assistant.close()

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
            def complete_persisted_execution(db, lock, execution_id):
                # Model the supervisor's contract: it persists its final state;
                # the coding agent then retrieves that authoritative row.
                with lock:
                    db.execute(
                        """UPDATE workload_executions
                           SET status='completed',returncode=0,stdout='OK',stderr='',
                               elapsed_seconds=0.1,finished_at='2026-01-01T00:00:00Z'
                           WHERE id=?""",
                        (execution_id,),
                    )
                    db.commit()

            with patch("evo_experiments.execution.run_execution",side_effect=complete_persisted_execution):
                result=agent.run(cid,"Create and verify main.py",lambda *_:True)
            self.assertEqual(result["verification"],"passed")
            self.assertIn("Verification signal: PASSED",result["content"])
            run=assistant.store.get_agent_run(result["run_id"])
            import json
            metadata=json.loads(run["metadata_json"])
            self.assertEqual(metadata["verification"]["status"],"passed")
            self.assertEqual(metadata["workspace"],str(root.resolve()))
            self.assertEqual(metadata["model"],"fake")
            self.assertEqual(metadata["conversation_id"],cid)
            assistant.close()

    def test_managed_command_runs_without_holding_store_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("run_command",{"argv":["python","-m","unittest"]})]},
                {"content":"The check completed.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["python","-m","unittest"]])

            def assert_lock_released(db, lock, execution_id):
                self.assertFalse(lock._is_owned(),
                    "managed process supervision must not hold the application store lock")
                return {"id":execution_id,"argv":["python","-m","unittest"],
                        "returncode":0,"stdout":"OK","stderr":"",
                        "elapsed_seconds":0.1,"status":"completed"}

            with patch("evo_experiments.execution.run_execution",side_effect=assert_lock_released) as execute:
                result=agent.run(cid,"Run the unit tests",lambda *_:True,
                                source_revision="a"*40)
            execute.assert_called_once()
            self.assertEqual(result["verification"],"not_required")
            row=assistant.store.db.execute(
                "SELECT source_revision FROM workload_executions WHERE agent_run_id=?",
                (result["run_id"],),
            ).fetchone()
            self.assertEqual(row["source_revision"],"a"*40)
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

    def test_lint_only_command_does_not_count_as_test_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"main.py","content":"print(5)"})]},
                {"content":"","tool_calls":[call("run_command",{"argv":["ruff","check","."]})]},
                {"content":"Lint completed; tests were not run.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["ruff","check"]])
            with patch.object(agent.workspace,"run",return_value={"argv":["ruff","check","."],"returncode":0,"stdout":"All checks passed","stderr":"","elapsed_seconds":0.1}):
                result=agent.run(cid,"Create and lint main.py",lambda *_:True)
            self.assertEqual(result["verification"],"not_run")
            self.assertIn("Verification signal: NOT RUN",result["content"])
            assistant.close()

    def test_test_file_write_requires_and_consumes_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"src/widget.test.js","content":"test('ok',()=>{});"})]},
                {"content":"Updated the test after approval.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Update the test file",lambda name,args: name=="write_file")
            self.assertEqual(result["status"],"completed")
            self.assertEqual((root/"src/widget.test.js").read_text(encoding="utf-8"),"test('ok',()=>{});")
            assistant.close()

    def test_test_file_write_is_not_performed_when_approval_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("write_file",{"path":"tests/test_new.py","content":"def test_new(): pass"})]},
                {"content":"No test file was changed.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root)
            result=agent.run(cid,"Update the test file",lambda *_:False)
            self.assertFalse((root/"tests/test_new.py").exists())
            self.assertEqual(result["status"],"completed")
            assistant.close()

    def test_disallowed_command_is_rejected_before_requesting_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"project"; root.mkdir()
            provider=ToolProvider([
                {"content":"","tool_calls":[call("run_command",{"argv":["python","unsafe.py"]})]},
                {"content":"The command was outside the workspace policy.","tool_calls":[]}
            ])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            agent=CodingAgent(assistant,root,allowed_commands=[["pytest"]])
            approvals=[]
            result=agent.run(cid,"Run an unapproved command",
                             lambda name,args: approvals.append((name,args)) or True)
            self.assertEqual(approvals,[])
            event=assistant.store.db.execute(
                "SELECT status,output_summary FROM tool_events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(event["status"],"failed")
            self.assertIn("not permitted",event["output_summary"])
            self.assertEqual(result["status"],"completed")
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


    def test_existing_run_id_is_reused_for_desktop_orchestration(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider=ToolProvider([{"content":"Inspected the project; no changes needed.","tool_calls":[]}])
            assistant=self.make_assistant(tmp,provider)
            cid=assistant.new_conversation()
            run_id=assistant.store.start_agent_run("coding",{"source":"desktop","workspace":tmp})
            agent=CodingAgent(assistant,Path(tmp))
            result=agent.run(cid,"Inspect this workspace",lambda *_:False,run_id=run_id)
            self.assertEqual(result["run_id"],run_id)
            self.assertEqual(assistant.store.get_agent_run(run_id)["status"],"completed")
            import json
            metadata=json.loads(assistant.store.get_agent_run(run_id)["metadata_json"])
            self.assertEqual(metadata["source"],"desktop")
            self.assertEqual(metadata["conversation_id"],cid)
            self.assertEqual(len(assistant.store.list_agent_runs()),1)
            assistant.close()

if __name__=="__main__":
    unittest.main()


class MalformedToolArgumentTests(unittest.TestCase):
    def make_assistant(self, tmp, provider):
        config = EvoConfig("http://localhost", "no-key", "fake", 3, Path(tmp) / "state.db", 100, 0,
                           "You are a coding agent.", 8, 8)
        return EvoAssistant(config, EvoStore(config.database), provider)

    def _run_with_calls(self, calls, tmp):
        root = Path(tmp) / "project"
        root.mkdir()
        (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        provider = ToolProvider(calls)
        assistant = self.make_assistant(tmp, provider)
        cid = assistant.new_conversation()
        agent = CodingAgent(assistant, root)
        result = agent.run(cid, "Do work", lambda *_: False)
        assistant.close()
        return root, result

    def test_non_dict_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", ["bad"], "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertFalse((root / "main.py").read_text().endswith("unsafe"))
            self.assertIn("stopped", result["content"])

    def test_null_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", None, "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_string_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", "bad", "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_number_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", 42, "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_boolean_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", True, "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_array_arguments_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [call("write_file", [1, 2], "call-1")]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_missing_function_name_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_call = {"id": "call-1", "type": "function", "function": {"arguments": {}}}
            calls = [
                {"content": "", "tool_calls": [bad_call]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_missing_call_id_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_call = {"type": "function", "function": {"name": "write_file", "arguments": {}}}
            calls = [
                {"content": "", "tool_calls": [bad_call]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_multiple_calls_with_one_malformed_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                {"content": "", "tool_calls": [
                    call("read_file", {"path": "main.py"}, "call-1"),
                    call("write_file", "bad", "call-2"),
                ]},
                {"content": "stopped", "tool_calls": []},
            ]
            root, result = self._run_with_calls(calls, tmp)
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")

    def test_truncated_tool_call_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = ToolProvider([
                {
                    "content": "cut off",
                    "tool_calls": [call("write_file", {"path": "main.py", "content": "unsafe"}, "call-1")],
                    "finish_reason": "length",
                    "truncated": True,
                },
                {"content": "stopped", "tool_calls": []},
            ])
            assistant = self.make_assistant(tmp, provider)
            cid = assistant.new_conversation()
            agent = CodingAgent(assistant, root)
            result = agent.run(cid, "Do work", lambda *_: False)
            assistant.close()
            self.assertEqual((root / "main.py").read_text(), "print('ok')\n")
