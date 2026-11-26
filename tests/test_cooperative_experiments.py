import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.config import EvoConfig
from evo_core.cooperative_experiments import (
    ExperimentError, create_experiment, get_experiment, initialize_cooperative_experiments,
    list_experiment_events, transition_experiment,
)
from evo_core.cooperative_handoffs import initialize_cooperative_handoffs
from evo_core.dispatch_admission import initialize_invocation_lifecycle
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.runtime_binding import build_workspace_runtime
from evo_core.runtime_invocation_snapshots import initialize_runtime_invocation_snapshots
from evo_core.store import EvoStore
from evo_core.workspaces import create_workspace


def definition():
    return {
        "schema_version": 2,
        "components": {
            "primary": {
                "type": "model", "component_version": 1,
                "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
                "settings": {"endpoint": "http://127.0.0.1:18997/v1", "model": "primary", "timeout_seconds": 30},
            },
            "secondary": {
                "type": "model", "component_version": 1,
                "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
                "settings": {"endpoint": "http://127.0.0.1:18997/v1", "model": "secondary", "timeout_seconds": 30},
            },
            "assistant": {
                "type": "assistant_runtime", "component_version": 1,
                "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                "settings": {
                    "model_component": "primary", "additional_model_components": ["secondary"],
                    "persona_prompt": "", "max_output_tokens": 256, "temperature": 0.2,
                    "context_window_tokens": 8192, "history_messages": 4,
                    "max_history_chars": 4000, "memory_limit": 2,
                },
            },
            "policy": {
                "type": "command_policy", "component_version": 1,
                "adapter": {"id": "evo_command_policy", "contract_version": 1},
                "settings": {"allowed_commands": [["python", "-m", "unittest"]]},
            },
        },
        "entrypoints": {"assistant": "assistant"},
    }


class CooperativeExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "experiments.sqlite3")
        initialize_platform_registry(self.store)
        project = register_project(self.store, "Experiment project")
        checkout_path = self.root / "checkout"
        checkout_path.mkdir()
        checkout = register_checkout(self.store, project["project_id"], checkout_path)
        created = create_configuration(self.store, definition(), name="Experiment config")
        self.workspace = create_workspace(
            self.store, "Experiment workspace", project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        config = EvoConfig(
            base_url="http://127.0.0.1:18997/v1", api_key="never-persist-this",
            model="global", timeout_seconds=30, database=self.root / "experiments.sqlite3",
            max_tokens=256, temperature=0.2, system_prompt="policy", memory_limit=2,
            history_messages=4, workspace_root=self.root, allowed_commands=(("python",),),
            max_history_chars=4000, context_window_tokens=8192,
        )
        initialize_runtime_invocation_snapshots(self.store)
        initialize_invocation_lifecycle(self.store)
        initialize_cooperative_handoffs(self.store)
        initialize_cooperative_experiments(self.store)
        self.runtime = build_workspace_runtime(self.store, config, self.workspace["workspace_id"])

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def create(self, condition="C"):
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        return create_experiment(
            self.store, self.runtime, task_statement="Add a bounded validator.",
            acceptance_criteria=["tests-pass", "no-regressions"],
            verification_commands=[["python", "-m", "unittest", "tests.test_example"]],
            condition=condition, input_token_ceiling=12000, output_token_ceiling=4000,
            wall_clock_seconds=900, deadline_utc=deadline,
        )

    def test_freezes_runtime_revision_participants_and_budgets(self):
        record = self.create()
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["revision_hash"], self.runtime.revision_hash)
        self.assertEqual(len(record["spec"]["participants"]), 2)
        self.assertEqual(record["spec"]["execution_policy"], "sequential_global_provider_lease")
        self.assertFalse(record["spec"]["automatic_resume"])
        self.assertEqual(record["spec"]["budgets"]["input_token_ceiling"], 12000)

    def test_cooperation_condition_requires_two_model_participants(self):
        runtime = replace(
            self.runtime, additional_participants=(),
            additional_participant_bindings=(), additional_participant_provenance=(),
        )
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(ExperimentError):
            create_experiment(
                self.store, runtime, task_statement="Task", acceptance_criteria=["C1"],
                verification_commands=[["python", "-m", "unittest"]], condition="C",
                input_token_ceiling=100, output_token_ceiling=100,
                wall_clock_seconds=60, deadline_utc=deadline,
            )

    def test_requires_frozen_acceptance_criteria_and_bounded_verification_commands(self):
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        with self.assertRaises(ExperimentError):
            create_experiment(
                self.store, self.runtime, task_statement="Task", acceptance_criteria=[],
                verification_commands=[["python", "-m", "unittest"]], condition="A",
                input_token_ceiling=100, output_token_ceiling=100,
                wall_clock_seconds=60, deadline_utc=deadline,
            )
        with self.assertRaises(ExperimentError):
            create_experiment(
                self.store, self.runtime, task_statement="Task", acceptance_criteria=["C1"],
                verification_commands=[[]], condition="A", input_token_ceiling=100,
                output_token_ceiling=100, wall_clock_seconds=60, deadline_utc=deadline,
            )

    def test_authorization_and_execution_are_explicit_sequential_transitions(self):
        record = self.create()
        record = transition_experiment(
            self.store, record["experiment_id"], "authorized",
            idempotency_key="operator-approval-1", event_type="operator_authorized",
            expected_version=1,
        )
        self.assertEqual(record["version"], 2)
        record = transition_experiment(
            self.store, record["experiment_id"], "running",
            idempotency_key="execution-start-1", event_type="execution_started",
            expected_version=2,
        )
        self.assertEqual(record["status"], "running")
        self.assertEqual([e["to_status"] for e in list_experiment_events(self.store, record["experiment_id"])],
                         ["planned", "authorized", "running"])

    def test_invalid_transition_and_stale_version_are_rejected(self):
        record = self.create()
        with self.assertRaises(ExperimentError):
            transition_experiment(
                self.store, record["experiment_id"], "running",
                idempotency_key="skip-approval", event_type="execution_started",
            )
        transition_experiment(
            self.store, record["experiment_id"], "authorized",
            idempotency_key="approval", event_type="operator_authorized",
        )
        with self.assertRaises(ExperimentError):
            transition_experiment(
                self.store, record["experiment_id"], "running",
                idempotency_key="stale", event_type="execution_started", expected_version=1,
            )

    def test_idempotency_replay_is_safe_but_key_reuse_is_rejected(self):
        record = self.create()
        args = dict(idempotency_key="approval-1", event_type="operator_authorized")
        first = transition_experiment(self.store, record["experiment_id"], "authorized", **args)
        replay = transition_experiment(self.store, record["experiment_id"], "authorized", **args)
        self.assertEqual(first["version"], replay["version"])
        with self.assertRaises(ExperimentError):
            transition_experiment(
                self.store, record["experiment_id"], "cancelled",
                idempotency_key="approval-1", event_type="operator_cancelled",
            )

    def test_success_requires_verification_then_all_criteria_pass_with_evidence(self):
        record = self.create("A")
        eid = record["experiment_id"]
        transition_experiment(self.store, eid, "authorized", idempotency_key="a", event_type="authorized")
        transition_experiment(self.store, eid, "running", idempotency_key="b", event_type="started")
        transition_experiment(self.store, eid, "verifying", idempotency_key="c", event_type="verification_started")
        with self.assertRaises(ExperimentError):
            transition_experiment(
                self.store, eid, "adjudicating", idempotency_key="d", event_type="adjudication_started",
            )
        transition_experiment(self.store, eid, "adjudicating", idempotency_key="d", event_type="adjudication_started",
                              payload={"verification_evidence_references": ["artifact:tests.json"]})
        with self.assertRaises(ExperimentError):
            transition_experiment(
                self.store, eid, "succeeded", idempotency_key="e", event_type="adjudicated",
                payload={"adjudication": {"reviewer_type": "human", "criteria_results": [
                    {"criterion_id": "tests-pass", "status": "pass", "evidence_references": ["artifact:tests.json"]}
                ]}},
            )
        payload = {"adjudication": {"reviewer_type": "human", "criteria_results": [
            {"criterion_id": "tests-pass", "status": "pass", "evidence_references": ["artifact:tests.json"]},
            {"criterion_id": "no-regressions", "status": "pass", "evidence_references": ["artifact:diff.json"]},
        ]}}
        done = transition_experiment(self.store, eid, "succeeded", idempotency_key="e", event_type="adjudicated", payload=payload)
        self.assertEqual(done["status"], "succeeded")

    def test_terminal_states_cannot_resume(self):
        record = self.create()
        transition_experiment(self.store, record["experiment_id"], "cancelled",
                              idempotency_key="cancel", event_type="operator_cancelled")
        with self.assertRaises(ExperimentError):
            transition_experiment(self.store, record["experiment_id"], "authorized",
                                  idempotency_key="resume", event_type="resume")

    def test_manifest_and_event_history_are_immutable(self):
        record = self.create()
        with self.assertRaises(Exception):
            self.store.db.execute("UPDATE cooperative_experiments SET spec_json='{}' WHERE experiment_id=?",
                                  (record["experiment_id"],))
        self.store.db.rollback()
        with self.assertRaises(Exception):
            self.store.db.execute("DELETE FROM cooperative_experiment_events WHERE experiment_id=?",
                                  (record["experiment_id"],))
        self.store.db.rollback()
        self.assertEqual(get_experiment(self.store, record["experiment_id"])["spec_hash"], record["spec_hash"])

    def test_manifest_hash_tampering_is_detected(self):
        record = self.create()
        self.store.db.execute("DROP TRIGGER cooperative_experiment_spec_immutable")
        self.store.db.execute("UPDATE cooperative_experiments SET spec_json='{}' WHERE experiment_id=?",
                              (record["experiment_id"],))
        self.store.db.commit()
        with self.assertRaises(ExperimentError):
            get_experiment(self.store, record["experiment_id"])


if __name__ == "__main__":
    unittest.main()
