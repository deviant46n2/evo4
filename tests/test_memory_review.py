import unittest

from evo_core.memory_review import find_duplicate_candidates


class MemoryReviewTests(unittest.TestCase):
    def test_exact_and_near_duplicate_records_are_suggested(self):
        rows = [
            {"id": "a", "content": "The RTX 5070 Ti has 16 GB VRAM and CUDA support", "category": "hardware"},
            {"id": "b", "content": "RTX 5070 Ti has 16 GB VRAM with CUDA support", "category": "hardware"},
            {"id": "c", "content": "Pasta recipe with tomato basil and garlic", "category": "food"},
        ]
        result = find_duplicate_candidates(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual({result[0]["left"]["id"], result[0]["right"]["id"]}, {"a", "b"})
        self.assertIn("cuda", result[0]["shared_terms"])
        self.assertEqual(result[0]["method"], "lexical-overlap")

    def test_disjoint_memories_are_not_suggested(self):
        rows = [
            {"id": "a", "content": "RTX graphics card VRAM capacity"},
            {"id": "b", "content": "Favorite pasta recipe tomato basil"},
        ]
        self.assertEqual(find_duplicate_candidates(rows), [])

    def test_short_shared_phrase_does_not_trigger_suggestion(self):
        rows = [
            {"id": "a", "content": "The local model uses CUDA for inference"},
            {"id": "b", "content": "The local service uses SQLite for memory"},
        ]
        self.assertEqual(find_duplicate_candidates(rows), [])

    def test_results_are_bounded_and_deterministic(self):
        rows = [
            {"id": str(i), "content": "RTX 5070 Ti 16 GB VRAM CUDA local inference"}
            for i in range(8)
        ]
        first = find_duplicate_candidates(rows, limit=3)
        second = find_duplicate_candidates(rows, limit=3)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 3)

    def test_review_pairs_are_disjoint_and_one_record_cannot_dominate(self):
        rows = [
            {"id": "a", "content": "RTX 5070 Ti 16 GB VRAM CUDA support local graphics"},
            {"id": "b", "content": "RTX 5070 Ti 16 GB VRAM CUDA support local graphics card"},
            {"id": "c", "content": "RTX 5070 Ti 16 GB VRAM CUDA support local graphics device"},
            {"id": "d", "content": "Ryzen 9800X3D processor desktop CPU cores"},
            {"id": "e", "content": "Ryzen 9800X3D processor desktop CPU cores chip"},
        ]
        result = find_duplicate_candidates(rows, limit=10)
        ids = [item[key]["id"] for item in result for key in ("left", "right")]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn({"d", "e"}, [{item["left"]["id"], item["right"]["id"]} for item in result])

    def test_input_records_are_never_mutated(self):
        rows = [{"id": "a", "content": "RTX 5070 Ti 16 GB VRAM CUDA"},
                {"id": "b", "content": "RTX 5070 Ti 16 GB VRAM CUDA"}]
        before = [dict(row) for row in rows]
        find_duplicate_candidates(rows)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
