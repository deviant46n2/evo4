import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.coding_agent import CodingAgent, WorkspaceBindingInvalidatedError


class _Assistant:
    def __init__(self):
        self.store = object()


class WorkspaceBindingGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.agent = CodingAgent(_Assistant(), self.root, allowed_commands=[("python", "-c")])

    def tearDown(self):
        self.temp.cleanup()

    def _binding(self, *, version=1, path=None, availability="available"):
        canonical = str(path or self.root)
        return {
            "workspace_id": "workspace-1",
            "project_id": "project-1",
            "configuration_id": "configuration-1",
            "configuration_revision_id": "revision-1",
            "checkout_id": "checkout-1",
            "canonical_path": canonical,
            "workspace": {"version": version},
            "checkout": {
                "availability_status": availability,
                "canonical_path": canonical,
            },
        }

    def test_tool_action_rejects_archived_or_revised_workspace(self):
        with patch(
            "evo_core.coding_agent.workspace_registry.resolve_executable_workspace",
            side_effect=[self._binding(), self._binding(version=2)],
        ):
            self.agent._initialize_workspace_binding("workspace-1")
            called = []
            self.agent.workspace.project_overview = lambda: called.append(True)
            with self.assertRaises(WorkspaceBindingInvalidatedError):
                self.agent._execute("inspect_project", {})
            self.assertEqual(called, [])

    def test_direct_verification_command_revalidates_binding(self):
        with patch(
            "evo_core.coding_agent.workspace_registry.resolve_executable_workspace",
            side_effect=[self._binding(), self._binding(availability="unavailable")],
        ):
            self.agent._initialize_workspace_binding("workspace-1")
            with self.assertRaises(WorkspaceBindingInvalidatedError):
                self.agent.workspace.run(["python", "-c", "print('must not run')"], 5)

    def test_binding_cannot_be_retargeted_to_another_workspace(self):
        with patch(
            "evo_core.coding_agent.workspace_registry.resolve_executable_workspace",
            return_value=self._binding(),
        ):
            self.agent._initialize_workspace_binding("workspace-1")
            with self.assertRaises(WorkspaceBindingInvalidatedError):
                self.agent._initialize_workspace_binding("workspace-2")

    def test_initial_binding_must_match_constructed_workspace_path(self):
        other = self.root.parent / (self.root.name + "-other")
        other.mkdir()
        try:
            with patch(
                "evo_core.coding_agent.workspace_registry.resolve_executable_workspace",
                return_value=self._binding(path=other),
            ):
                with self.assertRaises(WorkspaceBindingInvalidatedError):
                    self.agent._initialize_workspace_binding("workspace-1")
        finally:
            other.rmdir()


if __name__ == "__main__":
    unittest.main()
