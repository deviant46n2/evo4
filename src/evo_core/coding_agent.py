import json
from .provider import ProviderError
from .workspace import Workspace, WorkspaceError

TOOL_SPECS = [
 {"type":"function","function":{"name":"list_files","description":"List files beneath the configured project workspace.","parameters":{"type":"object","properties":{"path":{"type":"string","default":"."},"pattern":{"type":"string","default":"*"}},"additionalProperties":False}}},
 {"type":"function","function":{"name":"read_file","description":"Read a UTF-8 text file beneath the configured project workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"search_text","description":"Search file contents for a literal text string beneath the workspace.","parameters":{"type":"object","properties":{"query":{"type":"string"},"path":{"type":"string","default":"."}},"required":["query"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"write_file","description":"Create or replace a text file. Requires explicit user approval.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"overwrite":{"type":"boolean","default":False}},"required":["path","content"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"run_command","description":"Run an argv command that matches the user's explicit workspace command allowlist. Requires explicit user approval.","parameters":{"type":"object","properties":{"argv":{"type":"array","items":{"type":"string"},"minItems":1},"timeout_seconds":{"type":"integer","default":120}},"required":["argv"],"additionalProperties":False}}}
]

class CodingAgent:
    """Bounded tool-using coding assistant. Writes and commands require per-action approval."""
    def __init__(self, assistant, workspace_root=None, allowed_commands=(), max_tool_rounds=8):
        self.assistant=assistant
        root=workspace_root if workspace_root is not None else "."
        self.workspace=Workspace(root,allowed_commands=allowed_commands)
        self.max_tool_rounds=max(1,min(int(max_tool_rounds),20))

    def _execute(self, name, args):
        if name=="list_files":
            return self.workspace.list_files(args.get("path","."),args.get("pattern","*"))
        if name=="read_file":
            return self.workspace.read_file(args["path"])
        if name=="search_text":
            return self.workspace.search_text(args["query"],args.get("path","."))
        if name=="write_file":
            return {"written":self.workspace.write_file(args["path"],args["content"],bool(args.get("overwrite",False)))}
        if name=="run_command":
            return self.workspace.run(args["argv"],args.get("timeout_seconds",120))
        raise WorkspaceError(f"Unknown tool: {name}")

    def run(self, conversation_id, request, approval, on_token=None):
        if not request.strip():
            raise ValueError("Coding request cannot be empty")
        store=self.assistant.store
        messages=self.assistant._build_messages(conversation_id,request)
        store.add_message(conversation_id,"user",request)
        run_id=store.start_agent_run("coding",{"workspace":str(self.workspace.root)})
        final_text=""
        try:
            for _ in range(self.max_tool_rounds):
                result=self.assistant.provider.chat(messages,max_tokens=self.assistant.config.max_tokens,
                    temperature=self.assistant.config.temperature,on_token=on_token,tools=TOOL_SPECS)
                calls=result.get("tool_calls") or []
                if not calls:
                    final_text=result.get("content","")
                    store.add_message(conversation_id,"assistant",final_text,metadata={"agent_run_id":run_id})
                    store.finish_agent_run(run_id,"completed",final_text[:1000])
                    return {"content":final_text,"run_id":run_id,"tool_rounds":_+1}
                assistant_call={"role":"assistant","content":result.get("content") or None,
                    "tool_calls":[{"id":call["id"],"type":"function","function":{
                        "name":call["function"]["name"],
                        "arguments":json.dumps(call["function"]["arguments"],ensure_ascii=False)}}
                        for call in calls]}
                messages.append(assistant_call)
                for call in calls:
                    name=call["function"]["name"]
                    args=call["function"]["arguments"]
                    try:
                        if name in {"write_file","run_command"}:
                            if not approval(name,args):
                                output={"error":"User denied this action; no changes or command execution were performed."}
                                status="denied"
                            else:
                                output=self._execute(name,args)
                                status="completed"
                        else:
                            output=self._execute(name,args)
                            status="completed"
                    except Exception as exc:
                        output={"error":f"{type(exc).__name__}: {exc}"}
                        status="failed"
                    store.record_tool_event(run_id,name,args,output,status)
                    messages.append({"role":"tool","tool_call_id":call["id"],
                                     "content":json.dumps(output,ensure_ascii=False,default=str)})
            final_text="Stopped after reaching the maximum tool-call rounds. Review the recorded tool events before continuing."
            store.add_message(conversation_id,"assistant",final_text,metadata={"agent_run_id":run_id,"truncated":True})
            store.finish_agent_run(run_id,"completed",final_text)
            return {"content":final_text,"run_id":run_id,"tool_rounds":self.max_tool_rounds}
        except Exception as exc:
            store.finish_agent_run(run_id,"failed",f"{type(exc).__name__}: {exc}")
            raise
