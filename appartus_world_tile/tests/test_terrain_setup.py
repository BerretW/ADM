import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from awt.material import TerrainMaterial
from awt.roads import Road
from awt.terrain_presets import list_presets, load_preset, save_preset
from awt.terrain_setup import apply_profile


class TerrainSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.heights = np.linspace(-20.0, 900.0, 10000, dtype=np.float32).reshape(100, 100)

    def test_profiles_fit_known_biome_bands_and_keep_surface_assets(self):
        material = TerrainMaterial()
        texture = os.path.join(self.tmp.name, "grass.png")
        Image.new("RGB", (4, 4), (70, 120, 45)).save(texture)
        material.surface("grass").albedo = texture

        levels = apply_profile(material, self.heights, "alpine")

        mountains = next(biome for biome in material.biomes if biome.name == "mountains")
        self.assertAlmostEqual(mountains.height.min, levels["snow_start_m"])
        self.assertEqual(material.surface("grass").albedo, texture)
        material.validate()

    def test_arid_profile_uses_sand_and_places_snow_above_the_heightmap(self):
        material = TerrainMaterial()

        levels = apply_profile(material, self.heights, "arid")

        self.assertEqual(material.biomes[0].surfaces[0].surface, "sand")
        self.assertGreater(levels["snow_start_m"], float(self.heights.max()))
        material.validate_rules()

    def test_preset_copies_textures_and_excludes_map_specific_paint(self):
        material = TerrainMaterial()
        texture = os.path.join(self.tmp.name, "albedo.png")
        Image.new("RGB", (8, 8), (45, 80, 120)).save(texture)
        material.surface("grass").albedo = texture
        material.ensure_paint(8, 8)
        material.paint[0, 0] = 1
        material.ensure_surface_paint(8, 8)
        material.surface_paint[0, 0] = 1
        material.roads = [Road("soil", 4, 2, [[0, 0, 1], [7, 7, 2]])]
        material.biomes[0].noise = 0.65

        folder = save_preset(os.path.join(self.tmp.name, "presets"), "Alpine World", material)
        presets = list_presets(os.path.dirname(folder))
        loaded = load_preset(os.path.dirname(folder), presets[0][1])

        copied = loaded.surface("grass").albedo
        self.assertTrue(copied.startswith(os.path.join(folder, "textures")))
        self.assertTrue(os.path.isfile(copied))
        self.assertIsNone(loaded.paint)
        self.assertIsNone(loaded.surface_paint)
        self.assertEqual(loaded.roads, [])
        self.assertEqual(loaded.surface_names(), material.surface_names())
        self.assertEqual(loaded.biomes[0].surface_names(), material.biomes[0].surface_names())
        self.assertEqual(loaded.biomes[0].noise, 0.65)
        with open(os.path.join(folder, "preset.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 2)

    def test_advanced_shader_settings_round_trip_in_preset_version_three(self):
        material = TerrainMaterial()
        texture = os.path.join(self.tmp.name, "height.png")
        Image.fromarray(np.full((4, 4), 128, np.uint8)).save(texture)
        surface = material.surface("grass")
        surface.height_map.path = texture
        surface.height_scale = 0.35
        surface.ao_strength = 0.6
        material.height_blend_enabled = True
        material.parallax_mode = "PARALLAX"
        folder = save_preset(os.path.join(self.tmp.name, "presets"), "Layered", material)
        with open(os.path.join(folder, "preset.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 3)
        loaded = load_preset(os.path.dirname(folder), "layered")
        self.assertTrue(loaded.height_blend_enabled)
        self.assertEqual(loaded.parallax_mode, "PARALLAX")
        self.assertEqual(loaded.surface("grass").height_scale, 0.35)
        self.assertEqual(loaded.surface("grass").ao_strength, 0.6)
        self.assertTrue(loaded.surface("grass").height_map.path.startswith(os.path.join(folder, "textures")))

    def test_per_map_gpu_encodings_round_trip_in_preset_version_four(self):
        material = TerrainMaterial()
        material.surface("grass").gpu_encodings = {"albedo": "BC7", "height": "RGBA8"}
        folder = save_preset(os.path.join(self.tmp.name, "presets"), "GPU", material)
        with open(os.path.join(folder, "preset.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 4)
        loaded = load_preset(os.path.dirname(folder), "gpu")
        self.assertEqual(loaded.surface("grass").gpu_encodings, {"albedo": "BC7", "height": "RGBA8"})

    def test_preset_rejects_texture_paths_outside_its_directory(self):
        root = os.path.join(self.tmp.name, "presets")
        folder = save_preset(root, "safe", TerrainMaterial())
        path = os.path.join(folder, "preset.json")
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        document["material"]["surfaces"][0]["albedo"] = "..\\outside.png"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        with self.assertRaisesRegex(ValueError, "outside its folder"):
            load_preset(root, "safe")

    def test_duplicate_preset_needs_explicit_replacement(self):
        root = os.path.join(self.tmp.name, "presets")
        save_preset(root, "Terrain", TerrainMaterial())
        with self.assertRaises(FileExistsError):
            save_preset(root, "Terrain", TerrainMaterial())

