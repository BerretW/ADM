"""Headless Blender tests for the automatic LOD generator."""

import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import numpy as np
import adm_blender

FAILS = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        FAILS.append(message)


def coords(data):
    out = np.empty(len(data) * 3, dtype=np.float32)
    data.foreach_get("co", out)
    return out.reshape(-1, 3)


def screen_tris(obj, screen):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons
               if obj.material_slots[p.material_index].material == screen)


def cone(points):
    return 0.2 * np.maximum(0.0, 1.0 - np.linalg.norm(points[:, :2] + (1.0, 0.0), axis=1))


def main():
    from adm_blender.blender import materials
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.lod_gen import triangle_count
    from adm_blender.core import constants as K

    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    root = bpy.data.objects.new("Prop", None)
    root.adm.adm_type = "MODEL"
    bpy.context.scene.collection.objects.link(root)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=4)
    obj = bpy.context.object
    obj.name = "Terminal"
    obj.parent = root
    me = obj.data
    frame = bpy.data.materials.new("Frame")
    materials.convert_to_adm_material(frame)
    screen = bpy.data.materials.new("Screen")
    materials.convert_to_adm_material(screen)
    screen.adm.shader = "INTERACTIVE"
    me.materials.append(frame)
    me.materials.append(screen)
    screen_faces = {p.index for p in me.polygons if p.center.x > 1.0 and p.center.y > 1.0}
    for poly in me.polygons:
        poly.material_index = 1 if poly.index in screen_faces else 0
        poly.select = poly.index in screen_faces
    color = me.color_attributes.new("COLOR_0", "FLOAT_COLOR", "CORNER")
    for item in color.data:
        item.color = (0.25, 0.5, 0.75, 0.1)
    obj.adm.interactive_surface_id = "main_display"
    obj.adm.interactive_aspect_ratio = 1.0
    check(bpy.ops.adm.interactive_surface_assign_faces() == {"FINISHED"}, "screen faces get a surface ID")

    obj.shape_key_add(name="Basis")
    obj.vertex_groups.new(name="Spine").add([v.index for v in me.vertices], 0.75, "REPLACE")
    key_a = obj.shape_key_add(name="Smile")
    base = coords(me.vertices)
    displaced = base.copy()
    displaced[:, 2] += cone(base)
    key_a.data.foreach_set("co", displaced.ravel())
    key_b = obj.shape_key_add(name="SmileUp")
    key_b.relative_key = key_a
    shifted = displaced.copy()
    shifted[:, 2] += 0.1
    key_b.data.foreach_set("co", shifted.ravel())

    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    check(bpy.ops.adm.generate_lods() == {"FINISHED"}, "generate four LOD levels")
    group = obj.parent
    levels = sorted(((lv.min_distance, lv.object) for lv in group.adm.lod_levels), key=lambda x: x[0])
    check(group.adm.adm_type == "LOD_GROUP" and group.parent == root
          and [d for d, _ in levels] == [0.0, 15.0, 40.0, 100.0] and levels[0][1] == obj,
          "LOD group under the model root with LOD0 at 0 m and 15/40/100 m switches")
    lods = [o for _, o in levels]
    tris = [triangle_count(o.data) for o in lods]
    locked = screen_tris(obj, screen)
    free = tris[0] - locked
    check(all(abs((t - locked) - r * free) <= 0.02 * free for t, r in zip(tris[1:], (0.5, 0.25, 0.1))),
          f"non-screen triangles follow 0.5/0.25/0.1 ratios: {tris}")
    check(all(screen_tris(o, screen) == locked for o in lods), "interactive screen is never decimated")
    check(all(set(p.material_index for p in o.data.polygons) == {0, 1} for o in lods),
          "both materials survive on every level")
    ok_ids = True
    for o in lods:
        ids = o.data.attributes["adm_interactive_surface_id"]
        for p in o.data.polygons:
            ok_ids &= (ids.data[p.index].value == b"main_display") == (p.material_index == 1)
    check(ok_ids, "surface IDs follow screen faces on every level")
    check(all("COLOR_0" in o.data.color_attributes for o in lods), "vertex control layers survive")
    check(all([g.name for g in o.vertex_groups] == ["Spine"] and
              all(len(v.groups) == 1 and abs(v.groups[0].weight - 0.75) < 1e-5 for v in o.data.vertices)
              for o in lods[1:]), "skin vertex groups and weights survive")
    check(all(not any(a.name.startswith("_adm_lod") for a in o.data.attributes) and
              "_adm_lod_decimate" not in o.vertex_groups for o in lods[1:]),
          "temporary decimation data is removed")
    names = [[kb.name for kb in o.data.shape_keys.key_blocks] if o.data.shape_keys else [] for o in lods]
    check(names[1] == names[2] == ["Basis", "Smile", "SmileUp"] and names[3] == [],
          "shape keys transferred to LOD1-LOD2 and dropped on LOD3")
    blocks = lods[1].data.shape_keys.key_blocks
    lod_base = coords(blocks["Basis"].data)
    smile = coords(blocks["Smile"].data) - lod_base
    up = coords(blocks["SmileUp"].data) - coords(blocks["Smile"].data)
    check(blocks["SmileUp"].relative_key.name == "Smile", "relative shape-key chain is preserved")
    check(np.abs(smile[:, 2] - cone(lod_base)).max() < 0.03 and np.allclose(smile[:, :2], 0, atol=1e-6),
          "morph deltas follow the decimated surface")
    check(np.allclose(up, (0, 0, 0.1), atol=1e-5), "relative morph delta is exact")
    check(all(o.adm.lod_source == obj and o.hide_get() for o in lods[1:]) and not obj.hide_get(),
          "generated levels are tagged and hidden for preview")

    data, report = ModelExporter(bpy.context, root, ExportOptions()).export()
    doc = report.doc
    check(report.ok, "model with generated LODs validates: " +
          "; ".join(f"{i.code} {i.message}" for i in report.issues if i.severity == "error"))
    check(len(doc.get("lodGroups", [])) == 1 and
          [lv["minDistance"] for lv in doc["lodGroups"][0]["levels"]] == [0.0, 15.0, 40.0, 100.0],
          "lodGroups exported with four levels")
    surfaces = doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]
    check(len(surfaces) == 1 and len(surfaces[0]["bindings"]) == 4,
          "one surface ID bound on all four LOD nodes")
    morph_meshes = [m.get("targetNames", []) for m in doc["meshes"]]
    check(sorted(len(n) for n in morph_meshes) == [0, 2, 2, 2], "three exported meshes carry two morph targets")

    bpy.context.view_layer.objects.active = group
    group.select_set(True)
    check(bpy.ops.adm.generate_lods(levels=3) == {"FINISHED"}, "regenerate from the LOD group")
    check(len(group.adm.lod_levels) == 3 and not any(o.name.endswith("_LOD3") for o in bpy.data.objects)
          and sum(1 for o in bpy.data.objects if o.adm.lod_source == obj) == 2,
          "regeneration replaces earlier levels without duplicates")
    try:
        rejected = bpy.ops.adm.generate_lods(ratios=(0.5, 0.6, 0.1, 0.05, 0.02)) == {"CANCELLED"}
    except RuntimeError as exc:
        rejected = "strictly decreasing" in str(exc)
    check(rejected, "non-decreasing ratios are rejected")
    check(len(group.adm.lod_levels) == 3, "rejected settings keep the existing levels")
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
