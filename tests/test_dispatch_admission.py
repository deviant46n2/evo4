import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from evo_core.dispatch_admission import (
    AdmissionError,
    AdmissionPolicy,
    ProviderBudget,
    ResourceDemand,
    derive_resource_demand,
    evaluate_resource_admission,
    acknowledge_abandoned_dispatch_recovery,
    finalize_invocation,
    get_invocation_lifecycle,
    heartbeat_dispatch_lease,
    initialize_invocation_lifecycle,
    mark_invocation_running,
    mark_stale_dispatch_leases_abandoned,
)
from evo_core.store import EvoStore


def telemetry(**overrides):
    value = {
        "sampled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ram_available_bytes": 8 * 1024 * 1024 * 1024,
        "cpu_logical_cores": 8,
        "load_average_1m": 1.0,
        "cpu_utilization_percent": 30.0,
        "gpu_available": False,
        "gpu_memory_used_mib": None,
        "gpu_memory_total_mib": None,
        "gpu_temperature_c": None,
    }
    value.update(overrides)
    return value


class ResourceAdmissionTests(unittest.TestCase):
    def test_remote_code_owned_demand_is_admitted_without_gpu_telemetry(self):
        result = evaluate_resource_admission(
            telemetry(), ResourceDemand("remote_service", 0.05, 64)
        )
        self.assertEqual(result["decision"], "admitted")

    def test_local_process_demand_is_admitted_without_gpu_telemetry(self):
        result = evaluate_resource_admission(
            telemetry(), ResourceDemand("local_process", 0.10, 64)
        )
        self.assertEqual(result["decision"], "admitted")

    def test_stale_sample_fails_closed_as_unknown(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=11)).isoformat().replace("+00:00", "Z")
        result = evaluate_resource_admission(
            telemetry(sampled_at=old),
            ResourceDemand("remote_service", 0.05, 64),
        )
        self.assertEqual((result["decision"], result["reason"]), ("unknown", "telemetry_stale"))

    def test_future_sample_fails_closed(self):
        future = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        result = evaluate_resource_admission(
            telemetry(sampled_at=future),
            ResourceDemand("remote_service", 0.05, 64),
        )
        self.assertEqual(result["decision"], "unknown")

    def test_missing_required_cpu_or_ram_dimension_fails_closed(self):
        result = evaluate_resource_admission(
            telemetry(ram_available_bytes=None),
            ResourceDemand("remote_service", 0.05, 64),
        )
        self.assertEqual(result["decision"], "unknown")

    def test_cpu_pressure_defers_even_when_headroom_exists(self):
        result = evaluate_resource_admission(
            telemetry(cpu_utilization_percent=90.0),
            ResourceDemand("remote_service", 0.05, 64),
        )
        self.assertEqual((result["decision"], result["reason"]), ("deferred", "cpu_pressure"))

    def test_ram_reserve_is_protected(self):
        result = evaluate_resource_admission(
            telemetry(ram_available_bytes=2 * 1024 * 1024 * 1024 + 32 * 1024 * 1024),
            ResourceDemand("remote_service", 0.05, 64),
        )
        self.assertEqual(result["reason"], "insufficient_ram_headroom")

    def test_gpu_demand_requires_gpu_telemetry(self):
        demand = ResourceDemand(
            "local_endpoint", 1.0, 1024, gpu_vram_mib=2048,
            compute_mode="gpu", memory_mode="persistent_incremental",
        )
        result = evaluate_resource_admission(telemetry(), demand)
        self.assertEqual(result["reason"], "required_gpu_telemetry_unavailable")

    def test_gpu_temperature_ceiling_defers(self):
        demand = ResourceDemand(
            "local_endpoint", 1.0, 1024, gpu_vram_mib=2048,
            compute_mode="gpu", memory_mode="persistent_incremental",
        )
        result = evaluate_resource_admission(
            telemetry(gpu_available=True, gpu_memory_used_mib=1000,
                      gpu_memory_total_mib=16000, gpu_temperature_c=85.0),
            demand,
        )
        self.assertEqual((result["decision"], result["reason"]), ("deferred", "gpu_temperature_ceiling"))

    def test_gpu_headroom_and_reserve_are_enforced(self):
        demand = ResourceDemand(
            "local_endpoint", 1.0, 1024, gpu_vram_mib=2000,
            compute_mode="gpu", memory_mode="cold_load",
        )
        result = evaluate_resource_admission(
            telemetry(gpu_available=True, gpu_memory_used_mib=15000,
                      gpu_memory_total_mib=16000, gpu_temperature_c=70.0),
            demand,
        )
        self.assertEqual(result["reason"], "insufficient_gpu_vram_headroom")

    def test_cpu_only_local_profile_does_not_require_gpu(self):
        demand = ResourceDemand(
            "local_endpoint", 1.0, 1024, compute_mode="cpu",
            memory_mode="cold_load",
        )
        result = evaluate_resource_admission(telemetry(), demand)
        self.assertEqual(result["decision"], "admitted")

    def test_invalid_local_gpu_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            ResourceDemand(
                "local_endpoint", 1.0, 1024, compute_mode="gpu",
                memory_mode="persistent_incremental",
            )

    def test_provider_budget_requires_bounded_positive_integer_limits(self):
        with self.assertRaises(ValueError):
            ProviderBudget("integration-1", 0, 1024, 4096)
        with self.assertRaises(ValueError):
            ProviderBudget("integration-1", 20, 10_000_001, 20_000_000)
        budget = ProviderBudget("integration-1", 20, 4096, 32768)
        self.assertEqual(budget.maximum_requests_per_utc_day, 20)

    def test_resource_and_policy_bounds_reject_unusable_or_extreme_values(self):
        with self.assertRaises(ValueError):
            AdmissionPolicy(cpu_pressure_percent=0)
        with self.assertRaises(ValueError):
            ResourceDemand("remote_service", 4097, 64)
        with self.assertRaises(ValueError):
            ResourceDemand("remote_service", 1, 16_777_217)


class ResourceDeclarationTests(unittest.TestCase):
    def test_remote_endpoint_uses_code_owned_cpu_ram_declaration(self):
        runtime = SimpleNamespace(
            participant=SimpleNamespace(adapter_id="openai_compatible_chat"),
            bound_participant=SimpleNamespace(endpoint="https://api.example.com/v1"),
        )
        demand = derive_resource_demand(runtime)
        self.assertEqual(demand, ResourceDemand("remote_service", 0.05, 64.0))

    def test_loopback_endpoint_requires_operator_profile(self):
        runtime = SimpleNamespace(
            participant=SimpleNamespace(adapter_id="openai_compatible_chat"),
            bound_participant=SimpleNamespace(endpoint="http://127.0.0.1:18997/v1"),
        )
        with self.assertRaises(AdmissionError):
            derive_resource_demand(runtime)

    def test_loopback_endpoint_uses_explicit_profile(self):
        runtime = SimpleNamespace(
            participant=SimpleNamespace(adapter_id="openai_compatible_chat"),
            bound_participant=SimpleNamespace(endpoint="http://127.0.0.1:18997/v1"),
        )
        demand = derive_resource_demand(runtime, local_profile={
            "compute_mode": "gpu", "cpu_cores": 2.0, "ram_mib": 1024,
            "gpu_vram_mib": 3072, "memory_mode": "persistent_incremental",
        })
        self.assertEqual(demand.locality, "local_endpoint")
        self.assertEqual(demand.gpu_vram_mib, 3072)

    def test_deterministic_verifier_has_code_owned_declaration(self):
        runtime = SimpleNamespace(
            participant=SimpleNamespace(adapter_id="evo_deterministic_verifier"),
            bound_participant=object(),
        )
        self.assertEqual(
            derive_resource_demand(runtime),
            ResourceDemand("local_process", 0.10, 64.0),
        )


class InvocationLifecycleTransitionTests(unittest.TestCase):
    def _store_with_invocation(self, *, heartbeat_age_seconds=0, status="running"):
        now = datetime.now(timezone.utc)
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        connection.execute("CREATE TABLE runtime_invocation_snapshots(invocation_id TEXT PRIMARY KEY)")
        store = SimpleNamespace(db=connection, lock=threading.RLock())
        initialize_invocation_lifecycle(store)
        connection.execute("INSERT INTO runtime_invocation_snapshots(invocation_id) VALUES('inv-1')")
        connection.execute(
            """INSERT INTO participant_invocations(
                invocation_id,workspace_id,project_id,participant_id,integration_id,adapter_id,
                configuration_id,revision_id,revision_hash,snapshot_hash,status,decision_json,
                deadline_utc,requested_output_tokens,budget_day_utc,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("inv-1","ws-1","project-1","participant-1","integration-1",
             "openai_compatible_chat","config-1","revision-1","revhash","snaphash",
             status,json.dumps({"decision":"admitted"}),
             (now + timedelta(minutes=2)).isoformat().replace("+00:00","Z"),
             100,"2026-11-25",now.isoformat().replace("+00:00","Z"),
             now.isoformat().replace("+00:00","Z")),
        )
        heartbeat = (now - timedelta(seconds=heartbeat_age_seconds)).isoformat().replace("+00:00","Z")
        connection.execute(
            """INSERT INTO dispatch_leases(
                lease_key,invocation_id,owner_id,state,acquired_at,heartbeat_at,deadline_utc
            ) VALUES(?,?,?,?,?,?,?)""",
            ("global_provider_dispatch","inv-1","owner-1","active",heartbeat,heartbeat,
             (now + timedelta(minutes=2)).isoformat().replace("+00:00","Z")),
        )
        connection.execute(
            """INSERT INTO provider_budget_usage(
                integration_id,budget_day_utc,requests_reserved,output_tokens_reserved,output_tokens_used
            ) VALUES(?,?,?,?,?)""",
            ("integration-1","2026-11-25",1,100,0),
        )
        connection.commit()
        return store, now

    def test_running_transition_requires_active_provider_lease(self):
        store, _ = self._store_with_invocation()
        try:
            store.db.execute("UPDATE participant_invocations SET status='admitted' WHERE invocation_id='inv-1'")
            store.db.execute("DELETE FROM dispatch_leases WHERE invocation_id='inv-1'")
            store.db.commit()
            self.assertFalse(mark_invocation_running(store, "inv-1"))
        finally:
            store.db.close()

    def test_heartbeat_refreshes_only_an_active_unexpired_lease(self):
        store, _ = self._store_with_invocation()
        try:
            self.assertTrue(heartbeat_dispatch_lease(store, "inv-1"))
            store.db.execute("UPDATE dispatch_leases SET state='abandoned' WHERE invocation_id='inv-1'")
            store.db.commit()
            self.assertFalse(heartbeat_dispatch_lease(store, "inv-1"))
        finally:
            store.db.close()

    def test_unsettled_cancellation_abandons_lease_until_operator_acknowledges_idle(self):
        store, _ = self._store_with_invocation()
        try:
            self.assertTrue(finalize_invocation(store, "inv-1", "cancelled", provider_settled=False))
            lease = store.db.execute("SELECT state FROM dispatch_leases WHERE invocation_id='inv-1'").fetchone()
            self.assertEqual(lease["state"], "abandoned")
            with self.assertRaises(AdmissionError):
                acknowledge_abandoned_dispatch_recovery(
                    store, actor="operator", reason="not checked", endpoint_idle_confirmed=False
                )
            result = acknowledge_abandoned_dispatch_recovery(
                store, actor="operator", reason="Verified inference server is idle",
                endpoint_idle_confirmed=True,
            )
            self.assertTrue(result["released"])
            self.assertIsNone(store.db.execute("SELECT 1 FROM dispatch_leases").fetchone())
            lifecycle = get_invocation_lifecycle(store, "inv-1")
            self.assertEqual(lifecycle["status"], "cancelled")
            self.assertIn("abandoned_lease_operator_recovery", [event["event_type"] for event in lifecycle["events"]])
        finally:
            store.db.close()

    def test_stale_lease_is_marked_abandoned_but_never_auto_released(self):
        store, now = self._store_with_invocation(heartbeat_age_seconds=30)
        try:
            self.assertEqual(
                mark_stale_dispatch_leases_abandoned(store, stale_after_seconds=15, now=now),
                1,
            )
            lease = store.db.execute("SELECT state FROM dispatch_leases WHERE invocation_id='inv-1'").fetchone()
            self.assertEqual(lease["state"], "abandoned")
            self.assertIsNotNone(store.db.execute("SELECT 1 FROM dispatch_leases").fetchone())
        finally:
            store.db.close()

    def test_admitted_invocation_cannot_be_finalized_as_success(self):
        store, _ = self._store_with_invocation(status="admitted")
        try:
            self.assertFalse(finalize_invocation(store, "inv-1", "succeeded", provider_settled=True))
            row = store.db.execute(
                "SELECT status FROM participant_invocations WHERE invocation_id='inv-1'"
            ).fetchone()
            self.assertEqual(row["status"], "admitted")
        finally:
            store.db.close()

    def test_admitted_invocation_can_only_be_cancelled_before_start_and_releases_reservations(self):
        store, _ = self._store_with_invocation(status="admitted")
        try:
            self.assertTrue(finalize_invocation(store, "inv-1", "cancelled"))
            self.assertIsNone(store.db.execute("SELECT 1 FROM dispatch_leases").fetchone())
            budget = store.db.execute(
                "SELECT requests_reserved,output_tokens_reserved FROM provider_budget_usage"
            ).fetchone()
            self.assertEqual((budget["requests_reserved"], budget["output_tokens_reserved"]), (0, 0))
            self.assertFalse(mark_invocation_running(store, "inv-1"))
        finally:
            store.db.close()

    def test_experiment_cancelled_after_admission_cannot_cross_worker_start(self):
        store, _ = self._store_with_invocation(status="admitted")
        try:
            store.db.execute(
                "CREATE TABLE cooperative_experiments(experiment_id TEXT PRIMARY KEY,status TEXT NOT NULL)"
            )
            store.db.execute(
                """CREATE TABLE cooperative_experiment_usage_reservations(
                    invocation_id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL
                )"""
            )
            store.db.execute(
                "INSERT INTO cooperative_experiments(experiment_id,status) VALUES('exp-1','cancelled')"
            )
            store.db.execute(
                "INSERT INTO cooperative_experiment_usage_reservations(invocation_id,experiment_id) VALUES('inv-1','exp-1')"
            )
            store.db.commit()
            self.assertFalse(mark_invocation_running(store, "inv-1"))
            row = store.db.execute(
                "SELECT status FROM participant_invocations WHERE invocation_id='inv-1'"
            ).fetchone()
            self.assertEqual(row["status"], "admitted")
        finally:
            store.db.close()

    def test_running_experiment_allows_reserved_invocation_to_start(self):
        store, _ = self._store_with_invocation(status="admitted")
        try:
            store.db.execute(
                "CREATE TABLE cooperative_experiments(experiment_id TEXT PRIMARY KEY,status TEXT NOT NULL)"
            )
            store.db.execute(
                """CREATE TABLE cooperative_experiment_usage_reservations(
                    invocation_id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL
                )"""
            )
            store.db.execute(
                "INSERT INTO cooperative_experiments(experiment_id,status) VALUES('exp-1','running')"
            )
            store.db.execute(
                "INSERT INTO cooperative_experiment_usage_reservations(invocation_id,experiment_id) VALUES('inv-1','exp-1')"
            )
            store.db.commit()
            self.assertTrue(mark_invocation_running(store, "inv-1"))
        finally:
            store.db.close()

    def test_concurrent_worker_start_transition_has_single_winner(self):
        store, _ = self._store_with_invocation(status="admitted")
        barrier = threading.Barrier(3)
        try:
            def start():
                barrier.wait()
                return mark_invocation_running(store, "inv-1")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(start) for _ in range(2)]
                barrier.wait()
                results = [future.result() for future in futures]
            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 1)
        finally:
            store.db.close()

    def test_provider_settled_after_stale_heartbeat_can_release_lease(self):
        store, now = self._store_with_invocation(heartbeat_age_seconds=30)
        try:
            mark_stale_dispatch_leases_abandoned(store, stale_after_seconds=15, now=now)
            self.assertTrue(finalize_invocation(store, "inv-1", "succeeded", provider_settled=True))
            self.assertIsNone(store.db.execute("SELECT 1 FROM dispatch_leases").fetchone())
        finally:
            store.db.close()


class InvocationLifecycleSchemaTests(unittest.TestCase):
    def test_migration_is_idempotent_and_installs_durable_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EvoStore(Path(directory) / "evo.sqlite3")
            try:
                self.assertTrue(initialize_invocation_lifecycle(store))
                self.assertTrue(initialize_invocation_lifecycle(store))
                tables = {
                    row["name"] for row in store.db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertTrue({
                    "participant_invocations", "provider_budget_usage",
                    "dispatch_leases", "invocation_lifecycle_events",
                }.issubset(tables))
                migration = store.db.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE name='participant_invocation_lifecycle_v1'"
                ).fetchone()[0]
                self.assertEqual(migration, 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
