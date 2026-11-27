import json
import io
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from awt.adm_export import (INDEX_NAME, ExportSettings, _core, _palette_conflict_details, changed_tiles, color1,
                            export_tiles, group_masks, prepare_adm_texture, rules_outdated,
                            seam_consistent_weights, triangle_masks)
from awt.material import (Band, Biome, BiomeSurface, MacroColorSettings, MapSlot, PhysicalMaterial, Surface,
                          TerrainMaterial, prepare_texture)
from awt.pipeline import BuildParams, build, load_manifest
from awt.ply import read_ply, weight_fields, write_ply
from awt.project import Project, load_project
from awt.roads import Road
from awt.texturing import quantize
from tests.test_pipeline import _terrain


def _read_adm(path):
    _buffers, constants, container, _validate = _core()
    with open(path, "rb") as handle:
        doc, chunks = container.read_container(handle.read(), constants.ADM_MAGIC)[:2]
    return doc, chunks


def _accessor(doc, chunks, index):
    from adm_blender.core.buffers import read_accessor_np

    return np.asarray(read_accessor_np(doc, chunks, index))


def _read_rgba16_png(data):
    width, height, depth, color = struct.unpack_from(">IIBB", data, 16)
    if (depth, color) != (16, 6):
        raise ValueError("Expected a 16-bit RGBA PNG")
    offset = 8
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        if kind == b"IDAT":
            compressed.extend(data[offset + 8:offset + 8 + length])
        offset += length + 12
    scanlines = zlib.decompress(compressed)
    stride = width * 8 + 1
    if any(scanlines[y * stride] != 0 for y in range(height)):
        raise ValueError("Unexpected PNG row filter")
    samples = b"".join(scanlines[y * stride + 1:(y + 1) * stride] for y in range(height))
    return np.frombuffer(samples, dtype=">u2").reshape(height, width, 4)


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
        self.settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "adm"),
                                       palette_conflict_policy="APPROXIMATE")

    def _primitives(self, doc, chunks, mesh=0):
        out = []
        for prim in doc["meshes"][mesh]["primitives"]:
            attrs = {name: _accessor(doc, chunks, index) for name, index in prim["attributes"].items()}
            out.append((prim, attrs, _accessor(doc, chunks, prim["indices"]).reshape(-1, 3)))
        return out

    def test_independent_collision_exports_as_a_mesh_collider(self):
        self.params.collision_max_error_m = 0.8
        self.params.collision_max_triangles_per_tile = 4096
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        result = export_tiles(manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(manifest["tiles"]))
        tile = manifest["tiles"][0]
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
        self.assertEqual(len(doc["colliders"]), 1)
        collider = doc["colliders"][0]
        self.assertEqual(collider["shape"], "MESH")
        self.assertEqual(collider["mesh"], len(tile["lods"]))
        self.assertNotIn("physicalMaterial", collider)
        self.assertNotIn("mesh", doc["nodes"][collider["node"]])
        primitive = doc["meshes"][collider["mesh"]]["primitives"][0]
        self.assertEqual(set(primitive["attributes"]), {"POSITION"})
        positions = _accessor(doc, chunks, primitive["attributes"]["POSITION"])
        indices = _accessor(doc, chunks, primitive["indices"])
        self.assertEqual(positions.shape[1], 3)
        self.assertEqual(indices.size, tile["collision"]["triangles"] * 3)
        self.assertEqual(changed_tiles(manifest, self.material, self.settings), [])
        original_digest = tile["collision"]["digest"]
        tile["collision"]["digest"] = "modified-collision-digest"
        self.assertEqual(changed_tiles(manifest, self.material, self.settings), [tile["id"]])
        tile["collision"]["digest"] = original_digest
        tile["collision"]["file"] = r"..\outside.ply"
        with self.assertRaisesRegex(ValueError, "must remain inside the build directory"):
            export_tiles(manifest, self.material, self.settings, "all")
        manifest["tiles"][1].pop("collision")
        with self.assertRaisesRegex(ValueError, "present for every tile"):
            export_tiles(manifest, self.material, self.settings, "all")

    def test_control_map_export_is_opt_in_and_emits_four_stable_channels(self):
        self.settings.control_map_resolution = 16
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(self.manifest["tiles"]))
        tile = self.manifest["tiles"][0]
        doc, _chunks = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
        extension = "ADM_terrain_control_map_v1"
        self.assertIn(extension, doc["extensionsUsed"])
        self.assertIn(extension, doc["extensionsRequired"])
        for material in doc["materials"]:
            self.assertEqual(len(material["extensions"]["ADM_terrain_surface_v1"]["surfaceIds"]), 4)
            control = material["extensions"][extension]
            self.assertEqual(control["mode"], "TEXTURE_RGBA")
            texture = doc["textures"][control["texture"]["index"]]
            sampler = doc["samplers"][texture["sampler"]]
            self.assertEqual(sampler["wrapS"], "CLAMP_TO_EDGE")
            self.assertEqual(sampler["wrapT"], "CLAMP_TO_EDGE")
            image = doc["images"][texture["source"]]
            image_path = os.path.join(self.settings.out_dir, *image["uri"].split("/"))
            pixels = np.asarray(Image.open(image_path).convert("RGBA"))
            self.assertEqual(pixels.shape, (16, 16, 4))
            np.testing.assert_array_equal(pixels.sum(axis=2), np.full((16, 16), 255, dtype=np.uint16))
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        self.settings.control_map_resolution = 32
        self.assertEqual(set(changed_tiles(self.manifest, self.material, self.settings)),
                         {item["id"] for item in self.manifest["tiles"]})
        self.settings.control_map_resolution = 16
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        np.save(self.src, _terrain(49, 65) + 1.0)
        with self.assertRaisesRegex(ValueError, "changed since the terrain build"):
            changed_tiles(self.manifest, self.material, self.settings)
        build(self.params, self.material)
        self.manifest = load_manifest(self.params.out_dir)
        self.assertEqual(set(changed_tiles(self.manifest, self.material, self.settings)),
                         {item["id"] for item in self.manifest["tiles"]})
        embedded = ExportSettings(
            out_dir=os.path.join(self.tmp.name, "adm_embedded"), embed_textures=True,
            palette_conflict_policy="APPROXIMATE", control_map_resolution=16)
        export_tiles(self.manifest, self.material, embedded, "all")
        embedded_doc, _ = _read_adm(os.path.join(embedded.out_dir, self.manifest["tiles"][0]["id"] + ".adm"))
        extension_data = embedded_doc["materials"][0]["extensions"]["ADM_terrain_control_map_v1"]
        embedded_image = embedded_doc["images"][
            embedded_doc["textures"][extension_data["texture"]["index"]]["source"]]
        self.assertIn("bufferView", embedded_image)
        self.assertNotIn("uri", embedded_image)

    def test_external_control_map_exports_stable_channels_and_invalidates_changed_masks(self):
        self.params.collision_max_error_m = 0.8
        physical = PhysicalMaterial("Ground", 0.7, 0.05, id="test.physical.ground")
        self.material.physical_materials.append(physical)
        for surface in self.material.surfaces:
            surface.physical_material_id = physical.id
        build(self.params, self.material)
        self.manifest = load_manifest(self.params.out_dir)
        export_tiles(self.manifest, self.material, self.settings, "all")
        tile_id = self.manifest["tiles"][0]["id"]
        baseline_doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile_id + ".adm"))
        collider_mesh = baseline_doc["colliders"][0]["mesh"]
        physical_before = (
            baseline_doc["physicalMaterials"],
            [primitive.get("extensions", {}).get("ADM_physical_surfaces_v1")
             for primitive in baseline_doc["meshes"][collider_mesh]["primitives"]],
        )

        source_ids = [surface.id for surface in reversed(self.material.surfaces[:4])]
        mask_path = os.path.join(self.tmp.name, "external-mask.png")
        mask = np.empty((49, 65, 4), dtype=np.uint8)
        mask[:] = (10, 100, 64, 255)
        Image.fromarray(mask).save(mask_path)
        self.material.external_control_map_path = mask_path
        self.material.external_control_map_surface_ids = source_ids
        self.settings.control_map_resolution = 16
        original_rules = self.material.rules_digest()

        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(self.manifest["tiles"]))
        self.assertEqual(self.material.rules_digest(), original_rules)
        expected = quantize(np.array([[
            mask[0, 0, source_ids.index(surface.id)] for surface in self.material.surfaces[:4]
        ]], dtype=np.float32))[0]
        tile = self.manifest["tiles"][0]
        doc, _chunks = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
        for material in doc["materials"]:
            surface_ids = material["extensions"]["ADM_terrain_surface_v1"]["surfaceIds"]
            self.assertEqual(surface_ids, [surface.id for surface in self.material.surfaces[:4]])
            control = material["extensions"]["ADM_terrain_control_map_v1"]
            image = doc["images"][doc["textures"][control["texture"]["index"]]["source"]]
            image_path = os.path.join(self.settings.out_dir, *image["uri"].split("/"))
            pixels = np.asarray(Image.open(image_path).convert("RGBA"))
            np.testing.assert_array_equal(pixels[0, 0], expected)
            self.assertTrue(np.all(pixels.sum(axis=2) == 255))
        collider_mesh = doc["colliders"][0]["mesh"]
        physical_after = (
            doc["physicalMaterials"],
            [primitive.get("extensions", {}).get("ADM_physical_surfaces_v1")
             for primitive in doc["meshes"][collider_mesh]["primitives"]],
        )
        self.assertEqual(physical_after, physical_before)
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])

        mask[0, 0, 0] = 11
        Image.fromarray(mask).save(mask_path)
        self.assertEqual(set(changed_tiles(self.manifest, self.material, self.settings)),
                         {item["id"] for item in self.manifest["tiles"]})
        self.material.external_control_map_surface_ids = [source_ids[0], source_ids[0],
                                                          source_ids[2], source_ids[3]]
        with self.assertRaisesRegex(ValueError, "four unique, existing stable surface IDs"):
            changed_tiles(self.manifest, self.material, self.settings)

    def test_project_v14_external_control_map_paths_and_ids_round_trip(self):
        project_path = os.path.join(self.tmp.name, "world.awtp")
        mask_path = os.path.join(self.tmp.name, "mask.png")
        project = Project(self.params, self.material, self.settings, path=project_path)
        project.material.external_control_map_path = mask_path
        project.material.external_control_map_surface_ids = [
            surface.id for surface in project.material.surfaces[:4]]

        payload = project.to_dict()
        self.assertEqual(payload["format_version"], 15)
        self.assertEqual(payload["material"]["external_control_map"]["path"], "mask.png")
        restored = Project.from_dict(payload, project_path)
        self.assertEqual(restored.material.external_control_map_path, mask_path)
        self.assertEqual(restored.material.external_control_map_surface_ids,
                         project.material.external_control_map_surface_ids)

        legacy = dict(payload)
        legacy["format_version"] = 13
        legacy["material"] = dict(payload["material"])
        legacy["material"].pop("external_control_map")
        restored_legacy = Project.from_dict(legacy, project_path)
        self.assertEqual(restored_legacy.material.external_control_map_path, "")
        self.assertEqual(restored_legacy.material.external_control_map_surface_ids, [])

    def test_project_v15_macro_color_path_settings_and_fingerprint_round_trip(self):
        project_path = os.path.join(self.tmp.name, "world.awtp")
        macro_path = os.path.join(self.tmp.name, "macro.png")
        Image.new("RGB", (8, 8), (90, 120, 150)).save(macro_path)
        project = Project(self.params, self.material, self.settings, path=project_path)
        project.material.macro_color = MacroColorSettings(
            path=macro_path,
            projection="SHARED_WORLD_XZ",
            blend_mode="LERP",
            strength=0.65,
            layer_influence=[1.0, 0.75, 0.5, 0.25],
            scale=[0.02, 0.03],
            offset=[0.1, -0.2],
            origin=[100.0, -50.0],
        )
        project.material.validate()
        original_fingerprint = project.material.fingerprint(64)

        payload = project.to_dict()
        self.assertEqual(payload["format_version"], 15)
        self.assertEqual(payload["material"]["macro_color"]["path"], "macro.png")
        restored = Project.from_dict(payload, project_path)
        self.assertEqual(restored.material.macro_color, project.material.macro_color)
        self.assertIn(macro_path, restored.material.textures())
        self.assertEqual(restored.material.fingerprint(64), original_fingerprint)

        Image.new("RGB", (8, 8), (10, 20, 30)).save(macro_path)
        self.assertNotEqual(restored.material.fingerprint(64), original_fingerprint)

        legacy = dict(payload)
        legacy["format_version"] = 14
        legacy["material"] = dict(payload["material"])
        legacy["material"].pop("macro_color")
        self.assertEqual(Project.from_dict(legacy, project_path).material.macro_color, MacroColorSettings())

    def test_macro_color_validation_rejects_grayscale_and_invalid_scale(self):
        grayscale_path = os.path.join(self.tmp.name, "macro-gray.png")
        Image.new("L", (8, 8), 128).save(grayscale_path)
        with self.assertRaisesRegex(ValueError, "at least three color channels"):
            MacroColorSettings(path=grayscale_path).validate()
        with self.assertRaisesRegex(ValueError, "scale must not be"):
            MacroColorSettings(scale=[0.0, 0.0]).validate()

    def test_macro_color_export_is_srgb_required_and_keeps_collision_assignments(self):
        self.params.collision_max_error_m = 0.8
        self.params.collision_max_triangles_per_tile = 4096
        physical = PhysicalMaterial("Terrain", 0.65, 0.1, "adm.phys.ground.v1")
        self.material.physical_materials.append(physical)
        for surface in self.material.surfaces:
            surface.physical_material_id = physical.id
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        tile_id = manifest["tiles"][0]["id"]

        baseline_dir = os.path.join(self.tmp.name, "adm-baseline")
        baseline_settings = ExportSettings(
            out_dir=baseline_dir, palette_conflict_policy="APPROXIMATE")
        export_tiles(manifest, self.material, baseline_settings, "selected", [tile_id])
        baseline_doc, baseline_chunks = _read_adm(os.path.join(baseline_dir, tile_id + ".adm"))

        macro_path = os.path.join(self.tmp.name, "macro-color.png")
        Image.new("RGB", (16, 16), (90, 130, 170)).save(macro_path)
        self.material.macro_color = MacroColorSettings(path=macro_path)
        macro_dir = os.path.join(self.tmp.name, "adm-macro")
        macro_settings = ExportSettings(
            out_dir=macro_dir, palette_conflict_policy="APPROXIMATE")
        export_tiles(manifest, self.material, macro_settings, "selected", [tile_id])
        macro_doc, macro_chunks = _read_adm(os.path.join(macro_dir, tile_id + ".adm"))

        from adm_blender.core import gputex
        from adm_blender.core.constants import TERRAIN_MACRO_COLOR_EXT

        self.assertIn(TERRAIN_MACRO_COLOR_EXT, macro_doc["extensionsUsed"])
        self.assertIn(TERRAIN_MACRO_COLOR_EXT, macro_doc["extensionsRequired"])
        material = macro_doc["materials"][0]
        extension = material["extensions"][TERRAIN_MACRO_COLOR_EXT]
        surface_ids = material["extensions"]["ADM_terrain_surface_v1"]["surfaceIds"]
        self.assertEqual(len(surface_ids), 4)
        self.assertEqual(len(set(surface_ids)), 4)
        self.assertEqual(extension["texture"]["texCoord"], 0)
        texture_record = macro_doc["textures"][extension["texture"]["index"]]
        image = macro_doc["images"][texture_record["source"]]
        texture_bytes = Path(macro_dir, image["uri"]).read_bytes()
        info = gputex.parse(texture_bytes, gputex.mime_of(texture_bytes), strict=True)
        self.assertTrue(info["srgb"])
        fallback = macro_doc["images"][texture_record["fallbackSource"]]
        self.assertEqual(Path(macro_dir, fallback["uri"]).read_bytes(), Path(macro_path).read_bytes())

        def collision_snapshot(doc, chunks):
            mesh = doc["meshes"][doc["colliders"][0]["mesh"]]
            return [
                (
                    _accessor(doc, chunks, primitive["attributes"]["POSITION"]).tolist(),
                    _accessor(doc, chunks, primitive["indices"]).tolist(),
                    primitive.get("extensions"),
                )
                for primitive in mesh["primitives"]
            ]

        def weight_snapshot(doc, chunks):
            return [
                _accessor(doc, chunks, primitive["attributes"]["COLOR_1"])
                for primitive in doc["meshes"][0]["primitives"]
            ]

        self.assertEqual(len(weight_snapshot(macro_doc, macro_chunks)),
                         len(weight_snapshot(baseline_doc, baseline_chunks)))
        for macro_weights, baseline_weights in zip(
                weight_snapshot(macro_doc, macro_chunks), weight_snapshot(baseline_doc, baseline_chunks)):
            np.testing.assert_array_equal(macro_weights, baseline_weights)
        self.assertEqual(
            collision_snapshot(macro_doc, macro_chunks),
            collision_snapshot(baseline_doc, baseline_chunks),
        )

    def test_physical_paint_exports_stable_per_triangle_references(self):
        self.params.collision_max_error_m = 0.8
        self.params.collision_max_triangles_per_tile = 4096
        self.settings.control_map_resolution = 16
        physical = PhysicalMaterial("Packed ground", 0.72, 0.05, "adm.phys.ground.v1")
        self.material.physical_materials.append(physical)
        self.material.ensure_physical_paint(65, 49)
        self.material.physical_paint[:, :16] = 0
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        self.assertFalse(rules_outdated(manifest, self.material))
        result = export_tiles(manifest, self.material, self.settings, "all")
        self.assertGreater(result["physical_triangles"], 0)
        self.assertFalse(any("changed since the build" in warning for warning in result["warnings"]))
        self.assertEqual(changed_tiles(manifest, self.material, self.settings), [])

        tile = next(tile for tile in manifest["tiles"] if tile["id"] == "x000_y000")
        doc, chunks = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
        collider = doc["colliders"][0]
        self.assertEqual(doc["physicalMaterials"], [{
            "id": physical.id, "friction": 0.72, "restitution": 0.05, "profile": "adm.phys.ground.v1"
        }])
        self.assertIn("ADM_physical_surfaces_v1", doc["extensionsUsed"])
        self.assertIn("ADM_physical_surfaces_v1", doc["extensionsRequired"])
        primitives = doc["meshes"][collider["mesh"]]["primitives"]
        assigned = [prim for prim in primitives if "ADM_physical_surfaces_v1" in prim.get("extensions", {})]
        unassigned = [prim for prim in primitives if "ADM_physical_surfaces_v1" not in prim.get("extensions", {})]
        self.assertTrue(assigned)
        self.assertTrue(unassigned)
        self.assertTrue(all(set(prim["extensions"]["ADM_physical_surfaces_v1"]["faceMaterials"]) ==
                            {physical.id} for prim in assigned))
        root_x = doc["nodes"][0]["translation"][0]
        physical_map = self.material.physical_paint
        physical_cell = self.material.physical_paint_cell
        _source_x = manifest["bounds_m"][0]
        for primitive, expected_painted in [(prim, True) for prim in assigned] + \
                [(prim, False) for prim in unassigned]:
            positions = _accessor(doc, chunks, primitive["attributes"]["POSITION"])
            triangles = _accessor(doc, chunks, primitive["indices"]).reshape(-1, 3)
            sample_columns = np.rint(
                (root_x + positions[triangles, 0].mean(axis=1) - _source_x) / manifest["spacing_m"]
            ).astype(int)
            if expected_painted:
                self.assertTrue(np.all(physical_map[0, np.clip(sample_columns // physical_cell, 0,
                                                               physical_map.shape[1] - 1)] == 0))
            else:
                self.assertTrue(np.all(physical_map[0, np.clip(sample_columns // physical_cell, 0,
                                                               physical_map.shape[1] - 1)] == 255))
        from adm_blender.core.physical_surfaces import query_physical_material
        assigned_index = doc["meshes"][collider["mesh"]]["primitives"].index(assigned[0])
        self.assertEqual(query_physical_material(doc, 0, assigned_index, 0)["id"], physical.id)
        unassigned_index = doc["meshes"][collider["mesh"]]["primitives"].index(unassigned[0])
        self.assertIsNone(query_physical_material(doc, 0, unassigned_index, 0))

        self.material.physical_paint[:, :16] = 255
        self.assertEqual(set(changed_tiles(manifest, self.material, self.settings)),
                         {"x000_y000", "x000_y001"})

    def test_automatic_physical_classification_uses_dominant_weights_and_manual_override(self):
        self.params.collision_max_error_m = 0.8
        self.params.collision_max_triangles_per_tile = 4096
        automatic = PhysicalMaterial("Automatic ground", 0.65, 0.02)
        manual = PhysicalMaterial("Manual road", 0.8, 0.0)
        self.material.physical_materials.extend((automatic, manual))
        for surface in self.material.surfaces:
            surface.physical_material_id = automatic.id
        self.material.ensure_physical_paint(65, 49)
        self.material.physical_paint[:, :16] = 1
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        tile = next(tile for tile in manifest["tiles"] if tile["id"] == "x000_y000")
        vertices, faces = read_ply(os.path.join(self.params.out_dir, tile["collision"]["file"]))
        fields = weight_fields(vertices)
        weights = np.column_stack([vertices[name] for name in fields])
        dominant = np.empty(len(faces), np.int64)
        for start in range(0, len(faces), 4096):
            stop = min(start + 4096, len(faces))
            dominant[start:stop] = np.argmax(
                weights[faces[start:stop]].astype(np.uint16).sum(axis=1), axis=1)
        self.assertEqual(tile["collision"]["used_surfaces"], np.unique(dominant).tolist())

        from awt.adm_export import _physical_face_assignments

        expected = [automatic.id] * len(faces)
        centroids_x = tile["origin_m"][0] + vertices["x"][faces].mean(axis=1)
        columns = np.rint((centroids_x - manifest["bounds_m"][0]) / manifest["spacing_m"]).astype(int)
        manual_faces = np.clip(columns, 0, self.material.physical_paint.shape[1] - 1) < 16
        for index in np.flatnonzero(manual_faces):
            expected[index] = manual.id
        actual = _physical_face_assignments(manifest, tile, self.material, vertices, faces)
        self.assertEqual(actual, expected)
        self.assertTrue(np.any(manual_faces))
        self.assertTrue(np.any(~manual_faces))

        settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "automatic-adm"),
                                  palette_conflict_policy="APPROXIMATE")
        export_tiles(manifest, self.material, settings, "all")
        doc, _chunks = _read_adm(os.path.join(settings.out_dir, "x000_y000.adm"))
        collider = doc["colliders"][0]
        primitives = doc["meshes"][collider["mesh"]]["primitives"]
        counts = {}
        for primitive in primitives:
            extension = primitive.get("extensions", {}).get("ADM_physical_surfaces_v1")
            if extension:
                for ident in extension["faceMaterials"]:
                    counts[ident] = counts.get(ident, 0) + 1
        self.assertEqual(counts, {automatic.id: int(np.count_nonzero(~manual_faces)),
                                  manual.id: int(np.count_nonzero(manual_faces))})

    def test_legacy_collision_manifest_without_dominant_metadata_remains_manual_only(self):
        self.params.collision_max_error_m = 0.8
        self.params.collision_max_triangles_per_tile = 4096
        build(self.params, self.material)
        manifest = load_manifest(self.params.out_dir)
        tile = next(tile for tile in manifest["tiles"] if tile["id"] == "x000_y000")
        vertices, faces = read_ply(os.path.join(self.params.out_dir, tile["collision"]["file"]))
        physical = PhysicalMaterial("Ground", 0.6, 0.02)
        self.material.physical_materials.append(physical)
        self.material.surface("grass").physical_material_id = physical.id
        legacy_tile = dict(tile)
        legacy_tile["collision"] = {
            key: value for key, value in tile["collision"].items() if key != "used_surfaces"
        }
        legacy_manifest = dict(manifest, format_version=3)

        from awt.adm_export import _physical_face_assignments

        legacy_assignments = _physical_face_assignments(
            legacy_manifest, legacy_tile, self.material, vertices, faces)
        self.assertEqual(legacy_assignments, [None] * len(faces))

        self.material.ensure_physical_paint(65, 49)
        self.material.physical_paint[:, :16] = 0
        legacy_assignments = _physical_face_assignments(
            legacy_manifest, legacy_tile, self.material, vertices, faces)
        self.assertIn(physical.id, legacy_assignments)
        self.assertIn(None, legacy_assignments)
        with self.assertRaisesRegex(ValueError, "used_surfaces metadata is missing"):
            _physical_face_assignments(manifest, legacy_tile, self.material, vertices, faces)
        legacy_v4 = dict(legacy_manifest, format_version=4)
        with self.assertRaisesRegex(ValueError, "used_surfaces metadata is missing"):
            _physical_face_assignments(legacy_v4, legacy_tile, self.material, vertices, faces)
        invalid_manifest = dict(
            manifest,
            tiles=[legacy_tile if item["id"] == tile["id"] else item for item in manifest["tiles"]])
        with self.assertRaisesRegex(ValueError, "used_surfaces metadata is missing"):
            changed_tiles(invalid_manifest, self.material, self.settings)

    def test_physical_paint_requires_collision_meshes(self):
        self.material.physical_materials.append(PhysicalMaterial("Ground", 0.6, 0.0))
        self.material.ensure_physical_paint(65, 49)
        self.material.physical_paint[0, 0] = 0
        with self.assertRaisesRegex(ValueError, "requires built collision meshes"):
            export_tiles(self.manifest, self.material, self.settings, "all")

    def test_unused_physical_material_does_not_change_existing_exports(self):
        export_tiles(self.manifest, self.material, self.settings, "all")
        self.material.physical_materials.append(PhysicalMaterial("Unused ground", 0.6, 0.0))
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])

    def test_surface_physical_mapping_selectively_invalidates_collision_tiles(self):
        source = os.path.join(self.tmp.name, "flat.npy")
        np.save(source, np.full((33, 33), 10.0, np.float32))
        params = BuildParams(input_path=source, out_dir=os.path.join(self.tmp.name, "auto_key_build"),
                             tile_cells=32, max_errors_m=[0.2], collision_max_error_m=0.5)
        material = TerrainMaterial()
        physical = PhysicalMaterial("Ground", 0.6, 0.05)
        material.physical_materials.append(physical)
        build(params, material)
        manifest = load_manifest(params.out_dir)
        settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "auto_key_adm"),
                                  palette_conflict_policy="APPROXIMATE")
        export_tiles(manifest, material, settings, "all")
        tile = manifest["tiles"][0]
        used = set(tile["collision"]["used_surfaces"])
        unused_index = next(index for index in range(len(material.surfaces)) if index not in used)
        material.surfaces[unused_index].physical_material_id = physical.id
        self.assertEqual(changed_tiles(manifest, material, settings), [])
        used_index = min(used)
        material.surfaces[used_index].physical_material_id = physical.id
        self.assertEqual(changed_tiles(manifest, material, settings), [tile["id"]])

    def test_removing_physical_material_clears_and_remaps_painted_indices(self):
        material = TerrainMaterial()
        material.physical_materials = [
            PhysicalMaterial("Ground", 0.6, 0.0),
            PhysicalMaterial("Stone", 0.8, 0.0),
            PhysicalMaterial("Wood", 0.4, 0.1),
        ]
        material.ensure_physical_paint(4, 2)
        material.physical_paint[0] = [0, 1, 2, 255]
        material.surface("grass").physical_material_id = material.physical_materials[1].id
        material.remove_physical_material(1)
        self.assertEqual(material.physical_paint[0].tolist(), [0, 255, 1, 255])
        self.assertEqual(material.surface("grass").physical_material_id, "")
        material.validate_rules()

    def test_irregular_tile_and_mixed_lod_shader_phase_at_shared_vertices(self):
        _core()
        from adm_blender.core.material_math import height_blend_weights

        material = TerrainMaterial()
        material.biomes = [Biome("mixed", surfaces=[
            BiomeSurface("grass"),
            BiomeSurface("rock", slope=Band(5.0, None, 10.0)),
        ], noise=0.4)]
        material.surface("grass").repeat_m = 7.0
        material.surface("rock").repeat_m = 11.0
        material.height_blend_enabled = True
        material.terrain_shader_version = "2.1.0"
        params = BuildParams(input_path=self.src, out_dir=os.path.join(self.tmp.name, "seam_build"),
                             tile_cells=32, max_errors_m=[0.2, 1.0], spacing_m=2.0)
        build(params, material)
        manifest = load_manifest(params.out_dir)
        settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "seam_adm"))
        export_tiles(manifest, material, settings, "all")

        observations = {}
        boundary_edges = []
        observed_surfaces = set()
        tile_size = manifest["tile_size_m"]
        world_top = manifest["bounds_m"][3]
        for tile in manifest["tiles"]:
            doc, chunks = _read_adm(os.path.join(settings.out_dir, tile["id"] + ".adm"))
            translation = np.asarray(doc["nodes"][0]["translation"])
            for lod in range(len(tile["lods"])):
                for prim, attrs, faces in self._primitives(doc, chunks, lod):
                    shader = doc["materials"][prim["material"]]
                    names = shader["name"].split(" ", 3)[-1].split("+")
                    scales = shader["shaderParameters"]["uv_scale"]
                    for position, uv, weights in zip(attrs["POSITION"], attrs["TEXCOORD_0"], attrs["COLOR_1"]):
                        world = position + translation
                        key = (round(float(world[0]), 5), round(float(world[2]), 5))
                        heights = []
                        for name, scale in zip(names, scales):
                            phase = uv * scale
                            expected = np.array([world[0], world_top + world[2]]) / tile_size * scale
                            np.testing.assert_allclose(np.sin(phase * 2 * np.pi),
                                                       np.sin(expected * 2 * np.pi), atol=2e-5)
                            np.testing.assert_allclose(np.cos(phase * 2 * np.pi),
                                                       np.cos(expected * 2 * np.pi), atol=2e-5)
                            heights.append(0.5 + 0.25 * np.sin(
                                (float(phase[0]) + float(phase[1])) * 2 * np.pi
                                + (0.0 if name == "grass" else 1.0)))
                        result = height_blend_weights(weights[:len(names)].tolist(), heights)
                        by_surface = dict(zip(names, result))
                        observed_surfaces.update(name for name, value in by_surface.items() if value > 0.05)
                        observations.setdefault(key, []).append((tile["id"], lod, by_surface))
                    world_positions = attrs["POSITION"] + translation
                    for face in faces:
                        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                            if (abs(float(world_positions[a, 0]) - tile_size) < 1e-4
                                    and abs(float(world_positions[b, 0]) - tile_size) < 1e-4
                                    and abs(float(world_positions[a, 2] - world_positions[b, 2])) > 1e-5):
                                boundary_edges.append((tile["id"], lod, names, scales,
                                                       world_positions[[a, b], 2], attrs["TEXCOORD_0"][[a, b]],
                                                       attrs["COLOR_1"][[a, b]]))

        compared = 0
        mixed_lod = 0
        irregular_compared = 0
        irregular = {tile["id"] for tile in manifest["tiles"] if tile["size_m"][1] < tile_size}
        for entries in observations.values():
            for left in entries:
                for right in entries:
                    if left[0] >= right[0]:
                        continue
                    for name in ("grass", "rock"):
                        self.assertAlmostEqual(left[2].get(name, 0), right[2].get(name, 0), delta=0.01)
                    compared += 1
                    mixed_lod += left[1] != right[1]
                    irregular_compared += left[0] in irregular or right[0] in irregular
        self.assertGreater(compared, 0)
        self.assertGreater(mixed_lod, 0)
        self.assertGreater(irregular_compared, 0)
        self.assertEqual(observed_surfaces, {"grass", "rock"})

        def fragment(edge, z):
            _, _, names, scales, positions, uvs, colors = edge
            t = (z - positions[0]) / (positions[1] - positions[0])
            uv = uvs[0] * (1 - t) + uvs[1] * t
            weights = colors[0] * (1 - t) + colors[1] * t
            heights = [0.5 + 0.25 * np.sin(
                float(np.sum(uv * scale)) * 2 * np.pi + (0.0 if name == "grass" else 1.0))
                for name, scale in zip(names, scales)]
            final = height_blend_weights(weights[:len(names)].tolist(), heights)
            return dict(zip(names, final))

        fragment_comparisons = 0
        mixed_lod_fragments = 0
        for i, left in enumerate(boundary_edges):
            for right in boundary_edges[i + 1:]:
                if left[0] == right[0]:
                    continue
                start = max(min(left[4]), min(right[4]))
                end = min(max(left[4]), max(right[4]))
                if end - start <= 1e-5:
                    continue
                for fraction in (0.1, 0.5, 0.9):
                    z = start + (end - start) * fraction
                    a, b = fragment(left, z), fragment(right, z)
                    for name in ("grass", "rock"):
                        self.assertAlmostEqual(a.get(name, 0), b.get(name, 0), delta=0.01)
                    fragment_comparisons += 1
                    mixed_lod_fragments += left[1] != right[1]
        self.assertGreater(fragment_comparisons, 0)
        self.assertGreater(mixed_lod_fragments, 0)

    def test_shader_only_fields_round_trip_without_invalidating_terrain_rules(self):
        material = TerrainMaterial()
        rules = material.rules_digest()
        material.biomes[0].noise = 0.4
        rules = material.rules_digest()
        surface = material.surface("grass")
        surface.ao_map = MapSlot("", channel=1, invert=True)
        surface.ao_strength = 0.7
        surface.height_map = MapSlot("", channel=0)
        surface.height_scale = 0.3
        surface.height_bias = -0.1
        surface.parallax_scale = 0.02
        surface.emission = ""
        material.height_blend_enabled = True
        material.height_blend_transition = 0.15
        material.height_blend_strength = 0.8
        material.parallax_mode = "PARALLAX_OCCLUSION"
        material.parallax_min_steps = 12
        material.parallax_max_steps = 48
        material.terrain_shader_version = "2.1.0"
        self.assertEqual(material.rules_digest(), rules)
        self.assertTrue(material.has_advanced_shader_features())
        payload = material.to_dict(None)
        self.assertEqual(payload["terrain_shader"]["version"], "2.1.0")
        restored = TerrainMaterial.from_dict(payload, None)
        restored.validate_rules()
        self.assertEqual(restored.surface("grass").ao_map, surface.ao_map)
        self.assertEqual(restored.surface("grass").height_map, surface.height_map)
        self.assertEqual(restored.surface("grass").height_bias, -0.1)
        self.assertEqual(restored.parallax_mode, "PARALLAX_OCCLUSION")
        self.assertEqual(restored.rules_digest(), rules)
        self.assertNotEqual(restored.fingerprint(64), TerrainMaterial().fingerprint(64))

    def test_legacy_material_keeps_legacy_project_shape_and_rejects_bad_channels(self):
        material = TerrainMaterial()
        payload = material.to_dict(None)
        self.assertNotIn("terrain_shader", payload)
        self.assertNotIn("ao_map", payload["surfaces"][0])
        payload["surfaces"][0]["ao_map"] = {"path": "", "channel": 4, "invert": False}
        with self.assertRaisesRegex(ValueError, "channel must be R"):
            TerrainMaterial.from_dict(payload, None).validate()

    def test_unknown_terrain_shader_settings_survive_project_round_trip_and_block_export(self):
        project = Project.new()
        data = project.to_dict()
        data["format_version"] = 5
        data["material"]["terrain_shader"] = {
            "version": "2.1.0", "future_effect": {"enabled": True, "values": [0.2, 0.7]}}
        restored = Project.from_dict(data)
        self.assertEqual(restored.to_dict()["material"]["terrain_shader"]["future_effect"],
                         {"enabled": True, "values": [0.2, 0.7]})
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "future.awtp")
            restored.save(path)
            restored = load_project(path)
            self.assertEqual(restored.to_dict()["material"]["terrain_shader"]["future_effect"],
                             {"enabled": True, "values": [0.2, 0.7]})
            output = os.path.join(directory, "export")
            with self.assertRaisesRegex(ValueError, "Unsupported terrain shader settings.*future_effect"):
                export_tiles({}, restored.material, ExportSettings(out_dir=output), "all")
            self.assertFalse(os.path.exists(output))
        rules = restored.material.rules_digest()
        fingerprint = restored.material.fingerprint(64)
        restored.material.unknown_terrain_shader_settings["future_effect"]["values"][0] = 0.4
        self.assertEqual(restored.material.rules_digest(), rules)
        self.assertNotEqual(restored.material.fingerprint(64), fingerprint)
        with self.assertRaisesRegex(ValueError, "Unsupported terrain shader settings.*future_effect"):
            restored.material.validate()

    def test_project_v12_physical_material_links_and_legacy_load_defaults(self):
        project = Project.new()
        project.material.height_blend_enabled = True
        height_path = Path(self.tmp.name, "height.png")
        height_path.write_bytes(b"height")
        project.material.surface("grass").height_map = MapSlot(str(height_path))
        physical = PhysicalMaterial("Ground", 0.6, 0.1, "adm.phys.ground.v1")
        project.material.physical_materials.append(physical)
        project.material.surface("grass").physical_material_id = physical.id
        project.material.ensure_physical_paint(8, 8)
        project.material.physical_paint[2:4, 3:6] = 0
        project.export.control_map_resolution = 128
        payload = project.to_dict()
        self.assertEqual(payload["format_version"], 15)
        self.assertEqual(payload["export"]["control_map_resolution"], 128)
        self.assertEqual(payload["export"]["palette_conflict_policy"], "STRICT")
        restored = Project.from_dict(payload)
        self.assertEqual(restored.export.control_map_resolution, 128)
        self.assertTrue(restored.material.height_blend_enabled)
        self.assertEqual(restored.material.surface("grass").height_map.path, str(height_path))
        self.assertEqual(restored.material.surface("grass").id, project.material.surface("grass").id)
        self.assertEqual(restored.material.physical_materials, [physical])
        self.assertEqual(restored.material.surface("grass").physical_material_id, physical.id)
        self.assertEqual(restored.material.rules_digest(), project.material.rules_digest())
        self.assertEqual(restored.material.fingerprint(64), project.material.fingerprint(64))
        self.assertTrue(np.array_equal(restored.material.physical_paint, project.material.physical_paint))
        legacy = project.to_dict()
        legacy["export"].pop("palette_conflict_policy")
        legacy["material"] = TerrainMaterial().to_dict(None)
        for surface in legacy["material"]["surfaces"]:
            surface.pop("id")
        legacy["build"].pop("collision_max_error_m")
        legacy["build"].pop("collision_max_triangles_per_tile")
        legacy["build"].pop("collision_boundary_max_edge_m")
        for version in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            legacy["format_version"] = version
            loaded = Project.from_dict(legacy)
            expected_policy = "APPROXIMATE" if version < 7 else "STRICT"
            self.assertEqual(loaded.export.palette_conflict_policy, expected_policy)
            self.assertEqual(loaded.material.surface("grass").id, Surface("grass").id)
            self.assertEqual(loaded.params.collision_max_error_m, 0.0)
            self.assertEqual(loaded.params.collision_max_triangles_per_tile, 262144)
        legacy_v11 = project.to_dict()
        legacy_v11["format_version"] = 11
        legacy_v11["build"].pop("collision_boundary_max_edge_m")
        self.assertEqual(Project.from_dict(legacy_v11).params.collision_boundary_max_edge_m, 4.0)
        for version in (2, 3, 4):
            payload["format_version"] = version
            payload["material"] = TerrainMaterial().to_dict(None)
            loaded = Project.from_dict(payload)
            self.assertFalse(loaded.material.height_blend_enabled)
            self.assertEqual(loaded.material.surface("grass").height_scale, 1.0)

    def test_advanced_export_requires_explicit_target_profile(self):
        self.material.height_blend_enabled = True
        self.assertFalse(rules_outdated(self.manifest, self.material))
        with self.assertRaisesRegex(ValueError, "require the explicit terrain shader version 2.1.0"):
            export_tiles(self.manifest, self.material, self.settings, "all")

    def test_advanced_export_writes_profile_maps_and_tangents_for_parallax(self):
        grass = self.material.surface("grass")
        grass.ao_map = MapSlot(self.packed, channel=1, invert=True)
        grass.ao_strength = 0.65
        grass.height_map = MapSlot(self.packed, channel=2)
        grass.height_scale = 0.4
        grass.height_bias = -0.15
        grass.parallax_scale = 0.025
        grass.emission = self.albedo
        for surface in self.material.surfaces:
            surface.normal = ""
        self.material.height_blend_enabled = True
        self.material.height_blend_transition = 0.15
        self.material.height_blend_strength = 0.8
        self.material.parallax_mode = "PARALLAX_OCCLUSION"
        self.material.parallax_min_steps = 12
        self.material.parallax_max_steps = 48
        self.material.terrain_shader_version = "2.1.0"

        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertTrue(any("Portable PBR fallbacks" in warning for warning in result["warnings"]))
        found_height_map = False
        found_emission_map = False
        found_tangent = False
        for tile in self.manifest["tiles"]:
            doc, chunks = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
            for exported in doc["materials"]:
                self.assertEqual(exported["shader"]["version"], "2.1.0")
                params = exported["shaderParameters"]
                self.assertTrue(params["height_blend_enabled"])
                self.assertEqual(params["height_blend_transition"], 0.15)
                self.assertEqual(params["height_blend_strength"], 0.8)
                self.assertEqual(params["parallax_mode"], "PARALLAX_OCCLUSION")
                self.assertEqual(params["parallax_min_steps"], 12.0)
                self.assertEqual(params["parallax_max_steps"], 48.0)
                height_name = next((name for name in params if name.endswith("_height_texture")), None)
                if height_name:
                    prefix = height_name.removesuffix("_height_texture")
                    self.assertIn("index", params[f"{prefix}_ao_texture"])
                    self.assertIn("index", params[height_name])
                    self.assertEqual(params[f"{prefix}_ao_channel"], 1.0)
                    self.assertTrue(params[f"{prefix}_ao_invert"])
                    self.assertEqual(params[f"{prefix}_ao_strength"], 0.65)
                    self.assertEqual(params[f"{prefix}_height_channel"], 2.0)
                    self.assertEqual(params[f"{prefix}_height_scale"], 0.4)
                    self.assertEqual(params[f"{prefix}_height_bias"], -0.15)
                    self.assertEqual(params[f"{prefix}_parallax_scale"], 0.025)
                    found_height_map = True
                if any(name.endswith("_emissive_texture") for name in params):
                    found_emission_map = True
            found_tangent |= any("TANGENT" in primitive["attributes"]
                                 for mesh in doc["meshes"] for primitive in mesh["primitives"])
        self.assertTrue(found_height_map)
        self.assertTrue(found_emission_map)
        self.assertTrue(found_tangent)

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

    def test_surface_ids_remain_stable_when_renamed(self):
        material = TerrainMaterial()
        ident = material.surface("grass").id
        material.rename_surface("grass", "turf")
        self.assertEqual(material.surface("turf").id, ident)
        self.assertEqual(Surface("grass").id, ident)
        material.surface("turf").id = "x" * 129
        with self.assertRaisesRegex(ValueError, "128 UTF-8 bytes"):
            material.validate_rules()

    def test_tiles_validate_and_keep_world_placement(self):
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(len(result["written"]), len(self.manifest["tiles"]))
        self.assertTrue(any("Approximate palette reduction affected" in warning for warning in result["warnings"]))
        self.assertGreater(result["max_reduction_error"], 0)
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
            surface_names = material["name"].split(" ", 3)[-1].split("+")
            surface_ids = material["extensions"]["ADM_terrain_surface_v1"]["surfaceIds"]
            self.assertEqual(surface_ids, [self.material.surface(name).id for name in surface_names])
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
        details = _palette_conflict_details(
            weights, faces, [Surface(f"surface-{i}") for i in range(6)], "tile-a", 1, 1)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["triangle_index"], 1)
        self.assertEqual(details[0]["dropped_surfaces"], [{
            "id": Surface("surface-3").id,
            "name": "surface-3",
            "corner_weights": [0, 40, 0],
        }])
        sets, assign = group_masks([0b0011, 0b0110, 0b110000, 0b1111])
        self.assertTrue(all(bin(s).count("1") <= 4 for s in sets))
        for mask, index in assign.items():
            self.assertEqual(mask & ~sets[index], 0)
        self.assertEqual(color1(weights[3:4], [4, 5]).tolist(), [[87, 168, 0, 0]])

    def test_approximate_palette_reduction_keeps_shared_vertex_weights_consistent(self):
        weights = np.array([[51, 51, 51, 51, 51], [51, 51, 51, 51, 51],
                            [255, 0, 0, 0, 0], [0, 60, 60, 60, 75]], dtype=np.uint8)
        faces = np.array([[2, 0, 1], [0, 3, 1]])
        masks, conflicts = triangle_masks(weights, faces)
        self.assertEqual(conflicts, 2)
        sets, assign = group_masks(masks)
        face_palettes = np.fromiter((sets[assign[int(mask)]] for mask in masks), dtype=np.uint64)
        effective, errors = seam_consistent_weights(weights, faces, face_palettes)

        edge_values = {}
        for face, palette in zip(faces, face_palettes):
            slots = [slot for slot in range(weights.shape[1]) if int(palette) & (1 << slot)]
            encoded = color1(effective[face], slots)
            for vertex, values in zip(face, encoded):
                actual = np.zeros(weights.shape[1], dtype=np.uint8)
                actual[slots] = values[:len(slots)]
                if vertex in edge_values:
                    np.testing.assert_array_equal(actual, edge_values[vertex])
                else:
                    edge_values[vertex] = actual
        self.assertGreater(errors[0], 0)
        self.assertGreater(errors[1], 0)
        self.assertEqual(effective[0].argmax(), weights[0].argmax())
        self.assertEqual(effective[1].argmax(), weights[1].argmax())

    def test_strict_palette_policy_rejects_before_writing_tiles(self):
        output = os.path.join(self.tmp.name, "strict_adm")
        settings = ExportSettings(out_dir=output, palette_conflict_policy="STRICT")
        with patch("awt.adm_export._tile_palette_conflicts_by_lod", return_value=[1]):
            with self.assertRaisesRegex(ValueError, "Strict export rejected 4 triangles"):
                export_tiles(self.manifest, self.material, settings, "all")
        self.assertEqual(os.listdir(output), [])

    def test_reference_project_palette_conflicts_and_measured_reduction(self):
        project_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "reference_project", "advanced_reference.awtp"))
        project = load_project(project_path)
        project.params.out_dir = os.path.join(self.tmp.name, "reference_build")
        build(project.params, project.material)
        manifest = load_manifest(project.params.out_dir)

        strict_output = os.path.join(self.tmp.name, "reference_strict")
        strict = ExportSettings(out_dir=strict_output, palette_conflict_policy="STRICT")
        with self.assertRaisesRegex(ValueError, "Strict export rejected 54 triangles") as raised:
            export_tiles(manifest, project.material, strict, "all")
        self.assertEqual(os.listdir(strict_output), [])
        self.assertIn("x000_y001 LOD 0 triangle", str(raised.exception))
        self.assertIn("Conflicts by LOD across selected tiles: LOD 0: 18, LOD 1: 18, LOD 2: 18",
                      str(raised.exception))
        self.assertIn("x000_y001 LOD 0: 18 conflicts", str(raised.exception))
        self.assertIn("corner weights", str(raised.exception))
        self.assertIn("Surface on the Map tab", str(raised.exception))

        approximate = ExportSettings(
            out_dir=os.path.join(self.tmp.name, "reference_approximate"),
            palette_conflict_policy="APPROXIMATE")
        result = export_tiles(manifest, project.material, approximate, "all")
        self.assertEqual(result["conflicts"], 54)
        self.assertEqual(result["conflicts_by_lod"], {0: 18, 1: 18, 2: 18})
        self.assertEqual(result["conflicts_by_tile_lod"], {"x000_y001": {0: 18, 1: 18, 2: 18}})
        self.assertEqual(list(result["mean_exported_weights_by_lod"]), [0, 1, 2])
        for weights in result["mean_exported_weights_by_lod"].values():
            self.assertAlmostEqual(sum(weights.values()), 1.0, delta=0.01)
        self.assertEqual(list(result["mean_exported_weights_by_tile_lod"]["x000_y001"]), [0, 1, 2])
        self.assertEqual(len(result["conflict_details"]), 20)
        self.assertEqual(result["conflict_details_truncated"], 34)
        self.assertEqual(result["conflict_details"], sorted(
            result["conflict_details"],
            key=lambda item: (item["tile_id"], item["lod"], item["triangle_index"])))
        self.assertLess(result["mean_reduction_error"], 0.02)
        self.assertLess(result["max_reduction_error"], 0.05)

        by_world_position = {}
        boundary_comparisons = 0
        cross_tile_or_lod_comparisons = 0
        max_boundary_error = 0.0
        for tile in manifest["tiles"]:
            doc, chunks = _read_adm(os.path.join(approximate.out_dir, tile["id"] + ".adm"))
            translation = np.asarray(doc["nodes"][0]["translation"])
            for lod_index, lod in enumerate(doc["meshes"]):
                by_position = {}
                for primitive in lod["primitives"]:
                    surface_names = doc["materials"][primitive["material"]]["name"].split(" ", 3)[-1].split("+")
                    attributes = {name: _accessor(doc, chunks, index)
                                  for name, index in primitive["attributes"].items()}
                    for position, weights in zip(attributes["POSITION"], attributes["COLOR_1"]):
                        world = position + translation
                        key = (round(float(world[0]), 5), round(float(world[2]), 5))
                        values = {name: float(weights[index]) for index, name in enumerate(surface_names)}
                        for previous in (by_position.get(key), by_world_position.get(key)):
                            if previous is None:
                                continue
                            shared_names = set(previous[2]) | set(values)
                            total_variation = 0.5 * sum(
                                abs(previous[2].get(name, 0.0) - values.get(name, 0.0))
                                for name in shared_names)
                            max_boundary_error = max(max_boundary_error, total_variation)
                            boundary_comparisons += 1
                            if previous[0] != tile["id"] or previous[1] != lod_index:
                                cross_tile_or_lod_comparisons += 1
                        by_position[key] = (tile["id"], lod_index, values)
                        by_world_position[key] = (tile["id"], lod_index, values)
        self.assertGreater(boundary_comparisons, 0)
        self.assertGreater(cross_tile_or_lod_comparisons, 0)
        self.assertLessEqual(max_boundary_error, 0.01)

    def test_height_blending_is_independent_of_primitive_slot_order(self):
        from adm_blender.core.material_math import height_blend_weights

        weights = np.array([[0, 102, 153, 0]], dtype=np.uint8)
        heights = [0.2, 0.3, 0.8, 0.9]
        results = []
        for slots in ([0, 1, 2], [1, 2, 3]):
            encoded = color1(weights, slots)[0, :len(slots)].astype(float) / 255.0
            blended = height_blend_weights(encoded.tolist(), [heights[index] for index in slots])
            results.append({index: blended[position] for position, index in enumerate(slots)})
        self.assertAlmostEqual(results[0][1], results[1][1])
        self.assertAlmostEqual(results[0][2], results[1][2])
        self.assertEqual(results[0][0], 0)
        self.assertEqual(results[1][3], 0)

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

    def test_changed_only_tracks_surfaces_used_by_each_tile_and_all_lods(self):
        source = os.path.join(self.tmp.name, "painted.npy")
        np.save(source, np.zeros((33, 97), np.float32))
        params = BuildParams(input_path=source, out_dir=os.path.join(self.tmp.name, "painted"),
                             tile_cells=32, max_errors_m=[0.1, 1.0], spacing_m=1.0)
        material = TerrainMaterial()
        material.ensure_surface_paint(97, 33)
        grass = material.surface_names().index("grass")
        rock = material.surface_names().index("rock")
        material.surface_paint[:, :48] = grass
        material.surface_paint[:, 48:] = rock
        build(params, material)
        manifest = load_manifest(params.out_dir)
        settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "painted_adm"))
        for tile in manifest["tiles"]:
            for lod in tile["lods"]:
                vertices, _ = read_ply(os.path.join(manifest["_dir"], lod["file"]))
                actual = [i for i, name in enumerate(weight_fields(vertices)) if np.any(vertices[name])]
                self.assertEqual(lod["used_surfaces"], actual)
        export_tiles(manifest, material, settings, "all")
        affected = {tile["id"] for tile in manifest["tiles"]
                    if any(rock in lod["used_surfaces"] for lod in tile["lods"])}
        self.assertTrue(affected)
        self.assertLess(len(affected), len(manifest["tiles"]))
        material.surface("rock").roughness = 0.3
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        self.assertEqual(set(export_tiles(manifest, material, settings)["written"]), affected)
        material.surface("soil").roughness = 0.3
        self.assertEqual(changed_tiles(manifest, material, settings), [])
        material.double_sided = True
        self.assertEqual(len(changed_tiles(manifest, material, settings)), len(manifest["tiles"]))
        material.terrain_shader_version = "2.1.0"
        material.height_blend_enabled = True
        ao = os.path.join(self.tmp.name, "rock_ao.png")
        Image.new("L", (4, 4), 80).save(ao)
        material.surface("rock").ao_map.path = ao
        material.surface("rock").height_map.path = ao
        export_tiles(manifest, material, settings, "all")
        settings.gpu_container = "KTX2"
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        self.assertEqual(set(export_tiles(manifest, material, settings)["written"]), affected)
        settings.gpu_container = "DDS"
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        export_tiles(manifest, material, settings)
        material.surface("rock").gpu_encodings = {"ao": "RGBA8", "height": "BC7"}
        export_tiles(manifest, material, settings)
        settings.gpu_encoding = "BC7"
        self.assertEqual(changed_tiles(manifest, material, settings), [])
        del material.surface("rock").gpu_encodings["ao"]
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        export_tiles(manifest, material, settings)
        settings.gpu_encoding = "RGBA8"
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        export_tiles(manifest, material, settings)
        Image.new("L", (4, 4), 160).save(ao)
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        self.assertEqual(set(export_tiles(manifest, material, settings)["written"]), affected)
        material.surface("rock").height_map.invert = True
        material.surface("rock").height_bias = 0.1
        self.assertEqual(set(changed_tiles(manifest, material, settings)), affected)
        export_tiles(manifest, material, settings)
        material.surface("soil").ao_strength = 0.5
        self.assertEqual(changed_tiles(manifest, material, settings), [])
        material.height_blend_strength = 0.4
        self.assertEqual(len(changed_tiles(manifest, material, settings)), len(manifest["tiles"]))

        legacy = json.loads(json.dumps(manifest))
        for tile in legacy["tiles"]:
            for lod in tile["lods"]:
                lod.pop("used_surfaces")
        legacy_settings = ExportSettings(out_dir=os.path.join(self.tmp.name, "legacy_adm"))
        export_tiles(legacy, material, legacy_settings, "all")
        material.surface("soil").roughness = 0.4
        self.assertEqual(len(changed_tiles(legacy, material, legacy_settings)), len(legacy["tiles"]))
        tile = manifest["tiles"][0]
        original = tile["lods"][0]["used_surfaces"]
        tile["lods"][0]["used_surfaces"] = [(original[0] + 1) % len(material.surfaces)]
        with self.assertRaisesRegex(ValueError, "metadata does not match"):
            export_tiles(manifest, material, settings, "selected", [tile["id"]])
        manifest["tiles"][0]["lods"][0]["used_surfaces"] = [-1]
        with self.assertRaisesRegex(ValueError, "invalid used_surfaces"):
            changed_tiles(manifest, material, settings)

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

    def test_dx10_bc7_srgb_dds_is_preserved_with_png_fallback(self):
        path = os.path.join(self.tmp.name, "bc7.dds")
        raw = bytearray(148 + 16)
        raw[:4] = b"DDS "
        struct.pack_into("<I", raw, 4, 124)
        struct.pack_into("<4I", raw, 8, 0x1007, 4, 4, 16)
        struct.pack_into("<I", raw, 76, 32)
        struct.pack_into("<I", raw, 80, 4)
        raw[84:88] = b"DX10"
        struct.pack_into("<I", raw, 108, 0x1000)
        struct.pack_into("<4I", raw, 128, 99, 3, 0, 1)
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

            exported_bytes = handle.read()
            info = gputex.parse(exported_bytes, gputex.MIME_DDS, strict=True)
        self.assertEqual(exported_bytes, bytes(raw))
        self.assertEqual(info["kind"], "BC7")
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

    def test_supported_gpu_source_with_wrong_color_space_is_not_silently_converted(self):
        _core()
        from adm_blender.core import gputex

        rgba = np.full((4, 4, 4), [150, 100, 50, 255], dtype=np.uint8)
        for mime, extension in ((gputex.MIME_DDS, "dds"), (gputex.MIME_KTX2, "ktx2")):
            for role, srgb in (("albedo", False), ("data", True), ("normal", True)):
                blob, _ = gputex.encode(rgba, mime, "BC7", srgb=srgb, mipmaps=True)
                path = os.path.join(self.tmp.name, f"{role}.{extension}")
                with open(path, "wb") as handle:
                    handle.write(blob)
                with self.assertRaisesRegex(ValueError, "color space does not match"):
                    prepare_adm_texture(path, role)

    def test_bc5_normal_keeps_primary_and_uses_rgb_core_pbr_fallback(self):
        _core()
        from adm_blender.core import gputex
        from adm_blender.core.buffers import read_view

        pixels = np.full((4, 4, 4), [150, 100, 255, 255], dtype=np.uint8)
        blob, _ = gputex.encode(pixels, gputex.MIME_DDS, "BC5", False, mipmaps=True)
        path = os.path.join(self.tmp.name, "normal_bc5.dds")
        with open(path, "wb") as handle:
            handle.write(blob)
        for surface in self.material.surfaces:
            surface.normal = path
        self.material.terrain_shader_version = "2.1.0"
        for embed in (False, True):
            with self.subTest(embed=embed):
                self.settings.embed_textures = embed
                self.settings.out_dir = os.path.join(self.tmp.name, f"bc5_{embed}")
                export_tiles(self.manifest, self.material, self.settings, "all")
                doc, chunks = _read_adm(os.path.join(self.settings.out_dir, "x000_y000.adm"))

                def image_bytes(index):
                    image = doc["images"][index]
                    if "bufferView" in image:
                        return read_view(doc, chunks, image["bufferView"])
                    with open(os.path.join(self.settings.out_dir, image["uri"].replace("/", os.sep)), "rb") as f:
                        return f.read()

                material = next(m for m in doc["materials"] if "normalTexture" in m)
                primary_ref = material["shaderParameters"]["layer0_normal"]["index"]
                primary = doc["textures"][primary_ref]
                self.assertEqual(image_bytes(primary["source"]), blob)
                with Image.open(io.BytesIO(image_bytes(primary["fallbackSource"]))) as image:
                    two_channel = np.asarray(image.convert("RGBA"))
                self.assertTrue(np.all(two_channel[..., 2] == 0))
                core_ref = doc["textures"][material["normalTexture"]["index"]]
                self.assertNotIn("fallbackSource", core_ref)
                with Image.open(io.BytesIO(image_bytes(core_ref["source"]))) as image:
                    normal = np.asarray(image.convert("RGBA"))
                xy = two_channel[..., :2].astype(np.float32) / 127.5 - 1
                z = np.sqrt(np.maximum(0, 1 - np.sum(xy * xy, axis=-1, keepdims=True)))
                xyz = np.concatenate((xy, z), axis=-1)
                xyz /= np.linalg.norm(xyz, axis=-1, keepdims=True)
                expected_rgb = np.rint((xyz * 0.5 + 0.5) * 255).astype(np.uint8)
                np.testing.assert_array_equal(normal[..., :3], expected_rgb)
                self.assertTrue(np.all(normal[..., 3] == 255))
                self.assertTrue(np.all(normal[..., 2] > 128))

        converted = prepare_adm_texture(path, "normal", "KTX2", "RGBA8", True)
        self.assertTrue(converted.reencoded_source)
        self.assertEqual(gputex.parse(converted.primary.data, gputex.MIME_KTX2, strict=True)["kind"], "RGBA8")
        np.testing.assert_array_equal(gputex.decode(converted.primary.data, strict=True)[0],
                                      gputex.decode(blob, strict=True)[0])
        self.assertIsNotNone(converted.pbr_normal)
        self.settings.embed_textures = False
        self.settings.gpu_container = "KTX2"
        self.settings.gpu_encoding = "RGBA8"
        self.settings.convert_gpu_sources = True
        export_tiles(self.manifest, self.material, self.settings, "all")
        doc, _ = _read_adm(os.path.join(self.settings.out_dir, "x000_y000.adm"))
        material = next(m for m in doc["materials"] if "normalTexture" in m)
        shader_texture = doc["textures"][material["shaderParameters"]["layer0_normal"]["index"]]
        shader_image = doc["images"][shader_texture["source"]]
        self.assertEqual(shader_image["mimeType"], gputex.MIME_KTX2)
        core_texture = doc["textures"][material["normalTexture"]["index"]]
        with Image.open(os.path.join(self.settings.out_dir, doc["images"][core_texture["source"]]["uri"])) as image:
            self.assertTrue(np.all(np.asarray(image.convert("RGB"))[..., 2] > 128))

    def test_export_changed_invalidates_previous_export_revision(self):
        with patch("awt.adm_export.INDEX_VERSION", 4):
            export_tiles(self.manifest, self.material, self.settings, "all")
            self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        self.assertEqual(set(changed_tiles(self.manifest, self.material, self.settings)),
                         {tile["id"] for tile in self.manifest["tiles"]})

    def test_gpu_export_configuration_preserves_sources_and_r16(self):
        _core()
        from adm_blender.core import gputex

        gpu_bytes, _ = gputex.encode(np.full((4, 4, 4), 127, dtype=np.uint8),
                                     gputex.MIME_DDS, "BC7", srgb=False)
        gpu_path = os.path.join(self.tmp.name, "source.dds")
        Path(gpu_path).write_bytes(gpu_bytes)
        height_path = os.path.join(self.tmp.name, "height16.png")
        height = np.array([[0, 1], [32767, 65535]], dtype=np.uint16)
        Image.fromarray(height).save(height_path)

        for encoding in ("BC7", "RGBA8"):
            with self.subTest(encoding=encoding):
                prepared = prepare_adm_texture(self.albedo, "albedo", "KTX2", encoding)
                info = gputex.parse(prepared.primary.data, gputex.MIME_KTX2, strict=True)
                self.assertEqual((info["kind"], info["srgb"]), (encoding, True))
                unchanged = prepare_adm_texture(gpu_path, "data", "KTX2", encoding)
                self.assertEqual(unchanged.primary.data, gpu_bytes)
                scalar = prepare_adm_texture(height_path, "data", "KTX2", encoding)
                self.assertEqual(gputex.parse(scalar.primary.data, gputex.MIME_KTX2, strict=True)["kind"], "R16")
                np.testing.assert_array_equal(gputex.decode_scalar(scalar.primary.data, strict=True)[0], height)
        with self.assertRaisesRegex(ValueError, "Unsupported GPU"):
            prepare_adm_texture(self.albedo, "albedo", "UNKNOWN", "AUTO")

        self.settings.gpu_container = "KTX2"
        self.settings.gpu_encoding = "BC7"
        export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        self.settings.gpu_encoding = "RGBA8"
        self.assertEqual(len(changed_tiles(self.manifest, self.material, self.settings)), len(self.manifest["tiles"]))
        result = export_tiles(self.manifest, self.material, self.settings, "changed")
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for texture in doc["textures"]:
                image = doc["images"][texture["source"]]
                blob = Path(self.settings.out_dir, image["uri"]).read_bytes()
                self.assertEqual(gputex.parse(blob, gputex.MIME_KTX2, strict=True)["kind"], "RGBA8")
        self.material.surface("rock").roughness_map.path = gpu_path
        self.material.surface("grass").height_map = MapSlot(height_path)
        self.material.terrain_shader_version = "2.1.0"
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertTrue(any("retains BC7 in DDS" in warning for warning in result["warnings"]))
        self.assertTrue(any("retains R16 in KTX2" in warning for warning in result["warnings"]))
        project = Project(self.params, self.material, self.settings)
        data = project.to_dict()
        self.assertEqual(data["format_version"], 15)
        restored = Project.from_dict(data)
        self.assertEqual((restored.export.gpu_container, restored.export.gpu_encoding), ("KTX2", "RGBA8"))
        self.assertEqual(self.material.rules_digest(), restored.material.rules_digest())
        self.settings.gpu_encoding = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "Unsupported GPU"):
            export_tiles(self.manifest, self.material, self.settings, "all")

    def test_explicit_gpu_source_conversion_rebuilds_mips_and_preserves_r16(self):
        _core()
        from adm_blender.core import gputex

        values = np.array([[0, 1, 257, 65535], [16, 300, 32768, 65534]], dtype=np.uint16)
        original, _ = gputex.encode_scalar(values, gputex.MIME_DDS, "R16", mipmaps=False)
        path = os.path.join(self.tmp.name, "r16.dds")
        Path(path).write_bytes(original)
        with patch("awt.adm_export.MAX_TEXTURE_PIXELS", 4), \
                patch.object(gputex, "decode_scalar", side_effect=AssertionError("decoded too early")):
            with self.assertRaisesRegex(ValueError, "dimensions exceed"):
                prepare_adm_texture(path, "data", "KTX2", "BC7", True)
        converted = prepare_adm_texture(path, "data", "KTX2", "BC7", True)
        self.assertTrue(converted.reencoded_source)
        self.assertEqual(gputex.parse(converted.primary.data, gputex.MIME_KTX2, strict=True)["kind"], "R16")
        np.testing.assert_array_equal(gputex.decode_scalar(converted.primary.data, strict=True)[0], values)
        np.testing.assert_array_equal(_read_rgba16_png(converted.fallback.data)[..., 0], values)
        self.material.surface("grass").height_map = MapSlot(path, channel=1)
        self.material.terrain_shader_version = "2.1.0"
        self.settings.gpu_container = "KTX2"
        self.settings.gpu_encoding = "BC7"
        self.settings.convert_gpu_sources = True
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertTrue(any("explicitly re-encoded" in warning for warning in result["warnings"]))
        self.assertTrue(any("retains R16 in KTX2" in warning for warning in result["warnings"]))
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for material in doc["materials"]:
                for key in material["shaderParameters"]:
                    if key.endswith("_height_texture"):
                        self.assertEqual(material["shaderParameters"][key.split("_")[0] + "_height_channel"], 1.0)
        project = Project(self.params, self.material, self.settings)
        serialized = project.to_dict()
        self.assertTrue(Project.from_dict(serialized).export.convert_gpu_sources)
        serialized["export"]["convert_gpu_sources"] = "false"
        with self.assertRaisesRegex(ValueError, "must be true or false"):
            Project.from_dict(serialized)

    def test_per_map_encoding_separates_and_shares_texture_assets(self):
        _core()
        from adm_blender.core import gputex

        rock = self.material.surface("rock")
        rock.metallic_map = MapSlot(self.packed, channel=0)
        rock.roughness_map = MapSlot(self.packed, channel=1)
        rock.gpu_encodings = {"metallic": "RGBA8", "roughness": "BC7"}
        digest = self.material.rules_digest()
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        found = False
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for material in doc["materials"]:
                params = material["shaderParameters"]
                for name, value in params.items():
                    if not name.endswith("_metallic_texture"):
                        continue
                    prefix = name.split("_")[0]
                    rough = params.get(prefix + "_roughness_texture")
                    if rough is None:
                        continue
                    metal_ref, rough_ref = value["index"], rough["index"]
                    self.assertNotEqual(metal_ref, rough_ref)
                    for index, kind in ((metal_ref, "RGBA8"), (rough_ref, "BC7")):
                        image = doc["images"][doc["textures"][index]["source"]]
                        blob = Path(self.settings.out_dir, image["uri"]).read_bytes()
                        self.assertEqual(gputex.parse(blob, gputex.MIME_DDS, strict=True)["kind"], kind)
                    found = True
        self.assertTrue(found)
        affected = {tile["id"] for tile in self.manifest["tiles"]
                    if any(self.material.surface_names().index("rock") in lod["used_surfaces"]
                           for lod in tile["lods"])}
        rock.gpu_encodings["roughness"] = "RGBA8"
        self.assertEqual(self.material.rules_digest(), digest)
        self.assertEqual(set(changed_tiles(self.manifest, self.material, self.settings)), affected)
        result = export_tiles(self.manifest, self.material, self.settings, "changed")
        shared = False
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for material in doc["materials"]:
                params = material["shaderParameters"]
                for name, value in params.items():
                    rough = params.get(name.split("_")[0] + "_roughness_texture")
                    if name.endswith("_metallic_texture") and rough is not None:
                        self.assertEqual(value["index"], rough["index"])
                        shared = True
        self.assertTrue(shared)
        data = Project(self.params, self.material, self.settings).to_dict()
        self.assertEqual(data["format_version"], 15)
        self.assertEqual(Project.from_dict(data).material.surface("rock").gpu_encodings, rock.gpu_encodings)
        rock.gpu_encodings["height"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "unsupported per-map GPU encoding"):
            self.material.validate()

    def test_per_map_bc5_encoding_uses_reconstructed_core_normal(self):
        _core()
        from adm_blender.core import gputex

        for surface in self.material.surfaces:
            surface.normal = self.normal
            surface.gpu_encodings["normal"] = "BC5"
        self.material.terrain_shader_version = "2.1.0"
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for material in doc["materials"]:
                shader_ref = material["shaderParameters"]["layer0_normal"]["index"]
                shader_texture = doc["textures"][shader_ref]
                source = doc["images"][shader_texture["source"]]
                blob = Path(self.settings.out_dir, source["uri"]).read_bytes()
                self.assertEqual(gputex.parse(blob, gputex.MIME_DDS, strict=True)["kind"], "BC5")
                with Image.open(Path(self.settings.out_dir, doc["images"][shader_texture["fallbackSource"]]["uri"])) as image:
                    self.assertTrue(np.all(np.asarray(image.convert("RGBA"))[..., 2] == 0))
                core_ref = doc["textures"][material["normalTexture"]["index"]]
                with Image.open(Path(self.settings.out_dir, doc["images"][core_ref["source"]]["uri"])) as image:
                    self.assertTrue(np.all(np.asarray(image.convert("RGB"))[..., 2] > 128))
        with self.assertRaisesRegex(ValueError, "only for normal maps"):
            prepare_adm_texture(self.packed, "data", gpu_encoding="BC5")

    def test_per_map_scalar_formats_export_the_selected_channel(self):
        _core()
        from adm_blender.core import gputex

        rock = self.material.surface("rock")
        rock.metallic_map = MapSlot(self.packed, channel=0)
        rock.roughness_map = MapSlot(self.packed, channel=1, invert=True)
        self.settings.gpu_container = "KTX2"
        for encoding in ("R8", "R16", "BC4"):
            with self.subTest(encoding=encoding):
                rock.gpu_encodings = {"metallic": encoding, "roughness": encoding}
                result = export_tiles(self.manifest, self.material, self.settings, "all")
                self.assertTrue(any("selected channel in red" in w for w in result["warnings"]))
                found = False
                for tile in result["written"]:
                    doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
                    for material in doc["materials"]:
                        params = material["shaderParameters"]
                        for key, ref in params.items():
                            if not key.endswith("_roughness_texture"):
                                continue
                            prefix = key.split("_")[0]
                            if prefix + "_metallic_texture" not in params:
                                continue
                            self.assertEqual(params[prefix + "_roughness_channel"], 0.0)
                            self.assertTrue(params[prefix + "_roughness_invert"])
                            self.assertNotEqual(ref["index"], params[prefix + "_metallic_texture"]["index"])
                            image = doc["images"][doc["textures"][ref["index"]]["source"]]
                            blob = Path(self.settings.out_dir, image["uri"]).read_bytes()
                            self.assertEqual(gputex.parse(blob, gputex.MIME_KTX2, strict=True)["kind"], encoding)
                            values = gputex.decode_scalar(blob, strict=True)[0]
                            expected = 200 * 257 if encoding == "R16" else 200
                            self.assertLessEqual(np.max(np.abs(values.astype(np.int64) - expected)), 1)
                            found = True
                self.assertTrue(found)
        self.assertEqual(rock.roughness_map.channel, 1)
        for channel, expected in enumerate((10, 200, 30, 255)):
            prepared = prepare_adm_texture(self.packed, "data", "DDS", "R8", False, channel)
            self.assertTrue(prepared.channel_remapped)
            np.testing.assert_array_equal(gputex.decode_scalar(prepared.primary.data, strict=True)[0], expected)
        source, _ = gputex.encode(np.full((4, 4, 4), [10, 200, 30, 255], dtype=np.uint8),
                                  gputex.MIME_DDS, "RGBA8", False)
        path = os.path.join(self.tmp.name, "packed.dds")
        Path(path).write_bytes(source)
        preserved = prepare_adm_texture(path, "data", "KTX2", "R8", False, 1)
        self.assertEqual(preserved.primary.data, source)
        self.assertFalse(preserved.channel_remapped)
        converted = prepare_adm_texture(path, "data", "KTX2", "R8", True, 1)
        self.assertTrue(converted.channel_remapped)
        np.testing.assert_array_equal(gputex.decode_scalar(converted.primary.data, strict=True)[0], 200)

        values = np.array([[0, 1], [32768, 65535]], dtype=np.uint16)
        path16 = os.path.join(self.tmp.name, "height16.png")
        Image.fromarray(values).save(path16)
        high_precision = prepare_adm_texture(path16, "data", "KTX2", "BC4", False, 1)
        self.assertEqual(gputex.parse(high_precision.primary.data, gputex.MIME_KTX2, strict=True)["kind"], "R16")
        np.testing.assert_array_equal(gputex.decode_scalar(high_precision.primary.data, strict=True)[0], values)

    def test_scalar_gpu_textures_preserve_source_bytes_and_png_values(self):
        _core()
        from adm_blender.core import gputex

        values8 = np.array([[0, 1, 25, 255], [64, 128, 192, 250],
                            [2, 3, 4, 5], [200, 201, 202, 203]], dtype=np.uint8)
        values16 = np.array([[0, 1, 257, 4096], [8192, 16384, 32768, 65535],
                             [1234, 2345, 3456, 4567], [50000, 60000, 100, 200]], dtype=np.uint16)
        for kind, values in (("R8", values8), ("R16", values16), ("BC4", values8)):
            for mime, extension in ((gputex.MIME_DDS, ".dds"), (gputex.MIME_KTX2, ".ktx2")):
                with self.subTest(kind=kind, mime=mime):
                    blob, encoded_kind = gputex.encode_scalar(values, mime, kind, mipmaps=False)
                    self.assertEqual(encoded_kind, kind)
                    path = os.path.join(self.tmp.name, "height" + extension)
                    with open(path, "wb") as handle:
                        handle.write(blob)

                    prepared = prepare_adm_texture(path, "data")
                    self.assertEqual(prepared.primary.data, blob)
                    self.assertEqual(prepared.primary.mime, mime)
                    self.assertEqual(prepared.fallback.mime, "image/png")
                    expected, _ = gputex.decode_scalar(blob, mime, strict=True)
                    if kind == "R16":
                        fallback_values = _read_rgba16_png(prepared.fallback.data)
                        alpha = 65535
                    else:
                        with Image.open(io.BytesIO(prepared.fallback.data)) as image:
                            fallback_values = np.asarray(image.convert("RGBA"))
                        alpha = 255
                    np.testing.assert_array_equal(fallback_values[..., 0], expected)
                    self.assertTrue(np.all(fallback_values[..., 1:3] == 0))
                    self.assertTrue(np.all(fallback_values[..., 3] == alpha))

    def test_ktx2_r16_preview_and_mip_changes_are_exported(self):
        _core()
        from adm_blender.core import gputex

        values = np.arange(64, dtype=np.uint16).reshape(8, 8) * 513
        blob, _ = gputex.encode_scalar(values, gputex.MIME_KTX2, "R16", mipmaps=True)
        path = os.path.join(self.tmp.name, "height.ktx2")
        with open(path, "wb") as handle:
            handle.write(blob)
        preview = _read_rgba16_png(prepare_texture(path).data)
        np.testing.assert_array_equal(preview[..., 0], values)
        self.assertTrue(np.all(preview[..., 1:3] == 0))

        self.material.surface("grass").height_map = MapSlot(path)
        self.material.terrain_shader_version = "2.1.0"
        export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        texture_dir = os.path.join(self.settings.out_dir, "textures")
        primary = next(name for name in os.listdir(texture_dir)
                       if name.startswith("height_") and name.endswith(".ktx2"))
        with open(os.path.join(texture_dir, primary), "rb") as handle:
            self.assertEqual(handle.read(), blob)

        info = gputex.parse(blob, gputex.MIME_KTX2, strict=True)
        changed = bytearray(blob)
        changed[info["levels"][1][0]] ^= 1
        with open(path, "wb") as handle:
            handle.write(changed)
        np.testing.assert_array_equal(gputex.decode_scalar(bytes(changed), strict=True)[0], values)
        dirty = changed_tiles(self.manifest, self.material, self.settings)
        self.assertTrue(dirty)
        result = export_tiles(self.manifest, self.material, self.settings, "changed")
        self.assertEqual(set(result["written"]), set(dirty))
        self.assertEqual(changed_tiles(self.manifest, self.material, self.settings), [])
        for tile in dirty:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            primaries = [doc["images"][texture["source"]] for texture in doc["textures"]]
            self.assertTrue(any(Path(self.settings.out_dir, image["uri"]).read_bytes() == bytes(changed)
                                for image in primaries if image["mimeType"] == gputex.MIME_KTX2))

    def test_ktx2_bc7_preview_decodes_color(self):
        _core()
        from adm_blender.core import gputex

        pixels = np.full((4, 4, 4), [150, 100, 50, 255], dtype=np.uint8)
        blob, _ = gputex.encode(pixels, gputex.MIME_KTX2, "BC7", srgb=True, mipmaps=False)
        path = os.path.join(self.tmp.name, "albedo.ktx2")
        with open(path, "wb") as handle:
            handle.write(blob)
        with Image.open(io.BytesIO(prepare_texture(path).data)) as image:
            np.testing.assert_array_equal(np.asarray(image), gputex.decode(blob, strict=True)[0])

    def test_r16_png_is_exported_as_r16_dds_without_precision_loss(self):
        _core()
        from adm_blender.core import gputex

        values = np.array([[0, 255, 256, 4095], [8191, 32768, 65534, 65535]], dtype=np.uint16)
        path = os.path.join(self.tmp.name, "height.png")
        Image.fromarray(values).save(path)

        prepared = prepare_adm_texture(path, "data")
        info = gputex.parse(prepared.primary.data, gputex.MIME_DDS, strict=True)
        self.assertEqual(info["kind"], "R16")
        self.assertEqual(prepared.fallback.mime, "image/png")
        decoded, _ = gputex.decode_scalar(prepared.primary.data, strict=True)
        np.testing.assert_array_equal(decoded, values)
        fallback_values = _read_rgba16_png(prepared.fallback.data)
        np.testing.assert_array_equal(fallback_values[..., 0], values)
        self.assertTrue(np.all(fallback_values[..., 1:3] == 0))
        self.assertTrue(np.all(fallback_values[..., 3] == 65535))

    def test_r16_tiff_is_exported_as_r16_dds_without_precision_loss(self):
        _core()
        from adm_blender.core import gputex

        values = np.array([[0, 1, 254, 255], [256, 32768, 65534, 65535]], dtype=np.uint16)
        path = os.path.join(self.tmp.name, "height.tiff")
        Image.fromarray(values).save(path)
        prepared = prepare_adm_texture(path, "data")
        self.assertEqual(gputex.parse(prepared.primary.data, gputex.MIME_DDS, strict=True)["kind"], "R16")
        np.testing.assert_array_equal(gputex.decode_scalar(prepared.primary.data, strict=True)[0], values)
        np.testing.assert_array_equal(_read_rgba16_png(prepared.fallback.data)[..., 0], values)
        self.material.surface("grass").height_map = MapSlot(path)
        self.material.terrain_shader_version = "2.1.0"
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        found = False
        for tile in result["written"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile + ".adm"))
            for material in doc["materials"]:
                for key, ref in material["shaderParameters"].items():
                    if not key.endswith("_height_texture"):
                        continue
                    texture = doc["textures"][ref["index"]]
                    source = doc["images"][texture["source"]]
                    fallback = doc["images"][texture["fallbackSource"]]
                    primary = Path(self.settings.out_dir, source["uri"]).read_bytes()
                    png = Path(self.settings.out_dir, fallback["uri"]).read_bytes()
                    np.testing.assert_array_equal(gputex.decode_scalar(primary, strict=True)[0], values)
                    np.testing.assert_array_equal(_read_rgba16_png(png)[..., 0], values)
                    found = True
        self.assertTrue(found)

    def test_multichannel_sixteen_bit_height_png_retains_primary_and_channels(self):
        _core()
        from adm_blender.core.buffers import read_view
        from adm_blender.core.png import encode_png

        values = np.array([[[0, 257, 65534, 65535], [42, 258, 12345, 60000]],
                           [[1, 259, 54321, 65535], [999, 260, 2, 40000]]], dtype=np.uint16)
        source = encode_png(2, 2, values.astype(">u2").tobytes(), 4, bit_depth=16)
        path = os.path.join(self.tmp.name, "height-rgba16.png")
        Path(path).write_bytes(source)
        prepared = prepare_adm_texture(path, "data")
        self.assertEqual(prepared.primary.data, source)
        self.assertEqual(prepared.primary.mime, "image/png")
        self.assertIsNone(prepared.fallback)
        self.material.surface("grass").height_map = MapSlot(path, channel=1)
        self.material.terrain_shader_version = "2.1.0"
        for embedded in (False, True):
            with self.subTest(embedded=embedded):
                settings = ExportSettings(out_dir=os.path.join(self.tmp.name, f"out-{embedded}"),
                                          embed_textures=embedded, palette_conflict_policy="APPROXIMATE")
                result = export_tiles(self.manifest, self.material, settings, "all")
                self.assertTrue(any("uses a 16-bit PNG primary" in warning for warning in result["warnings"]))
                found = False
                for tile in result["written"]:
                    doc, binary = _read_adm(os.path.join(settings.out_dir, tile + ".adm"))
                    for material in doc["materials"]:
                        params = material["shaderParameters"]
                        for key, ref in params.items():
                            if not key.endswith("_height_texture"):
                                continue
                            index = key.split("_")[0]
                            self.assertEqual(params[index + "_height_channel"], 1.0)
                            texture = doc["textures"][ref["index"]]
                            self.assertNotIn("fallbackSource", texture)
                            image = doc["images"][texture["source"]]
                            self.assertEqual(image["mimeType"], "image/png")
                            blob = (read_view(doc, binary, image["bufferView"]) if embedded
                                    else Path(settings.out_dir, image["uri"]).read_bytes())
                            self.assertEqual(blob, source)
                            np.testing.assert_array_equal(_read_rgba16_png(blob), values)
                            found = True
                self.assertTrue(found)

    def test_multichannel_sixteen_bit_tiff_preserves_samples_and_checks_limits(self):
        import tifffile
        from adm_blender.core.buffers import read_view

        values = np.arange(3 * 4 * 4, dtype=np.uint16).reshape(3, 4, 4) * 257
        values[..., 3] = 65535
        for planar in ("contig", "separate"):
            with self.subTest(planar=planar):
                path = os.path.join(self.tmp.name, f"height-{planar}.tiff")
                pixels = np.moveaxis(values, -1, 0) if planar == "separate" else values
                tifffile.imwrite(path, pixels, photometric="rgb", planarconfig=planar)
                prepared = prepare_adm_texture(path, "data")
                self.assertEqual(prepared.primary.mime, "image/png")
                self.assertIsNone(prepared.fallback)
                np.testing.assert_array_equal(_read_rgba16_png(prepared.primary.data), values)
                with patch("awt.adm_export.MAX_TEXTURE_PIXELS", 4), \
                        patch.object(tifffile.TiffPage, "asarray", side_effect=AssertionError("decoded too early")):
                    with self.assertRaisesRegex(ValueError, "dimensions exceed"):
                        prepare_adm_texture(path, "data")

        unsupported = os.path.join(self.tmp.name, "height-unsupported.tiff")
        tifffile.imwrite(unsupported, np.zeros((3, 4, 2), np.uint16),
                         photometric="minisblack", planarconfig="contig")
        with self.assertRaisesRegex(ValueError, "Cannot preserve 16-bit TIFF channel layout"):
            prepare_adm_texture(unsupported, "data")

        self.material.surface("grass").height_map = MapSlot(path, channel=2)
        self.material.terrain_shader_version = "2.1.0"
        for embedded in (False, True):
            with self.subTest(embedded=embedded):
                settings = ExportSettings(out_dir=os.path.join(self.tmp.name, f"tiff-out-{embedded}"),
                                          embed_textures=embedded, palette_conflict_policy="APPROXIMATE")
                result = export_tiles(self.manifest, self.material, settings, "all")
                self.assertTrue(any("uses a 16-bit PNG primary" in warning for warning in result["warnings"]))
                found = False
                for tile in result["written"]:
                    doc, binary = _read_adm(os.path.join(settings.out_dir, tile + ".adm"))
                    for material in doc["materials"]:
                        for key, ref in material["shaderParameters"].items():
                            if not key.endswith("_height_texture"):
                                continue
                            texture = doc["textures"][ref["index"]]
                            self.assertNotIn("fallbackSource", texture)
                            source = doc["images"][texture["source"]]
                            blob = (read_view(doc, binary, source["bufferView"]) if embedded
                                    else Path(settings.out_dir, source["uri"]).read_bytes())
                            np.testing.assert_array_equal(_read_rgba16_png(blob), values)
                            self.assertEqual(material["shaderParameters"][key.split("_")[0] + "_height_channel"], 2.0)
                            found = True
                self.assertTrue(found)

    def test_sixteen_bit_grayscale_channels_preserve_visual_sampling(self):
        path = os.path.join(self.tmp.name, "height16.png")
        Image.fromarray(np.full((4, 4), 32768, dtype=np.uint16)).save(path)
        self.material.surface("grass").height_map = MapSlot(path, channel=2)
        self.material.terrain_shader_version = "2.1.0"
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertTrue(any("uses red for green/blue" in warning for warning in result["warnings"]))
        channels = []
        for tile in self.manifest["tiles"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
            for material in doc["materials"]:
                params = material["shaderParameters"]
                channels.extend(value for key, value in params.items()
                                if key.endswith("_height_channel") and
                                key.replace("_channel", "_texture") in params)
        self.assertTrue(channels)
        self.assertTrue(all(value == 0 for value in channels))
        self.assertEqual(self.material.surface("grass").height_map.channel, 2)

    def test_r16_gpu_source_keeps_explicit_zero_channel_selection(self):
        _core()
        from adm_blender.core import gputex

        blob, _ = gputex.encode_scalar(np.full((4, 4), 32768, dtype=np.uint16),
                                       gputex.MIME_KTX2, "R16", mipmaps=False)
        path = os.path.join(self.tmp.name, "height16.ktx2")
        with open(path, "wb") as handle:
            handle.write(blob)
        self.material.surface("grass").height_map = MapSlot(path, channel=2)
        self.material.terrain_shader_version = "2.1.0"
        result = export_tiles(self.manifest, self.material, self.settings, "all")
        self.assertFalse(any("uses red for green/blue" in warning for warning in result["warnings"]))
        channels = []
        for tile in self.manifest["tiles"]:
            doc, _ = _read_adm(os.path.join(self.settings.out_dir, tile["id"] + ".adm"))
            for material in doc["materials"]:
                params = material["shaderParameters"]
                channels.extend(value for key, value in params.items()
                                if key.endswith("_height_channel") and
                                key.replace("_channel", "_texture") in params)
        self.assertTrue(channels)
        self.assertTrue(all(value == 2 for value in channels))

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
        self.params.collision_max_error_m = 0.6
        self.params.collision_max_triangles_per_tile = 1234
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
