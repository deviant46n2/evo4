import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import create_configuration
from evo_core.api import create_app
from evo_core.project_checkouts import register_checkout, register_project
from evo_core.task_workspaces import create_task_workspace, get_task_workspace_operation_status, get_task_workspace_fingerprint
from evo_core.workspaces import create_workspace


DEFINITION = {"schema_version": 1, "components": {}}


def request(app, path, method="GET", payload=None):
    path_part, _, query = path.partition("?")
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path_part,
        "raw_path": path_part.encode(), "query_string": query.encode(),
        "root_path": "", "headers": ([(b"content-type", b"application/json")] if payload is not None else []), "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765), "state": {},
    }
    messages = []
    body_bytes = json.dumps(payload).encode() if payload is not None else b""
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}
    async def send(message):
        messages.append(message)
    asyncio.run(app(scope, receive, send))
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return messages[0]["status"], json.loads(body)


class TaskWorkspaceFilesApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "config.toml"
        config_path.write_text(
            '[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n'
            f'[experiment]\ndatabase="{self.root / "evo.sqlite3"}"\n'
            f'[workspace]\nroot="{self.root}"\nallowed_commands=[]\n',
            encoding="utf-8",
        )
        self.app = create_app(config_path)
        store = self.app.state.store
        project = register_project(store, "API files")
        self.source = self.root / "source"
        self.source.mkdir()
        self._git(self.source, "init", "--initial-branch=main")
        self._git(self.source, "config", "user.name", "Test")
        self._git(self.source, "config", "user.email", "test@example.invalid")
        (self.source / "readme.txt").write_text("API inspection works\n")
        self._git(self.source, "add", "readme.txt")
        self._git(self.source, "commit", "-m", "initial")
        revision = self._git(self.source, "rev-parse", "HEAD")
        checkout = register_checkout(store, project["project_id"], self.source,
                                      branch_or_ref="main", last_known_commit=revision)
        cfg = create_configuration(store, DEFINITION, name="api")
        parent = create_workspace(store, "Parent", project["project_id"],
                                  cfg["configuration"]["configuration_id"],
                                  cfg["revision"]["revision_id"], checkout_id=checkout["checkout_id"])
        destination = self.root / "task-worktrees"
        destination.mkdir()
        created_operation = create_task_workspace(store, parent["workspace_id"], "api-task", destination)
        self.operation = get_task_workspace_operation_status(store, created_operation["operation_id"])
        self.task_root = Path(self.operation["destination_path"])

    def tearDown(self):
        self.app.state.chat_executor.shutdown(wait=True, cancel_futures=False)
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    @staticmethod
    def _git(path, *args):
        result = subprocess.run(["git", "-C", str(path), *args],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def test_coding_agent_rejects_mismatched_task_workspace_operation(self):
        from evo_core.coding_agent import CodingAgent, WorkspaceBindingInvalidatedError
        from evo_core.task_workspaces import create_task_workspace

        other = create_task_workspace(
            self.app.state.store,
            self.operation["parent_workspace_id"],
            "api-task-other-agent-binding",
            self.root / "task-worktrees",
        )
        other_workspace_id = other["workspace"]["workspace_id"]
        other_root = Path(other["canonical_path"])
        agent = CodingAgent(
            self.app.state.assistant,
            other_root,
            task_workspace_operation_id=self.operation["operation_id"],
        )
        agent._workspace_id = other_workspace_id
        agent._project_id = self.operation["project_id"]
        agent._source_revision = self.operation["source_revision"]

        with self.assertRaises(WorkspaceBindingInvalidatedError):
            agent._execute("write_file", {
                "path": "must-not-escape.txt",
                "content": "wrong task workspace",
            })

        self.assertFalse((self.task_root / "must-not-escape.txt").exists())
        self.assertFalse((other_root / "must-not-escape.txt").exists())

    def test_file_listing_and_read_routes(self):
        (self.task_root / "note.txt").write_text("API text")
        operation_id = self.operation["operation_id"]
        status, listing = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/files")
        self.assertEqual(status, 200)
        self.assertIn("note.txt", {item["name"] for item in listing["items"]})
        status, result = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/file?path=note.txt")
        self.assertEqual(status, 200)
        self.assertEqual(result["content"], "API text")
        self.assertEqual(result["source_revision"], self.operation["source_revision"])

    def test_file_listing_api_exposes_scan_truncation_provenance(self):
        from unittest.mock import patch

        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            (self.task_root / name).write_text(name)
        operation_id = self.operation["operation_id"]
        with patch("evo_core.task_workspace_files.MAX_DIRECTORY_SCAN_ENTRIES", 2):
            status, listing = request(
                self.app, "/api/v1/task-workspaces/" + operation_id + "/files?limit=1",
            )
        self.assertEqual(status, 200)
        self.assertEqual(listing["scan_limit"], 2)
        self.assertTrue(listing["scan_truncated"])
        self.assertFalse(listing["total_exact"])
        self.assertTrue(listing["truncated"])
        self.assertEqual(len(listing["items"]), 1)

    def test_workspace_fingerprint_tracks_file_content_and_ignores_git_metadata(self):
        operation_id = self.operation["operation_id"]
        before = get_task_workspace_fingerprint(self.app.state.store, operation_id)
        self.assertTrue(before["complete"])
        self.assertEqual(len(before["fingerprint"]), 64)
        (self.task_root / "fingerprint.txt").write_text("first state")
        after = get_task_workspace_fingerprint(self.app.state.store, operation_id)
        self.assertTrue(after["complete"])
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        (self.task_root / "fingerprint.txt").write_text("second state")
        changed = get_task_workspace_fingerprint(self.app.state.store, operation_id)
        self.assertNotEqual(after["fingerprint"], changed["fingerprint"])

    def test_workspace_fingerprint_fails_closed_on_symlinks(self):
        operation_id = self.operation["operation_id"]
        target = self.root / "outside-target.txt"
        target.write_text("outside")
        (self.task_root / "outside-link").symlink_to(target)
        result = get_task_workspace_fingerprint(self.app.state.store, operation_id)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["fingerprint"])

    def test_invalid_file_paths_are_rejected(self):
        status, body = request(
            self.app,
            "/api/v1/task-workspaces/" + self.operation["operation_id"] + "/file?path=..%2Foutside",
        )
        self.assertEqual(status, 404)
        self.assertIn("detail", body)



    def test_review_joins_only_matching_run_plan_and_execution_verification_evidence(self):
        from evo_core import orchestration

        operation_id = self.operation["operation_id"]
        project_id = self.operation["project_id"]
        task_workspace_id = self.operation["task_workspace_id"]
        proposal = {
            "title": "Reviewable task", "summary": "A task with deterministic checks.",
            "steps": [{
                "title": "Implement", "description": "Make the change.",
                "expected_outcome": "The change is ready.", "verification": "Run tests.",
                "verification_commands": [["python", "-m", "unittest"]],
            }],
        }
        with self.app.state.lab_db.lock:
            plan = orchestration.create_plan(
                self.app.state.lab_db.connection, "Implement and verify", workspace=str(self.root),
                workspace_id=self.operation["parent_workspace_id"], project_id=project_id, proposal=proposal,
                allowed_commands=None, store=self.app.state.store,
            )
            orchestration.approve_plan(self.app.state.lab_db.connection, plan["id"])
            run_metadata = {
                "project_id": project_id, "workspace_id": task_workspace_id,
                "parent_workspace_id": self.operation["parent_workspace_id"],
                "task_workspace_operation_id": operation_id,
                "task_workspace_source_revision": self.operation["source_revision"],
                "plan_id": plan["id"], "verification_state": "passed",
            }
            run_id = self.app.state.store.start_agent_run("orchestrated", run_metadata)
            orchestration.attach_run(self.app.state.lab_db.connection, plan["id"], run_id)
            step_id = plan["steps"][0]["id"]
            execution_id = "execution-123"
            self.app.state.lab_db.connection.execute(
                """INSERT INTO workload_executions
                   (id,agent_run_id,workspace_id,project_id,approval_evidence_json,
                    source_revision,cancel_requested,requested_at,argv_json,policy_json,
                    workspace,status,timeout_seconds,started_at,finished_at,returncode,
                    elapsed_seconds,stdout,stderr,error,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (execution_id, run_id, task_workspace_id, project_id, "{}",
                 self.operation["source_revision"], 0, "2026-11-28T12:00:00+00:00",
                 json.dumps(["python", "-m", "unittest"]), json.dumps([["python"]]),
                 str(self.task_root), "completed", 120, "2026-11-28T12:00:00+00:00",
                 "2026-11-28T12:00:02+00:00", 0, 2.0, "OK", "", "",
                 "2026-11-28T12:00:00+00:00"),
            )
            self.app.state.lab_db.connection.commit()
            orchestration.record_verification(
                self.app.state.lab_db.connection, plan["id"], step_id,
                ["python", "-m", "unittest"], "passed", 0, "S" * 9000, "E" * 9000,
                execution_id=execution_id,
                workspace_fingerprint_before="a" * 64,
                workspace_fingerprint_after="a" * 64,
                workspace_snapshot_stable=True,
            )

        status, review = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/review")
        self.assertEqual(status, 200)
        self.assertEqual(len(review["execution_evidence"]), 1)
        evidence = review["execution_evidence"][0]
        self.assertEqual(evidence["run_id"], run_id)
        self.assertEqual(evidence["plan_id"], plan["id"])
        self.assertEqual(len(evidence["managed_executions"]), 1)
        run_execution = evidence["managed_executions"][0]
        self.assertEqual(run_execution["id"], "execution-123")
        self.assertEqual(run_execution["argv"], ["python", "-m", "unittest"])
        self.assertEqual(run_execution["effective_command_policy"], [["python"]])
        self.assertEqual(run_execution["working_directory"], str(self.task_root))
        self.assertEqual(run_execution["source_revision"], self.operation["source_revision"])
        self.assertEqual(run_execution["stdout"], "OK")
        self.assertFalse(run_execution["stdout_truncated"])
        self.assertEqual(run_execution["returncode"], 0)
        self.assertEqual(evidence["managed_executions_omitted"], 0)
        self.assertEqual(evidence["verification_summary"]["passed"], 1)
        self.assertEqual(evidence["verification_evidence_summary"]["command_coverage_state"], "passed")
        self.assertEqual(evidence["verification_evidence_summary"]["configured_commands"], 1)
        self.assertEqual(evidence["verification_evidence_summary"]["recorded_checks"], 1)
        self.assertEqual(evidence["verification_evidence_summary"]["invalid_checks"], 0)
        self.assertEqual(evidence["verification_evidence_summary"]["unrecorded_commands"], 0)
        check = evidence["steps"][0]["verification_checks"][0]
        self.assertEqual(check["execution_id"], "execution-123")
        managed = check["managed_execution"]
        self.assertEqual(managed["id"], "execution-123")
        self.assertEqual(managed["argv"], ["python", "-m", "unittest"])
        self.assertEqual(managed["effective_command_policy"], [["python"]])
        self.assertEqual(managed["working_directory"], str(self.task_root))
        self.assertEqual(managed["source_revision"], self.operation["source_revision"])
        self.assertEqual(managed["timeout_seconds"], 120)
        self.assertEqual(managed["returncode"], 0)
        self.assertEqual(check["status"], "passed")
        self.assertEqual(len(check["stdout"]), 8192)
        self.assertTrue(check["stdout_truncated"])
        self.assertEqual(check["stdout"][-20:], "S" * 20)
        self.assertEqual(len(check["stderr"]), 8192)
        self.assertTrue(check["stderr_truncated"])
        self.assertEqual(check["stderr"][-20:], "E" * 20)
        self.assertEqual(check["workspace_fingerprint_before"], "a" * 64)
        self.assertEqual(check["workspace_fingerprint_after"], "a" * 64)
        self.assertTrue(check["workspace_snapshot_stable"])

        with self.app.state.lab_db.lock:
            self.app.state.lab_db.connection.execute(
                "UPDATE workload_executions SET workspace=? WHERE id=?",
                (str(self.root), "execution-123"),
            )
            self.app.state.lab_db.connection.commit()
        status, mismatched_review = request(
            self.app, "/api/v1/task-workspaces/" + operation_id + "/review")
        self.assertEqual(status, 200)
        mismatched_check = mismatched_review["execution_evidence"][0]["steps"][0]["verification_checks"][0]
        self.assertEqual(mismatched_check["execution_id"], "execution-123")
        self.assertIsNone(mismatched_check["managed_execution"])
        self.assertEqual(mismatched_review["execution_evidence"][0]["managed_executions"], [])

    def test_review_does_not_join_runs_with_mismatched_task_provenance(self):
        operation_id = self.operation["operation_id"]
        run_id = self.app.state.store.start_agent_run("coding", {
            "project_id": self.operation["project_id"],
            "workspace_id": self.operation["task_workspace_id"],
            "task_workspace_operation_id": operation_id,
            "task_workspace_source_revision": "0" * 40,
        })
        status, review = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/review")
        self.assertEqual(status, 200)
        self.assertEqual(review["execution_evidence"], [])

    def test_apply_route_requires_approval_and_records_change(self):
        operation_id = self.operation["operation_id"]
        path = "/api/v1/task-workspaces/" + operation_id + "/file"
        status, body = request(self.app, path, method="POST", payload={
            "path": "new.txt", "content": "created by explicit approval",
            "approved": False,
        })
        self.assertEqual(status, 409)
        self.assertFalse((self.task_root / "new.txt").exists())
        status, body = request(self.app, path, method="POST", payload={
            "path": "new.txt", "content": "created by explicit approval",
            "approved": True,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "applied")
        self.assertEqual((self.task_root / "new.txt").read_text(), "created by explicit approval")
        self.assertIsNone(body["before_sha256"])
        status, history = request(self.app, "/api/v1/task-workspaces/" + operation_id + "/changes")
        self.assertEqual(status, 200)
        self.assertEqual(history["items"][0]["change_id"], body["change_id"])
        self.assertEqual(history["items"][0]["status"], "applied")
        self.assertEqual(history["total"], 1)
        self.assertFalse(history["truncated"])

    def test_isolated_coding_agent_write_execution_and_review_pipeline(self):
        """Exercise the real task-workspace write, managed command, and review join."""
        from evo_core.coding_agent import CodingAgent

        class ToolProvider:
            def __init__(self):
                self.responses = [
                    {"content": "", "tool_calls": [{
                        "id": "write-1", "type": "function",
                        "function": {"name": "write_file", "arguments": {
                            "path": "generated.py", "content": "VALUE = 42\n",
                        }},
                    }]},
                    {"content": "", "tool_calls": [{
                        "id": "test-write-1", "type": "function",
                        "function": {"name": "write_file", "arguments": {
                            "path": "test_generated.py",
                            "content": "import unittest\nfrom generated import VALUE\n\nclass GeneratedValueTests(unittest.TestCase):\n    def test_generated_value(self):\n        self.assertEqual(VALUE, 42)\n",
                        }},
                    }]},
                    {"content": "", "tool_calls": [{
                        "id": "check-1", "type": "function",
                        "function": {"name": "run_command", "arguments": {
                            "argv": ["python", "-m", "unittest"],
                        }},
                    }]},
                    {"content": "Implemented the isolated change and ran its check.",
                     "tool_calls": []},
                ]

            def chat(self, messages, max_tokens, temperature, on_token=None, tools=None):
                return self.responses.pop(0)

        operation = self.operation
        source_head = self._git(self.source, "rev-parse", "HEAD")
        source_status = self._git(self.source, "status", "--porcelain")
        run_id = self.app.state.store.start_agent_run("coding", {
            "project_id": operation["project_id"],
            "workspace_id": operation["task_workspace_id"],
            "parent_workspace_id": operation["parent_workspace_id"],
            "task_workspace_operation_id": operation["operation_id"],
            "task_workspace_source_revision": operation["source_revision"],
        })
        assistant = self.app.state.assistant
        previous_provider = assistant.provider
        assistant.provider = ToolProvider()
        try:
            agent = CodingAgent(
                assistant, self.task_root,
                allowed_commands=[["python", "-m", "unittest"]],
                task_workspace_operation_id=operation["operation_id"],
            )
            conversation_id = assistant.new_conversation(
                project_id=operation["project_id"],
                workspace_id=operation["task_workspace_id"],
            )
            result = agent.run(
                conversation_id, "Create generated.py, add a unit test, and run the unit tests.",
                lambda name, args: True,
                run_id=run_id,
                project_id=operation["project_id"],
                workspace_id=operation["task_workspace_id"],
                source_revision=operation["source_revision"],
            )
        finally:
            assistant.provider = previous_provider

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["verification"], "passed")
        self.assertEqual((self.task_root / "generated.py").read_text(), "VALUE = 42\n")
        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), source_head)
        self.assertEqual(self._git(self.source, "status", "--porcelain"), source_status)

        status, review = request(
            self.app, "/api/v1/task-workspaces/" + operation["operation_id"] + "/review",
        )
        self.assertEqual(status, 200)
        self.assertEqual(review["status"], "ok")
        self.assertIn("generated.py", {item["path"] for item in review["changed_files"]})
        self.assertIn("test_generated.py", {item["path"] for item in review["changed_files"]})
        self.assertEqual(review["file_change_summary"]["applied"], 2)
        evidence = [item for item in review["execution_evidence"] if item["run_id"] == run_id]
        self.assertEqual(len(evidence), 1)
        executions = evidence[0]["managed_executions"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["argv"], ["python", "-m", "unittest"])
        self.assertEqual(executions[0]["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
