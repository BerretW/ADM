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
from mathutils import Euler, Matrix, Quaternion, Vector  # noqa: E402

import adm_blender  # noqa: E402
from adm_blender.core import constants as K  # noqa: E402
from adm_blender.core.container import write_container  # noqa: E402
from adm_blender.core.validate import validate_adm  # noqa: E402
from adm_blender.tests.test_skeleton_profiles import humanoid_rig, quadruped_rig  # noqa: E402

FAILS = []
POS_TOL = 1e-5
DISPLAY_TOL = 2e-5
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


def evaluated_world_vertices(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def corrected_world_delta(arm, bone_name):
    from adm_blender.blender import convert as cv

    bone = arm.data.bones[bone_name]
    correction = cv.bone_frame_correction(bone)
    rest = arm.matrix_world @ bone.matrix_local @ correction
    pose = arm.matrix_world @ arm.pose.bones[bone_name].matrix @ correction
    return pose.to_quaternion() @ rest.to_quaternion().inverted()


# --------------------------------------------------------------------------------------------------
def main(tmp):
    adm_blender.register()
    from adm_blender.blender import humanoid_wizard, ui

    check(humanoid_wizard._depsgraph_freshness_update in bpy.app.handlers.depsgraph_update_post,
          "wizard freshness tracker is registered")
    ui.set_sidebar_category("ADM Test")
    check(all(panel.bl_category == "ADM Test" for panel in humanoid_wizard.SIDEBAR_PANELS),
          "custom sidebar category includes character panels")
    ui.set_sidebar_category("ADM")
    check(all(panel.bl_category == "ADM Character" for panel in humanoid_wizard.SIDEBAR_PANELS),
          "character panels use their dedicated default tab")
    from adm_blender.blender import convert as cv
    from adm_blender.blender import rig as R
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter, RestPose
    from adm_blender.blender.export_anim import AnimExporter
    from adm_blender.blender.import_adm import ImportError_, ImportOptions, ModelImporter
    from adm_blender.blender.import_anim import AnimImportOptions, check_library_compat, import_library
    from adm_blender.blender.operators import ensure_role_names
    from adm_blender.blender.humanoid_wizard import (
        STEP_STATUS_BLOCKED, STEP_STATUS_COMPLETE, STEP_STATUS_IN_PROGRESS, STEP_STATUS_WARNING,
        _auto_weight_mesh, _complete_step, _generate_skeleton, _refresh_stale_results,
        export_readiness, step_statuses,
    )
    from adm_blender.core import ik as IK
    from adm_blender.core.mathutil import IDENTITY, mat_mul, node_local_matrix
    from adm_blender.core import skeleton as SK
    from adm_blender.core import skeleton_profiles as SP
    from adm_blender.core.buffers import read_accessor_np
    from adm_blender.core.validate import validate_file

    def node_world_matrix(doc, index):
        parents = [None] * len(doc["nodes"])
        for parent, node in enumerate(doc["nodes"]):
            for child in node.get("children", []):
                parents[child] = parent
        chain = []
        while index is not None:
            chain.append(node_local_matrix(doc["nodes"][index]))
            index = parents[index]
        result = list(IDENTITY)
        for local in reversed(chain):
            result = mat_mul(result, local)
        return result

    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    sc = bpy.context.scene
    wm = bpy.context.window_manager.adm

    print("== numbered Mixamo namespace")
    mixamo_arm, _ = build_humanoid("Numbered_Mixamo", prefix="mixamorig1:", helper=False)
    mixamo_names = {"UpperLeg": "UpLeg", "LowerLeg": "Leg", "UpperArm": "Arm",
                    "LowerArm": "ForeArm", "Toes": "ToeBase"}
    for bone in mixamo_arm.data.bones:
        for side in ("Left", "Right"):
            for old, new in mixamo_names.items():
                if bone.name == "mixamorig1:" + side + old:
                    bone.name = "mixamorig1:" + side + new
    wizard = sc.adm_humanoid_wizard
    wizard.armature = mixamo_arm
    check(bpy.ops.adm.hw_auto_configure() == {"FINISHED"},
          "wizard configures a freshly imported numbered Mixamo rig")
    check(not any(issue.code == "ROLE_MISSING" for issue in R.analyze(mixamo_arm)),
          "numbered Mixamo rig has every required humanoid role after auto-configure")
    check(all(mixamo_arm.data.bones["mixamorig1:" + side + name].adm.role == side.lower() + role
              for side in ("Left", "Right")
              for name, role in (("UpLeg", "UpperLeg"), ("Leg", "LowerLeg"), ("Foot", "Foot"),
                                 ("Arm", "UpperArm"), ("ForeArm", "LowerArm"), ("Hand", "Hand"))),
          "screenshot Mixamo limb names map without renaming imported bones")
    wizard.armature = None
    mixamo_data = mixamo_arm.data
    bpy.data.objects.remove(mixamo_arm, do_unlink=True)
    bpy.data.armatures.remove(mixamo_data)

    # ------------------------------------------------------------------ humanoid wizard template
    print("== humanoid wizard template")
    bpy.ops.mesh.primitive_cube_add(size=0.4)
    template_mesh = bpy.context.active_object
    template_mesh.name = "Wizard_UnriggedMesh"
    check(bpy.ops.adm.create_model_root(name="Wizard_Root") == {"FINISHED"},
          "wizard test has an ADM model root")
    wizard = sc.adm_humanoid_wizard
    wizard.mode = "AUTO"
    wizard.model_root = bpy.data.objects["Wizard_Root"]
    wizard.armature = None
    wizard.step_results = "{}"
    wizard.stale_steps = "[]"
    select(template_mesh)
    check(bpy.ops.adm.hw_navigate(step=12) == {"FINISHED"}
          and bpy.ops.adm.hw_navigate(step=0) == {"FINISHED"} and wizard.step == 0,
          "wizard allows free forward and backward navigation")
    initial_statuses = step_statuses(bpy.context, wizard)
    check(initial_statuses[0] == STEP_STATUS_IN_PROGRESS
          and initial_statuses[1] == "Not started"
          and initial_statuses[12] == STEP_STATUS_BLOCKED,
          f"wizard exposes in-progress, not-started, and blocked phase states: {initial_statuses}")
    readiness = export_readiness(bpy.context, wizard)
    check(bool(readiness["blockers"]) and bool(readiness["recommendations"]),
          "export readiness separates blockers from recommendations")
    check(bpy.ops.adm.hw_analyze() == {"FINISHED"}, "wizard analyzes an unrigged mesh")
    check(step_statuses(bpy.context, wizard)[0] == STEP_STATUS_COMPLETE,
          "analyze phase is recorded complete")
    check(wizard.detected_mode == "UNRIGGED", f"wizard classifies mesh as {wizard.detected_mode}")
    check(bpy.ops.adm.hw_generate_skeleton() == {"FINISHED"}, "wizard creates manual-placement skeleton")
    template_arm = wizard.armature
    check(step_statuses(bpy.context, wizard)[1] == STEP_STATUS_COMPLETE,
          "skeleton phase is recorded complete")
    expected_roles = set(SP.roles(SP.HUMANOID))
    template_roles = {bone.adm.role for bone in template_arm.data.bones if bone.adm.role}
    check(template_roles == expected_roles, f"template creates all {len(expected_roles)} humanoid roles")
    check(all((bone.parent.name if bone.parent else None) == SP.roles(SP.HUMANOID)[bone.adm.role]["parent"]
              for bone in template_arm.data.bones), "template preserves profile parent hierarchy")
    select(template_arm)
    bpy.ops.object.mode_set(mode="EDIT")
    for eye_name in ("leftEye", "rightEye"):
        template_arm.data.edit_bones.remove(template_arm.data.edit_bones[eye_name])
    bpy.ops.object.mode_set(mode="OBJECT")
    stale_roles = {
        "leftUpperLeg": "leftFrontUpperLeg",
        "leftLowerLeg": "leftFrontLowerLeg",
        "leftFoot": "leftFrontFoot",
        "rightUpperLeg": "rightFrontUpperLeg",
    }
    for bone_name, role in stale_roles.items():
        template_arm.data.bones[bone_name].adm.role = role
    template_arm.data.adm.profile = "animal.canine.v1"
    check(bpy.ops.adm.hw_auto_configure(repair_invalid=False) == {"CANCELLED"}
          and template_arm.data.adm.profile_id == "animal.canine.v1"
          and template_arm.data.bones["leftUpperLeg"].adm.role == "leftFrontUpperLeg",
          "humanoid auto-configure preserves stale roles when repair is declined")
    check(bpy.ops.adm.hw_auto_configure(repair_invalid=True) == {"FINISHED"},
          "humanoid auto-configure repairs roles from another profile")
    check(template_arm.data.adm.profile_id == SP.HUMANOID
          and all(template_arm.data.bones[name].adm.role == expected
                  for name, expected in (("leftUpperLeg", "leftUpperLeg"),
                                         ("leftLowerLeg", "leftLowerLeg"),
                                         ("leftFoot", "leftFoot"),
                                         ("rightUpperLeg", "rightUpperLeg")))
          and not any(issue.code == "ROLE_UNKNOWN" for issue in R.analyze(template_arm)),
          "repaired Mixamo-style role mappings validate as humanoid")
    eye_bones = [bone for bone in template_arm.data.bones if bone.adm.role in {"leftEye", "rightEye"}]
    check(not eye_bones and "add and position them manually" in wizard.status,
          "auto-configure leaves missing eye placement to the user")
    check(bpy.ops.adm.hw_auto_configure(repair_invalid=True) == {"FINISHED"}
          and len([bone for bone in template_arm.data.bones
                   if bone.adm.role in {"leftEye", "rightEye"}]) == 0,
          "repeated auto-configure still does not create missing eye bones")
    check(not template_mesh.vertex_groups and not any(m.type == "ARMATURE" for m in template_mesh.modifiers),
          "skeleton generation does not bind or modify mesh weights")
    preserve_group = template_mesh.vertex_groups.new(name="PreserveExistingWeight")
    preserve_group.add([0], 0.75, "REPLACE")
    check(bpy.ops.adm.hw_skinning() == {"FINISHED"}, "skinning suggestions skip existing weight data")
    check(template_mesh.vertex_groups.get("PreserveExistingWeight") is not None
          and abs(preserve_group.weight(0) - 0.75) < 1e-6
          and not any(mod.type == "ARMATURE" for mod in template_mesh.modifiers),
          "skinning suggestion preserves existing groups and weights")
    hips_group = template_mesh.vertex_groups.new(name="hips")
    hips_group.add([0], 0.25, "REPLACE")
    world_before_adopt = template_mesh.matrix_world.copy()
    check(bpy.ops.adm.hw_skinning(existing_action="ADOPT") == {"FINISHED"},
          "wizard adopts existing weights without recomputing them")
    check(any(mod.type == "ARMATURE" and mod.object == template_arm for mod in template_mesh.modifiers)
          and template_mesh.parent == template_arm,
          "adopting weights binds mesh to the selected armature")
    check(template_mesh.vertex_groups.get("PreserveExistingWeight") is not None
          and template_mesh.vertex_groups.get("hips") is not None
          and abs(hips_group.weight(0) - 0.25) < 1e-6
          and max(abs(template_mesh.matrix_world[row][column] - world_before_adopt[row][column])
                  for row in range(4) for column in range(4)) < 1e-8,
          "adoption preserves vertex-group weights and world transform")
    wizard.step = 3
    _complete_step(bpy.context, wizard, 3)
    check(step_statuses(bpy.context, wizard)[3] == STEP_STATUS_COMPLETE,
          "fresh skinning result is shown complete")
    hips_group.add([0], 0.5, "REPLACE")
    _refresh_stale_results(sc, wizard)
    check(step_statuses(bpy.context, wizard)[3] == STEP_STATUS_WARNING,
          "editing vertex weights marks a completed skinning result stale")
    hips_group.add([0], 0.25, "REPLACE")
    _refresh_stale_results(sc, wizard)
    check(step_statuses(bpy.context, wizard)[3] == STEP_STATUS_COMPLETE,
          "restoring the recorded weights clears the stale warning")
    _complete_step(bpy.context, wizard, 3)
    original_vertex = template_mesh.data.vertices[0].co.copy()
    template_mesh.data.vertices[0].co.x += 0.01
    _refresh_stale_results(sc, wizard)
    check(step_statuses(bpy.context, wizard)[3] == STEP_STATUS_WARNING,
          "editing model geometry marks a completed result stale")
    template_mesh.data.vertices[0].co = original_vertex
    _refresh_stale_results(sc, wizard)
    wizard.step = 2
    _complete_step(bpy.context, wizard, 2)
    select(template_arm, active=template_arm)
    bpy.ops.object.mode_set(mode="EDIT")
    head_bone = template_arm.data.edit_bones["head"]
    original_tail = head_bone.tail.copy()
    head_bone.tail.x += 0.01
    bpy.ops.object.mode_set(mode="OBJECT")
    _refresh_stale_results(sc, wizard)
    check(step_statuses(bpy.context, wizard)[2] == STEP_STATUS_WARNING,
          "editing armature rest bones marks a completed placement result stale")
    bpy.ops.object.mode_set(mode="EDIT")
    template_arm.data.edit_bones["head"].tail = original_tail
    bpy.ops.object.mode_set(mode="OBJECT")
    _refresh_stale_results(sc, wizard)
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0.0, 1.0, 0.0))
    reweight_mesh = bpy.context.active_object
    reweight_mesh.name = "Wizard_ReweightMesh"
    legacy_group = reweight_mesh.vertex_groups.new(name="LegacyWeights")
    legacy_group.add(list(range(len(reweight_mesh.data.vertices))), 0.6, "REPLACE")
    reweight_world = reweight_mesh.matrix_world.copy()
    deform_state = {bone.name: bone.use_deform for bone in template_arm.data.bones}
    for bone in template_arm.data.bones:
        bone.use_deform = False
    try:
        _auto_weight_mesh(bpy.context, reweight_mesh, template_arm, replace_existing=True)
        no_deform_rejected = False
    except ValueError:
        no_deform_rejected = True
    check(no_deform_rejected and reweight_mesh.vertex_groups.get("LegacyWeights") is not None
          and abs(reweight_mesh.vertex_groups["LegacyWeights"].weight(0) - 0.6) < 1e-6,
          "reweighting refuses rigs without deform bones before deleting existing groups")
    for bone in template_arm.data.bones:
        bone.use_deform = bone.name == "hips"
    try:
        _auto_weight_mesh(bpy.context, reweight_mesh, template_arm, replace_existing=True)
        reweight_succeeded = True
    except Exception:
        reweight_succeeded = False
    finally:
        for bone in template_arm.data.bones:
            bone.use_deform = deform_state[bone.name]
    restored_on_failure = (reweight_mesh.vertex_groups.get("LegacyWeights") is not None
                           and abs(reweight_mesh.vertex_groups["LegacyWeights"].weight(0) - 0.6) < 1e-6
                           and not any(mod.type == "ARMATURE" for mod in reweight_mesh.modifiers)
                           and max(abs(reweight_mesh.matrix_world[row][column] - reweight_world[row][column])
                                   for row in range(4) for column in range(4)) < 1e-8)
    replaced_on_success = (reweight_mesh.vertex_groups.get("LegacyWeights") is None
                           and reweight_mesh.vertex_groups.get("hips") is not None
                           and any(mod.type == "ARMATURE" and mod.object == template_arm
                                   for mod in reweight_mesh.modifiers))
    check((replaced_on_success if reweight_succeeded else restored_on_failure),
          "delete-and-recompute " + ("replaces old groups on success" if reweight_succeeded
                                     else "restores old groups on failure"))
    reweight_data = reweight_mesh.data
    bpy.data.objects.remove(reweight_mesh, do_unlink=True)
    if reweight_data.users == 0:
        bpy.data.meshes.remove(reweight_data)
    select(template_arm, active=template_arm)
    template_errors = [issue for issue in R.analyze(template_arm) if issue.severity == "ERROR"]
    check(not template_errors, f"template passes rig validation: {[(issue.code, issue.message) for issue in template_errors]}")
    check(bpy.ops.adm.hw_confirm_placement() == {"FINISHED"}, "wizard confirms a valid manual placement")
    check(bpy.ops.adm.hw_generate_hitboxes() == {"FINISHED"}, "wizard generates bone hitboxes")
    hitbox_count = len(wizard.model_root.adm.hitboxes)
    check(hitbox_count >= 15, f"wizard creates standard anatomical hitbox areas ({hitbox_count})")
    check(bpy.ops.adm.hw_generate_hitboxes() == {"FINISHED"}
          and len(wizard.model_root.adm.hitboxes) == hitbox_count,
          "hitbox generation preserves existing records on repeat")
    check(bpy.ops.adm.hw_create_sockets() == {"FINISHED"}, "wizard creates standard humanoid sockets")
    generated_socket_names = {obj.adm.attachment_name for obj in bpy.data.objects
                              if obj.adm.adm_type == "ATTACHMENT"}
    check(SP.HUMANOID_SOCKET_NAMES <= generated_socket_names,
          "wizard creates all 20 standardized humanoid socket names")
    socket_count = len(generated_socket_names)
    check(bpy.ops.adm.hw_create_sockets() == {"FINISHED"}
          and len({obj.adm.attachment_name for obj in bpy.data.objects
                   if obj.adm.adm_type == "ATTACHMENT"}) == socket_count,
          "socket generation preserves existing markers on repeat")
    _hitbox_data, hitbox_report = ModelExporter(
        bpy.context, wizard.model_root, ExportOptions()).export()
    check(hitbox_report.ok, f"generated hitboxes validate for ADM export: {[e.message for e in hitbox_report.errors]}")
    check(len(hitbox_report.doc.get("hitboxes", [])) == hitbox_count,
          "generated hitbox records survive ADM export")
    check(SP.HUMANOID_SOCKET_NAMES <= {item["name"] for item in hitbox_report.doc.get("attachments", [])},
          "generated humanoid sockets survive ADM export")
    rest_before = template_arm.data.bones["rightUpperArm"].matrix_local.copy()
    wizard.test_pose = "RAISE_ARMS"
    check(bpy.ops.adm.hw_apply_test_pose() == {"FINISHED"}, "wizard applies a non-destructive rig test pose")
    check(abs(template_arm.pose.bones["rightUpperArm"].rotation_euler.y) > 0.1,
          "test pose moves the mapped pose bone")
    rest_after = template_arm.data.bones["rightUpperArm"].matrix_local
    check(max(abs(rest_after[row][column] - rest_before[row][column])
              for row in range(4) for column in range(4)) < 1e-8,
          "test pose leaves rest transforms unchanged")
    check(bpy.ops.adm.hw_reset_test_pose() == {"FINISHED"}, "wizard restores the saved test pose")
    check(abs(template_arm.pose.bones["rightUpperArm"].rotation_euler.y) < 1e-8,
          "test pose reset restores prior bone transforms")
    try:
        _generate_skeleton(bpy.context, wizard)
        duplicate_rejected = False
    except ValueError:
        duplicate_rejected = True
    check(duplicate_rejected and len([obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]) == 1,
          "repeat generation does not duplicate an existing rig")
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
    check(any(i.code == "CORRECTION_NOT_NORMALIZED" and "Normalize Corrections" in i.message
              and "ADM Skeleton & Animation" in i.message for i in wm.rig_report),
          "rig correction warning explains how to repair the rig")
    check({"SKIN_INFLUENCES", "SKIN_NOT_NORMALIZED"} <= report, f"skin issues reported {sorted(report)}")
    check("VALID" in wm.rig_report_title and "INVALID" not in wm.rig_report_title, wm.rig_report_title)

    check(bpy.ops.adm.normalize_corrections() == {"FINISHED"}, "normalize_corrections")
    check(not R.correction_issues(armA), "corrections normalized")
    correction_bone = armA.data.bones["LeftHand"]
    correction = tuple(correction_bone.adm.reference_correction)
    correction_bone.adm.reference_correction = tuple(-v for v in correction)
    check(not R.correction_issues(armA), "correction quaternion sign is equivalent")
    correction_bone.adm.reference_correction = correction
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
    rootA.scale = (2.0, 2.0, 2.0)
    posed_arm = armA.pose.bones["LeftUpperArm"]
    posed_arm.rotation_mode = "XYZ"
    posed_arm.rotation_euler = (0.25, 0.1, -0.3)
    bpy.context.view_layer.update()
    check(bpy.ops.adm.create_profile_sockets() == {"FINISHED"}, "create_profile_sockets")
    socks = {o.adm.attachment_name: o for o in bpy.data.objects if o.adm.adm_type == "ATTACHMENT"}
    check(armA.data.pose_position == "POSE" and abs(posed_arm.rotation_euler.x - 0.25) < 1e-6,
          "creating sockets restores the active pose")
    with RestPose(bpy.context):
        error = max(abs(value - (1.0 if row == column else 0.0))
                    for obj in socks.values()
                    for row, values in enumerate((rootA.matrix_world.inverted() @ obj.matrix_world).to_3x3())
                    for column, value in enumerate(values))
    check(error < 1e-5, f"sockets created during a pose have unit model-space rest frames ({error:.2e})")
    with RestPose(bpy.context):
        socket = socks["hand.left.support"]
        socket.matrix_world = (socket.matrix_world @ Matrix.Rotation(0.3, 4, "X")
                               @ Matrix.Diagonal((1.2, 0.9, 1.0, 1.0)))
        bpy.context.view_layer.update()
        socket_position = socket.matrix_world.translation.copy()
        legacy = socks["hand.left"]
        legacy_world = legacy.matrix_world.copy()
        legacy.matrix_world = legacy.matrix_world @ Matrix.Rotation(0.2, 4, "Z")
        bpy.context.view_layer.update()
        legacy_rotated = legacy.matrix_world.copy()
    try:
        ModelExporter(bpy.context, rootA, ExportOptions()).export()
        check(False, "export rejects invalid socket frames")
    except ExportError as exc:
        check("HUMANOID_SOCKET_FRAME" in str(exc) and "Align Socket Frames" in str(exc),
              "export error identifies invalid socket frames and gives the repair instruction")
    check(bpy.ops.adm.align_socket_frames() == {"FINISHED"}, "align socket frames operator")
    with RestPose(bpy.context):
        frame = rootA.matrix_world.inverted() @ socket.matrix_world
        check((socket.matrix_world.translation - socket_position).length < 1e-5
              and max(abs(frame[r][c] - (1.0 if r == c else 0.0))
                      for r in range(3) for c in range(3)) < 1e-5,
              "socket frame repair preserves the authored rest position and aligns axes/scale")
        check(max(abs(legacy.matrix_world[r][c] - legacy_rotated[r][c])
                  for r in range(4) for c in range(4)) < 1e-5,
              "standard socket repair leaves legacy/custom frames unchanged")
        legacy.matrix_world = legacy_world
    check(armA.data.pose_position == "POSE" and abs(posed_arm.rotation_euler.x - 0.25) < 1e-6,
          "socket frame repair restores the active pose")
    posed_arm.rotation_euler = (0.0, 0.0, 0.0)
    rootA.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    for t in SP.socket_templates("humanoid.vrm1"):
        o = socks.get(t["name"])
        ok = o is not None and o.parent == armA and o.parent_type == "BONE" and o.parent_bone == rb[t["role"]]
        if ok:
            head = armA.matrix_world @ armA.data.bones[o.parent_bone].head_local
            ok = (o.matrix_world.translation - head).length < 1e-6 and \
                ang_deg(o.matrix_world.to_quaternion(), rootA.matrix_world.to_quaternion()) < 1e-3
        check(ok, f"socket {t['name']} on {t['role']}")
    authored_socket = socks["back.backpack"]
    authored_socket.matrix_world = Matrix.Translation(Vector((0.04, 0.03, -0.02))) @ authored_socket.matrix_world
    bpy.context.view_layer.update()
    bpy.ops.mesh.primitive_cube_add(size=0.06)
    rigid_segment = bpy.context.object
    rigid_segment.name = "LeftHandRigidSegment"
    rigid_segment.parent = armA
    rigid_segment.parent_type = "BONE"
    rigid_segment.parent_bone = "LeftHand"
    rigid_segment.matrix_parent_inverse = Matrix.Identity(4)
    rigid_segment.matrix_world = Matrix.Translation(armA.matrix_world @ armA.pose.bones["LeftHand"].head)
    bpy.context.view_layer.update()

    # ------------------------------------------------------------------ export -> import
    print("== skeleton export")
    noise = Matrix.Diagonal((1.000003, 1.0000007, 1.0, 1.0))
    check("scale" not in cv.node_transform_fields(noise, force_trs=True),
          "bone transform serialization removes float32 near-unit scale noise")
    check("scale" in cv.node_transform_fields(noise)
          and "scale" in cv.node_transform_fields(
              Matrix.Diagonal((1.001, 1.0, 1.0, 1.0)), force_trs=True),
          "scale cleanup preserves object transforms and meaningful bone scale")
    exp = ModelExporter(bpy.context, rootA, ExportOptions())
    data, rep = exp.export()
    check(rep.ok, f"model valid {[str(e) for e in rep.errors[:4]]}")
    doc = rep.doc
    prof = doc["skeletonProfiles"][0]
    check(prof["id"] == "humanoid.vrm1" and prof["referencePose"] == "T", "profile + reference pose declared")
    check(doc["extensions"][K.HUMANOID_SOCKETS_EXT] == {"version": K.HUMANOID_SOCKETS_VERSION}
          and K.HUMANOID_SOCKETS_EXT in doc["extensionsRequired"],
          "humanoid socket capability declared and required")
    node_name = {i: n.get("name") for i, n in enumerate(doc["nodes"])}
    check({node_name[i]: r for r, i in prof["roles"].items()} == rolesA, "roles exported by node")
    check(set(prof.get("referenceCorrection", {})) == set(rolesA.values()), "normalized corrections exported")

    print("== serialized rest corrections")
    scaled_arm, scaled_roles = build_humanoid("ScaledRest", helper=False)
    scaled_arm.data.adm.profile = SP.HUMANOID
    scaled_arm.data.adm.export_profile = True
    for bone_name, role in scaled_roles.items():
        scaled_arm.data.bones[bone_name].adm.role = role
    scaled_arm.scale = (1.0, 1.15, 0.85)
    scaled_body = add_body(scaled_arm, "")
    select(scaled_arm, scaled_body, active=scaled_arm)
    R.apply_normalized_corrections(scaled_arm)
    check(not R.correction_issues(scaled_arm), "scaled rig corrections match serialized local rotations")
    try:
        scaled_data, scaled_report = ModelExporter(
            bpy.context, None, ExportOptions(selected_only=True)).export()
        check(scaled_report.ok, "scaled humanoid exports with valid serialized corrections")
    except ExportError as exc:
        check(False, f"scaled humanoid export: {exc}")
    scaled_arm_data = scaled_arm.data
    bpy.data.objects.remove(scaled_body, do_unlink=True)
    bpy.data.objects.remove(scaled_arm, do_unlink=True)
    if scaled_arm_data.users == 0:
        bpy.data.armatures.remove(scaled_arm_data)

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
    check(SP.HUMANOID_SOCKET_NAMES <= set(att), "all registered humanoid equipment sockets exported")
    missing_socket_ext = deepcopy(doc)
    missing_socket_ext["extensions"].pop(K.HUMANOID_SOCKETS_EXT)
    socket_ext_report = validate_adm(write_container(K.ADM_MAGIC, missing_socket_ext, rep.bin))
    check("HUMANOID_SOCKET_EXTENSION" in {e.code for e in socket_ext_report.errors},
          "standard socket without extension is rejected")
    optional_socket_ext = deepcopy(doc)
    optional_socket_ext["extensionsRequired"].remove(K.HUMANOID_SOCKETS_EXT)
    optional_report = validate_adm(write_container(K.ADM_MAGIC, optional_socket_ext, rep.bin))
    check("HUMANOID_SOCKET_REQUIRED" in {e.code for e in optional_report.errors},
          "humanoid socket capability cannot be optional")
    empty_socket_ext = deepcopy(doc)
    empty_socket_ext["attachments"] = [a for a in empty_socket_ext["attachments"]
                                       if a["name"] not in SP.HUMANOID_SOCKET_NAMES]
    empty_report = validate_adm(write_container(K.ADM_MAGIC, empty_socket_ext, rep.bin))
    check("HUMANOID_SOCKET_EMPTY" in {e.code for e in empty_report.errors},
          "socket capability without a registered attachment is rejected")
    bad_socket_parent = deepcopy(doc)
    next(a for a in bad_socket_parent["attachments"] if a["name"] == "hand.right.grip")["node"] = \
        prof["roles"]["leftHand"]
    parent_report = validate_adm(write_container(K.ADM_MAGIC, bad_socket_parent, rep.bin))
    check("HUMANOID_SOCKET_PARENT" in {e.code for e in parent_report.errors},
          "socket on the wrong role is rejected")
    bad_socket_fallback = deepcopy(doc)
    next(a for a in bad_socket_fallback["attachments"] if a["name"] == "back.backpack")["node"] = \
        prof["roles"]["spine"]
    fallback_report = validate_adm(write_container(K.ADM_MAGIC, bad_socket_fallback, rep.bin))
    check("HUMANOID_SOCKET_PARENT" in {e.code for e in fallback_report.errors},
          "lower-priority fallback is rejected when the primary role is mapped")
    bad_socket_version = deepcopy(doc)
    bad_socket_version["extensions"][K.HUMANOID_SOCKETS_EXT]["version"] = "2.0.0"
    version_report = validate_adm(write_container(K.ADM_MAGIC, bad_socket_version, rep.bin))
    check("HUMANOID_SOCKET_VERSION" in {e.code for e in version_report.errors},
          "unknown socket extension version is rejected")
    bad_socket_frame = deepcopy(doc)
    socket_node = att["back.backpack"]
    bad_socket_frame["nodes"][socket_node].pop("matrix", None)
    bad_socket_frame["nodes"][socket_node]["rotation"] = [0.0, 0.0, 0.70710678, 0.70710678]
    frame_report = validate_adm(write_container(K.ADM_MAGIC, bad_socket_frame, rep.bin))
    check("HUMANOID_SOCKET_FRAME" in {e.code for e in frame_report.errors},
          "noncanonical socket frame is rejected")
    skin = doc["skins"][prof["skin"]]
    ibm0 = read_accessor_np(doc, rep.bin, skin["inverseBindMatrices"])
    joints0 = [node_name[j] for j in skin["joints"]]
    path = os.path.join(tmp, "heroA.adm")
    with open(path, "wb") as fh:
        fh.write(data)
    check(validate_file(path).ok, "validate_file heroA.adm")
    missing_joint_display = deepcopy(doc)
    missing_joint_display["nodes"][skin["joints"][0]]["extensions"].pop(K.JOINT_DISPLAY_EXT)
    missing_display_report = validate_adm(write_container(K.ADM_MAGIC, missing_joint_display, rep.bin))
    check("JOINT_DISPLAY_REQUIRED" in {e.code for e in missing_display_report.errors},
          "required joint display data is enforced")
    zero_joint_tail = deepcopy(doc)
    zero_joint_tail["nodes"][skin["joints"][0]]["extensions"][K.JOINT_DISPLAY_EXT]["tail"] = [0, 0, 0]
    zero_tail_report = validate_adm(write_container(K.ADM_MAGIC, zero_joint_tail, rep.bin))
    check("JOINT_DISPLAY_TAIL" in {e.code for e in zero_tail_report.errors},
          "zero-length joint display tail is rejected")

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
             "LeftLowerLeg": Euler((0.15, 0.0, 0.45)), "Spine": Euler((0.2, 0.1, 0.0)),
             "Head": Euler((0.0, 0.4, 0.2))}
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
    check({("bone", "leftUpperArm"), ("bone", "leftLowerArm"), ("bone", "leftLowerLeg"),
           ("bone", "spine"), ("bone", "head"),
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
                     key.key_blocks["jawOpen"].value, evaluated_world_vertices(bodyA),
                     rigid_segment.matrix_world.copy(),
                     {b.name: armA.matrix_world @ armA.pose.bones[b.name].matrix
                      for b in armA.data.bones})

    lvl, reasons, _w = check_library_compat(bpy.context, armB, rep.doc)
    check(lvl == SK.SEMANTIC, f"compat level {lvl} {reasons}")
    select(armB)
    hips_bone = next(bone for bone in armB.data.bones if bone.adm.role == "hips")
    for missing in (True, False):
        hips_bone.adm.use_reference_correction = not missing
        if not missing:
            hips_bone.adm.reference_correction = (
                R.normalized_correction(armB, hips_bone) @ Quaternion((1.0, 0.0, 0.0), 0.4))
        before = (hips_bone.adm.use_reference_correction, tuple(hips_bone.adm.reference_correction))
        lvl, reasons, _w = check_library_compat(bpy.context, armB, rep.doc)
        check(lvl == SK.INCOMPATIBLE
              and sum("Normalize Corrections" in reason and "ADM Skeleton & Animation" in reason
                      for reason in reasons) == 1,
              f"{'missing' if missing else 'stale'} correction error includes one repair instruction")
        try:
            import_library(bpy.context, lib_path, AnimImportOptions(armature=armB))
            check(False, "strict import refuses invalid reference corrections")
        except ImportError_ as exc:
            check("Normalize Corrections" in str(exc) and "bypasses validation" in str(exc),
                  "strict import error includes the repair and explains the bypass risk")
        check(before == (hips_bone.adm.use_reference_correction,
                         tuple(hips_bone.adm.reference_correction)),
              "compatibility checks do not silently change reference corrections")
        check(bpy.ops.adm.normalize_corrections() == {"FINISHED"}
              and check_library_compat(bpy.context, armB, rep.doc)[0] == SK.SEMANTIC,
              "following the correction repair instruction restores semantic compatibility")
    check(bpy.ops.adm.anim_compat_test("EXEC_DEFAULT", filepath=lib_path) == {"FINISHED"} and
          ": SEMANTIC" in wm.compat_title and any(i.code == "CLIP" and i.path == "swing" for i in wm.compat_report),
          f"anim_compat_test: {wm.compat_title}")
    imp, slib = import_library(bpy.context, lib_path, AnimImportOptions(armature=armB))
    check(not imp.warnings, f"retarget import clean {imp.warnings}")
    check(slib.clips[0].title == "Swing" and slib.clips[0].description == "Arm swing with jaw open",
          "clip metadata preserved")
    rootA_inv = rootA.matrix_world.inverted()
    rootB_inv = rootB.matrix_world.inverted()
    for f, (deltas, handA, jaw, _vertices, _rigid, _poses) in sample.items():
        sc.frame_set(f)
        bpy.context.view_layer.update()
        worst = max(ang_deg(world_delta(armB, "b_" + n), deltas[n]) for n in keyed)
        check(worst < ANG_TOL_DEG, f"frame {f}: world rotation deltas match ({worst:.4f} deg)")
        handB = armB.matrix_world @ armB.pose.bones["b_LeftHand"].head
        d = ((rootB_inv @ handB) / 1.25 - (rootA_inv @ handA)).length
        check(d < 1e-4, f"frame {f}: hand position scales with proportions ({d:.2e} m)")
        jb = bodyB.data.shape_keys.key_blocks["Jaw_Open"].value
        check(abs(jb - jaw) < 1e-4, f"frame {f}: ARKit jawOpen -> 'Jaw_Open' {jb:.4f} vs {jaw:.4f}")

    armB.rotation_mode = "QUATERNION"
    armB.rotation_quaternion = Euler((0.37, -0.21, 0.49)).to_quaternion()
    bpy.context.view_layer.update()
    R.apply_normalized_corrections(armB)
    rotated_imp, _ = import_library(bpy.context, lib_path, AnimImportOptions(armature=armB, strict=False))
    check(any("REFERENCE_POSE" in warning for warning in rotated_imp.warnings),
          "rotated-armature test explicitly overrides the changed reference pose")
    for f in (6, 11, 16):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        worst = max(ang_deg(
            (R.model_matrix(armB) @ armB.pose.bones["b_" + n].matrix
             @ cv.bone_frame_correction(armB.data.bones["b_" + n])).to_quaternion()
            @ (R.model_matrix(armB) @ armB.data.bones["b_" + n].matrix_local
               @ cv.bone_frame_correction(armB.data.bones["b_" + n])).to_quaternion().inverted(),
            world_delta(armA, n)) for n in keyed)
        check(worst < ANG_TOL_DEG, f"frame {f}: semantic rotations account for armature object rotation "
              f"({worst:.4f} deg)")

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
    try:
        AnimExporter(bpy.context, dlib).export()
        check(False, "ADM 1.0 exporter must reject a provisional animal profile")
    except ExportError as exc:
        check("proposal outside ADM 1.0" in str(exc), "provisional animal library export refused")
    proposal_doc = {
        "library": {"targetProfile": "animal.canine.v1", "binding": "SEMANTIC"},
        "clips": [{"channels": [{"target": {"kind": "bone", "role": "leftHindUpperLeg"}}]}],
    }
    lvl, reasons, _ = check_library_compat(bpy.context, quads["Dog2"], proposal_doc)
    check(lvl == SK.PROVISIONAL_SEMANTIC, f"canine -> canine: {lvl}")
    lvl, reasons, _ = check_library_compat(bpy.context, quads["Dog2"], proposal_doc, allow_provisional=False)
    check(lvl == SK.INCOMPATIBLE, "allow_provisional=False refuses provisional binding")
    lvl, reasons, _ = check_library_compat(bpy.context, quads["Horse"], proposal_doc)
    check(lvl == SK.INCOMPATIBLE, f"canine -> equine: {lvl} {reasons[:1]}")
    lvl, _r, _ = check_library_compat(bpy.context, armB, proposal_doc)
    check(lvl == SK.INCOMPATIBLE, f"canine -> humanoid: {lvl}")
    hum_doc = validate_file(lib_path).doc
    lvl, _r, _ = check_library_compat(bpy.context, dog, hum_doc)
    check(lvl == SK.INCOMPATIBLE, f"humanoid -> canine: {lvl}")

    # ------------------------------------------------------------------ re-import heroA
    print("== skeleton round-trip (fresh file)")
    origin = {n: (armA.matrix_world @ armA.data.bones[n].matrix_local) for n in rolesA}
    visible_bones = {
        b.name: (armA.matrix_world @ b.head_local, armA.matrix_world @ b.tail_local,
                 armA.matrix_world @ b.matrix_local)
        for b in armA.data.bones
    }
    weights0 = bone_weights(bodyA)
    corr0 = {b.name: tuple(b.adm.reference_correction) for b in armA.data.bones if b.adm.role}
    rootA_w = rootA.matrix_world.copy()
    bpy.ops.wm.read_homefile(use_empty=True)
    ensure_role_names()
    root2 = ModelImporter(bpy.context, path, ImportOptions()).run()
    sc = bpy.context.scene
    arm2 = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    body2 = next(o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups)
    rigid2 = bpy.data.objects.get("LeftHandRigidSegment")
    check(arm2.data.adm.profile_id == "humanoid.vrm1", "profile id imported")
    check({b.name: b.adm.role for b in arm2.data.bones if b.adm.role} == rolesA, "roles imported")
    rel = root2.matrix_world @ rootA_w.inverted()
    dm = max(max(abs(a - b) for ra, rb_ in zip(
        rel @ origin[n], arm2.matrix_world @ arm2.data.bones[n].matrix_local
        @ cv.bone_frame_correction(arm2.data.bones[n])) for a, b in zip(ra, rb_)) for n in rolesA)
    check(dm < POS_TOL, f"ADM joint frames preserved ({dm:.2e})")
    display_metadata = sum(
        K.JOINT_DISPLAY_EXT in node.get("extensions", {})
        for node in doc["nodes"]
    )
    check(display_metadata == len(visible_bones),
          f"Blender bone display metadata exported ({display_metadata}/{len(visible_bones)})")
    visible_dev = max(
        max((rel @ head - arm2.matrix_world @ arm2.data.bones[name].head_local).length,
            (rel @ tail - arm2.matrix_world @ arm2.data.bones[name].tail_local).length,
            max(abs(a - b) for ra, rb_ in zip(
                rel @ matrix, arm2.matrix_world @ arm2.data.bones[name].matrix_local)
                for a, b in zip(ra, rb_)))
        for name, (head, tail, matrix) in visible_bones.items()
    )
    check(visible_dev < DISPLAY_TOL, f"visible bone shape preserved ({visible_dev:.2e})")
    check(rigid2 is not None and not rigid2.vertex_groups
          and not any(m.type == "ARMATURE" for m in rigid2.modifiers)
          and rigid2.parent_type == "BONE",
          "rigid segment keeps its bone attachment without invented skin weights")
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
    socket_objs2 = {o.adm.attachment_name: o for o in bpy.data.objects if o.adm.adm_type == "ATTACHMENT"}
    socks2 = {name: o.parent_bone for name, o in socket_objs2.items()}
    check(socks2.get("hand.left") == "LeftHand", f"socket parent preserved {socks2.get('hand.left')}")
    check(SP.HUMANOID_SOCKET_NAMES <= set(socks2), "all equipment socket names survive import")
    data2, rep2 = ModelExporter(bpy.context, root2, ExportOptions()).export()
    check(rep2.ok, "re-export valid")
    check(rep2.doc["extensions"][K.HUMANOID_SOCKETS_EXT] == {"version": K.HUMANOID_SOCKETS_VERSION}
          and SP.HUMANOID_SOCKET_NAMES <= {a["name"] for a in rep2.doc.get("attachments", [])},
          "socket extension round-trips")
    att2 = {a["name"]: a["node"] for a in rep2.doc.get("attachments", [])}
    backpack_frame0 = node_world_matrix(doc, att["back.backpack"])
    backpack_frame2 = node_world_matrix(rep2.doc, att2["back.backpack"])
    backpack_frame_dev = max(abs(a - b) for a, b in zip(backpack_frame0, backpack_frame2))
    check(backpack_frame_dev < POS_TOL, f"authored backpack socket frame survives round-trip ({backpack_frame_dev:.2e})")
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
    rigid_node = next(n for n in rep2.doc["nodes"] if n.get("name") == "LeftHandRigidSegment")
    check("skin" not in rigid_node, "rigid segment remains unskinned after round-trip")

    semantic_doc = validate_file(lib_path).doc
    lvl, reasons, _ = check_library_compat(bpy.context, arm2, semantic_doc)
    check(lvl == SK.SEMANTIC, f"corrected-frame semantic compatibility: {lvl} {reasons}")
    imp2, _ = import_library(bpy.context, lib_path, AnimImportOptions(armature=arm2))
    check(not imp2.warnings, f"corrected-frame animation import clean {imp2.warnings}")
    for f, (deltas, _handA, _jaw, verticesA, rigidA, posesA) in sample.items():
        sc.frame_set(f)
        bpy.context.view_layer.update()
        worst = max(ang_deg(corrected_world_delta(arm2, n), q) for n, q in deltas.items())
        check(worst < ANG_TOL_DEG, f"frame {f}: corrected ADM joint rotations match ({worst:.4f} deg)")
        pose_error = max(max(abs(a - b) for rowa, rowb in zip(rel @ posesA[n],
                          arm2.matrix_world @ arm2.pose.bones[n].matrix
                          @ cv.bone_frame_correction(arm2.data.bones[n]))
                             for a, b in zip(rowa, rowb)) for n in posesA)
        check(pose_error < POS_TOL, f"frame {f}: ADM joint world matrices match ({pose_error:.2e})")
        vertices2 = evaluated_world_vertices(body2)
        verticesA = sorted(verticesA, key=lambda p: tuple(round(v, 6) for v in p))
        vertices2 = sorted(vertices2, key=lambda p: tuple(round(v, 6) for v in p))
        vertex_error = max((rel @ a - b).length for a, b in zip(verticesA, vertices2))
        check(vertex_error < 2e-3, f"frame {f}: skinned vertex positions match ({vertex_error:.2e} m)")
        rigid_error = max(abs(a - b) for rowa, rowb in zip(rel @ rigidA, rigid2.matrix_world)
                          for a, b in zip(rowa, rowb))
        check(rigid_error < POS_TOL, f"frame {f}: rigid bone-linked segment follows ADM joint motion ({rigid_error:.2e})")

    exact_lib = sc.adm_anim.libraries.add()
    exact_lib.lib_id, exact_lib.title, exact_lib.description = "human@test@exact", "Exact", "Exact joint animation"
    exact_lib.armature, exact_lib.binding = arm2, "EXACT"
    exact_clip = exact_lib.clips.add()
    exact_clip.clip_id, exact_clip.title, exact_clip.description = "joints", "Joints", "Elbow and knee"
    exact_action = bpy.data.actions.new("ExactJointAnimation")
    exact_clip.action = exact_action
    exact_clip.use_action_range = True
    arm2.animation_data_create().action = exact_action
    for name in ("LeftLowerArm", "LeftLowerLeg"):
        pb = arm2.pose.bones[name]
        pb.rotation_mode = "QUATERNION"
        for frame, angle in ((1, 0.0), (11, 0.7)):
            sc.frame_set(frame)
            pb.rotation_quaternion = Euler((angle, angle * 0.2, -angle * 0.15)).to_quaternion()
            pb.keyframe_insert("rotation_quaternion")
    exact_samples = {}
    for frame in (1, 6, 11):
        sc.frame_set(frame)
        bpy.context.view_layer.update()
        exact_samples[frame] = {
            b.name: arm2.matrix_world @ arm2.pose.bones[b.name].matrix
            @ cv.bone_frame_correction(arm2.data.bones[b.name])
            for b in arm2.data.bones
        }
    exact_data, exact_report = AnimExporter(bpy.context, exact_lib).export()
    check(exact_report is not None and exact_report.ok, "EXACT animation export with corrected bone frames")
    exact_path = os.path.join(tmp, "exact_joint_animation.adm_anim")
    with open(exact_path, "wb") as fh:
        fh.write(exact_data)
    root3 = ModelImporter(bpy.context, path, ImportOptions()).run()
    arm3 = next(o for o in root3.children_recursive if o.type == "ARMATURE")
    exact_import, _ = import_library(bpy.context, exact_path, AnimImportOptions(armature=arm3))
    check(not exact_import.warnings, f"EXACT animation import clean {exact_import.warnings}")
    for frame, expected in exact_samples.items():
        sc.frame_set(frame)
        bpy.context.view_layer.update()
        pose_error = max(max(abs(a - b) for rowa, rowb in zip(
            expected[name], arm3.matrix_world @ arm3.pose.bones[name].matrix
            @ cv.bone_frame_correction(arm3.data.bones[name]))
                              for a, b in zip(rowa, rowb)) for name in expected)
        check(pose_error < POS_TOL, f"EXACT frame {frame}: corrected joint matrices match ({pose_error:.2e})")

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
