import tempfile
import unittest
from pathlib import Path
from evo_core.store import EvoStore

class ResearchStoreTests(unittest.TestCase):
    def test_research_document_capture_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=EvoStore(Path(tmp)/"state.db")
            doc_id=store.add_research_document("SQLite WAL notes","WAL improves reader/writer concurrency.",
                                               "https://sqlite.org/wal.html","web")
            results=store.search_research("concurrency")
            self.assertEqual(len(results),1)
            self.assertEqual(results[0]["id"],doc_id)
            self.assertEqual(results[0]["url"],"https://sqlite.org/wal.html")
            store.close()

if __name__=="__main__":
    unittest.main()
