import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from evo_experiments.scheduler import (
    LEASE_SECONDS, cancel_job, create_job, dispatch_jobs, finish_job,
    initialize_scheduler, list_jobs, start_job,
)


class WorkloadSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize_scheduler(self.db)
        self.now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        self.sample = {
            "gpu_memory_total_mib": 16384,
            "gpu_memory_used_mib": 12000,
            "ram_available_bytes": 12 * 1024**3,
            "ram_used_percent": 55,
            "gpu_temperature_c": 60,
        }

    def tearDown(self):
        self.db.close()

    def job(self, name="background", **overrides):
        values = {"name": name, "kind": "benchmark", "priority": 10,
                  "estimated_vram_mib": 1500, "estimated_ram_mib": 512}
        values.update(overrides)
        return create_job(self.db, values, now=self.now)

    def test_jobs_persist_and_are_ordered_by_priority(self):
        low = self.job("low", priority=5)
        high = self.job("high", priority=80)
        result = list_jobs(self.db)
        self.assertEqual(result["jobs"][0]["id"], high["id"])
        self.assertEqual(result["counts"]["queued"], 2)
        self.assertFalse(result["process_control"])

    def test_dispatch_reserves_only_with_headroom(self):
        job = self.job()
        result = dispatch_jobs(self.db, self.sample, now=self.now)
        self.assertEqual(result["decisions"][0]["decision"], "reserved")
        saved = next(item for item in result["jobs"] if item["id"] == job["id"])
        self.assertEqual(saved["status"], "reserved")
        self.assertIsNotNone(saved["lease_expires_at"])

    def test_unknown_estimates_remain_queued(self):
        job = self.job("unknown", estimated_vram_mib=None)
        result = dispatch_jobs(self.db, self.sample, now=self.now)
        self.assertEqual(result["decisions"][0]["decision"], "unknown")
        saved = next(item for item in result["jobs"] if item["id"] == job["id"])
        self.assertEqual(saved["status"], "queued")

    def test_reserved_jobs_consume_projected_capacity(self):
        self.job("first", priority=20, estimated_vram_mib=1800, estimated_ram_mib=512)
        second = self.job("second", priority=10, estimated_vram_mib=1800, estimated_ram_mib=512)
        result = dispatch_jobs(self.db, self.sample, limit=5, now=self.now)
        by_id = {item["id"]: item for item in result["jobs"]}
        self.assertEqual(by_id[second["id"]]["status"], "queued")
        self.assertIn(by_id[second["id"]]["last_decision"]["decision"], {"defer", "unknown"})

    def test_cpu_only_jobs_reserve_ram_without_gpu_demand(self):
        job = self.job("cpu", kind="cpu", gpu_heavy=False, estimated_vram_mib=None)
        result = dispatch_jobs(self.db, {"ram_available_bytes": 12*1024**3, "ram_used_percent":50}, now=self.now)
        saved = next(item for item in result["jobs"] if item["id"] == job["id"])
        self.assertEqual(saved["status"], "reserved")

    def test_missing_telemetry_never_reserves_background_work(self):
        job = self.job()
        result = dispatch_jobs(self.db, {}, now=self.now)
        saved = next(item for item in result["jobs"] if item["id"] == job["id"])
        self.assertEqual(saved["status"], "queued")
        self.assertEqual(result["decisions"][0]["decision"], "unknown")

    def test_reservation_expires_back_to_queue(self):
        job = self.job()
        dispatch_jobs(self.db, self.sample, now=self.now)
        later = self.now + timedelta(seconds=LEASE_SECONDS + 1)
        result = dispatch_jobs(self.db, self.sample, now=later)
        saved = next(item for item in result["jobs"] if item["id"] == job["id"])
        self.assertEqual(result["expired_reservations"], 1)
        self.assertEqual(saved["status"], "reserved")
        self.assertEqual(result["decisions"][0]["decision"], "reserved")

    def test_queue_refresh_reaps_expired_reservations(self):
        job=self.job()
        dispatch_jobs(self.db,self.sample,now=self.now)
        later=self.now+timedelta(seconds=LEASE_SECONDS+1)
        with patch("evo_experiments.scheduler._now",return_value=later):
            saved=next(item for item in list_jobs(self.db)["jobs"] if item["id"]==job["id"])
        self.assertEqual(saved["status"],"queued")
        self.assertIsNone(saved["lease_expires_at"])

    def test_start_finish_lifecycle_releases_reservation(self):
        job = self.job()
        dispatch_jobs(self.db, self.sample, now=self.now)
        running = start_job(self.db, job["id"], now=self.now)
        self.assertEqual(running["status"], "running")
        finished = finish_job(self.db, job["id"], "completed", "External workload exited normally", now=self.now)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(list_jobs(self.db)["counts"]["completed"], 1)

    def test_cancel_only_queued_or_reserved_and_never_stops_running_process(self):
        queued = self.job("queued")
        self.assertEqual(cancel_job(self.db, queued["id"], now=self.now)["status"], "cancelled")
        running = self.job("running")
        dispatch_jobs(self.db, self.sample, now=self.now)
        start_job(self.db, running["id"], now=self.now)
        with self.assertRaisesRegex(ValueError, "never stopped"):
            cancel_job(self.db, running["id"], now=self.now)

    def test_expired_reservation_cannot_be_started(self):
        job = self.job()
        dispatch_jobs(self.db, self.sample, now=self.now)
        with self.assertRaisesRegex(ValueError, "not currently reserved"):
            start_job(self.db, job["id"], now=self.now + timedelta(seconds=LEASE_SECONDS + 1))

    def test_invalid_job_fields_rejected(self):
        with self.assertRaises(ValueError):
            create_job(self.db, {"name":"", "priority":10})
        with self.assertRaises(ValueError):
            create_job(self.db, {"name":"bad", "priority":101})
        with self.assertRaises(ValueError):
            create_job(self.db, {"name":"bad", "gpu_heavy":"yes"})


    def test_database_reopen_preserves_queue_and_running_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"scheduler.sqlite3"
            db=sqlite3.connect(path);db.row_factory=sqlite3.Row;initialize_scheduler(db)
            job=create_job(db,{"name":"persistent","kind":"cpu","estimated_ram_mib":256},now=self.now)
            dispatch_jobs(db,{"ram_available_bytes":8*1024**3,"ram_used_percent":40},now=self.now)
            start_job(db,job["id"],now=self.now)
            db.close()
            reopened=sqlite3.connect(path);reopened.row_factory=sqlite3.Row
            initialize_scheduler(reopened)
            saved=list_jobs(reopened)["jobs"][0]
            self.assertEqual(saved["id"],job["id"])
            self.assertEqual(saved["status"],"running")
            reopened.close()

    def test_rejected_lifecycle_transition_does_not_leave_open_transaction(self):
        queued=self.job("queued")
        with self.assertRaises(ValueError):
            finish_job(self.db,queued["id"],"completed",now=self.now)
        self.assertFalse(self.db.in_transaction)
        with self.assertRaises(ValueError):
            cancel_job(self.db,"missing-job",now=self.now)
        self.assertFalse(self.db.in_transaction)
        self.job("after rejected transitions")
        self.assertFalse(self.db.in_transaction)

    def test_running_jobs_cannot_be_marked_cancelled(self):
        job = self.job()
        dispatch_jobs(self.db, self.sample, now=self.now)
        start_job(self.db, job["id"], now=self.now)
        with self.assertRaisesRegex(ValueError, "completed or failed"):
            finish_job(self.db, job["id"], "cancelled")


if __name__ == "__main__":
    unittest.main()
