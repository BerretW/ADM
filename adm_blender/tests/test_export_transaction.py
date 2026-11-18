"""Focused tests for staged, recoverable ADM model publication.

Run: blender -b --factory-startup --python-exit-code 1 --python adm_blender/tests/test_export_transaction.py
"""

import os
import hashlib
import json
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from adm_blender.blender import export_adm  # noqa: E402


FIXTURE = os.path.join(REPO, "adm-standard", "fixtures", "valid", "triangle.adm")
ADM_BYTES = open(FIXTURE, "rb").read()


class FakeExporter:
    data = ADM_BYTES
    external_files = {}
    armature = None

    def __init__(self, _context, _root, _options):
        self.mat = types.SimpleNamespace(external_root=None, external_files=dict(self.external_files))
        self.opts = types.SimpleNamespace(validate=True)
        self._committed_rig_ids = []
        if self.armature is not None:
            self.armature.data.adm.rig_id = "new-rig-id"
            self._committed_rig_ids.append((self.armature, "old-rig-id"))

    def export(self):
        return self.data, None

    rollback_rig_ids = export_adm.ModelExporter.rollback_rig_ids


class ExportTransactionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix=".adm_export_txn_", dir=REPO)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.model = os.path.join(self.root, "model.adm")

    def publish(self, textures=None, validator=None):
        with mock.patch.object(export_adm, "validate_adm_resolved",
                               side_effect=validator or (lambda _data, _path: types.SimpleNamespace(ok=True))):
            export_adm._publish_export_transaction(
                self.root, self.model, textures or {}, ADM_BYTES)

    def test_staging_failure_preserves_existing_model_and_sidecars(self):
        old_model = b"old model"
        old_texture = b"same"
        with open(self.model, "wb") as stream:
            stream.write(old_model)
        os.makedirs(os.path.join(self.root, "textures"))
        with open(os.path.join(self.root, "textures", "albedo.png"), "wb") as stream:
            stream.write(old_texture)
        with mock.patch.object(export_adm, "_write_synced", side_effect=OSError("injected staging failure")):
            with self.assertRaisesRegex(export_adm.ExportError, "staging failed"):
                self.publish({"textures/albedo.png": b"same"})
        with open(self.model, "rb") as stream:
            self.assertEqual(stream.read(), old_model)
        with open(os.path.join(self.root, "textures", "albedo.png"), "rb") as stream:
            self.assertEqual(stream.read(), old_texture)
        self.assertFalse(os.path.exists(os.path.join(self.root, export_adm._EXPORT_TXN_DIR)))

    def test_staged_bytes_are_validated_before_any_target_is_published(self):
        texture = b"staged external texture"
        published_state = []

        def validate(data, staged_model):
            staged_root = os.path.dirname(staged_model)
            self.assertEqual(open(staged_model, "rb").read(), data)
            self.assertEqual(open(os.path.join(staged_root, "textures", "a.png"), "rb").read(), texture)
            self.assertFalse(os.path.exists(self.model))
            published_state.append(True)
            return types.SimpleNamespace(ok=True)

        self.publish({"textures/a.png": texture}, validate)
        self.assertEqual(published_state, [True])
        self.assertEqual(open(self.model, "rb").read(), ADM_BYTES)
        self.assertEqual(open(os.path.join(self.root, "textures", "a.png"), "rb").read(), texture)

    def test_validation_failure_preserves_existing_targets(self):
        old_model = b"before validation"
        with open(self.model, "wb") as stream:
            stream.write(old_model)
        failure = types.SimpleNamespace(code="TEST", path="$", message="injected")
        with self.assertRaisesRegex(export_adm.ExportError, "resolved ADM validation"):
            self.publish({"textures/new.png": b"new texture"},
                         lambda _data, _path: types.SimpleNamespace(ok=False, errors=[failure]))
        self.assertEqual(open(self.model, "rb").read(), old_model)
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "new.png")))

    def test_same_content_sidecar_is_accepted_and_different_content_is_rejected(self):
        sidecar = os.path.join(self.root, "textures", "same.png")
        os.makedirs(os.path.dirname(sidecar))
        with open(sidecar, "wb") as stream:
            stream.write(b"identical")
        self.publish({"textures/same.png": b"identical"})
        self.assertEqual(open(sidecar, "rb").read(), b"identical")

        with open(self.model, "wb") as stream:
            stream.write(b"existing model")
        with self.assertRaisesRegex(export_adm.ExportError, "different content"):
            self.publish({"textures/same.png": b"different"})
        self.assertEqual(open(self.model, "rb").read(), b"existing model")
        self.assertEqual(open(sidecar, "rb").read(), b"identical")

    def test_publication_failure_restores_preexisting_model_and_removes_new_sidecars(self):
        old_model = b"preexisting model"
        with open(self.model, "wb") as stream:
            stream.write(old_model)
        original_replace = export_adm._replace_export_file
        calls = 0

        def fail_model_publish(source, target):
            nonlocal calls
            calls += 1
            if target == self.model:
                raise OSError("injected model publication failure")
            return original_replace(source, target)

        with mock.patch.object(export_adm, "validate_adm_resolved",
                               return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_replace_export_file", side_effect=fail_model_publish):
            with self.assertRaisesRegex(export_adm.ExportError, "previous outputs restored"):
                export_adm._publish_export_transaction(
                    self.root, self.model,
                    {"textures/a.png": b"new a", "textures/b.png": b"new b"}, ADM_BYTES)
        self.assertGreaterEqual(calls, 3)
        self.assertEqual(open(self.model, "rb").read(), old_model)
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "a.png")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "b.png")))

    def test_interrupted_publication_recovers_all_targets(self):
        old_model = b"old model"
        with open(self.model, "wb") as stream:
            stream.write(old_model)
        original_replace = export_adm._replace_export_file
        calls = 0

        def interrupt_after_first_publish(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return original_replace(source, target)

        with mock.patch.object(export_adm, "validate_adm_resolved",
                               return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_replace_export_file",
                                  side_effect=interrupt_after_first_publish):
            with self.assertRaises(KeyboardInterrupt):
                export_adm._publish_export_transaction(
                    self.root, self.model,
                    {"textures/a.png": b"new a", "textures/b.png": b"new b"}, ADM_BYTES)
        self.assertTrue(os.path.isfile(os.path.join(self.root, export_adm._EXPORT_TXN_DIR, "journal.json")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "textures", "a.png")))
        export_adm._recover_export_transaction(self.root)
        self.assertEqual(open(self.model, "rb").read(), old_model)
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "a.png")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "b.png")))
        self.assertFalse(os.path.exists(os.path.join(self.root, export_adm._EXPORT_TXN_DIR)))

    def test_rollback_failure_is_reported_and_recoverable(self):
        old_model = b"old model"
        with open(self.model, "wb") as stream:
            stream.write(old_model)
        original_journal = export_adm._write_transaction_journal
        original_replace = export_adm._replace_export_file

        def fail_commit_marker(transaction_dir, journal):
            if journal["state"] == "committed":
                raise OSError("injected commit marker failure")
            return original_journal(transaction_dir, journal)

        def fail_backup_restore(source, target):
            if os.path.basename(source).startswith(".adm-restore-"):
                raise OSError("injected rollback failure")
            return original_replace(source, target)

        with mock.patch.object(export_adm, "validate_adm_resolved",
                               return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_write_transaction_journal", side_effect=fail_commit_marker), \
                mock.patch.object(export_adm, "_replace_export_file", side_effect=fail_backup_restore):
            with self.assertRaisesRegex(export_adm.ExportError, "rollback failed"):
                export_adm._publish_export_transaction(
                    self.root, self.model, {"textures/new.png": b"texture"}, ADM_BYTES)
        export_adm._recover_export_transaction(self.root)
        self.assertEqual(open(self.model, "rb").read(), old_model)
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "new.png")))

    def test_recovery_failure_is_explicit(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        os.mkdir(transaction_dir)
        with open(os.path.join(transaction_dir, "journal.json"), "w", encoding="utf-8") as stream:
            stream.write('{"version":99,"state":"prepared","files":[]}')
        with self.assertRaisesRegex(export_adm.ExportError, "recovery failed"):
            export_adm._recover_export_transaction(self.root)

    def test_recovery_refuses_symlinked_transaction_directory(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        outside = tempfile.mkdtemp(prefix=".adm_export_outside_", dir=REPO)
        self.addCleanup(shutil.rmtree, outside, True)
        marker = os.path.join(outside, "keep.txt")
        with open(marker, "wb") as stream:
            stream.write(b"preserve")
        try:
            os.symlink(outside, transaction_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")
        with self.assertRaisesRegex(export_adm.ExportError, "symlinked transaction directory"):
            export_adm._recover_export_transaction(self.root)
        self.assertTrue(os.path.islink(transaction_dir))
        self.assertEqual(open(marker, "rb").read(), b"preserve")

    def test_recovery_refuses_transaction_directory_resolving_outside_root(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        os.mkdir(transaction_dir)
        journal_path = os.path.join(transaction_dir, "journal.json")
        with open(journal_path, "w", encoding="utf-8") as stream:
            stream.write('{"version":99,"state":"prepared","files":[]}')
        actual_realpath = os.path.realpath
        outside = os.path.join(REPO, "outside-transaction-dir")

        def redirected_realpath(path):
            if os.path.abspath(path) == os.path.abspath(transaction_dir):
                return outside
            return actual_realpath(path)

        with mock.patch.object(export_adm.os.path, "realpath", side_effect=redirected_realpath):
            with self.assertRaisesRegex(export_adm.ExportError, "symlinked transaction directory"):
                export_adm._recover_export_transaction(self.root)
        self.assertTrue(os.path.isfile(journal_path))

    def test_recovery_refuses_journal_resolving_outside_transaction_directory(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        os.mkdir(transaction_dir)
        journal_path = os.path.join(transaction_dir, "journal.json")
        with open(journal_path, "w", encoding="utf-8") as stream:
            stream.write('{"version":99,"state":"prepared","files":[]}')
        actual_realpath = os.path.realpath
        outside = os.path.join(REPO, "outside-journal.json")

        def redirected_realpath(path):
            if os.path.abspath(path) == os.path.abspath(journal_path):
                return outside
            return actual_realpath(path)

        with mock.patch.object(export_adm.os.path, "realpath", side_effect=redirected_realpath):
            with self.assertRaisesRegex(export_adm.ExportError, "symlinked journal"):
                export_adm._recover_export_transaction(self.root)
        self.assertTrue(os.path.isfile(journal_path))

    def test_recovery_rejects_journal_target_through_symlink_component(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        os.mkdir(transaction_dir)
        outside = tempfile.mkdtemp(prefix=".adm_export_outside_", dir=REPO)
        self.addCleanup(shutil.rmtree, outside, True)
        marker = os.path.join(outside, "victim.bin")
        with open(marker, "wb") as stream:
            stream.write(b"outside target")
        try:
            os.symlink(outside, os.path.join(self.root, "redirect"), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")
        journal = {
            "version": 1,
            "state": "prepared",
            "files": [{
                "target": "redirect/victim.bin",
                "staged": "staged/model.adm",
                "backup": None,
                "old_hash": None,
                "new_hash": hashlib.sha256(b"replacement").hexdigest(),
                "publish": True,
            }],
        }
        with open(os.path.join(transaction_dir, "journal.json"), "w", encoding="utf-8") as stream:
            json.dump(journal, stream)
        with self.assertRaisesRegex(export_adm.ExportError, "recovery failed"):
            export_adm._recover_export_transaction(self.root)
        self.assertTrue(os.path.isfile(os.path.join(transaction_dir, "journal.json")))
        self.assertEqual(open(marker, "rb").read(), b"outside target")

    def test_recovery_rejects_journal_target_resolving_outside_root(self):
        transaction_dir = os.path.join(self.root, export_adm._EXPORT_TXN_DIR)
        os.mkdir(transaction_dir)
        target = os.path.join(self.root, "redirect", "victim.bin")
        outside = os.path.join(REPO, "outside-target", "victim.bin")
        journal = {
            "version": 1,
            "state": "prepared",
            "files": [{
                "target": "redirect/victim.bin",
                "staged": "staged/model.adm",
                "backup": None,
                "old_hash": None,
                "new_hash": hashlib.sha256(b"replacement").hexdigest(),
                "publish": True,
            }],
        }
        journal_path = os.path.join(transaction_dir, "journal.json")
        with open(journal_path, "w", encoding="utf-8") as stream:
            json.dump(journal, stream)
        actual_realpath = os.path.realpath

        def redirected_realpath(path):
            if os.path.abspath(path) == os.path.abspath(target):
                return outside
            return actual_realpath(path)

        with mock.patch.object(export_adm.os.path, "realpath", side_effect=redirected_realpath):
            with self.assertRaisesRegex(export_adm.ExportError, "recovery failed"):
                export_adm._recover_export_transaction(self.root)
        self.assertTrue(os.path.isfile(journal_path))

    def test_directory_lock_prevents_concurrent_recovery_or_publication(self):
        with export_adm._ExportDirectoryLock(self.root):
            with self.assertRaisesRegex(export_adm.ExportError, "another ADM export is active"):
                with export_adm._ExportDirectoryLock(self.root):
                    pass
        with export_adm._ExportDirectoryLock(self.root):
            pass

    def test_publication_failure_rolls_back_source_rig_id(self):
        armature = types.SimpleNamespace(
            name="Rig",
            data=types.SimpleNamespace(adm=types.SimpleNamespace(rig_id="old-rig-id")))
        FakeExporter.armature = armature
        FakeExporter.external_files = {}
        original_replace = export_adm._replace_export_file

        def fail_publish(_source, _target):
            raise OSError("injected publication failure")

        with mock.patch.object(export_adm, "ModelExporter", FakeExporter), \
                mock.patch.object(export_adm, "validate_adm_resolved",
                                  return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_replace_export_file", side_effect=fail_publish):
            with self.assertRaises(export_adm.ExportError):
                export_adm.export_model(None, self.model)
        self.assertEqual(armature.data.adm.rig_id, "old-rig-id")
        FakeExporter.armature = None
        export_adm._recover_export_transaction(self.root)

    def test_resolved_validation_failure_rolls_back_source_rig_id(self):
        armature = types.SimpleNamespace(
            name="Rig",
            data=types.SimpleNamespace(adm=types.SimpleNamespace(rig_id="old-rig-id")))
        FakeExporter.armature = armature
        FakeExporter.external_files = {}
        issue = types.SimpleNamespace(code="TEST", path="$", message="injected")
        with mock.patch.object(export_adm, "ModelExporter", FakeExporter), \
                mock.patch.object(export_adm, "validate_adm_resolved",
                                  return_value=types.SimpleNamespace(ok=False, errors=[issue])):
            with self.assertRaisesRegex(export_adm.ExportError, "resolved ADM validation"):
                export_adm.export_model(None, self.model)
        self.assertEqual(armature.data.adm.rig_id, "old-rig-id")
        FakeExporter.armature = None

    def test_validation_failure_does_not_commit_pending_rig_id(self):
        armature = types.SimpleNamespace(
            name="Rig",
            data=types.SimpleNamespace(adm=types.SimpleNamespace(rig_id="old-rig-id")))
        exporter = object.__new__(export_adm.ModelExporter)

        def invalid_export():
            exporter._pending_rig_ids = [(armature, "new-rig-id")]
            raise export_adm.ExportError("validation failed")

        exporter._export = invalid_export
        with self.assertRaisesRegex(export_adm.ExportError, "validation failed"):
            exporter.export()
        self.assertEqual(armature.data.adm.rig_id, "old-rig-id")

    def test_baseexception_during_rig_id_commit_rolls_back_prior_assignments(self):
        class RigProperties:
            def __init__(self, value, fail_value=None):
                self._rig_id = value
                self.fail_value = fail_value

            @property
            def rig_id(self):
                return self._rig_id

            @rig_id.setter
            def rig_id(self, value):
                if value == self.fail_value:
                    raise KeyboardInterrupt("injected rigId commit interruption")
                self._rig_id = value

        def armature(name, value, fail_value=None):
            return types.SimpleNamespace(name=name, data=types.SimpleNamespace(
                adm=RigProperties(value, fail_value)))

        first = armature("first", "old-first")
        second = armature("second", "old-second", "new-second")
        exporter = object.__new__(export_adm.ModelExporter)
        exporter._pending_rig_ids = [(first, "new-first"), (second, "new-second")]
        exporter._committed_rig_ids = []
        with self.assertRaises(KeyboardInterrupt):
            exporter._commit_rig_ids()
        self.assertEqual(first.data.adm.rig_id, "old-first")
        self.assertEqual(second.data.adm.rig_id, "old-second")

    def test_baseexception_during_publication_rolls_back_source_rig_id(self):
        armature = types.SimpleNamespace(
            name="Rig",
            data=types.SimpleNamespace(adm=types.SimpleNamespace(rig_id="old-rig-id")))
        FakeExporter.armature = armature
        FakeExporter.external_files = {}

        def interrupt_publish(_source, _target):
            raise KeyboardInterrupt("injected publication interruption")

        with mock.patch.object(export_adm, "ModelExporter", FakeExporter), \
                mock.patch.object(export_adm, "validate_adm_resolved",
                                  return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_replace_export_file", side_effect=interrupt_publish):
            with self.assertRaises(KeyboardInterrupt):
                export_adm.export_model(None, self.model)
        self.assertEqual(armature.data.adm.rig_id, "old-rig-id")
        self.assertTrue(os.path.isfile(os.path.join(self.root, export_adm._EXPORT_TXN_DIR, "journal.json")))
        FakeExporter.armature = None
        export_adm._recover_export_transaction(self.root)

    def test_baseexception_cause_is_preserved_when_rigid_rollback_fails(self):
        class RigProperties:
            def __init__(self):
                self._rig_id = "old-rig-id"

            @property
            def rig_id(self):
                return self._rig_id

            @rig_id.setter
            def rig_id(self, value):
                if value == "old-rig-id":
                    raise KeyboardInterrupt("injected rollback interruption")
                self._rig_id = value

        armature = types.SimpleNamespace(
            name="Rig", data=types.SimpleNamespace(adm=RigProperties()))
        FakeExporter.armature = armature
        FakeExporter.external_files = {}

        def interrupt_publish(_source, _target):
            raise KeyboardInterrupt("injected publication interruption")

        with mock.patch.object(export_adm, "ModelExporter", FakeExporter), \
                mock.patch.object(export_adm, "validate_adm_resolved",
                                  return_value=types.SimpleNamespace(ok=True)), \
                mock.patch.object(export_adm, "_replace_export_file", side_effect=interrupt_publish):
            with self.assertRaisesRegex(export_adm.ExportError, "rigId rollback failed") as raised:
                export_adm.export_model(None, self.model)
        self.assertIsInstance(raised.exception.__cause__, KeyboardInterrupt)
        FakeExporter.armature = None
        export_adm._recover_export_transaction(self.root)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportTransactionTests))
    if not result.wasSuccessful():
        raise RuntimeError("export transaction tests failed")
