import io
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from evo_core.store import EvoStore
import evo_core.cli as evo_cli


class RunFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=EvoStore(Path(self.tmp.name)/"evo.db")

    def tearDown(self):
        if self.store is not None:
            self.store.close()
        self.tmp.cleanup()

    def make_run(self):
        return self.store.start_agent_run("coding",{"workspace":"demo"})

    def test_new_learning_tables_are_added_to_an_existing_database(self):
        database=Path(self.tmp.name)/"evo.db"
        self.store.close()
        legacy=sqlite3.connect(database)
        legacy.execute("DROP TABLE run_feedback")
        legacy.execute("DROP TABLE memory_relations")
        legacy.commit()
        legacy.close()
        upgraded=EvoStore(database)
        try:
            tables={row[0] for row in upgraded.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("run_feedback",tables)
            self.assertIn("memory_relations",tables)
        finally:
            upgraded.close()
        self.store=None

    def test_feedback_and_lesson_are_saved_atomically(self):
        run_id=self.make_run()
        result=self.store.record_run_feedback(
            run_id,"failure","The patch compiled but broke an existing test.",
            "Run the full existing test suite after a targeted test passes.",
            "coding regression tests","coding")
        feedback=self.store.list_run_feedback(run_id)
        self.assertEqual(len(feedback),1)
        self.assertEqual(feedback[0]["outcome"],"failure")
        self.assertIn("broke an existing test",feedback[0]["feedback"])
        self.assertEqual(feedback[0]["lesson_id"],result["lesson_id"])
        lessons=self.store.search_lessons("full existing test suite")
        self.assertEqual(len(lessons),1)
        self.assertEqual(lessons[0]["source"],"user-run-feedback")
        self.assertAlmostEqual(lessons[0]["confidence"],1.0)

    def test_feedback_can_be_saved_without_creating_a_lesson(self):
        run_id=self.make_run()
        result=self.store.record_run_feedback(run_id,"success","User verified expected behavior.")
        self.assertIsNone(result["lesson_id"])
        self.assertEqual(self.store.list_run_feedback(run_id)[0]["outcome"],"success")

    def test_invalid_outcome_or_empty_feedback_is_rejected(self):
        run_id=self.make_run()
        with self.assertRaises(ValueError):
            self.store.record_run_feedback(run_id,"unknown","x")
        with self.assertRaises(ValueError):
            self.store.record_run_feedback(run_id,"partial","")
        self.assertEqual(self.store.list_run_feedback(run_id),[])

    def test_unknown_run_is_rejected_without_orphan_lesson(self):
        with self.assertRaises(ValueError):
            self.store.record_run_feedback("missing","failure","bad","lesson")
        self.assertEqual(self.store.list_lessons(),[])

    def test_cli_can_review_a_run_and_create_a_retrievable_lesson(self):
        run_id=self.make_run()
        config=Path(self.tmp.name)/"config.toml"
        config.write_text(
            f'[server]\nmodel="test"\n[experiment]\ndatabase="{self.store.path}"\n',
            encoding="utf-8")
        argv=["evo","--config",str(config),"runs","review",run_id,
              "--outcome","partial","--feedback","One test remains failing.",
              "--lesson","Run the complete test suite before declaring success.",
              "--trigger","coding verification"]
        with patch.object(sys,"argv",argv), patch("sys.stdout",new=io.StringIO()) as output:
            evo_cli.main()
        self.assertIn("Feedback recorded:",output.getvalue())
        self.assertEqual(len(self.store.search_lessons("complete test suite")),1)

    def test_cli_show_handles_runs_without_tool_events(self):
        run_id=self.make_run()
        config=Path(self.tmp.name)/"config.toml"
        config.write_text(
            f'[server]\nmodel="test"\n[experiment]\ndatabase="{self.store.path}"\n',
            encoding="utf-8")
        argv=["evo","--config",str(config),"runs","show",run_id]
        with patch.object(sys,"argv",argv), patch("sys.stdout",new=io.StringIO()) as output:
            evo_cli.main()
        self.assertIn(run_id,output.getvalue())
        self.assertIn("Tool events:",output.getvalue())

    def test_run_summary_reports_verification_and_feedback_metrics(self):
        run_id=self.make_run()
        self.store.update_agent_run_metadata(run_id,{
            "verification":{"status":"passed"},"tool_calls":4})
        self.store.finish_agent_run(run_id,"completed","done")
        self.store.record_run_feedback(run_id,"success","User confirmed behavior.")
        summary=self.store.agent_run_summary()
        self.assertEqual(summary["coding_runs"],1)
        self.assertEqual(summary["run_statuses"],{"completed":1})
        self.assertEqual(summary["verification_statuses"],{"passed":1})
        self.assertEqual(summary["reviewed_runs"],1)
        self.assertEqual(summary["feedback_outcomes"],{"success":1})
        self.assertEqual(summary["average_tool_calls"],4.0)

    def test_backup_preserves_feedback_and_linked_lesson(self):
        run_id=self.make_run()
        result=self.store.record_run_feedback(
            run_id,"failure","A regression was found.",
            "Run regression tests before merging changes.","regression tests")
        destination=self.store.backup(Path(self.tmp.name)/"backup.sqlite3")
        restored=EvoStore(destination)
        try:
            feedback=restored.list_run_feedback(run_id)
            self.assertEqual(len(feedback),1)
            self.assertEqual(feedback[0]["lesson_id"],result["lesson_id"])
            self.assertEqual(len(restored.search_lessons("regression tests")),1)
        finally:
            restored.close()

    def test_run_history_and_tool_events_are_inspectable(self):
        run_id=self.make_run()
        self.store.record_tool_event(run_id,"read_file",{"path":"main.py"},{"ok":True},"completed")
        row=self.store.get_agent_run(run_id)
        self.assertEqual(row["kind"],"coding")
        events=self.store.get_run_events(run_id)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["tool_name"],"read_file")
        self.assertEqual(self.store.list_agent_runs()[0]["id"],run_id)


if __name__=="__main__":
    unittest.main()
