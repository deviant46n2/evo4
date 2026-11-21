import sqlite3
import unittest

from evo_core import orchestration


class AgentOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE agent_runs(id TEXT PRIMARY KEY)")
        orchestration.initialize(self.db)
        self.plan = orchestration.create_plan(self.db, "Improve retrieval", "/workspace", {
            "title": "Improve retrieval",
            "summary": "Inspect, implement, and verify the retrieval improvement.",
            "steps": [
                {"title": "Inspect", "description": "Inspect relevant implementation and tests.",
                 "expected_outcome": "Relevant code and constraints are understood.",
                 "verification": "Inspection results identify concrete files and behavior."},
                {"title": "Implement", "description": "Make the smallest safe implementation change.",
                 "expected_outcome": "Requested behavior is implemented.",
                 "verification": "Review the diff and run focused tests."},
            ],
        })

    def tearDown(self):
        self.db.close()

    def test_plan_is_proposed_and_steps_are_ordered(self):
        self.assertEqual(self.plan["status"], "proposed")
        self.assertEqual([s["position"] for s in self.plan["steps"]], [0, 1])
        self.assertEqual(self.plan["events"][0]["type"], "proposed")

    def test_plan_validation_rejects_empty_or_oversized_steps(self):
        for steps in ([], [{}] * 13, ["not an object"]):
            with self.assertRaises(ValueError):
                orchestration.create_plan(self.db, "x", "/w", {
                    "title": "x", "summary": "y", "steps": steps})

    def test_completed_plan_requires_every_step_completed(self):
        orchestration.approve_plan(self.db, self.plan["id"])
        orchestration.attach_run(self.db, self.plan["id"], "run-1")
        with self.assertRaises(ValueError):
            orchestration.finish_plan(self.db, self.plan["id"], "completed")

    def test_non_text_model_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            orchestration.create_plan(self.db, "x", "/w", {
                "title": 123, "summary": "S",
                "steps": [{"title": "I", "description": "D",
                           "expected_outcome": "O", "verification": "V"}]})

    def test_approval_is_explicit_and_one_way(self):
        approved = orchestration.approve_plan(self.db, self.plan["id"])
        self.assertEqual(approved["status"], "approved")
        with self.assertRaises(ValueError):
            orchestration.approve_plan(self.db, self.plan["id"])

    def test_steps_must_run_in_order_and_finish_from_running(self):
        orchestration.approve_plan(self.db, self.plan["id"])
        orchestration.attach_run(self.db, self.plan["id"], "run-1")
        steps = self.plan["steps"]
        with self.assertRaises(ValueError):
            orchestration.start_step(self.db, self.plan["id"], steps[1]["id"])
        orchestration.start_step(self.db, self.plan["id"], steps[0]["id"])
        with self.assertRaises(ValueError):
            orchestration.finish_step(self.db, self.plan["id"], steps[1]["id"], "completed")
        orchestration.finish_step(self.db, self.plan["id"], steps[0]["id"], "completed", "Inspected")
        orchestration.start_step(self.db, self.plan["id"], steps[1]["id"])
        orchestration.finish_step(self.db, self.plan["id"], steps[1]["id"], "completed", "Tests passed")
        self.assertEqual(orchestration.get_plan(self.db, self.plan["id"])["steps"][1]["status"], "completed")

    def test_failed_plan_skips_remaining_steps(self):
        orchestration.approve_plan(self.db, self.plan["id"])
        orchestration.attach_run(self.db, self.plan["id"], "run-1")
        step = self.plan["steps"][0]
        orchestration.start_step(self.db, self.plan["id"], step["id"])
        orchestration.finish_step(self.db, self.plan["id"], step["id"], "failed", "No access")
        orchestration.finish_plan(self.db, self.plan["id"], "failed", "Step failed")
        result = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"][1]["status"], "skipped")

    def test_restart_recovery_marks_active_step_interrupted_and_skips_future_steps(self):
        orchestration.approve_plan(self.db, self.plan["id"])
        orchestration.attach_run(self.db, self.plan["id"], "run-1")
        first = self.plan["steps"][0]
        orchestration.start_step(self.db, self.plan["id"], first["id"])
        self.assertEqual(orchestration.recover_plans(self.db), [self.plan["id"]])
        recovered = orchestration.get_plan(self.db, self.plan["id"])
        self.assertEqual(recovered["steps"][0]["status"], "interrupted")
        self.assertEqual(recovered["steps"][1]["status"], "skipped")

    def test_model_proposal_is_json_only_and_persisted_only_after_validation(self):
        class Provider:
            def chat(self, messages, **kwargs):
                return {"content": '{"title":"T","summary":"S","steps":['
                    '{"title":"I","description":"Inspect","expected_outcome":"Know the code",'
                    '"verification":"Read relevant files"}]}'}
        proposal = orchestration.propose_with_model(Provider(), "Do work", "/workspace")
        saved = orchestration.create_plan(self.db, "Do work", "/workspace", proposal)
        self.assertEqual(saved["status"], "proposed")
        self.assertEqual(saved["steps"][0]["verification"], "Read relevant files")

    def test_invalid_model_json_is_rejected_without_saving(self):
        class Provider:
            def chat(self, messages, **kwargs):
                return {"content": "not JSON"}
        with self.assertRaises(ValueError):
            orchestration.propose_with_model(Provider(), "Do work", "/workspace")
        self.assertEqual(orchestration.list_plans(self.db), [])


if __name__ == "__main__":
    unittest.main()
