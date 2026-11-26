"""Generate and round-trip the advanced reference ADM scene in Blender."""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy

from adm_blender.tests.build_advanced_material_test_scene import main as generate_scene


def main():
    from adm_blender.core import constants as K
    from adm_blender.core.container import read_container
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter

    with tempfile.TemporaryDirectory(prefix="adm_advanced_reference_") as tmp:
        blend_path = os.path.join(tmp, "reference.blend")
        generate_scene(blend_path)
        path = os.path.join(tmp, "reference.adm")
        with open(path, "rb") as stream:
            doc, _ = read_container(stream.read(), K.ADM_MAGIC)
        expected = set(K.SHADER_LAYERED_HEIGHT_COUNTS)
        assert len(doc["meshes"]) == 8
        assert len(doc["materials"]) == 8
        seen = set()
        for material in doc["materials"]:
            key = (material["shader"]["id"], material["shader"]["version"])
            params = material["shaderParameters"]
            blend = params["height_blend_enabled"]
            assert params["parallax_mode"] == ("PARALLAX_OCCLUSION" if blend else "PARALLAX")
            for index in range(K.SHADER_LAYERED_HEIGHT_COUNTS[key]):
                assert params[f"layer{index}_ao_texture"]
                assert params[f"layer{index}_height_texture"]
                assert params[f"layer{index}_normal"]
                assert params[f"layer{index}_parallax_scale"] > 0
            seen.add((key, blend))
        assert seen == {(key, blend) for key in expected for blend in (False, True)}
        print("PHASE import reference ADM", flush=True)
        bpy.ops.wm.read_homefile(use_empty=True)
        importer = ModelImporter(bpy.context, path, ImportOptions())
        importer.run()
        assert len(importer.materials) == 8
        imported = {(mat.adm.shader_key(), mat.adm.params["height_blend_enabled"].value_bool)
                    for mat in importer.materials}
        assert imported == seen
        for mat in importer.materials:
            blend = mat.adm.params["height_blend_enabled"].value_bool
            assert mat.adm.params["parallax_mode"].value_enum == (
                "PARALLAX_OCCLUSION" if blend else "PARALLAX")
            assert mat.adm.params["layer0_ao_texture"].image is not None
            assert mat.adm.params["layer0_height_texture"].image is not None
        print("PHASE re-export reference ADM", flush=True)
        data, report = ModelExporter(bpy.context, importer.root, ExportOptions(vertex_controls=True)).export()
        assert report.ok, report.errors
        roundtrip, _ = read_container(data, K.ADM_MAGIC)
        roundtrip_seen = set()
        for material in roundtrip["materials"]:
            key = (material["shader"]["id"], material["shader"]["version"])
            params = material["shaderParameters"]
            blend = params["height_blend_enabled"]
            assert params["parallax_mode"] == ("PARALLAX_OCCLUSION" if blend else "PARALLAX")
            assert params["layer0_ao_texture"] and params["layer0_height_texture"]
            roundtrip_seen.add((key, blend))
        assert roundtrip_seen == seen
        print("RESULT: PASS", flush=True)


if __name__ == "__main__":
    main()
