import unittest

from evo_core.command_policy import (
    CommandPolicyError,
    effective_project_command_prefixes,
    intersect_command_prefixes,
    project_command_prefixes,
)


class CommandPolicyTests(unittest.TestCase):
    def revision(self, policy_marker=True, policy=None):
        components = {}
        if policy_marker:
            components["command_policy"] = policy
        return {"definition": {"schema_version": 1, "components": components}}

    def test_project_policy_can_only_narrow_global_prefixes(self):
        global_policy = (("python",), ("git", "status"), ("pytest",))
        project_policy = self.revision(policy={"allowed_commands": [
            ["python", "-m", "unittest"],
            ["git"],
            ["npm", "test"],
        ]})
        effective = effective_project_command_prefixes(global_policy, project_policy)
        self.assertEqual(
            effective,
            (("python", "-m", "unittest"), ("git", "status")),
        )

    def test_missing_project_policy_denies_all_project_commands(self):
        self.assertEqual(
            effective_project_command_prefixes(
                (("python",),), self.revision(policy_marker=False)
            ),
            (),
        )

    def test_explicit_empty_project_policy_denies_all(self):
        self.assertEqual(
            effective_project_command_prefixes(
                (("python",),), self.revision(policy={"allowed_commands": []})
            ),
            (),
        )

    def test_empty_global_policy_denies_even_broad_project_policy(self):
        self.assertEqual(
            effective_project_command_prefixes(
                (), self.revision(policy={"allowed_commands": [["python"]]})
            ),
            (),
        )

    def test_incomparable_prefixes_have_empty_intersection(self):
        self.assertEqual(
            intersect_command_prefixes(
                (("python", "-m"),), (("python", "-c"),)
            ),
            (),
        )

    def test_project_policy_rejects_unknown_fields(self):
        with self.assertRaises(CommandPolicyError):
            project_command_prefixes(
                self.revision(policy={"allowed_commands": [["python"]], "mode": "allow"})
            )

    def test_project_policy_rejects_malformed_prefixes(self):
        for malformed in (None, "python", [["python", ""]], [["python", "\x00"]], [[]]):
            with self.subTest(malformed=malformed):
                with self.assertRaises(CommandPolicyError):
                    project_command_prefixes(
                        self.revision(policy={"allowed_commands": malformed})
                    )

    def test_invalid_revision_fails_closed(self):
        for revision in (None, {}, {"definition_json": "not-json"},
                         {"definition": {"components": []}}):
            with self.subTest(revision=revision):
                with self.assertRaises(CommandPolicyError):
                    project_command_prefixes(revision)


    def test_schema2_policy_reads_typed_settings_and_only_narrows(self):
        revision = {
            "definition": {
                "schema_version": 2,
                "components": {
                    "model": {
                        "type": "model", "component_version": 1,
                        "adapter": {"id": "openai_compatible_chat", "contract_version": 1},
                        "settings": {
                            "endpoint": "http://127.0.0.1:18997/v1",
                            "model": "local", "timeout_seconds": 30,
                        },
                    },
                    "assistant": {
                        "type": "assistant_runtime", "component_version": 1,
                        "adapter": {"id": "evo_assistant_runtime", "contract_version": 1},
                        "settings": {
                            "model_component": "model", "persona_prompt": "",
                            "max_output_tokens": 1024, "temperature": 0.2,
                            "context_window_tokens": 8192, "history_messages": 8,
                            "max_history_chars": 8000, "memory_limit": 4,
                        },
                    },
                    "restrictions": {
                        "type": "command_policy", "component_version": 1,
                        "adapter": {"id": "evo_command_policy", "contract_version": 1},
                        "settings": {"allowed_commands": [["pytest"], ["python", "-m", "unittest"]]},
                    },
                },
                "entrypoints": {"assistant": "assistant"},
            }
        }
        self.assertEqual(
            effective_project_command_prefixes((("python",), ("git",)), revision),
            (("python", "-m", "unittest"),),
        )

    def test_schema2_malformed_command_component_fails_closed(self):
        revision = {
            "definition": {
                "schema_version": 2,
                "components": {"command_policy": {"type": "command_policy", "settings": {"allowed_commands": [["python"]]}}},
                "entrypoints": {"assistant": "command_policy"},
            }
        }
        with self.assertRaises(CommandPolicyError):
            project_command_prefixes(revision)


if __name__ == "__main__":
    unittest.main()
