import argparse
import unittest
from unittest.mock import ANY, patch

from evo_core.cli import build_parser, _task_workspace_command


class TaskWorkspaceCliTests(unittest.TestCase):
    def test_parser_exposes_read_only_diagnostics(self):
        parser = build_parser()
        args = parser.parse_args(["task-workspaces", "list", "--status", "recovery_required"])
        self.assertEqual(args.command, "task-workspaces")
        self.assertEqual(args.task_workspace_command, "list")
        self.assertEqual(args.status, "recovery_required")
        self.assertEqual(args.limit, 50)
        show = parser.parse_args(["task-workspaces", "show", "operation-1"])
        self.assertEqual(show.operation_id, "operation-1")
        review = parser.parse_args(["task-workspaces", "review", "operation-1"])
        self.assertEqual(review.task_workspace_command, "review")

    @patch("evo_core.task_workspaces.list_task_workspace_operations")
    def test_list_passes_filters_and_limit(self, list_operations):
        list_operations.return_value = [{"operation_id": "operation-1"}]
        args = argparse.Namespace(
            task_workspace_command="list", project_id="project-1",
            status="recovery_required", limit=25,
        )
        result = _task_workspace_command(object(), args)
        self.assertEqual(result, {"operations": [{"operation_id": "operation-1"}]})
        list_operations.assert_called_once_with(
            ANY, project_id="project-1", status="recovery_required", limit=25,
        )

    @patch("evo_core.task_workspaces.get_task_workspace_operation_status")
    def test_show_is_read_only_status_lookup(self, get_status):
        get_status.return_value = {"operation_id": "operation-1", "status": "recovery_required"}
        args = argparse.Namespace(task_workspace_command="show", operation_id="operation-1")
        self.assertEqual(_task_workspace_command(object(), args), get_status.return_value)
        get_status.assert_called_once_with(ANY, "operation-1")

    @patch("evo_core.task_workspaces.get_task_workspace_review")
    def test_review_returns_bounded_review_artifact(self, get_review):
        get_review.return_value = {"stable": True, "patch": "diff"}
        args = argparse.Namespace(task_workspace_command="review", operation_id="operation-1")
        self.assertEqual(_task_workspace_command(object(), args), get_review.return_value)
        get_review.assert_called_once_with(ANY, "operation-1")


if __name__ == "__main__":
    unittest.main()
