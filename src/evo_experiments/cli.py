import argparse
import json
from .config import load_config
from .db import ResultsDB
from .monitor import sample_nvidia_smi
from .runner import run_tasks

def build_parser():
    parser = argparse.ArgumentParser(prog="evo-exp", description="Evo 4 inference experiment harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hardware", help="Print one GPU/RAM telemetry sample")
    init = sub.add_parser("init-db", help="Create the results database")
    init.add_argument("--config", default="config.toml")
    run = sub.add_parser("run", help="Run JSONL tasks against a local OpenAI-compatible endpoint")
    run.add_argument("--config", default="config.toml")
    run.add_argument("--tasks", default="tasks/smoke.jsonl")
    run.add_argument("--repetitions", type=int)
    report = sub.add_parser("report", help="Show recent experiment results")
    report.add_argument("--config", default="config.toml")
    report.add_argument("--limit", type=int, default=20)
    return parser

def main():
    args = build_parser().parse_args()
    if args.command == "hardware":
        print(json.dumps(sample_nvidia_smi(), indent=2))
        return
    config = load_config(args.config)
    if args.command == "init-db":
        db = ResultsDB(config.database)
        db.close()
        print(f"Initialized {config.database}")
    elif args.command == "run":
        ids = run_tasks(config, args.tasks, args.repetitions)
        print(f"Recorded {len(ids)} runs: {ids}")
        print(f"Database: {config.database}")
        print("Inspect report output for completed and failed runs.")
    elif args.command == "report":
        db = ResultsDB(config.database)
        try:
            for row in db.summary(max(1, args.limit)):
                print(json.dumps(dict(row), ensure_ascii=False))
        finally:
            db.close()

if __name__ == "__main__":
    main()
