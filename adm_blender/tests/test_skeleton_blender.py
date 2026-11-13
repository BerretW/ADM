"""Blender background tests of the skeleton profile tooling (humanoid.vrm1 + provisional quadrupeds).

Covers detection, role validation (missing / duplicate / hierarchy / extra bones), reference pose and the
ROTATE_180 fix, ADM-IK-1 chains (profile templates, Blender IK conversion, solver preview, invalid chains),
profile sockets, skinning checks, model export -> import round-trip (bind pose, weights, roles, IK,
corrections), SEMANTIC retargeting between humanoids with different proportions and bone rolls combined
with ARKit morph channels, and animal profile compatibility rules.

Run:  blender -b --factory-startup --python adm_blender/tests/test_skeleton_blender.py
"""

import math
import os
import sys
import tempfile
import traceback
from copy import deepcopy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

import bpy  # noqa: E402
from mathutils import Euler, Quaternion, Vector  # noqa: E402

import adm_blender  # noqa: E402
from adm_blender.core import constants as K  # noqa: E402
from adm_blender.core.container import write_container  # noqa: E402
from adm_blender.core.validate import validate_adm  # noqa: E402
from adm_blender.tests.test_skeleton_profiles import humanoid_rig, quadruped_rig  # noqa: E402

FAILS = []
POS_TOL = 1e-5
ANG_TOL_DEG = 0.05


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def select(*objs, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def bl(p):
    """ADM model space -> Blender (x, -z, y)."""
    return Vector((p[0], -p[2], p[1]))


def cap(role):
    return role[0].upper() + role[1:]


def build_armature(name, joints, roll_deg=0.0, extra=()):
    """joints: {bone: {"parent", "head" (ADM)}}. Tails point to the most central child (or continue the
    parent direction for leaves).  ``extra``: (name, parent, head_adm) helper bones."""
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(arm)
    select(arm)
    bpy.ops.object.mode_set(mode="EDIT")
    children = {}
    for n, j in joints.items():
        children.setdefault(j["parent"], []).append(n)
    for n, j in joints.items():
        eb = data.edit_bones.new(n)
        head = bl(j["head"])
        kids = children.get(n, [])
        if kids:
            kid = min(kids, key=lambda k: (abs(joints[k]["head"][0] - j["head"][0]), k))
            tail = bl(joints[kid]["head"])
        else:
            par = joints[j["parent"]]["head"] if j["parent"] else (j["head"][0], j["head"][1] - 1, j["head"][2])
            d = head - bl(par)
            tail = head + d.normalized() * 0.08
        eb.head, eb.tail = head, tail
        eb.roll = math.radians(roll_deg)
    for n, j in joints.items():
        if j["parent"]:
            data.edit_bones[n].parent = data.edit_bones[j["parent"]]
    for n, par, head in extra:
        eb = data.edit_bones.new(n)
        eb.head = bl(head)
        eb.tail = bl(head) + Vector((0, 0, 0.05))
        eb.parent = data.edit_bones[par]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def build_humanoid(name, scale=1.0, roll_deg=0.0, mirrored=False, arm_drop_deg=0.0, prefix="",
                   helper=True):
    joints, asg = humanoid_rig(scale=scale, mirrored=mirrored, arm_drop_deg=arm_drop_deg)
    names = {b: prefix + cap(r) for b, r in asg}
    table = {names[b]: {"parent": names[j["parent"]] if j["parent"] else None, "head": j["head"]}
             for b, j in joints.items()}
    extra = [(prefix + "ClothHelper", prefix + "Chest", (0.0, 1.3 * scale, 0.12 * scale))] if helper else []
    arm = build_armature(name, table, roll_deg, extra)
    if helper:
        arm.data.bones[prefix + "ClothHelper"].use_deform = False
    return arm, {names[b]: r for b, r in asg}


def add_body(arm, prefix, key_name=None):
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=arm.matrix_world @ bl((0, 1.2, 0)))
    body = bpy.context.active_object
    body.name = arm.name + "_Body"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    groups = [prefix + n for n in ("Hips", "Spine", "Chest", "UpperChest", "Neck")]
    vgs = [body.vertex_groups.new(name=g) for g in groups]
    for vi, v in enumerate(body.data.vertices):
        a = vi % len(groups)
        vgs[a].add([vi], 0.7, "REPLACE")
        vgs[(a + 1) % len(groups)].add([vi], 0.3, "REPLACE")
    # vertex 0: 5 influences, not normalized -> SKIN_INFLUENCES / SKIN_NOT_NORMALIZED
    for g in vgs:
        g.add([0], 0.3, "REPLACE")
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    body.parent = arm
    body.matrix_parent_inverse = arm.matrix_world.inverted()
    if key_name:
        body.shape_key_add(name="Basis")
        kb = body.shape_key_add(name=key_name)
        for d in kb.data:
            d.co += Vector((0, 0.02, 0))
    return body


def model_root(arm, name, location=(0, 0, 0)):
    select(arm)
    assert bpy.ops.adm.create_model_root(name=name) == {"FINISHED"}
    root = bpy.data.objects[name]
    root.location = location
    bpy.context.view_layer.update()
    return root


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}


def world_delta(arm, bone_name):
    pb = arm.pose.bones[bone_name]
    rest = (arm.matrix_world @ arm.data.bones[bone_name].matrix_local).to_quaternion()
    pose = (arm.matrix_world @ pb.matrix).to_quaternion()
    return pose @ rest.inverted()


def ang_deg(q1, q2):
    return math.degrees(q1.rotation_difference(q2).angle)


def bone_weights(obj):
    """vertex position (rounded) -> {group name: weight} for weights > 1e-6."""
    names = {g.index: g.name for g in obj.vertex_groups}
    out = {}
    for v in obj.data.vertices:
        key = tuple(round(c, 4) for c in (obj.matrix_world @ v.co))
        out[key] = {names[g.group]: g.weight for g in v.groups if g.weight > 1e-6}
    return out


# --------------------------------------------------------------------------------------------------
def main(tmp):
    adm_blender.register()
    from adm_blender.blender import rig as R
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
    from adm_blender.blender.export_anim import AnimExporter
    from adm_blender.blender.import_adm import ImportError_, ImportOptions, ModelImporter
    from adm_blender.blender.import_anim import AnimImportOptions, check_library_compat, import_library
    from adm_blender.blender.operators import ensure_role_names
    from adm_blender.core import ik as IK
    from adm_blender.core import skeleton as SK
    from adm_blender.core import skeleton_profiles as SP
    from adm_blender.core.buffers import read_accessor_np
    from adm_blender.core.validate import validate_file

    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    sc = bpy.context.scene
    wm = bpy.context.window_manager.adm

    # ------------------------------------------------------------------ detection + validation
    print("== humanoid detection & validation")
    armA, rolesA = build_humanoid("HeroA")
    bodyA = add_body(armA, "", key_name="jawOpen")
    rootA = model_root(armA, "HeroA_Root")
    select(armA)
    check(bpy.ops.adm.detect_profile() == {"FINISHED"}, "detect_profile operator")
    sk = armA.data.adm
    check(sk.profile_id == "humanoid.vrm1", f"detected profile {sk.profile_id}")
    got = {b.name: b.adm.role for b in armA.data.bones if b.adm.role}
    check(got == rolesA, f"auto mapping matches ({len(got)}/{len(rolesA)})")
    check(set(SP.required_roles("humanoid.vrm1")) <= set(got.values()), "all VRM required roles mapped")
    check(armA.data.bones["ClothHelper"].adm.role == "", "helper bone stays unmapped")
    check(sk.export_profile, "profile export enabled by detection")
    check(bpy.ops.adm.validate_rig() == {"FINISHED"}, "validate_rig operator")
    errs = [i for i in wm.rig_report if i.severity == "ERROR"]
    check(not errs, f"valid rig has no errors {[(i.code, i.bone) for i in errs]}")
    report = {i.code for i in wm.rig_report}
    check("EXTRA_BONES" in report, "extra helper bone reported as INFO (allowed)")
    check("CORRECTION_NOT_NORMALIZED" in report, "missing normalized corrections reported")
    check({"SKIN_INFLUENCES", "SKIN_NOT_NORMALIZED"} <= report, f"skin issues reported {sorted(report)}")
    check("VALID" in wm.rig_report_title and "INVALID" not in wm.rig_report_title, wm.rig_report_title)

    check(bpy.ops.adm.normalize_corrections() == {"FINISHED"}, "normalize_corrections")
    check(not R.correction_issues(armA), "corrections normalized")
    bpy.ops.object.mode_set(mode="OBJECT")
    check(bpy.ops.adm.skin_fix() == {"FINISHED"}, "skin_fix")
    check(not codes(R.skin_issues(armA)) & {"SKIN_INFLUENCES", "SKIN_NOT_NORMALIZED"}, "skin fixed")
    v0 = bodyA.data.vertices[0]
    check(len(v0.groups) == 4 and abs(sum(g.weight for g in v0.groups) - 1.0) < 1e-5,
          "vertex 0 limited to 4 normalized influences")

    print("== invalid mappings")
    b = armA.data.bones["LeftLowerArm"]
    b.adm.role = ""
    iss = R.analyze(armA)
    check(any(i.code == "ROLE_MISSING" and i.role == "leftLowerArm" and i.fix == SK.FIX_AUTO_MAP for i in iss),
          "missing required role leftLowerArm (with auto-map fix)")
    try:
        ModelExporter(bpy.context, rootA, ExportOptions()).export()
        check(False, "export must refuse a rig with a missing required role")
    except ExportError as exc:
        check("leftLowerArm" in str(exc), f"export refused: {exc}")
    check(bpy.ops.adm.rig_fix(fix=SK.FIX_AUTO_MAP) == {"FINISHED"} and b.adm.role == "leftLowerArm",
          "auto-map fix restores the role")

    try:
        r = bpy.ops.adm.set_bone_role(bone="Neck", role="head")
    except RuntimeError:
        r = {"CANCELLED"}
    check(r == {"CANCELLED"} and armA.data.bones["Neck"].adm.role == "neck", "set_bone_role refuses duplicates")
    armA.data.bones["Neck"].adm.role = "head"
    iss = R.analyze(armA)
    dup = [i for i in iss if i.code == "ROLE_DUPLICATE"]
    check(dup and dup[0].role == "head" and dup[0].severity == SK.ERROR, "duplicate role detected")
    try:
        ModelExporter(bpy.context, rootA, ExportOptions()).export()
        check(False, "export must refuse a duplicate role")
    except ExportError:
        check(True, "export refused duplicate role")
    armA.data.bones["Neck"].adm.role = "neck"

    select(armA)
    bpy.ops.object.mode_set(mode="EDIT")
    armA.data.edit_bones["LeftHand"].parent = armA.data.edit_bones["Chest"]
    bpy.ops.object.mode_set(mode="OBJECT")
    iss = R.analyze(armA)
    check(any(i.code == "ROLE_HIERARCHY" and i.role == "leftHand" and i.bone == "LeftHand" for i in iss),
          "wrong parent -> ROLE_HIERARCHY on leftHand")
    bpy.ops.object.mode_set(mode="EDIT")
    armA.data.edit_bones["LeftHand"].parent = armA.data.edit_bones["LeftLowerArm"]
    bpy.ops.object.mode_set(mode="OBJECT")
    check(not SK.has_errors(R.analyze(armA)), "rig valid again after restoring the parent")

    print("== reference pose")
    armM, _ = build_humanoid("Mirrored", mirrored=True, prefix="m_", helper=False)
    rootM = model_root(armM, "Mirrored_Root", (5, 0, 0))
    R.apply_mapping(armM, {"m_" + cap(r): r for r in SP.roles("humanoid.vrm1")})
    armM.data.adm.profile = "humanoid.vrm1"
    iss = R.analyze(armM)
    face = [i for i in iss if i.code == "REFERENCE_FACING"]
    check(face and face[0].severity == SK.ERROR and face[0].fix == SK.FIX_ROTATE_180, "mirrored rig detected")
    select(armM)
    check(bpy.ops.adm.rig_fix(fix=SK.FIX_ROTATE_180) == {"FINISHED"}, "ROTATE_180 fix")
    check("REFERENCE_FACING" not in codes(R.analyze(armM)), "facing fixed")
    tA, tM = R.joint_table(armA), R.joint_table(armM)
    dev = max((Vector(tA[n]["head"]) - Vector(tM["m_" + n]["head"])).length for n in tA if n != "ClothHelper")
    check(dev < POS_TOL, f"rotated rig matches the reference joints ({dev:.2e} m)")
    check((rootM.matrix_world.translation - Vector((5, 0, 0))).length < 1e-6, "model root not moved by fix")

    armD, _ = build_humanoid("Drooped", arm_drop_deg=45.0, prefix="d_", helper=False)
    model_root(armD, "Drooped_Root", (-5, 0, 0))
    armD.data.adm.profile = "humanoid.vrm1"
    R.apply_mapping(armD, {"d_" + cap(r): r for r in SP.roles("humanoid.vrm1")})
    pose = [i for i in R.analyze(armD) if i.code == "REFERENCE_POSE"]
    check(pose and any("UpperArm" in i.message or "upperArm" in i.message.lower() for i in pose),
          f"A-pose arms flagged {[i.message for i in pose][:2]}")

    # ------------------------------------------------------------------ IK
    print("== IK chains")
    select(armA)
    check(bpy.ops.adm.ik_from_profile(replace=True) == {"FINISHED"}, "ik_from_profile")
    tmpl = {t["id"]: t for t in SP.ik_templates("humanoid.vrm1")}
    ids = [c.chain_id for c in sk.ik_chains]
    check(ids == sorted(tmpl), f"profile chains in lexical order {ids}")
    rb = R.role_bone_map(armA)
    for c in sk.ik_chains:
        t = tmpl[c.chain_id]
        same = (c.root, c.mid, c.end) == (rb[t["root"]], rb[t["mid"]], rb[t["end"]])
        pole = Vector(R.pole_to_adm(armA, c.pole))
        check(same and (pole - Vector(t["pole"])).length < 1e-6, f"chain {c.chain_id} bones + ADM pole")
    check(not codes(R.analyze(armA), SK.ERROR), "profile chains validate")

    left = next(c for c in sk.ik_chains if c.end == "LeftHand")
    tgt = R.ensure_preview_target(bpy.context, armA, left)
    check(tgt.get("adm_editor_only") is True, "preview target is editor-only")
    up = armA.matrix_world @ armA.pose.bones["LeftUpperArm"].head
    tgt.location = up + Vector((-0.2, 0.15, -0.25))
    bpy.context.view_layer.update()
    check(bpy.ops.adm.ik_preview() == {"FINISHED"}, "ik_preview operator")
    bpy.context.view_layer.update()
    hand = armA.matrix_world @ armA.pose.bones["LeftHand"].head
    check((hand - tgt.matrix_world.translation).length < 1e-4,
          f"IK preview reaches the target ({(hand - tgt.matrix_world.translation).length:.2e} m)")
    elbow = armA.matrix_world @ armA.pose.bones["LeftLowerArm"].head
    axis = (tgt.matrix_world.translation - up).normalized()
    bend = (elbow - up) - axis * (elbow - up).dot(axis)
    pole_w = armA.matrix_world.to_3x3() @ Vector(left.pole)
    check(bend.dot(pole_w) > 0, "elbow bends toward the pole (ADM +Z = back)")
    res = R.preview_ik(bpy.context, armA, [left])
    check(res and res[0][1] != IK.INVALID, f"solver status {res[0][1] if res else None}")
    tgt.location = up + Vector((-3.0, 0, 0))
    bpy.context.view_layer.update()
    res = R.preview_ik(bpy.context, armA, [left])
    bpy.context.view_layer.update()
    straight = (armA.pose.bones["LeftHand"].head - armA.pose.bones["LeftUpperArm"].head).length
    check(abs(straight - 0.55) < 1e-4, f"unreachable target -> straight chain ({straight:.5f})")
    check(bpy.ops.adm.ik_reset() == {"FINISHED"}, "ik_reset")
    bpy.context.view_layer.update()
    check((armA.pose.bones["LeftHand"].head - armA.data.bones["LeftHand"].head_local).length < 1e-6,
          "reset restores the reference pose")
    left.target = None
    bpy.data.objects.remove(tgt)

    bad = sk.ik_chains.add()
    bad.chain_id, bad.root, bad.mid, bad.end = "broken", "RightUpperArm", "RightHand", "RightLowerArm"
    bad.pole = (0, -1, 0)
    iss = R.analyze(armA)
    check({"IK_NOT_DIRECT", "IK_OVERLAP"} & codes(iss, SK.ERROR), f"invalid chain detected {codes(iss, SK.ERROR)}")
    sk.ik_chains.remove(len(sk.ik_chains) - 1)
    inc = sk.ik_chains.add()
    inc.chain_id, inc.root, inc.mid = "partial", "Neck", "Head"
    check("IK_INCOMPLETE" in codes(R.analyze(armA)), "incomplete chain detected")
    sk.ik_chains.remove(len(sk.ik_chains) - 1)

    print("== Blender IK constraints")
    sk.ik_chains.clear()
    goal = bpy.data.objects.new("Goal", None)
    sc.collection.objects.link(goal)
    con = armA.pose.bones["LeftLowerArm"].constraints.new("IK")
    con.target, con.chain_count = goal, 2
    con3 = armA.pose.bones["RightLowerArm"].constraints.new("IK")
    con3.target, con3.chain_count = goal, 3
    cr = armA.pose.bones["Head"].constraints.new("COPY_ROTATION")
    cr.target = goal
    ci = codes(R.constraint_issues(armA))
    check({"BLENDER_IK_UNSUPPORTED", "BLENDER_CONSTRAINT_UNSUPPORTED"} <= ci, f"unsupported constraints {ci}")
    created, notes = R.chains_from_blender_ik(armA)
    check(created == [tmpl_id for tmpl_id, t in tmpl.items() if t["end"] == "leftHand"],
          f"two-bone IK converted {created}")
    c = sk.ik_chains[0]
    check((c.root, c.mid, c.end) == ("LeftUpperArm", "LeftLowerArm", "LeftHand"), "converted chain joints")
    check(any("chain_count=3" in n for n in notes), "3-bone constraint skipped with a note")
    for pb in armA.pose.bones:
        for k in list(pb.constraints):
            pb.constraints.remove(k)
    bpy.data.objects.remove(goal)
    R.add_chains_from_profile(armA, replace=True)

    print("== profile sockets")
    select(armA)
    check(bpy.ops.adm.create_profile_sockets() == {"FINISHED"}, "create_profile_sockets")
    socks = {o.adm.attachment_name: o for o in bpy.data.objects if o.adm.adm_type == "ATTACHMENT"}
    for t in SP.socket_templates("humanoid.vrm1"):
        o = socks.get(t["name"])
        ok = o is not None and o.parent == armA and o.parent_type == "BONE" and o.parent_bone == rb[t["role"]]
        if ok:
            head = armA.matrix_world @ armA.data.bones[o.parent_bone].head_local
            ok = (o.matrix_world.translation - head).length < 1e-6 and \
                ang_deg(o.matrix_world.to_quaternion(), rootA.matrix_world.to_quaternion()) < 1e-3
        check(ok, f"socket {t['name']} on {t['role']}")

    # ------------------------------------------------------------------ export -> import
    print("== skeleton export")
    exp = ModelExporter(bpy.context, rootA, ExportOptions())
    data, rep = exp.export()
    check(rep.ok, f"model valid {[str(e) for e in rep.errors[:4]]}")
    doc = rep.doc
    prof = doc["skeletonProfiles"][0]
    check(prof["id"] == "humanoid.vrm1" and prof["referencePose"] == "T", "profile + reference pose declared")
    node_name = {i: n.get("name") for i, n in enumerate(doc["nodes"])}
    check({node_name[i]: r for r, i in prof["roles"].items()} == rolesA, "roles exported by node")
    check(set(prof.get("referenceCorrection", {})) == set(rolesA.values()), "normalized corrections exported")
    missing_correction = deepcopy(doc)
    missing_role = next(iter(missing_correction["skeletonProfiles"][0]["referenceCorrection"]))
    del missing_correction["skeletonProfiles"][0]["referenceCorrection"][missing_role]
    correction_report = validate_adm(
        write_container(K.ADM_MAGIC, missing_correction, rep.bin))
    check("PROFILE_CORRECTION_REQUIRED" in {e.code for e in correction_report.errors},
          f"missing correction for {missing_role} is rejected")
    chains = {c["id"]: c for c in doc.get("ikChains", [])}
    check(set(chains) == set(tmpl), f"IK chains exported {sorted(chains)}")
    for cid, c in chains.items():
        t = tmpl[cid]
        check(c["solver"] == "TWO_BONE" and [node_name[c[k]] for k in ("root", "mid", "end")] ==
              [rb[t[k]] for k in ("root", "mid", "end")] and
              (Vector(c["pole"]) - Vector(t["pole"])).length < 1e-6, f"exported chain {cid}")
    att = {a["name"]: a["node"] for a in doc.get("attachments", [])}
    hand_node = prof["roles"]["leftHand"]
    check("hand.left" in att and att["hand.left"] in doc["nodes"][hand_node].get("children", []),
          "hand.left socket is a child of the leftHand joint")
    skin = doc["skins"][prof["skin"]]
    ibm0 = read_accessor_np(doc, rep.bin, skin["inverseBindMatrices"])
    joints0 = [node_name[j] for j in skin["joints"]]
    path = os.path.join(tmp, "heroA.adm")
    with open(path, "wb") as fh:
        fh.write(data)
    check(validate_file(path).ok, "validate_file heroA.adm")

    # ------------------------------------------------------------------ retargeting
    print("== SEMANTIC retarget between humanoids (scale 1.25, roll 30 deg, other names)")
    armB, rolesB = build_humanoid("HeroB", scale=1.25, roll_deg=30.0, prefix="b_", helper=False)
    bodyB = add_body(armB, "b_", key_name="Jaw_Open")
    rootB = model_root(armB, "HeroB_Root", (3, 0, 0))
    armB.data.adm.profile = "humanoid.vrm1"
    armB.data.adm.export_profile = True
    R.apply_mapping(armB, rolesB)
    R.apply_normalized_corrections(armB)
    fb = rootB.adm.face_bindings.add()
    fb.channel, fb.object, fb.target, fb.scale = "jawOpen", bodyB, "Jaw_Open", 1.0
    rootB.adm.face_enabled = True
    check(not SK.has_errors(R.analyze(armB)), "target rig valid")

    lib = sc.adm_anim.libraries.add()
    lib.lib_id, lib.title, lib.description = "human@test@retarget", "Retarget", "Arm swing and jaw"
    lib.armature, lib.binding = armA, "SEMANTIC"
    clip = lib.clips.add()
    clip.clip_id, clip.title, clip.description = "swing", "Swing", "Arm swing with jaw open"
    act = bpy.data.actions.new("Swing")
    clip.action = act
    clip.use_action_range = True
    ad = armA.animation_data_create()
    ad.action = act
    keyed = {"LeftUpperArm": Euler((0.3, 0.5, -0.7)), "LeftLowerArm": Euler((0.0, 0.0, 1.1)),
             "Spine": Euler((0.2, 0.1, 0.0)), "Head": Euler((0.0, 0.4, 0.2))}
    for name in keyed:
        armA.pose.bones[name].rotation_mode = "QUATERNION"
    for f, s in ((1, 0.0), (11, 1.0), (21, 0.25)):
        sc.frame_set(f)
        for name, e in keyed.items():
            pb = armA.pose.bones[name]
            pb.rotation_quaternion = Euler((e.x * s, e.y * s, e.z * s)).to_quaternion()
            pb.keyframe_insert("rotation_quaternion")
    key = bodyA.data.shape_keys
    kad = key.animation_data_create()
    kad.action = act
    for f, w in ((1, 0.0), (11, 0.8), (21, 0.1)):
        key.key_blocks["jawOpen"].value = w
        key.key_blocks["jawOpen"].keyframe_insert("value", frame=f)
    exp = AnimExporter(bpy.context, lib)
    data, rep = exp.export()
    check(rep is not None and rep.ok, "semantic library valid")
    ch = {(c["target"]["kind"], c["target"].get("role") or c["target"].get("name"))
          for c in rep.doc["clips"][0]["channels"]}
    check({("bone", "leftUpperArm"), ("bone", "leftLowerArm"), ("bone", "spine"), ("bone", "head"),
           ("morph", "jawOpen")} <= ch, f"combined bone + ARKit channels {sorted(ch)}")
    check(rep.doc["library"]["targetProfile"] == "humanoid.vrm1", "library declares humanoid.vrm1")
    check(rep.doc["clips"][0]["title"] == "Swing" and rep.doc["clips"][0]["description"] ==
          "Arm swing with jaw open", "clip title/description exported")
    lib_path = os.path.join(tmp, "human_retarget.adm_anim")
    with open(lib_path, "wb") as fh:
        fh.write(data)

    sample = {}
    for f in (6, 11, 16):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        sample[f] = ({n: world_delta(armA, n) for n in keyed},
                     armA.matrix_world @ armA.pose.bones["LeftHand"].head,
                     key.key_blocks["jawOpen"].value)

    lvl, reasons, _w = check_library_compat(bpy.context, armB, rep.doc)
    check(lvl == SK.SEMANTIC, f"compat level {lvl} {reasons}")
    select(armB)
    check(bpy.ops.adm.anim_compat_test("EXEC_DEFAULT", filepath=lib_path) == {"FINISHED"} and
          ": SEMANTIC" in wm.compat_title and any(i.code == "CLIP" and i.path == "swing" for i in wm.compat_report),
          f"anim_compat_test: {wm.compat_title}")
    imp, slib = import_library(bpy.context, lib_path, AnimImportOptions(armature=armB))
    check(not imp.warnings, f"retarget import clean {imp.warnings}")
    check(slib.clips[0].title == "Swing" and slib.clips[0].description == "Arm swing with jaw open",
          "clip metadata preserved")
    rootA_inv = rootA.matrix_world.inverted()
    rootB_inv = rootB.matrix_world.inverted()
    for f, (deltas, handA, jaw) in sample.items():
        sc.frame_set(f)
        bpy.context.view_layer.update()
        worst = max(ang_deg(world_delta(armB, "b_" + n), deltas[n]) for n in keyed)
        check(worst < ANG_TOL_DEG, f"frame {f}: world rotation deltas match ({worst:.4f} deg)")
        handB = armB.matrix_world @ armB.pose.bones["b_LeftHand"].head
        d = ((rootB_inv @ handB) / 1.25 - (rootA_inv @ handA)).length
        check(d < 1e-4, f"frame {f}: hand position scales with proportions ({d:.2e} m)")
        jb = bodyB.data.shape_keys.key_blocks["Jaw_Open"].value
        check(abs(jb - jaw) < 1e-4, f"frame {f}: ARKit jawOpen -> 'Jaw_Open' {jb:.4f} vs {jaw:.4f}")

    # ------------------------------------------------------------------ animals
    print("== animal profiles (PROVISIONAL)")
    quads = {}
    for name, kind, pid, x in (("Dog", "digitigrade", "animal.canine.v1", 10),
                               ("Dog2", "digitigrade", "animal.canine.v1", 12),
                               ("Horse", "unguligrade", "animal.equine.v1", 14)):
        a = build_armature(name, quadruped_rig(kind))
        model_root(a, name + "_Root", (x, 0, 0))
        a.data.adm.profile = pid
        a.data.adm.export_profile = True
        n = R.auto_map_profile(a)
        iss = R.analyze(a)
        check(n >= len(SP.required_roles(pid)) and not SK.has_errors(iss),
              f"{name}: {pid} mapped {n} roles, errors {codes(iss, SK.ERROR)}")
        check("PROFILE_PROVISIONAL" in codes(iss), f"{name}: flagged PROVISIONAL")
        quads[name] = a
    dog = quads["Dog"]
    dlib = sc.adm_anim.libraries.add()
    dlib.lib_id, dlib.title, dlib.description = "animal@canine@locomotion", "Canine", "Dog walk"
    dlib.armature, dlib.binding = dog, "SEMANTIC"
    dc = dlib.clips.add()
    dc.clip_id, dc.title, dc.description = "walk", "Walk", "Dog walk cycle"
    dact = bpy.data.actions.new("DogWalk")
    dc.action = dact
    dog.animation_data_create().action = dact
    hip_role = next(b.name for b in dog.data.bones if b.adm.role == "leftHindUpperLeg")
    pb = dog.pose.bones[hip_role]
    pb.rotation_mode = "QUATERNION"
    for f, a_ in ((1, 0.0), (11, 0.5)):
        sc.frame_set(f)
        pb.rotation_quaternion = Euler((a_, 0, 0)).to_quaternion()
        pb.keyframe_insert("rotation_quaternion")
    data, rep = AnimExporter(bpy.context, dlib).export()
    check(rep is not None and rep.ok and rep.doc["library"]["targetProfile"] == "animal.canine.v1",
          "canine library exported")
    dog_path = os.path.join(tmp, "canine.adm_anim")
    with open(dog_path, "wb") as fh:
        fh.write(data)
    lvl, reasons, _ = check_library_compat(bpy.context, quads["Dog2"], rep.doc)
    check(lvl == SK.PROVISIONAL_SEMANTIC, f"canine -> canine: {lvl}")
    imp, _s = import_library(bpy.context, dog_path, AnimImportOptions(armature=quads["Dog2"]))
    check(any(w.startswith("PROVISIONAL") for w in imp.warnings), "provisional import warns")
    try:
        import_library(bpy.context, dog_path, AnimImportOptions(armature=quads["Dog2"], allow_provisional=False))
        check(False, "allow_provisional=False must refuse")
    except ImportError_:
        check(True, "allow_provisional=False refuses provisional binding")
    lvl, reasons, _ = check_library_compat(bpy.context, quads["Horse"], rep.doc)
    check(lvl == SK.INCOMPATIBLE, f"canine -> equine: {lvl} {reasons[:1]}")
    try:
        import_library(bpy.context, dog_path, AnimImportOptions(armature=quads["Horse"]))
        check(False, "canine library must not bind to the equine rig")
    except ImportError_ as exc:
        check("INCOMPATIBLE" in str(exc), "canine -> equine import refused")
    lvl, _r, _ = check_library_compat(bpy.context, armB, rep.doc)
    check(lvl == SK.INCOMPATIBLE, f"canine -> humanoid: {lvl}")
    hum_doc = validate_file(lib_path).doc
    lvl, _r, _ = check_library_compat(bpy.context, dog, hum_doc)
    check(lvl == SK.INCOMPATIBLE, f"humanoid -> canine: {lvl}")

    # ------------------------------------------------------------------ re-import heroA
    print("== skeleton round-trip (fresh file)")
    origin = {n: (armA.matrix_world @ armA.data.bones[n].matrix_local) for n in rolesA}
    weights0 = bone_weights(bodyA)
    corr0 = {b.name: tuple(b.adm.reference_correction) for b in armA.data.bones if b.adm.role}
    rootA_w = rootA.matrix_world.copy()
    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    root2 = ModelImporter(bpy.context, path, ImportOptions()).run()
    arm2 = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    body2 = next(o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups)
    check(arm2.data.adm.profile_id == "humanoid.vrm1", "profile id imported")
    check({b.name: b.adm.role for b in arm2.data.bones if b.adm.role} == rolesA, "roles imported")
    rel = root2.matrix_world @ rootA_w.inverted()
    dm = max(max(abs(a - b) for ra, rb_ in zip(rel @ origin[n], arm2.matrix_world @ arm2.data.bones[n].matrix_local)
                 for a, b in zip(ra, rb_)) for n in rolesA)
    check(dm < POS_TOL, f"bind matrices preserved ({dm:.2e})")
    dc_ = max(ang_deg(Quaternion(corr0[n]), Quaternion(tuple(arm2.data.bones[n].adm.reference_correction)))
              for n in corr0)
    check(dc_ < 1e-3, f"reference corrections preserved ({dc_:.2e} deg)")
    chains2 = {c.chain_id: (c.root, c.mid, c.end) for c in arm2.data.adm.ik_chains}
    check(chains2 == {cid: (rb[t["root"]], rb[t["mid"]], rb[t["end"]]) for cid, t in tmpl.items()},
          "IK chains imported")
    pole_dev = max((Vector(R.pole_to_adm(arm2, c.pole)) - Vector(tmpl[c.chain_id]["pole"])).length
                   for c in arm2.data.adm.ik_chains)
    check(pole_dev < 1e-6, f"IK poles preserved ({pole_dev:.2e})")
    w1 = bone_weights(body2)
    wdev, missing = 0.0, 0
    shift = rel
    for pos, w in weights0.items():
        p2 = tuple(round(c, 4) for c in (shift @ Vector(pos)))
        if p2 not in w1:
            missing += 1
            continue
        for g in set(w) | set(w1[p2]):
            wdev = max(wdev, abs(w.get(g, 0.0) - w1[p2].get(g, 0.0)))
    check(missing == 0 and wdev < 2e-3, f"skin weights preserved (missing {missing}, max dev {wdev:.1e})")
    socks2 = {o.adm.attachment_name: o.parent_bone for o in bpy.data.objects if o.adm.adm_type == "ATTACHMENT"}
    check(socks2.get("hand.left") == "LeftHand", f"socket parent preserved {socks2.get('hand.left')}")
    data2, rep2 = ModelExporter(bpy.context, root2, ExportOptions()).export()
    check(rep2.ok, "re-export valid")
    p2 = rep2.doc["skeletonProfiles"][0]
    n2 = {i: n.get("name") for i, n in enumerate(rep2.doc["nodes"])}
    skin2 = rep2.doc["skins"][p2["skin"]]
    ibm1 = read_accessor_np(rep2.doc, rep2.bin, skin2["inverseBindMatrices"])
    j1 = [n2[j] for j in skin2["joints"]]
    idx = {n: i for i, n in enumerate(j1)}
    dev = max(float(abs(ibm0[i] - ibm1[idx[n]]).max()) for i, n in enumerate(joints0) if n in idx)
    check(set(joints0) == set(j1) and dev < POS_TOL, f"inverse bind matrices round-trip ({dev:.2e})")
    check({n2[i]: r for r, i in p2["roles"].items()} == rolesA and p2["referencePose"] == "T",
          "profile round-trip")

    adm_blender.unregister()


if __name__ == "__main__":
    code = 0
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main(tmp)
        except Exception:
            traceback.print_exc()
            FAILS.append("exception")
    print("RESULT:", "FAIL" if FAILS else "PASS", f"({len(FAILS)} failures)" if FAILS else "")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
