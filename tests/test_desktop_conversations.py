import tempfile
import unittest
from pathlib import Path

from evo_core.store import EvoStore


class ConversationManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvoStore(Path(self.temp.name) / "evo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_first_user_message_generates_title(self):
        conversation_id = self.store.create_conversation()
        self.store.add_message(conversation_id, "user", "  Build a local memory assistant\nwith reliable search  ")
        conversation = self.store.get_conversation(conversation_id)
        self.assertEqual(conversation["title"], "Build a local memory assistant with reliable search")

    def test_generated_title_is_bounded(self):
        conversation_id = self.store.create_conversation()
        self.store.add_message(conversation_id, "user", "x" * 200)
        self.assertEqual(len(self.store.get_conversation(conversation_id)["title"]), 57)
        self.assertTrue(self.store.get_conversation(conversation_id)["title"].endswith("..."))

    def test_manual_rename_and_validation(self):
        conversation_id = self.store.create_conversation()
        self.assertTrue(self.store.rename_conversation(conversation_id, "  Project notes  "))
        self.assertEqual(self.store.get_conversation(conversation_id)["title"], "Project notes")
        with self.assertRaises(ValueError):
            self.store.rename_conversation(conversation_id, "  ")

    def test_search_matches_title_and_message_content(self):
        first = self.store.create_conversation("Hardware notes")
        second = self.store.create_conversation("Untitled")
        self.store.add_message(second, "user", "Investigate CUDA memory fragmentation")
        self.assertEqual({row["id"] for row in self.store.list_conversations(query="hardware")}, {first})
        self.assertEqual({row["id"] for row in self.store.list_conversations(query="CUDA")}, {second})

    def test_search_escapes_like_wildcards(self):
        literal = self.store.create_conversation("100% local")
        other = self.store.create_conversation("100x local")
        self.assertEqual([row["id"] for row in self.store.list_conversations(query="%")], [literal])

    def test_delete_cascades_messages(self):
        conversation_id = self.store.create_conversation()
        self.store.add_message(conversation_id, "user", "Delete me")
        self.assertTrue(self.store.delete_conversation(conversation_id))
        self.assertIsNone(self.store.get_conversation(conversation_id))
        self.assertEqual(self.store.get_messages(conversation_id), [])
        self.assertFalse(self.store.delete_conversation(conversation_id))


if __name__ == "__main__":
    unittest.main()
