"""ADM 1.0 material fallback and optional semantic-record validation."""

import copy
import hashlib
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from adm_blender.core import constants as K
from adm_blender.core.buffers import BinBuilder
from adm_blender.core.component_animation import component_track_issues, sample_track_values
from adm_blender.core.container import ChunkCollection, read_container, write_container
from adm_blender.core.png import encode_png
from adm_blender.core import physical_surfaces as PS
from adm_blender.core.validate import validate_adm, validate_adm_resolved, validate_anim


FIXTURES = Path(__file__).resolve().parents[2] / "adm-standard" / "fixtures" / "valid"
PROFILE_FIXTURES = FIXTURES.parent / "profiles"


class Draft4Tests(unittest.TestCase):
    def setUp(self):
        self.doc, self.chunks = read_container((FIXTURES / "triangle.adm").read_bytes(), K.ADM_MAGIC)

    def validate(self, doc=None):
        return validate_adm(write_container(K.ADM_MAGIC, self.doc if doc is None else doc, self.chunks))

    def test_component_sampling_and_profile_limits(self):
        linear = sample_track_values([0.0, 1.0], [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "LINEAR")
        self.assertIn((0.0, 0.5, 0.0), linear)
        metadata = {"axles": [{"index": 0, "steeringAngleRad": 0.5}]}
        self.assertEqual(component_track_issues(
            "vehicle.car.v1", metadata, "steering.axle0.left", "rotation",
            [[0.0, math.sin(0.25), 0.0, math.cos(0.25)]]), [])
        self.assertTrue(component_track_issues(
            "vehicle.car.v1", metadata, "steering.axle0.left", "rotation",
            [[0.0, math.sin(0.3), 0.0, math.cos(0.3)]]))

    def test_weapon_both_articulation_checks_each_path(self):
        metadata = {"articulations": [{
            "role": "weapon.bolt", "allowed": "BOTH",
            "translationAxis": "Z", "translationMin": -0.02, "translationMax": 0.0,
            "rotationAxis": "X", "rotationMinRad": 0.0, "rotationMaxRad": 0.25,
        }]}
        self.assertEqual(component_track_issues(
            "weapon.firearm.v1", metadata, "weapon.bolt", "translation", [[0.0, 0.0, -0.01]]), [])
        self.assertEqual(component_track_issues(
            "weapon.firearm.v1", metadata, "weapon.bolt", "rotation",
            [[math.sin(0.1), 0.0, 0.0, math.cos(0.1)]]), [])
        self.assertTrue(component_track_issues(
            "weapon.firearm.v1", metadata, "weapon.bolt", "rotation",
            [[0.0, math.sin(0.1), 0.0, math.cos(0.1)]]))
        self.assertTrue(component_track_issues(
            "weapon.firearm.v1", metadata, "weapon.bolt", "translation", [[0.01, 0.0, 0.0]]))

    def test_magazine_allows_authored_translation_and_rotation_axes(self):
        self.assertEqual(component_track_issues(
            "weapon.firearm.v1", {}, "weapon.magazine", "translation", [[0.01, -0.02, 0.03]]), [])
        self.assertEqual(component_track_issues(
            "weapon.firearm.v1", {}, "weapon.magazine", "rotation",
            [[0.1, 0.2, 0.3, math.sqrt(0.86)]]), [])

    def test_cubic_component_limits_include_between_key_extrema(self):
        metadata = {"articulations": [{
            "role": "weapon.bolt", "allowed": "TRANSLATION", "translationAxis": "Z",
            "translationMin": -0.02, "translationMax": 0.0,
        }]}
        samples = sample_track_values(
            [0.0, 1.0], [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], "CUBICSPLINE",
            [[0.0, 0.0, -4.0], [0.0, 0.0, -4.0]],
            [[0.0, 0.0, 4.0], [0.0, 0.0, 4.0]])
        self.assertIn((0.0, 0.0, 1.0), samples)
        self.assertTrue(component_track_issues(
            "weapon.firearm.v1", metadata, "weapon.bolt", "translation", samples))

    def codes(self, doc=None):
        return {issue.code for issue in self.validate(doc).errors}

    def terrain_macro_color_doc(self):
        doc = copy.deepcopy(self.doc)
        doc["materials"] = [{
            "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
            "metallicFactor": 0.0,
            "roughnessFactor": 1.0,
            "emissiveFactor": [0.0, 0.0, 0.0],
            "alphaMode": "OPAQUE",
            "shader": {"id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_TERRAIN_4[1]},
            "extensions": {
                K.TERRAIN_SURFACE_EXT: {
                    "version": "1.0.0", "surfaceIds": ["a", "b", "c", "d"],
                },
                K.TERRAIN_MACRO_COLOR_EXT: {
                    "version": "1.0.0",
                    "texture": {"index": 0, "texCoord": 0},
                    "projection": "LOCAL_UV",
                    "blendMode": "MULTIPLY",
                },
            },
        }]
        doc["textures"] = [{"source": 0}]
        doc["images"] = [{"uri": "textures/macro.png", "mimeType": "image/png"}]
        doc["extensionsUsed"] = [
            K.EXTERNAL_IMAGES_EXT, K.TERRAIN_SURFACE_EXT, K.TERRAIN_MACRO_COLOR_EXT,
        ]
        doc["extensionsRequired"] = [K.EXTERNAL_IMAGES_EXT, K.TERRAIN_MACRO_COLOR_EXT]
        return doc

    def test_terrain_macro_color_contract_and_resolved_rgb_image(self):
        doc = self.terrain_macro_color_doc()
        data = write_container(K.ADM_MAGIC, doc, self.chunks)
        report = validate_adm(data)
        self.assertTrue(report.ok, report.format())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "textures").mkdir()
            (root / "textures" / "macro.png").write_bytes(
                encode_png(1, 1, bytes((255, 64, 0)), channels=3)
            )
            model_path = root / "model.adm"
            model_path.write_bytes(data)
            report = validate_adm_resolved(data, model_path)
        self.assertTrue(report.ok, report.format())

        invalid_cases = (
            ("shader", {"id": K.SHADER_CORE[0], "version": K.SHADER_CORE[1]},
             "TERRAIN_MACRO_COLOR_PROFILE"),
            ("surfaceIds", ["a", "b", "c"], "TERRAIN_MACRO_COLOR_SURFACES"),
            ("blendMode", "SCREEN", "TERRAIN_MACRO_COLOR_MODE"),
            ("scale", [0.0, 0.0], "TERRAIN_MACRO_COLOR_SCALE"),
            ("layerInfluence", [1.0, 1.0, 1.0], "TERRAIN_MACRO_COLOR_INFLUENCE"),
        )
        for field, value, code in invalid_cases:
            with self.subTest(field=field):
                changed = copy.deepcopy(doc)
                if field == "shader":
                    changed["materials"][0][field] = value
                elif field == "surfaceIds":
                    changed["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT][field] = value
                else:
                    changed["materials"][0]["extensions"][K.TERRAIN_MACRO_COLOR_EXT][field] = value
                self.assertIn(code, {issue.code for issue in self.validate(changed).errors})

        changed = copy.deepcopy(doc)
        changed["materials"][0]["extensions"][K.TERRAIN_MACRO_COLOR_EXT]["projection"] = \
            "SHARED_WORLD_XZ"
        self.assertIn("TERRAIN_MACRO_COLOR_TEXCOORD", self.codes(changed))

        changed = copy.deepcopy(doc)
        changed["samplers"] = [{"magFilter": "NEAREST"}]
        changed["textures"][0]["sampler"] = 0
        self.assertIn("TERRAIN_MACRO_COLOR_FILTER", self.codes(changed))

    def test_terrain_macro_normal_contract_and_invalid_inputs(self):
        doc = self.terrain_macro_color_doc()
        material = doc["materials"][0]
        material["extensions"].pop(K.TERRAIN_MACRO_COLOR_EXT)
        material["extensions"][K.TERRAIN_MACRO_NORMAL_EXT] = {
            "version": "1.0.0", "texture": {"index": 0, "texCoord": 0},
            "projection": "LOCAL_UV",
        }
        doc["extensionsUsed"].remove(K.TERRAIN_MACRO_COLOR_EXT)
        doc["extensionsUsed"].append(K.TERRAIN_MACRO_NORMAL_EXT)
        doc["extensionsRequired"].remove(K.TERRAIN_MACRO_COLOR_EXT)
        doc["extensionsRequired"].append(K.TERRAIN_MACRO_NORMAL_EXT)
        report = self.validate(doc)
        self.assertTrue(report.ok, report.format())

        changed = copy.deepcopy(doc)
        changed["extensionsRequired"].remove(K.TERRAIN_MACRO_NORMAL_EXT)
        self.assertIn("TERRAIN_MACRO_NORMAL_REQUIRED", self.codes(changed))

        invalid_cases = (
            ("shader", {"id": K.SHADER_CORE[0], "version": K.SHADER_CORE[1]},
             "TERRAIN_MACRO_NORMAL_PROFILE"),
            ("surfaceIds", ["a", "b", "c"], "TERRAIN_MACRO_NORMAL_SURFACES"),
            ("projection", "TRIPLANAR", "TERRAIN_MACRO_NORMAL_PROJECTION"),
            ("strength", 1.1, "TERRAIN_MACRO_NORMAL_STRENGTH"),
            ("layerInfluence", [1.0, 1.0, 1.0], "TERRAIN_MACRO_NORMAL_INFLUENCE"),
            ("scale", [0.0, 0.0], "TERRAIN_MACRO_NORMAL_SCALE"),
        )
        for field, value, code in invalid_cases:
            with self.subTest(field=field):
                changed = copy.deepcopy(doc)
                if field == "shader":
                    changed["materials"][0][field] = value
                elif field == "surfaceIds":
                    changed["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT][field] = value
                else:
                    changed["materials"][0]["extensions"][K.TERRAIN_MACRO_NORMAL_EXT][field] = value
                self.assertIn(code, {issue.code for issue in self.validate(changed).errors})

        changed = copy.deepcopy(doc)
        changed["materials"][0]["extensions"][K.TERRAIN_MACRO_NORMAL_EXT]["projection"] = \
            "SHARED_WORLD_XZ"
        self.assertIn("TERRAIN_MACRO_NORMAL_TEXCOORD", self.codes(changed))

        changed = copy.deepcopy(doc)
        changed["images"][0]["mimeType"] = "image/jpeg"
        self.assertIn("TERRAIN_MACRO_NORMAL_IMAGE_FORMAT", self.codes(changed))

        changed = copy.deepcopy(doc)
        changed["samplers"] = [{"magFilter": "NEAREST"}]
        changed["textures"][0]["sampler"] = 0
        self.assertIn("TERRAIN_MACRO_NORMAL_FILTER", self.codes(changed))

    def test_published_fixtures(self):
        for path in sorted(FIXTURES.glob("*.adm*")):
            with self.subTest(path=path.name):
                validate = validate_anim if path.suffix == ".adm_anim" else validate_adm
                report = validate(path.read_bytes())
                self.assertTrue(report.ok, report.format())

    def test_vertex_control_animation_requires_extension(self):
        path = FIXTURES / "shader_parameter_tracks.adm_anim"
        doc, chunks = read_container(path.read_bytes(), K.ANIM_MAGIC)
        target = next(ch["target"] for ch in doc["clips"][0]["channels"]
                      if ch["target"]["kind"] == "shaderParameter")
        target["parameter"] = "wetnessOffset"
        doc["extensionsUsed"] = [K.VERTEX_CONTROL_EXT]
        doc["extensionsRequired"] = [K.VERTEX_CONTROL_EXT]
        report = validate_anim(write_container(K.ANIM_MAGIC, doc, chunks))
        self.assertTrue(report.ok, report.format())

        del doc["extensionsUsed"]
        del doc["extensionsRequired"]
        report = validate_anim(write_container(K.ANIM_MAGIC, doc, chunks))
        self.assertIn("CHANNEL_VERTEX_CONTROL_EXTENSION", {e.code for e in report.errors})

    def test_noncore_requires_each_explicit_fallback_field(self):
        doc, chunks = read_container((FIXTURES / "shader_layered.adm").read_bytes(), K.ADM_MAGIC)
        for field in K.PBR_FALLBACK_FIELDS:
            with self.subTest(field=field):
                changed = copy.deepcopy(doc)
                del changed["materials"][0][field]
                report = validate_adm(write_container(K.ADM_MAGIC, changed, chunks))
                self.assertIn("ADM_ERR_MISSING_PBR_FALLBACK", {e.code for e in report.errors})

    def test_core_material_retains_implicit_defaults(self):
        self.doc["materials"] = [{}]
        self.assertTrue(self.validate().ok)

    def test_quadruped_proposals_are_not_valid_adm_profiles(self):
        self.doc["skins"] = [{"joints": [0]}]
        self.doc["skeletonProfiles"] = [{"id": "animal.canine.v1", "skin": 0, "roles": {}}]
        report = self.validate()
        self.assertIn("PROFILE_NOT_IN_ADM_1_0", {issue.code for issue in report.errors})

        anim_path = FIXTURES / "catalog-only.adm_anim"
        anim_doc, anim_chunks = read_container(anim_path.read_bytes(), K.ANIM_MAGIC)
        anim_doc["library"]["targetProfile"] = "animal.canine.v1"
        report = validate_anim(write_container(K.ANIM_MAGIC, anim_doc, anim_chunks))
        self.assertIn("PROFILE_ID", {issue.code for issue in report.errors})
        self.assertIn("PROFILE_NOT_IN_ADM_1_0", {issue.code for issue in report.errors})

    def test_custom_semantic_profiles_are_exact_only(self):
        anim_path = FIXTURES / "catalog-only.adm_anim"
        anim_doc, anim_chunks = read_container(anim_path.read_bytes(), K.ANIM_MAGIC)
        anim_doc["library"]["targetProfile"] = "org.example.robot.v2"
        report = validate_anim(write_container(K.ANIM_MAGIC, anim_doc, anim_chunks))
        self.assertIn("LIBRARY_PROFILE_EXACT_ONLY", {issue.code for issue in report.errors})

        anim_doc["library"]["binding"] = "EXACT"
        anim_doc["library"]["rigId"] = "a" * 64
        report = validate_anim(write_container(K.ANIM_MAGIC, anim_doc, anim_chunks))
        self.assertTrue(report.ok, report.format())

    def test_vehicle_model_profile_constraints(self):
        source = PROFILE_FIXTURES / "vehicle_car_minimal.adm"
        doc, chunks = read_container(source.read_bytes(), K.ADM_MAGIC)
        report = validate_adm(write_container(K.ADM_MAGIC, doc, chunks))
        self.assertTrue(report.ok, report.format())

        doc["modelProfiles"][0]["metadata"]["axles"][0]["wheels"]["left"]["radius"] = 0
        report = validate_adm(write_container(K.ADM_MAGIC, doc, chunks))
        self.assertIn("VEHICLE_WHEEL_DIMENSION", {issue.code for issue in report.errors})

    def test_weapon_model_profile_constraints(self):
        source = PROFILE_FIXTURES / "weapon_firearm_minimal.adm"
        doc, chunks = read_container(source.read_bytes(), K.ADM_MAGIC)
        report = validate_adm(write_container(K.ADM_MAGIC, doc, chunks))
        self.assertTrue(report.ok, report.format())

        doc["modelProfiles"][0]["metadata"]["unsupportedField"] = True
        report = validate_adm(write_container(K.ADM_MAGIC, doc, chunks))
        self.assertIn("MODEL_PROFILE_METADATA_FIELD", {issue.code for issue in report.errors})

    def test_component_animation_targets(self):
        source = PROFILE_FIXTURES / "vehicle_front_wheel_spin.adm_anim"
        doc, chunks = read_container(source.read_bytes(), K.ANIM_MAGIC)
        self.assertTrue(validate_anim(write_container(K.ANIM_MAGIC, doc, chunks)).ok)

        doc["clips"][0]["channels"][0]["path"] = "scale"
        report = validate_anim(write_container(K.ANIM_MAGIC, doc, chunks))
        self.assertIn("CHANNEL_PATH", {issue.code for issue in report.errors})

    def test_exact_only_profiles_cannot_declare_roles(self):
        self.doc["skins"] = [{"joints": [0]}]
        self.doc["skeletonProfiles"] = [{"id": "generic.v1", "skin": 0, "roles": {"hips": 0}}]
        self.assertIn("PROFILE_EXACT_ONLY_ROLES", self.codes())

    def add_metadata(self):
        self.doc["attachments"] = [{"name": "part_socket", "node": 0}]
        self.doc["modelComponents"] = [{"id": "part.0", "role": "custom.part", "node": 0, "socket": "part_socket"}]
        self.doc["physicalMaterials"] = [{"id": "rubber", "friction": 0.8, "restitution": 0.1}]
        self.doc["colliders"] = [{"node": 0, "shape": "SPHERE", "radius": 0.5, "physicalMaterial": "rubber"}]
        self.doc["hitboxes"] = [{"id": "body", "collider": 0, "boneNode": 0, "role": "torso"}]

    def test_optional_metadata_references_and_coefficients(self):
        self.add_metadata()
        self.assertTrue(self.validate().ok, self.validate().format())
        cases = (
            ("physicalMaterials", "friction", -0.1, "PHYSICAL_MATERIAL_RANGE"),
            ("colliders", "physicalMaterial", "missing", "PHYSICAL_MATERIAL_REFERENCE"),
            ("modelComponents", "socket", "missing", "COMPONENT_SOCKET"),
            ("modelComponents", "id", "INVALID ID", "COMPONENT_ID"),
            ("hitboxes", "collider", 99, "INDEX_RANGE"),
        )
        for array, key, value, code in cases:
            with self.subTest(array=array, field=key):
                doc = copy.deepcopy(self.doc)
                doc[array][0][key] = value
                self.assertIn(code, self.codes(doc))

    def test_duplicate_semantic_ids_rejected(self):
        self.add_metadata()
        for array, code in (("modelComponents", "COMPONENT_ID_DUPLICATE"),
                            ("physicalMaterials", "PHYSICAL_MATERIAL_DUPLICATE"),
                            ("hitboxes", "HITBOX_ID_DUPLICATE")):
            with self.subTest(array=array):
                doc = copy.deepcopy(self.doc)
                doc[array].append(copy.deepcopy(doc[array][0]))
                self.assertIn(code, self.codes(doc))

    def test_hitbox_bone_must_be_collider_ancestor(self):
        self.add_metadata()
        self.doc["nodes"].append({"name": "unrelated"})
        self.doc["scenes"][0]["nodes"].append(len(self.doc["nodes"]) - 1)
        self.doc["hitboxes"][0]["boneNode"] = len(self.doc["nodes"]) - 1
        self.assertIn("HITBOX_ANCESTRY", self.codes())

    def test_registered_physical_surface_profiles_and_unknown_profile(self):
        self.add_metadata()
        self.doc["extensionsUsed"] = [K.PHYSICAL_SURFACES_EXT]
        self.doc["extensionsRequired"] = [K.PHYSICAL_SURFACES_EXT]
        for profile in K.PHYSICAL_SURFACE_PROFILES:
            with self.subTest(profile=profile):
                self.doc["physicalMaterials"][0]["profile"] = profile
                self.assertTrue(self.validate().ok, self.validate().format())
        self.doc["physicalMaterials"][0]["profile"] = "adm.phys.unknown.v1"
        self.assertIn("PHYSICAL_MATERIAL_PROFILE", self.codes())

    def test_registered_and_custom_physical_surface_types(self):
        self.add_metadata()
        material = self.doc["physicalMaterials"][0]
        material.update({
            "type": "adm.physical.grass.v1",
            "subtype": "adm.physical.grass.tall.v1",
            "tags": ["adm.physical.tag.organic.v1", "adm.physical.tag.vegetated.v1"],
            "description": "Tall meadow grass",
        })
        self.doc["extensionsUsed"] = [K.PHYSICAL_SURFACE_TYPES_EXT]
        self.doc["extensionsRequired"] = [K.PHYSICAL_SURFACE_TYPES_EXT]
        self.assertTrue(self.validate().ok, self.validate().format())

        material["type"] = "org.example.physical.soft_wood.v1"
        material["subtype"] = "org.example.physical.soft_wood_oak.v1"
        report = self.validate()
        self.assertTrue(report.ok, report.format())
        self.assertIn("PHYSICAL_SURFACE_TYPE_UNKNOWN", {issue.code for issue in report.warnings})
        self.assertEqual(PS.resolve_type_id(material["type"]), K.PHYSICAL_SURFACE_REGISTRY["unknownType"])

    def test_physical_surface_registry_is_well_formed(self):
        types = K.PHYSICAL_SURFACE_REGISTRY["types"]
        type_ids = [record["id"] for record in types]
        self.assertEqual(len(type_ids), len(set(type_ids)))
        self.assertIn(K.PHYSICAL_SURFACE_REGISTRY["unknownType"], type_ids)
        self.assertEqual(len(K.PHYSICAL_SURFACE_REGISTRY["tags"]),
                         len(set(K.PHYSICAL_SURFACE_REGISTRY["tags"])))
        for record in types:
            with self.subTest(type_id=record["id"]):
                self.assertEqual(len(record["subtypes"]), len(set(record["subtypes"])))
                self.assertTrue(all(subtype.startswith(record["id"][:-3] + ".")
                                    for subtype in record["subtypes"]))

    def test_physical_surface_types_validate_fallbacks_and_limits(self):
        self.add_metadata()
        material = self.doc["physicalMaterials"][0]
        material["type"] = "adm.physical.grass.v1"
        self.doc["extensionsUsed"] = [K.PHYSICAL_SURFACE_TYPES_EXT]
        self.doc["extensionsRequired"] = [K.PHYSICAL_SURFACE_TYPES_EXT]
        material["subtype"] = "adm.physical.grass.short.v1"
        self.assertTrue(self.validate().ok, self.validate().format())

        doc = copy.deepcopy(self.doc)
        doc["physicalMaterials"][0]["type"] = "user.surface.v1"
        self.assertIn("PHYSICAL_SURFACE_TYPE_ID", self.codes(doc))
        doc = copy.deepcopy(self.doc)
        doc["physicalMaterials"][0]["subtype"] = "org.example.physical.grass_variation.v1"
        report = self.validate(doc)
        self.assertTrue(report.ok, report.format())
        self.assertIn("PHYSICAL_SURFACE_SUBTYPE_UNKNOWN", {issue.code for issue in report.warnings})
        doc = copy.deepcopy(self.doc)
        doc["physicalMaterials"][0]["tags"] = ["adm.physical.tag.wet.v1"] * 2
        self.assertIn("PHYSICAL_SURFACE_TAG_DUPLICATE", self.codes(doc))
        doc = copy.deepcopy(self.doc)
        doc["extensionsRequired"] = []
        self.assertIn("PHYSICAL_SURFACE_TYPES_REQUIRED", self.codes(doc))
        doc = copy.deepcopy(self.doc)
        doc["extensionsUsed"] = []
        self.assertIn("PHYSICAL_SURFACE_TYPES_USED", self.codes(doc))
        doc = copy.deepcopy(self.doc)
        doc["physicalMaterials"][0]["description"] = "x" * 513
        self.assertIn("PHYSICAL_SURFACE_DESCRIPTION", self.codes(doc))

    def test_physical_surface_query_uses_triangle_override_then_collider_default(self):
        self.add_metadata()
        self.doc["physicalMaterials"].append({
            "id": "stone",
            "friction": 0.7,
            "restitution": 0.0,
        })
        self.doc["colliders"][0] = {
            "node": 0, "shape": "MESH", "mesh": 0, "physicalMaterial": "rubber",
        }
        primitive = self.doc["meshes"][0]["primitives"][0]
        triangle_count = self.doc["accessors"][primitive["indices"]]["count"] // 3
        primitive["extensions"] = {
            K.PHYSICAL_SURFACES_EXT: {"faceMaterials": ["stone"] * triangle_count},
        }
        self.doc["extensionsUsed"] = [K.PHYSICAL_SURFACES_EXT]
        self.doc["extensionsRequired"] = [K.PHYSICAL_SURFACES_EXT]
        report = self.validate()
        self.assertTrue(report.ok, report.format())
        self.assertEqual(PS.query_physical_material(self.doc, 0, 0, 0)["id"], "stone")
        self.assertEqual(PS.query_physical_material(self.doc, 0)["id"], "rubber")

        del primitive["extensions"][K.PHYSICAL_SURFACES_EXT]
        self.assertEqual(PS.query_physical_material(self.doc, 0, 0, 0)["id"], "rubber")
        self.doc["colliders"][0].pop("physicalMaterial")
        self.assertIsNone(PS.query_physical_material(self.doc, 0, 0, 0))
        with self.assertRaises(IndexError):
            PS.query_physical_material(self.doc, 0, 0, triangle_count)
        with self.assertRaises(ValueError):
            PS.query_physical_material(self.doc, 0, 0)

    def test_physical_face_material_ids_are_stable_references(self):
        self.doc["physicalMaterials"] = [{"id": "wood", "profile": "adm.phys.wood.v1",
                                          "friction": 0.65, "restitution": 0.15}]
        prim = self.doc["meshes"][0]["primitives"][0]
        tri_count = self.doc["accessors"][prim["indices"]]["count"] // 3
        prim["extensions"] = {K.PHYSICAL_SURFACES_EXT: {"faceMaterials": ["wood"] * tri_count}}
        self.doc["extensionsUsed"] = [K.PHYSICAL_SURFACES_EXT]
        self.doc["extensionsRequired"] = [K.PHYSICAL_SURFACES_EXT]
        self.assertTrue(self.validate().ok, self.validate().format())
        prim["extensions"][K.PHYSICAL_SURFACES_EXT]["faceMaterials"][0] = "missing"
        self.assertIn("PHYSICAL_FACE_REFERENCE", self.codes())

    def test_terrain_surface_ids_map_local_layers_and_allow_custom_ids(self):
        self.doc["materials"] = [{"baseColorFactor": [1.0, 1.0, 1.0, 1.0]}]
        material = self.doc["materials"][0]
        material["extensions"] = {K.TERRAIN_SURFACE_EXT: {
            "version": "1.0.0",
            "surfaceIds": ["awt.surface.0123456789abcdef01234567", "org.example.custom-rock"],
        }}
        self.doc["extensionsUsed"] = [K.TERRAIN_SURFACE_EXT]
        self.assertTrue(self.validate().ok, self.validate().format())

        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = ["same", "same"]
        self.assertIn("TERRAIN_SURFACE_DUPLICATE", self.codes())
        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = ["x" * 129]
        self.assertIn("TERRAIN_SURFACE_ID", self.codes())
        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = ["one"]
        self.doc["extensionsRequired"] = [K.TERRAIN_SURFACE_EXT]
        self.assertIn("TERRAIN_SURFACE_REQUIRED", self.codes())
        self.doc["extensionsRequired"] = []
        self.doc["extensions"] = {K.TERRAIN_SURFACE_EXT: {}}
        self.assertIn("TERRAIN_SURFACE_SCOPE", self.codes())

    def test_terrain_control_map_contract_and_required_declaration(self):
        builder = BinBuilder()
        positions = builder.add_accessor([(0, 0, 0), (1, 0, 0), (0, 0, 1)], "F32", "VEC3")
        indices = builder.add_accessor([0, 1, 2], "U16", "SCALAR")
        image = builder.add_view(encode_png(1, 1, bytes((64, 128, 192, 255))), chunk_type="IMAG")
        surface_ids = ["surface.0", "surface.1", "surface.2", "surface.3"]
        material = {
            "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 1.0,
            "emissiveFactor": [0.0, 0.0, 0.0], "alphaMode": "OPAQUE",
            "shader": {"id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_TERRAIN_4[1]},
            "extensions": {
                K.TERRAIN_SURFACE_EXT: {"version": "1.0.0", "surfaceIds": surface_ids},
                K.TERRAIN_CONTROL_MAP_EXT: {
                    "version": "1.0.0", "mode": "TEXTURE_RGBA", "texture": {"index": 0},
                    "mapping": "WORLD_PLANAR_XZ", "channelOrder": [0, 1, 2, 3],
                },
            },
        }
        self.doc = {
            "asset": {}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": positions},
                                        "indices": indices, "material": 0}]}],
            "materials": [material], "textures": [{"source": 0, "sampler": 0}],
            "samplers": [{"magFilter": "LINEAR", "minFilter": "LINEAR"}],
            "images": [{"bufferView": image, "mimeType": "image/png"}],
            "accessors": builder.accessors, "bufferViews": builder.buffer_views,
            "extensionsUsed": [K.TERRAIN_SURFACE_EXT, K.TERRAIN_CONTROL_MAP_EXT],
            "extensionsRequired": [K.TERRAIN_CONTROL_MAP_EXT],
        }
        self.chunks = builder.bytes()
        report = self.validate()
        self.assertTrue(report.ok, report.format())

        material["extensions"][K.TERRAIN_CONTROL_MAP_EXT]["channelOrder"] = [0, 1, 1, 3]
        self.assertIn("TERRAIN_CONTROL_MAP_CHANNEL_ORDER", self.codes())
        material["extensions"][K.TERRAIN_CONTROL_MAP_EXT]["channelOrder"] = [0, 1, 2, 3]
        control = material["extensions"][K.TERRAIN_CONTROL_MAP_EXT]
        control["texture"]["texCoord"] = 0
        self.assertIn("TERRAIN_CONTROL_MAP_TEXCOORD", self.codes())
        del control["texture"]["texCoord"]
        control["mapping"] = "UV"
        control["origin"] = [1.0, 2.0]
        self.assertIn("TERRAIN_CONTROL_MAP_ORIGIN", self.codes())
        del control["origin"]
        control["mapping"] = "WORLD_PLANAR_XZ"

        rgb_image = builder.add_view(
            encode_png(1, 1, bytes((64, 128, 192)), channels=3), chunk_type="IMAG"
        )
        self.doc["bufferViews"] = builder.buffer_views
        self.doc["images"].append({"bufferView": rgb_image, "mimeType": "image/png"})
        self.doc["textures"][0]["source"] = 1
        self.chunks = builder.bytes()
        self.assertIn("TERRAIN_CONTROL_MAP_CHANNELS", self.codes())
        control["mode"] = "TEXTURE_RGB_IMPLICIT"
        self.assertNotIn("TERRAIN_CONTROL_MAP_CHANNELS", self.codes())
        control["mode"] = "TEXTURE_RGBA"
        self.doc["textures"][0]["source"] = 0

        self.doc["samplers"][0]["minFilter"] = "NEAREST"
        self.assertIn("TERRAIN_CONTROL_MAP_FILTER", self.codes())
        self.doc["samplers"][0]["minFilter"] = "LINEAR"
        self.doc["extensionsRequired"] = []
        self.assertIn("TERRAIN_CONTROL_MAP_REQUIRED", self.codes())
        self.doc["extensionsRequired"] = [K.TERRAIN_CONTROL_MAP_EXT]
        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = surface_ids[:3]
        self.assertIn("TERRAIN_CONTROL_MAP_SURFACES", self.codes())
        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = surface_ids
        material["shader"] = {"id": K.SHADER_CORE[0], "version": K.SHADER_CORE[1]}
        self.assertIn("TERRAIN_CONTROL_MAP_PROFILE", self.codes())
        material["shader"] = {"id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_TERRAIN_4[1]}
        control["mode"] = "VERTEX_ONLY"
        del control["texture"]
        del control["mapping"]
        material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = surface_ids[:3]
        self.assertIn("TERRAIN_CONTROL_MAP_SURFACES", self.codes())

    def test_external_control_map_validates_channels_after_resolution(self):
        blob = encode_png(1, 1, bytes((64, 128, 192)), channels=3)
        material = {
            "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 1.0,
            "emissiveFactor": [0.0, 0.0, 0.0], "alphaMode": "OPAQUE",
            "shader": {"id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_TERRAIN_4[1]},
            "extensions": {
                K.TERRAIN_SURFACE_EXT: {
                    "version": "1.0.0", "surfaceIds": ["a", "b", "c", "d"],
                },
                K.TERRAIN_CONTROL_MAP_EXT: {
                    "version": "1.0.0", "mode": "TEXTURE_RGBA", "texture": {"index": 0},
                    "mapping": "WORLD_PLANAR_XZ",
                },
            },
        }
        self.doc["materials"] = [material]
        self.doc["meshes"][0]["primitives"][0]["material"] = 0
        self.doc["textures"] = [{"source": 0}]
        self.doc["images"] = [{"uri": "textures/control.png", "mimeType": "image/png"}]
        self.doc["extensionsUsed"] = [
            K.EXTERNAL_IMAGES_EXT, K.TERRAIN_SURFACE_EXT, K.TERRAIN_CONTROL_MAP_EXT,
        ]
        self.doc["extensionsRequired"] = [K.EXTERNAL_IMAGES_EXT, K.TERRAIN_CONTROL_MAP_EXT]
        data = write_container(K.ADM_MAGIC, self.doc, self.chunks)
        self.assertTrue(validate_adm(data).ok, validate_adm(data).format())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "textures").mkdir()
            (root / "textures" / "control.png").write_bytes(blob)
            model_path = root / "model.adm"
            model_path.write_bytes(data)
            report = validate_adm_resolved(data, model_path)
        self.assertIn("TERRAIN_CONTROL_MAP_CHANNELS", {issue.code for issue in report.errors})

    def test_external_image_uri_hash_and_resolved_validation(self):
        blob = encode_png(2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 255)))
        digest = hashlib.sha256(blob).hexdigest()
        self.doc["images"] = [{"uri": "textures/wall.png", "mimeType": "image/png", "sha256": digest}]
        self.doc["textures"] = [{"source": 0}]
        self.doc["extensionsUsed"] = [K.EXTERNAL_IMAGES_EXT]
        self.doc["extensionsRequired"] = [K.EXTERNAL_IMAGES_EXT]
        data = write_container(K.ADM_MAGIC, self.doc, self.chunks)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "textures").mkdir()
            (root / "textures" / "wall.png").write_bytes(blob)
            model_path = root / "model.adm"
            model_path.write_bytes(data)
            self.assertTrue(validate_adm_resolved(data, model_path).ok)
            self.doc["images"][0]["sha256"] = "0" * 64
            corrupt = write_container(K.ADM_MAGIC, self.doc, self.chunks)
            self.assertIn("IMAGE_EXTERNAL_SHA256",
                          {e.code for e in validate_adm_resolved(corrupt, model_path).errors})

    def test_external_image_uri_rejects_traversal_and_needs_extension(self):
        self.doc["images"] = [{"uri": "../outside.png", "mimeType": "image/png"}]
        self.assertIn("IMAGE_EXTERNAL_URI", self.codes())
        self.doc["images"][0]["uri"] = "textures/wall.png"
        self.doc["extensionsUsed"] = [K.EXTERNAL_IMAGES_EXT]
        self.doc["extensionsRequired"] = []
        self.assertIn("IMAGE_EXTERNAL_EXT", self.codes())

    def test_external_image_symlink_cannot_escape_asset_root(self):
        blob = encode_png(1, 1, bytes((255, 255, 255, 255)))
        self.doc["images"] = [{"uri": "textures/link.png", "mimeType": "image/png"}]
        self.doc["extensionsUsed"] = [K.EXTERNAL_IMAGES_EXT]
        self.doc["extensionsRequired"] = [K.EXTERNAL_IMAGES_EXT]
        data = write_container(K.ADM_MAGIC, self.doc, self.chunks)
        with tempfile.TemporaryDirectory() as asset_dir, tempfile.TemporaryDirectory() as outside_dir:
            asset_root = Path(asset_dir)
            link_dir = asset_root / "textures"
            link_dir.mkdir()
            outside_image = Path(outside_dir) / "outside.png"
            outside_image.write_bytes(blob)
            link = link_dir / "link.png"
            try:
                link.symlink_to(outside_image)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            model_path = asset_root / "model.adm"
            model_path.write_bytes(data)
            report = validate_adm_resolved(data, model_path)
            self.assertIn("IMAGE_EXTERNAL_PATH", {e.code for e in report.errors})

    def test_animation_accessors_require_anim_chunk(self):
        doc, chunks = read_container((FIXTURES / "shader_parameter_tracks.adm_anim").read_bytes(), K.ANIM_MAGIC)
        # A model's GEOM payload has a valid byte range but is not animation storage.
        chunk_id = next(iter(self.chunks.entries))
        doc["bufferViews"][0] = {"chunkId": chunk_id, "byteOffset": 0, "byteLength": 4}
        report = validate_anim(write_container(K.ANIM_MAGIC, doc, self.chunks))
        self.assertIn("ANIMATION_CHUNK_TYPE", {e.code for e in report.errors})

    def test_ktx2_fallback_and_image_chunk_types(self):
        builder = BinBuilder()
        primary = builder.add_view(b"\xabKTX 20\xbb\r\n\x1a\n" + bytes(68), chunk_type="IMAG")
        alternate = builder.add_view(encode_png(1, 1, b"\xff\x00\x00\xff"), chunk_type="IMAG")
        doc = {"asset": {}, "nodes": [{}], "scenes": [{"nodes": [0]}], "scene": 0, "meshes": [],
               "accessors": [], "bufferViews": builder.buffer_views,
               "images": [{"bufferView": primary, "mimeType": "image/ktx2"},
                          {"bufferView": alternate, "mimeType": "image/png"}],
               "textures": [{"source": 0, "fallbackSource": 1}]}
        chunks = builder.bytes()

        def validate(changed):
            return validate_adm(write_container(K.ADM_MAGIC, changed, chunks))

        report = validate(doc)
        # A header-only stub is not a decodable ADM-subset KTX2 (valid files: test_gputex).
        self.assertIn("IMAGE_DECODE", {e.code for e in report.errors})
        for texture, code in (({"source": 0}, "IMAGE_FALLBACK_REQUIRED"),
                              ({"source": 0, "fallbackSource": 0}, "IMAGE_FALLBACK_TYPE"),
                              ({"source": 1, "fallbackSource": 0}, "IMAGE_FALLBACK_FORBIDDEN")):
            with self.subTest(texture=texture):
                changed = copy.deepcopy(doc)
                changed["textures"] = [texture]
                self.assertIn(code, {e.code for e in validate(changed).errors})
        changed = copy.deepcopy(doc)
        changed["images"][1]["bufferView"] = primary
        # A KTX2 range cannot be interpreted as the PNG portable fallback.
        self.assertIn("IMAGE_DECODE", {e.code for e in validate(changed).errors})

    def test_tint_palette_height_one_to_five(self):
        for height, ok in ((1, True), (5, True), (6, False)):
            with self.subTest(height=height):
                builder = BinBuilder()
                positions = builder.add_accessor([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "F32", "VEC3")
                indices = builder.add_accessor([0, 1, 2], "U16", "SCALAR")
                image = builder.add_view(encode_png(2, height, b"\x80\x40\x20\xff" * 2 * height),
                                         chunk_type="IMAG")
                doc = {
                    "asset": {}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": positions},
                                                "indices": indices, "material": 0}]}],
                    "materials": [{"extensions": {K.VERTEX_CONTROL_EXT: {"tintPalette": {"index": 0}}}}],
                    "samplers": [{"magFilter": "NEAREST", "minFilter": "NEAREST"}],
                    "textures": [{"source": 0, "sampler": 0}],
                    "images": [{"bufferView": image, "mimeType": "image/png"}],
                    "accessors": builder.accessors, "bufferViews": builder.buffer_views,
                    "extensionsUsed": [K.VERTEX_CONTROL_EXT], "extensionsRequired": [K.VERTEX_CONTROL_EXT],
                }
                report = validate_adm(write_container(K.ADM_MAGIC, doc, builder.bytes()))
                if ok:
                    self.assertTrue(report.ok, report.format())
                else:
                    self.assertIn("VERTEX_CONTROL_PALETTE_SIZE", {e.code for e in report.errors})


class InteractiveSurfaceTests(unittest.TestCase):
    def setUp(self):
        builder = BinBuilder()
        positions = builder.add_accessor([(0, 0, 0), (1, 0, 0.1), (1, 1, 0.1), (0, 1, 0)],
                                        "F32", "VEC3")
        uv0 = builder.add_accessor([(0, 1), (1, 1), (1, 0), (0, 0)], "F32", "VEC2")
        uv1 = builder.add_accessor([(1, 1), (0, 1), (0, 0), (1, 0)], "F32", "VEC2")
        indices = builder.add_accessor([0, 1, 2, 0, 2, 3], "U16", "SCALAR")
        image = builder.add_view(encode_png(1, 1, b"\x20\x40\x60\xff"), chunk_type="IMAG")
        self.chunks = builder.bytes()
        self.doc = {
            "asset": {}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"mesh": 0}, {"mesh": 0}],
            "meshes": [{"primitives": [
                {"attributes": {"POSITION": positions, "TEXCOORD_0": uv0, "TEXCOORD_1": uv1},
                "indices": indices, "material": 1},
                {"attributes": {"POSITION": positions}, "indices": indices, "material": 0},
            ]}],
            "materials": [
                {"baseColorFactor": [0.2, 0.2, 0.2, 1]},
                {"animationId": "screen_material", "shader": {"id": K.SHADER_INTERACTIVE[0],
                                                                "version": K.SHADER_INTERACTIVE[1]},
                "baseColorFactor": [1, 1, 1, 1], "baseColorTexture": {"index": 0},
                "metallicFactor": 0, "roughnessFactor": 1, "emissiveFactor": [0, 0, 0],
                "alphaMode": "OPAQUE"},
            ],
            "textures": [{"source": 0}], "images": [{"bufferView": image, "mimeType": "image/png"}],
            "accessors": builder.accessors, "bufferViews": builder.buffer_views,
            "extensionsUsed": [K.INTERACTIVE_SURFACES_EXT],
            "extensions": {K.INTERACTIVE_SURFACES_EXT: {
                "version": K.INTERACTIVE_SURFACES_VERSION,
                "surfaces": [
                    {"surfaceId": "left_screen", "aspectRatio": 1.5,
                    "bindings": [{"node": 0, "primitive": 0, "texCoord": 0}]},
                    {"surfaceId": "right_screen",
                    "bindings": [{"node": 1, "primitive": 0, "texCoord": 1}]},
                ],
            }},
        }

    def validate(self, doc=None):
        return validate_adm(write_container(K.ADM_MAGIC, self.doc if doc is None else doc, self.chunks))

    def codes(self, doc):
        return {issue.code for issue in self.validate(doc).errors}

    def test_shared_shader_curved_mesh_multiple_surfaces_and_fallback(self):
        report = self.validate()
        self.assertTrue(report.ok, report.format())
        ext = self.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]
        ext["surfaces"][0]["bindings"].extend(ext["surfaces"][1]["bindings"])
        ext["surfaces"].pop()
        report = self.validate()
        self.assertTrue(report.ok, report.format())

    def test_extension_policy_and_unknown_shader_version_fallback(self):
        required = copy.deepcopy(self.doc)
        required["extensionsRequired"] = [K.INTERACTIVE_SURFACES_EXT]
        self.assertTrue(self.validate(required).ok, self.validate(required).format())
        optional_unknown = copy.deepcopy(self.doc)
        optional_unknown["extensionsUsed"].append("Other_v1")
        optional_unknown["extensions"]["Other_v1"] = {"data": "ignored"}
        self.assertTrue(self.validate(optional_unknown).ok, self.validate(optional_unknown).format())
        future = copy.deepcopy(self.doc)
        future["materials"][1]["shader"]["version"] = "2.0.0"
        del future["extensions"]
        del future["extensionsUsed"]
        report = self.validate(future)
        self.assertTrue(report.ok, report.format())
        self.assertIn("SHADER_UNKNOWN_OFFICIAL", {issue.code for issue in report.warnings})

    def test_nonfinite_interactive_uv_has_accessor_diagnostic(self):
        primitive = self.doc["meshes"][0]["primitives"][0]
        uv_index = primitive["attributes"]["TEXCOORD_0"]
        accessor = self.doc["accessors"][uv_index]
        view = self.doc["bufferViews"][accessor["bufferView"]]
        for value in (float("nan"), float("inf"), float("-inf")):
            payloads = {cid: bytes(data) for cid, data in self.chunks.items()}
            bad_uv = bytearray(payloads[view["chunkId"]])
            struct.pack_into("<f", bad_uv, view["byteOffset"] + accessor.get("byteOffset", 0), value)
            payloads[view["chunkId"]] = bytes(bad_uv)
            chunks = ChunkCollection(payloads, chunk_types={cid: entry.chunk_type
                                                            for cid, entry in self.chunks.entries.items()})
            data = write_container(K.ADM_MAGIC, self.doc, chunks)
            for reader in ("default", "without_numpy"):
                with self.subTest(value=value, reader=reader):
                    if reader == "without_numpy":
                        with mock.patch("adm_blender.core.validate._np", None):
                            report = validate_adm(data)
                    else:
                        report = validate_adm(data)
                    self.assertTrue(any(issue.code == "ADM_ERR_NONFINITE" and issue.path == f"accessors[{uv_index}]"
                                        for issue in report.errors), report.format())

    def test_aspect_ratio_remains_positive_in_binary32(self):
        self.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"][0]["aspectRatio"] = 1e-45
        report = self.validate()
        self.assertTrue(report.ok, report.format())

    def test_invalid_surface_bindings_and_shader_data(self):
        ext = K.INTERACTIVE_SURFACES_EXT
        cases = (
            ("duplicate ID", lambda d: d["extensions"][ext]["surfaces"][1].update(surfaceId="left_screen"),
            "INTERACTIVE_SURFACE_ID_DUPLICATE"),
            ("invalid ID", lambda d: d["extensions"][ext]["surfaces"][0].update(surfaceId="bad id"),
            "INTERACTIVE_SURFACE_ID"),
            ("node", lambda d: d["extensions"][ext]["surfaces"][0]["bindings"][0].update(node=999),
            "INDEX_RANGE"),
            ("primitive", lambda d: d["extensions"][ext]["surfaces"][0]["bindings"][0].update(primitive=999),
            "INDEX_RANGE"),
            ("UV set", lambda d: d["extensions"][ext]["surfaces"][0]["bindings"][0].update(texCoord=True),
            "INTERACTIVE_TEXCOORD"),
            ("missing UV", lambda d: d["meshes"][0]["primitives"][0]["attributes"].pop("TEXCOORD_0"),
            "INTERACTIVE_UV_MISSING"),
            ("corrupt UV reference",
            lambda d: d["meshes"][0]["primitives"][0]["attributes"].update(TEXCOORD_0=999), "INDEX_RANGE"),
            ("shader version", lambda d: d["materials"][1]["shader"].update(version="2.0.0"),
            "INTERACTIVE_MATERIAL"),
            ("invalid SemVer", lambda d: d["materials"][1]["shader"].update(version="1.0"),
            "SHADER_VERSION"),
            ("parameter range", lambda d: d["materials"][1].update(shaderParameters={"brightness": -1}),
            "SHADER_PARAM_VALUE"),
            ("parameter type", lambda d: d["materials"][1].update(shaderParameters={"unlit": 1}),
            "SHADER_PARAM_VALUE"),
            ("missing fallback", lambda d: d["materials"][1].pop("roughnessFactor"),
            "ADM_ERR_MISSING_PBR_FALLBACK"),
            ("extension version", lambda d: d["extensions"][ext].update(version="2.0.0"),
            "INTERACTIVE_EXTENSION_VERSION"),
            ("aspect ratio", lambda d: d["extensions"][ext]["surfaces"][0].update(aspectRatio=0),
            "INTERACTIVE_ASPECT_RATIO"),
            ("aspect ratio underflows binary32",
            lambda d: d["extensions"][ext]["surfaces"][0].update(aspectRatio=1e-46),
            "INTERACTIVE_ASPECT_RATIO"),
            ("huge aspect ratio", lambda d: d["extensions"][ext]["surfaces"][0].update(aspectRatio=10 ** 400),
            "INTERACTIVE_ASPECT_RATIO"),
            ("huge brightness", lambda d: d["materials"][1].update(shaderParameters={"brightness": 10 ** 400}),
            "SHADER_PARAM_VALUE"),
            ("unbound primitive", lambda d: d["extensions"][ext]["surfaces"].pop(),
            "INTERACTIVE_BINDING_MISSING"),
            ("missing extension data", lambda d: d.pop("extensions"), "INTERACTIVE_EXTENSION_MISSING"),
            ("duplicate binding",
            lambda d: d["extensions"][ext]["surfaces"][1]["bindings"][0].update(node=0, texCoord=0),
            "INTERACTIVE_BINDING_DUPLICATE"),
            ("noninteractive material", lambda d: d["meshes"][0]["primitives"][0].update(material=0),
            "INTERACTIVE_MATERIAL"),
            ("unknown required extension",
            lambda d: (d["extensionsUsed"].append("Other_v1"), d.update(extensionsRequired=["Other_v1"])),
            "EXTENSION_UNSUPPORTED"),
        )
        for label, mutate, code in cases:
            with self.subTest(case=label):
                changed = copy.deepcopy(self.doc)
                mutate(changed)
                self.assertIn(code, self.codes(changed))

    def test_external_fallback_is_validated_and_resolved(self):
        blob = encode_png(1, 1, b"\x20\x40\x60\xff")
        self.doc["images"] = [{"uri": "screen.png", "mimeType": "image/png",
                              "sha256": hashlib.sha256(blob).hexdigest()}]
        self.doc["extensionsUsed"].append(K.EXTERNAL_IMAGES_EXT)
        self.doc["extensionsRequired"] = [K.EXTERNAL_IMAGES_EXT]
        data = write_container(K.ADM_MAGIC, self.doc, self.chunks)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "screen.png").write_bytes(blob)
            report = validate_adm_resolved(data, root / "terminal.adm")
            self.assertTrue(report.ok, report.format())

    def test_published_negative_interactive_fixtures(self):
        cases = {
            "duplicate_id": "INTERACTIVE_SURFACE_ID_DUPLICATE",
            "node": "INDEX_RANGE",
            "primitive": "INDEX_RANGE",
            "missing_uv": "INTERACTIVE_UV_MISSING",
            "uv_set": "INTERACTIVE_TEXCOORD",
            "shader_version": "INTERACTIVE_MATERIAL",
            "parameter": "SHADER_PARAM_VALUE",
            "extension_version": "INTERACTIVE_EXTENSION_VERSION",
            "required_unknown": "EXTENSION_UNSUPPORTED",
            "bad_material": "INTERACTIVE_MATERIAL",
            "missing_fallback": "ADM_ERR_MISSING_PBR_FALLBACK",
        }
        for name, code in cases.items():
            with self.subTest(case=name):
                path = FIXTURES.parent / "invalid" / f"bad_interactive_{name}.adm"
                report = validate_adm(path.read_bytes())
                self.assertIn(code, {issue.code for issue in report.errors}, report.format())


if __name__ == "__main__":
    unittest.main()
