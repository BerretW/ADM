"""Blender integration test for semantic mechanical component animation."""

import json
import math
import os
import sys
import tempfile
from copy import deepcopy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

import bpy  # noqa: E402
from bpy_extras import anim_utils  # noqa: E402

import adm_blender  # noqa: E402
from adm_blender.blender.export_adm import ExportError  # noqa: E402
from adm_blender.blender.export_anim import AnimExporter  # noqa: E402
from adm_blender.blender.import_anim import AnimImportOptions, import_library  # noqa: E402
from adm_blender.blender.import_adm import ImportError_  # noqa: E402
from adm_blender.core.buffers import read_accessor_np  # noqa: E402
from adm_blender.core.container import write_container  # noqa: E402
from adm_blender.core import constants as K  # noqa: E402
from adm_blender.core.validate import validate_anim  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("  ok   " + message)


def make_model(name):
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    root.adm.adm_type = "MODEL"
    root.adm.model_profiles_json = json.dumps([{
        "id": "weapon.firearm.v1",
        "schemaVersion": 1,
        "metadata": {
            "feedType": "NONE",
            "articulations": [{
                "role": "weapon.bolt",
                "allowed": "BOTH",
                "translationAxis": "Z",
                "translationMin": -0.02,
                "translationMax": 0.0,
                "rotationAxis": "X",
                "rotationMinRad": 0.0,
                "rotationMaxRad": 0.2,
            }],
        },
    }], separators=(",", ":"))

    objects = {}
    for role, parent_role in (("weapon.receiver", None), ("weapon.muzzle", "weapon.receiver"),
                              ("weapon.bolt", "weapon.receiver")):
        obj = bpy.data.objects.new(name + "_" + role, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = root if parent_role is None else objects[parent_role]
        obj.adm.component_role = role
        obj.adm.component_profile = "weapon.firearm.v1"
        obj.rotation_mode = "QUATERNION"
        objects[role] = obj
    return root, objects


def add_curve(channelbag, path, index, value_start, value_end):
    curve = channelbag.fcurves.new(data_path=path, index=index)
    curve.keyframe_points.add(2)
    curve.keyframe_points.foreach_set("co", (1.0, value_start, 25.0, value_end))
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"
    curve.update()
    return curve


def run():
    adm_blender.register()
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    source_root, source = make_model("Source")
    target_root, target = make_model("Target")
    target_obj = target["weapon.bolt"]
    target_obj.location = (0.2, 0.3, 0.4)

    action = bpy.data.actions.new("Component Test")
    slot = action.slots.new(id_type="OBJECT", name=source["weapon.bolt"].name)
    bag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
    add_curve(bag, "location", 1, 0.0, 0.01)
    angle = 0.1
    add_curve(bag, "rotation_quaternion", 0, 1.0, math.cos(angle / 2))
    add_curve(bag, "rotation_quaternion", 1, 0.0, math.sin(angle / 2))
    add_curve(bag, "rotation_quaternion", 2, 0.0, 0.0)
    add_curve(bag, "rotation_quaternion", 3, 0.0, 0.0)

    library = scene.adm_anim.libraries.add()
    library.lib_id = "weapon@inspection"
    library.title = "Visual Inspection"
    library.description = "Mechanical component animation round trip"
    library.target = "COMPONENTS"
    library.model_root = source_root
    library.component_profile = "weapon.firearm.v1"
    clip = library.clips.add()
    clip.clip_id = "bolt_cycle"
    clip.title = "Bolt Cycle"
    clip.description = "Move the modeled bolt through its declared range"
    clip.action = action
    clip.use_action_range = False
    clip.frame_start = 1
    clip.frame_end = 32
    clip.fps = 60.0
    clip.root_motion = "IN_PLACE"

    exporter = AnimExporter(bpy.context, library)
    data, report = exporter.export()
    check(report.ok, "component animation exporter produces valid ADM")
    doc = validate_anim(data).doc
    timing = doc["extensions"]["ADM_animation_timing_v1"]
    clip_timing = doc["clips"][0]["extensions"]["ADM_animation_timing_v1"]
    check(timing["fps"] == 30 and timing["fpsBase"] == 1.0
          and clip_timing["frameStart"] == 1 and clip_timing["frameEnd"] == 32
          and clip_timing["fps"] == 60 and clip_timing["fpsBase"] == 1.0
          and abs(doc["clips"][0]["duration"] - 31 / 60) < 1e-6,
          "export preserves the 32-frame range and uses per-clip FPS to set playback duration")
    invalid_timing = deepcopy(doc)
    invalid_timing["clips"][0]["extensions"]["ADM_animation_timing_v1"]["frameEnd"] = 31
    invalid_report = validate_anim(write_container(K.ANIM_MAGIC, invalid_timing, validate_anim(data).bin))
    check(any(issue.code == "ANIMATION_TIMING_DURATION" for issue in invalid_report.errors),
          "validator rejects a clip frame range that conflicts with its duration")
    old_contract = deepcopy(doc)
    old_contract["extensions"]["ADM_animation_timing_v1"]["version"] = "1.0.0"
    old_report = validate_anim(write_container(K.ANIM_MAGIC, old_contract, validate_anim(data).bin))
    check(any(issue.code == "ANIMATION_TIMING_VERSION" for issue in old_report.errors),
          "validator rejects the superseded single-rate timing contract")
    tracks = {(channel["target"]["role"], channel["path"]): channel
              for channel in doc["clips"][0]["channels"]}
    check(("weapon.bolt", "translation") in tracks and ("weapon.bolt", "rotation") in tracks,
          "export preserves component role and both articulation paths")
    track = tracks[("weapon.bolt", "translation")]
    values = read_accessor_np(doc, validate_anim(data).bin, doc["clips"][0]["samplers"][track["sampler"]]["output"])
    check(abs(float(values[-1, 2]) + 0.01) < 1e-5, "export records rest-relative ADM translation delta")

    axis_violation_curve = add_curve(bag, "location", 0, 0.0, 0.01)
    try:
        AnimExporter(bpy.context, library).export()
    except ExportError as exc:
        check("outside" in str(exc), "export rejects component motion outside its profile limits")
    else:
        raise AssertionError("export accepted an out-of-axis component translation")
    axis_violation_curve.keyframe_points[-1].co.y = 0.0
    axis_violation_curve.update()
    scale_curve = add_curve(bag, "scale", 0, 1.0, 1.0)
    try:
        AnimExporter(bpy.context, library).export()
    except ExportError as exc:
        check("cannot animate scale" in str(exc), "export rejects component scale tracks")
    else:
        raise AssertionError("export accepted a component scale track")
    bag.fcurves.remove(scale_curve)

    with tempfile.NamedTemporaryFile(suffix=".adm_anim", delete=False) as stream:
        stream.write(data)
        path = stream.name
    try:
        scene.render.fps = 24
        target_profiles = json.loads(target_root.adm.model_profiles_json)
        target_profiles[0]["metadata"]["articulations"][0]["translationMin"] = -0.005
        target_root.adm.model_profiles_json = json.dumps(target_profiles, separators=(",", ":"))
        try:
            import_library(bpy.context, path, AnimImportOptions(model_root=target_root))
        except ImportError_ as exc:
            check("outside" in str(exc), "import rejects tracks outside target profile limits")
        else:
            raise AssertionError("import accepted a track outside target profile limits")
        target_profiles[0]["metadata"]["articulations"][0]["translationMin"] = -0.02
        target_root.adm.model_profiles_json = json.dumps(target_profiles, separators=(",", ":"))
        imp, _slib = import_library(
            bpy.context, path, AnimImportOptions(model_root=target_root, set_active=True))
    finally:
        os.unlink(path)
    check(any("scene frame rate changed" in warning for warning in imp.warnings)
          and scene.render.fps == 30,
          "import restores source frame rate and reports the scene setting change")
    check(round(imp.context.scene.adm_anim.libraries[-1].clips[0].action.frame_end) == 32,
          "import preserves the 32-frame action range")
    check(imp.context.scene.adm_anim.libraries[-1].clips[0].fps == 60.0,
          "import preserves per-clip FPS independently of the project rate")
    scene.frame_set(32)
    bpy.context.view_layer.update()
    check(all(abs(a - b) < 1e-5 for a, b in zip(target_obj.location, (0.2, 0.31, 0.4))),
          "import evaluates translation delta relative to target rest transform")
    check(abs(target_obj.rotation_quaternion.angle - angle) < 1e-5,
          "import evaluates component rotation delta")

    adm_blender.unregister()
    print("PASS: mechanical component animation export/import")


run()
