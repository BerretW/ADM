"""Draft 0.4 material fallback and optional semantic-record validation."""

import copy
from pathlib import Path
import unittest

from adm_blender.core import constants as K
from adm_blender.core.buffers import BinBuilder
from adm_blender.core.container import read_container, write_container
from adm_blender.core.png import encode_png
from adm_blender.core.validate import validate_adm, validate_anim


FIXTURES = Path(__file__).resolve().parents[2] / "adm-standard" / "fixtures" / "valid"


class Draft4Tests(unittest.TestCase):
    def setUp(self):
        self.doc, self.chunks = read_container((FIXTURES / "triangle.adm").read_bytes(), K.ADM_MAGIC)

    def validate(self, doc=None):
        return validate_adm(write_container(K.ADM_MAGIC, self.doc if doc is None else doc, self.chunks))

    def codes(self, doc=None):
        return {issue.code for issue in self.validate(doc).errors}

    def test_published_fixtures(self):
        for path in sorted(FIXTURES.glob("*.adm*")):
            with self.subTest(path=path.name):
                validate = validate_anim if path.suffix == ".adm_anim" else validate_adm
                report = validate(path.read_bytes())
                self.assertTrue(report.ok, report.format())

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


if __name__ == "__main__":
    unittest.main()
