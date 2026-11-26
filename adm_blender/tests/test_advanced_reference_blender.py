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
    from adm_blender.core.buffers import read_view
    from adm_blender.core import gputex
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter

    with tempfile.TemporaryDirectory(prefix="adm_advanced_reference_") as tmp:
        blend_path = os.path.join(tmp, "reference.blend")
        generate_scene(blend_path)
        path = os.path.join(tmp, "reference.adm")
        with open(path, "rb") as stream:
            doc, chunks = read_container(stream.read(), K.ADM_MAGIC)
        def gpu_sources(document, data_chunks):
            sources = {}
            for texture in document.get("textures", []):
                image = document["images"][texture["source"]]
                if image["mimeType"] not in (gputex.MIME_DDS, gputex.MIME_KTX2):
                    continue
                blob = read_view(document, data_chunks, image["bufferView"])
                info = gputex.parse(blob, image["mimeType"], strict=True)
                sources[info["kind"]] = blob
            return sources

        source_blobs = gpu_sources(doc, chunks)
        assert set(source_blobs) == {"R8", "R16", "BC4", "BC5", "BC7"}
        texture_dir = os.path.join(REPO, "appartus_world_tile", "reference_project", "textures")
        for kind, filename in (("R8", "cobblestone_height.ktx2"), ("R16", "rock_height.dds"),
                               ("BC4", "sand_height.dds"), ("BC5", "dirt_normal.ktx2"),
                               ("BC7", "grass_albedo.ktx2")):
            with open(os.path.join(texture_dir, filename), "rb") as stream:
                assert source_blobs[kind] == stream.read(), kind
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
        print("PHASE reopen reference Blender project", flush=True)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        reopened_root = bpy.data.objects["Advanced Material Reference"]
        reopened_data, reopened_report = ModelExporter(
            bpy.context, reopened_root, ExportOptions(vertex_controls=True)).export()
        assert reopened_report.ok, reopened_report.errors
        reopened_doc, reopened_chunks = read_container(reopened_data, K.ADM_MAGIC)
        assert gpu_sources(reopened_doc, reopened_chunks) == source_blobs
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
        roundtrip, roundtrip_chunks = read_container(data, K.ADM_MAGIC)
        assert gpu_sources(roundtrip, roundtrip_chunks) == source_blobs
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
