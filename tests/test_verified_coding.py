import json
import os
import tempfile
import unittest

from evo_core import orchestration


class VerifiedCodingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "plans.db")
        import sqlite3
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        orchestration.initialize(self.db)
        self.plan = orchestration.create_plan(self.db, "Fix tests", "/workspace", {
            "title": "Fix tests",
            "summary": "Implement and verify.",
            "steps": [
                {"title": "Implement", "description": "Edit code.", "expected_outcome": "Code changed.",
                 "verification": "Run unit tests.", "verification_commands": [["python", "-m", "unittest"]]},
                {"title": "Document", "description": "Update docs.", "expected_outcome": "Docs changed.",
                 "verification": "Manual review.", "verification_commands": []},
            ],
        })

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_verification_commands_persisted(self):
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_commands"], [["python", "-m", "unittest"]])
        self.assertEqual(plan["steps"][1]["verification_commands"], [])

    def test_record_verification_persists_evidence(self):
        step = self.plan["steps"][0]
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        refreshed = orchestration.get_plan(self.db, self.plan["id"])
        checks = refreshed["steps"][0]["verification_checks"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["status"], "passed")
        self.assertEqual(checks[0]["exit_code"], 0)
        self.assertEqual(refreshed["steps"][0]["verification_status"], "passed")

    def test_missing_verification_is_not_run(self):
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "not_run")
        self.assertEqual(plan["verification_summary"]["not_run"], 1)
        self.assertEqual(plan["verification_summary"]["not_configured"], 1)

    def test_failed_verification_status(self):
        step = self.plan["steps"][0]
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "failed", 1, "", "boom")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "failed")

    def test_mixed_verified_and_unverified_plan_completion_allowed(self):
        orchestration.approve_plan(self.db, self.plan["id"])
        orchestration.attach_run(self.db, self.plan["id"], "run-1")
        orchestration.start_step(self.db, self.plan["id"], self.plan["steps"][0]["id"])
        orchestration.finish_step(self.db, self.plan["id"], self.plan["steps"][0]["id"], "completed", "done", verification_status="passed")
        orchestration.start_step(self.db, self.plan["id"], self.plan["steps"][1]["id"])
        orchestration.finish_step(self.db, self.plan["id"], self.plan["steps"][1]["id"], "completed", "done", verification_status="not_required")
        # One step has no verification configured; plan can still complete.
        orchestration.finish_plan(self.db, self.plan["id"], "completed")
        self.assertEqual(orchestration.get_plan(self.db, self.plan["id"])["status"], "completed")

    def test_invalid_verification_command_rejected(self):
        with self.assertRaises(ValueError):
            orchestration.create_plan(self.db, "x", "/w", {
                "title": "x", "summary": "y",
                "steps": [{"title": "s", "description": "d", "expected_outcome": "o",
                           "verification": "v", "verification_commands": "not-a-list"}],
            })


    def test_one_of_two_passed_is_not_run(self):
        step = self.plan["steps"][0]
        # Reconfigure to two distinct commands.
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"], ["python", "-m", "pytest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "not_run")

    def test_one_passed_one_failed_is_failed(self):
        step = self.plan["steps"][0]
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"], ["python", "-m", "pytest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "pytest"], "failed", 1, "", "boom")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "failed")

    def test_duplicate_evidence_does_not_satisfy_other_command(self):
        step = self.plan["steps"][0]
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"], ["python", "-m", "pytest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "not_run")

    def test_all_configured_commands_passed(self):
        step = self.plan["steps"][0]
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "passed")

    def test_denied_verification_persisted_as_failed(self):
        step = self.plan["steps"][0]
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "denied", None, "", "denied")
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "failed")
        self.assertEqual(plan["steps"][0]["verification_checks"][0]["status"], "denied")

    def test_partial_verification_survives_restart(self):
        step = self.plan["steps"][0]
        with self.db:
            self.db.execute("UPDATE agent_plan_steps SET verification_commands_json=? WHERE id=?",
                            (json.dumps([["python", "-m", "unittest"], ["python", "-m", "pytest"]]), step["id"]))
        orchestration.record_verification(self.db, self.plan["id"], step["id"], ["python", "-m", "unittest"], "passed", 0, "OK", "")
        # Reopen database to simulate restart.
        self.db.close()
        import sqlite3
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        plan = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(plan["steps"][0]["verification_status"], "not_run")
        self.assertEqual(plan["steps"][0]["verification_checks"][0]["status"], "passed")


    def test_finish_step_persists_verification_status(self):
        plan = self.plan
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-1")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="passed")
        refreshed = orchestration.get_plan(self.db, plan["id"])
        self.assertEqual(refreshed["steps"][0]["verification_status"], "passed")

    def test_plan_cannot_complete_with_not_run(self):
        plan = self.plan
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-1")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="not_run")
        with self.assertRaises(ValueError):
            orchestration.finish_plan(self.db, plan["id"], "completed")

    def test_plan_cannot_complete_with_not_configured(self):
        plan = self.plan
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-1")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="not_configured")
        with self.assertRaises(ValueError):
            orchestration.finish_plan(self.db, plan["id"], "completed")

    def test_plan_cannot_complete_with_failed_verification(self):
        plan = self.plan
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-1")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="failed")
        with self.assertRaises(ValueError):
            orchestration.finish_plan(self.db, plan["id"], "completed")

    def test_plan_can_complete_with_passed_verification(self):
        plan = self.plan
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-1")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="passed")
        # second step not_required
        step2 = plan["steps"][1]
        orchestration.start_step(self.db, plan["id"], step2["id"])
        orchestration.finish_step(self.db, plan["id"], step2["id"], "completed", "done", verification_status="not_required")
        orchestration.finish_plan(self.db, plan["id"], "completed")
        self.assertEqual(orchestration.get_plan(self.db, plan["id"])["status"], "completed")

    def test_inspection_only_not_required_can_complete(self):
        plan = orchestration.create_plan(self.db, "Inspect", "/w", {
            "title": "Inspect", "summary": "Inspect only.",
            "steps": [{"title": "Inspect", "description": "Look.", "expected_outcome": "Known.", "verification": "Manual.", "verification_commands": []}],
        })
        step = plan["steps"][0]
        orchestration.approve_plan(self.db, plan["id"])
        orchestration.attach_run(self.db, plan["id"], "run-2")
        orchestration.start_step(self.db, plan["id"], step["id"])
        orchestration.finish_step(self.db, plan["id"], step["id"], "completed", "done", verification_status="not_required")
        orchestration.finish_plan(self.db, plan["id"], "completed")
        self.assertEqual(orchestration.get_plan(self.db, plan["id"])["status"], "completed")

    def test_migration_adds_verification_status_column(self):
        import sqlite3
        db_path = os.path.join(self.tmp.name, "old.db")
        old = sqlite3.connect(db_path)
        old.executescript("""
        CREATE TABLE agent_plan_steps (
          id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, position INTEGER NOT NULL,
          title TEXT NOT NULL, description TEXT NOT NULL, expected_outcome TEXT NOT NULL,
          verification TEXT NOT NULL, verification_commands_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '',
          started_at TEXT, finished_at TEXT, UNIQUE(plan_id,position)
        );
        """)
        old.commit()
        old.close()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        orchestration.initialize(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_plan_steps)")}
        self.assertIn("verification_status", cols)
        conn.close()

    def test_create_plan_validates_verification_commands_against_allowlist(self):
        with self.assertRaises(ValueError):
            orchestration.create_plan(self.db, "x", "/w", {
                "title": "x", "summary": "y",
                "steps": [{"title": "s", "description": "d", "expected_outcome": "o",
                           "verification": "v", "verification_commands": [["python", "test_calculator.py"]]}],
            }, allowed_commands=[["python", "-m", "unittest"]])
        plan = orchestration.create_plan(self.db, "x", "/w", {
            "title": "x", "summary": "y",
            "steps": [{"title": "s", "description": "d", "expected_outcome": "o",
                       "verification": "v", "verification_commands": [["python", "-m", "unittest"]]}],
        }, allowed_commands=[["python", "-m", "unittest"]])
        self.assertEqual(plan["steps"][0]["verification_commands"], [["python", "-m", "unittest"]])

    def test_empty_allowlist_does_not_permit_verification_command(self):
        with self.assertRaises(ValueError):
            orchestration.create_plan(self.db, "x", "/w", {
                "title": "x", "summary": "y",
                "steps": [{"title": "s", "description": "d", "expected_outcome": "o",
                           "verification": "v", "verification_commands": [["python", "-m", "unittest"]]}],
            }, allowed_commands=[])

    def test_propose_with_model_receives_allowlist(self):
        class FakeProvider:
            def __init__(self):
                self.messages = None
            def chat(self, messages, **kwargs):
                self.messages = messages
                return {"content": json.dumps({"title": "t", "summary": "s", "steps": [
                    {"title": "s", "description": "d", "expected_outcome": "o", "verification": "v",
                     "verification_commands": [["python", "-m", "unittest"]]}
                ]})}
        provider = FakeProvider()
        proposal = orchestration.propose_with_model(provider, "request", "/w", allowed_commands=[["python", "-m", "unittest"]])
        self.assertEqual(proposal["steps"][0]["verification_commands"], [["python", "-m", "unittest"]])
        self.assertIn("Configured command prefixes: python -m unittest", provider.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
