import tempfile
import unittest
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
    initialize_invocation_lifecycle,
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

    def test_provider_budget_requires_positive_integer_limits(self):
        with self.assertRaises(ValueError):
            ProviderBudget(0, 1024, 4096)
        budget = ProviderBudget(20, 4096, 32768)
        self.assertEqual(budget.maximum_requests_per_utc_day, 20)


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
