"""Blender headless test for ADM profile viewport previews (adm_blender/blender/shader_preview.py).

Builds every profile preview with all parameters overridden, checks the exported PBR fallback is
unaffected, and bakes Brick / Terrain with Cycles to verify the node math against the contracts.
"""
import os
import sys
import traceback

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FAILS = []
RES = 16


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
    elif isinstance(value, (tuple, list)):
        cur = list(v.value_vec)
        cur[:len(value)] = value
        v.value_vec = cur
    else:
        v.value_f = value


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
    from adm_blender.blender import materials as M
    from adm_blender.blender import shader_preview as SP
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter

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
