"""Blender integration test for Mixamo action mapping and ADM retargeting."""

import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

import bpy  # noqa: E402
from bpy_extras import anim_utils  # noqa: E402
from mathutils import Vector  # noqa: E402

import adm_blender  # noqa: E402
from adm_blender.blender.export_anim import AnimExporter  # noqa: E402
from adm_blender.blender.mixamo_import import retarget_mixamo_action  # noqa: E402
from adm_blender.blender import rig as rig_tools  # noqa: E402
from adm_blender.core.validate import validate_anim  # noqa: E402
from adm_blender.tests.test_skeleton_profiles import humanoid_rig  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("  ok   " + message)


def _mixamo_bone_name(role):
    center = {
        "hips": "Hips", "spine": "Spine", "chest": "Spine1", "upperChest": "Spine2",
        "neck": "Neck", "head": "Head",
    }
    if role in center:
        return "mixamorig:" + center[role]
    names = {
        "Shoulder": "Shoulder", "UpperArm": "Arm", "LowerArm": "ForeArm", "Hand": "Hand",
        "UpperLeg": "UpLeg", "LowerLeg": "Leg", "Foot": "Foot", "Toes": "ToeBase",
    }
    side, stem = next((role[:-len(marker)], marker) for marker in names if role.endswith(marker))
    return "mixamorig:" + side.capitalize() + names[stem]


def _make_armature(name, mixamo=False, mirrored=False):
    joints, assignments = humanoid_rig()
    role_by_name = dict(assignments)
    names = {
        bone: _mixamo_bone_name(role) if mixamo else f"{name}_{role}"
        for bone, role in assignments
    }
    mapped = {
        names[bone]: {
            "parent": names[joint["parent"]] if joint["parent"] else None,
            "head": ((-joint["head"][0], joint["head"][1], -joint["head"][2])
                     if mirrored else joint["head"]),
        }
        for bone, joint in joints.items()
    }
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    children = {}
    for bone, joint in mapped.items():
        children.setdefault(joint["parent"], []).append(bone)
    for bone, joint in mapped.items():
        edit_bone = data.edit_bones.new(bone)
        p = joint["head"]
        edit_bone.head = (p[0], -p[2], p[1])
        kids = children.get(bone, [])
        if kids:
            child = mapped[min(kids)]["head"]
            edit_bone.tail = (child[0], -child[2], child[1])
        else:
            edit_bone.tail = edit_bone.head + Vector((0.0, 0.0, 0.08))
    for bone, joint in mapped.items():
        if joint["parent"]:
            data.edit_bones[bone].parent = data.edit_bones[joint["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    if not mixamo:
        arm.data.adm.profile = "humanoid.vrm1"
        for bone, role in role_by_name.items():
            arm.data.bones[names[bone]].adm.role = role
    return arm, names


def _make_action(arm, source_names, name):
    action = bpy.data.actions.new(name)
    slot = action.slots.new(id_type="OBJECT", name=arm.name)
    channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
    hips_path = f'pose.bones["{source_names["B_hips"]}"]'
    _add_curve(channelbag, hips_path + ".rotation_quaternion", 0, 1.0, math.cos(0.2))
    _add_curve(channelbag, hips_path + ".rotation_quaternion", 1, 0.0, math.sin(0.2))
    _add_curve(channelbag, hips_path + ".rotation_quaternion", 2, 0.0, 0.0)
    _add_curve(channelbag, hips_path + ".rotation_quaternion", 3, 0.0, 0.0)
    _add_curve(channelbag, hips_path + ".location", 1, 0.0, 0.1)
    for role, angle in (("leftUpperArm", 0.3), ("leftLowerArm", 0.2),
                        ("rightUpperArm", -0.3), ("rightLowerArm", -0.2)):
        path = f'pose.bones["{source_names["B_" + role]}"].rotation_quaternion'
        _add_curve(channelbag, path, 0, 1.0, math.cos(angle / 2))
        _add_curve(channelbag, path, 1, 0.0, math.sin(angle / 2))
        _add_curve(channelbag, path, 2, 0.0, 0.0)
        _add_curve(channelbag, path, 3, 0.0, 0.0)
    animation_data = arm.animation_data_create()
    animation_data.action = action
    animation_data.action_slot = slot
    return action


def _add_curve(channelbag, path, index, start, end):
    curve = channelbag.fcurves.new(data_path=path, index=index)
    curve.keyframe_points.add(2)
    curve.keyframe_points.foreach_set("co", (1.0, start, 32.0, end))
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"
    curve.update()


def run():
    bpy.ops.wm.read_homefile(use_empty=True)
    adm_blender.register()
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    source, source_names = _make_armature("MixamoSource", mixamo=True)
    target, _target_names = _make_armature("Target")

    action = _make_action(source, source_names, "Mixamo Walk")

    importer, library, clip, warnings = retarget_mixamo_action(
        bpy.context, source, action, target,
        library_id="mixamo@animations",
        library_title="Mixamo Animations",
        library_description="Imported Mixamo clips",
        clip_id="walk",
        clip_title="Walk",
        clip_description="A 32-frame Mixamo walk",
    )
    check(not warnings and not importer.warnings, "semantic Mixamo retarget completes without warnings")
    check(len(scene.adm_anim.libraries) == 1 and library.lib_id == "mixamo@animations",
          "new animation library is created")
    check(clip.action.frame_range[0] == 1 and clip.action.frame_range[1] == 32,
          "the imported action retains the full 32-frame range")
    target_bag = anim_utils.action_get_channelbag_for_slot(clip.action, clip.action.slots[0])
    check(any(fc.data_path == 'pose.bones["Target_hips"].location' and fc.array_index == 1
              for fc in target_bag.fcurves),
          "extracted hips translation is retargeted to the target rig")

    _, appended_library, appended_clip, _ = retarget_mixamo_action(
        bpy.context, source, action, target,
        library_index=0,
        clip_id="run",
        clip_title="Run",
        clip_description="A second Mixamo clip",
    )
    check(appended_library == library and appended_clip.clip_id == "run"
          and len(appended_library.clips) == 2 and len(scene.adm_anim.libraries) == 1,
          "a clip appends to the selected library without leaving a temporary library")
    data, report = AnimExporter(bpy.context, appended_library).export()
    doc = validate_anim(data).doc
    timing = doc["clips"][0]["extensions"]["ADM_animation_timing_v1"]
    check(report.ok and timing["frameStart"] == 1 and timing["frameEnd"] == 32,
          "the exported ADM clip retains its source frame timing")

    backwards_source, backwards_names = _make_armature(
        "BackwardsMixamoSource", mixamo=True, mirrored=True)
    backwards_action = _make_action(backwards_source, backwards_names, "Backward Walk")
    _, facing_library, _, facing_warnings = retarget_mixamo_action(
        bpy.context, backwards_source, backwards_action, target,
        library_id="mixamo@facing_fix",
        library_title="Facing Fix",
        library_description="Automatic source facing correction",
        clip_id="walk",
        clip_title="Walk",
        clip_description="A source rig facing the opposite direction",
    )
    check(any("180 degrees about the up axis" in warning for warning in facing_warnings)
          and not any(issue.code == "REFERENCE_FACING" for issue in rig_tools.analyze(backwards_source)),
          f"opposite-facing Mixamo rigs are auto-aligned to ADM forward "
          f"(warnings={facing_warnings!r}, errors="
          f"{[issue.code for issue in rig_tools.analyze(backwards_source) if issue.severity == 'ERROR']!r})")
    check(facing_library.lib_id == "mixamo@facing_fix",
          "the auto-aligned action still exports into its requested library")
    scene.frame_set(32)
    bpy.context.view_layer.update()
    arm_roles = ("hips", "leftUpperArm", "leftLowerArm", "leftHand",
                 "rightUpperArm", "rightLowerArm", "rightHand")
    pose_errors = []
    for role in arm_roles:
        source_bone = next(bone for bone in backwards_source.data.bones if bone.adm.role == role)
        target_bone = next(bone for bone in target.data.bones if bone.adm.role == role)
        source_pose = backwards_source.matrix_world @ backwards_source.pose.bones[source_bone.name].matrix
        target_pose = target.matrix_world @ target.pose.bones[target_bone.name].matrix
        source_rest = backwards_source.matrix_world @ source_bone.matrix_local
        target_rest = target.matrix_world @ target_bone.matrix_local
        source_delta = source_pose.to_quaternion() @ source_rest.to_quaternion().inverted()
        target_delta = target_pose.to_quaternion() @ target_rest.to_quaternion().inverted()
        angle = source_delta.rotation_difference(target_delta).angle
        pose_errors.append((role, (source_pose.translation - target_pose.translation).length,
                            min(angle, abs(2 * math.pi - angle))))
    check(max(position for _, position, _ in pose_errors) < 1e-5
          and max(angle for _, _, angle in pose_errors) < math.radians(0.1),
          f"aligned source and target arm poses match "
          f"(errors={[(role, f'{position:.2e} m', f'{math.degrees(angle):.3g} deg') for role, position, angle in pose_errors]!r})")

    scene.frame_start, scene.frame_end = 1, 32
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    with tempfile.TemporaryDirectory(prefix="adm_mixamo_fbx_test_") as folder:
        fbx_path = os.path.join(folder, "mixamo.fbx")
        export_result = bpy.ops.export_scene.fbx(
            filepath=fbx_path,
            use_selection=True,
            object_types={"ARMATURE"},
            add_leaf_bones=False,
            bake_anim=True,
            bake_anim_use_all_actions=False,
            bake_anim_use_nla_strips=False,
            bake_anim_force_startend_keying=True,
        )
        check("FINISHED" in export_result and os.path.isfile(fbx_path),
              "a Mixamo-style animated armature exports to FBX")
        target_fbx, _ = _make_armature("FBXTarget")
        objects_before = set(bpy.data.objects)
        collections_before = set(bpy.data.collections)
        scene.render.fps = 24
        operator_result = bpy.ops.import_anim.mixamo_fbx(
            filepath=fbx_path,
            target_armature=target_fbx.name,
            library_mode="NEW",
            library_id="mixamo@fbx",
            library_title="Mixamo FBX",
            library_description="FBX operator integration test",
            clip_id="fbx_walk",
            clip_title="FBX Walk",
            clip_description="Retargeted from a temporary FBX",
        )
        fbx_library = next(lib for lib in scene.adm_anim.libraries if lib.lib_id == "mixamo@fbx")
        check(operator_result == {"FINISHED"} and len(fbx_library.clips) == 1,
              "the FBX wizard imports and retargets the source action")
        check(set(bpy.data.objects) == objects_before,
              "temporary source FBX objects are cleaned up after success")
        check(scene.render.fps == 30
              and fbx_library.clips[0].action.frame_range[0] == 1
              and fbx_library.clips[0].action.frame_range[1] == 32,
              "FBX source frame rate and full frame range survive at a different scene rate")
        check(set(bpy.data.collections) == collections_before,
              "empty collections created by the temporary FBX import are removed")
        fbx_index = next(index for index, lib in enumerate(scene.adm_anim.libraries)
                         if lib.lib_id == "mixamo@fbx")
        append_result = bpy.ops.import_anim.mixamo_fbx(
            filepath=fbx_path,
            target_armature=target_fbx.name,
            library_mode="EXISTING",
            existing_library=str(fbx_index),
            clip_id="fbx_run",
            clip_title="FBX Run",
            clip_description="Appended from a temporary FBX",
        )
        check(append_result == {"FINISHED"} and len(fbx_library.clips) == 2,
              "the FBX wizard appends to the selected existing library")

    print("Mixamo animation integration test passed.")


if __name__ == "__main__":
    run()
