import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from awt.material import Surface, TerrainMaterial, prepare_texture
from awt.material_set_import import (MAP_NAMES, apply_material_sets, resolve_material_set,
                                     scan_material_sets, validate_material_set_files)


class MaterialSetImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _image(self, relative, mode="RGB", color=(80, 120, 60), image_format="PNG"):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new(mode, (8, 8), color).save(path, image_format)
        return path

    def test_scan_groups_recursively_ignores_packed_and_unknown_maps(self):
        albedo = self._image(os.path.join("wood", "rock_01_ABTE.weird"))
        normal = self._image(os.path.join("wood", "nested", "rock_01_nm"))
        packed = self._image(os.path.join("wood", "rock_01_ma.dds"))
        unknown = self._image(os.path.join("wood", "rock_01_unknown.png"))
        scan = scan_material_sets(self.root)

        self.assertEqual([item.name for item in scan.sets], ["rock_01"])
        item = scan.sets[0]
        self.assertEqual(item.files["albedo"], (albedo,))
        self.assertEqual(item.files["normal"], (normal,))
        self.assertEqual(item.packed_maps, (packed,))
        self.assertEqual(scan.ignored_packed_files, (packed,))
        self.assertIn(unknown, scan.unknown_files)
        self.assertEqual(item.missing_maps, ("ao", "roughness", "metallic", "height", "emission"))
        validate_material_set_files(item, resolve_material_set(item, {}))

    def test_scan_reports_conflicts_deterministically_and_accepts_custom_suffixes(self):
        self._image("sub/rock_albedo.png")
        second = self._image("rock_diffuse.tga")
        configured = {name: ("custom_" + name,) for name in MAP_NAMES}
        configured["albedo"] = ("_albedo", "_diffuse")
        configured["metallic"] = ""
        unknown_metallic = self._image("gear_metallic.png")
        scan = scan_material_sets(self.root, configured)

        self.assertEqual(len(scan.sets), 1)
        item = scan.sets[0]
        self.assertEqual(item.name, "rock")
        actual = [os.path.relpath(path, scan.root).replace("\\", "/") for path in item.files["albedo"]]
        self.assertEqual(actual, ["rock_diffuse.tga", "sub/rock_albedo.png"])
        self.assertEqual(item.conflicts, ("albedo",))
        self.assertIn(unknown_metallic, scan.unknown_files)
        with self.assertRaisesRegex(ValueError, "Choose one albedo"):
            resolve_material_set(item, {})
        resolved = resolve_material_set(item, {("rock", "albedo"): second})
        self.assertEqual(resolved["albedo"], second)
        validate_material_set_files(item, resolved)

    def test_apply_preserves_existing_surfaces_and_updates_only_found_maps(self):
        old_albedo = self._image("old.png", color=(1, 2, 3))
        old_normal = self._image("old_normal.png", color=(128, 128, 255))
        replacement = self._image("rock_albedo.png", color=(9, 8, 7))
        new_albedo = self._image("sand_albedo.png", color=(4, 5, 6))
        existing = Surface("rock", albedo=old_albedo, normal=old_normal)
        material = TerrainMaterial(surfaces=[existing])
        scan = scan_material_sets(self.root)

        result = apply_material_sets(material, scan, {"rock", "sand"})
        self.assertEqual(result, {"added": 1, "updated": 0, "skipped": 1})
        self.assertEqual(existing.albedo, old_albedo)
        self.assertEqual(existing.normal, old_normal)
        self.assertEqual(material.surface("sand").albedo, new_albedo)

        result = apply_material_sets(material, scan, {"rock"}, update_existing=True)
        self.assertEqual(result, {"added": 0, "updated": 1, "skipped": 0})
        self.assertEqual(existing.albedo, replacement)
        self.assertEqual(existing.normal, old_normal)

    def test_unresolved_conflict_does_not_mutate_material(self):
        first = self._image("rock_albedo.png")
        self._image("rock_diffuse.png")
        material = TerrainMaterial(surfaces=[Surface("existing")])
        before = material.surface_names()
        scan = scan_material_sets(self.root)

        with self.assertRaisesRegex(ValueError, "Choose one albedo"):
            apply_material_sets(material, scan, {"rock"})
        self.assertEqual(material.surface_names(), before)
        choices = {("rock", "albedo"): first}
        self.assertEqual(apply_material_sets(material, scan, {"rock"}, choices)["added"], 1)

    def test_texture_byte_and_pixel_limits_are_checked_before_decode(self):
        path = self._image("large.png")
        with patch("awt.material.MAX_TEXTURE_BYTES", 4):
            with self.assertRaisesRegex(ValueError, "Texture file is larger"):
                prepare_texture(path)
        with patch("awt.material.MAX_TEXTURE_PIXELS", 10):
            with self.assertRaisesRegex(ValueError, "pixel limit"):
                prepare_texture(path)

    def test_scanner_caps_directory_entries(self):
        self._image("first_albedo.png")
        self._image("second_albedo.png")
        with patch("awt.material_set_import.MAX_MATERIAL_SET_ENTRIES", 1):
            with self.assertRaisesRegex(ValueError, "more than 1 entries"):
                scan_material_sets(self.root)

    def test_selected_texture_must_remain_inside_scanned_directory(self):
        image = self._image("rock_albedo.png")
        scan = scan_material_sets(self.root)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        external_path = os.path.join(outside.name, "external.png")
        Image.new("RGB", (4, 4)).save(external_path)

        with self.assertRaisesRegex(ValueError, "outside the selected directory"):
            validate_material_set_files(scan.sets[0], {"albedo": external_path})
        self.assertTrue(os.path.isfile(image))

    def test_import_rejects_unsupported_source_format_by_content(self):
        path = self._image("rock_albedo.jpg", image_format="JPEG")
        item = scan_material_sets(self.root).sets[0]
        with self.assertRaisesRegex(ValueError, "Unsupported texture format 'JPEG'"):
            validate_material_set_files(item, {"albedo": path})

    def test_tiff_and_tga_sources_are_validated_by_content(self):
        for name, image_format in (("tiff", "TIFF"), ("tga", "TGA")):
            path = self._image(f"{name}_albedo.not-an-image-extension", image_format=image_format)
            item = next(candidate for candidate in scan_material_sets(self.root).sets
                        if candidate.name == name)
            validate_material_set_files(item, {"albedo": path})

