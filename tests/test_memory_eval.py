import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from evo_core.memory_eval import evaluate_memory_retrieval
import evo_core.cli as evo_cli


class MemoryEvaluationTests(unittest.TestCase):
    def write_cases(self, directory, data):
        path=Path(directory)/"cases.json"
        path.write_text(json.dumps(data),encoding="utf-8")
        return path

    def test_fixture_scores_retrieval_with_ranked_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write_cases(tmp,{
                "version":1,
                "memories":[
                    {"key":"gpu","content":"RTX 5070 Ti has 16 GB VRAM and Ryzen CPU."},
                    {"key":"food","content":"Pasta recipe with tomato and basil."},
                    {"key":"coding","content":"Coding agents should run tests and verify exit codes."}
                ],
                "queries":[
                    {"id":"gpu-query","query":"RTX 5070 Ti VRAM","expected":["gpu"]},
                    {"id":"code-query","query":"coding agent tests verify exit codes","expected":["coding"]}
                ]})
            report=evaluate_memory_retrieval(path,top_k=2)
            self.assertEqual(report["memory_count"],3)
            self.assertEqual(report["query_count"],2)
            self.assertEqual(report["hit_rate_at_k"],1.0)
            self.assertEqual(report["mean_recall_at_k"],1.0)
            self.assertEqual(report["mean_reciprocal_rank"],1.0)
            self.assertTrue(all(row["relevant_retrieved"] for row in report["results"]))
            self.assertIn("Synthetic isolated benchmark",report["note"])

    def test_fallback_backend_is_measured_separately(self):
        fixture=Path(__file__).resolve().parents[1]/"tasks"/"memory-retrieval.json"
        report=evaluate_memory_retrieval(fixture,top_k=5,backend="fallback")
        self.assertEqual(report["backend"],"fallback")
        self.assertEqual(report["hit_rate_at_k"],1.0)
        self.assertEqual(report["mean_recall_at_k"],1.0)

    def test_invalid_backend_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write_cases(tmp,{
                "version":1,"memories":[{"key":"known","content":"Known fact"}],
                "queries":[{"query":"known fact","expected":["known"]}]})
            with self.assertRaisesRegex(ValueError,"backend"):
                evaluate_memory_retrieval(path,backend="vector")

    def test_unknown_expected_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write_cases(tmp,{
                "version":1,"memories":[{"key":"known","content":"Known fact"}],
                "queries":[{"query":"known fact","expected":["missing"]}]})
            with self.assertRaisesRegex(ValueError,"unknown memory keys"):
                evaluate_memory_retrieval(path)

    def test_invalid_top_k_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write_cases(tmp,{
                "version":1,"memories":[{"key":"known","content":"Known fact"}],
                "queries":[{"query":"known fact","expected":["known"]}]})
            with self.assertRaisesRegex(ValueError,"top_k"):
                evaluate_memory_retrieval(path,0)

    def test_cli_evaluation_does_not_create_the_configured_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases=self.write_cases(tmp,{
                "version":1,
                "memories":[{"key":"one","content":"local GPU inference"}],
                "queries":[{"query":"GPU inference","expected":["one"]}]})
            database=Path(tmp)/"state"/"evo.sqlite3"
            argv=["evo","memory","evaluate","--cases",str(cases)]
            with patch.object(sys,"argv",argv), patch("sys.stdout",new=io.StringIO()) as output:
                evo_cli.main()
            self.assertIn("hit_rate_at_k",output.getvalue())
            self.assertFalse(database.exists())

    def test_empty_or_wrong_version_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write_cases(tmp,{"version":2,"memories":[],"queries":[]})
            with self.assertRaisesRegex(ValueError,"version=1"):
                evaluate_memory_retrieval(path)


if __name__=="__main__":
    unittest.main()
