"""Verify material-height and physical-type metadata survives Blender round trips."""

import copy
import os
import sys
import tempfile

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import adm_blender
from adm_blender.blender import materials as M
from adm_blender.blender.export_adm import (
    UNKNOWN_MESH_EXTENSIONS_PROPERTY, UNKNOWN_NODE_EXTENSIONS_PROPERTY, UNKNOWN_PRIMITIVE_ATTRIBUTE,
    UNKNOWN_PRIMITIVE_EXTENSIONS_PROPERTY,
    UNKNOWN_ROOT_EXTENSIONS_PROPERTY, UNKNOWN_SCENE_EXTENSIONS_PROPERTY, ExportError, ExportOptions, ModelExporter,
)
from adm_blender.blender.import_adm import ImportError_, ImportOptions, ModelImporter
from adm_blender.core import constants as K
from adm_blender.core.buffers import read_accessor_np, read_view
from adm_blender.core.container import read_container, write_container
from adm_blender.core.png import encode_png
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
    physical = root.adm.physical_materials.add()
    physical.name = "meadow"
    physical.surface_type = "adm.physical.grass.v1"
    physical.surface_subtype = "adm.physical.grass.tall.v1"
    physical.surface_tags_json = '["adm.physical.tag.organic.v1","adm.physical.tag.vegetated.v1"]'
    physical.surface_description = "Tall meadow grass"
    physical.surface_tags_json = "{}"
    try:
        ModelExporter(bpy.context, root, ExportOptions()).export()
    except ExportError as exc:
        assert "Physical Tags JSON must be an array" in str(exc)
    else:
        raise AssertionError("non-array physical tags were accepted")
    physical.surface_tags_json = '["adm.physical.tag.organic.v1","adm.physical.tag.vegetated.v1"]'
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
    terrain_surface = {
        "version": "1.0.0",
        "surfaceIds": ["awt.surface.0123456789abcdef01234567"],
    }
    material["extensions"][K.TERRAIN_SURFACE_EXT] = terrain_surface
    unknown_material = {"unrecognized": True, "future": {"values": [0.2, "text"]}}
    material["extensions"]["EXAMPLE_unknown_material"] = unknown_material
    unknown_root = {"opaque": {"index": 2, "values": [True, "preserve"]}}
    doc.setdefault("extensions", {})["EXAMPLE_unknown_root"] = unknown_root
    unknown_node = {"opaque": [None, {"reference": 1}]}
    mesh_node = next(node for node in doc["nodes"] if "mesh" in node)
    mesh_node.setdefault("extensions", {})["EXAMPLE_unknown_node"] = unknown_node
    unknown_mesh = {"opaque": {"index": 3, "tag": "mesh"}}
    doc["meshes"][mesh_node["mesh"]].setdefault("extensions", {})["EXAMPLE_unknown_mesh"] = unknown_mesh
    unknown_scene = {"opaque": {"index": 5, "tag": "scene"}}
    doc["scenes"][doc["scene"]].setdefault("extensions", {})["EXAMPLE_unknown_scene"] = unknown_scene
    unknown_primitive = {"opaque": {"index": 4, "tag": "primitive"}}
    doc["meshes"][mesh_node["mesh"]]["primitives"][0].setdefault("extensions", {})[
        "EXAMPLE_unknown_primitive"] = unknown_primitive
    doc.setdefault("extensionsUsed", []).append(K.MATERIAL_HEIGHT_EXT)
    doc["extensionsUsed"].append(K.TERRAIN_SURFACE_EXT)
    doc["extensionsUsed"].append("EXAMPLE_height_metadata")
    doc["extensionsUsed"].append("EXAMPLE_unknown_material")
    doc["extensionsUsed"].append("EXAMPLE_unknown_root")
    doc["extensionsUsed"].append("EXAMPLE_unknown_node")
    doc["extensionsUsed"].append("EXAMPLE_unknown_mesh")
    doc["extensionsUsed"].append("EXAMPLE_unknown_scene")
    doc["extensionsUsed"].append("EXAMPLE_unknown_primitive")
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
        assert K.TERRAIN_SURFACE_EXT in exported["extensionsUsed"]
        assert K.TERRAIN_SURFACE_EXT not in exported.get("extensionsRequired", [])
        assert exported["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT] == terrain_surface
        assert "EXAMPLE_height_metadata" in exported["extensionsUsed"]
        assert exported["materials"][0]["extensions"]["EXAMPLE_unknown_material"] == unknown_material
        assert "EXAMPLE_unknown_material" in exported["extensionsUsed"]
        assert exported["extensions"]["EXAMPLE_unknown_root"] == unknown_root
        assert "EXAMPLE_unknown_root" in exported["extensionsUsed"]
        assert next(n for n in exported["nodes"] if "mesh" in n)["extensions"]["EXAMPLE_unknown_node"] == unknown_node
        assert "EXAMPLE_unknown_node" in exported["extensionsUsed"]
        assert exported["meshes"][0]["extensions"]["EXAMPLE_unknown_mesh"] == unknown_mesh
        assert "EXAMPLE_unknown_mesh" in exported["extensionsUsed"]
        assert exported["scenes"][exported["scene"]]["extensions"]["EXAMPLE_unknown_scene"] == unknown_scene
        assert "EXAMPLE_unknown_scene" in exported["extensionsUsed"]
        assert exported["meshes"][0]["primitives"][0]["extensions"]["EXAMPLE_unknown_primitive"] == unknown_primitive
        assert "EXAMPLE_unknown_primitive" in exported["extensionsUsed"]
        assert exported["physicalMaterials"] == [{
            "id": "meadow",
            "friction": 0.5,
            "restitution": 0.0,
            "type": "adm.physical.grass.v1",
            "subtype": "adm.physical.grass.tall.v1",
            "tags": ["adm.physical.tag.organic.v1", "adm.physical.tag.vegetated.v1"],
            "description": "Tall meadow grass",
        }]
        assert K.PHYSICAL_SURFACE_TYPES_EXT in exported["extensionsRequired"]
        check_uv1_tangent(exported, binary)

    with tempfile.TemporaryDirectory(prefix="adm_material_height_") as folder:
        print("PHASE unknown official shader round trip", flush=True)
        future_doc = copy.deepcopy(doc)
        future_material = future_doc["materials"][0]
        future_material["shader"] = {"id": K.SHADER_TWO_LAYER[0], "version": "99.0.0"}
        future_material["animationId"] = "future_shader"
        future_material["baseColorFactor"] = [1, 1, 1, 1]
        future_material["metallicFactor"] = 0.3
        future_material["roughnessFactor"] = 0.7
        future_material["emissiveFactor"] = [0, 0, 0]
        future_material["alphaMode"] = "OPAQUE"
        second_sampler = {"wrapS": "REPEAT", "magFilter": "LINEAR"}
        future_doc["samplers"].append(second_sampler)
        future_doc["textures"].append({**texture, "sampler": len(future_doc["samplers"]) - 1})
        parameters = {"future_mode": "SOME_MODE", "future_float": 0.123456789,
                      "future_vector": [0.2, 0.4, 0.6], "future_bool": True,
                      "future_empty": None, "future_texture": {"index": ref["index"], "texCoord": 1},
                      "future_texture_2": {"index": len(future_doc["textures"]) - 1},
                      "future_opaque": {"unknownReference": 17}}
        future_material["shaderParameters"] = parameters
        future_data = write_container(K.ADM_MAGIC, future_doc, chunks)
        validation = validate_adm(future_data)
        assert validation.ok, [str(issue) for issue in validation.errors]
        future_path = os.path.join(folder, "future.adm")
        with open(future_path, "wb") as stream:
            stream.write(future_data)
        future = ModelImporter(bpy.context, future_path, ImportOptions())
        future.run()
        assert any("SHADER_UNKNOWN_PRESERVED" in warning for warning in future.warnings)
        assert any("SHADER_OPAQUE_PARAMETER" in warning for warning in future.warnings)

        def check_future(root):
            exporter = ModelExporter(bpy.context, root, ExportOptions())
            encoded, report = exporter.export()
            assert report.ok, report.errors
            assert any("unknown shader parameters are preserved" in warning for warning in exporter.warnings)
            exported, binary = read_container(encoded, K.ADM_MAGIC)
            actual = exported["materials"][0]
            assert actual["shader"] == future_material["shader"]
            values = actual["shaderParameters"]
            assert {k: v for k, v in values.items() if k not in ("future_texture", "future_texture_2")} == {
                k: v for k, v in parameters.items() if k not in ("future_texture", "future_texture_2")}
            assert values["future_texture"]["texCoord"] == 1
            tex = exported["textures"][values["future_texture"]["index"]]
            assert exported["samplers"][tex["sampler"]] == sampler
            assert read_view(exported, binary, exported["images"][tex["source"]]["bufferView"]) == source_blob
            tex2 = exported["textures"][values["future_texture_2"]["index"]]
            assert exported["samplers"][tex2["sampler"]] == second_sampler
            assert read_view(exported, binary, exported["images"][tex2["source"]]["bufferView"]) == source_blob
            assert "TEXCOORD_1" in exported["meshes"][0]["primitives"][0]["attributes"]

        check_future(future.root)
        future_root_name = future.root.name
        future_blend = os.path.join(folder, "future.blend")
        bpy.ops.wm.save_as_mainfile(filepath=future_blend)
        bpy.ops.wm.open_mainfile(filepath=future_blend)
        future_root = bpy.data.objects[future_root_name]
        future_mesh = next(obj for obj in future_root.children_recursive if obj.type == "MESH")
        future_mat = future_mesh.data.materials[0]
        future_mat.adm.shader = "CORE"
        exporter = ModelExporter(bpy.context, future_root, ExportOptions())
        _, report = exporter.export()
        assert report.ok, report.errors
        assert any("inactive unknown shader parameters" in warning for warning in exporter.warnings)
        future_mat.adm.shader = "CUSTOM"
        future_mat.adm.custom_shader = f"{K.SHADER_TWO_LAYER[0]}@99.0.0"
        check_future(future_root)
        image_key = M.MATERIAL_UNKNOWN_SHADER_IMAGE + "0"
        saved_image = future_mat[image_key]
        del future_mat[image_key]
        try:
            ModelExporter(bpy.context, future_root, ExportOptions()).export()
        except ExportError as exc:
            assert "image for 'future_texture' is missing" in str(exc)
        else:
            raise AssertionError("Missing unknown-shader texture was accepted")
        future_mat[image_key] = saved_image

        invalid_doc = copy.deepcopy(future_doc)
        invalid_doc["materials"][0]["shaderParameters"]["future_texture"]["index"] = len(future_doc["textures"])
        invalid_path = os.path.join(folder, "future_invalid.adm")
        with open(invalid_path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, invalid_doc, chunks))
        try:
            ModelImporter(bpy.context, invalid_path, ImportOptions()).run()
        except ImportError_ as exc:
            assert "invalid unknown shader texture" in str(exc)
        else:
            raise AssertionError("Invalid unknown-shader texture reference was accepted")

        print("PHASE distinct unknown primitive extensions", flush=True)
        split_doc = copy.deepcopy(doc)
        split_mesh = split_doc["meshes"][mesh_node["mesh"]]
        first = split_mesh["primitives"][0]
        second = copy.deepcopy(first)
        second["extensions"]["EXAMPLE_unknown_primitive"] = {"tag": "second"}
        accessor = split_doc["accessors"][first["indices"]]
        assert accessor["componentType"] == "U16" and accessor["count"] % 6 == 0
        half = accessor["count"] // 2
        first_indices = copy.deepcopy(accessor)
        second_indices = copy.deepcopy(accessor)
        first_indices["count"] = second_indices["count"] = half
        second_indices["byteOffset"] = accessor.get("byteOffset", 0) + half * 2
        for item in (first_indices, second_indices):
            item.pop("min", None)
            item.pop("max", None)
        first["indices"] = len(split_doc["accessors"])
        second["indices"] = first["indices"] + 1
        split_doc["accessors"].extend([first_indices, second_indices])
        split_mesh["primitives"].append(second)
        split_path = os.path.join(folder, "unknown_primitives.adm")
        with open(split_path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, split_doc, chunks))
        split_importer = ModelImporter(bpy.context, split_path, ImportOptions())
        split_importer.run()
        split_data, split_report = ModelExporter(bpy.context, split_importer.root, ExportOptions()).export()
        assert split_report.ok, split_report.errors
        split_result, _ = read_container(split_data, K.ADM_MAGIC)
        assert [p["extensions"]["EXAMPLE_unknown_primitive"] for p in split_result["meshes"][0]["primitives"]] == [
            unknown_primitive, {"tag": "second"}]

        print("PHASE distinct unknown scene extensions", flush=True)
        multi_doc = copy.deepcopy(doc)
        second_node = copy.deepcopy(mesh_node)
        second_node.pop("children", None)
        multi_doc["nodes"].append(second_node)
        multi_doc["scenes"].append({"name": "Other", "nodes": [len(multi_doc["nodes"]) - 1],
                                    "extensions": {"EXAMPLE_unknown_scene": {"tag": "other"}}})
        multi_path = os.path.join(folder, "unknown_scenes.adm")
        with open(multi_path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, multi_doc, chunks))
        multi_importer = ModelImporter(bpy.context, multi_path, ImportOptions())
        multi_importer.run()
        multi_data, multi_report = ModelExporter(bpy.context, multi_importer.root, ExportOptions()).export()
        assert multi_report.ok, multi_report.errors
        multi_result, _ = read_container(multi_data, K.ADM_MAGIC)
        assert [s["extensions"]["EXAMPLE_unknown_scene"] for s in multi_result["scenes"]] == [
            unknown_scene, {"tag": "other"}]
        bpy.ops.object.select_all(action="DESELECT")
        multi_importer.root.select_set(True)
        multi_scene = next(obj for obj in multi_importer.root.children if obj.adm.adm_type == "SCENE")
        multi_scene.select_set(True)
        try:
            ModelExporter(bpy.context, None, ExportOptions(selected_only=True)).export()
        except ExportError as exc:
            assert "cannot merge selected objects from different scenes" in str(exc)
        else:
            raise AssertionError("Merging an ancestor and unknown scene was accepted")

        path = os.path.join(folder, "optional.adm")
        with open(path, "wb") as stream:
            stream.write(fixture)
        print("PHASE import optional material height", flush=True)
        importer = ModelImporter(bpy.context, path, ImportOptions())
        importer.run()
        physical = importer.root.adm.physical_materials[0]
        assert physical.surface_type == "adm.physical.grass.v1"
        assert physical.surface_subtype == "adm.physical.grass.tall.v1"
        assert physical.surface_tags_json == (
            '["adm.physical.tag.organic.v1","adm.physical.tag.vegetated.v1"]')
        assert physical.surface_description == "Tall meadow grass"
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
        assert any("Unknown root extensions are preserved" in warning for warning in exporter.warnings)
        assert any("Unknown node extensions are preserved" in warning for warning in exporter.warnings)
        assert any("unknown mesh extensions are preserved" in warning for warning in exporter.warnings)
        assert any("unknown scene extensions are preserved" in warning for warning in exporter.warnings)
        assert any("unknown primitive extensions are preserved" in warning for warning in exporter.warnings)
        assert any("OPTIONAL_EXTENSIONS_UNSUPPORTED" in warning and "EXAMPLE_unknown_material" in warning
                   for warning in exporter.warnings)
        check_export(encoded)
        unknown_surface_doc = copy.deepcopy(doc)
        unknown_surface_doc["physicalMaterials"][0]["type"] = "org.example.physical.soft_wood.v1"
        unknown_surface_doc["physicalMaterials"][0]["subtype"] = "org.example.physical.soft_wood_oak.v1"
        unknown_surface_path = os.path.join(folder, "unknown_surface_type.adm")
        with open(unknown_surface_path, "wb") as stream:
            stream.write(write_container(K.ADM_MAGIC, unknown_surface_doc, chunks))
        unknown_surface_importer = ModelImporter(bpy.context, unknown_surface_path, ImportOptions())
        unknown_surface_importer.run()
        unknown_surface = unknown_surface_importer.root.adm.physical_materials[0]
        assert unknown_surface.surface_type == "org.example.physical.soft_wood.v1"
        unknown_surface_data, unknown_surface_report = ModelExporter(
            bpy.context, unknown_surface_importer.root, ExportOptions()).export()
        assert unknown_surface_report.ok, unknown_surface_report.errors
        unknown_surface_exported, _ = read_container(unknown_surface_data, K.ADM_MAGIC)
        assert unknown_surface_exported["physicalMaterials"][0]["type"] == (
            "org.example.physical.soft_wood.v1")
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
        assert selected_doc["extensions"]["EXAMPLE_unknown_root"] == unknown_root
        assert next(n for n in selected_doc["nodes"] if "mesh" in n)["extensions"]["EXAMPLE_unknown_node"] == unknown_node
        assert selected_doc["meshes"][0]["extensions"]["EXAMPLE_unknown_mesh"] == unknown_mesh
        assert selected_doc["scenes"][selected_doc["scene"]]["extensions"]["EXAMPLE_unknown_scene"] == unknown_scene
        saved_scene_extensions = imported_root[UNKNOWN_SCENE_EXTENSIONS_PROPERTY]
        imported_root[UNKNOWN_SCENE_EXTENSIONS_PROPERTY] = "{broken"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown scene extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown scene extension metadata was accepted")
        imported_root[UNKNOWN_SCENE_EXTENSIONS_PROPERTY] = saved_scene_extensions
        saved_mesh_extensions = imported_mesh.data[UNKNOWN_MESH_EXTENSIONS_PROPERTY]
        imported_mesh.data[UNKNOWN_MESH_EXTENSIONS_PROPERTY] = "{broken"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown mesh extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown mesh extension metadata was accepted")
        imported_mesh.data[UNKNOWN_MESH_EXTENSIONS_PROPERTY] = saved_mesh_extensions
        assert selected_doc["meshes"][0]["primitives"][0]["extensions"]["EXAMPLE_unknown_primitive"] == unknown_primitive
        saved_primitive_extensions = imported_mesh.data[UNKNOWN_PRIMITIVE_EXTENSIONS_PROPERTY]
        imported_mesh.data[UNKNOWN_PRIMITIVE_EXTENSIONS_PROPERTY] = "{broken"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown primitive extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown primitive extension metadata was accepted")
        imported_mesh.data[UNKNOWN_PRIMITIVE_EXTENSIONS_PROPERTY] = saved_primitive_extensions
        primitive_attr = imported_mesh.data.attributes[UNKNOWN_PRIMITIVE_ATTRIBUTE]
        primitive_attr.data[0].value = 999
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "invalid unknown primitive extension face ID" in str(exc)
        else:
            raise AssertionError("Invalid primitive face ID was accepted")
        primitive_attr.data[0].value = 1
        primitive_attr.name = "renamed_primitive_attribute"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown primitive extensions without" in str(exc)
        else:
            raise AssertionError("Missing primitive face attribute was accepted")
        primitive_attr.name = UNKNOWN_PRIMITIVE_ATTRIBUTE
        for value in primitive_attr.data:
            value.value = 0
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "a primitive with unknown extensions has no exported faces" in str(exc)
        else:
            raise AssertionError("Removing an unknown primitive was accepted")
        for value in primitive_attr.data:
            value.value = 1
        imported_mesh.data.materials.append(bpy.data.materials.new("Split material"))
        imported_mesh.data.polygons[0].material_index = 1
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "unknown primitive extension would be split" in str(exc)
        else:
            raise AssertionError("Splitting an unknown primitive extension was accepted")
        imported_mesh.data.polygons[0].material_index = 0
        imported_mesh.data.materials.pop(index=1)
        saved_node_extensions = imported_mesh[UNKNOWN_NODE_EXTENSIONS_PROPERTY]
        imported_mesh[UNKNOWN_NODE_EXTENSIONS_PROPERTY] = "{broken"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown node extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown node extension metadata was accepted")
        imported_mesh[UNKNOWN_NODE_EXTENSIONS_PROPERTY] = saved_node_extensions
        saved_root_extensions = imported_root[UNKNOWN_ROOT_EXTENSIONS_PROPERTY]
        imported_root[UNKNOWN_ROOT_EXTENSIONS_PROPERTY] = "{broken"
        try:
            ModelExporter(bpy.context, imported_root, ExportOptions()).export()
        except ExportError as exc:
            assert "cannot preserve unknown root extensions" in str(exc)
        else:
            raise AssertionError("Invalid unknown root extension metadata was accepted")
        imported_root[UNKNOWN_ROOT_EXTENSIONS_PROPERTY] = saved_root_extensions
        other_root = bpy.data.objects.new("Conflicting root", None)
        bpy.context.scene.collection.objects.link(other_root)
        other_root.select_set(True)
        try:
            ModelExporter(bpy.context, None, ExportOptions(selected_only=True)).export()
        except ExportError as exc:
            assert "cannot merge selected objects from different scenes" in str(exc)
        else:
            raise AssertionError("Merging unknown scene extensions was accepted")
        del imported_root[UNKNOWN_SCENE_EXTENSIONS_PROPERTY]
        other_root[UNKNOWN_ROOT_EXTENSIONS_PROPERTY] = '{"EXAMPLE_unknown_root":{"opaque":false}}'
        try:
            ModelExporter(bpy.context, None, ExportOptions(selected_only=True)).export()
        except ExportError as exc:
            assert "conflicting unknown root extension" in str(exc)
        else:
            raise AssertionError("Conflicting unknown root extensions were accepted")
        imported_root[UNKNOWN_SCENE_EXTENSIONS_PROPERTY] = saved_scene_extensions
        bpy.data.objects.remove(other_root, do_unlink=True)
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
        print("PHASE import and export required terrain Control Map", flush=True)
        control_doc = copy.deepcopy(doc)
        control_material = control_doc["materials"][0]
        control_material["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] = [
            "surface.0", "surface.1", "surface.2", "surface.3",
        ]
        control_material["extensions"][K.TERRAIN_CONTROL_MAP_EXT] = {
            "version": "1.0.0", "mode": "TEXTURE_RGBA",
            "texture": {"index": ref["index"], "texCoord": 1}, "mapping": "UV",
        }
        control_material["shader"] = {
            "id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_TERRAIN_4[1],
        }
        control_material["emissiveFactor"] = [0.0, 0.0, 0.0]
        control_material["alphaMode"] = "OPAQUE"
        control_doc["textures"][ref["index"]].pop("sampler", None)
        control_doc["extensionsRequired"].remove(K.MATERIAL_HEIGHT_EXT)
        control_doc.setdefault("extensionsUsed", []).append(K.TERRAIN_CONTROL_MAP_EXT)
        control_doc.setdefault("extensionsRequired", []).append(K.TERRAIN_CONTROL_MAP_EXT)
        control_fixture = write_container(K.ADM_MAGIC, control_doc, chunks)
        control_report = validate_adm(control_fixture)
        assert control_report.ok, control_report.format()
        control_path = os.path.join(folder, "required_control_map.adm")
        with open(control_path, "wb") as stream:
            stream.write(control_fixture)
        control_importer = ModelImporter(bpy.context, control_path, ImportOptions())
        control_root = control_importer.run()
        control_blender_material = next(
            material for material in bpy.data.materials
            if material.get(M.MATERIAL_CONTROL_MAP_DATA)
        )
        assert control_blender_material.adm.control_map_enabled
        assert control_blender_material.adm.control_map_mode == "TEXTURE_RGBA"
        assert control_blender_material.adm.control_map_image is not None
        assert control_blender_material.adm.control_map_preview_image is not None
        assert control_blender_material.adm.control_map_preview_image.colorspace_settings.name == "Non-Color"
        control_exporter = ModelExporter(bpy.context, control_root, ExportOptions())
        control_encoded, control_export_report = control_exporter.export()
        assert control_export_report.ok, control_export_report.errors
        control_exported, _ = read_container(control_encoded, K.ADM_MAGIC)
        exported_control = control_exported["materials"][0]["extensions"][K.TERRAIN_CONTROL_MAP_EXT]
        assert K.TERRAIN_CONTROL_MAP_EXT in control_exported["extensionsRequired"]
        assert exported_control["mode"] == "TEXTURE_RGBA"
        assert exported_control["texture"]["texCoord"] == 1
        assert exported_control["texture"]["index"] < len(control_exported["textures"])
        assert control_exported["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] == \
            control_doc["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"]
        control_preview_nodes = [
            node for node in control_blender_material.node_tree.nodes
            if node.name.startswith("ADM Preview")
        ]
        assert any(node.bl_idname == "ShaderNodeTexImage" and node.image ==
                   control_blender_material.adm.control_map_preview_image for node in control_preview_nodes)
        control_blender_material.adm.control_map_surface_0 = "surface.blender-roundtrip-layer0"
        control_blender_material.adm.control_map_mode = "VERTEX_MODULATE"
        control_blender_material.adm.control_map_strength = 0.5
        edited_control_exporter = ModelExporter(bpy.context, control_root, ExportOptions())
        edited_control_encoded, edited_control_report = edited_control_exporter.export()
        assert edited_control_report.ok, edited_control_report.errors
        edited_control, _ = read_container(edited_control_encoded, K.ADM_MAGIC)
        edited_control_ext = edited_control["materials"][0]["extensions"][K.TERRAIN_CONTROL_MAP_EXT]
        assert edited_control_ext["mode"] == "VERTEX_MODULATE"
        assert edited_control_ext["strength"] == 0.5
        edited_surface_ids = edited_control["materials"][0]["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"]
        assert edited_surface_ids[0] == "surface.blender-roundtrip-layer0"
        control_blend_path = os.path.join(folder, "control_map.blend")
        control_root_name = control_root.name
        control_material_name = control_blender_material.name
        bpy.ops.wm.save_as_mainfile(filepath=control_blend_path)
        bpy.ops.wm.open_mainfile(filepath=control_blend_path)
        control_root = bpy.data.objects[control_root_name]
        control_blender_material = bpy.data.materials[control_material_name]
        assert control_blender_material.adm.control_map_mode == "VERTEX_MODULATE"
        assert control_blender_material.adm.control_map_strength == 0.5
        assert control_blender_material.adm.control_map_image is not None
        assert control_blender_material.adm.control_map_preview_image is not None
        assert control_blender_material.adm.control_map_preview_image.colorspace_settings.name == "Non-Color"
        reloaded_control_exporter = ModelExporter(bpy.context, control_root, ExportOptions())
        reloaded_control_encoded, reloaded_control_report = reloaded_control_exporter.export()
        assert reloaded_control_report.ok, reloaded_control_report.errors
        reloaded_control, _ = read_container(reloaded_control_encoded, K.ADM_MAGIC)
        reloaded_control_ext = reloaded_control["materials"][0]["extensions"][K.TERRAIN_CONTROL_MAP_EXT]
        assert reloaded_control_ext["mode"] == "VERTEX_MODULATE"
        assert reloaded_control_ext["strength"] == 0.5
        assert control_doc["materials"][0]["extensions"][K.TERRAIN_CONTROL_MAP_EXT]["texture"]["index"] == \
            ref["index"]

        print("PHASE reject required terrain Macro Color", flush=True)
        macro_doc = copy.deepcopy(control_doc)
        macro_material = macro_doc["materials"][0]
        macro_material["extensions"].pop(K.TERRAIN_CONTROL_MAP_EXT)
        macro_image_index = len(macro_doc["images"])
        macro_doc["images"].append({
            "uri": "textures/macro.png", "mimeType": "image/png",
        })
        macro_texture_index = len(macro_doc["textures"])
        macro_doc["textures"].append({"source": macro_image_index})
        macro_material["extensions"][K.TERRAIN_MACRO_COLOR_EXT] = {
            "version": "1.0.0", "texture": {"index": macro_texture_index, "texCoord": 0},
            "projection": "LOCAL_UV", "blendMode": "MULTIPLY",
        }
        macro_doc["extensionsUsed"].remove(K.TERRAIN_CONTROL_MAP_EXT)
        macro_doc["extensionsUsed"].append(K.TERRAIN_MACRO_COLOR_EXT)
        macro_doc["extensionsUsed"].append(K.EXTERNAL_IMAGES_EXT)
        macro_doc["extensionsRequired"].remove(K.TERRAIN_CONTROL_MAP_EXT)
        macro_doc["extensionsRequired"].append(K.TERRAIN_MACRO_COLOR_EXT)
        macro_doc["extensionsRequired"].append(K.EXTERNAL_IMAGES_EXT)
        macro_fixture = write_container(K.ADM_MAGIC, macro_doc, chunks)
        macro_report = validate_adm(macro_fixture)
        assert macro_report.ok, macro_report.format()
        os.makedirs(os.path.join(folder, "textures"), exist_ok=True)
        with open(os.path.join(folder, "textures", "macro.png"), "wb") as stream:
            stream.write(encode_png(1, 1, bytes((255, 0, 0, 255))))
        macro_path = os.path.join(folder, "required_macro_color.adm")
        with open(macro_path, "wb") as stream:
            stream.write(macro_fixture)
        before = (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))
        try:
            ModelImporter(bpy.context, macro_path, ImportOptions()).run()
        except ImportError_ as exc:
            assert K.TERRAIN_MACRO_COLOR_EXT in str(exc) and "required" in str(exc)
        else:
            raise AssertionError("Required unsupported terrain Macro Color was accepted")
        assert before == (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))

        print("PHASE reject required terrain Macro Normal", flush=True)
        normal_doc = copy.deepcopy(macro_doc)
        normal_material = normal_doc["materials"][0]
        normal_material["extensions"].pop(K.TERRAIN_MACRO_COLOR_EXT)
        normal_material["extensions"][K.TERRAIN_MACRO_NORMAL_EXT] = {
            "version": "1.0.0", "texture": {"index": macro_texture_index, "texCoord": 0},
            "projection": "LOCAL_UV",
        }
        normal_doc["extensionsUsed"].remove(K.TERRAIN_MACRO_COLOR_EXT)
        normal_doc["extensionsUsed"].append(K.TERRAIN_MACRO_NORMAL_EXT)
        normal_doc["extensionsRequired"].remove(K.TERRAIN_MACRO_COLOR_EXT)
        normal_doc["extensionsRequired"].append(K.TERRAIN_MACRO_NORMAL_EXT)
        normal_fixture = write_container(K.ADM_MAGIC, normal_doc, chunks)
        normal_report = validate_adm(normal_fixture)
        assert normal_report.ok, normal_report.format()
        normal_path = os.path.join(folder, "required_macro_normal.adm")
        with open(normal_path, "wb") as stream:
            stream.write(normal_fixture)
        before = (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))
        try:
            ModelImporter(bpy.context, normal_path, ImportOptions()).run()
        except ImportError_ as exc:
            assert K.TERRAIN_MACRO_NORMAL_EXT in str(exc) and "required" in str(exc)
        else:
            raise AssertionError("Required unsupported terrain Macro Normal was accepted")
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
