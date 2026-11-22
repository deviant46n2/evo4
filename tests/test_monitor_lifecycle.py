import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_experiments.config import load_config
from evo_experiments.monitor import ResourceMonitor
from evo_experiments.runner import run_tasks


def _run_and_ignore(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except Exception:
        pass




class MonitorLifecycleTests(unittest.TestCase):
    def test_stop_waits_for_in_flight_callback(self):
        started = threading.Event()
        release = threading.Event()
        stopped = threading.Event()

        def callback(sample):
            started.set()
            release.wait(timeout=2)

        monitor = ResourceMonitor(0.01, callback)
        monitor.start()
        self.assertTrue(started.wait(timeout=1))

        def stopper():
            monitor.stop()
            stopped.set()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        self.assertFalse(stopped.wait(0.2), "stop() returned while callback was still blocked")
        release.set()
        thread.join(timeout=2)
        self.assertTrue(stopped.is_set())

    def test_interrupted_join_does_not_return_early(self):
        started = threading.Event()
        release = threading.Event()

        def callback(sample):
            started.set()
            release.wait(timeout=2)

        monitor = ResourceMonitor(0.01, callback)
        monitor.start()
        self.assertTrue(started.wait(timeout=1))

        original_join = threading.Thread.join
        calls = {"count": 0}

        def fake_join(self_thread, timeout=None):
            if self_thread is monitor.thread and calls["count"] == 0:
                calls["count"] += 1
                release.set()
                raise KeyboardInterrupt()
            return original_join(self_thread, timeout)

        released = threading.Event()

        def stopper():
            try:
                with patch("threading.Thread.join", fake_join):
                    monitor.stop()
            except KeyboardInterrupt:
                released.set()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        thread.join(timeout=2)
        self.assertTrue(released.is_set())

    def test_real_monitor_callback_blocks_database_close(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config_path = Path(temp) / "config.toml"
            tasks_path = Path(temp) / "tasks.jsonl"
            config_path.write_text(
                '[server]\nbase_url="http://127.0.0.1:1"\nmodel="fake"\ntimeout_seconds=1\n'
                f'[experiment]\ndatabase="{db_path}"\n'
                'sample_interval_seconds=0.05\nrepetitions=1\n',
                encoding="utf-8",
            )
            tasks_path.write_text('{"id":"t","prompt":"p"}\n', encoding="utf-8")

            callback_entered = threading.Event()
            callback_release = threading.Event()
            close_called = threading.Event()
            shutdown_entered = threading.Event()

            original_add_sample = __import__("evo_experiments.db", fromlist=["ResultsDB"]).ResultsDB.add_sample
            original_close = __import__("evo_experiments.db", fromlist=["ResultsDB"]).ResultsDB.close
            original_stop = ResourceMonitor.stop

            def blocking_add_sample(self_db, experiment_id, sample):
                callback_entered.set()
                callback_release.wait(timeout=2)
                return original_add_sample(self_db, experiment_id, sample)

            def tracking_close(self_db):
                close_called.set()
                return original_close(self_db)

            def tracking_stop(self_monitor):
                shutdown_entered.set()
                return original_stop(self_monitor)

            with patch("evo_experiments.runner.stream_chat_completion", return_value={
                    "response": "hello", "finish_reason": "stop",
                    "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                    "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}), \
                 patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})), \
                 patch("evo_experiments.db.ResultsDB.add_sample", blocking_add_sample), \
                 patch("evo_experiments.db.ResultsDB.close", tracking_close), \
                 patch("evo_experiments.runner.ResourceMonitor.stop", tracking_stop):
                worker = threading.Thread(target=lambda: run_tasks(load_config(config_path), tasks_path), daemon=True)
                worker.start()
                self.assertTrue(callback_entered.wait(timeout=2))
                self.assertTrue(shutdown_entered.wait(timeout=2), "runner did not enter monitor shutdown")
                self.assertFalse(close_called.is_set(), "database closed before callback exited")
                callback_release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(close_called.wait(timeout=2))


class MonitorShutdownFailureTests(unittest.TestCase):
    def test_runner_waits_for_worker_when_monitor_stop_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config_path = Path(temp) / "config.toml"
            tasks_path = Path(temp) / "tasks.jsonl"
            config_path.write_text(
                '[server]\nbase_url="http://127.0.0.1:1"\nmodel="fake"\ntimeout_seconds=1\n'
                f'[experiment]\ndatabase="{db_path}"\n'
                'sample_interval_seconds=0.2\nrepetitions=1\n',
                encoding="utf-8",
            )
            tasks_path.write_text('{"id":"t","prompt":"p"}\n', encoding="utf-8")

            callback_entered = threading.Event()
            callback_release = threading.Event()
            close_called = threading.Event()
            guard_entered = threading.Event()

            class FailingStopMonitor:
                def __init__(self, interval, callback):
                    self.interval = interval
                    self.callback = callback
                    self.stop_event = threading.Event()
                    self.thread = None

                def start(self):
                    self.thread = threading.Thread(target=self._run, daemon=True)
                    self.thread.start()

                def _run(self):
                    callback_entered.set()
                    self.callback({"peak_vram_mib": 1})
                    callback_release.wait(timeout=2)

                def stop(self):
                    raise RuntimeError("stop failed")

            original_close = __import__("evo_experiments.db", fromlist=["ResultsDB"]).ResultsDB.close

            def tracking_close(self_db):
                close_called.set()
                return original_close(self_db)

            def blocking_sample(self_db, experiment_id, sample):
                callback_entered.wait(timeout=1)
                callback_release.wait(timeout=2)

            original_join = threading.Thread.join

            def join_guard(self_thread, timeout=None):
                if callback_entered.is_set() and not callback_release.is_set():
                    guard_entered.set()
                return original_join(self_thread, timeout)

            with patch("evo_experiments.runner.ResourceMonitor", FailingStopMonitor), \
                 patch("threading.Thread.join", join_guard), \
                 patch("evo_experiments.runner.stream_chat_completion", return_value={
                     "response": "hello", "finish_reason": "stop",
                     "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                     "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}), \
                 patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})), \
                 patch("evo_experiments.db.ResultsDB.add_sample", blocking_sample), \
                 patch("evo_experiments.db.ResultsDB.close", tracking_close):
                worker = threading.Thread(target=lambda: _run_and_ignore(run_tasks, load_config(config_path), tasks_path), daemon=True)
                worker.start()
                self.assertTrue(callback_entered.wait(timeout=2))
                self.assertTrue(guard_entered.wait(timeout=2), "runner did not enter independent join guard")
                self.assertFalse(callback_release.is_set())
                self.assertFalse(close_called.is_set(), "database closed while worker was alive")
                callback_release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(close_called.wait(timeout=2))


class MonitorUnexpectedJoinTests(unittest.TestCase):
    def test_unexpected_join_failure_does_not_close_database_while_worker_alive(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "results.db"
            config_path = Path(temp) / "config.toml"
            tasks_path = Path(temp) / "tasks.jsonl"
            config_path.write_text(
                '[server]\nbase_url="http://127.0.0.1:1"\nmodel="fake"\ntimeout_seconds=1\n'
                f'[experiment]\ndatabase="{db_path}"\n'
                'sample_interval_seconds=0.2\nrepetitions=1\n',
                encoding="utf-8",
            )
            tasks_path.write_text('{"id":"t","prompt":"p"}\n', encoding="utf-8")

            callback_entered = threading.Event()
            callback_release = threading.Event()
            close_called = threading.Event()
            join_failed = threading.Event()

            class FailingJoinMonitor:
                def __init__(self, interval, callback):
                    self.interval = interval
                    self.callback = callback
                    self.stop_event = threading.Event()
                    self.thread = None

                def start(self):
                    self.thread = threading.Thread(target=self._run, daemon=True)
                    self.thread.start()

                def _run(self):
                    callback_entered.set()
                    self.callback({"peak_vram_mib": 1})
                    callback_release.wait(timeout=2)

                def stop(self):
                    self.stop_event.set()

            original_join = threading.Thread.join
            calls = {"count": 0}

            def fake_join(self_thread, timeout=None):
                if calls["count"] == 0:
                    calls["count"] += 1
                    join_failed.set()
                    raise RuntimeError("join failed")
                return original_join(self_thread, timeout)

            original_close = __import__("evo_experiments.db", fromlist=["ResultsDB"]).ResultsDB.close

            def tracking_close(self_db):
                close_called.set()
                return original_close(self_db)

            def blocking_sample(self_db, experiment_id, sample):
                callback_entered.wait(timeout=1)
                callback_release.wait(timeout=2)

            with patch("evo_experiments.runner.ResourceMonitor", FailingJoinMonitor), \
                 patch("threading.Thread.join", fake_join), \
                 patch("evo_experiments.runner.stream_chat_completion", return_value={
                     "response": "hello", "finish_reason": "stop",
                     "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                     "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}), \
                 patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})), \
                 patch("evo_experiments.db.ResultsDB.add_sample", blocking_sample), \
                 patch("evo_experiments.db.ResultsDB.close", tracking_close):
                worker = threading.Thread(target=lambda: _run_and_ignore(run_tasks, load_config(config_path), tasks_path), daemon=True)
                worker.start()
                self.assertTrue(callback_entered.wait(timeout=2))
                self.assertTrue(join_failed.wait(timeout=2), "join failure was not observed")
                self.assertFalse(callback_release.is_set(), "worker was released before the guard waited")
                self.assertFalse(close_called.is_set(), "database closed while worker was alive")
                callback_release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(close_called.wait(timeout=2))


if __name__ == "__main__":
    unittest.main()
