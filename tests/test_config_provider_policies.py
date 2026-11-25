import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evo_core.config import load_config
from evo_core.provider_approvals import ProviderApprovalError, find_provider_approval, parse_provider_approvals


BASE_CONFIG = """
[server]
base_url = "http://127.0.0.1:18997"
api_key = "no-key"
model = "local-model"

[security]
allowed_provider_origins = ["https://api.example.test"]

[secrets]
allowed_env_vars = ["EVO_TEST_KEY"]
"""


class OperatorProviderPolicyConfigTests(unittest.TestCase):
    def _load(self, text):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "config.toml"
        path.write_text(text, encoding="utf-8")
        try:
            return load_config(path), temp
        except Exception:
            temp.cleanup()
            raise

    def test_loads_exact_origins_and_secret_name_allowlist(self):
        config, temp = self._load(BASE_CONFIG)
        try:
            self.assertEqual(config.allowed_provider_origins, ("https://api.example.test",))
            self.assertEqual(config.allowed_secret_env_vars, ("EVO_TEST_KEY",))
            self.assertEqual(config.provider_approvals, ())
        finally:
            temp.cleanup()

    def test_rejects_wildcards_and_non_loopback_http_origins(self):
        for origin in ("https://*.example.test", "http://api.example.test"):
            with self.subTest(origin=origin):
                text = BASE_CONFIG.replace('"https://api.example.test"', repr(origin))
                temp = tempfile.TemporaryDirectory()
                path = Path(temp.name) / "config.toml"
                path.write_text(text, encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        load_config(path)
                finally:
                    temp.cleanup()

    def test_rejects_duplicate_origins_and_invalid_secret_names(self):
        cases = (
            BASE_CONFIG.replace(
                '["https://api.example.test"]',
                '["https://api.example.test", "https://api.example.test:443"]',
            ),
            BASE_CONFIG.replace('["EVO_TEST_KEY"]', '["BAD-NAME"]'),
        )
        for text in cases:
            with self.subTest(text=text):
                temp = tempfile.TemporaryDirectory()
                path = Path(temp.name) / "config.toml"
                path.write_text(text, encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        load_config(path)
                finally:
                    temp.cleanup()

    def test_loads_explicit_remote_compliance_approval(self):
        text = BASE_CONFIG + """
[[provider_approvals]]
origin = "https://api.example.test"
adapter_id = "openai_compatible_chat"
uses = ["chat_completion"]
status = "approved"
reviewed_at = "2026-11-23"
terms_reference = "terms-v3"
data_handling_reference = "handling-v2"
"""
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "config.toml"
        path.write_text(text, encoding="utf-8")
        try:
            config = load_config(path)
            approval = find_provider_approval(
                config.provider_approvals,
                "https://api.example.test:443",
                "openai_compatible_chat",
                "chat_completion",
            )
            self.assertIsNotNone(approval)
            self.assertEqual(approval.status, "approved")
        finally:
            temp.cleanup()

    def test_absent_approval_remains_unknown(self):
        self.assertIsNone(
            find_provider_approval(
                (), "https://api.example.test", "openai_compatible_chat", "chat_completion"
            )
        )

    def test_loopback_requires_explicit_local_only_classification(self):
        record = {
            "origin": "http://127.0.0.1:18997",
            "adapter_id": "openai_compatible_chat",
            "uses": ["chat_completion"],
            "status": "local_only",
            "reviewed_at": "2026-11-23",
            "data_handling_reference": "local inference verified",
        }
        parsed = parse_provider_approvals([record])
        self.assertEqual(parsed[0].status, "local_only")
        record["status"] = "approved"
        record["terms_reference"] = "terms"
        with self.assertRaises(ProviderApprovalError):
            parse_provider_approvals([record])

    def test_rejects_duplicate_approval_and_unknown_adapter_or_use(self):
        record = {
            "origin": "https://api.example.test",
            "adapter_id": "openai_compatible_chat",
            "uses": ["chat_completion"],
            "status": "approved",
            "reviewed_at": "2026-11-23",
            "terms_reference": "terms",
            "data_handling_reference": "handling",
        }
        with self.assertRaises(ProviderApprovalError):
            parse_provider_approvals([record, record])
        unknown_adapter = dict(record, adapter_id="custom.python")
        with self.assertRaises(ProviderApprovalError):
            parse_provider_approvals([unknown_adapter])
        unknown_use = dict(record, uses=["execute_shell"])
        with self.assertRaises(ProviderApprovalError):
            parse_provider_approvals([unknown_use])


if __name__ == "__main__":
    unittest.main()
