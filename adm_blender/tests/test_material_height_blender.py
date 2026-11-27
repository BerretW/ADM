"""Verify optional material-height metadata survives Blender round trips."""

import os
import sys
import tempfile

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import adm_blender
from adm_blender.blender import materials as M
from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
from adm_blender.blender.import_adm import ImportError_, ImportOptions, ModelImporter
from adm_blender.core import constants as K
from adm_blender.core.buffers import read_accessor_np, read_view
from adm_blender.core.container import read_container, write_container
from adm_blender.core.validate import validate_adm


def main():
    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    uv1 = obj.data.uv_layers.new(name="UVMap_1")
    for source, target in zip(obj.data.uv_layers[0].data, uv1.data):
        target.uv = (1.0 - source.uv.x, source.uv.y)
    mat = bpy.data.materials.new("Material height")
    mat.use_nodes = True
    obj.data.materials.append(mat)
    image = bpy.data.images.new("Height source", 4, 4, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(np.tile(np.array((0.3, 0.6, 0.8, 1.0), dtype=np.float32), 16))
    image.update()
    image.pack()
    M.set_slot_image(mat, "NORMAL", image)
    bpy.ops.adm.create_model_root(name="Height root")
    root = bpy.data.objects["Height root"]
    original, report = ModelExporter(
        bpy.context, root, ExportOptions(image_format="DDS", gpu_compression="RGBA8")).export()
    assert report.ok, report.errors
    doc, chunks = read_container(original, K.ADM_MAGIC)
    material = doc["materials"][0]
    ref = material.pop("normalTexture")
    texture = doc["textures"][ref["index"]]
    gpu_image = doc["images"][texture["source"]]
    source_blob = read_view(doc, chunks, gpu_image["bufferView"])
    sampler = {"wrapS": "CLAMP_TO_EDGE", "wrapT": "MIRRORED_REPEAT",
               "magFilter": "NEAREST", "extras": {"note": "preserve"}}
    doc.setdefault("samplers", []).append(sampler)
    texture["sampler"] = len(doc["samplers"]) - 1
    height = {"version": "1.0.0", "heightTexture": {"index": ref["index"], "texCoord": 1},
              "channel": "G", "invert": True, "scale": 2.0, "bias": -0.2,
              "referenceHeight": 0.3, "parallaxMode": "PARALLAX_OCCLUSION",
              "parallaxScale": 0.04, "pomMinSteps": 7, "pomMaxSteps": 27,
              "futureControl": {"weights": [0.25, 0.75], "enabled": True},
              "extras": {"uneditable": ["keep", 3]},
              "extensions": {"EXAMPLE_height_metadata": {"value": "keep"}}}
    material.setdefault("extensions", {})[K.MATERIAL_HEIGHT_EXT] = height
    unknown_material = {"unrecognized": True, "future": {"values": [0.2, "text"]}}
    material["extensions"]["EXAMPLE_unknown_material"] = unknown_material
    doc.setdefault("extensionsUsed", []).append(K.MATERIAL_HEIGHT_EXT)
    doc["extensionsUsed"].append("EXAMPLE_height_metadata")
    doc["extensionsUsed"].append("EXAMPLE_unknown_material")
    fixture = write_container(K.ADM_MAGIC, doc, chunks)
    validation = validate_adm(fixture)
    assert validation.ok, [str(issue) for issue in validation.errors]

    def check_uv1_tangent(exported, binary):
        primitive = exported["meshes"][0]["primitives"][0]
        assert "TANGENT" in primitive["attributes"]
        attrs = primitive["attributes"]
        positions = read_accessor_np(exported, binary, attrs["POSITION"])
        uvs = read_accessor_np(exported, binary, attrs["TEXCOORD_1"])
        tangents = read_accessor_np(exported, binary, attrs["TANGENT"])
        indices = read_accessor_np(exported, binary, primitive["indices"]).reshape(-1)
        i, j, k = indices[:3]
        e1, e2 = positions[j] - positions[i], positions[k] - positions[i]
        d1, d2 = uvs[j] - uvs[i], uvs[k] - uvs[i]
        tangent = (e1 * d2[1] - e2 * d1[1]) / (d1[0] * d2[1] - d2[0] * d1[1])
        tangent /= np.linalg.norm(tangent)
        assert np.dot(tangent, tangents[i, :3]) > 0.99

    def check_export(data):
        exported, binary = read_container(data, K.ADM_MAGIC)
        actual = exported["materials"][0]["extensions"][K.MATERIAL_HEIGHT_EXT]
        assert {k: v for k, v in actual.items() if k != "heightTexture"} == {
            k: v for k, v in height.items() if k != "heightTexture"}
        assert actual["heightTexture"]["texCoord"] == 1
        tex = exported["textures"][actual["heightTexture"]["index"]]
        assert exported["samplers"][tex["sampler"]] == sampler
        source = exported["images"][tex["source"]]
        assert read_view(exported, binary, source["bufferView"]) == source_blob
        assert K.MATERIAL_HEIGHT_EXT in exported["extensionsUsed"]
        assert "EXAMPLE_height_metadata" in exported["extensionsUsed"]
        assert exported["materials"][0]["extensions"]["EXAMPLE_unknown_material"] == unknown_material
        assert "EXAMPLE_unknown_material" in exported["extensionsUsed"]
        check_uv1_tangent(exported, binary)

    with tempfile.TemporaryDirectory(prefix="adm_material_height_") as folder:
        path = os.path.join(folder, "optional.adm")
        with open(path, "wb") as stream:
            stream.write(fixture)
        print("PHASE import optional material height", flush=True)
        importer = ModelImporter(bpy.context, path, ImportOptions())
        importer.run()
        assert any("MATERIAL_HEIGHT_FALLBACK" in warning for warning in importer.warnings)
        assert any("MATERIAL_HEIGHT_UNKNOWN" in warning and "futureControl" in warning
                   for warning in importer.warnings)
        assert any("OPTIONAL_EXTENSIONS_UNSUPPORTED" in warning and "EXAMPLE_unknown_material" in warning
                   for warning in importer.warnings)
        exporter = ModelExporter(bpy.context, importer.root, ExportOptions())
        encoded, report = exporter.export()
        assert report.ok, report.errors
        assert any("unknown material-height fields" in warning for warning in exporter.warnings)
        assert any("unknown material extensions are preserved" in warning for warning in exporter.warnings)
        assert any("OPTIONAL_EXTENSIONS_UNSUPPORTED" in warning and "EXAMPLE_unknown_material" in warning
                   for warning in exporter.warnings)
        check_export(encoded)
        print("PHASE save and reopen Blender project", flush=True)
        root_name = importer.root.name
        blend_path = os.path.join(folder, "height.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        exporter = ModelExporter(bpy.context, bpy.data.objects[root_name], ExportOptions())
        encoded, report = exporter.export()
        assert report.ok, report.errors
        assert any("OPTIONAL_EXTENSIONS_UNSUPPORTED" in warning and "EXAMPLE_unknown_material" in warning
                   for warning in exporter.warnings)
        check_export(encoded)
        bpy.ops.object.select_all(action="DESELECT")
        imported_root = bpy.data.objects[root_name]
        imported_mesh = next(obj for obj in imported_root.children_recursive if obj.type == "MESH")
        imported_mesh.select_set(True)
        exporter = ModelExporter(bpy.context, None, ExportOptions(selected_only=True))
        selected_data, report = exporter.export()
        assert report.ok, report.errors
        assert any("OPTIONAL_EXTENSIONS_UNSUPPORTED" in warning and "EXAMPLE_unknown_material" in warning
                   for warning in exporter.warnings)
        selected_doc, _ = read_container(selected_data, K.ADM_MAGIC)
        assert selected_doc["materials"][0]["extensions"]["EXAMPLE_unknown_material"] == unknown_material
        imported_mat = imported_mesh.data.materials[0]
        saved_extensions = imported_mat[M.MATERIAL_UNKNOWN_EXTENSIONS]
        imported_mat[M.MATERIAL_UNKNOWN_EXTENSIONS] = "{broken"
        exporter = ModelExporter(bpy.context, imported_root, ExportOptions())
        try:
            exporter.export()
        except ExportError as exc:
            assert "cannot preserve unknown extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown extension metadata was accepted")
        imported_mat[M.MATERIAL_UNKNOWN_EXTENSIONS] = saved_extensions
        print("PHASE differing normal and height UV sets", flush=True)
        material["normalTexture"] = ref
        path = os.path.join(folder, "mixed_uv.adm")
        with open(path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, doc, chunks))
        mixed = ModelImporter(bpy.context, path, ImportOptions())
        mixed.run()
        exporter = ModelExporter(bpy.context, mixed.root, ExportOptions())
        encoded, report = exporter.export()
        assert report.ok, report.errors
        assert any("different UV sets" in warning for warning in exporter.warnings)
        exported, _ = read_container(encoded, K.ADM_MAGIC)
        assert exported["materials"][0]["extensions"][K.MATERIAL_HEIGHT_EXT]["heightTexture"]["texCoord"] == 1
        del material["normalTexture"]
        print("PHASE reject required material height", flush=True)
        doc.setdefault("extensionsRequired", []).append(K.MATERIAL_HEIGHT_EXT)
        required = write_container(K.ADM_MAGIC, doc, chunks)
        path = os.path.join(folder, "required.adm")
        with open(path, "wb") as stream:
            stream.write(required)
        before = (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))
        try:
            ModelImporter(bpy.context, path, ImportOptions()).run()
        except ImportError_ as exc:
            assert "required" in str(exc) and K.MATERIAL_HEIGHT_EXT in str(exc)
        else:
            raise AssertionError("Required unsupported material height was accepted")
        assert before == (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))
        print("PHASE layered shader parallax without a normal map", flush=True)
        doc["extensionsRequired"].remove(K.MATERIAL_HEIGHT_EXT)
        del material["extensions"][K.MATERIAL_HEIGHT_EXT]
        material["shader"] = {"id": K.SHADER_TWO_LAYER[0], "version": K.SHADER_PROFILE_LAYERED_HEIGHT_V1}
        material["animationId"] = "height_only"
        material["emissiveFactor"] = [0, 0, 0]
        material["alphaMode"] = "OPAQUE"
        doc["textures"].append({"source": texture["fallbackSource"]})
        material["shaderParameters"] = {
            "layer0_texture": {"index": len(doc["textures"]) - 1, "texCoord": 1},
            "layer0_height_texture": {"index": ref["index"], "texCoord": 1},
            "layer0_parallax_scale": 0.1,
            "parallax_mode": "PARALLAX_OCCLUSION",
        }
        path = os.path.join(folder, "shader_height.adm")
        shader_fixture = write_container(K.ADM_MAGIC, doc, chunks)
        validation = validate_adm(shader_fixture)
        assert validation.ok, [str(issue) for issue in validation.errors]
        with open(path, "wb") as stream:
            stream.write(shader_fixture)
        layered = ModelImporter(bpy.context, path, ImportOptions())
        layered.run()
        encoded, report = ModelExporter(bpy.context, layered.root, ExportOptions()).export()
        assert report.ok, report.errors
        exported, binary = read_container(encoded, K.ADM_MAGIC)
        assert "normalTexture" not in exported["materials"][0]
        check_uv1_tangent(exported, binary)
        material["shaderParameters"]["layer1_height_texture"] = {"index": ref["index"]}
        material["shaderParameters"]["layer1_parallax_scale"] = 0.1
        path = os.path.join(folder, "shader_mixed_uv.adm")
        with open(path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, doc, chunks))
        layered = ModelImporter(bpy.context, path, ImportOptions())
        layered.run()
        exporter = ModelExporter(bpy.context, layered.root, ExportOptions())
        encoded, report = exporter.export()
        assert report.ok, [str(issue) for issue in report.errors]
        assert any("different UV sets" in warning for warning in exporter.warnings)
        exported, binary = read_container(encoded, K.ADM_MAGIC)
        check_uv1_tangent(exported, binary)
        material["shaderParameters"]["parallax_mode"] = "NONE"
        path = os.path.join(folder, "shader_no_parallax.adm")
        with open(path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, doc, chunks))
        layered = ModelImporter(bpy.context, path, ImportOptions())
        layered.run()
        encoded, report = ModelExporter(bpy.context, layered.root, ExportOptions()).export()
        assert report.ok, [str(issue) for issue in report.errors]
        exported, _ = read_container(encoded, K.ADM_MAGIC)
        assert "TANGENT" not in exported["meshes"][0]["primitives"][0]["attributes"]
        print("PHASE core normal map using mirrored UV 1", flush=True)
        material.pop("shader")
        material.pop("shaderParameters")
        material["normalTexture"] = {"index": ref["index"], "texCoord": 1}
        path = os.path.join(folder, "normal_uv1.adm")
        with open(path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, doc, chunks))
        normal = ModelImporter(bpy.context, path, ImportOptions())
        normal.run()
        encoded, report = ModelExporter(bpy.context, normal.root, ExportOptions()).export()
        assert report.ok, [str(issue) for issue in report.errors]
        exported, binary = read_container(encoded, K.ADM_MAGIC)
        assert exported["materials"][0]["normalTexture"]["texCoord"] == 1
        check_uv1_tangent(exported, binary)
    print("RESULT: PASS", flush=True)


if __name__ == "__main__":
    main()
