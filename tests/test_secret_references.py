import unittest

from evo_core.secret_references import SecretResolutionError, resolve_secret_references


class SecretReferenceTests(unittest.TestCase):
    def test_allowlisted_environment_reference_resolves(self):
        result = resolve_secret_references(
            {"api_key": "env:EVO_TEST_KEY"},
            ["EVO_TEST_KEY"],
            environ={"EVO_TEST_KEY": "secret-value"},
        )
        self.assertEqual(result["api_key"], "secret-value")
        self.assertNotIn("secret-value", repr(result.keys()))

    def test_non_allowlisted_reference_fails_closed(self):
        with self.assertRaises(SecretResolutionError):
            resolve_secret_references(
                {"api_key": "env:EVO_TEST_KEY"},
                [],
                environ={"EVO_TEST_KEY": "secret-value"},
            )

    def test_missing_and_empty_secrets_fail_closed(self):
        for environ in ({}, {"EVO_TEST_KEY": ""}):
            with self.subTest(environ=environ):
                with self.assertRaises(SecretResolutionError):
                    resolve_secret_references(
                        {"api_key": "env:EVO_TEST_KEY"},
                        ["EVO_TEST_KEY"],
                        environ=environ,
                    )

    def test_malformed_references_and_unknown_secret_slots_fail(self):
        for references in (
            {"api_key": "file:/tmp/key"},
            {"password": "env:EVO_TEST_KEY"},
            {"api_key": "env:BAD-NAME"},
        ):
            with self.subTest(references=references):
                with self.assertRaises(SecretResolutionError):
                    resolve_secret_references(
                        references,
                        ["EVO_TEST_KEY"],
                        environ={"EVO_TEST_KEY": "secret-value"},
                    )

    def test_invalid_operator_allowlist_fails(self):
        with self.assertRaises(SecretResolutionError):
            resolve_secret_references({}, "EVO_TEST_KEY", environ={})
        with self.assertRaises(SecretResolutionError):
            resolve_secret_references({}, ["BAD-NAME"], environ={})

    def test_returned_mapping_is_read_only(self):
        result = resolve_secret_references(
            {"api_key": "env:EVO_TEST_KEY"},
            ["EVO_TEST_KEY"],
            environ={"EVO_TEST_KEY": "secret-value"},
        )
        with self.assertRaises(TypeError):
            result["api_key"] = "replacement"


if __name__ == "__main__":
    unittest.main()
