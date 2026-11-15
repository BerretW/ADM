import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from awt.adm_export import INDEX_NAME, ExportSettings, _core, changed_tiles, export_tiles
from awt.material import TerrainMaterial
from awt.pipeline import BuildParams, build, load_manifest
from awt.project import Project, load_project
from tests.test_pipeline import _terrain


def _read_adm(path):
    _buffers, constants, container, _validate = _core()
    with open(path, "rb") as handle:
        doc, chunks = container.read_container(handle.read(), constants.ADM_MAGIC)[:2]
    return doc, chunks


def _accessor(doc, chunks, index):
    from adm_blender.core.buffers import read_accessor_np

    return np.asarray(read_accessor_np(doc, chunks, index))


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src.npy")
        np.save(self.src, _terrain(49, 65))
        self.params = BuildParams(input_path=self.src, out_dir=os.path.join(self.tmp.name, "build"),
                                  tile_cells=32, max_errors_m=[0.2, 1.0], spacing_m=2.0)
        build(self.params)
        self.manifest = load_manifest(self.params.out_dir)
        self.material = TerrainMaterial()
        self.albedo = os.path.join(self.tmp.name, "grass albedo.tga")
        Image.new("RGB", (8, 8), (90, 140, 60)).save(self.albedo)
        self.packed = os.path.join(self.tmp.name, "rock_ma.png")
        Image.new("RGBA", (8, 8), (10, 200, 30, 255)).save(self.packed)
        self.normal = os.path.join(self.tmp.name, "rock_n.png")
        Image.new("RGB", (8, 8), (128, 128, 255)).save(self.normal)
        self.material.layers[0].albedo = self.albedo
        self.material.layers[1].roughness_map.path = self.packed
        self.material.layers[1].roughness_map.channel = 1
        self.material.layers[1].roughness_map.invert = True
        self.material.layers[1].normal = self.normal
        self.settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "adm"))

    def test_tiles_validate_and_keep_world_placement(self):
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(self.manifest["tiles"]))
        textures = os.listdir(os.path.join(self.settings.out_dir, "textures"))
        self.assertEqual(len(textures), 3)  # shared once, TGA converted to PNG
        self.assertTrue(any(name.startswith("grass_albedo_") and name.endswith(".png") for name in textures))

        tile = next(t for t in self.manifest["tiles"] if t["id"] == "x001_y000")
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, "x001_y000.adm"))
        self.assertEqual(doc["extensionsRequired"], ["ADM_external_images_v1"])
        params = doc["materials"][0]["shaderParameters"]
        self.assertEqual(doc["materials"][0]["shader"]["id"], "adm.terrain.four_layer")
        self.assertEqual(params["layer1_roughness_channel"], 1.0)
        self.assertTrue(params["layer1_roughness_invert"])
        self.assertEqual(params["blend_mask"]["texCoord"], 1)
        self.assertEqual(params["uv_scale"], [16.0] * 4)  # 64 m tile / 4 m repeat
        self.assertEqual([level["minDistance"] for level in doc["lodGroups"][0]["levels"]], [0.0, 64.0])

        root = doc["nodes"][0]
        mesh = doc["meshes"][0]["primitives"][0]
        position = _accessor(doc, chunks, mesh["attributes"]["POSITION"]) + np.array(root["translation"])
        normal = _accessor(doc, chunks, mesh["attributes"]["NORMAL"])
        tangent = _accessor(doc, chunks, mesh["attributes"]["TANGENT"])
        uv0 = _accessor(doc, chunks, mesh["attributes"]["TEXCOORD_0"])
        faces = _accessor(doc, chunks, mesh["indices"]).reshape(-1, 3)
        # World X east, ADM -Z north: the tile covers x 64..128, north edge z = -(origin y + size y).
        x0, y0 = tile["origin_m"][:2]
        self.assertAlmostEqual(float(position[:, 0].min()), x0, places=3)
        self.assertAlmostEqual(float(position[:, 2].min()), -(y0 + tile["size_m"][1]), places=3)
        north_west = np.argmin(position[:, 0] + position[:, 2])
        self.assertTrue(np.allclose(uv0[north_west], [0.0, 0.0]))  # top-left of the texture
        a, b, c = (position[faces[:, k]] for k in range(3))
        face_normal = np.cross(b - a, c - a)
        self.assertTrue(np.all(face_normal[:, 1] > 0))  # front faces look up
        self.assertTrue(np.all(normal[:, 1] > 0))
        bitangent = np.cross(normal, tangent[:, :3]) * tangent[:, 3:]
        self.assertTrue(np.all(bitangent[:, 2] < 0))  # +V of the normal map points north

    def test_changed_only_export_follows_geometry_and_material(self):
        export_tiles(self.manifest, self.material, self.settings, "changed")
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        again = export_tiles(self.manifest, self.material, self.settings, "changed")
        self.assertEqual(again["written"], [])

        self.material.layers[2].roughness = 0.3
        self.assertEqual(len(changed_tiles(self.manifest, self.material, self.settings)),
                         len(self.manifest["tiles"]))
        export_tiles(self.manifest, self.material, self.settings)

        # Raise the north-east corner only: just that tile changes.
        data = _terrain(49, 65)
        data[:8, -8:] += 30.0
        np.save(self.src, data)
        build(self.params)
        manifest = load_manifest(self.params.out_dir)
        self.assertEqual(changed_tiles(manifest, self.material, self.settings), ["x001_y001"])

        os.remove(os.path.join(self.settings.out_dir, "x000_y000.adm"))
        self.assertIn("x000_y000", changed_tiles(manifest, self.material, self.settings))
        result = export_tiles(manifest, self.material, self.settings, "selected", ["x000_y000"])
        self.assertEqual(result["written"], ["x000_y000"])
        with open(os.path.join(self.settings.out_dir, INDEX_NAME), encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)["tiles"]), len(manifest["tiles"]))

    def test_embedded_textures_and_single_lod(self):
        self.params.max_errors_m = [0.5]
        build(self.params)
        manifest = load_manifest(self.params.out_dir)
        self.settings.embed_textures = True
        export_tiles(manifest, self.material, self.settings, "all")
        doc, _chunks = _read_adm(os.path.join(self.settings.out_dir, "x000_y000.adm"))
        self.assertNotIn("extensionsUsed", doc)
        self.assertNotIn("lodGroups", doc)
        self.assertEqual(doc["nodes"][0]["mesh"], 0)
        self.assertTrue(all("bufferView" in image for image in doc["images"]))
        self.assertFalse(os.path.exists(os.path.join(self.settings.out_dir, "textures")))

    def test_project_round_trip_uses_relative_paths(self):
        project = Project.new(self.src)
        project.params = self.params
        project.material = self.material
        project.export = self.settings
        project.selection = ["x001_y000"]
        path = os.path.join(self.tmp.name, "world.awtp")
        project.save(path)
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["build"]["input_path"], "src.npy")
        self.assertEqual(raw["material"]["layers"][0]["albedo"], "grass albedo.tga")

        loaded = load_project(path)
        self.assertEqual(loaded.params, self.params)
        self.assertEqual(loaded.material, self.material)
        self.assertEqual(loaded.export, self.settings)
        self.assertEqual(loaded.selection, ["x001_y000"])
        with self.assertRaises(ValueError):
            Project.from_dict({"format": "something else"})

    def test_bake_keeps_north_up_and_layers_without_water(self):
        from awt.bake import bake

        tile = next(t for t in self.manifest["tiles"] if t["size_m"] == [64.0, 64.0])
        mask = np.zeros((16, 16, 4), np.uint8)
        mask[:8, :, 1] = 255  # north half rock, alpha (water) 0
        mask[8:, :, 3] = 255  # south half water
        Image.fromarray(mask, "RGBA").save(os.path.join(self.manifest["_dir"], tile["mask"]))
        material = TerrainMaterial()
        for layer, color in zip(material.layers, ([0, 255, 0], [255, 0, 0], [255, 255, 255], [0, 0, 255])):
            layer.color = color
        image, bbox = bake(self.manifest, material, [(tile["ix"], tile["iy"])])
        x0, y0 = tile["origin_m"][:2]
        self.assertEqual(bbox, (x0, y0, x0 + 64.0, y0 + 64.0))
        self.assertEqual(image[1, image.shape[1] // 2].tolist(), [255, 0, 0])
        self.assertEqual(image[-2, image.shape[1] // 2].tolist(), [0, 0, 255])


if __name__ == "__main__":
    unittest.main()
