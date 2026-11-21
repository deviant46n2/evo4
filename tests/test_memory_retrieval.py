import tempfile
import unittest
from pathlib import Path

from evo_core.store import EvoStore


class HybridMemoryRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EvoStore(Path(self.tmp.name) / "memory.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_hybrid_candidates_include_content_and_tag_matches(self):
        tagged = self.store.add_memory(
            "A preference for careful engineering decisions",
            category="preferences", tags=["qwen", "cuda"], source="user", confidence=0.9,
        )
        content = self.store.add_memory(
            "The local Qwen runtime uses CUDA for inference",
            category="environment", tags=["runtime"], source="user", confidence=0.8,
        )
        rows = self.store.search_memories("Qwen CUDA", limit=5)
        ids = [row["id"] for row in rows]
        self.assertIn(content, ids)
        self.assertIn(tagged, ids)
        self.assertTrue(all("retrieval_score" in row for row in rows))

    def test_content_match_ranks_above_tag_only_match(self):
        tag_only = self.store.add_memory(
            "The workstation has a fast graphics processor",
            category="hardware", tags=["RTX", "5070"], source="user", confidence=1.0,
        )
        content_match = self.store.add_memory(
            "The RTX 5070 Ti has 16 GB VRAM",
            category="hardware", tags=[], source="user", confidence=0.6,
        )
        rows = self.store.search_memories("RTX 5070 VRAM", limit=5)
        self.assertEqual(rows[0]["id"], content_match)
        self.assertIn(tag_only, [row["id"] for row in rows])

    def test_match_explanation_reports_evidence_and_coverage(self):
        memory_id = self.store.add_memory(
            "The local coding model is served through llama.cpp",
            category="models", tags=["qwen"], source="explicit-user",
        )
        row = self.store.search_memories("local coding model llama cpp", limit=1)[0]
        self.assertEqual(row["id"], memory_id)
        self.assertTrue(row["retrieval_matched_terms"])
        self.assertGreater(row["retrieval_coverage"], 0)
        self.assertTrue(row["retrieval_reason"])

    def test_empty_and_stopword_only_queries_return_no_results(self):
        self.assertEqual(self.store.search_memories(""), [])
        self.assertEqual(self.store.search_memories("what is it"), [])

    def test_legacy_relevance_alias_is_preserved(self):
        self.store.add_memory("RTX 5070 Ti has 16 GB VRAM", category="hardware")
        row = self.store.search_memories("RTX VRAM", limit=1)[0]
        self.assertGreater(row["relevance"], 0)
        self.assertEqual(row["relevance"], row["retrieval_score"])

    def test_percentage_is_a_literal_token_not_a_broad_numeric_match(self):
        exact = self.store.add_memory("100% local inference")
        self.store.add_memory("100 local inference")
        rows = self.store.search_memories("100%", limit=8)
        self.assertEqual([row["id"] for row in rows], [exact])
        self.assertIn("100%", rows[0]["retrieval_matched_terms"])

    def test_archived_and_superseded_records_never_enter_active_retrieval(self):
        old_id = self.store.add_memory("RTX 5070 Ti old driver", source="user")
        new_id = self.store.supersede_memory(
            old_id, "RTX 5070 Ti current driver", reason="Updated by user"
        )
        rows = self.store.search_memories("RTX 5070 Ti driver", limit=10)
        ids = [row["id"] for row in rows]
        self.assertIn(new_id, ids)
        self.assertNotIn(old_id, ids)


if __name__ == "__main__":
    unittest.main()
