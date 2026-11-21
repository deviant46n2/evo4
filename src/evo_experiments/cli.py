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
REPORT_FIELDS = ("id","started_at","task_id","category","repetition","model","run_label","status",
    "elapsed_seconds","time_to_first_token_seconds","prompt_tokens","completion_tokens",
    "tokens_per_second","finish_reason","seed","evaluation_status","evaluation_details",
    "evaluation_passed","evaluation_total","error")
SUMMARY_FIELDS = ("configuration","model","category","runs","completed","failed","running","truncated","incomplete",
    "unknown","checks_passed","checks_scored","avg_elapsed_seconds","median_elapsed_seconds","stdev_elapsed_seconds",
    "avg_ttft_seconds","median_ttft_seconds","stdev_ttft_seconds","avg_tokens_per_second",
    "median_tokens_per_second","stdev_tokens_per_second","avg_peak_vram_mib","max_peak_vram_mib",
    "avg_gpu_utilization_percent","max_sampled_ram_mib")

def _write_rows(rows, csv_output, fieldnames=()):
    if csv_output:
        names = list(rows[0].keys()) if rows else list(fieldnames)
        writer = csv.DictWriter(sys.stdout, fieldnames=names)
        if names:
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
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
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
                _write_rows([dict(row) for row in db.summary(max(1, args.limit))], args.csv, REPORT_FIELDS)
            else:
                _write_rows([dict(row) for row in db.aggregates()], args.csv, SUMMARY_FIELDS)
        finally:
            db.close()
    elif args.command == "run":
        try:
            ids = run_tasks(config, args.tasks, args.repetitions)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(2)
        print(f"Recorded {len(ids)} runs: {ids}")
        print(f"Database: {config.database}")
        db = ResultsDB(config.database)
        try:
            not_completed = db.count_not_completed(ids)
        finally:
            db.close()
        if not_completed:
            print(f"{not_completed} of {len(ids)} runs were not completed (failed, truncated, incomplete, or unknown); "
                  "inspect `evo-exp report`.", file=sys.stderr)
            raise SystemExit(1)
        print("Inspect report and summary commands for results.")
if __name__ == "__main__":
    main()
