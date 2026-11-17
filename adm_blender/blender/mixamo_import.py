"""Mixamo FBX action mapping and ADM semantic retargeting."""

import os
import tempfile

import bpy

from ..core import skeleton_profiles as SP
from ..core import skeleton as SK
from ..core.validate import LIBRARY_ID_RE, SEGMENT_RE
from . import rig as rig_tools
from .export_adm import ExportError
from .export_anim import AnimExporter
from .import_adm import ImportError_
from .import_anim import AnimImportOptions, import_library


def _mapped_roles(arm):
    roles = {}
    duplicates = set()
    for bone in arm.data.bones:
        role = bone.adm.role.strip()
        if not role:
            continue
        if role in roles:
            duplicates.add(role)
        else:
            roles[role] = bone.name
    return roles, duplicates


def _snapshot_target(arm):
    return {
        "bones": {
            bone.name: (bone.adm.role, bone.adm.use_reference_correction,
                        tuple(bone.adm.reference_correction))
            for bone in arm.data.bones
        },
        "action": arm.animation_data.action if arm.animation_data else None,
        "action_slot": arm.animation_data.action_slot if arm.animation_data else None,
    }


def _restore_target(arm, snapshot):
    for bone in arm.data.bones:
        state = snapshot["bones"].get(bone.name)
        if state is not None:
            bone.adm.role, bone.adm.use_reference_correction, bone.adm.reference_correction = state
    if arm.animation_data:
        arm.animation_data.action = snapshot["action"]
        if snapshot["action"] is not None and snapshot["action_slot"] is not None:
            arm.animation_data.action_slot = snapshot["action_slot"]


def _configure_humanoid(arm, overwrite, set_profile=True, explicit_roles=None):
    if set_profile:
        arm.data.adm.profile = SP.HUMANOID
        arm.data.adm.export_profile = True
    if explicit_roles is None:
        rig_tools.auto_map_profile(arm, overwrite=overwrite, profile_id=SP.HUMANOID)
    else:
        bones = {bone.name: bone for bone in arm.data.bones}
        unknown_bones = set(explicit_roles) - set(bones)
        if unknown_bones:
            raise ValueError(f"{arm.name}: mapping references unknown bones: "
                             + ", ".join(sorted(unknown_bones)))
        for bone in arm.data.bones:
            bone.adm.role = explicit_roles.get(bone.name, "")
        valid_roles = set(SP.roles(SP.HUMANOID))
        for role in explicit_roles.values():
            if role not in valid_roles:
                raise ValueError(f"{arm.name}: unsupported humanoid role {role!r}")
    roles, duplicates = _mapped_roles(arm)
    missing = sorted(set(SP.required_roles(SP.HUMANOID)) - set(roles))
    if missing or duplicates:
        details = []
        if missing:
            details.append("missing required roles: " + ", ".join(missing))
        if duplicates:
            details.append("duplicate roles: " + ", ".join(sorted(duplicates)))
        raise ValueError(f"{arm.name}: " + "; ".join(details))
    rig_tools.apply_normalized_corrections(arm)


def _align_source_facing(context, arm):
    facing_issue = next((issue for issue in rig_tools.analyze(arm)
                         if issue.code == "REFERENCE_FACING"), None)
    if facing_issue is None:
        return ()
    rig_tools.apply_fix(context, arm, SK.FIX_ROTATE_180, facing_issue.role, facing_issue.bone)
    remaining = [issue for issue in rig_tools.analyze(arm) if issue.code == "REFERENCE_FACING"]
    if remaining:
        raise ValueError(f"{arm.name}: could not align the source rig with ADM humanoid facing")
    return ("source rig faced +Z; automatically rotated it 180 degrees about the up axis "
            "to match ADM humanoid forward (-Z)",)


def _copy_clip(source, destination):
    destination.use_action_range = False
    for attr in ("clip_id", "title", "description", "language", "tags", "action", "frame_start",
                 "frame_end", "fps", "loop", "root_motion", "root_bone"):
        setattr(destination, attr, getattr(source, attr))
    destination.use_action_range = source.use_action_range
    for source_event in source.events:
        event = destination.events.add()
        event.time = source_event.time
        event.name = source_event.name
        event.payload = source_event.payload


def retarget_mixamo_action(context, source_arm, source_action, target_arm, *,
                           library_index=None, library_id="", library_title="", library_description="",
                           library_author="", library_license="", library_revision="", library_namespace="",
                           library_tags="",
                           clip_id="", clip_title="", clip_description="", root_motion="EXTRACT",
                           source_role_mapping=None, clip_fps=0.0):
    """Map a Mixamo action to a humanoid profile and import it onto the target rig."""
    if source_arm is None or source_arm.type != "ARMATURE":
        raise ValueError("the imported FBX must contain one armature")
    if source_action is None:
        raise ValueError("the imported FBX armature has no animation action")
    if target_arm is None or target_arm.type != "ARMATURE":
        raise ValueError("choose a target armature")
    if target_arm.data.adm.profile_id.strip() != SP.HUMANOID:
        raise ValueError(f"target rig profile must be {SP.HUMANOID}")
    if not SEGMENT_RE.match(clip_id):
        raise ValueError("clip ID must match [a-z][a-z0-9_]*")
    for label, value in (("clip title", clip_title), ("clip description", clip_description)):
        if not value.strip():
            raise ValueError(f"{label} is required")
    if root_motion not in {"IN_PLACE", "EXTRACT", "IGNORE"}:
        raise ValueError(f"unsupported root-motion mode {root_motion!r}")

    scene = context.scene
    libraries = scene.adm_anim.libraries
    destination = None
    if library_index is None:
        if not LIBRARY_ID_RE.match(library_id):
            raise ValueError("library ID must match segment('@'segment)*, lowercase")
        if not library_title.strip() or not library_description.strip():
            raise ValueError("new library title and description are required")
        if any(lib.lib_id == library_id for lib in libraries):
            raise ValueError(f"library ID {library_id!r} already exists")
        output_id, output_title, output_description = library_id, library_title, library_description
        output_language = "en"
    else:
        if library_index < 0 or library_index >= len(libraries):
            raise ValueError("selected animation library no longer exists")
        destination = libraries[library_index]
        if destination.target != "RIG" or destination.armature != target_arm:
            raise ValueError("selected animation library does not target the chosen armature")
        if any(clip.clip_id == clip_id for clip in destination.clips):
            raise ValueError(f"clip ID {clip_id!r} already exists in {destination.lib_id!r}")
        output_id, output_title, output_description = (
            destination.lib_id, destination.title, destination.description)
        output_language = destination.language

    target_snapshot = _snapshot_target(target_arm)
    scene_state = (scene.render.fps, scene.render.fps_base, scene.frame_current,
                   scene.frame_start, scene.frame_end, scene.adm_anim.active_library)
    library_count = len(libraries)
    action_ids_before = {action.as_pointer() for action in bpy.data.actions}
    existing_clip_count = len(destination.clips) if destination is not None else None
    source_warnings = ()
    success = False
    try:
        _configure_humanoid(source_arm, overwrite=True, explicit_roles=source_role_mapping)
        source_warnings = _align_source_facing(context, source_arm)
        _configure_humanoid(target_arm, overwrite=False, set_profile=False)

        source_library = libraries.add()
        source_index = len(libraries) - 1
        source_library.lib_id = output_id
        source_library.title = output_title
        source_library.description = output_description
        source_library.language = output_language or "en"
        source_library.author = library_author
        source_library.license = library_license
        source_library.revision = library_revision
        source_library.namespace = library_namespace
        source_library.tags = library_tags
        source_library.target = "RIG"
        source_library.armature = source_arm
        source_library.binding = "SEMANTIC"
        source_library.root_motion_from_hips = root_motion == "EXTRACT"
        source_clip = source_library.clips.add()
        source_clip.clip_id = clip_id
        source_clip.title = clip_title
        source_clip.description = clip_description
        source_clip.language = output_language or "en"
        source_clip.action = source_action
        source_clip.use_action_range = True
        source_clip.fps = clip_fps
        source_clip.root_motion = root_motion

        exporter = AnimExporter(context, source_library)
        data, _report = exporter.export()
        libraries.remove(source_index)

        with tempfile.TemporaryDirectory(prefix="adm_mixamo_") as folder:
            path = os.path.join(folder, "retarget.adm_anim")
            with open(path, "wb") as stream:
                stream.write(data)
            importer, imported_library = import_library(
                context, path,
                AnimImportOptions(armature=target_arm, strict=True, frame_start=1,
                                  match_source_frame_rate=True, set_active=True))

        imported_index = len(libraries) - 1
        if destination is None:
            result_library = imported_library
            result_clip = imported_library.clips[0]
            result_index = imported_index
        else:
            result_library = libraries[library_index]
            result_clip = result_library.clips.add()
            _copy_clip(imported_library.clips[0], result_clip)
            libraries.remove(imported_index)
            result_index = library_index
        scene.adm_anim.active_library = result_index
        success = True
        return importer, result_library, result_clip, source_warnings + tuple(exporter.warnings)
    finally:
        if not success:
            if destination is not None and library_index < len(libraries):
                while len(libraries[library_index].clips) > existing_clip_count:
                    libraries[library_index].clips.remove(len(libraries[library_index].clips) - 1)
            while len(libraries) > library_count:
                libraries.remove(len(libraries) - 1)
            _restore_target(target_arm, target_snapshot)
            scene.render.fps, scene.render.fps_base = scene_state[:2]
            scene.frame_start, scene.frame_end = scene_state[3:5]
            scene.frame_set(scene_state[2])
            scene.adm_anim.active_library = min(scene_state[5], max(0, len(libraries) - 1))
            for action in list(bpy.data.actions):
                if action.as_pointer() not in action_ids_before and action != source_action:
                    action.use_fake_user = False
                    bpy.data.actions.remove(action)
