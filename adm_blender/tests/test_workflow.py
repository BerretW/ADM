"""Blender background test of the full authoring workflow (create -> author -> export -> import -> re-export).

Run:  blender -b --factory-startup --python adm_blender/tests/test_workflow.py
"""

import os
import importlib.util
import sys
import tempfile
import traceback

import bmesh

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

import bpy  # noqa: E402
from mathutils import Euler, Vector  # noqa: E402

import adm_blender  # noqa: E402

FAILS = []

BONES = [  # name, parent, head, tail
    ("mixamorig:Hips", None, (0, 0, 1.0), (0, 0, 1.1)),
    ("mixamorig:Spine", "mixamorig:Hips", (0, 0, 1.1), (0, 0, 1.25)),
    ("mixamorig:Spine1", "mixamorig:Spine", (0, 0, 1.25), (0, 0, 1.4)),
    ("mixamorig:Neck", "mixamorig:Spine1", (0, 0, 1.5), (0, 0, 1.6)),
    ("mixamorig:Head", "mixamorig:Neck", (0, 0, 1.6), (0, 0, 1.8)),
]
# ADM reference pose: forward -Z, +X = character's right  ->  in Blender the character faces +Y with its
# right side on +X (Blender's usual -Y facing characters must be rotated 180 deg, see REFERENCE_FACING).
for side, s in (("Left", -1), ("Right", 1)):
    BONES += [
        (f"mixamorig:{side}Arm", "mixamorig:Spine1", (0.2 * s, 0, 1.45), (0.45 * s, 0, 1.45)),
        (f"mixamorig:{side}ForeArm", f"mixamorig:{side}Arm", (0.45 * s, 0, 1.45), (0.7 * s, 0, 1.45)),
        (f"mixamorig:{side}Hand", f"mixamorig:{side}ForeArm", (0.7 * s, 0, 1.45), (0.8 * s, 0, 1.45)),
        (f"mixamorig:{side}UpLeg", "mixamorig:Hips", (0.1 * s, 0, 0.95), (0.1 * s, 0, 0.5)),
        (f"mixamorig:{side}Leg", f"mixamorig:{side}UpLeg", (0.1 * s, 0, 0.5), (0.1 * s, 0, 0.1)),
        (f"mixamorig:{side}Foot", f"mixamorig:{side}Leg", (0.1 * s, 0, 0.1), (0.1 * s, 0.15, 0.0)),
    ]


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def errs(rep):
    return [] if rep is None or rep.ok else [str(e) for e in rep.errors[:6]]


def select(*objs, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def string_attr_value(item):
    value = item.value
    return value.decode("utf-8") if isinstance(value, bytes) else value


def test_material_interpolation():
    import numpy as np
    from bpy_extras import anim_utils

    from adm_blender.blender.import_anim import _fill

    results = {}
    for mode in ("STEP", "LINEAR", "CUBICSPLINE"):
        action = bpy.data.actions.new(f"interpolation_{mode}")
        slot = action.slots.new(id_type="MATERIAL", name=f"interpolation_{mode}")
        channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        curve = channelbag.fcurves.new(data_path="adm.wetness_offset", index=0)
        tangents = np.array([1.0, 1.0]) if mode == "CUBICSPLINE" else None
        _fill(curve, np.array([1.0, 25.0]), np.array([0.0, 1.0]), tangents, tangents, mode, 24.0)
        results[mode] = (curve.evaluate(1.0), curve.evaluate(13.0), curve.evaluate(25.0))
        bpy.data.actions.remove(action)
    check(results["STEP"] == (0.0, 0.0, 1.0), f"STEP material interpolation {results['STEP']}")
    check(all(abs(a - b) < 1e-5 for a, b in zip(results["LINEAR"], (0.0, 0.5, 1.0))),
          f"LINEAR material interpolation {results['LINEAR']}")
    check(all(abs(a - b) < 1e-5 for a, b in zip(results["CUBICSPLINE"], (0.0, 0.5, 1.0))),
          f"CUBICSPLINE material interpolation {results['CUBICSPLINE']}")


def test_vertex_color_authoring(tmp):
    import numpy as np
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.blender.vertex_colors import (
        DEFAULTS, VertexColorError, ensure_layers, palette_colors, palette_position, sync_control_meshes)
    from adm_blender.core import constants as K
    from adm_blender.core.buffers import read_accessor
    from adm_blender.core.container import read_container, write_container

    def close(actual, expected):
        return np.allclose(actual, expected, atol=1e-6)

    def layer_values(mesh, name):
        values = np.empty((len(mesh.color_attributes[name].data), 4), dtype=np.float32)
        mesh.color_attributes[name].data.foreach_get("color", values.ravel())
        return values

    print("== vertex color authoring")
    mesh = bpy.data.meshes.new("ControlMesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                      (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)], [],
                     [(0, 1, 2, 3), (4, 5, 6, 7)])
    mesh.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new("ControlObject", mesh)
    bpy.context.scene.collection.objects.link(obj)
    select(obj)
    bpy.context.view_layer.update()
    sync_control_meshes()
    check(not mesh.color_attributes, "ordinary new meshes remain untouched")
    mat = bpy.data.materials.new("TintControls")
    mat.use_nodes = True
    mat.adm.vertex_controls_enabled = True
    mesh.materials.append(mat)
    bpy.context.view_layer.update()
    sync_control_meshes()
    check(not mesh.color_attributes,
          "meshes outside an ADM model stay untouched even with an enabled material")
    loose_mesh = bpy.data.meshes.new("LooseMesh")
    loose_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
    loose_mesh.materials.append(mat)
    loose = bpy.data.objects.new("LooseObject", loose_mesh)
    bpy.context.scene.collection.objects.link(loose)
    root = bpy.data.objects.new("VertexColorRoot", None)
    root.adm.adm_type = "MODEL"
    bpy.context.scene.collection.objects.link(root)
    obj.parent = root
    bpy.context.view_layer.update()
    check(bpy.app.timers.is_registered(sync_control_meshes),
          "adding a mesh to an ADM model queues initialization")
    sync_control_meshes()
    check(not loose_mesh.color_attributes, "unrelated non-ADM meshes sharing the material stay untouched")
    select(loose)
    bpy.ops.adm.convert_materials()
    check(all(close(layer_values(loose_mesh, name), default) for name, default in DEFAULTS.items()),
          "explicit conversion to ADM initializes the selected mesh")
    select(obj)
    bpy.data.objects.remove(loose)
    bpy.data.meshes.remove(loose_mesh)
    check(all(close(layer_values(mesh, name), default) for name, default in DEFAULTS.items()),
          "new control mesh gets exact neutral defaults, including dry alpha")
    check(any(node.bl_idname == "ShaderNodeVertexColor" and node.layer_name == "COLOR_0"
              for node in mat.node_tree.nodes), "new mesh preview samples its actual color attribute")
    authored = (0.2, 0.3, 0.4, 0.5)
    for name in DEFAULTS:
        mesh.color_attributes[name].data.foreach_set("color", np.tile(authored, (8, 1)).ravel())
    ensure_layers(mesh)
    check(all(close(layer_values(mesh, name), authored) for name in DEFAULTS),
          "repeated initialization preserves both authored layers")
    wm = bpy.context.window_manager.adm
    wm.vertex_color_scope = "SELECTED"
    wm.vertex_color_channel = "G"
    wm.vertex_color_values = (0.9, 0.7, 0.8, 0.1)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    for face in bm.faces:
        face.select_set(face.index == 0)
    bmesh.update_edit_mesh(mesh)
    check(bpy.ops.adm.vertex_colors(action="APPLY") == {"FINISHED"},
          "channel editing works with live Edit Mode face selection")
    layer = bm.loops.layers.float_color["COLOR_0"]
    check(all(close(loop[layer], (0.2, 0.7, 0.4, 0.5)) for loop in bm.faces[0].loops)
          and all(close(loop[layer], authored) for loop in bm.faces[1].loops),
          "live Edit Mode writes only the chosen channel on selected corners")
    check(obj.mode == "EDIT", "channel editing preserves Edit Mode")
    check(bpy.ops.adm.vertex_colors(action="RESET") == {"FINISHED"}, "reset selected control faces")
    bpy.ops.object.mode_set(mode="OBJECT")
    check(all(close(layer_values(mesh, name)[:4], default)
              and close(layer_values(mesh, name)[4:], authored) for name, default in DEFAULTS.items()),
          "reset affects only selected corners and restores both exact defaults")
    wm.vertex_color_scope = "ALL"
    wm.vertex_color_channel = "G"
    check(bpy.ops.adm.vertex_colors(action="APPLY") == {"FINISHED"}, "apply one channel in Object Mode")
    check(close(layer_values(mesh, "COLOR_0")[:4], (0, 0.7, 1, 0))
          and close(layer_values(mesh, "COLOR_0")[4:], (0.2, 0.7, 0.4, 0.5)),
          "single-channel writes preserve R, B and A")

    palette = bpy.data.images.new("FourTintEntries", 4, 3, alpha=True, float_buffer=True)
    palette.pixels.foreach_set((0.9, 0.9, 0.9, 1) * 8 + (0.1, 0.2, 0.3, 1, 0.3, 0.2, 0.1, 1,
                                                           0.2, 0.8, 0.4, 1, 0.8, 0.2, 0.4, 1))
    palette.update()
    mat.adm.vertex_tint_palette = palette
    check(len(mat.adm.tint_palette_entries) == 4
          and close(mat.adm.tint_palette_entries[2].color, (0.2, 0.8, 0.4, 1)),
          "palette picker shows the actual authored float swatches")
    mat.adm.active_tint_entry = 2
    mat.adm.tint_offset = 0.25
    other = bpy.data.materials.new("OtherMaterial")
    mesh.materials.append(other)
    mesh.polygons[1].material_index = 1
    before = layer_values(mesh, "COLOR_0").copy()
    bpy.ops.object.mode_set(mode="EDIT")
    wm.vertex_color_scope = "SELECTED"
    check(bpy.ops.adm.vertex_colors(action="TINT") == {"FINISHED"}, "apply selected palette swatch")
    bpy.ops.object.mode_set(mode="OBJECT")
    after = layer_values(mesh, "COLOR_0")
    check(close(after[:4, 0], 0.5625) and close(after[:4, 1:], before[:4, 1:])
          and close(after[4:], before[4:]), "palette stores the offset-aware index only in active-material R")
    mesh.materials.append(mat)
    mesh.polygons[1].material_index = 2
    wm.vertex_color_scope = "ALL"
    mat.adm.active_tint_entry = 1
    bpy.ops.adm.vertex_colors(action="TINT")
    check(close(layer_values(mesh, "COLOR_0")[:, 0], 0.3125)
          and close(layer_values(mesh, "COLOR_0")[:, 1:], after[:, 1:]),
          "palette matches all slots using the active material, not just one slot index")
    mesh.polygons[1].material_index = 1
    mat.adm.active_tint_entry = 2
    mesh.color_attributes["COLOR_0"].data.foreach_set("color", after.ravel())
    try:
        palette_position(0, 4, 2.0)
    except VertexColorError:
        check(True, "unreachable palette entry is rejected instead of choosing another color")
    else:
        check(False, "unreachable palette entry is rejected instead of choosing another color")
    tall = bpy.data.images.new("TallPalette", 2, 5, alpha=True, float_buffer=True)
    tall.pixels.foreach_set((0.9, 0.9, 0.9, 1.0) * 8 + (0.1, 0.2, 0.3, 1.0, 0.4, 0.5, 0.6, 1.0))
    tall.update()
    check(close(palette_colors(tall), ((0.1, 0.2, 0.3, 1.0), (0.4, 0.5, 0.6, 1.0))),
          "5 px high palette reads only its first (top) row")
    bad_palette = bpy.data.images.new("TooTall", 2, 6, alpha=True)
    try:
        palette_colors(bad_palette)
    except VertexColorError:
        check(True, "palettes higher than 5 px are rejected")
    else:
        check(False, "palettes higher than 5 px are rejected")

    options = ExportOptions(selected_only=True, vertex_controls=True)
    data, report = ModelExporter(bpy.context, None, options).export()
    check(report.ok, "authored vertex controls and palette export as a valid ADM")
    path = os.path.join(tmp, "vertex_controls.adm")
    with open(path, "wb") as stream:
        stream.write(data)
    importer = ModelImporter(bpy.context, path, ImportOptions(weld=False))
    root = importer.run()
    _, roundtrip = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True)).export()
    palette_primitive = next(p for m in roundtrip.doc["meshes"] for p in m["primitives"]
                             if "tintPalette" in roundtrip.doc["materials"][p["material"]]
                             .get("extensions", {}).get(K.VERTEX_CONTROL_EXT, {}))
    values = read_accessor(roundtrip.doc, roundtrip.bin, palette_primitive["attributes"]["COLOR_0"])
    check(values and close(values, (0.5625, 0.7, 1.0, 0.0)),
          "export/import/re-export preserves tint index and the other control channels")
    imported_mat = next(m for m in importer.materials if m.adm.vertex_tint_palette is not None)
    check(imported_mat.adm.vertex_tint_palette.size[:] == (4, 3)
          and len(imported_mat.adm.tint_palette_entries) == 4
          and np.allclose(imported_mat.adm.tint_palette_entries[2].color, (0.2, 0.8, 0.4, 1), atol=0.01),
          "import rebuilds the top-row swatches of a multi-row tint palette")
    doc, chunks = read_container(data, K.ADM_MAGIC)
    for primitive in doc["meshes"][0]["primitives"]:
        for name in DEFAULTS:
            primitive["attributes"].pop(name)
    with open(path, "wb") as stream:
        stream.write(write_container(K.ADM_MAGIC, doc, chunks))
    root_missing = ModelImporter(bpy.context, path, ImportOptions()).run()
    imported_mesh = next(child.data for child in root_missing.children if child.type == "MESH")
    check(all(close(layer_values(imported_mesh, name), default) for name, default in DEFAULTS.items()),
          "import of omitted optional controls materializes the specified defaults")

    select(obj)
    for name in DEFAULTS:
        mesh.color_attributes.remove(mesh.color_attributes[name])
    _, defaults_export = ModelExporter(bpy.context, None, options).export()
    check(all(close(read_accessor(defaults_export.doc, defaults_export.bin, p["attributes"][name]), default)
              for p in defaults_export.doc["meshes"][0]["primitives"] for name, default in DEFAULTS.items()),
          "export writes exact defaults even if a source mesh has no control layers")
    check(not mesh.color_attributes, "export default initialization does not modify the source mesh")
    invalid = mesh.attributes.new("COLOR_0", "INT", "POINT")
    try:
        ModelExporter(bpy.context, None, options).export()
    except ExportError as exc:
        check("COLOR_0 must be" in str(exc), "export diagnoses a conflicting non-color attribute")
    else:
        check(False, "export diagnoses a conflicting non-color attribute")
    mesh.attributes.remove(invalid)
    ordinary_data, _ = ModelExporter(bpy.context, None, ExportOptions(selected_only=True)).export()
    with open(path, "wb") as stream:
        stream.write(ordinary_data)
    ordinary_root = ModelImporter(bpy.context, path, ImportOptions()).run()
    check(all(not child.data.color_attributes for child in ordinary_root.children if child.type == "MESH"),
          "ordinary ADM import without controls does not add control layers")
    select(obj)

    for edit in (False, True):
        for name in DEFAULTS:
            attr = mesh.color_attributes.get(name)
            if attr is not None:
                mesh.color_attributes.remove(attr)
        attr = mesh.color_attributes.new("COLOR_0", "BYTE_COLOR", "POINT")
        for value in attr.data:
            value.color = authored
        expected = np.array([value.color[:] for value in attr.data])
        if edit:
            bpy.ops.object.mode_set(mode="EDIT")
        ensure_layers(mesh)
        if edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        check(mesh.color_attributes["COLOR_0"].domain == "CORNER"
              and mesh.color_attributes["COLOR_0"].data_type == "FLOAT_COLOR"
              and close(layer_values(mesh, "COLOR_0"), expected),
              f"BYTE_COLOR/POINT conversion preserves linear values in {'Edit' if edit else 'Object'} Mode")

    ordinary = mesh.color_attributes.new("Color", "FLOAT_COLOR", "CORNER")
    ordinary.data.foreach_set("color", np.tile((0.8, 0.4, 0.2, 1), (8, 1)).ravel())
    mat.adm.vertex_controls_enabled = False
    check(bpy.ops.adm.convert_materials() == {"FINISHED"} and mat.adm.vertex_controls_enabled,
          "Convert Materials to ADM enables control-layer authoring")
    check(close(layer_values(mesh, "Color"), (0.8, 0.4, 0.2, 1)),
          "conversion preserves unrelated ordinary color layers")


def build_rig():
    arm_data = bpy.data.armatures.new("Rig")
    arm = bpy.data.objects.new("Rig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    select(arm)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent, h, t in BONES:
        eb = arm_data.edit_bones.new(name)
        eb.head, eb.tail = h, t
        if parent:
            eb.parent = arm_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def build_body(arm):
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 0, 1.2))
    body = bpy.context.active_object
    body.name = "Body"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    vg = body.vertex_groups.new(name="mixamorig:Spine")
    vg.add(list(range(len(body.data.vertices))), 1.0, "REPLACE")
    vg2 = body.vertex_groups.new(name="mixamorig:Spine1")
    vg2.add([0, 1], 0.5, "REPLACE")
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    body.parent = arm
    body.shape_key_add(name="Basis")
    sk = body.shape_key_add(name="smile")
    for v in sk.data:
        v.co += Vector((0, 0, 0.02))
    body.data.uv_layers.active.name = "UVMap"
    color0 = body.data.color_attributes.new(name="COLOR_0", type="FLOAT_COLOR", domain="CORNER")
    for color in color0.data:
        color.color = (0.25, 0.75, 0.5, 0.4)
    color1 = body.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    for color in color1.data:
        color.color = (0.1, 0.2, 0.3, 0.4)
    # textured material
    img = bpy.data.images.new("albedo", 8, 8, alpha=True)
    img.pixels = [0.5] * (8 * 8 * 4)
    img.pack()
    mat = bpy.data.materials.new("Skin")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.4
    body.data.materials.append(mat)
    return body


def test_edit_mode_export(tmp):
    from unittest.mock import patch

    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
    from adm_blender.core.buffers import read_accessor
    from adm_blender.core.validate import validate_file

    bpy.ops.wm.read_homefile(use_empty=True)
    objects = []
    for name in ("EditShape", "EditModifier"):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = name
        obj.data.name = name + "Mesh"
        obj.data.uv_layers.new(name="UV1")
        objects.append(obj)
    shape, modified = objects
    shape.shape_key_add(name="Basis")
    key = shape.shape_key_add(name="Morph")
    key.data[0].co.x += 0.25
    modifier = modified.modifiers.new("Subdivision", "SUBSURF")
    modifier.subdivision_type = "SIMPLE"
    modifier.levels = 1
    select(*objects, active=shape)
    bpy.ops.object.mode_set(mode="EDIT")
    for obj in objects:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].co.x -= 0.25
        uv0 = bm.loops.layers.uv.get("UVMap")
        uv1 = bm.loops.layers.uv.get("UV1")
        for face in bm.faces:
            for loop in face.loops:
                loop[uv0].uv = (0.25, 0.75)
                loop[uv1].uv = (0.6, 0.3)
        bmesh.update_edit_mesh(obj.data)

    mesh_count, key_count = len(bpy.data.meshes), len(bpy.data.shape_keys)
    try:
        for apply in (False, True):
            exporter = ModelExporter(bpy.context, None, ExportOptions(selected_only=True, apply_modifiers=apply))
            _data, report = exporter.export()
            check(report.ok, f"edit-mode export valid (apply modifiers={apply}): {errs(report)}")
            meshes = {mesh["name"]: mesh for mesh in report.doc["meshes"]}
            for obj in objects:
                mesh = meshes[obj.data.name]
                primitive = mesh["primitives"][0]
                attrs = primitive["attributes"]
                for semantic, expected in (("TEXCOORD_0", (0.25, 0.25)), ("TEXCOORD_1", (0.6, 0.7))):
                    values = read_accessor(report.doc, report.bin, attrs[semantic])
                    check(values and all(all(abs(a - b) < 1e-5 for a, b in zip(value, expected))
                                         for value in values),
                          f"{obj.name} current edit-mode {semantic} exported (apply modifiers={apply})")
                positions = read_accessor(report.doc, report.bin, attrs["POSITION"])
                check(any(abs(p[0] + 1.25) < 1e-5 for p in positions),
                      f"{obj.name} current edit-mode geometry exported (apply modifiers={apply})")
                triangles = len(read_accessor(report.doc, report.bin, primitive["indices"])) // 3
                expected_triangles = 48 if obj == modified and apply else 12
                check(triangles == expected_triangles,
                      f"{obj.name} modifier setting preserves topology: {triangles} triangles")
            shape_mesh = meshes[shape.data.name]
            check(shape_mesh.get("targetNames") == ["Morph"], "edit-mode export retains shape key")
            delta_index = shape_mesh["primitives"][0]["targets"][0]["POSITION"]
            deltas = read_accessor(report.doc, report.bin, delta_index)
            check(any(abs(v[0] - 0.25) < 1e-5 for v in deltas), "edit-mode shape-key delta preserved")
            check(all(obj.mode == "EDIT" for obj in objects), "export preserves multi-object Edit Mode")
            check(len(bpy.data.meshes) == mesh_count and len(bpy.data.shape_keys) == key_count,
                  "export releases temporary mesh and shape-key datablocks")

        with patch.object(ModelExporter, "_build_mesh", side_effect=ExportError("forced export failure")):
            try:
                ModelExporter(bpy.context, None, ExportOptions(selected_only=True, apply_modifiers=False)).export()
            except ExportError as exc:
                check(str(exc) == "forced export failure", "edit-mode export surfaces failures")
            else:
                check(False, "edit-mode export must surface failures")
        check(all(obj.mode == "EDIT" for obj in objects)
              and len(bpy.data.meshes) == mesh_count and len(bpy.data.shape_keys) == key_count,
              "failed edit-mode export preserves mode and releases temporary datablocks")

        path = os.path.join(tmp, "edited.adm")
        result = bpy.ops.export_scene.adm(filepath=path, scope="SELECTED", apply_modifiers=False)
        check(result == {"FINISHED"} and validate_file(path).ok, "file export operator works in Edit Mode")
        check(all(obj.mode == "EDIT" for obj in objects), "file export operator preserves Edit Mode")
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def main(tmp):
    adm_blender.register()
    from adm_blender.blender import material_anim as MA
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter, export_model
    from adm_blender.blender.export_anim import AnimExporter, channelbag_fcurves
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.blender.import_anim import AnimImportOptions, import_library
    from adm_blender.core.buffers import read_accessor
    from adm_blender.core import constants as K
    from adm_blender.core.validate import material_binding_issues, validate_adm_resolved, validate_file
    spec = importlib.util.spec_from_file_location("adm_reference_container",
                                                  os.path.join(REPO, "adm-standard", "tools", "container.py"))
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)

    bpy.ops.wm.read_homefile(use_empty=True)
    from adm_blender.blender.operators import ensure_role_names
    ensure_role_names()
    test_vertex_color_authoring(tmp)
    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    sc = bpy.context.scene
    test_material_interpolation()

    print("== authoring")
    arm = build_rig()
    body = build_body(arm)
    body.data.materials[0].adm.vertex_controls_enabled = True
    select(arm, body, active=arm)
    check(bpy.ops.adm.create_model_root(name="Hero") == {"FINISHED"}, "create_model_root")
    root = bpy.data.objects["Hero"]
    check(arm.parent == root and body.parent == arm, "hierarchy")
    select(arm)
    arm.data.adm.export_profile = True
    check(bpy.ops.adm.auto_map_roles() == {"FINISHED"}, "auto_map_roles")
    roles = {b.adm.role for b in arm.data.bones if b.adm.role}
    check({"hips", "spine", "chest", "head", "leftUpperArm", "rightFoot"} <= roles, f"roles {sorted(roles)}")

    select(body)
    check(bpy.ops.adm.create_collider(shape="CAPSULE", fit=True) == {"FINISHED"}, "create_collider")
    collider = bpy.context.active_object
    physical = root.adm.physical_materials.add()
    physical.name, physical.friction, physical.restitution = "cloth", 0.6, 0.1
    physical = root.adm.physical_materials.add()
    physical.name, physical.profile = "stone", "adm.phys.stone.v1"
    collider.adm.physical_material = "cloth"
    collider_world = collider.matrix_world.copy()
    collider.parent, collider.parent_type, collider.parent_bone = arm, "BONE", "mixamorig:Hips"
    collider.matrix_world = collider_world

    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(2, 0, 0.5))
    mesh_collider = bpy.context.active_object
    mesh_collider.name = "MeshCollider"
    mesh_collider.parent = root
    mesh_collider.adm.adm_type = "COLLIDER"
    mesh_collider.adm["collider_shape"] = 3
    mesh_collider.adm.physical_material = "stone"
    select(mesh_collider)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    edit_mesh = bmesh.from_edit_mesh(mesh_collider.data)
    edit_mesh.faces.ensure_lookup_table()
    edit_mesh.faces[0].select_set(True)
    bmesh.update_edit_mesh(mesh_collider.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    check(mesh_collider.data.polygons[0].select, "face selection survives Edit Mode")
    check(bpy.ops.adm.physical_material_assign_faces() == {"FINISHED"}, "assign physical material to selected face")
    face_attr = mesh_collider.data.attributes.get("adm_physical_material_id")
    check(face_attr is not None and string_attr_value(face_attr.data[0]) == "stone",
          f"FACE string attribute stores stable ID ({face_attr.data[0].value!r})")
    mesh_collider.data.polygons[0].select = False
    mesh_collider.adm.physical_material = "cloth"

    hitbox = root.adm.hitboxes.add()
    hitbox.name, hitbox.collider, hitbox.object, hitbox.role = "torso", collider, arm, "torso"
    hitbox.bone = "mixamorig:Hips"
    select(arm)
    check(bpy.ops.adm.create_attachment(attachment_name="prop.socket.back") == {"FINISHED"}, "create_attachment")
    component = root.adm.model_components.add()
    component.name, component.role = "back.part", "custom.back"
    component.object, component.socket = arm, "prop.socket.back"
    component.bone = "mixamorig:Hips"

    # LOD group of two props with a custom shader material
    sd = sc.adm_anim.shaders.add()
    sd.shader_id, sd.version, sd.description = "studio.paint", "1.0.0", "Worn paint"
    p = sd.params.add()
    p.name, p.type, p.description, p.animatable = "wear", "F32", "Paint wear amount", True
    p.use_minimum, p.use_maximum = True, True
    p.minimum[0], p.maximum[0] = 0.0, 1.0
    p = sd.params.add()
    p.name, p.type, p.description, p.animatable = "tint", "VEC3", "Paint tint", True
    p.default_vec = (1, 1, 1, 0)
    p = sd.params.add()
    p.name, p.type, p.description = "glossy", "BOOL", "Clear coat"
    check(sd.name == "studio.paint@1.0.0", f"shader def name {sd.name!r}")
    paint = bpy.data.materials.new("Paint")
    paint.use_nodes = True
    paint.adm.shader = "CUSTOM"
    paint.adm.custom_shader = sd.name
    lods = []
    for i, size in enumerate((0.3, 0.2)):
        bpy.ops.mesh.primitive_cube_add(size=size, location=(1, 0, 0.5))
        o = bpy.context.active_object
        o.name = f"Crate_LOD{i}"
        o.data.materials.append(paint)
        o.parent = root
        lods.append(o)
    select(*lods, active=lods[0])
    check(bpy.ops.adm.create_lod_group() == {"FINISHED"}, "create_lod_group")
    select(lods[0])
    check(bpy.ops.adm.material_sync_params() == {"FINISHED"}, "material_sync_params")
    check([v.name for v in paint.adm.params] == ["wear", "tint", "glossy"], "params synced")
    check(bpy.ops.adm.material_auto_animation_id() == {"FINISHED"} and paint.adm.animation_id == "paint",
          f"animation id {paint.adm.animation_id!r}")
    paint.adm.params["glossy"].use = True
    paint.adm.params["glossy"].value_bool = True
    paint.adm.vertex_controls_enabled = True
    paint.adm.tint_offset = 0.25
    paint.adm.normal_multiplier = 0.75
    paint.adm.reflection_multiplier = 1.5

    print("== model export")
    exp = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True))
    data, rep = exp.export()
    print("   notes:", exp.warnings)
    check(rep.ok, f"model valid {errs(rep)}")
    doc = rep.doc
    check(data[8:12] == (64).to_bytes(4, "little"), "Draft 0.4 native header")
    check(all("chunkId" in view for view in doc["bufferViews"]), "chunk-addressed buffer views")
    check(doc["physicalMaterials"][0]["id"] == "cloth", "physical material exported")
    physical_primitive = next(
        p for m in doc["meshes"] for p in m["primitives"]
        if K.PHYSICAL_SURFACES_EXT in p.get("extensions", {})
    )
    face_ids = physical_primitive["extensions"][K.PHYSICAL_SURFACES_EXT]["faceMaterials"]
    check(len(face_ids) == 12 and face_ids.count("stone") == 2 and face_ids.count("cloth") == 10,
          f"per-triangle physical surfaces {face_ids}")
    check(doc["modelComponents"][0]["id"] == "back.part", "component exported")
    check(doc["hitboxes"][0]["id"] == "torso", "hitbox exported")
    check(any(d["id"] == "studio.paint" for d in doc.get("shaderDefinitions", [])), "shader definition embedded")
    pm = next(m for m in doc["materials"] if m["name"] == "Paint")
    paint_vertex = pm["extensions"][K.VERTEX_CONTROL_EXT]
    check(paint_vertex["parameters"] == {
        "tintOffset": 0.25,
        "normalMultiplier": 0.75,
        "reflectionMultiplier": 1.5,
        "wetnessOffset": 0.0,
    }, "vertex-control parameters exported")
    check(all(field in pm for field in ("baseColorFactor", "metallicFactor", "roughnessFactor",
                                       "emissiveFactor", "alphaMode")), "explicit non-core PBR fallback")
    check(pm.get("shaderParameters") == {"glossy": True} and pm.get("animationId") == "paint",
          f"paint material {pm}")
    body_primitive = next(p for m in doc["meshes"] if m["name"] == body.data.name for p in m["primitives"])
    check("COLOR_1" in body_primitive["attributes"],
          "reserved COLOR_1 exported under the required vertex-control extension")
    color1_values = read_accessor(rep.doc, rep.bin, body_primitive["attributes"]["COLOR_1"])
    check(color1_values and all(all(abs(actual - expected) < 1e-6
                                    for actual, expected in zip(value, (0.1, 0.2, 0.3, 0.4)))
                                for value in color1_values),
          "reserved COLOR_1 values exported without alteration")
    check(len(doc.get("colliders", [])) >= 1 or any("collider" in n for n in map(str, doc.get("nodes", []))),
          "collider exported")
    model_path = os.path.join(tmp, "hero.adm")
    with open(model_path, "wb") as fh:
        fh.write(data)
    external_path = os.path.join(tmp, "hero_external.adm")
    external_exp, external_report = export_model(
        bpy.context, external_path, root, ExportOptions(embed_textures=False, vertex_controls=True)
    )
    check(external_report.ok, f"external-texture model valid {errs(external_report)}")
    external_image = external_report.doc["images"][0]
    check("uri" in external_image and os.path.isfile(os.path.join(tmp, *external_image["uri"].split("/"))),
          "external texture sidecar written")
    with open(external_path, "rb") as fh:
        external_blob = fh.read()
    check(validate_adm_resolved(external_blob, external_path).ok, "external texture resolves and validates")

    print("== animation authoring")
    lib = sc.adm_anim.libraries.add()
    lib.lib_id, lib.title, lib.description = "hero@moves", "Hero moves", "Test moves"
    lib.armature, lib.binding = arm, "SEMANTIC"
    clip = lib.clips.add()
    clip.clip_id, clip.title, clip.description = "wave", "Wave", "Raise the left arm and fade the paint"
    act = bpy.data.actions.new("Wave")
    clip.action = act
    clip.use_action_range = True
    ad = arm.animation_data_create()
    ad.action = act
    pb = arm.pose.bones["mixamorig:LeftArm"]
    pb.rotation_mode = "QUATERNION"
    for f, ang in ((1, 0.0), (13, 1.0), (25, 0.0)):
        sc.frame_set(f)
        pb.rotation_quaternion = Euler((0, ang, 0)).to_quaternion()
        pb.keyframe_insert("rotation_quaternion")
    # shape key into the same action
    key = body.data.shape_keys
    kad = key.animation_data_create()
    kad.action = act
    for f, w in ((1, 0.0), (25, 1.0)):
        key.key_blocks["smile"].value = w
        key.key_blocks["smile"].keyframe_insert("value", frame=f)
    check(any(s.target_id_type == "KEY" for s in act.slots), "shape key keyed into clip action")
    # material: link to clip, then key shader + BSDF values
    sc.adm_anim.active_library = 0
    lib.active_clip = 0
    select(lods[0])
    check(bpy.ops.adm.material_link_clip() == {"FINISHED"}, "material_link_clip")
    ms, ns = MA.material_slots(act, paint)
    check(ms is not None and ns is not None, "material slots in clip action")
    bsdf = paint.node_tree.nodes["Principled BSDF"]
    for f, w in ((1, 0.0), (25, 1.0)):
        sc.frame_set(f)
        paint.adm.params["wear"].value_f = w
        check(bpy.ops.adm.material_key_param(name="wear") == {"FINISHED"}, f"key wear @{f}")
        paint.adm.wetness_offset = w
        paint.keyframe_insert("adm.wetness_offset", frame=f)
        bsdf.inputs["Roughness"].default_value = 0.2 + 0.6 * w
        bsdf.inputs["Roughness"].keyframe_insert("default_value", frame=f)
    kinds = sorted(s.target_id_type for s in act.slots)
    print("   slots:", [(s.target_id_type, s.name_display) for s in act.slots])
    check(kinds.count("MATERIAL") == 1 and kinds.count("NODETREE") == 1, "no duplicate material slots")

    exp = AnimExporter(bpy.context, lib)
    data, rep = exp.export()
    print("   notes:", exp.warnings)
    check(rep is not None and rep.ok, f"semantic library valid {errs(rep)}")
    chans = rep.doc["clips"][0]["channels"]
    got = {(c["target"]["kind"], c["target"].get("role") or c["target"].get("name")
            or c["target"].get("parameter")) for c in chans}
    print("   channels:", sorted(got))
    for want in (("bone", "leftUpperArm"), ("morph", "smile"), ("shaderParameter", "wear"),
                 ("shaderParameter", "wetnessOffset"), ("pbrParameter", "roughnessFactor")):
        check(want in got, f"channel {want}")
    check(("shaderParameter", "tint") not in got, "unkeyed shader param not exported")
    sem_path = os.path.join(tmp, "hero_moves.adm_anim")
    check(K.VERTEX_CONTROL_EXT in rep.doc["extensionsRequired"],
          "vertex-control animation declares its required extension")
    bind_issues = material_binding_issues(doc, rep.doc)
    check(not bind_issues, f"vertex-control animation binds to exported material {bind_issues}")
    with open(sem_path, "wb") as fh:
        fh.write(data)

    lib2 = sc.adm_anim.libraries.add()
    lib2.lib_id, lib2.title, lib2.description = "hero@exact", "Exact", "Exact moves"
    lib2.armature, lib2.binding = arm, "EXACT"
    c2 = lib2.clips.add()
    c2.clip_id, c2.title, c2.description, c2.action = "wave", "Wave", "Exact wave", act
    exp = AnimExporter(bpy.context, lib2)
    data, rep = exp.export()
    check(rep is not None and rep.ok, f"exact library valid {errs(rep)}")
    exact_path = os.path.join(tmp, "hero_exact.adm_anim")
    with open(exact_path, "wb") as fh:
        fh.write(data)

    lib3 = sc.adm_anim.libraries.add()
    lib3.lib_id, lib3.title, lib3.description = "material@paint", "Paint", "Paint wear only"
    lib3.target = "MODEL_ANY"
    c3 = lib3.clips.add()
    c3.clip_id, c3.title, c3.description, c3.action = "wear", "Wear", "Paint wears off", act
    exp = AnimExporter(bpy.context, lib3)
    data, rep = exp.export()
    check(rep is not None and rep.ok, f"model.any library valid {errs(rep)}")
    kinds3 = {c["target"]["kind"] for c in rep.doc["clips"][0]["channels"]}
    check("bone" not in kinds3 and "shaderParameter" in kinds3, f"model.any channels {kinds3}")
    any_path = os.path.join(tmp, "paint.adm_anim")
    with open(any_path, "wb") as fh:
        fh.write(data)

    print("== validators on disk")
    for pth in (model_path, sem_path, exact_path, any_path):
        r = validate_file(pth)
        check(r.ok, f"validate_file {os.path.basename(pth)} {errs(r)}")
        result = reference.verify(pth)
        check(result["verifiedPayloads"], f"independent container validator {os.path.basename(pth)}")

    print("== re-import into a fresh file")
    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    root2 = ModelImporter(bpy.context, external_path, ImportOptions()).run()
    check(root2.adm.physical_materials[0].name == "cloth", "physical material imported")
    check(root2.adm.model_components[0].bone == "mixamorig:Hips", "component bone reference imported")
    check(root2.adm.hitboxes[0].collider.adm.physical_material == "cloth", "hitbox collider link imported")
    check(root2.adm.hitboxes[0].bone == "mixamorig:Hips", "hitbox bone ancestor imported")
    imported_collider = next(o for o in bpy.data.objects if o.adm.adm_type == "COLLIDER"
                             and o.adm.collider_shape == "MESH")
    imported_faces = imported_collider.data.attributes["adm_physical_material_id"]
    check(len(imported_faces.data) == 12 and
          sum(1 for face in imported_faces.data if string_attr_value(face) == "stone") == 2 and
          sum(1 for face in imported_faces.data if string_attr_value(face) == "cloth") == 10,
          "per-triangle physical IDs round-trip to Blender FACE attribute")
    arm2 = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    check(arm2 is not None, "armature imported")
    paint2 = bpy.data.materials.get("Paint")
    check(paint2 is not None and paint2.adm.shader == "CUSTOM" and paint2.adm.custom_shader == "studio.paint@1.0.0",
          "custom shader material imported")
    check(paint2 is not None and paint2.adm.vertex_controls_enabled
          and tuple(round(v, 6) for v in (
              paint2.adm.tint_offset, paint2.adm.normal_multiplier,
              paint2.adm.reflection_multiplier, paint2.adm.wetness_offset
          )) == (0.25, 0.75, 1.5, 0.0), "vertex-control material parameters imported")
    body2 = bpy.data.objects.get("Body")
    imported_color0 = body2.data.color_attributes.get("COLOR_0") if body2 is not None else None
    check(imported_color0 is not None, "COLOR_0 survives model import")
    if imported_color0 is not None:
        check(all(abs(a - b) < 1e-6 for a, b in zip(imported_color0.data[0].color, (0.25, 0.75, 0.5, 0.4))),
              f"COLOR_0 values round-trip {tuple(imported_color0.data[0].color)}")
    imported_color1 = body2.data.color_attributes.get("COLOR_1") if body2 is not None else None
    check(imported_color1 is not None, "reserved COLOR_1 survives model import")
    if imported_color1 is not None:
        check(all(abs(a - b) < 1e-6 for a, b in zip(imported_color1.data[0].color, (0.1, 0.2, 0.3, 0.4))),
              f"reserved COLOR_1 values round-trip {tuple(imported_color1.data[0].color)}")
    skin2 = bpy.data.materials.get("Skin")
    check(skin2 is not None and any(n.name == "ADM Preview COLOR_0" for n in skin2.node_tree.nodes),
          "imported vertex-control preview resolves COLOR_0 after mesh creation")
    check(bpy.context.scene.adm_anim.shaders.get("studio.paint@1.0.0") is not None, "shader def imported")
    for pth, label in ((sem_path, "semantic"), (exact_path, "exact"), (any_path, "model.any")):
        imp, slib = import_library(bpy.context, pth, AnimImportOptions(armature=arm2))
        print(f"   {label} warnings:", imp.warnings)
        check(not imp.warnings, f"{label} import clean")
        if label == "semantic":
            imported_action = slib.clips[0].action
            imported_slot, _ = MA.material_slots(imported_action, paint2)
            wetness_curves = [fc for fc in channelbag_fcurves(imported_action, imported_slot)
                              if fc.data_path == "adm.wetness_offset"]
            values = [round(point.co.y, 6) for fc in wetness_curves for point in fc.keyframe_points]
            check(len(values) >= 2 and values[0] == 0.0 and values[-1] == 1.0
                  and all(a <= b for a, b in zip(values, values[1:])),
                  f"vertex-control animation values round-trip {values}")
        exp = AnimExporter(bpy.context, slib)
        data, rep = exp.export()
        check(rep is not None and rep.ok, f"{label} re-export valid {errs(rep)}")
        n0 = len(next(c for c in [validate_file(pth).doc["clips"][0]])["channels"])
        n1 = len(rep.doc["clips"][0]["channels"])
        check(n0 == n1, f"{label} channel count {n0} -> {n1}")
    data, rep = ModelExporter(bpy.context, root2, ExportOptions(vertex_controls=True)).export()
    check(rep.ok, f"re-imported model re-export valid {errs(rep)}")
    check(rep.doc["physicalMaterials"] == doc["physicalMaterials"], "physical coefficients round-trip")
    check(rep.doc["modelComponents"][0]["socket"] == "prop.socket.back", "component socket round-trip")
    check(rep.doc["hitboxes"][0]["role"] == "torso", "hitbox role round-trip")

    test_edit_mode_export(tmp)
    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_wf_") as tmp:
            main(tmp)
    except Exception as exc:
        traceback.print_exc()
        report = getattr(exc, "report", None)
        if report is not None:
            for issue in report.errors:
                print("   validation:", issue)
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
