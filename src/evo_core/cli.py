import argparse
import sys
from .assistant import EvoAssistant
from .config import load_config
from .provider import ProviderError
from .store import EvoStore

def build_parser():
    parser=argparse.ArgumentParser(prog="evo",description="Evo 4 local-first assistant")
    parser.add_argument("--config",default="config.toml",help="TOML configuration file")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("doctor",help="Check the configured model endpoint")
    chat=sub.add_parser("chat",help="Start an interactive conversation")
    chat.add_argument("--conversation",help="Resume an existing conversation ID")
    mem=sub.add_parser("memory",help="Manage persistent memories")
    ms=mem.add_subparsers(dest="memory_command",required=True)
    add=ms.add_parser("add"); add.add_argument("content"); add.add_argument("--category",default="general")
    add.add_argument("--tag",action="append",default=[]); add.add_argument("--source",default="user")
    add.add_argument("--confidence",type=float,default=1.0)
    search=ms.add_parser("search"); search.add_argument("query"); search.add_argument("--limit",type=int,default=10)
    ms.add_parser("list")
    archive=ms.add_parser("archive"); archive.add_argument("id")
    task=sub.add_parser("task",help="Manage persistent tasks")
    ts=task.add_subparsers(dest="task_command",required=True)
    ta=ts.add_parser("add"); ta.add_argument("title"); ta.add_argument("--description",default="")
    ta.add_argument("--priority",type=int,default=3)
    tl=ts.add_parser("list"); tl.add_argument("--status")
    td=ts.add_parser("status"); td.add_argument("id"); td.add_argument("value",choices=["open","in_progress","blocked","done","cancelled"])
    sub.add_parser("conversations",help="List recent conversations")
    return parser

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
        except ProviderError as exc:
            print(str(exc),file=sys.stderr); raise SystemExit(1)
        finally: assistant.close()
        return
    if args.command=="chat":
        assistant=EvoAssistant(config)
        try:
            cid=args.conversation or assistant.new_conversation()
            print(f"Evo 4 | conversation {cid}\nType /exit to quit, /new to start another conversation.")
            while True:
                try: user_text=input("\nYou> ").strip()
                except (EOFError,KeyboardInterrupt): print(); break
                if not user_text: continue
                if user_text=="/exit": break
                if user_text=="/new":
                    cid=assistant.new_conversation(); print(f"New conversation: {cid}"); continue
                print("\nEvo> ",end="",flush=True)
                try:
                    result=assistant.turn(cid,user_text,on_token=lambda token: print(token,end="",flush=True))
                    print(f"\n[{result['elapsed_seconds']:.1f}s]",flush=True)
                except ProviderError as exc:
                    print(f"\nProvider error: {exc}",file=sys.stderr)
            print(f"Conversation ID: {cid}")
        finally: assistant.close()
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
        elif args.command=="task":
            if args.task_command=="add":
                print(f"Created task: {store.add_task(args.title,args.description,args.priority)}")
            elif args.task_command=="list":
                for row in store.list_tasks(args.status):
                    print(f"{row['id']} [{row['status']} p{row['priority']}] {row['title']}")
            elif args.task_command=="status":
                print("Updated." if store.update_task_status(args.id,args.value) else "Task not found.")
        elif args.command=="conversations":
            for row in store.list_conversations():
                print(f"{row['id']} [{row['updated_at']}] {row['title']}")
    finally: store.close()

if __name__=="__main__":
    main()
