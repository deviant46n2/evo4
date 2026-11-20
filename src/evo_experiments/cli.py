import argparse
import csv
import json
import sys
from .client import ModelRequestError, list_models
from .config import load_config
from .db import ResultsDB
from .monitor import sample_nvidia_smi
from .runner import run_tasks
def build_parser():
    parser = argparse.ArgumentParser(prog="evo-exp", description="Evo 4 inference experiment harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hardware", help="Print one GPU/RAM telemetry sample")
    doctor = sub.add_parser("doctor", help="Check local OpenAI-compatible server connectivity")
    doctor.add_argument("--config", default="config.toml")
    init = sub.add_parser("init-db", help="Create the results database")
    init.add_argument("--config", default="config.toml")
    run = sub.add_parser("run", help="Run JSONL tasks against a local OpenAI-compatible endpoint")
    run.add_argument("--config", default="config.toml")
    run.add_argument("--tasks", default="tasks/smoke.jsonl")
    run.add_argument("--repetitions", type=int)
    report = sub.add_parser("report", help="Show recent experiment results")
    report.add_argument("--config", default="config.toml")
    report.add_argument("--limit", type=int, default=20)
    report.add_argument("--csv", action="store_true", help="Write report as CSV to stdout")
    summary = sub.add_parser("summary", help="Aggregate results by configuration label and task category")
    summary.add_argument("--config", default="config.toml")
    summary.add_argument("--csv", action="store_true", help="Write summary as CSV to stdout")
    return parser
def _write_rows(rows, csv_output):
    if csv_output:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    else:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
def main():
    args = build_parser().parse_args()
    if args.command == "hardware":
        print(json.dumps(sample_nvidia_smi(), indent=2))
        return
    config = load_config(args.config)
    if args.command == "doctor":
        try:
            models = list_models(base_url=config.base_url, api_key=config.api_key,
                                 timeout=min(config.timeout_seconds, 10))
        except ModelRequestError as exc:
            print(f"Server check failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
        print(f"Server reachable: {config.base_url}")
        print("Models exposed by server:")
        for model in models:
            print(f"  - {model}")
        if models and config.model not in models:
            print(f"Configured model {config.model!r} is not in the server model list.", file=sys.stderr)
            raise SystemExit(2)
        if not models:
            print("Warning: server returned no model IDs; verify the configured model manually.")
        return
    if args.command in ("init-db", "report", "summary"):
        db = ResultsDB(config.database)
        try:
            if args.command == "init-db":
                print(f"Initialized {config.database}")
            elif args.command == "report":
                _write_rows([dict(row) for row in db.summary(max(1, args.limit))], args.csv)
            else:
                _write_rows([dict(row) for row in db.aggregates()], args.csv)
        finally:
            db.close()
    elif args.command == "run":
        ids = run_tasks(config, args.tasks, args.repetitions)
        print(f"Recorded {len(ids)} runs: {ids}")
        print(f"Database: {config.database}")
        db = ResultsDB(config.database)
        try:
            failed = db.count_failed(ids)
        finally:
            db.close()
        if failed:
            print(f"{failed} of {len(ids)} runs failed; inspect `evo-exp report`.", file=sys.stderr)
            raise SystemExit(1)
        print("Inspect report and summary commands for results.")
if __name__ == "__main__":
    main()
