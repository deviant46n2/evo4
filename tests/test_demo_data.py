import tempfile
import unittest
from pathlib import Path

from evo_core.demo_data import seed_demo_data, demo_data_status, clear_demo_data
from evo_core.store import EvoStore
from evo_experiments.db import ResultsDB


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "evo.sqlite3"
        self.store = EvoStore(path)
        self.lab = ResultsDB(path)

    def tearDown(self):
        self.store.close()
        self.lab.close()
        self.tmp.cleanup()

    def test_seed_is_idempotent_and_populates_all_requested_workspaces(self):
        first = seed_demo_data(self.store, self.lab)
        second = seed_demo_data(self.store, self.lab)
        self.assertGreater(first["seeded"]["memories"], 0)
        self.assertGreater(first["seeded"]["candidates"], 0)
        self.assertGreater(first["seeded"]["agent_runs"], 0)
        self.assertGreater(first["seeded"]["experiments"], 0)
        self.assertGreater(first["seeded"]["resource_samples"], 0)
        self.assertTrue(all(value == 0 for value in second["seeded"].values()))
        status = demo_data_status(self.store, self.lab)
        self.assertTrue(status["active"])
        self.assertGreater(status["memories"], 0)
        self.assertGreater(status["agent_runs"], 0)
        self.assertGreater(status["experiments"], 0)

    def test_clear_removes_only_demo_records_and_preserves_user_data(self):
        self.store.add_memory("A real user memory", "preferences", source="user")
        result = seed_demo_data(self.store, self.lab)
        cleared = clear_demo_data(self.store, self.lab)
        self.assertEqual(cleared["removed"]["memories"], result["seeded"]["memories"])
        self.assertEqual(cleared["removed"]["candidates"], result["seeded"]["candidates"])
        self.assertEqual(cleared["removed"]["agent_runs"], result["seeded"]["agent_runs"])
        self.assertEqual(cleared["removed"]["experiments"], result["seeded"]["experiments"])
        remaining = self.store.db.execute("SELECT content FROM memories").fetchall()
        self.assertEqual([row["content"] for row in remaining], ["A real user memory"])
        self.assertEqual(self.lab.connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0], 0)
        self.assertFalse(demo_data_status(self.store, self.lab)["active"])


if __name__ == "__main__":
    unittest.main()
