import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from evo_core.ai_configurations import (
    ConfigurationArchivedError,
    ConfigurationConflictError,
    ConfigurationNotFoundError,
    ConfigurationValidationError,
    archive_configuration,
    canonical_json,
    content_hash,
    create_configuration,
    create_revision,
    get_configuration,
    get_revision,
    list_configurations,
    list_revisions,
    reactivate_configuration,
    restore_revision,
    update_configuration,
    validate_definition,
)
from evo_core.platform_registry import initialize_platform_registry
from evo_core.store import EvoStore


def make_store(db_path):
    store = EvoStore(db_path)
    initialize_platform_registry(store)
    return store


VALID_DEFINITION = {
    "schema_version": 1,
    "components": {
        "model": {"provider": "p", "model": "m", "settings": {"context_window": 8}, "secret_refs": {"api_key": "ref"}},
        "agents": {"roles": []},
    },
    "extensions": {"x": 1},
}


class ValidationTests(unittest.TestCase):
    def test_valid_minimal(self):
        d = validate_definition({"schema_version": 1, "components": {}})
        self.assertEqual(d["schema_version"], 1)
        self.assertEqual(d["components"], {})

    def test_valid_extensible(self):
        d = validate_definition(VALID_DEFINITION)
        self.assertIn("model", d["components"])

    def test_missing_schema_version(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"components": {}})

    def test_unsupported_schema_version(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 2, "components": {}})

    def test_bool_schema_version(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": True, "components": {}})

    def test_float_schema_version(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1.0, "components": {}})

    def test_string_schema_version(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": "1", "components": {}})

    def test_missing_components(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1})

    def test_non_object_components(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": []})

    def test_empty_component_name(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"": {}}})

    def test_whitespace_component_name(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"   ": {}}})

    def test_non_object_component_value(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": "b"}})

    def test_unknown_top_level_key(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {}, "foo": 1})

    def test_invalid_extensions(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {}, "extensions": "x"})

    def test_duplicate_json_keys(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition('{"schema_version": 1, "schema_version": 1, "components": {}}')

    def test_nan_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"v": float("nan")}}})

    def test_infinity_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"v": float("inf")}}})

    def test_non_json_value_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"v": object()}}})

    def test_sensitive_key_rejected(self):
        for key in ("api_key", "password", "access_token", "refresh_token", "client_secret", "private_key", "secret"):
            with self.subTest(key=key):
                with self.assertRaises(ConfigurationValidationError):
                    validate_definition({"schema_version": 1, "components": {"a": {key: "value"}}})

    def test_secret_references_accepted(self):
        d = validate_definition({"schema_version": 1, "components": {"a": {"api_key_ref": "ref", "secret_ref": "ref", "secret_refs": {"k": "ref"}}}})
        self.assertIn("api_key_ref", d["components"]["a"])

    def test_caller_mutation_does_not_alter_normalized(self):
        original = {"schema_version": 1, "components": {"a": {"n": 1}}}
        normalized = validate_definition(original)
        original["components"]["a"]["n"] = 999
        self.assertEqual(normalized["components"]["a"]["n"], 1)

    def test_non_object_definition(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition("not an object")
        with self.assertRaises(ConfigurationValidationError):
            validate_definition(42)

    def test_non_string_json_text(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition(123)


class CanonicalizationTests(unittest.TestCase):
    def test_key_order_independence(self):
        a = {"schema_version": 1, "components": {"z": {"b": 2, "a": 1}}}
        b = {"schema_version": 1, "components": {"z": {"a": 1, "b": 2}}}
        self.assertEqual(canonical_json(validate_definition(a)), canonical_json(validate_definition(b)))

    def test_stable_hash(self):
        d = validate_definition(VALID_DEFINITION)
        self.assertEqual(content_hash(d), content_hash(validate_definition(VALID_DEFINITION)))

    def test_changed_value_changes_hash(self):
        d1 = validate_definition(VALID_DEFINITION)
        changed = copy.deepcopy(VALID_DEFINITION)
        changed["components"]["model"]["settings"]["context_window"] = 16
        d2 = validate_definition(changed)
        self.assertNotEqual(content_hash(d1), content_hash(d2))

    def test_parse_text_duplicate_keys(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition('{"schema_version": 1, "components": {}, "components": {}}')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_create_and_read(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg", change_summary="init")
        cfg = result["configuration"]
        rev = result["revision"]
        self.assertEqual(cfg["status"], "active")
        self.assertEqual(cfg["version"], 1)
        self.assertEqual(rev["revision_number"], 1)
        self.assertIsNone(rev["parent_revision_id"])
        fetched = get_configuration(self.store, cfg["configuration_id"])
        self.assertEqual(fetched["configuration_id"], cfg["configuration_id"])
        self.assertEqual(fetched["current_revision"]["revision_id"], rev["revision_id"])
        revs = list_revisions(self.store, cfg["configuration_id"])
        self.assertEqual(len(revs), 1)
        self.assertEqual(revs[0]["revision_number"], 1)

    def test_list_configurations(self):
        create_configuration(self.store, VALID_DEFINITION, name="a")
        create_configuration(self.store, VALID_DEFINITION, name="b")
        configs = list_configurations(self.store)
        self.assertEqual(len(configs), 2)

    def test_update_appends_revision(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        rev2_def = copy.deepcopy(VALID_DEFINITION)
        rev2_def["components"]["model"]["settings"]["context_window"] = 16
        new_rev = create_revision(
            self.store, cfg_id, rev2_def, expected_version=1, change_summary="update"
        )
        self.assertEqual(new_rev["revision_number"], 2)
        self.assertEqual(new_rev["parent_revision_id"], result["revision"]["revision_id"])
        old_rev = get_revision(self.store, cfg_id, result["revision"]["revision_id"])
        self.assertEqual(old_rev["definition"]["components"]["model"]["settings"]["context_window"], 8)
        current = get_configuration(self.store, cfg_id)
        self.assertEqual(current["current_revision_id"], new_rev["revision_id"])
        self.assertEqual(current["version"], 2)

    def test_restore_appends_revision(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        rev1_id = result["revision"]["revision_id"]
        rev2 = create_revision(self.store, cfg_id, copy.deepcopy(VALID_DEFINITION), expected_version=1)
        restored = restore_revision(self.store, cfg_id, rev1_id, expected_version=2, change_summary="restore")
        self.assertEqual(restored["revision_number"], 3)
        self.assertEqual(restored["parent_revision_id"], rev2["revision_id"])
        rev1 = get_revision(self.store, cfg_id, rev1_id)
        self.assertEqual(rev1["content_hash"], restored["content_hash"])

    def test_restore_other_configuration_rejected(self):
        r1 = create_configuration(self.store, VALID_DEFINITION, name="cfg1")
        r2 = create_configuration(self.store, VALID_DEFINITION, name="cfg2")
        with self.assertRaises(ConfigurationNotFoundError):
            restore_revision(
                self.store, r2["configuration"]["configuration_id"], r1["revision"]["revision_id"], expected_version=1
            )

    def test_archive_reactivate(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        archived = archive_configuration(self.store, cfg_id, expected_version=1)
        self.assertEqual(archived["status"], "archived")
        with self.assertRaises(ConfigurationArchivedError):
            create_revision(self.store, cfg_id, VALID_DEFINITION, expected_version=2)
        reactivated = reactivate_configuration(self.store, cfg_id, expected_version=2)
        self.assertEqual(reactivated["status"], "active")

    def test_stale_conflicts(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        with self.assertRaises(ConfigurationConflictError):
            create_revision(self.store, cfg_id, VALID_DEFINITION, expected_version=999)
        with self.assertRaises(ConfigurationConflictError):
            archive_configuration(self.store, cfg_id, expected_version=999)
        # state unchanged
        current = get_configuration(self.store, cfg_id)
        self.assertEqual(current["version"], 1)

    def test_stale_restore_leaves_no_revision(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        before = len(list_revisions(self.store, cfg_id))
        with self.assertRaises(ConfigurationConflictError):
            restore_revision(self.store, cfg_id, result["revision"]["revision_id"], expected_version=999)
        after = len(list_revisions(self.store, cfg_id))
        self.assertEqual(before, after)

    def test_update_configuration_metadata(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]
        updated = update_configuration(self.store, cfg_id, {"name": "new", "description": "desc"}, expected_version=1)
        self.assertEqual(updated["name"], "new")
        self.assertEqual(updated["description"], "desc")
        self.assertEqual(updated["version"], 2)

    def test_injected_failure_create_rolls_back(self):
        # Use a proxy to fail during revision insert.
        class FailingDB:
            def __init__(self, real):
                self._real = real
                self.in_transaction = False

            def __getattr__(self, name):
                return getattr(self._real, name)

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO ai_configuration_revisions" in sql:
                    raise RuntimeError("boom")
                return self._real.execute(sql, *args, **kwargs)

        store = self.store
        original_db = store.db
        proxy = FailingDB(original_db)
        store.db = proxy
        try:
            with self.assertRaises(RuntimeError):
                create_configuration(store, VALID_DEFINITION, name="cfg")
        finally:
            store.db = original_db
        count = original_db.execute("SELECT COUNT(*) FROM ai_configurations").fetchone()[0]
        self.assertEqual(count, 0)
        rev_count = original_db.execute("SELECT COUNT(*) FROM ai_configuration_revisions").fetchone()[0]
        self.assertEqual(rev_count, 0)

    def test_injected_failure_update_rolls_back(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg = result["configuration"]
        cfg_id = cfg["configuration_id"]

        class FailingDB:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO ai_configuration_revisions" in sql:
                    raise RuntimeError("boom")
                return self._real.execute(sql, *args, **kwargs)

        original_db = self.store.db
        proxy = FailingDB(original_db)
        self.store.db = proxy
        try:
            with self.assertRaises(RuntimeError):
                create_revision(self.store, cfg_id, VALID_DEFINITION, expected_version=1)
        finally:
            self.store.db = original_db
        revs = list_revisions(self.store, cfg_id)
        self.assertEqual(len(revs), 1)
        current = get_configuration(self.store, cfg_id)
        self.assertEqual(current["version"], 1)

    def test_persistence_survives_reopen(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        cfg_id = result["configuration"]["configuration_id"]
        self.store.db.close()
        reopened = EvoStore(self.db_path)
        initialize_platform_registry(reopened)
        cfg = get_configuration(reopened, cfg_id)
        self.assertEqual(cfg["configuration_id"], cfg_id)
        reopened.db.close()

    def test_invalid_definition_creates_no_partial_record(self):
        before = self.store.db.execute("SELECT COUNT(*) FROM ai_configurations").fetchone()[0]
        with self.assertRaises(ConfigurationValidationError):
            create_configuration(self.store, {"schema_version": 1, "components": {"a": {"api_key": "secret"}}}, name="cfg")
        after = self.store.db.execute("SELECT COUNT(*) FROM ai_configurations").fetchone()[0]
        self.assertEqual(before, after)


class CanonicalHashPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_persisted_hash_matches(self):
        result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        rev = result["revision"]
        self.assertEqual(rev["content_hash"], content_hash(rev["definition"]))
        self.assertEqual(canonical_json(rev["definition"]), rev["definition_json"] if "definition_json" in rev else canonical_json(rev["definition"]))
        stored = self.store.db.execute(
            "SELECT definition_json, content_hash FROM ai_configuration_revisions WHERE revision_id=?",
            (rev["revision_id"],),
        ).fetchone()
        self.assertEqual(stored["content_hash"], content_hash(json.loads(stored["definition_json"])))



class SecretReferenceTests(unittest.TestCase):
    def test_valid_secret_ref(self):
        d = validate_definition({"schema_version": 1, "components": {"a": {"secret_ref": "ref:1"}}})
        self.assertEqual(d["components"]["a"]["secret_ref"], "ref:1")

    def test_valid_secret_refs(self):
        d = validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": {"api_key": "ref:1", "token": "ref:2"}}}})
        self.assertEqual(d["components"]["a"]["secret_refs"]["api_key"], "ref:1")

    def test_secret_ref_non_string_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_ref": 123}}})

    def test_secret_ref_empty_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_ref": "   "}}})

    def test_secret_refs_non_mapping_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": "ref"}}})

    def test_secret_refs_empty_key_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": {"": "ref"}}}})

    def test_secret_refs_non_string_value_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": {"k": 1}}}})

    def test_nested_object_in_secret_refs_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": {"k": {"nested": "x"}}}}})

    def test_hidden_credential_in_secret_refs_value_string_allowed(self):
        # Values are references by contract; keys are reference names.
        d = validate_definition({"schema_version": 1, "components": {"a": {"secret_refs": {"password": "ref:pw"}}}})
        self.assertEqual(d["components"]["a"]["secret_refs"]["password"], "ref:pw")

    def test_sensitive_key_elsewhere_rejected(self):
        with self.assertRaises(ConfigurationValidationError):
            validate_definition({"schema_version": 1, "components": {"a": {"password": "x"}}})


class DirectImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)
        self.result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        self.cfg_id = self.result["configuration"]["configuration_id"]
        self.rev_id = self.result["revision"]["revision_id"]

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_direct_update_rejected(self):
        before = get_revision(self.store, self.cfg_id, self.rev_id)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "UPDATE ai_configuration_revisions SET change_summary='x' WHERE revision_id=?",
                        (self.rev_id,),
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise
        after = get_revision(self.store, self.cfg_id, self.rev_id)
        self.assertEqual(before["change_summary"], after["change_summary"])
        self.assertEqual(before["content_hash"], after["content_hash"])
        self.assertEqual(before["revision_number"], after["revision_number"])
        self.assertEqual(before["parent_revision_id"], after["parent_revision_id"])

    def test_direct_delete_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "DELETE FROM ai_configuration_revisions WHERE revision_id=?", (self.rev_id,)
                    )
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise
        rev = get_revision(self.store, self.cfg_id, self.rev_id)
        self.assertIsNotNone(rev)


class ExpectedVersionStrictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)
        self.result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        self.cfg_id = self.result["configuration"]["configuration_id"]

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def _invalid_values(self):
        return [True, False, 1.0, "1", 0, -1, None]

    def test_create_revision_invalid_expected_version(self):
        for value in self._invalid_values():
            with self.subTest(value=value):
                before = len(list_revisions(self.store, self.cfg_id))
                with self.assertRaises(ConfigurationValidationError):
                    create_revision(self.store, self.cfg_id, VALID_DEFINITION, expected_version=value)
                after = len(list_revisions(self.store, self.cfg_id))
                self.assertEqual(before, after)

    def test_restore_invalid_expected_version(self):
        rev_id = self.result["revision"]["revision_id"]
        for value in self._invalid_values():
            with self.subTest(value=value):
                before = len(list_revisions(self.store, self.cfg_id))
                with self.assertRaises(ConfigurationValidationError):
                    restore_revision(self.store, self.cfg_id, rev_id, expected_version=value)
                after = len(list_revisions(self.store, self.cfg_id))
                self.assertEqual(before, after)

    def test_archive_invalid_expected_version(self):
        for value in self._invalid_values():
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationValidationError):
                    archive_configuration(self.store, self.cfg_id, expected_version=value)
        cfg = get_configuration(self.store, self.cfg_id)
        self.assertEqual(cfg["status"], "active")

    def test_reactivate_invalid_expected_version(self):
        archive_configuration(self.store, self.cfg_id, expected_version=1)
        for value in self._invalid_values():
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationValidationError):
                    reactivate_configuration(self.store, self.cfg_id, expected_version=value)
        cfg = get_configuration(self.store, self.cfg_id)
        self.assertEqual(cfg["status"], "archived")

    def test_update_invalid_expected_version(self):
        for value in self._invalid_values():
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationValidationError):
                    update_configuration(self.store, self.cfg_id, {"name": "x"}, expected_version=value)
        cfg = get_configuration(self.store, self.cfg_id)
        self.assertEqual(cfg["name"], "cfg")


class MetadataValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)
        self.result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        self.cfg_id = self.result["configuration"]["configuration_id"]

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_create_invalid_name_type(self):
        with self.assertRaises(ConfigurationValidationError):
            create_configuration(self.store, VALID_DEFINITION, name=123)

    def test_create_invalid_description_type(self):
        with self.assertRaises(ConfigurationValidationError):
            create_configuration(self.store, VALID_DEFINITION, description=123)

    def test_create_invalid_change_summary_type(self):
        with self.assertRaises(ConfigurationValidationError):
            create_configuration(self.store, VALID_DEFINITION, change_summary=123)

    def test_revision_invalid_change_summary_type(self):
        with self.assertRaises(ConfigurationValidationError):
            create_revision(self.store, self.cfg_id, VALID_DEFINITION, expected_version=1, change_summary=123)

    def test_update_invalid_name_type(self):
        with self.assertRaises(ConfigurationValidationError):
            update_configuration(self.store, self.cfg_id, {"name": 123}, expected_version=1)

    def test_update_invalid_description_type(self):
        with self.assertRaises(ConfigurationValidationError):
            update_configuration(self.store, self.cfg_id, {"description": 123}, expected_version=1)


class ReadLockConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cfg.sqlite3"
        self.store = make_store(self.db_path)
        self.result = create_configuration(self.store, VALID_DEFINITION, name="cfg")
        self.cfg_id = self.result["configuration"]["configuration_id"]

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_read_waits_for_write_transaction(self):
        import threading

        barrier = threading.Barrier(2)
        reader_started = threading.Event()
        reader_finished = threading.Event()
        holding = threading.Event()
        read_result = {}

        def writer():
            barrier.wait()
            with self.store.lock:
                self.store.db.execute("BEGIN IMMEDIATE")
                try:
                    self.store.db.execute(
                        "UPDATE ai_configurations SET name=? WHERE configuration_id=?",
                        ("changed", self.cfg_id),
                    )
                    holding.set()
                    reader_started.wait(timeout=2.0)
                    self.store.db.commit()
                except Exception:
                    self.store.db.rollback()
                    raise

        def reader():
            barrier.wait()
            holding.wait(timeout=2.0)
            reader_started.set()
            try:
                read_result["value"] = list_configurations(self.store)
            finally:
                reader_finished.set()

        t_writer = threading.Thread(target=writer)
        t_reader = threading.Thread(target=reader)
        t_writer.start()
        t_reader.start()
        t_writer.join()
        self.assertTrue(reader_finished.wait(timeout=2.0))
        self.assertTrue(any(c["name"] == "changed" for c in read_result["value"]))
        t_reader.join()


if __name__ == "__main__":
    unittest.main()
