import threading
import time
import unittest
from unittest.mock import patch

from evo_experiments.monitor import ResourceMonitor


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
        self.assertFalse(monitor.thread.is_alive())

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

        release_late = threading.Event()

        def stopper():
            try:
                with patch("threading.Thread.join", fake_join):
                    monitor.stop()
            except KeyboardInterrupt:
                release_late.set()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        thread.join(timeout=2)
        self.assertTrue(release_late.is_set())
        self.assertFalse(monitor.thread.is_alive())

    def test_runner_cannot_close_database_while_monitor_callback_blocked(self):
        import tempfile
        from pathlib import Path

        from evo_experiments.config import load_config
        from evo_experiments.runner import run_tasks

        temp = tempfile.TemporaryDirectory()
        try:
            db_path = Path(temp.name) / "results.db"
            config_path = Path(temp.name) / "config.toml"
            tasks_path = Path(temp.name) / "tasks.jsonl"
            config_path.write_text(
                f'[server]\nbase_url="http://127.0.0.1:1"\nmodel="fake"\ntimeout_seconds=1\n'
                f'[experiment]\ndatabase="{db_path}"\n'
                f'sample_interval_seconds=0.2\nrepetitions=1\n',
                encoding="utf-8",
            )
            tasks_path.write_text('{"id":"t","prompt":"p"}\n', encoding="utf-8")

            callback_entered = threading.Event()
            callback_release = threading.Event()
            close_called = threading.Event()

            class BlockingMonitor:
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
                    self.stop_event.wait()

                def stop(self):
                    self.stop_event.set()
                    self.thread.join()

            original_close = __import__("evo_experiments.db", fromlist=["ResultsDB"]).ResultsDB.close

            def tracking_close(self_db):
                close_called.set()
                return original_close(self_db)

            def blocking_sample(self_db, experiment_id, sample):
                callback_entered.wait(timeout=1)
                callback_release.wait(timeout=2)

            with patch("evo_experiments.runner.ResourceMonitor", BlockingMonitor), \
                 patch("evo_experiments.runner.stream_chat_completion", return_value={
                     "response": "hello", "finish_reason": "stop",
                     "elapsed_seconds": 1.0, "time_to_first_token_seconds": 0.1,
                     "prompt_tokens": 1, "completion_tokens": 1, "tokens_per_second": 1.0}), \
                 patch("evo_experiments.runner.evaluate_task", return_value=("passed", {"passed": 1, "total": 1, "checks": []})), \
                 patch("evo_experiments.db.ResultsDB.add_sample", blocking_sample), \
                 patch("evo_experiments.db.ResultsDB.close", tracking_close):
                worker = threading.Thread(target=lambda: run_tasks(load_config(config_path), tasks_path), daemon=True)
                worker.start()
                self.assertTrue(callback_entered.wait(timeout=2))
                # Give run_tasks time to finish the model call and reach cleanup.
                time.sleep(0.2)
                self.assertFalse(close_called.is_set(), "database closed while monitor callback was blocked")
                callback_release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(close_called.wait(timeout=2))
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
