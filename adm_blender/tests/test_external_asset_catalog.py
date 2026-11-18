"""Focused tests for external-asset discovery and rights gates."""

import json
from pathlib import Path
import unittest
from unittest.mock import mock_open, patch

from adm_blender.tests.external_asset_catalog import discover, permission


class ExternalAssetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("model.FBX")

    def check_manifest(self, **overrides):
        data = {"asset": self.path.name, "source": "Created by test",
                "license": "Test license", "permission_for_local_testing": True}
        data.update(overrides)
        with patch.object(Path, "open", mock_open(read_data=json.dumps(data))):
            return permission(self.path)

    def test_discovery_is_case_insensitive_and_missing_formats_are_empty(self):
        with patch.object(Path, "is_dir", return_value=True), \
                patch.object(Path, "iterdir", return_value=[self.path]), \
                patch.object(Path, "is_file", return_value=True):
            found = discover("assets")
        self.assertEqual(found["FBX"], [self.path])
        self.assertEqual(found["ADM"], [])
        self.assertEqual(found["BLEND"], [])
        self.assertEqual(found["ADM_ANIM"], [])

    def test_missing_and_malformed_manifests_are_skipped(self):
        with patch.object(Path, "open", side_effect=FileNotFoundError):
            self.assertFalse(permission(self.path)[0])
        with patch.object(Path, "open", mock_open(read_data="{")):
            self.assertFalse(permission(self.path)[0])

    def test_explicit_asset_specific_permission_is_required(self):
        for overrides in ({"asset": "another.FBX"}, {"permission_for_local_testing": False},
                          {"permission_for_local_testing": "true"}, {"license": "unknown"},
                          {"license": "License unknown"},
                          {"license": "License name or description of permission"},
                          {"source": ""}):
            with self.subTest(overrides=overrides):
                self.assertFalse(self.check_manifest(**overrides)[0])
        self.assertTrue(self.check_manifest()[0])


if __name__ == "__main__":
    unittest.main()
