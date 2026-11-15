"""Blender headless test for official shader identity and typed-data round trips."""
import os
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FAILS = []


def check(condition, message):
    print(("  ok  " if condition else "  FAIL ") + message)
    if not condition:
        FAILS.append(message)


def main(tmp):
    adm_blender.register()
    from adm_blender.core import constants as K
    from adm_blender.blender import materials as M
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = bpy.context.active_object
    cube.data.uv_layers.new(name="Detail")
    mat = bpy.data.materials.new("Core20")
    cube.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    check(bpy.ops.adm.create_model_root(name="ShaderRoot") == {"FINISHED"}, "create model root")
    root = bpy.data.objects["ShaderRoot"]

    for key, kind in K.OFFICIAL_SHADER_KINDS.items():
        mat.adm.shader = kind
        mat.adm.shader_version = key[1]
        scalar_maps = []
        if key[1] == K.SHADER_PROFILE_V2:
            scalar_maps = [
                p["name"] for p in K.OFFICIAL_SHADERS[key]
                if p["name"].endswith(("_metallic_texture", "_roughness_texture"))
                and (p["name"].startswith("color1_") or kind == "LAYERED")
            ]
            for index, name in enumerate(scalar_maps):
                img = bpy.data.images.new(f"{kind}_{name}", 2, 2, alpha=True)
                img.pixels = [0.2, 0.4, 0.7, 0.6] * 4
                img.pack()
                mat.adm.params[name].image = img
                mat.adm.params[name].tex_coord = index % 2
                prefix = name[:-len("_texture")]
                mat.adm.params[prefix + "_channel"].texture_channel = ("R", "G", "B", "A")[index % 4]
                mat.adm.params[prefix + "_invert"].texture_invert = index % 2 == 1
        if kind in ("TERRAIN_4", "TWO_LAYER"):
            if kind == "TWO_LAYER":
                mask = bpy.data.images.new("two_layer_mask", 2, 2, alpha=True)
                mask.pixels = [0.35, 0.1, 0.8, 1.0] * 4
                mask.pack()
                mat.adm.params["blend_mask"].image = mask
                mat.adm.params["blend_mask"].tex_coord = 1
            for i in range(2 if kind == "TWO_LAYER" else 4):
                for prop in ("metallic", "roughness"):
                    name = f"layer{i}_{prop}_texture"
                    img = bpy.data.images.new(f"{key[1]}_{name}", 2, 2, alpha=True)
                    img.pixels = [0.2 + i * 0.1, 0.7, 0.9, 0.65] * 4
                    img.pack()
                    mat.adm.params[name].image = img
                    mat.adm.params[name].tex_coord = i % 2
                    mat.adm.params[f"layer{i}_{prop}_channel"].texture_channel = (
                        ("R", "G", "B", "A")[(i + (prop == "roughness")) % 4])
                    mat.adm.params[f"layer{i}_{prop}_invert"].value_bool = (i % 2 == 1)
        if kind == "INTERACTIVE":
            bpy.context.view_layer.objects.active = cube
            cube.select_set(True)
            for poly in cube.data.polygons:
                poly.select = True
            cube.adm.interactive_surface_id = "test_screen"
            check(bpy.ops.adm.interactive_surface_assign_faces() == {"FINISHED"},
                  "INTERACTIVE: assign screen faces")
        if kind == "EMISSIVE":
            bsdf = M.principled_of(mat)
            bsdf.inputs["Emission Color"].default_value = (0.25, 0.5, 0.75, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 2.0
        bpy.context.view_layer.update()
        exporter = ModelExporter(bpy.context, root, ExportOptions())
        data, report = exporter.export()
        check(report.ok, f"{kind}: export validates")
        if not report.ok:
            continue
        material = report.doc["materials"][0]
        for index, name in enumerate(scalar_maps):
            prefix = name[:-len("_texture")]
            values = material["shaderParameters"]
            check(values[name].get("texCoord", 0) == index % 2
                  and values[prefix + "_channel"] == index % 4
                  and values[prefix + "_invert"] == (index % 2 == 1),
                  f"{kind}@2.0.0: export {name} UV, channel and inversion")
        if kind in ("TERRAIN_4", "TWO_LAYER"):
            for i in range(2 if kind == "TWO_LAYER" else 4):
                for prop in ("metallic", "roughness"):
                    name = f"layer{i}_{prop}_texture"
                    check(material["shaderParameters"][name].get("texCoord", 0) == i % 2,
                          f"TERRAIN_4@{key[1]}: export {name} UV")
                    channel = f"layer{i}_{prop}_channel"
                    invert = f"layer{i}_{prop}_invert"
                    check(material["shaderParameters"][channel] == (i + (prop == "roughness")) % 4
                          and material["shaderParameters"][invert] == (i % 2 == 1),
                          f"TERRAIN_4@{key[1]}: export {prop} channel and inversion for layer {i}")
        check(material.get("shader", {"id": K.SHADER_CORE[0], "version": K.SHADER_CORE[1]}) ==
              {"id": key[0], "version": key[1]}, f"{kind}: exact shader ID/version")
        if kind != "CORE":
            check(all(field in material for field in K.PBR_FALLBACK_FIELDS), f"{kind}: explicit PBR fallback")
        path = os.path.join(tmp, f"{kind.lower()}.adm")
        with open(path, "wb") as stream:
            stream.write(data)
        ModelImporter(bpy.context, path, ImportOptions()).run()
        imported = next((candidate for candidate in bpy.data.materials
                         if candidate != mat and candidate.adm.shader_key() == key), None)
        check(imported is not None, f"{kind}: import restores profile")
        if imported is not None and key == K.SHADER_LAYERED:
            check(abs(imported.adm.layer_factor) < 1e-6, "LAYERED: layer factor restored")
        elif imported is not None and key in K.OFFICIAL_SHADERS:
            expected_params = {p["name"] for p in K.OFFICIAL_SHADERS[key]}
            actual_params = {p.name for p in imported.adm.params}
            check(actual_params == expected_params, f"{kind}: typed parameter schema restored")
            for index, name in enumerate(scalar_maps):
                value = imported.adm.params[name]
                prefix = name[:-len("_texture")]
                check(value.use and value.image is not None and value.tex_coord == index % 2
                      and value.image.colorspace_settings.name == "Non-Color"
                      and abs(value.image.pixels[0] - 0.2) < 0.02
                      and abs(value.image.pixels[3] - 0.6) < 0.02
                      and imported.adm.params[prefix + "_channel"].texture_channel
                      == ("R", "G", "B", "A")[index % 4]
                      and imported.adm.params[prefix + "_invert"].texture_invert == (index % 2 == 1),
                      f"{kind}@2.0.0: import {name} linear data and settings")
            if kind in ("TERRAIN_4", "TWO_LAYER"):
                if kind == "TWO_LAYER":
                    mask = imported.adm.params["blend_mask"]
                    check(mask.use and mask.tex_coord == 1 and mask.image is not None
                          and mask.image.colorspace_settings.name == "Non-Color"
                          and abs(mask.image.pixels[0] - 0.35) < 0.02,
                          "TWO_LAYER: mask and UV survive export and import")
                for i in range(2 if kind == "TWO_LAYER" else 4):
                    for prop in ("metallic", "roughness"):
                        name = f"layer{i}_{prop}_texture"
                        value = imported.adm.params[name]
                        check(value.use and value.image is not None and value.tex_coord == i % 2
                              and value.image.colorspace_settings.name == "Non-Color",
                              f"TERRAIN_4@{key[1]}: import {name} image and UV")
                        if value.image is not None:
                            source = mat.adm.params[name].image
                            check(abs(value.image.pixels[0] - source.pixels[0]) <= 1 / 255,
                                  f"TERRAIN_4@{key[1]}: import {name} linear red value")
                            check(abs(value.image.pixels[3] - source.pixels[3]) <= 1 / 255,
                                  f"TERRAIN_4@{key[1]}: import {name} alpha value")
                        channel = f"layer{i}_{prop}_channel"
                        invert = f"layer{i}_{prop}_invert"
                        check(imported.adm.params[channel].texture_channel
                              == ("R", "G", "B", "A")[(i + (prop == "roughness")) % 4]
                              and imported.adm.params[invert].value_bool == (i % 2 == 1),
                              f"TERRAIN_4@{key[1]}: import {prop} channel and inversion for layer {i}")
        if key[1] == K.SHADER_PROFILE_V2 or kind not in (
                "CORE", "LAYERED", "CUTOUT", "EMISSIVE", "DECAL"):
            check(not any("portable PBR fallback" in warning for warning in exporter.warnings),
                  f"{kind}: has a profile preview, no fallback warning")
            if imported is not None and (key[1] == K.SHADER_PROFILE_V2 or kind != "INTERACTIVE"):
                out = next((n for n in imported.node_tree.nodes
                            if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
                check(out is not None and M.is_preview_node(out), f"{kind}: imported material shows profile preview")

    mat.adm.shader = "CORE"
    mat.adm.shader_version = K.SHADER_PROFILE_V2
    color1 = cube.data.color_attributes.get("COLOR_1")
    if color1 is None:
        color1 = cube.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    color1.data.foreach_set("color", [0.25, 0.5, 0.75, 1.0] * len(color1.data))
    try:
        ModelExporter(bpy.context, root, ExportOptions(vertex_controls=False)).export()
        check(False, "v2 COLOR_1 export rejects disabled ADM Vertex Controls")
    except ExportError as exc:
        check("COLOR_1 masks" in str(exc) and "export option" in str(exc),
              "v2 COLOR_1 export reports the required ADM Vertex Controls option")
    data, report = ModelExporter(
        bpy.context, root, ExportOptions(vertex_controls=True)
    ).export()
    check(report.ok, "v2 COLOR_1 export validates with ADM Vertex Controls enabled")
    check("ADM_vertex_control_v1" in report.doc.get("extensionsRequired", []),
          "v2 COLOR_1 export requires the vertex-control extension")
    attrs = report.doc["meshes"][0]["primitives"][0]["attributes"]
    check("COLOR_1" in attrs, "v2 COLOR_1 export includes the authored mask attribute")

    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_shaders_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
