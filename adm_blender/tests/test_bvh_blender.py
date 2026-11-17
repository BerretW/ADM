"""Blender integration test for BVH import and humanoid retargeting."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

import bpy  # noqa: E402

import adm_blender  # noqa: E402
from adm_blender.blender.file_io import (  # noqa: E402
    ADM_OT_import_bvh_animation,
    _bvh_target_search,
    _default_bvh_target,
    _resolve_bvh_target,
)
from adm_blender.tests.test_mixamo_animation_blender import _make_armature  # noqa: E402
from adm_blender.tests.test_skeleton_profiles import humanoid_rig  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("  ok   " + message)


def _bvh_text(frame_time=0.0333333333333):
    joints, assignments = humanoid_rig()
    role_by_name = dict(assignments)
    name_by_role = {
        role: role[0].upper() + role[1:]
        for role in role_by_name.values()
    }
    children = {}
    for bone, joint in joints.items():
        children.setdefault(joint["parent"], []).append(bone)

    def serialize(bone, depth):
        joint = joints[bone]
        role = role_by_name[bone]
        prefix = " " * depth
        if joint["parent"] is None:
            offset = joint["head"]
            kind = "ROOT"
            channels = "CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation"
        else:
            parent_head = joints[joint["parent"]]["head"]
            offset = tuple(a - b for a, b in zip(joint["head"], parent_head))
            kind = "JOINT"
            channels = "CHANNELS 3 Zrotation Yrotation Xrotation"
        lines = [f"{prefix}{kind} {name_by_role[role]}", f"{prefix}{{",
                 f"{prefix} OFFSET {offset[0]} {offset[1]} {offset[2]}",
                 f"{prefix} {channels}"]
        descendants = sorted(children.get(bone, ()))
        for child in descendants:
            lines.extend(serialize(child, depth + 1))
        if not descendants:
            lines.extend([f"{prefix} End Site", f"{prefix} {{",
                          f"{prefix}  OFFSET 0 0.1 0", f"{prefix} }}"])
        lines.append(f"{prefix}}}")
        return lines

    root = next(bone for bone, joint in joints.items() if joint["parent"] is None)
    channel_count = 6 + 3 * (len(joints) - 1)
    zero_frame = " ".join("0" for _ in range(channel_count))
    return "\n".join(["HIERARCHY", *serialize(root, 0), "MOTION", "Frames: 2",
                      f"Frame Time: {frame_time}", zero_frame, zero_frame, ""])


def run():
    bpy.ops.wm.read_homefile(use_empty=True)
    adm_blender.register()
    target, _ = _make_armature("BVHTarget")
    active_before = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = None
    check(_default_bvh_target(bpy.context) == target.name,
          "BVH import defaults to the only armature when no active target is selected")
    check(_resolve_bvh_target(bpy.context, target.name) == target,
          "BVH import resolves the selected target from the current view layer")
    preview_data = bpy.data.armatures.new("BVHPreview")
    preview = bpy.data.objects.new("BVHPreview", preview_data)
    bpy.context.scene.collection.objects.link(preview)
    preview["adm_bvh_preview_token"] = "test-preview"
    bpy.context.view_layer.update()
    check(preview.name not in _bvh_target_search(None, bpy.context, "")
          and _resolve_bvh_target(bpy.context, preview.name) is None,
          "temporary BVH previews cannot be selected as retarget targets")
    bpy.data.objects.remove(preview, do_unlink=True)
    bpy.data.armatures.remove(preview_data)
    bpy.context.view_layer.objects.active = active_before
    with tempfile.TemporaryDirectory(prefix="adm_bvh_test_") as folder:
        for name, frame_time in (("walk.bvh", 0.0333333333333), ("run.bvh", 0.0166666666667)):
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(_bvh_text(frame_time))
        properties = bpy.context.window_manager.operator_properties_last("import_anim.bvh_adm")
        properties.target_armature = target.name
        properties.preview_path = os.path.join(folder, "walk.bvh")
        properties.preview_token = "selection-persistence-test"
        other_data = bpy.data.armatures.new("AnotherRig")
        other = bpy.data.objects.new("AnotherRig", other_data)
        bpy.context.scene.collection.objects.link(other)
        bpy.context.view_layer.update()
        check(properties.target_armature == target.name,
              "adding another rig does not change the stored target selection")
        for _ in range(3):
            ADM_OT_import_bvh_animation._create_preview(properties, bpy.context)
            check(properties.target_armature == target.name
                  and target.name in _bvh_target_search(properties, bpy.context, "bvhtarget"),
                  "the real operator retains its selected target while the preview exists")
            ADM_OT_import_bvh_animation._remove_preview(properties)
            bpy.context.view_layer.update()
            check(properties.target_armature == target.name
                  and _resolve_bvh_target(bpy.context, properties.target_armature) == target,
                  "the real operator retains its selected target after preview cleanup")
        bpy.data.objects.remove(other, do_unlink=True)
        bpy.data.armatures.remove(other_data)
        properties.preview_token = ""
        result = bpy.ops.import_anim.bvh_adm(
            filepath=os.path.join(folder, "walk.bvh"),
            directory=folder,
            files=[{"name": "walk.bvh"}, {"name": "run.bvh"}],
            target_armature=properties.target_armature,
            library_mode="NEW",
            library_id="bvh@test",
            library_title="BVH Test",
            library_description="BVH import integration fixture",
            library_author="Test Author",
            clip_id="walk",
            clip_title="Walk",
            clip_description="Two-frame BVH import test",
            source_mapping="Hips=hips",
            root_motion="IN_PLACE",
        )

    check("FINISHED" in result, "BVH wizard imports and retargets a batch of mapped humanoid clips")
    libraries = bpy.context.scene.adm_anim.libraries
    check(len(libraries) == 1 and libraries[0].lib_id == "bvh@test",
          "BVH import creates the requested ADM animation library")
    clips = {clip.clip_id: clip for clip in libraries[0].clips}
    check(set(clips) == {"walk", "run"}
          and all(tuple(clip.action.frame_range) == (1.0, 2.0) for clip in clips.values()),
          "BVH batch import preserves per-file clip IDs and source frame ranges")
    check(abs(clips["walk"].fps - 30.0) < 1e-5 and abs(clips["run"].fps - 60.0) < 1e-5,
          "BVH batch import accepts and preserves different per-clip frame rates")
    check(all("Source:" in clip.description for clip in clips.values()),
          "BVH clip descriptions retain per-file source provenance")
    check(libraries[0].author == "Test Author",
          "BVH import preserves library-level provenance metadata")
    check(not any(obj.type == "ARMATURE" and obj != target for obj in bpy.context.scene.objects),
          "temporary BVH source armature is removed after retargeting")
    adm_blender.unregister()


if __name__ == "__main__":
    run()
