import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evo_core.ai_configurations import create_configuration
from evo_core.config import EvoConfig
from evo_core.cooperative_handoffs import (
    HandoffBudget, HandoffError, create_handoff, get_handoff,
    initialize_cooperative_handoffs, list_handoffs, validate_context_references,
    validate_handoff_payload,
)
from evo_core.dispatch_admission import initialize_invocation_lifecycle
from evo_core.participant_contracts import stable_integration_id, stable_participant_id
from evo_core.platform_registry import initialize_platform_registry
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.runtime_binding import build_workspace_runtime
from evo_core.runtime_invocation_snapshots import (
    create_runtime_invocation_snapshot, initialize_runtime_invocation_snapshots,
)
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


class HandoffContractTests(unittest.TestCase):
    def test_proposal_contract_accepts_bounded_structured_plan(self):
        value = validate_handoff_payload("proposal", {
            "summary": "Implement the isolated change.",
            "plan": [{"step_id": "step-1", "description": "Add a validator.", "affected_paths": ["src/a.py"]}],
        })
        self.assertEqual(value["plan"][0]["step_id"], "step-1")

    def test_critique_contract_requires_unique_findings_and_known_severity(self):
        good = {
            "summary": "Two issues.",
            "findings": [{
                "finding_id": "F-1", "severity": "high", "target": "src/a.py",
                "issue": "Missing validation.", "recommendation": "Reject malformed input.",
                "evidence_references": ["artifact:diff"],
            }],
        }
        self.assertEqual(len(validate_handoff_payload("critique", good)["findings"]), 1)
        bad = dict(good, findings=good["findings"] * 2)
        with self.assertRaises(HandoffError):
            validate_handoff_payload("critique", bad)

    def test_synthesis_requires_explicit_disposition_and_reason(self):
        good = {
            "summary": "Final candidate prepared.",
            "dispositions": [{"finding_id": "F-1", "disposition": "deferred", "reason": "Outside scope."}],
        }
        self.assertEqual(validate_handoff_payload("synthesis", good)["dispositions"][0]["disposition"], "deferred")
        with self.assertRaises(HandoffError):
            validate_handoff_payload("synthesis", {
                "summary": "Missing disposition.", "dispositions": [{"finding_id": "F-1", "disposition": "ignored", "reason": "x"}],
            })

    def test_adjudication_preserves_unknown_and_requires_evidence_list(self):
        value = validate_handoff_payload("adjudication", {
            "reviewer_type": "human", "criteria_results": [
                {"criterion_id": "C-1", "status": "unknown", "evidence_references": []}
            ], "notes": "",
        })
        self.assertEqual(value["criteria_results"][0]["status"], "unknown")

    def test_rejects_unknown_fields_oversize_payload_secret_like_text_and_invalid_role(self):
        with self.assertRaises(HandoffError):
            validate_handoff_payload("proposal", {"summary": "x", "plan": [], "dispatch": True})
        with self.assertRaises(HandoffError):
            validate_handoff_payload("proposal", {"summary": "x", "plan": []})
        with self.assertRaises(HandoffError):
            validate_handoff_payload("proposal", {
                "summary": "Use token Bearer abcdefghijklmnopqrstuvwxyz123456",
                "plan": [{"step_id": "1", "description": "x"}],
            })
        with self.assertRaises(HandoffError):
            validate_handoff_payload("unrestricted_chat", {})

    def test_rejects_unhashable_enum_values_without_leaking_type_errors(self):
        with self.assertRaises(HandoffError):
            validate_handoff_payload("critique", {"summary": "x", "findings": [{
                "finding_id": "F1", "severity": [], "target": "src/a.py",
                "issue": "x", "recommendation": "y",
            }]})
        with self.assertRaises(HandoffError):
            validate_context_references([{
                "reference_id": "x", "source_type": [], "scope": "workspace:1",
                "trust_label": "untrusted_input",
            }])

    def test_context_references_are_typed_unique_and_bounded(self):
        value = validate_context_references([{
            "reference_id": "task-1", "source_type": "task_statement",
            "scope": "workspace:ws-1", "trust_label": "untrusted_input",
        }])
        self.assertEqual(value[0]["trust_label"], "untrusted_input")
        with self.assertRaises(HandoffError):
            validate_context_references([{
                "reference_id": "x", "source_type": "task_statement",
                "scope": "workspace:ws-1", "trust_label": "trusted",
            }])

    def test_budget_rejects_boolean_and_naive_deadline(self):
        with self.assertRaises(HandoffError):
            HandoffBudget(True, 10, "2026-11-25T12:00:00Z")
        with self.assertRaises(HandoffError):
            HandoffBudget(10, 10, "2026-11-25T12:00:00")


class HandoffPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = EvoStore(self.root / "handoffs.sqlite3")
        initialize_platform_registry(self.store)
        project = register_project(self.store, "Handoff project")
        checkout_path = self.root / "checkout"
        checkout_path.mkdir()
        checkout = register_checkout(self.store, project["project_id"], checkout_path)
        created = create_configuration(self.store, definition(), name="Handoff config")
        self.workspace = create_workspace(
            self.store, "Handoff workspace", project["project_id"],
            created["configuration"]["configuration_id"], created["revision"]["revision_id"],
            checkout_id=checkout["checkout_id"],
        )
        self.config = EvoConfig(
            base_url="http://127.0.0.1:18997/v1", api_key="never-persist-this",
            model="global", timeout_seconds=30, database=self.root / "handoffs.sqlite3",
            max_tokens=256, temperature=0.2, system_prompt="policy", memory_limit=2,
            history_messages=4, workspace_root=self.root, allowed_commands=(("python",),),
            max_history_chars=4000, context_window_tokens=8192,
        )
        initialize_runtime_invocation_snapshots(self.store)
        initialize_invocation_lifecycle(self.store)
        initialize_cooperative_handoffs(self.store)
        self.runtime = build_workspace_runtime(self.store, self.config, self.workspace["workspace_id"])
        self.selected = self.runtime.select_participant(self.runtime.participant.participant_id)
        self.invocation_id = "handoff-invocation"
        snapshot = create_runtime_invocation_snapshot(
            self.store, self.selected, invocation_id=self.invocation_id,
            invocation_kind="participant_completion",
        )
        now = datetime.now(timezone.utc)
        deadline = (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        with self.store.lock:
            self.store.db.execute(
                """INSERT INTO participant_invocations(
                    invocation_id,workspace_id,project_id,participant_id,integration_id,adapter_id,
                    configuration_id,revision_id,revision_hash,snapshot_hash,status,decision_json,
                    deadline_utc,requested_output_tokens,budget_day_utc,created_at,updated_at,finished_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.invocation_id, self.workspace["workspace_id"], self.runtime.project_id,
                    self.selected.participant.participant_id, self.selected.participant.integration_id,
                    self.selected.participant.adapter_id, self.runtime.configuration_id,
                    self.runtime.revision_id, self.runtime.revision_hash, snapshot["snapshot_hash"],
                    "succeeded", json.dumps({"decision": "admitted"}), deadline, 1024, "2026-11-25",
                    deadline, deadline, deadline,
                ),
            )
            self.store.db.commit()
        self.deadline = (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        self.payload = {
            "summary": "Implement the bounded feature.",
            "plan": [{"step_id": "S1", "description": "Add the contract module."}],
        }

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_persists_secret_safe_revision_pinned_handoff_and_reads_back_hash(self):
        secondary = next(item for item in self.runtime.participants if item.participant_type == "model" and item.participant_id != self.selected.participant.participant_id)
        record = create_handoff(
            self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
            role="proposal", target_participant_id=secondary.participant_id,
            payload=self.payload, context_references=[{
                "reference_id": "task-statement", "source_type": "task_statement",
                "scope": "workspace:" + self.runtime.workspace_id, "trust_label": "untrusted_input",
            }],
            budget=HandoffBudget(2048, 1024, self.deadline),
        )
        fetched = get_handoff(self.store, record["handoff_id"])
        self.assertEqual(fetched["handoff_hash"], record["handoff_hash"])
        self.assertEqual(fetched["handoff_json"]["source_participant_id"], self.selected.participant.participant_id)
        self.assertNotIn("never-persist-this", fetched["handoff_json"].__repr__())
        self.assertEqual(len(list_handoffs(self.store, self.runtime.workspace_id, "task-1")), 1)

    def test_synthesis_may_be_a_terminal_handoff_without_model_target(self):
        result = create_handoff(
            self.store, self.selected, invocation_id=self.invocation_id, task_id="task-2",
            role="synthesis", target_participant_id=None,
            payload={"summary": "Candidate synthesized.", "dispositions": []},
            budget=HandoffBudget(10, 10, self.deadline),
        )
        self.assertIsNone(result["target_participant_id"])

    def test_rejects_token_ceilings_exceeding_invocation_or_context_window(self):
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(8192, 256, self.deadline),
            )
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(7168, 1025, self.deadline),
            )

    def test_rejects_wrong_target_and_non_succeeded_invocation(self):
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id="caller-invented-participant",
                payload=self.payload, budget=HandoffBudget(10, 10, self.deadline),
            )
        with self.store.lock:
            self.store.db.execute("UPDATE participant_invocations SET status='timed_out' WHERE invocation_id=?", (self.invocation_id,))
            self.store.db.commit()
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(10, 10, self.deadline),
            )

    def test_rejects_deadline_exceeding_invocation_and_repeated_role_for_invocation(self):
        late = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(10, 10, late),
            )
        create_handoff(
            self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
            role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
            payload=self.payload, budget=HandoffBudget(10, 10, self.deadline),
        )
        with self.assertRaises(Exception):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(10, 10, self.deadline),
            )

    def test_only_successful_pinned_invocation_can_create_handoff(self):
        self.store.db.execute("UPDATE participant_invocations SET revision_hash='different' WHERE invocation_id=?", (self.invocation_id,))
        self.store.db.commit()
        with self.assertRaises(HandoffError):
            create_handoff(
                self.store, self.selected, invocation_id=self.invocation_id, task_id="task-1",
                role="proposal", target_participant_id=self.runtime.participants[1].participant_id,
                payload=self.payload, budget=HandoffBudget(10, 10, self.deadline),
            )


if __name__ == "__main__":
    unittest.main()
