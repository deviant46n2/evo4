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
        for step in self.plan["steps"]:
            orchestration.start_step(self.db, self.plan["id"], step["id"])
            orchestration.finish_step(self.db, self.plan["id"], step["id"], "completed", "done")
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


if __name__ == "__main__":
    unittest.main()
