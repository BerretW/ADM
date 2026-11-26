import json
import io
import os
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image

from awt.adm_export import (INDEX_NAME, ExportSettings, _core, changed_tiles, color1, export_tiles, group_masks,
                            prepare_adm_texture, rules_outdated, triangle_masks)
from awt.material import Biome, BiomeSurface, TerrainMaterial, prepare_texture
from awt.pipeline import BuildParams, build, load_manifest
from awt.ply import read_ply, weight_fields, write_ply
from awt.project import Project, load_project
from awt.roads import Road
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
        self.material = TerrainMaterial()
        build(self.params, self.material)
        self.manifest = load_manifest(self.params.out_dir)
        self.albedo = os.path.join(self.tmp.name, "grass albedo.tga")
        Image.new("RGB", (8, 8), (90, 140, 60)).save(self.albedo)
        self.packed = os.path.join(self.tmp.name, "rock_ma.png")
        Image.new("RGBA", (8, 8), (10, 200, 30, 255)).save(self.packed)
        self.normal = os.path.join(self.tmp.name, "rock_n.png")
        Image.new("RGB", (8, 8), (128, 128, 255)).save(self.normal)
        rock = self.material.surface("rock")
        self.material.surface("grass").albedo = self.albedo
        self.material.surface("grass").normal = self.normal
        rock.roughness_map.path = self.packed
        rock.roughness_map.channel = 1
        rock.roughness_map.invert = True
        rock.normal = self.normal
        self.settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "adm"))

    def _primitives(self, doc, chunks, mesh=0):
        out = []
        for prim in doc["meshes"][mesh]["primitives"]:
            attrs = {name: _accessor(doc, chunks, index) for name, index in prim["attributes"].items()}
            out.append((prim, attrs, _accessor(doc, chunks, prim["indices"]).reshape(-1, 3)))
        return out

    def test_biome_noise_requires_rebuild_and_is_exported(self):
        self.material.biomes = [Biome("plain", surfaces=[BiomeSurface("grass"), BiomeSurface("soil")])]
        np.save(self.src, np.zeros((33, 33), np.float32))
        self.params.max_errors_m = [0.2]
        self.params.texture_detail_m = 2.0
        build(self.params, self.material)
        before = load_manifest(self.params.out_dir)
        self.material.biomes[0].noise = 1
        self.assertTrue(rules_outdated(before, self.material))
        self.assertTrue(export_tiles(before, self.material, self.settings, "all")["warnings"])
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        self.assertFalse(rules_outdated(manifest, self.material))
        self.assertFalse(export_tiles(manifest, self.material, self.settings, "all")["warnings"])
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, "x000_y000.adm"))
        colors = np.concatenate([attrs["COLOR_1"] for _, attrs, _ in self._primitives(doc, chunks)])
        self.assertGreater(float(np.ptp(colors[:, 0])), 0.1)
        self.assertTrue(np.any(colors[:, 1] > 0))

    def test_tiles_validate_and_keep_world_placement(self):
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(self.manifest["tiles"]))
        self.assertEqual(result["warnings"], [])
        textures = os.listdir(os.path.join(self.settings.out_dir, "textures"))
        self.assertEqual(len(textures), 6)  # three role-aware textures, each with a DDS and PNG
        self.assertTrue(any(name.startswith("grass_albedo_") and name.endswith(".dds") for name in textures))
        self.assertTrue(any(name.startswith("grass_albedo_") and name.endswith(".png") for name in textures))

        tile = next(t for t in self.manifest["tiles"] if t["id"] == "x001_y000")
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, "x001_y000.adm"))
        self.assertIn("ADM_external_images_v1", doc["extensionsRequired"])
        self.assertEqual(len(doc["extensionsRequired"]), 2)
        self.assertEqual([level["minDistance"] for level in doc["lodGroups"][0]["levels"]], [0.0, 64.0])
        names = self.manifest["texturing"]["surfaces"]
        for material in doc["materials"]:
            self.assertEqual(material["shader"]["id"], "adm.terrain.four_layer")
            self.assertEqual(material["shaderParameters"]["uv_scale"][0] > 0, True)
        self.assertEqual(len(doc["textures"]), len(doc["images"]) // 2)
        for texture in doc["textures"]:
            primary = doc["images"][texture["source"]]
            fallback = doc["images"][texture["fallbackSource"]]
            self.assertEqual(primary["mimeType"], "image/vnd-ms.dds")
            self.assertEqual(fallback["mimeType"], "image/png")
        rock_params = []
        for other in self.manifest["tiles"]:
            other_doc, _ = _read_adm(os.path.join(self.settings.out_dir, other["id"] + ".adm"))
            rock_params += [m["shaderParameters"] for m in other_doc["materials"]
                            if any(k.endswith("_roughness_texture") for k in m["shaderParameters"])]
        self.assertTrue(rock_params)
        for params in rock_params:
            slot = next(k for k in params if k.endswith("_roughness_texture")).split("_")[0]
            self.assertEqual(params[f"{slot}_roughness_channel"], 1.0)
            self.assertTrue(params[f"{slot}_roughness_invert"])
            self.assertEqual(params["uv_scale"][int(slot[5:])], 8.0)  # 64 m tile / 8 m rock repeat

        root = doc["nodes"][0]
        prims = self._primitives(doc, chunks)
        self.assertEqual(result["max_primitives"], max(len(m["primitives"]) for m in doc["meshes"]))
        position = np.concatenate([a["POSITION"] for _p, a, _f in prims]) + np.array(root["translation"])
        normal = np.concatenate([a["NORMAL"] for _p, a, _f in prims])
        tangent = np.concatenate([a["TANGENT"] for _p, a, _f in prims])
        uv0 = np.concatenate([a["TEXCOORD_0"] for _p, a, _f in prims])
        faces, base = [], 0
        for _p, attrs, f in prims:
            faces.append(f + base)
            base += len(attrs["POSITION"])
            color = attrs["COLOR_1"]
            self.assertEqual(color.shape[1], 4)
            total = color.astype(np.float64).sum(axis=1)
            self.assertTrue(np.all(np.abs(total - (255 if color.dtype == np.uint8 else 1.0))
                                   <= (2 if color.dtype == np.uint8 else 0.01)))
        faces = np.concatenate(faces)
        self.assertEqual(len(faces), tile["lods"][0]["triangles"])
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
        self.assertGreater(len(names), 4)

    def test_road_grade_is_exported_in_adm(self):
        self.material.roads = [Road("gravel", 8.0, 4.0, [[8, 24, 5], [56, 24, 17]])]
        self.params.max_errors_m = [0.0]
        self.params.texture_detail_m = 2.0
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        export_tiles(manifest, self.material, self.settings, "all")
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, "x001_y001.adm"))
        root = np.asarray(doc["nodes"][0]["translation"])
        positions = np.concatenate([attrs["POSITION"] for _, attrs, _ in self._primitives(doc, chunks)]) + root
        selected = positions[np.isclose(positions[:, 0], 64) & np.isclose(positions[:, 2], -48)]
        self.assertGreater(len(selected), 0)
        self.assertTrue(np.allclose(selected[:, 1], 11, atol=1e-4))

    def test_surface_sets_cover_triangles(self):
        weights = np.array([[255, 0, 0, 0, 0, 0],
                            [0, 255, 0, 0, 0, 0],
                            [0, 0, 255, 0, 0, 0],
                            [0, 60, 0, 40, 53, 102],
                            [0, 0, 0, 0, 255, 0]], np.uint8)
        faces = np.array([[0, 1, 2], [2, 3, 4]])
        bits, conflicts = triangle_masks(weights, faces)
        self.assertEqual(conflicts, 1)  # second triangle touches five surfaces
        self.assertEqual(bin(int(bits[1])).count("1"), 4)
        self.assertFalse(int(bits[1]) >> 3 & 1)  # the weakest surface (index 3) is dropped
        sets, assign = group_masks([0b0011, 0b0110, 0b110000, 0b1111])
        self.assertTrue(all(bin(s).count("1") <= 4 for s in sets))
        for mask, index in assign.items():
            self.assertEqual(mask & ~sets[index], 0)
        self.assertEqual(color1(weights[3:4], [4, 5]).tolist(), [[87, 168, 0, 0]])

    def test_changed_only_export_follows_geometry_and_material(self):
        export_tiles(self.manifest, self.material, self.settings, "changed")
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        again = export_tiles(self.manifest, self.material, self.settings, "changed")
        self.assertEqual(again["written"], [])

        self.material.surface("soil").roughness = 0.3
        self.assertEqual(len(changed_tiles(self.manifest, self.material, self.settings)),
                         len(self.manifest["tiles"]))
        export_tiles(self.manifest, self.material, self.settings)

        # Painting changes the rules the vertex weights came from: export warns until rebuilt.
        self.material.ensure_paint(65, 49)
        self.material.paint[:8, :8] = 1
        self.assertTrue(rules_outdated(self.manifest, self.material))
        self.assertTrue(export_tiles(self.manifest, self.material, self.settings, "selected",
                                     ["x000_y000"])["warnings"])
        self.material.paint = None
        self.assertFalse(rules_outdated(self.manifest, self.material))

        # Raise the north-east corner only: just that tile changes.
        data = _terrain(49, 65)
        data[:8, -8:] += 30.0
        np.save(self.src, data)
        build(self.params, self.material)
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
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        self.settings.embed_textures = True
        export_tiles(manifest, self.material, self.settings, "all")
        doc, _chunks = _read_adm(os.path.join(self.settings.out_dir, "x000_y000.adm"))
        self.assertNotIn("ADM_external_images_v1", doc["extensionsUsed"])
        self.assertNotIn("lodGroups", doc)
        self.assertEqual(doc["nodes"][0]["mesh"], 0)
        self.assertTrue(all("bufferView" in image for image in doc["images"]))
        self.assertFalse(os.path.exists(os.path.join(self.settings.out_dir, "textures")))

    def test_dx10_bc7_dds_is_decoded_and_transcoded_to_adm_dds_with_png_fallback(self):
        path = os.path.join(self.tmp.name, "bc7.dds")
        raw = bytearray(148 + 16)
        raw[:4] = b"DDS "
        struct.pack_into("<I", raw, 4, 124)
        struct.pack_into("<4I", raw, 8, 0x1007, 4, 4, 16)
        struct.pack_into("<I", raw, 76, 32)
        struct.pack_into("<I", raw, 80, 4)
        raw[84:88] = b"DX10"
        struct.pack_into("<I", raw, 108, 0x1000)
        struct.pack_into("<4I", raw, 128, 98, 3, 0, 1)
        raw[148:] = bytes([0x40]) + bytes(15)
        with open(path, "wb") as handle:
            handle.write(raw)

        prepared = prepare_texture(path)
        self.assertEqual(prepared.mime, "image/png")
        with Image.open(io.BytesIO(prepared.data)) as image:
            self.assertEqual(image.size, (4, 4))
            self.assertEqual(image.format, "PNG")
        from awt.bake import _albedo

        self.assertEqual(_albedo(path, 4).shape, (4, 4, 3))

        self.material.surface("grass").albedo = path
        export_tiles(self.manifest, self.material, self.settings, "all")
        exported = os.listdir(os.path.join(self.settings.out_dir, "textures"))
        dds = [name for name in exported if name.startswith("bc7_") and name.endswith(".dds")]
        png = [name for name in exported if name.startswith("bc7_") and name.endswith(".png")]
        self.assertEqual(len(dds), 1)
        self.assertEqual(len(png), 1)
        with Image.open(os.path.join(self.settings.out_dir, "textures", png[0])) as image:
            self.assertEqual(image.size, (4, 4))
        with open(os.path.join(self.settings.out_dir, "textures", dds[0]), "rb") as handle:
            from adm_blender.core import gputex

            info = gputex.parse(handle.read(), gputex.MIME_DDS, strict=True)
        self.assertIn(info["kind"], ("BC1", "BC3"))
        self.assertTrue(info["srgb"])

    def test_adm_compatible_dds_is_preserved_and_roles_select_color_space_and_format(self):
        _core()
        from adm_blender.core import gputex

        rgba = np.full((4, 4, 4), [150, 100, 50, 255], dtype=np.uint8)
        blob, _kind = gputex.encode(rgba, gputex.MIME_DDS, "BC1", srgb=True, mipmaps=False)
        path = os.path.join(self.tmp.name, "albedo.dds")
        with open(path, "wb") as handle:
            handle.write(blob)

        preserved = prepare_adm_texture(path, "albedo")
        self.assertEqual(preserved.primary.data, blob)
        self.assertEqual(preserved.primary.mime, gputex.MIME_DDS)
        self.assertEqual(preserved.fallback.mime, "image/png")
        converted_normal = prepare_adm_texture(self.normal, "normal")
        normal_info = gputex.parse(converted_normal.primary.data, gputex.MIME_DDS, strict=True)
        self.assertEqual(normal_info["kind"], "RGBA8")
        self.assertFalse(normal_info["srgb"])
        converted_data = prepare_adm_texture(self.packed, "data")
        data_info = gputex.parse(converted_data.primary.data, gputex.MIME_DDS, strict=True)
        self.assertEqual(data_info["kind"], "BC3")
        self.assertFalse(data_info["srgb"])

    def test_truncated_dx10_dds_reports_the_decode_error(self):
        path = os.path.join(self.tmp.name, "truncated.dds")
        raw = bytearray(128)
        raw[:4] = b"DDS "
        struct.pack_into("<I", raw, 4, 124)
        struct.pack_into("<2I", raw, 12, 4, 4)
        raw[84:88] = b"DX10"
        with open(path, "wb") as handle:
            handle.write(raw)
        with self.assertRaisesRegex(ValueError, "Truncated DDS DX10 header"):
            prepare_texture(path)

    def test_project_round_trip_uses_relative_paths(self):
        project = Project.new(self.src)
        project.params = self.params
        project.material = self.material
        self.material.ensure_paint(65, 49)
        self.material.paint[3:9, 4:20] = 2
        self.material.ensure_surface_paint(65, 49)
        self.material.surface_paint[10:20, 10:20] = self.material.surface_names().index("soil")
        self.material.roads = [Road("gravel", 5.0, 2.0, [[4, 5, 10], [50, 20, 12]])]
        project.export = self.settings
        project.selection = ["x001_y000"]
        path = os.path.join(self.tmp.name, "world.awtp")
        project.save(path)
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["build"]["input_path"], "src.npy")
        self.assertEqual(raw["material"]["surfaces"][0]["albedo"], "grass albedo.tga")

        loaded = load_project(path)
        self.assertEqual(loaded.params, self.params)
        self.assertEqual(loaded.material, self.material)
        self.assertTrue(np.array_equal(loaded.material.paint, self.material.paint))
        self.assertTrue(np.array_equal(loaded.material.surface_paint, self.material.surface_paint))
        self.assertEqual(loaded.material.roads, self.material.roads)
        self.assertEqual(loaded.material.rules_digest(), self.material.rules_digest())
        self.assertEqual(loaded.export, self.settings)
        self.assertEqual(loaded.selection, ["x001_y000"])
        raw["format_version"] = 2
        raw["material"].pop("surface_paint")
        raw["material"].pop("roads")
        self.assertFalse(Project.from_dict(raw).material.roads)
        with self.assertRaises(ValueError):
            Project.from_dict({"format": "something else"})

    def test_bake_keeps_north_up_and_blends_vertex_weights(self):
        from awt.bake import bake

        tile = next(t for t in self.manifest["tiles"] if t["size_m"] == [64.0, 64.0])
        names = self.manifest["texturing"]["surfaces"]
        path = os.path.join(self.manifest["_dir"], tile["lods"][0]["file"])
        verts, faces = read_ply(path)
        verts = verts.copy()
        for name in weight_fields(verts):
            verts[name] = 0
        north = verts["y"] > 40.0  # well inside the north half, so no triangle crosses y = 32
        south = verts["y"] < 24.0
        verts[f"w{names.index('rock')}"][north] = 255
        verts[f"w{names.index('sand')}"][south] = 255
        middle = ~(north | south)
        verts[f"w{names.index('rock')}"][middle] = 128
        verts[f"w{names.index('sand')}"][middle] = 127
        write_ply(path, verts, faces)
        material = TerrainMaterial()
        material.surface("rock").color = [255, 0, 0]
        material.surface("sand").color = [0, 0, 255]
        image, bbox = bake(self.manifest, material, [(tile["ix"], tile["iy"])])
        x0, y0 = tile["origin_m"][:2]
        self.assertEqual(bbox, (x0, y0, x0 + 64.0, y0 + 64.0))
        self.assertEqual(image[1, image.shape[1] // 2].tolist(), [255, 0, 0])
        self.assertEqual(image[-2, image.shape[1] // 2].tolist(), [0, 0, 255])
        mixed = image[image.shape[0] // 2, image.shape[1] // 2].tolist()
        self.assertTrue(mixed[0] > 100 and mixed[2] > 100 and mixed[1] == 0)


if __name__ == "__main__":
    unittest.main()
