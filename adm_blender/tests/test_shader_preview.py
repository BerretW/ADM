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

    # 1. every builder with every parameter overridden ------------------------------------------
    for kind in sorted(SP.BUILDERS):
        mat = bpy.data.materials.new(f"prev_{kind}")
        plane.data.materials.clear()
        plane.data.materials.append(mat)
        M.convert_to_adm_material(mat)
        fallback = M.principled_of(mat)
        fallback.inputs["Base Color"].default_value = (0.3, 0.6, 0.9, 1.0)
        mat.adm.vertex_controls_enabled = True
        mat.adm.shader = kind
        key = mat.adm.shader_key()
        for prm in K.OFFICIAL_SHADERS[key]:
            if prm["type"] == "TEXTURE":
                set_param(mat, prm["name"], tex)
            elif prm["type"] == "F32":
                set_param(mat, prm["name"], float(prm.get("maximum", 1.0)) * 0.5)
            elif prm["type"] != "BOOL":
                set_param(mat, prm["name"], [0.5] * K.SHADER_NUMERIC_DIMS[prm["type"]])
        check(all(v.use for v in mat.adm.params), f"{kind}: editing values enables Override")
        out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        check(out is not None and M.is_preview_node(out), f"{kind}: preview output is active")
        check(M.principled_of(mat) == fallback, f"{kind}: exporter still sees the fallback BSDF")
        exporter = ModelExporter(bpy.context, root, ExportOptions())
        _data, report = exporter.export()
        check(report.ok, f"{kind}: export validates")
        if report.ok:
            m = report.doc["materials"][0]
            check(close(m["baseColorFactor"], (0.3, 0.6, 0.9, 1.0), 1e-5), f"{kind}: fallback base color exported")
            names = {p["name"] for p in K.OFFICIAL_SHADERS[key]}
            check(set(m.get("shaderParameters", {})) == names, f"{kind}: all overridden parameters exported")
        mat.adm.vertex_controls_enabled = False
        mat.adm.shader = "CORE"
        check(not any(M.is_preview_node(n) for n in mat.node_tree.nodes), f"{kind}: CORE removes preview nodes")

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
    color0.data.foreach_set("color", np.tile((0.75, 1.0, 1.0, 0.0), len(color0.data)).ravel())
    palette = bpy.data.images.new("palette", 2, 1, alpha=True, float_buffer=True)
    palette.pixels.foreach_set((0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0))
    palette.update()
    mat.adm.vertex_tint_palette = palette
    bpy.context.view_layer.update()
    alb = bake(plane, mat, "DIFFUSE")
    check(close(alb[8, 8, :3], (0.8, 0.0, 0.0)),
          f"COLOR_0 tint index samples the nearest palette entry ({alb[8, 8, :3]})")

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
