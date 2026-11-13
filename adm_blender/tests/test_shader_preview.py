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
