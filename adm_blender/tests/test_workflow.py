"""Blender background test of the full authoring workflow (create -> author -> export -> import -> re-export).

Run:  blender -b --factory-startup --python adm_blender/tests/test_workflow.py
"""

import os
import importlib.util
import sys
import tempfile
import traceback

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


def main(tmp):
    adm_blender.register()
    from adm_blender.blender import material_anim as MA
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.export_anim import AnimExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.blender.import_anim import AnimImportOptions, import_library
    from adm_blender.core.validate import validate_file
    spec = importlib.util.spec_from_file_location("adm_reference_container",
                                                  os.path.join(REPO, "adm-standard", "tools", "container.py"))
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)

    bpy.ops.wm.read_homefile(use_empty=True)
    from adm_blender.blender.operators import ensure_role_names
    ensure_role_names()
    sc = bpy.context.scene

    print("== authoring")
    arm = build_rig()
    body = build_body(arm)
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
    collider.adm.physical_material = "cloth"
    collider_world = collider.matrix_world.copy()
    collider.parent, collider.parent_type, collider.parent_bone = arm, "BONE", "mixamorig:Hips"
    collider.matrix_world = collider_world
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

    print("== model export")
    exp = ModelExporter(bpy.context, root, ExportOptions())
    data, rep = exp.export()
    print("   notes:", exp.warnings)
    check(rep.ok, f"model valid {errs(rep)}")
    doc = rep.doc
    check(data[8:12] == (64).to_bytes(4, "little"), "Draft 0.4 native header")
    check(all("chunkId" in view for view in doc["bufferViews"]), "chunk-addressed buffer views")
    check(doc["physicalMaterials"][0]["id"] == "cloth", "physical material exported")
    check(doc["modelComponents"][0]["id"] == "back.part", "component exported")
    check(doc["hitboxes"][0]["id"] == "torso", "hitbox exported")
    check(any(d["id"] == "studio.paint" for d in doc.get("shaderDefinitions", [])), "shader definition embedded")
    pm = next(m for m in doc["materials"] if m["name"] == "Paint")
    check(all(field in pm for field in ("baseColorFactor", "metallicFactor", "roughnessFactor",
                                       "emissiveFactor", "alphaMode")), "explicit non-core PBR fallback")
    check(pm.get("shaderParameters") == {"glossy": True} and pm.get("animationId") == "paint",
          f"paint material {pm}")
    check(len(doc.get("colliders", [])) >= 1 or any("collider" in n for n in map(str, doc.get("nodes", []))),
          "collider exported")
    model_path = os.path.join(tmp, "hero.adm")
    with open(model_path, "wb") as fh:
        fh.write(data)

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
                 ("pbrParameter", "roughnessFactor")):
        check(want in got, f"channel {want}")
    check(("shaderParameter", "tint") not in got, "unkeyed shader param not exported")
    sem_path = os.path.join(tmp, "hero_moves.adm_anim")
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
    root2 = ModelImporter(bpy.context, model_path, ImportOptions()).run()
    check(root2.adm.physical_materials[0].name == "cloth", "physical material imported")
    check(root2.adm.model_components[0].bone == "mixamorig:Hips", "component bone reference imported")
    check(root2.adm.hitboxes[0].collider.adm.physical_material == "cloth", "hitbox collider link imported")
    check(root2.adm.hitboxes[0].bone == "mixamorig:Hips", "hitbox bone ancestor imported")
    arm2 = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    check(arm2 is not None, "armature imported")
    paint2 = bpy.data.materials.get("Paint")
    check(paint2 is not None and paint2.adm.shader == "CUSTOM" and paint2.adm.custom_shader == "studio.paint@1.0.0",
          "custom shader material imported")
    check(bpy.context.scene.adm_anim.shaders.get("studio.paint@1.0.0") is not None, "shader def imported")
    for pth, label in ((sem_path, "semantic"), (exact_path, "exact"), (any_path, "model.any")):
        imp, slib = import_library(bpy.context, pth, AnimImportOptions(armature=arm2))
        print(f"   {label} warnings:", imp.warnings)
        check(not imp.warnings, f"{label} import clean")
        exp = AnimExporter(bpy.context, slib)
        data, rep = exp.export()
        check(rep is not None and rep.ok, f"{label} re-export valid {errs(rep)}")
        n0 = len(next(c for c in [validate_file(pth).doc["clips"][0]])["channels"])
        n1 = len(rep.doc["clips"][0]["channels"])
        check(n0 == n1, f"{label} channel count {n0} -> {n1}")
    data, rep = ModelExporter(bpy.context, root2, ExportOptions()).export()
    check(rep.ok, f"re-imported model re-export valid {errs(rep)}")
    check(rep.doc["physicalMaterials"] == doc["physicalMaterials"], "physical coefficients round-trip")
    check(rep.doc["modelComponents"][0]["socket"] == "prop.socket.back", "component socket round-trip")
    check(rep.doc["hitboxes"][0]["role"] == "torso", "hitbox role round-trip")

    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_wf_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
