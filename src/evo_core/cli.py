import argparse
import json
import sys
from .assistant import EvoAssistant
from .config import load_config
from .provider import ProviderError
from .store import EvoStore

def build_parser():
    parser=argparse.ArgumentParser(prog="evo",description="Evo 4 local-first assistant")
    parser.add_argument("--config",default="config.toml",help="TOML configuration file")
    sub=parser.add_subparsers(dest="command",required=True)
    doctor=sub.add_parser("doctor",help="Check the configured model endpoint")
    doctor.add_argument("--test-tools",action="store_true",help="Run a harmless function-calling capability probe")
    for name,help_text in (("chat","Start an interactive conversation"),
                           ("code","Start an approval-gated coding-agent session")):
        command=sub.add_parser(name,help=help_text)
        command.add_argument("--conversation",help="Resume an existing conversation ID")
        if name=="code":
            command.add_argument("--workspace",help="Project root (overrides [workspace].root)")
    mem=sub.add_parser("memory",help="Manage persistent memories")
    ms=mem.add_subparsers(dest="memory_command",required=True)
    add=ms.add_parser("add"); add.add_argument("content"); add.add_argument("--category",default="general")
    add.add_argument("--tag",action="append",default=[]); add.add_argument("--source",default="user")
    add.add_argument("--confidence",type=float,default=1.0)
    search=ms.add_parser("search"); search.add_argument("query"); search.add_argument("--limit",type=int,default=10)
    ms.add_parser("list")
    archive=ms.add_parser("archive"); archive.add_argument("id")
    ms.add_parser("candidates",help="List tentative memories awaiting review")
    accept=ms.add_parser("accept"); accept.add_argument("id")
    reject=ms.add_parser("reject"); reject.add_argument("id")
    task=sub.add_parser("task",help="Manage persistent tasks")
    ts=task.add_subparsers(dest="task_command",required=True)
    ta=ts.add_parser("add"); ta.add_argument("title"); ta.add_argument("--description",default="")
    ta.add_argument("--priority",type=int,default=3)
    tl=ts.add_parser("list"); tl.add_argument("--status")
    td=ts.add_parser("status"); td.add_argument("id"); td.add_argument("value",choices=["open","in_progress","blocked","done","cancelled"])
    learn=sub.add_parser("learn",help="Store and retrieve lessons from feedback and outcomes")
    ls=learn.add_subparsers(dest="learn_command",required=True)
    la=ls.add_parser("add"); la.add_argument("lesson"); la.add_argument("--trigger",default="")
    la.add_argument("--category",default="general"); la.add_argument("--source",default="user")
    la.add_argument("--confidence",type=float,default=1.0)
    lq=ls.add_parser("search"); lq.add_argument("query"); lq.add_argument("--limit",type=int,default=5)
    ls.add_parser("list")
    research=sub.add_parser("research",help="Store and search sourced research notes")
    rs=research.add_subparsers(dest="research_command",required=True)
    ra=rs.add_parser("add"); ra.add_argument("title"); ra.add_argument("--content",required=True)
    ra.add_argument("--url"); ra.add_argument("--source-type",default="manual")
    rq=rs.add_parser("search"); rq.add_argument("query"); rq.add_argument("--limit",type=int,default=10)
    sub.add_parser("conversations",help="List recent conversations")
    return parser

def _interactive(args,config):
    assistant=EvoAssistant(config)
    try:
        cid=args.conversation or assistant.new_conversation()
        agent=None
        if args.command=="code":
            from .coding_agent import CodingAgent
            agent=CodingAgent(assistant,args.workspace or config.workspace_root,config.allowed_commands)
            print(f"Evo 4 Coding Agent | workspace {agent.workspace.root} | conversation {cid}")
            print("Writes and commands require per-action approval. Type /exit to quit.")
        else:
            print(f"Evo 4 | conversation {cid}\nType /exit to quit, /new to start another conversation.")
        while True:
            try:
                user_text=input("\nYou> ").strip()
            except (EOFError,KeyboardInterrupt):
                print(); break
            if not user_text: continue
            if user_text=="/exit": break
            if user_text=="/new":
                cid=assistant.new_conversation()
                print(f"New conversation: {cid}")
                continue
            print("\nEvo> ",end="",flush=True)
            try:
                stream=lambda token: print(token,end="",flush=True)
                if agent:
                    def approve(name,arguments):
                        print(f"\n\nApproval required: {name}")
                        print(json.dumps(arguments,indent=2,ensure_ascii=False))
                        return input("Allow this action? [y/N] ").strip().lower()=="y"
                    result=agent.run(cid,user_text,approve,on_token=stream)
                    print(f"\n[agent run {result['run_id']}; {result['tool_rounds']} rounds]",flush=True)
                else:
                    result=assistant.turn(cid,user_text,on_token=stream)
                    print(f"\n[{result['elapsed_seconds']:.1f}s]",flush=True)
            except Exception as exc:
                print(f"\nEvo error: {type(exc).__name__}: {exc}",file=sys.stderr)
        print(f"Conversation ID: {cid}")
    finally:
        assistant.close()

def main():
    args=build_parser().parse_args()
    try:
        config=load_config(args.config)
    except Exception as exc:
        print(f"Configuration error: {exc}",file=sys.stderr); raise SystemExit(2)
    if args.command=="doctor":
        assistant=EvoAssistant(config)
        try:
            models=assistant.provider.list_models()
            print(f"Endpoint: {config.base_url}\nConfigured model: {config.model}\nAvailable models:")
            for model in models: print(f"  {model}")
            if models and config.model not in models: raise SystemExit(2)
            if args.test_tools:
                probe=[{"type":"function","function":{"name":"evo_probe","description":"Return the supplied test value.","parameters":{"type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":False}}}]
                try:
                    result=assistant.provider.chat([{"role":"user","content":"Call evo_probe exactly once with value evo-tool-test."}],
                                                   max_tokens=64,temperature=0.0,tools=probe)
                    calls=result.get("tool_calls") or []
                    if calls and calls[0]["function"]["name"]=="evo_probe":
                        print("Tool calling: supported by this model/server probe.")
                    else:
                        print("Tool calling: no function call returned; coding-agent compatibility is unconfirmed.")
                        raise SystemExit(3)
                except ProviderError as exc:
                    print(f"Tool calling probe failed: {exc}",file=sys.stderr)
                    raise SystemExit(3)
        except ProviderError as exc:
            print(str(exc),file=sys.stderr); raise SystemExit(1)
        finally: assistant.close()
        return
    if args.command in {"chat","code"}:
        _interactive(args,config)
        return
    store=EvoStore(config.database)
    try:
        if args.command=="memory":
            if args.memory_command=="add":
                mid=store.add_memory(args.content,args.category,args.tag,args.source,args.confidence)
                print(f"Saved memory: {mid}")
            elif args.memory_command=="search":
                for row in store.search_memories(args.query,args.limit):
                    print(f"{row['id']} [{row['category']}; confidence={row['confidence']:.2f}; source={row['source']}] {row['content']}")
            elif args.memory_command=="list":
                for row in store.list_memories(): print(f"{row['id']} [{row['category']}] {row['content']}")
            elif args.memory_command=="archive":
                print("Archived." if store.archive_memory(args.id) else "Memory not found.")
            elif args.memory_command=="candidates":
                for row in store.list_memory_candidates():
                    print(f"{row['id']} [{row['category']}; confidence={row['confidence']:.2f}] {row['content']}")
            elif args.memory_command in {"accept","reject"}:
                outcome=store.review_memory_candidate(args.id,args.memory_command=="accept")
                if outcome is None: print("Candidate not found or already reviewed.")
                elif outcome is False: print("Candidate rejected.")
                else: print(f"Candidate accepted as memory {outcome}.")
        elif args.command=="task":
            if args.task_command=="add":
                print(f"Created task: {store.add_task(args.title,args.description,args.priority)}")
            elif args.task_command=="list":
                for row in store.list_tasks(args.status):
                    print(f"{row['id']} [{row['status']} p{row['priority']}] {row['title']}")
            elif args.task_command=="status":
                print("Updated." if store.update_task_status(args.id,args.value) else "Task not found.")
        elif args.command=="learn":
            if args.learn_command=="add":
                lesson_id=store.add_lesson(args.lesson,args.trigger,args.category,args.source,args.confidence)
                print(f"Saved lesson: {lesson_id}")
            elif args.learn_command=="search":
                for row in store.search_lessons(args.query,args.limit):
                    print(f"{row['id']} [{row['category']}; confidence={row['confidence']:.2f}] {row['lesson']}")
            elif args.learn_command=="list":
                for row in store.list_lessons():
                    print(f"{row['id']} [{row['category']}; confidence={row['confidence']:.2f}] {row['lesson']}")
        elif args.command=="research":
            if args.research_command=="add":
                doc_id=store.add_research_document(args.title,args.content,args.url,args.source_type)
                print(f"Saved research document: {doc_id}")
            elif args.research_command=="search":
                for row in store.search_research(args.query,args.limit):
                    print(f"{row['id']} [{row['source_type']}] {row['title']} | {row['url'] or 'no URL'}")
                    print(row['content'][:1000])
        elif args.command=="conversations":
            for row in store.list_conversations():
                print(f"{row['id']} [{row['updated_at']}] {row['title']}")
    finally:
        store.close()

if __name__=="__main__":
    main()
