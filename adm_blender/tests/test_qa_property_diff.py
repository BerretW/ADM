"""Tests for machine-readable ADM manifest property comparisons."""

import unittest

from adm_blender.core.qa_property_diff import compare_adm_manifests


class QaPropertyDiffTests(unittest.TestCase):
    def test_reports_added_removed_and_changed_semantic_properties(self):
        before = {
            "materials": [{"name": "Body", "roughness": 0.5, "oldFlag": True}],
            "nodes": [{"name": "Root"}],
        }
        after = {
            "materials": [{"name": "Body", "roughness": 0.75, "newFlag": True}],
            "nodes": [{"name": "Root", "translation": [0, 0, 1]}],
        }

        diff = compare_adm_manifests(before, after)

        self.assertEqual(diff["change_count"], 4)
        self.assertFalse(diff["truncated"])
        self.assertEqual(
            {(entry["path"], entry["change"]) for entry in diff["changes"]},
            {
                ("/materials/0/newFlag", "added"),
                ("/materials/0/oldFlag", "removed"),
                ("/materials/0/roughness", "changed"),
                ("/nodes/0/translation", "added"),
            },
        )

    def test_ignores_accessor_storage_but_keeps_manifest_properties(self):
        before = {
            "accessors": [{"count": 3, "bufferView": 0}],
            "bufferViews": [{"chunkId": 1}],
            "meshes": [{"primitives": [{
                "attributes": {"POSITION": 0},
                "material": 0,
            }]}],
            "materials": [{"name": "Body"}],
        }
        after = {
            "accessors": [{"count": 4, "bufferView": 7}],
            "bufferViews": [{"chunkId": 2}],
            "meshes": [{"primitives": [{
                "attributes": {"POSITION": 7},
                "material": 0,
            }]}],
            "materials": [{"name": "Body"}],
        }

        self.assertEqual(compare_adm_manifests(before, after)["changes"], [])

    def test_uses_numeric_tolerance_and_caps_reported_paths(self):
        before = {"nodes": [{"translation": [1.0, 2.0]}]}
        after = {"nodes": [{"translation": [1.0000001, 3.0], "name": "Root"}]}

        diff = compare_adm_manifests(before, after, max_changes=1)

        self.assertEqual(diff["change_count"], 2)
        self.assertTrue(diff["truncated"])
        self.assertEqual(len(diff["changes"]), 1)

    def test_rejects_invalid_manifests_and_limits(self):
        with self.assertRaises(TypeError):
            compare_adm_manifests([], {})
        with self.assertRaises(ValueError):
            compare_adm_manifests({}, {}, max_changes=0)


if __name__ == "__main__":
    unittest.main()
