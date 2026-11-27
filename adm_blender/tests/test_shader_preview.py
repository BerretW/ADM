"""Blender headless test for ADM profile viewport previews (adm_blender/blender/shader_preview.py).

Builds every profile preview with all parameters overridden, checks the exported PBR fallback is
unaffected, and bakes Brick / Terrain with Cycles to verify the node math against the contracts.
"""
import json
import math
import os
import sys
import tempfile
import traceback

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FAILS = []
RES = 16
with open(os.path.join(REPO, "adm-standard", "fixtures", "expectations",
                       "terrain_control_map_filtering_v1.json"), encoding="utf-8") as handle:
    CONTROL_MAP_FILTERING = json.load(handle)


def check(condition, message):
    print(("  ok  " if condition else "  FAIL ") + message)
    if not condition:
        FAILS.append(message)


def close(a, b, tol=0.01):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def image(name, rgba_fn, non_color=True):
    img = bpy.data.images.new(name, RES, RES, alpha=True, float_buffer=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    px = np.zeros((RES, RES, 4), np.float32)
    for y in range(RES):
        for x in range(RES):
            px[y, x] = rgba_fn(x, y)
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.pack()
    return img


def bake(obj, mat, kind):
    target = bpy.data.images.new(f"bake_{kind}", RES, RES, float_buffer=True)
    target.colorspace_settings.name = "Non-Color"
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = target
    mat.node_tree.nodes.active = node
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    kw = {"pass_filter": {"COLOR"}} if kind == "DIFFUSE" else {}
    bpy.ops.object.bake(type=kind, margin=0, **kw)
    px = np.array(target.pixels[:], dtype=np.float32).reshape(RES, RES, 4)
    mat.node_tree.nodes.remove(node)
    bpy.data.images.remove(target)
    return px


def bake_socket(obj, mat, socket):
    target = bpy.data.images.new("bake_socket", RES, RES, float_buffer=True)
    target.colorspace_settings.name = "Non-Color"
    nodes = mat.node_tree.nodes
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    surface = out.inputs["Surface"]
    original = [link.from_socket for link in surface.links]
    for link in list(surface.links):
        mat.node_tree.links.remove(link)
    emission = nodes.new("ShaderNodeEmission")
    mat.node_tree.links.new(socket, emission.inputs["Color"])
    mat.node_tree.links.new(emission.outputs["Emission"], surface)
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.image = target
    nodes.active = image_node
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="EMIT", margin=0)
    px = np.array(target.pixels[:], dtype=np.float32).reshape(RES, RES, 4)
    for link in list(surface.links):
        mat.node_tree.links.remove(link)
    for source in original:
        mat.node_tree.links.new(source, surface)
    nodes.remove(emission)
    nodes.remove(image_node)
    bpy.data.images.remove(target)
    return px


def set_param(mat, name, value):
    v = mat.adm.params[name]
    if isinstance(value, bpy.types.Image):
        v.image = value
    elif isinstance(value, str):
        v.value_enum = value
    elif isinstance(value, (tuple, list)):
        cur = list(v.value_vec)
        cur[:len(value)] = value
        v.value_vec = cur
    else:
        v.value_f = value


def set_color1(obj, color):
    attr = obj.data.color_attributes.get("COLOR_1")
    if attr is None:
        attr = obj.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    attr.data.foreach_set("color", np.tile(color, len(attr.data)).ravel())
    return attr


def preview_bsdf(mat, materials):
    output = next(n for n in mat.node_tree.nodes
                  if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    surface = materials._from(output.inputs["Surface"])
    if surface is not None and surface.node.type == "BSDF_PRINCIPLED":
        return surface.node
    return next((node for node in mat.node_tree.nodes
                 if node.name == f"{materials.PREVIEW_PREFIX} BSDF"), None)


def main():
    adm_blender.register()
    from adm_blender.core import constants as K
    from adm_blender.core.material_math import (
        height_blend_weights, terrain_macro_color, terrain_macro_normal,
        terrain_macro_normal_frame,
    )
    from adm_blender.blender import materials as M
    from adm_blender.blender import shader_preview as SP
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, import_model
    from adm_blender.core.container import read_container

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    plane = bpy.context.active_object
    check(bpy.ops.adm.create_model_root(name="PreviewRoot") == {"FINISHED"}, "create model root")
    root = bpy.data.objects["PreviewRoot"]
    tex = image("any_tex", lambda x, y: (0.5, 0.5, 1.0, 1.0))
    plane[SP.PREVIEW_WEAR_AMOUNT] = 0.6

    # Texture edits must affect the active preview, not just the portable fallback.
    mat = bpy.data.materials.new("texture_refresh")
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.vertex_controls_enabled = True
    red = image("preview_red", lambda x, y: (1.0, 0.0, 0.0, 1.0), non_color=False)
    green = image("preview_green", lambda x, y: (0.0, 1.0, 0.0, 1.0), non_color=False)
    for img, expected in ((red, (1.0, 0.0, 0.0)), (green, (0.0, 1.0, 0.0))):
        mat.adm.pick_base_color = img
        bsdf = preview_bsdf(mat, M)
        pixel = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
        check(close(pixel, expected), f"PBR: assigned texture appears in preview ({pixel})")
    mat.adm.shader = "TERRAIN_4"
    bpy.context.view_layer.objects.active = plane
    plane.select_set(True)
    check(bpy.ops.adm.material_terrain_from_pbr() == {"FINISHED"},
          "TERRAIN_4: copy PBR base texture to layer 0")
    bsdf = preview_bsdf(mat, M)
    pixel = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: copied texture appears in preview ({pixel})")
    uv1 = plane.data.uv_layers.new(name="Detail")
    for uv in uv1.data:
        uv.uv = (0.75, 0.5)
    split = image("preview_uv1", lambda x, y: (1.0, 0.0, 0.0, 1.0) if x < RES // 2
                  else (0.0, 1.0, 0.0, 1.0), non_color=False)
    mat.adm.pick_base_color = split
    M.set_slot_uv(mat, "BASE_COLOR", 1, [uv.name for uv in plane.data.uv_layers])
    check(bpy.ops.adm.material_terrain_from_pbr() == {"FINISHED"},
          "TERRAIN_4: copy a UV1 PBR texture")
    bsdf = preview_bsdf(mat, M)
    pixel = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: copied texture uses named UV1 ({pixel})")

    # Control Map weights replace COLOR_1 before layer color composition.
    control_mat = bpy.data.materials.new("terrain_control_map")
    plane.data.materials.clear()
    plane.data.materials.append(control_mat)
    control_mat.adm.shader = "TERRAIN_4"
    control_mat.adm.shader_version = "2.1.0"
    set_param(control_mat, "layer0_base_color", (1.0, 0.0, 0.0, 1.0))
    set_param(control_mat, "layer1_base_color", (0.0, 1.0, 0.0, 1.0))
    set_param(control_mat, "layer2_base_color", (0.0, 0.0, 1.0, 1.0))
    set_param(control_mat, "layer3_base_color", (1.0, 1.0, 0.0, 1.0))
    for channel in ("r", "g", "b", "a"):
        set_param(control_mat, f"color1_{channel}_strength", 1.0)
    control_mat.adm.control_map_enabled = True
    surface_ids = [
        getattr(control_mat.adm, f"control_map_surface_{index}") for index in range(4)
    ]
    check(all(surface_ids) and len(set(surface_ids)) == 4,
          "TERRAIN_4: enabling Control Map creates four stable layer identities")
    control_maps = {
        "green": image("control_map_green", lambda x, y: (0.0, 1.0, 0.0, 0.0)),
        "implicit_blue": image("control_map_implicit_blue", lambda x, y: (0.0, 0.0, 1.0, 0.0)),
    }
    control_cases = (
        ("TEXTURE_RGBA", (1.0, 0.0, 0.0, 0.0), "green", (0.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
        ("TEXTURE_RGB_IMPLICIT", (1.0, 0.0, 0.0, 0.0), "implicit_blue",
         (1.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
        ("VERTEX_MULTIPLY", (0.5, 0.5, 0.0, 0.0), "green",
         (0.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
        ("VERTEX_OVERRIDE", (1.0, 0.0, 0.0, 0.0), "green",
         (0.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
        ("VERTEX_MODULATE", (0.5, 0.5, 0.0, 0.0), "green",
         (0.0, 1.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
        ("VERTEX_ONLY", (1.0, 0.0, 0.0, 0.0), "green",
         (1.0, 0.0, 0.0), (1.0, 1.0, 1.0, 1.0)),
    )
    for mode, weights, image_name, expected, override_mask in control_cases:
        set_color1(plane, weights)
        plane.data.update()
        bpy.context.view_layer.update()
        control_mat.adm.control_map_mode = mode
        control_mat.adm.control_map_override_mask = override_mask
        control_mat.adm.control_map_image = control_maps[image_name]
        M.refresh_shader_preview(control_mat)
        bsdf = preview_bsdf(control_mat, M)
        pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
        check(close(pixel, expected), f"TERRAIN_4: {mode} Control Map pixel ({pixel})")
    set_color1(plane, (1.0, 0.0, 0.0, 0.0))
    plane.data.update()
    control_mat.adm.control_map_mode = "TEXTURE_RGBA"
    control_mat.adm.control_map_mapping = "UV"
    control_mat.adm.control_map_scale = (1.0, 1.0)
    control_mat.adm.control_map_offset = (0.0, 0.0)
    control_mat.adm.control_map_image = image(
        "control_map_uv_split",
        lambda x, y: (1.0, 0.0, 0.0, 0.0) if x < RES * 0.6 else (0.0, 1.0, 0.0, 0.0))
    control_mat.adm.control_map_tex_coord = 1
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: Control Map samples UV1 ({pixel})")
    control_mat.adm.control_map_tex_coord = 0
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (1.0, 0.0, 0.0)), f"TERRAIN_4: Control Map samples UV0 ({pixel})")
    control_mat.adm.control_map_offset = (0.3, 0.0)
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: Control Map UV offset affects sampling ({pixel})")
    control_mat.adm.control_map_mapping = "WORLD_PLANAR_XZ"
    control_mat.adm.control_map_origin = (-0.75, 0.0)
    control_mat.adm.control_map_offset = (0.0, 0.0)
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: world-planar XZ and origin affect sampling ({pixel})")
    control_mat.adm.control_map_origin = (-0.25, 0.0)
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (1.0, 0.0, 0.0)), f"TERRAIN_4: world-planar uses object world position ({pixel})")
    plane.location.x = 0.5
    bpy.context.view_layer.update()
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: translated object changes world-planar sample ({pixel})")
    plane.location.x = 100.5
    control_mat.adm.control_map_origin = (99.75, 0.0)
    bpy.context.view_layer.update()
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    pixel = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(pixel, (0.0, 1.0, 0.0)), f"TERRAIN_4: world-planar remains stable after floating-origin shift ({pixel})")
    plane.location.x = 0.0
    control_mat.adm.control_map_mode = "TEXTURE_RGBA"
    control_mat.adm.control_map_mapping = "UV"
    control_mat.adm.control_map_scale = CONTROL_MAP_FILTERING["uvScale"]
    control_mat.adm.control_map_offset = (0.0, 0.0)
    filtering_width = CONTROL_MAP_FILTERING["width"]
    filtering_height = CONTROL_MAP_FILTERING["height"]
    checker_y, checker_x = np.indices((filtering_height, filtering_width))
    red = ((checker_x + checker_y) % 2).astype(np.float32)
    filtering_pixels = np.zeros((filtering_height, filtering_width, 4), dtype=np.float32)
    filtering_pixels[..., 0] = red
    filtering_pixels[..., 1] = 1.0 - red
    filtering_image = bpy.data.images.new(
        "control_map_minified_checker", filtering_width, filtering_height,
        alpha=True, float_buffer=True)
    filtering_image.colorspace_settings.name = "Non-Color"
    filtering_image.pixels.foreach_set(filtering_pixels.ravel())
    filtering_image.update()
    filtering_image.pack()
    control_mat.adm.control_map_image = filtering_image
    M.refresh_shader_preview(control_mat)
    bsdf = preview_bsdf(control_mat, M)
    minified = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(minified, CONTROL_MAP_FILTERING["expectedLinearAverage"][:3],
                tol=CONTROL_MAP_FILTERING["tolerance"]),
          f"TERRAIN_4: minified linear Control Map resolves to averaged weights ({minified})")

    control_mat.adm.control_map_mapping = "WORLD_PLANAR_XZ"
    control_mat.adm.control_map_origin = (0.0, 0.0)
    control_mat.adm.control_map_scale = (0.1, 1.0)
    control_mat.adm.control_map_image = image(
        "control_map_shared_edge_gradient",
        lambda x, y: (x / (RES - 1), 1.0 - x / (RES - 1), 0.0, 0.0),
    )
    M.refresh_shader_preview(control_mat)
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(2.0, 0.0, 0.0))
    seam_plane = bpy.context.object
    seam_plane.data.materials.append(control_mat)
    bpy.context.view_layer.update()
    bsdf = preview_bsdf(control_mat, M)
    left_edge = bake_socket(plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, RES - 1, :3]
    right_edge = bake_socket(seam_plane, control_mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 0, :3]
    check(float(np.max(np.abs(left_edge - right_edge))) < 0.08,
          f"TERRAIN_4: shared world-XZ Control Map stays continuous across adjacent tiles "
          f"({left_edge}, {right_edge})")
    bpy.data.objects.remove(seam_plane, do_unlink=True)

    control_mat.adm.control_map_mapping = "WORLD_PLANAR_XZ"
    control_mat.adm.control_map_scale = (1.0, 1.0)
    control_mat.adm.control_map_origin = (-0.75, 0.0)
    bpy.context.view_layer.update()
    M.refresh_shader_preview(control_mat)
    control_encoded, control_report = ModelExporter(
        bpy.context, root, ExportOptions(vertex_controls=True)).export()
    check(control_report.ok, f"TERRAIN_4: authoring-generated Control Map validates ({control_report.errors})")
    if control_report.ok:
        control_doc, _ = read_container(control_encoded, K.ADM_MAGIC)
        exported_control_mat = next(material for material in control_doc["materials"]
                                    if material["name"] == control_mat.name)
        check(exported_control_mat["extensions"][K.TERRAIN_CONTROL_MAP_EXT]["mode"] == "TEXTURE_RGBA"
              and exported_control_mat["extensions"][K.TERRAIN_CONTROL_MAP_EXT]["mapping"] == "WORLD_PLANAR_XZ"
              and exported_control_mat["extensions"][K.TERRAIN_SURFACE_EXT]["surfaceIds"] == surface_ids,
              "TERRAIN_4: generated Control Map and stable layer IDs export")

    # 1. every builder with every parameter overridden ------------------------------------------
    profile_cases = sorted(
        (key, kind) for key, kind in K.OFFICIAL_SHADER_KINDS.items()
        if kind in SP.BUILDERS
    )
    for key, kind in profile_cases:
        mat = bpy.data.materials.new(f"prev_{kind}")
        plane.data.materials.clear()
        plane.data.materials.append(mat)
        M.convert_to_adm_material(mat)
        fallback = M.principled_of(mat)
        fallback.inputs["Base Color"].default_value = (0.3, 0.6, 0.9, 1.0)
        mat.adm.vertex_controls_enabled = True
        mat.adm.shader = kind
        mat.adm.shader_version = key[1]
        for prm in K.OFFICIAL_SHADERS[key]:
            if prm["type"] == "TEXTURE":
                set_param(mat, prm["name"], tex)
            elif prm["type"] == "F32":
                set_param(mat, prm["name"], float(prm.get("maximum", 1.0)) * 0.5)
            elif prm["type"] == "BOOL":
                mat.adm.params[prm["name"]].value_bool = True
            elif prm["type"] == "ENUM":
                set_param(mat, prm["name"], prm["values"][0])
            else:
                set_param(mat, prm["name"], [0.5] * K.SHADER_NUMERIC_DIMS[prm["type"]])
        check(all(v.use for v in mat.adm.params), f"{kind}: editing values enables Override")
        out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        check(out is not None and M.is_preview_node(out), f"{kind}: preview output is active")
        check(M.principled_of(mat) == fallback, f"{kind}: exporter still sees the fallback BSDF")
        exporter = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True))
        _data, report = exporter.export()
        check(report.ok, f"{kind}: export validates")
        if report.ok:
            m = report.doc["materials"][0]
            check(close(m["baseColorFactor"], (0.3, 0.6, 0.9, 1.0), 1e-5), f"{kind}: fallback base color exported")
            names = {p["name"] for p in K.OFFICIAL_SHADERS[key]}
            check(set(m.get("shaderParameters", {})) == names, f"{kind}: all overridden parameters exported")
            if key == (K.SHADER_CORE[0], K.SHADER_PROFILE_EDGE_WEAR):
                check(SP.PREVIEW_WEAR_AMOUNT not in str(report.doc),
                      "CORE@2.1.0: preview wear amount is not exported")
        mat.adm.vertex_controls_enabled = False
        mat.adm.shader_version = "1.0.0"
        mat.adm.shader = "CORE"
        check(not any(M.is_preview_node(n) for n in mat.node_tree.nodes), f"{kind}: CORE removes preview nodes")

    # 1b. Versioned COLOR_1 overlays compose before the universal COLOR_0 wetness operation.
    mat = bpy.data.materials.new("color1_v2_surface")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.shader_version = K.SHADER_PROFILE_V2
    mat.adm.shader = "CORE"
    fallback = M.principled_of(mat)
    fallback.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1.0)
    fallback.inputs["Metallic"].default_value = 0.2
    fallback.inputs["Roughness"].default_value = 0.7
    fallback.inputs["Specular IOR Level"].default_value = 0.0
    color1 = plane.data.color_attributes.get("COLOR_1")
    if color1 is None:
        color1 = plane.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    color1.data.foreach_set("color", np.tile((0.5, 0.0, 0.0, 0.0), len(color1.data)).ravel())
    set_param(mat, "color1_r_strength", 0.5)
    set_param(mat, "color1_r_color", (0.8, 0.2, 0.1))
    set_param(mat, "color1_r_metallic", 0.8)
    set_param(mat, "color1_r_roughness", 0.9)
    for channel in ("g", "b", "a"):
        set_param(mat, f"color1_{channel}_strength", 0.0)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    check(bsdf is not None, "CORE@2.0.0: builds a profile preview")
    if bsdf is not None:
        base_color = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
        metallic = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        roughness = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(base_color[8, 8, :3], (0.35, 0.35, 0.475)),
              f"COLOR_1.R surface overlay blends linear color ({base_color[8, 8, :3]})")
        check(close(metallic[8, 8, :1], (0.35,)),
              f"COLOR_1.R surface overlay blends metallic ({metallic[8, 8, 0]:.3f})")
        check(close(roughness[8, 8, :1], (0.75,)),
              f"COLOR_1.R surface overlay blends roughness ({roughness[8, 8, 0]:.3f})")
        packed = image("overlay_packed", lambda x, y: (0.2, 0.4, 0.6, 0.8))
        set_param(mat, "color1_r_metallic_texture", packed)
        set_param(mat, "color1_r_roughness_texture", packed)
        mat.adm.params["color1_r_metallic_channel"].texture_channel = "G"
        mat.adm.params["color1_r_metallic_invert"].texture_invert = True
        mat.adm.params["color1_r_roughness_channel"].texture_channel = "B"
        bsdf = preview_bsdf(mat, M)
        metallic = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        roughness = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metallic[8, 8, :1], (0.27,)) and close(roughness[8, 8, :1], (0.66,)),
              "COLOR_1.R uses independently selected/inverted scalar map channels before blending")
        mat.adm.params["color1_r_metallic_texture"].use = False
        mat.adm.params["color1_r_roughness_texture"].use = False
        bsdf = preview_bsdf(mat, M)
        metallic = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        roughness = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metallic[8, 8, :1], (0.35,)) and close(roughness[8, 8, :1], (0.75,)),
              "COLOR_1.R absent scalar maps retain the factor-only behavior")
        mat.adm.vertex_controls_enabled = True
        color0 = plane.data.color_attributes.get("COLOR_0")
        color0.data.foreach_set("color", np.tile((0.0, 1.0, 1.0, 0.5), len(color0.data)).ravel())
        mat.adm.wetness_offset = 0.25
        M.refresh_shader_preview(mat)
        bsdf = preview_bsdf(mat, M)
        color0_after = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
        check(close(color0_after[8, 8, :3], (0.310625, 0.310625, 0.4215625)),
              f"COLOR_0 wetness follows the COLOR_1 overlay ({color0_after[8, 8, :3]})")
        mat.adm.vertex_controls_enabled = False

    # 1c. PBR metallic-roughness 2.1.0 derives edge wear and instance dirt at runtime.
    mat = bpy.data.materials.new("edge_wear_21")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.shader_version = K.SHADER_PROFILE_EDGE_WEAR
    fallback = M.principled_of(mat)
    fallback.inputs["Base Color"].default_value = (0.2, 0.2, 0.2, 1.0)
    fallback.inputs["Specular IOR Level"].default_value = 0.0
    set_color1(plane, (0.0, 0.0, 1.0, 0.0))
    plane[SP.PREVIEW_WEAR_AMOUNT] = 1.0
    set_param(mat, "color1_b_color", (0.82, 0.82, 0.82))
    set_param(mat, "color1_b_roughness", 0.3)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    flat = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(flat[8, 8, :3], (0.2, 0.2, 0.2)),
          f"CORE@2.1.0: COLOR_1.B alone does not wear a flat surface ({flat[8, 8, :3]})")

    normal_image = image(
        "normal_edge_step",
        lambda x, y: (0.5, 0.5, 1.0, 1.0) if x < RES // 2 else (1.0, 0.5, 0.5, 1.0),
    )
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    normal_tex = nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal_image
    uv_node = nodes.new("ShaderNodeTexCoord")
    links.new(uv_node.outputs["UV"], normal_tex.inputs["Vector"])
    normal_map = nodes.new("ShaderNodeNormalMap")
    links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], fallback.inputs["Normal"])
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    normal_edge = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(np.max(normal_edge[:, 7:9, 0]) > normal_edge[8, 3, 0] + 0.1,
          "CORE@2.1.0: normal-map transitions trigger wear only at the transition")
    check(np.ptp(normal_edge[:, 7, 0]) > 0.03,
          "CORE@2.1.0: procedural chips vary along the same edge")
    plane[SP.PREVIEW_WEAR_AMOUNT] = 0.0
    plane.update_tag()
    no_wear = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(np.max(np.abs(no_wear[:, 7:9, 0] - 0.2)) < 0.01,
          "CORE@2.1.0: zero engine wear disables wear with an enabled vertex mask")
    plane[SP.PREVIEW_WEAR_AMOUNT] = 0.5
    plane.update_tag()
    half_wear = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(np.max(np.abs(half_wear[:, 7:9, 0] - (normal_edge[:, 7:9, 0] + 0.2) / 2)) < 0.02,
          "CORE@2.1.0: engine wear adjusts the overlay without changing the mask")
    plane[SP.PREVIEW_WEAR_AMOUNT] = 1.0
    plane.update_tag()
    instance = plane.copy()
    scene.collection.objects.link(instance)
    instance[SP.PREVIEW_WEAR_AMOUNT] = 0.0
    instance.location.x += 3.0
    instance.update_tag()
    instance_wear = bake_socket(instance, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(np.max(np.abs(instance_wear[:, 7:9, 0] - 0.2)) < 0.01,
          "CORE@2.1.0: shared-material instances can have independent engine wear")
    bpy.data.objects.remove(instance, do_unlink=True)

    base_texture = image("edge_wear_base", lambda x, y: (0.1, 0.3, 0.5, 1.0), non_color=False)
    base_node = nodes.new("ShaderNodeTexImage")
    base_node.image = base_texture
    links.new(base_node.outputs["Color"], fallback.inputs["Base Color"])
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    textured = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(textured[8, 3, :3], (0.1, 0.3, 0.5)),
          "CORE@2.1.0: the original base texture remains visible away from edges")
    check(np.max(textured[:, 7:9, 0]) > 0.2,
          "CORE@2.1.0: wear changes the textured material at normal-map edges")
    links.remove(base_node.outputs["Color"].links[0])
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    set_color1(plane, (0.0, 0.0, 0.0, 0.0))
    no_wear_mask = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(no_wear_mask[8, 7, :3], (0.2, 0.2, 0.2)),
          "CORE@2.1.0: COLOR_1.B still gates detected normal-map edges")
    links.remove(normal_map.outputs["Normal"].links[0])

    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0, location=(3.0, 0.0, 0.0))
    sphere = bpy.context.active_object
    sphere.name = "edge_wear_curvature_test"
    sphere.data.materials.append(mat)
    sphere[SP.PREVIEW_WEAR_AMOUNT] = 1.0
    set_color1(sphere, (0.0, 0.0, 1.0, 0.0))
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    curved = bake_socket(sphere, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(max(curved[8, 8, :3]) > 0.2,
          "CORE@2.1.0: positive geometric curvature triggers wear")

    set_color1(plane, (0.0, 1.0, 0.0, 0.0))
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 3.0, 0.0))
    second_instance = bpy.context.active_object
    second_instance.name = "edge_wear_dirt_instance"
    second_instance.data.materials.append(mat)
    set_color1(second_instance, (0.0, 1.0, 0.0, 0.0))
    set_param(mat, "color1_g_color", (0.18, 0.14, 0.1))
    set_param(mat, "color1_g_roughness", 0.95)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    dirt_amount_node = next(node for node in mat.node_tree.nodes
                            if node.name == "ADM Preview Per-instance Dirt Amount")
    amount_a = bake_socket(plane, mat, dirt_amount_node.outputs["Random"])[8, 8, 0]
    amount_b = bake_socket(second_instance, mat, dirt_amount_node.outputs["Random"])[8, 8, 0]
    check(0.0 <= amount_a <= 1.0 and 0.0 <= amount_b <= 1.0 and abs(amount_a - amount_b) > 1e-4,
          f"CORE@2.1.0: dirt amount varies per instance ({amount_a:.3f}, {amount_b:.3f})")
    dirt_a = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    dirt_b = bake_socket(second_instance, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    expected_a = tuple(0.2 * (1.0 - amount_a) + target * amount_a for target in (0.18, 0.14, 0.1))
    expected_b = tuple(0.2 * (1.0 - amount_b) + target * amount_b for target in (0.18, 0.14, 0.1))
    check(close(dirt_a, expected_a) and close(dirt_b, expected_b),
          "CORE@2.1.0: COLOR_1.G gates per-instance dirt without storing its amount in ADM")
    bpy.data.objects.remove(sphere, do_unlink=True)
    bpy.data.objects.remove(second_instance, do_unlink=True)

    # The explicit mask-preview mode works even when the profile's effect is disabled.
    window = bpy.context.window_manager.adm
    mat.adm.shader_version = "1.0.0"
    window.vertex_color_layer = "COLOR_1"
    window.vertex_color_channel = "R"
    window.vertex_color_preview = True
    M.refresh_shader_preview(mat)
    output = next(n for n in mat.node_tree.nodes
                  if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    check(M.is_preview_node(output), "COLOR_1 preview works on a reserved 1.0.0 profile")
    window.vertex_color_preview = False
    M.refresh_shader_preview(mat)

    # Interactive: the object displays its authored fallback, not invented runtime content.
    mat = bpy.data.materials.new("interactive_static")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    fallback = M.principled_of(mat)
    fallback.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1.0)
    fallback.inputs["Specular IOR Level"].default_value = 0.0
    mat.adm.shader = "INTERACTIVE"
    mat.adm.params["brightness"].value_f = 8.0
    mat.adm.params["enabled"].value_bool = False
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.2, 0.4, 0.6)),
          f"INTERACTIVE: disabled runtime still displays the authored fallback on the object ({alb[8, 8, :3]})")

    # 2. Brick: bake albedo / roughness ------------------------------------------------------------
    mat = bpy.data.materials.new("brick")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    M.principled_of(mat).inputs["Base Color"].default_value = (0.8, 0.1, 0.1, 1.0)
    # Cycles' diffuse-colour bake subtracts the dielectric specular albedo; disable it for exact values.
    M.principled_of(mat).inputs["Specular IOR Level"].default_value = 0.0
    mat.adm.shader = "BRICK"
    set_param(mat, "mortar_mask", image("mortar", lambda x, y: (1.0, 1.0, 1.0, 1.0) if x < RES // 2
                                        else (0.0, 0.0, 0.0, 1.0)))
    set_param(mat, "mortar_color", (0.2, 0.4, 0.6))
    set_param(mat, "uv_scale", (2.0, 1.0))
    alb = bake(plane, mat, "DIFFUSE")
    # uv_scale.x = 2 repeats the half-white mask twice: bake column 1 -> mortar, column 6 -> brick.
    check(close(alb[8, 1, :3], (0.2, 0.4, 0.6)), f"BRICK: mortar albedo = mortar_color ({alb[8, 1, :3]})")
    check(close(alb[8, 6, :3], (0.8, 0.1, 0.1)), f"BRICK: brick albedo = base color ({alb[8, 6, :3]})")
    check(close(alb[8, 9, :3], (0.2, 0.4, 0.6)), "BRICK: uv_scale repeats the mortar mask")
    # Roughness is only defined by the specular lobe; restore it for the ROUGHNESS bake.
    M.principled_of(mat).inputs["Specular IOR Level"].default_value = 0.5
    M.refresh_shader_preview(mat)
    rough = bake(plane, mat, "ROUGHNESS")
    check(close(rough[8, 1, :1], (0.9,)) and close(rough[8, 6, :1], (0.75,)),
          f"BRICK: roughness defaults mix by mask ({rough[8, 1, 0]:.3f}, {rough[8, 6, 0]:.3f})")
    set_param(mat, "brick_roughness", 0.4)
    count = len(mat.node_tree.nodes)
    set_param(mat, "brick_roughness", 0.25)
    check(len(mat.node_tree.nodes) == count, "BRICK: overridden value change does not rebuild the graph")
    rough = bake(plane, mat, "ROUGHNESS")
    check(close(rough[8, 6, :1], (0.25,)), f"BRICK: driver updates roughness live ({rough[8, 6, 0]:.3f})")
    M.principled_of(mat).inputs["Specular IOR Level"].default_value = 0.0
    set_param(mat, "dirt_mask", image("dirt", lambda x, y: (0.5, 0.5, 0.5, 1.0)))
    alb = bake(plane, mat, "DIFFUSE")
    k = 1.0 + (0.35 - 1.0) * 0.5
    check(close(alb[8, 6, :3], (0.8 * k, 0.1 * k, 0.1 * k)), f"BRICK: dirt multiplies by mix(1,0.35,d) ({alb[8, 6, :3]})")

    # PBR Layered 2.0 uses the same scalar maps and independently tiled UVs as terrain.
    mat = bpy.data.materials.new("layered_scalar_maps")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.shader = "LAYERED"
    mat.adm.shader_version = K.SHADER_PROFILE_V2
    for uv in plane.data.uv_layers[1].data:
        uv.uv = (0.375, 0.5)
    color1.data.foreach_set("color", np.tile((0.25, 0.25, 0.25, 0.25), len(color1.data)).ravel())
    set_param(mat, "uv_scale", (2.0, 1.0, 1.0, 1.0))
    for i in range(4):
        set_param(mat, f"layer{i}_metallic", 0.5)
        set_param(mat, f"layer{i}_roughness", 0.8)
    metal_map = image("layered_metal", lambda x, y: (0.1, 0.2 if x < RES // 2 else 0.8, 0.3, 1.0))
    rough_map = image("layered_rough", lambda x, y: (0.1, 0.2, 0.25, 1.0))
    set_param(mat, "layer0_metallic_texture", metal_map)
    mat.adm.params["layer0_metallic_texture"].tex_coord = 1
    mat.adm.params["layer0_metallic_channel"].texture_channel = "G"
    set_param(mat, "layer2_roughness_texture", rough_map)
    mat.adm.params["layer2_roughness_channel"].texture_channel = "B"
    mat.adm.params["layer2_roughness_invert"].texture_invert = True
    bsdf = preview_bsdf(mat, M)
    metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
    rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
    check(close(metal[8, 8, :1], (0.475,)) and close(rough[8, 8, :1], (0.75,)),
          "LAYERED@2.0.0 blends textured factors with layer UV1, tiling and inversion")

    # 3. Terrain: one-hot and all-zero blend masks ------------------------------------------------
    mat = bpy.data.materials.new("terrain")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    M.principled_of(mat).inputs["Specular IOR Level"].default_value = 0.0
    mat.adm.shader = "TERRAIN_4"
    for i, c in enumerate(((0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.1, 0.9), (0.5, 0.5, 0.1))):
        set_param(mat, f"layer{i}_base_color", (*c, 1.0))
    set_param(mat, "blend_mask", image("blend", lambda x, y: (0.0, 1.0, 0.0, 0.0) if x < RES // 2
                                       else (0.0, 0.0, 0.0, 0.0)))
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 3, :3], (0.1, 0.9, 0.1)), f"TERRAIN_4: one-hot G selects layer 1 ({alb[8, 3, :3]})")
    check(close(alb[8, 12, :3], (0.9, 0.1, 0.1)), f"TERRAIN_4: zero mask falls back to layer 0 ({alb[8, 12, :3]})")
    color0 = plane.data.color_attributes.get("COLOR_0")
    if color0 is not None:
        color0.data.foreach_set("color", np.tile((0.0, 1.0, 1.0, 0.0), len(color0.data)).ravel())
        plane.data.update()
    layer_colors = ((0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.1, 0.9), (0.5, 0.5, 0.1))
    for i, expected in enumerate(layer_colors):
        rgba = tuple(float(n == i) for n in range(4))
        one_hot = image(f"one_hot_layer_{i}", lambda x, y, rgba=rgba: rgba)
        set_param(mat, "blend_mask", one_hot)
        check(one_hot.colorspace_settings.name == "Non-Color" and one_hot.alpha_mode == "CHANNEL_PACKED",
              f"TERRAIN_4: channel {i} mask uses linear packed channels")
        alb = bake(plane, mat, "DIFFUSE")
        check(close(alb[8, 8, :3], expected), f"TERRAIN_4: channel {i} selects layer {i}")
        data, report = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True)).export()
        check(report.ok and "blend_mask" in report.doc["materials"][0]["shaderParameters"],
              f"TERRAIN_4: channel {i} mask exports")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "one_hot.adm")
            with open(path, "wb") as stream:
                stream.write(data)
            _, imported_root = import_model(bpy.context, path, ImportOptions())
            imported = next(obj for obj in imported_root.children_recursive if obj.type == "MESH")
            imported_mat = imported.active_material
            imported_mask = imported_mat.adm.params["blend_mask"].image
            check(imported_mask.colorspace_settings.name == "Non-Color"
                  and imported_mask.alpha_mode == "CHANNEL_PACKED",
                  f"TERRAIN_4: imported channel {i} mask remains linear and packed")
            imported_bsdf = preview_bsdf(imported_mat, M)
            imported_color = bake_socket(imported, imported_mat,
                                         imported_bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
            check(close(imported_color, expected),
                  f"TERRAIN_4: exported channel {i} selects layer {i} ({imported_color})")

    set_param(mat, "blend_mask", image("metal_layer_0", lambda x, y: (1.0, 0.0, 0.0, 0.0)))
    set_param(mat, "layer0_metallic_texture", image("metal_factor_map", lambda x, y: (0.8, 0.0, 0.0, 1.0)))
    set_param(mat, "layer0_metallic", 0.0)
    bsdf = preview_bsdf(mat, M)
    before = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)[8, 8, 0]
    check(bpy.ops.adm.material_set_map_factor(name="layer0_metallic") == {"FINISHED"},
          "TERRAIN_4: enable metallic map factor")
    bsdf = preview_bsdf(mat, M)
    after = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)[8, 8, 0]
    check(close((before, after), (0.0, 0.8)), "TERRAIN_4: setting factor to 1 changes metallic preview")
    mat.adm.params["layer0_metallic_texture"].use = False
    mat.adm.params["layer0_metallic"].use = False

    # 3b. Terrain 2.0.0 uses normalized COLOR_1 weights and the zero-sum layer-0 fallback.
    mat.adm.shader_version = K.SHADER_PROFILE_V2
    M.sync_official_shader_params(mat, (K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_V2))
    mat.adm.params["blend_mask"].use = False
    mat.adm.params["blend_mask"].image = None
    color1 = plane.data.color_attributes.get("COLOR_1")
    if color1 is None:
        color1 = plane.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    color1.data.foreach_set("color", np.tile((0.0, 1.0, 0.0, 0.0), len(color1.data)).ravel())
    M.refresh_shader_preview(mat)
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.1, 0.9, 0.1)),
          f"TERRAIN_4@2.0.0: COLOR_1.G selects layer 1 ({alb[8, 8, :3]})")
    color1.data.foreach_set("color", np.zeros((len(color1.data), 4), dtype=np.float32).ravel())
    bpy.context.view_layer.update()
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.9, 0.1, 0.1)),
          f"TERRAIN_4@2.0.0: zero weights fall back to layer 0 ({alb[8, 8, :3]})")

    # Macro Color is an sRGB albedo-only operation over the existing normalized weights.
    layer_colors = ((0.9, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.1, 0.9), (0.5, 0.5, 0.1))
    for index, color in enumerate(layer_colors):
        set_param(mat, f"layer{index}_base_color", (*color, 1.0))
    color1.data.foreach_set("color", np.tile((0.0, 1.0, 0.0, 0.0), len(color1.data)).ravel())
    macro_sample = (0.5, 0.25, 0.75, 0.5)
    macro_image = image("macro_color_srgb", lambda x, y: macro_sample, non_color=False)
    mat.adm.macro_color_enabled = True
    mat.adm.macro_color_image = macro_image
    mat.adm.macro_color_projection = "LOCAL_UV"
    mat.adm.macro_color_tex_coord = 0
    mat.adm.macro_color_strength = 0.4
    mat.adm.macro_color_layer_influence = (1.0, 0.5, 1.0, 1.0)
    saved_weights = np.array([tuple(item.color) for item in color1.data], dtype=np.float32)
    for blend_mode in ("MULTIPLY", "TINT", "LERP"):
        mat.adm.macro_color_blend_mode = blend_mode
        M.refresh_shader_preview(mat)
        bsdf = preview_bsdf(mat, M)
        pixel = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
        expected = terrain_macro_color(
            layer_colors, (0.0, 1.0, 0.0, 0.0), macro_sample, blend_mode, 0.4,
            (1.0, 0.5, 1.0, 1.0),
        )
        check(close(pixel, expected), f"TERRAIN_4: {blend_mode} Macro Color matches linear reference ({pixel})")
    check(np.array_equal(saved_weights, np.array([tuple(item.color) for item in color1.data], dtype=np.float32)),
          "TERRAIN_4: Macro Color does not modify COLOR_1 terrain weights")
    split_macro = image(
        "macro_color_projection",
        lambda x, y: (1.0, 0.0, 0.0, 1.0) if x < RES // 2 else (0.0, 0.0, 1.0, 1.0),
        non_color=False,
    )
    mat.adm.macro_color_image = split_macro
    mat.adm.macro_color_blend_mode = "LERP"
    mat.adm.macro_color_strength = 1.0
    mat.adm.macro_color_layer_influence = (1.0, 1.0, 1.0, 1.0)
    mat.adm.macro_color_projection = "LOCAL_UV"
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    local = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(local[8, 3, :3], (1.0, 0.0, 0.0)) and close(local[8, 12, :3], (0.0, 0.0, 1.0)),
          f"TERRAIN_4: Macro Color samples local UV ({local[8, 3, :3]}, {local[8, 12, :3]})")
    mat.adm.macro_color_projection = "SHARED_WORLD_XZ"
    mat.adm.macro_color_origin = (-1.0, 0.0)
    bpy.context.view_layer.update()
    bsdf = preview_bsdf(mat, M)
    world = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(world[8, 3, :3], (1.0, 0.0, 0.0)) and close(world[8, 12, :3], (0.0, 0.0, 1.0)),
          f"TERRAIN_4: Macro Color samples shared world XZ ({world[8, 3, :3]}, {world[8, 12, :3]})")
    mat.adm.macro_color_enabled = False

    # Macro Normal reconstructs BC5 XY and composes each active layer with RNM.
    macro_normal_sample = (0.75, 0.5, 0.5, 1.0)
    mat.adm.macro_normal_enabled = True
    mat.adm.macro_normal_image = image(
        "macro_normal_rnm", lambda x, y: macro_normal_sample)
    mat.adm.macro_normal_projection = "LOCAL_UV"
    mat.adm.macro_normal_tex_coord = 0
    mat.adm.macro_normal_strength = 0.5
    mat.adm.macro_normal_layer_influence = (1.0, 0.5, 1.0, 1.0)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    normal_socket = bsdf.inputs["Normal"].links[0].from_socket
    macro_normal_pixel = bake_socket(plane, mat, normal_socket)[8, 8, :3]
    expected_normal = terrain_macro_normal(
        (None, None, None, None), (0.0, 1.0, 0.0, 0.0),
        macro_normal_sample[:2], 0.5, (1.0, 0.5, 1.0, 1.0))
    check(close(macro_normal_pixel, expected_normal),
          f"TERRAIN_4: Macro Normal RNM matches independent vector ({macro_normal_pixel})")
    original_rotation = plane.rotation_euler.copy()
    plane.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    mat.adm.macro_normal_projection = "SHARED_WORLD_XZ"
    mat.adm.macro_normal_origin = (0.0, 0.0)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    rotated_normal = bake_socket(
        plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    tangent_frame = terrain_macro_normal_frame(
        (0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    expected_tangent = terrain_macro_normal(
        (None, None, None, None), (0.0, 1.0, 0.0, 0.0),
        macro_normal_sample[:2], 0.5, (1.0, 0.5, 1.0, 1.0))
    expected_world = tuple(sum(axis[i] * component for axis, component in
                               zip(tangent_frame, expected_tangent)) for i in range(3))
    check(close(rotated_normal, expected_world),
          f"TERRAIN_4: shared-world RNM follows the projection tangent frame ({rotated_normal})")
    plane.rotation_euler = original_rotation
    uv0 = plane.data.uv_layers[0]
    uv1 = plane.data.uv_layers[1]
    for source_uv, target_uv in zip(uv0.data, uv1.data):
        target_uv.uv = (source_uv.uv.y, 1.0 - source_uv.uv.x)
    set_param(mat, "layer1_normal", image(
        "layer1_rotated_uv_normal",
        lambda x, y: (0.75, 0.5, 0.5 * math.sqrt(0.75) + 0.5, 1.0)))
    mat.adm.params["layer1_normal"].tex_coord = 1
    mat.adm.macro_normal_projection = "SHARED_WORLD_XZ"
    mat.adm.macro_normal_strength = 0.0
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    uv1_normal = bake_socket(plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    check(close(uv1_normal, (0.0, 0.5, math.sqrt(0.75))),
          f"TERRAIN_4: layer UV1 normal transforms through the shared Macro Normal frame ({uv1_normal})")
    bpy.context.view_layer.update()
    normal_weights = np.array([tuple(item.color) for item in color1.data], dtype=np.float32)
    mat.adm.macro_normal_strength = 0.0
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    neutral_normal = bake_socket(plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    check(close(neutral_normal, (0.0, 0.5, math.sqrt(0.75))),
          f"TERRAIN_4: zero Macro Normal strength preserves the base normal ({neutral_normal})")
    check(np.array_equal(normal_weights, np.array([tuple(item.color) for item in color1.data],
                                                   dtype=np.float32)),
          "TERRAIN_4: Macro Normal does not modify COLOR_1 terrain weights")
    split_normal = image(
        "macro_normal_projection",
        lambda x, y: (0.5, 0.5, 1.0, 1.0) if x < RES // 2 else (0.75, 0.5, 1.0, 1.0))
    mat.adm.macro_normal_image = split_normal
    mat.adm.macro_normal_strength = 1.0
    mat.adm.macro_normal_layer_influence = (1.0, 1.0, 1.0, 1.0)
    mat.adm.macro_normal_projection = "LOCAL_UV"
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    local_normal = bake_socket(plane, mat, bsdf.inputs["Normal"].links[0].from_socket)
    check(local_normal[8, 3, 0] < 0.03 and local_normal[8, 12, 0] > 0.2,
          "TERRAIN_4: Macro Normal samples local UV coordinates")
    mat.adm.macro_normal_projection = "SHARED_WORLD_XZ"
    mat.adm.macro_normal_origin = (-1.0, 0.0)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    world_normal = bake_socket(plane, mat, bsdf.inputs["Normal"].links[0].from_socket)
    check(world_normal[8, 3, 0] < 0.03 and world_normal[8, 12, 0] > 0.2,
          "TERRAIN_4: Macro Normal samples shared world XZ coordinates")
    mat.adm.params["layer1_normal"].image = None
    for source_uv, target_uv in zip(uv0.data, uv1.data):
        target_uv.uv = (1.0 - source_uv.uv.x, source_uv.uv.y)
    mat.adm.macro_normal_image = image(
        "macro_normal_mirrored_uv", lambda x, y: macro_normal_sample)
    mat.adm.macro_normal_projection = "LOCAL_UV"
    mat.adm.macro_normal_tex_coord = 1
    mat.adm.macro_normal_strength = 0.5
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    mirrored_normal = bake_socket(
        plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    check(close(mirrored_normal, (-0.25, 0.0, math.sqrt(0.9375))),
          f"TERRAIN_4: mirrored UV handedness follows the tangent frame ({mirrored_normal})")
    for macro_scale, expected_x in (((0.0, 1.0), 0.25), ((1.0, 0.0), -0.25)):
        mat.adm.macro_normal_scale = macro_scale
        M.refresh_shader_preview(mat)
        bsdf = preview_bsdf(mat, M)
        scaled_degenerate = bake_socket(
            plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
        expected = (expected_x, 0.0, math.sqrt(0.9375))
        check(close(scaled_degenerate, expected),
              f"TERRAIN_4: zero Macro Normal scale component uses fallback frame {macro_scale}")
    mat.adm.macro_normal_scale = (1.0, 1.0)
    for uv in uv1.data:
        uv.uv = (0.5, 0.5)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    degenerate_uv = bake_socket(
        plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    check(close(degenerate_uv, (0.25, 0.0, math.sqrt(0.9375))),
          f"TERRAIN_4: degenerate UV derivatives use deterministic fallback ({degenerate_uv})")
    plane.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    M.refresh_shader_preview(mat)
    bsdf = preview_bsdf(mat, M)
    rotated_degenerate_uv = bake_socket(
        plane, mat, bsdf.inputs["Normal"].links[0].from_socket)[8, 8, :3]
    rotated_frame = terrain_macro_normal_frame(
        (0.0, -1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    expected_rotated_degenerate = terrain_macro_normal(
        (None, None, None, None), (0.0, 1.0, 0.0, 0.0),
        macro_normal_sample[:2], 0.5, (1.0, 1.0, 1.0, 1.0))
    expected_rotated_degenerate_world = tuple(
        sum(axis[i] * component for axis, component in
            zip(rotated_frame, expected_rotated_degenerate)) for i in range(3))
    check(close(rotated_degenerate_uv, expected_rotated_degenerate_world),
          f"TERRAIN_4: rotated degenerate UV uses reference fallback "
          f"({rotated_degenerate_uv}, expected {expected_rotated_degenerate_world})")
    plane.rotation_euler = original_rotation
    mat.adm.macro_normal_enabled = False

    # Terrain scalar maps use their own UV set, layer tiling and normalized layer weights.
    for version in ("1.0.0", K.SHADER_PROFILE_V2):
        mat = bpy.data.materials.new(f"terrain_maps_{version}")
        plane.data.materials.clear()
        plane.data.materials.append(mat)
        M.convert_to_adm_material(mat)
        mat.adm.vertex_controls_enabled = False
        mat.adm.shader = "TERRAIN_4"
        mat.adm.shader_version = version
        for uv in plane.data.uv_layers[1].data:
            uv.uv = (0.375, 0.5)
        set_param(mat, "uv_scale", (2.0, 1.0, 1.0, 1.0))
        set_param(mat, "blend_mask", image(f"weights_{version}", lambda x, y: (1.0, 1.0, 1.0, 1.0)))
        color1.data.foreach_set("color", np.ones(len(color1.data) * 4, dtype=np.float32))
        for i in range(4):
            set_param(mat, f"layer{i}_metallic", 0.5)
            set_param(mat, f"layer{i}_roughness", 0.8)
            metallic = image(f"metal_{version}_{i}",
                             lambda x, y, i=i: ((0.1 if x < RES // 2 else 0.8) if i == 0
                                                else i * 0.2, 0.95, 0.05, 1.0))
            set_param(mat, f"layer{i}_metallic_texture", metallic)
            if i < 3:
                roughness = image(f"rough_{version}_{i}", lambda x, y, i=i: ((i + 1) * 0.1, 0.9, 0.9, 1.0))
                set_param(mat, f"layer{i}_roughness_texture", roughness)
        mat.adm.params["layer0_metallic_texture"].tex_coord = 1
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.25,)),
              f"TERRAIN_4@{version}: tiled UV1 metallic red maps blend with factors ({metal[8, 3, 0]:.3f})")
        check(close(rough[8, 3, :1], (0.32,)),
              f"TERRAIN_4@{version}: roughness red maps and missing-map factor blend ({rough[8, 3, 0]:.3f})")
        mat.adm.params["layer0_metallic_texture"].image = None
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.275,)),
              f"TERRAIN_4@{version}: removing a metallic map restores its factor ({metal[8, 3, 0]:.3f})")
        set_param(mat, "blend_mask", image(f"one_hot_{version}", lambda x, y: (0.0, 0.0, 0.0, 1.0)))
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.3,)) and close(rough[8, 3, :1], (0.8,)),
              f"TERRAIN_4@{version}: one-hot mask selects layer 3 maps and fallback")
        set_param(mat, "blend_mask", image(f"zero_{version}", lambda x, y: (0.0, 0.0, 0.0, 0.0)))
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.5,)) and close(rough[8, 3, :1], (0.08,)),
              f"TERRAIN_4@{version}: zero mask selects layer 0 maps and fallback")

        packed = image(f"packed_{version}", lambda x, y: (0.2, 0.4, 0.6, 0.8))
        set_param(mat, "layer0_metallic_texture", packed)
        set_param(mat, "layer0_roughness_texture", packed)
        set_param(mat, "layer0_metallic", 1.0)
        set_param(mat, "layer0_roughness", 1.0)
        for channel, expected in zip(("R", "G", "B", "A"), (0.2, 0.4, 0.6, 0.8)):
            mat.adm.params["layer0_metallic_channel"].texture_channel = channel
            mat.adm.params["layer0_roughness_channel"].texture_channel = channel
            bsdf = preview_bsdf(mat, M)
            metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
            rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
            check(close(metal[8, 3, :1], (expected,)) and close(rough[8, 3, :1], (expected,)),
                  f"TERRAIN_4@{version}: metallic and roughness select packed {channel}")
        mat.adm.params["layer0_metallic_channel"].texture_channel = "G"
        mat.adm.params["layer0_roughness_channel"].texture_channel = "B"
        mat.adm.params["layer0_metallic_invert"].texture_invert = True
        mat.adm.params["layer0_roughness_invert"].texture_invert = True
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.6,)) and close(rough[8, 3, :1], (0.4,)),
              f"TERRAIN_4@{version}: independently selected channels invert before multiplication")
        mat.adm.params["layer0_metallic_invert"].texture_invert = False
        mat.adm.params["layer0_roughness_invert"].use = False
        bsdf = preview_bsdf(mat, M)
        metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
        rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
        check(close(metal[8, 3, :1], (0.4,)) and close(rough[8, 3, :1], (0.6,)),
              f"TERRAIN_4@{version}: inversion can be disabled or reset to default")

    # Advanced terrain height blending is a real node effect; AO and POM settings
    # remain editable and survive ADM import/export.
    mat = bpy.data.materials.new("terrain_height_blend_v21")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.shader = "TERRAIN_4"
    mat.adm.shader_version = K.SHADER_PROFILE_LAYERED_HEIGHT_V2
    color1.data.foreach_set("color", np.tile((0.5, 0.5, 0.0, 0.0), len(color1.data)).ravel())
    set_param(mat, "layer0_base_color", (1.0, 0.0, 0.0, 1.0))
    set_param(mat, "layer1_base_color", (0.0, 0.0, 1.0, 1.0))
    set_param(mat, "layer0_height_texture", image("height_low", lambda x, y: (0.1, 0.1, 0.1, 1.0)))
    set_param(mat, "layer1_height_texture", image("height_high", lambda x, y: (0.9, 0.9, 0.9, 1.0)))
    mat.adm.params["height_blend_enabled"].value_bool = True
    set_param(mat, "height_blend_transition", 0.2)
    set_param(mat, "height_blend_strength", 1.0)
    bsdf = preview_bsdf(mat, M)
    actual = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    weights = height_blend_weights((0.5, 0.5, 0.0, 0.0), (0.1, 0.9, 0.5, 0.5),
                                   transition=0.2, present=(True, True, False, False))
    expected = (weights[0], 0.0, weights[1])
    check(close(actual, expected),
          f"TERRAIN_4@2.1.0: Cycles bake applies height blending ({actual} vs {expected})")

    mat.adm.params["height_blend_enabled"].value_bool = False
    set_param(mat, "layer0_ao_texture", image("ao_packed", lambda x, y: (0.2, 0.4, 0.6, 0.8)))
    set_param(mat, "layer0_ao_channel", 1.0)
    set_param(mat, "layer1_ao_texture", image("ao_white", lambda x, y: (1.0, 1.0, 1.0, 1.0)))
    bsdf = preview_bsdf(mat, M)
    actual = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)[8, 8, :3]
    check(close(actual, (0.35, 0.0, 0.35)),
          f"TERRAIN_4@2.1.0: selected AO channels affect the documented preview approximation ({actual})")

    set_param(mat, "parallax_mode", "PARALLAX_OCCLUSION")
    set_param(mat, "layer0_parallax_scale", 0.025)
    exporter = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True))
    data, report = exporter.export()
    check(report.ok, "TERRAIN_4@2.1.0: advanced material export validates")
    if report.ok:
        terrain_doc = next(material for material in report.doc["materials"]
                           if material.get("shader") == {
                               "id": K.SHADER_TERRAIN_4[0], "version": K.SHADER_PROFILE_LAYERED_HEIGHT_V2})
        terrain_params = terrain_doc["shaderParameters"]
        check(terrain_params["parallax_mode"] == "PARALLAX_OCCLUSION"
              and abs(terrain_params["layer0_parallax_scale"] - 0.025) < 1e-6
              and "layer0_ao_texture" in terrain_params,
              "TERRAIN_4@2.1.0: AO texture and POM metadata export")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "terrain_height.adm")
            with open(path, "wb") as stream:
                stream.write(data)
            _, imported_root = import_model(bpy.context, path, ImportOptions())
            imported = next(obj for obj in imported_root.children_recursive if obj.type == "MESH")
            imported_mat = imported.active_material
            check(imported_mat.adm.shader == "TERRAIN_4"
                  and imported_mat.adm.shader_version == K.SHADER_PROFILE_LAYERED_HEIGHT_V2
                  and imported_mat.adm.params["parallax_mode"].value_enum == "PARALLAX_OCCLUSION"
                  and imported_mat.adm.params["layer0_ao_texture"].image is not None,
                  "TERRAIN_4@2.1.0: shader version, AO texture, and POM metadata round-trip")
            imported_color1 = imported.data.color_attributes.get("COLOR_1")
            check(imported_color1 is not None and
                  close(imported_color1.data[0].color, (0.5, 0.5, 0.0, 0.0)),
                  "TERRAIN_4@2.1.0: authored COLOR_1 weights round-trip")

    # Two-layer mask directly interpolates all layer properties without vertex colors.
    mat = bpy.data.materials.new("two_layer")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    mat.adm.shader = "TWO_LAYER"
    set_param(mat, "layer0_base_color", (0.2, 0.4, 0.6, 1.0))
    set_param(mat, "layer1_base_color", (0.8, 0.2, 0.1, 1.0))
    set_param(mat, "layer0_metallic", 0.2)
    set_param(mat, "layer1_metallic", 0.8)
    set_param(mat, "layer0_roughness", 0.4)
    set_param(mat, "layer1_roughness", 0.8)
    bsdf = preview_bsdf(mat, M)
    base = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    check(close(base[8, 8, :3], (0.2, 0.4, 0.6)), "TWO_LAYER: absent mask selects layer 0")
    set_param(mat, "blend_mask", image("two_mask",
                                       lambda x, y: (0.0, 0.0, 0.0, 1.0) if x < 5
                                       else (0.5, 0.0, 0.0, 1.0) if x < 10
                                       else (1.0, 0.0, 0.0, 1.0)))
    bsdf = preview_bsdf(mat, M)
    base = bake_socket(plane, mat, bsdf.inputs["Base Color"].links[0].from_socket)
    metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
    rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
    check(close(base[8, 2, :3], (0.2, 0.4, 0.6))
          and close(base[8, 7, :3], (0.5, 0.3, 0.35))
          and close(base[8, 13, :3], (0.8, 0.2, 0.1)),
          "TWO_LAYER: black, gray and white mask blend albedo")
    check(close(metal[8, 7, :1], (0.5,)) and close(rough[8, 7, :1], (0.6,)),
          "TWO_LAYER: gray mask blends metallic and roughness")
    for i, pixel in enumerate(((0.1, 0.2, 0.1, 1.0), (0.1, 0.8, 0.5, 1.0))):
        tex = image(f"two_layer_packed_{i}", lambda x, y, p=pixel: p)
        set_param(mat, f"layer{i}_metallic", 1.0)
        set_param(mat, f"layer{i}_roughness", 1.0)
        set_param(mat, f"layer{i}_metallic_texture", tex)
        set_param(mat, f"layer{i}_roughness_texture", tex)
        mat.adm.params[f"layer{i}_metallic_channel"].texture_channel = "G"
        mat.adm.params[f"layer{i}_roughness_channel"].texture_channel = "B"
    mat.adm.params["layer1_metallic_invert"].texture_invert = True
    mat.adm.params["layer1_roughness_invert"].texture_invert = True
    bsdf = preview_bsdf(mat, M)
    metal = bake_socket(plane, mat, bsdf.inputs["Metallic"].links[0].from_socket)
    rough = bake_socket(plane, mat, bsdf.inputs["Roughness"].links[0].from_socket)
    check(close(metal[8, 7, :1], (0.2,)) and close(rough[8, 7, :1], (0.3,)),
          "TWO_LAYER: packed maps select and invert each layer's channels independently")

    # 4. Vertex controls are evaluated after the profile's material operations ---------------------
    mat = bpy.data.materials.new("vertex_controls")
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    fallback = M.principled_of(mat)
    fallback.inputs["Base Color"].default_value = (0.8, 0.4, 0.2, 1.0)
    fallback.inputs["Roughness"].default_value = 0.6
    fallback.inputs["Specular IOR Level"].default_value = 0.0
    mat.adm.shader = "BRICK"
    color0 = plane.data.color_attributes.get("COLOR_0")
    if color0 is None:
        color0 = plane.data.color_attributes.new(name="COLOR_0", type="FLOAT_COLOR", domain="CORNER")
    color0.data.foreach_set("color", np.tile((0.0, 1.0, 1.0, 0.0), len(color0.data)).ravel())
    mat.adm.vertex_controls_enabled = True
    mat.adm.wetness_offset = 1.0
    alb = bake(plane, mat, "DIFFUSE")
    water_f0 = ((1.333 - 1.0) / (1.333 + 1.0)) ** 2
    check(close(alb[8, 8, :3], (0.8 * 0.85 * (1.0 - water_f0),
                                 0.4 * 0.85 * (1.0 - water_f0),
                                 0.2 * 0.85 * (1.0 - water_f0))),
          f"COLOR_0 wetness darkens preview albedo ({alb[8, 8, :3]})")
    rough = bake(plane, mat, "ROUGHNESS")
    check(close(rough[8, 8, :1], (0.1,)), f"COLOR_0 wetness reduces preview roughness ({rough[8, 8, 0]:.3f})")
    node_count = len(mat.node_tree.nodes)
    mat.adm.wetness_offset = 0.5
    check(len(mat.node_tree.nodes) == node_count, "vertex-control values update through drivers without rebuilding")
    bpy.context.view_layer.update()
    alb = bake(plane, mat, "DIFFUSE")
    half_wet_f0 = water_f0 * 0.5
    check(close(alb[8, 8, :3], (0.8 * 0.925 * (1.0 - half_wet_f0),
                                 0.4 * 0.925 * (1.0 - half_wet_f0),
                                 0.2 * 0.925 * (1.0 - half_wet_f0))),
          f"vertex-control wetness driver updates live ({alb[8, 8, :3]})")
    mat.adm.wetness_offset = 0.0
    # Creating COLOR_1 can invalidate the previously held RNA attribute reference.
    color0 = plane.data.color_attributes["COLOR_0"]
    color0.data.foreach_set("color", np.tile((0.75, 1.0, 1.0, 0.0), len(color0.data)).ravel())
    check(close(plane.data.color_attributes["COLOR_0"].data[0].color, (0.75, 1.0, 1.0, 0.0)),
          "tint editing writes the actual COLOR_0 after layer initialization")
    palette = bpy.data.images.new("palette", 2, 1, alpha=True, float_buffer=True)
    palette.pixels.foreach_set((0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0))
    palette.update()
    mat.adm.vertex_tint_palette = palette
    bpy.context.view_layer.update()
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.8, 0.0, 0.0)),
          f"COLOR_0 tint index samples the nearest palette entry ({alb[8, 8, :3]})")
    # A 2x3 palette: only the top row (last in Blender's bottom-up pixels) is the palette.
    tall = bpy.data.images.new("tall_palette", 2, 3, alpha=True, float_buffer=True)
    tall.pixels.foreach_set((0.0, 1.0, 0.0, 1.0) * 4 + (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0))
    tall.update()
    mat.adm.vertex_tint_palette = tall
    bpy.context.view_layer.update()
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.0, 0.0, 0.2)),
          f"a multi-row palette samples only its top row ({alb[8, 8, :3]})")

    # 5. COLOR_0 produces exact dielectric and metallic F0 in the preview -------------------------
    f0_mat = bpy.data.materials.new("vertex_f0")
    plane.data.materials.clear()
    plane.data.materials.append(f0_mat)
    M.convert_to_adm_material(f0_mat)
    fallback = M.principled_of(f0_mat)
    fallback.inputs["Base Color"].default_value = (0.25, 0.5, 0.75, 1.0)
    fallback.inputs["Metallic"].default_value = 0.4
    fallback.inputs["IOR"].default_value = 1.5
    fallback.inputs["Specular IOR Level"].default_value = 0.5
    f0_attr = plane.data.color_attributes.get("COLOR_0")
    if f0_attr is None:
        f0_attr = plane.data.color_attributes.new(name="COLOR_0", type="FLOAT_COLOR", domain="CORNER")
    f0_attr.data.foreach_set("color", np.tile((0.0, 1.0, 0.8, 0.0), len(f0_attr.data)).ravel())
    color1_attr = plane.data.color_attributes.get("COLOR_1")
    if color1_attr is None:
        color1_attr = plane.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    color1_attr.data.foreach_set("color", np.tile((0.1, 0.2, 0.3, 0.4), len(color1_attr.data)).ravel())
    f0_mat.adm.vertex_controls_enabled = True
    f0_mat.adm.reflection_multiplier = 0.5
    f0_mat.adm.wetness_offset = 0.5
    SP.build(f0_mat)
    bpy.context.view_layer.update()
    dielectric = next(n for n in f0_mat.node_tree.nodes if n.name == "ADM Preview Dielectric F0")
    metal = next(n for n in f0_mat.node_tree.nodes if n.name == "ADM Preview Metallic F0")
    metal_f0 = bake_socket(plane, f0_mat, metal.inputs["Base Color"].links[0].from_socket)
    wetness = 0.5
    dielectric_base_f0 = ((1.5 - 1.0) / (1.5 + 1.0)) ** 2
    dielectric_reflectance = dielectric_base_f0 * 0.4
    dielectric_coat = water_f0 + (1.0 - water_f0) ** 2 * dielectric_reflectance
    expected_dielectric = dielectric_reflectance + (dielectric_coat - dielectric_reflectance) * wetness
    metal_base_f0 = (0.25 * 0.4, 0.5 * 0.4, 0.75 * 0.4)
    expected_metal = tuple(
        base + (water_f0 + (1.0 - water_f0) ** 2 * base - base) * wetness
        for base in metal_base_f0
    )
    check(close(metal_f0[8, 8, :3], expected_metal),
          f"COLOR_0 metallic F0 is reflectivity-scaled then water-coated ({metal_f0[8, 8, :3]})")
    dielectric_ior = bake_socket(plane, f0_mat, dielectric.inputs["IOR"].links[0].from_socket)
    measured_ior = float(dielectric_ior[8, 8, 0])
    measured_f0 = ((measured_ior - 1.0) / (measured_ior + 1.0)) ** 2
    check(abs(measured_f0 - expected_dielectric) < 0.002,
          f"COLOR_0 dielectric IOR encodes exact effective F0 ({measured_f0:.5f})")
    diffuse_before = bake(plane, f0_mat, "DIFFUSE")
    color1_attr.data.foreach_set("color", np.tile((0.9, 0.8, 0.7, 0.6), len(color1_attr.data)).ravel())
    bpy.context.view_layer.update()
    diffuse_after = bake(plane, f0_mat, "DIFFUSE")
    check(np.allclose(diffuse_before, diffuse_after, atol=1e-5, rtol=0.0),
          "reserved COLOR_1 values do not affect shader output")

    layered_mat = bpy.data.materials.new("vertex_control_layered")
    plane.data.materials.clear()
    plane.data.materials.append(layered_mat)
    M.convert_to_adm_material(layered_mat)
    layered_mat.adm.shader = "LAYERED"
    layered_mat.adm.vertex_controls_enabled = True
    M.refresh_shader_preview(layered_mat)
    active_output = next(n for n in layered_mat.node_tree.nodes
                         if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    surface = M._from(active_output.inputs["Surface"])
    check(surface is not None and surface.node.type == "MIX_SHADER",
          "layered preview wires vertex-controlled F0 output")

    # Verify live drivers and COLOR_1 data survive a real save/reopen.
    saved = bpy.data.materials.new("reopen_preview")
    saved.use_nodes = True
    plane.data.materials.clear()
    plane.data.materials.append(saved)
    saved.adm.shader_version = K.SHADER_PROFILE_V2
    set_param(saved, "color1_r_roughness", 0.2)
    set_param(saved, "color1_r_strength", 1.0)
    color1 = plane.data.color_attributes["COLOR_1"]
    color1.data.foreach_set("color", np.tile((0.0, 0.0, 0.0, 0.0), len(color1.data)).ravel())
    bsdf = preview_bsdf(saved, M)
    rough_before = bake_socket(plane, saved, bsdf.inputs["Roughness"].links[0].from_socket)[8, 8, 0]
    set_param(saved, "color1_r_roughness", 0.8)
    color1.data.foreach_set("color", np.tile((1.0, 0.0, 0.0, 0.0), len(color1.data)).ravel())
    plane.data.update()
    bsdf = preview_bsdf(saved, M)
    rough_changed = bake_socket(plane, saved, bsdf.inputs["Roughness"].links[0].from_socket)[8, 8, 0]
    check(abs(rough_before - rough_changed) > 0.1, "COLOR_1 and roughness edits affect preview")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "preview.blend")
        plane_name = plane.name
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        plane = bpy.data.objects[plane_name]
        saved = bpy.data.materials["reopen_preview"]
        bsdf = preview_bsdf(saved, M)
        rough_reopened = bake_socket(plane, saved, bsdf.inputs["Roughness"].links[0].from_socket)[8, 8, 0]
        check(close((rough_reopened,), (rough_changed,)), "COLOR_1 roughness preview survives save/reopen")

    adm_blender.unregister()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
