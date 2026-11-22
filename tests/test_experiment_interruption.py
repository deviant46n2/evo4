import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_experiments.config import load_config
from evo_experiments.db import ResultsDB
from evo_experiments.runner import run_tasks

TASKS = '{"id":"t","prompt":"p"}\n'


def write_config(temp, db_path, server_port):
    config = Path(temp) / "config.toml"
    config.write_text(
        f'[server]\nbase_url="http://127.0.0.1:{server_port}"\nmodel="fake-model"\ntimeout_seconds=3\n'
        f'[experiment]\ndatabase="{db_path}"\n'
        f'sample_interval_seconds=0.2\nrepetitions=1\n',
        encoding="utf-8",
    )
    tasks = Path(temp) / "tasks.jsonl"
    tasks.write_text(TASKS, encoding="utf-8")
    return config, tasks


class ExperimentInterruptionTests(unittest.TestCase):
    def test_keyboard_interrupt_from_stream_marks_interrupted_and_reraises(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.stream_chat_completion", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status,finished_at,error FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "interrupted")
            self.assertIsNotNone(row["finished_at"])
            self.assertIn("KeyboardInterrupt", row["error"])

    def test_keyboard_interrupt_during_evaluation_marks_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.stream_chat_completion", return_value={
                    "response": "hello", "finish_reason": "stop",
                    "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                    "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}):
                with patch("evo_experiments.runner.evaluate_task", side_effect=KeyboardInterrupt()):
                    with self.assertRaises(KeyboardInterrupt):
                        run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status,finished_at,error FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "interrupted")
            self.assertIsNotNone(row["finished_at"])
            self.assertIn("KeyboardInterrupt", row["error"])

    def test_keyboard_interrupt_during_monitor_startup_does_not_leave_running(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.ResourceMonitor.start", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status,finished_at,error FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "interrupted")
            self.assertIsNotNone(row["finished_at"])

    def test_ordinary_exception_still_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.stream_chat_completion", side_effect=RuntimeError("boom")):
                run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status,error FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "failed")
            self.assertIn("boom", row["error"])

    def test_successful_completion_remains_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.stream_chat_completion", return_value={
                    "response": "hello", "finish_reason": "stop",
                    "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                    "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}):
                with patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})):
                    run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "completed")

    def test_interrupt_after_successful_commit_does_not_overwrite_result(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            original_stop = __import__("evo_experiments.monitor", fromlist=["ResourceMonitor"]).ResourceMonitor.stop

            def raising_stop(self):
                original_stop(self)
                raise KeyboardInterrupt()

            with patch("evo_experiments.runner.stream_chat_completion", return_value={
                    "response": "hello", "finish_reason": "stop",
                    "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                    "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}):
                with patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})):
                    with patch("evo_experiments.monitor.ResourceMonitor.stop", raising_stop):
                        with self.assertRaises(KeyboardInterrupt):
                            run_tasks(load_config(config), tasks)
            db = ResultsDB(db_path)
            row = db.connection.execute("SELECT status FROM experiments").fetchone()
            db.close()
            self.assertEqual(row["status"], "completed")

    def test_secondary_cleanup_failure_does_not_replace_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config, tasks = write_config(temp, db_path, 1)
            with patch("evo_experiments.runner.stream_chat_completion", side_effect=KeyboardInterrupt()):
                with patch("evo_experiments.runner.ResultsDB.finish_experiment", side_effect=RuntimeError("cleanup failed")):
                    with self.assertRaises(KeyboardInterrupt):
                        run_tasks(load_config(config), tasks)
