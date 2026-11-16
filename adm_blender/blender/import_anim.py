"""ADM animation library (.adm_anim) -> Blender actions + Scene.adm_anim metadata."""

import json
import math
import os

import bpy
import numpy as np
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion

from ..core import constants as K
from ..core.component_animation import component_track_issues, sample_track_values
from ..core import skeleton as SK
from ..core.buffers import read_accessor_np
from ..core.validate import validate_anim
from . import convert as cv
from . import material_anim as mat_anim
from .export_adm import compute_rig_id, find_model_root, rig_id_matches
from .component_profiles import (component_model_binding, component_rest_issues,
                                 restore_component_transform, snapshot_component_transform)
from .export_anim import EXPR_PREFIX, morph_meshes
from .import_adm import ImportError_
from .materials import scene_shader_registry


class AnimImportOptions:
    def __init__(self, **kw):
        self.armature = None
        self.model_root = None
        self.frame_start = 1
        self.strict = True        # refuse incompatible profile / rigId instead of warning
        self.allow_provisional = True  # same-profile SEMANTIC binding for PROVISIONAL (animal) profiles
        self.set_active = True    # assign the first clip to the rig
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown option {k!r}")
            setattr(self, k, v)


def _q_bl(xyzw):
    """ADM xyzw (ADM space) -> Blender-space Quaternion, without normalising (linear map)."""
    x, y, z, w = xyzw
    return Quaternion((w, x, -z, y))


def _qmat_left(q):
    """4x4 matrix M so that (q @ p) as wxyz vector == M @ p_wxyz."""
    w, x, y, z = q
    return np.array([[w, -x, -y, -z], [x, w, -z, y], [y, z, w, -x], [z, -y, x, w]])


def _qmat_right(q):
    """4x4 matrix M so that (p @ q) as wxyz vector == M @ p_wxyz."""
    w, x, y, z = q
    return np.array([[w, -x, -y, -z], [x, w, z, -y], [y, -z, w, x], [z, y, -x, w]])


def library_channel_roles(doc):
    roles = set()
    for clip in doc.get("clips", []):
        for ch in clip.get("channels", []):
            t = ch.get("target", {})
            if t.get("kind") == "bone" and "role" in t:
                roles.add(t["role"])
    return roles


def check_library_compat(context, arm, doc, allow_provisional=True):
    """Compatibility level of a validated .adm_anim document with ``arm``.

    Returns (level, reasons, rig_warnings). Structural rig errors and humanoid reference-pose
    deviations make SEMANTIC binding INCOMPATIBLE; provisional animal diagnostics remain warnings.
    """
    from .export_adm import rig_issue_blocks_semantic
    from .rig import assignments, joint_table, normalized_correction
    lib = doc["library"]
    rig_warnings = []
    if arm is None:
        level, reasons = SK.library_compatibility(lib, "", set())
        return level, reasons, rig_warnings
    sk = arm.data.adm
    pid = sk.profile_id.strip()
    exact = None
    if lib.get("binding") == "EXACT" and lib.get("rigId"):
        exact = bool(rig_id_matches(context, arm, lib["rigId"]))
    issues = []
    if lib.get("binding") == "SEMANTIC":
        bone_assignments = assignments(arm)
        for i in SK.analyze_rig(pid, joint_table(arm), bone_assignments):
            if rig_issue_blocks_semantic(pid, i.code):
                issues.append(i)
            elif i.severity != SK.INFO and i.code not in ("PROFILE_PROVISIONAL",):
                rig_warnings.append(f"rig '{arm.name}' {i.code}"
                                    f"{' (' + (i.bone or i.role) + ')' if (i.bone or i.role) else ''}: {i.message}")
        if pid == "humanoid.vrm1":
            for bone_name, role in bone_assignments:
                bone = arm.data.bones.get(bone_name)
                if bone is None:
                    continue
                if not bone.adm.use_reference_correction:
                    issues.append(SK.RigIssue(SK.ERROR, "REFERENCE_CORRECTION",
                                              "humanoid semantic retarget requires a normalized correction",
                                              role=role, bone=bone_name))
                    continue
                stored = Quaternion(bone.adm.reference_correction)
                expected = normalized_correction(arm, bone)
                actual_values, expected_values = tuple(stored), tuple(expected)
                correction_error = min(
                    max(abs(a - b) for a, b in zip(actual_values, expected_values)),
                    max(abs(a + b) for a, b in zip(actual_values, expected_values)))
                if correction_error > 1e-4:
                    issues.append(SK.RigIssue(SK.ERROR, "REFERENCE_CORRECTION",
                                              f"normalized correction differs by {correction_error:.6g}",
                                              role=role, bone=bone_name))
    rig_roles = {r for _b, r in assignments(arm)}
    level, reasons = SK.library_compatibility(lib, pid, rig_roles, exact, issues, library_channel_roles(doc))
    if level == SK.INCOMPATIBLE and exact is False:
        rig = compute_rig_id(context, arm)
        reasons.append(f"library {lib['rigId'][:12]}… vs rig {rig[:12]}… (EXACT clips require the identical rig)")
    if level == SK.PROVISIONAL_SEMANTIC and not allow_provisional:
        return SK.INCOMPATIBLE, reasons + ["PROVISIONAL profiles are disabled ('Allow Provisional' off)"], \
            rig_warnings
    return level, reasons, rig_warnings


class AnimImporter:
    def __init__(self, context, filepath, options=None):
        self.context = context
        self.filepath = filepath
        self.opts = options or AnimImportOptions()
        self.warnings = []

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ----------------------------------------------------------------------------------------------
    def run(self):
        with open(self.filepath, "rb") as fh:
            data = fh.read()
        report = validate_anim(data)
        if not report.ok:
            raise ImportError_(f"{os.path.basename(self.filepath)} is not a valid ADM animation library", report)
        self.doc, self.bin = report.doc, report.bin
        lib = self.doc["library"]
        arm = self.opts.armature
        self.model_any = lib["targetProfile"] == K.MODEL_ANY_PROFILE
        self.component_target = lib["targetProfile"] in ("vehicle.car.v1", "weapon.firearm.v1")
        if self.component_target or (arm is not None and arm.type != "ARMATURE"):
            arm = None
        if arm is None and not self.model_any and not self.component_target:
            raise ImportError_("select the target armature (rig) before importing an animation library")
        self.arm = arm
        self.model_root = self.opts.model_root
        self.binding = lib["binding"]
        if self.component_target:
            self._check_component_compat(lib)
        if (arm is not None and lib.get("motionScale") == "SOURCE_HEIGHT"
                and (not arm.data.adm.use_target_height or not math.isfinite(arm.data.adm.target_height)
                     or arm.data.adm.target_height <= 0)):
            raise ImportError_("library motionScale SOURCE_HEIGHT requires a finite positive target height "
                               "on the rig; no unscaled fallback is permitted")
        if not self.model_any and not self.component_target:
            self._check_compat(lib)
        self._prepare_targets(lib)

        scene = self.context.scene
        self.registry = scene_shader_registry(scene)
        slib = scene.adm_anim.libraries.add()
        scene.adm_anim.active_library = len(scene.adm_anim.libraries) - 1
        slib.lib_id = lib["id"]
        slib.title = lib["title"]
        slib.description = lib["description"]
        slib.language = lib["language"]
        slib.target = "MODEL_ANY" if self.model_any else "COMPONENTS" if self.component_target else "RIG"
        slib.armature = arm
        slib.model_root = self.model_root if self.component_target else None
        if self.component_target:
            slib.component_profile = lib["targetProfile"]
        slib.binding = self.binding
        slib.tags = ", ".join(lib.get("tags", []))
        slib.author = lib.get("author", "")
        slib.license = lib.get("license", "")
        slib.revision = lib.get("revision", "")
        slib.namespace = lib.get("namespace", "")
        slib.use_motion_scale = lib.get("motionScale") == "SOURCE_HEIGHT"
        if "sourceHeight" in lib:
            slib.source_height = lib["sourceHeight"]
        slib.root_motion_from_hips = lib.get("rootMotionSource") == "hips"

        actions = []
        for clip in self.doc["clips"]:
            action = self.import_clip(clip, lib)
            sc = slib.clips.add()
            sc.clip_id = clip["id"]
            sc.title = clip["title"]
            sc.description = clip["description"]
            sc.language = clip["language"]
            sc.tags = ", ".join(clip.get("tags", []))
            sc.loop = clip["loop"]
            sc.root_motion = clip["rootMotion"]
            if clip["rootMotion"] == "EXTRACT" and self.binding == "EXACT":
                sc.root_bone = self._root_bone(clip)
            sc.use_action_range = False
            sc.action = action
            sc.frame_start = int(action.frame_start)
            sc.frame_end = int(round(action.frame_end))
            sc.use_action_range = True
            for ev in clip.get("events", []):
                e = sc.events.add()
                e.time = ev["time"]
                e.name = ev["name"]
                if "payload" in ev:
                    e.payload = json.dumps(ev["payload"], ensure_ascii=False, separators=(",", ":"))
            actions.append(action)
        slib.active_clip = 0
        if self.opts.set_active and actions:
            assign_action(None if self.component_target else self.arm, actions[0],
                          model_root=self.model_root if self.component_target else None)
            if self.component_target:
                assign_component_actions(self.components, actions[0])
        return slib

    # ----------------------------------------------------------------------------------------------
    def _check_compat(self, lib):
        level, reasons, rig_warnings = check_library_compat(self.context, self.arm, self.doc,
                                                            allow_provisional=self.opts.allow_provisional)
        self.compat_level = level
        for w in rig_warnings:
            self.warn(w)
        if level == SK.INCOMPATIBLE:
            msg = "INCOMPATIBLE: " + "; ".join(reasons)
            if self.opts.strict:
                raise ImportError_(msg + ". Disable 'Strict' to import anyway.")
            self.warn(msg)
        elif level == SK.PROVISIONAL_SEMANTIC:
            self.warn("PROVISIONAL: " + "; ".join(reasons))
        else:
            for r in reasons[:-1]:
                self.warn(r)

    def _check_component_compat(self, lib):
        if self.binding != "SEMANTIC":
            raise ImportError_("mechanical component animations require SEMANTIC binding")
        root = self.model_root
        if root is None or root.type != "EMPTY" or root.adm.adm_type != "MODEL":
            raise ImportError_("select the matching model root before importing component animation")
        try:
            self.component_metadata, self.components = component_model_binding(root, lib["targetProfile"])
        except ValueError as exc:
            raise ImportError_(f"target model is incompatible: {exc}") from exc
        profile_id = lib["targetProfile"]
        for clip in self.doc["clips"]:
            for channel in clip["channels"]:
                target = channel["target"]
                if target["kind"] != "component":
                    continue
                role = target["role"]
                if role not in self.components:
                    if channel.get("optional"):
                        self.warn(f"clip '{clip['id']}': optional component role {role!r} is absent")
                    else:
                        raise ImportError_(f"clip '{clip['id']}': target model has no component role {role!r}")
                times, values, tangents_in, tangents_out, interpolation = self._sampler(
                    clip, channel["sampler"])
                try:
                    samples = sample_track_values(
                        times, values, interpolation, tangents_in, tangents_out,
                        rotation=channel["path"] == "rotation")
                except ValueError as exc:
                    raise ImportError_(f"clip '{clip['id']}' component {role!r}: {exc}") from exc
                issues = component_track_issues(
                    profile_id, self.component_metadata, role, channel["path"], samples)
                if issues:
                    raise ImportError_(f"clip '{clip['id']}' component {role!r}: {'; '.join(issues)}")

    def _prepare_targets(self, lib):
        arm = self.arm
        self.bones = {}
        self.rest_rot = {}
        self.morph_keys = {}
        self.component_rest = {}
        self.motion_scale = 1.0
        self.materials = {}
        materials = ({slot.material for obj in self.model_root.children_recursive
                      for slot in obj.material_slots if slot.material is not None}
                     if self.component_target else bpy.data.materials)
        for mat in materials:
            aid = mat.adm.animation_id.strip()
            if aid:
                if aid in self.materials:
                    self.warn(f"animationId '{aid}' is used by several materials; animating '{self.materials[aid].name}'")
                    continue
                self.materials[aid] = mat
        if arm is None:
            meshes = ([o for o in self.model_root.children_recursive if o.type == "MESH"]
                      if self.component_target else morph_meshes(None))
            for o in meshes:
                if o.data.shape_keys is None:
                    continue
                key = o.data.shape_keys
                for kb in key.key_blocks[1:]:
                    self.morph_keys.setdefault(kb.name, []).append((key, kb.name, 1.0))
            if self.component_target:
                scene = self.context.scene
                root = self.model_root
                frame_saved = scene.frame_current
                saved = []
                component_states = {obj: snapshot_component_transform(obj) for obj in self.components.values()}
                try:
                    for role, obj in self.components.items():
                        ad = obj.animation_data
                        if ad is not None:
                            saved.append((ad, ad.action, ad.action_slot if ad.action else None, ad.use_nla))
                            ad.use_nla = False
                            ad.action = None
                    self.context.view_layer.update()
                    rest_issues = component_rest_issues(root, self.components)
                    if rest_issues:
                        raise ImportError_("target model has invalid component rest transforms: "
                                           + "; ".join(rest_issues))
                    for role, obj in self.components.items():
                        location, rotation, _scale = obj.matrix_basis.decompose()
                        self.component_rest[role] = (location.copy(), rotation.copy())
                finally:
                    for ad, action, slot, use_nla in reversed(saved):
                        ad.action = action
                        if action is not None and slot is not None:
                            ad.action_slot = slot
                        ad.use_nla = use_nla
                    for obj, state in component_states.items():
                        restore_component_transform(obj, state)
                    scene.frame_set(frame_saved)
                    self.context.view_layer.update()
            return
        if self.binding == "SEMANTIC" and not self.model_any:
            for b in arm.data.bones:
                r = b.adm.role.strip()
                if r:
                    self.bones[r] = b
        else:
            self.bones = {b.name: b for b in arm.data.bones}
        self.joint_frame_correction = {}
        self.rest_scale = {}
        for b in arm.data.bones:
            try:
                correction = cv.bone_frame_correction(b)
                self.joint_frame_correction[b.name] = correction
                if b.parent:
                    parent_correction = cv.bone_frame_correction(b.parent)
                    bone_local = b.parent.matrix_local.inverted_safe() @ b.matrix_local
                    rl = parent_correction.inverted_safe() @ bone_local @ correction
                else:
                    rl = b.matrix_local @ correction
            except ValueError as exc:
                raise ImportError_(str(exc)) from exc
            t, r, s = rl.decompose()
            self.rest_rot[b.name] = (t, r)
            self.rest_scale[b.name] = s
        # morph targets: plain shape-key names + ARKit face channels bound on the model root
        for o in morph_meshes(arm):
            key = o.data.shape_keys
            for kb in key.key_blocks[1:]:
                self.morph_keys.setdefault(kb.name, []).append((key, kb.name, 1.0))
        root = find_model_root(arm)
        if root is not None and root.adm.face_enabled:
            for fb in root.adm.face_bindings:
                if fb.object and fb.object.data.shape_keys and fb.target in fb.object.data.shape_keys.key_blocks:
                    self.morph_keys.setdefault(fb.channel, []).append(
                        (fb.object.data.shape_keys, fb.target, fb.scale))
        if lib.get("motionScale") == "SOURCE_HEIGHT":
            sk = arm.data.adm
            self.motion_scale = sk.target_height / lib["sourceHeight"]

    def _root_bone(self, clip):
        cands = [c["target"]["nodeName"] for c in clip["channels"]
                 if c["target"]["kind"] == "bone" and c["path"] == "translation"
                 and c["target"]["nodeName"] in self.arm.data.bones]
        cands.sort(key=lambda n: (len(self.arm.data.bones[n].parent_recursive), n))
        return cands[0] if cands else ""

    # ----------------------------------------------------------------------------------------------
    # ----------------------------------------------------------------------------------------------
    def _material_targets(self, mat, tgt, ncomp, clip_id):
        """Write targets for a material channel, or None (with a warning) when the binding is impossible."""
        p = tgt["parameter"]
        if tgt["kind"] == "pbrParameter":
            targets = mat_anim.pbr_write_targets(mat, p)
            if not targets:
                self.warn(f"clip '{clip_id}': material '{mat.name}' cannot express PBR parameter '{p}' "
                          f"(needs a Principled BSDF{' with a Normal Map node' if p == 'normalScale' else ''}); skipped")
            return targets
        key = (tgt["shaderId"], tgt["shaderVersion"])
        if mat.adm.shader_key() != key:
            sk = mat.adm.shader_key()
            self.warn(f"clip '{clip_id}': material '{mat.name}' uses shader {sk[0]}@{sk[1]}, "
                      f"channel targets {key[0]}@{key[1]}; skipped")
            return None
        prm = self.registry.get(key, {}).get(p)
        is_vertex_control = p in K.VERTEX_CONTROL_PARAMS and mat.adm.vertex_controls_enabled
        if not is_vertex_control and (prm is None or not prm.get("animatable")):
            self.warn(f"clip '{clip_id}': shader {key[0]}@{key[1]} has no animatable parameter '{p}'; skipped")
            return None
        targets = mat_anim.shader_write_targets(mat, p, ncomp)
        if not targets:
            return None
        return [("MATERIAL", dp, idx, comp, 1.0) for dp, idx, comp in targets]

    def _sampler(self, clip, si):
        s = clip["samplers"][si]
        t = read_accessor_np(self.doc, self.bin, s["input"], np.float64)[:, 0]
        v = read_accessor_np(self.doc, self.bin, s["output"], np.float64)
        interp = s["interpolation"]
        if interp == "CUBICSPLINE":
            n = len(t)
            v = v.reshape(n, 3, -1)
            return t, v[:, 1], v[:, 0], v[:, 2], interp
        return t, v, None, None, interp

    def import_clip(self, clip, lib):
        arm = self.arm
        scene = self.context.scene
        fps = scene.render.fps / scene.render.fps_base
        f0 = self.opts.frame_start
        name = f"{lib['id']}:{clip['id']}"
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        cbs = {}

        def arm_cb():
            if "arm" not in cbs:
                slot = action.slots.new(id_type="OBJECT", name=arm.name)
                cbs["arm"] = anim_utils.action_ensure_channelbag_for_slot(action, slot)
            return cbs["arm"]

        def component_cb(obj):
            if obj.name not in cbs:
                slot = action.slots.new(id_type="OBJECT", name=obj.name)
                cbs[obj.name] = anim_utils.action_ensure_channelbag_for_slot(action, slot)
            return cbs[obj.name]

        key_cbs = {}

        def key_cb(key):
            if key.name not in key_cbs:
                slot = action.slots.new(id_type="KEY", name=key.name)
                key_cbs[key.name] = anim_utils.action_ensure_channelbag_for_slot(action, slot)
            return key_cbs[key.name]

        def mat_cb(mat, id_kind):
            k = (mat.name, id_kind)
            if k not in cbs:
                ms, ns = mat_anim.ensure_material_slots(action, mat)
                cbs[k] = anim_utils.action_ensure_channelbag_for_slot(action, ms if id_kind == "MATERIAL" else ns)
            return cbs[k]

        groups = {}

        def fcurve(cb, path, index, group):
            fc = cb.fcurves.new(path, index=index)
            if group:
                if (id(cb), group) not in groups:
                    groups[(id(cb), group)] = cb.groups.new(group)
                fc.group = groups[(id(cb), group)]
            return fc

        def write(cb, path, ncomp, group, t, v, tin, tout, interp, offset=None):
            frames = f0 + t * fps
            for c in range(ncomp):
                fc = fcurve(cb, path, c, group)
                vals = v[:, c] + (offset[c] if offset is not None else 0.0)
                _fill(fc, frames, vals, None if tin is None else tin[:, c], None if tout is None else tout[:, c],
                      interp, fps)

        semantic_rotation_data = {}
        if self.binding == "SEMANTIC":
            tracks = {}
            for channel in clip["channels"]:
                target = channel["target"]
                if target["kind"] != "bone" or channel["path"] != "rotation":
                    continue
                bone = self.bones.get(target["role"])
                if bone is not None:
                    tracks[bone.name] = self._sampler(clip, channel["sampler"])
            if tracks:
                key_times = np.unique(np.concatenate([track[0] for track in tracks.values()]))
                frame_count = int(np.ceil((key_times[-1] - key_times[0]) * fps))
                frame_times = key_times[0] + np.arange(frame_count + 1, dtype=np.float64) / fps
                frame_times = frame_times[frame_times <= key_times[-1] + 1e-8]
                sample_times = np.unique(np.concatenate((key_times, frame_times)))
                rest_local = {b.name: self.rest_rot[b.name][1] for b in arm.data.bones}
                rest_global = {}

                def get_rest_global(bone):
                    if bone.name not in rest_global:
                        local = rest_local[bone.name]
                        rest_global[bone.name] = (get_rest_global(bone.parent) @ local
                                                  if bone.parent else local.copy())
                    return rest_global[bone.name]

                for bone in arm.data.bones:
                    get_rest_global(bone)
                generated = {name: [] for name in tracks}
                for time in sample_times:
                    pose_global = {}

                    def get_pose_global(bone):
                        if bone.name not in pose_global:
                            parent_pose = get_pose_global(bone.parent) if bone.parent else None
                            if bone.name in tracks:
                                delta = _sample_quat_track(tracks[bone.name], float(time))
                                pose_global[bone.name] = delta @ rest_global[bone.name]
                            else:
                                pose_global[bone.name] = (parent_pose @ rest_local[bone.name]
                                                          if parent_pose else rest_local[bone.name].copy())
                        return pose_global[bone.name]

                    for bone in arm.data.bones:
                        get_pose_global(bone)
                    for name in tracks:
                        bone = arm.data.bones[name]
                        parent_pose = pose_global[bone.parent.name] if bone.parent else None
                        local_pose = (parent_pose.inverted() @ pose_global[name]
                                      if parent_pose else pose_global[name])
                        local_delta = rest_local[name].inverted() @ local_pose
                        frame = self.joint_frame_correction[name].to_quaternion()
                        basis_delta = frame @ local_delta @ frame.inverted()
                        basis_delta.normalize()
                        generated[name].append(tuple(basis_delta))
                semantic_rotation_data = {
                    name: (sample_times, _sign_continuity(np.asarray(values, dtype=np.float64)))
                    for name, values in generated.items()
                }

        missing = []
        for ch in clip["channels"]:
            tgt, path = ch["target"], ch["path"]
            t, v, tin, tout, interp = self._sampler(clip, ch["sampler"])
            kind = tgt["kind"]
            if kind == "bone":
                ident = tgt["role"] if self.binding == "SEMANTIC" else tgt["nodeName"]
                bone = self.bones.get(ident)
                if bone is None:
                    if not ch.get("optional"):
                        missing.append(f"bone {ident!r}")
                    continue
                pb_path = f'pose.bones["{bpy.utils.escape_identifier(bone.name)}"]'
                rt, rq = self.rest_rot[bone.name]
                rinv = rq.inverted()
                correction = self.joint_frame_correction[bone.name]
                if path == "rotation":
                    if self.binding == "SEMANTIC":
                        rotation_times, vv = semantic_rotation_data[bone.name]
                        pb = arm.pose.bones[bone.name]
                        pb.rotation_mode = "QUATERNION"
                        write(arm_cb(), pb_path + ".rotation_quaternion", 4, bone.name, rotation_times, vv,
                              None, None, "LINEAR")
                    else:
                        correction_rotation = correction.to_quaternion()
                        gram = correction.to_3x3().transposed() @ correction.to_3x3()
                        if max(abs(gram[r][c] - (gram[0][0] if r == c else 0.0))
                               for r in range(3) for c in range(3)) > 1e-5:
                            raise ImportError_(f"bone '{bone.name}': animated rotation cannot be represented "
                                               "without shear after the ADM joint-frame correction")
                        M = (_qmat_left(correction_rotation) @ _qmat_left(rinv)
                             @ _qmat_right(correction_rotation.inverted()) @ _adm_quat_map())
                        conv = lambda a: None if a is None else a @ M.T  # noqa: E731
                        vv = conv(v)
                        if interp != "CUBICSPLINE":
                            vv = _sign_continuity(vv)
                        pb = arm.pose.bones[bone.name]
                        pb.rotation_mode = "QUATERNION"
                        write(arm_cb(), pb_path + ".rotation_quaternion", 4, bone.name, t, vv,
                              conv(tin), conv(tout), interp)
                elif path == "translation":
                    if self.binding == "SEMANTIC":
                        root = find_model_root(arm)
                        arm_rot = ((root.matrix_world.inverted_safe() if root else Matrix()) @ arm.matrix_world)
                        arm_rot = arm_rot.to_3x3()
                        R = np.array(bone.matrix_local.to_3x3().inverted_safe() @ arm_rot.inverted_safe()
                                     @ cv.C3_INV) * self.motion_scale
                        offset = None
                    else:
                        inv_scale = Matrix.Diagonal(Vector((1.0 / self.rest_scale[bone.name][0],
                                                           1.0 / self.rest_scale[bone.name][1],
                                                           1.0 / self.rest_scale[bone.name][2])))
                        R = (np.array(correction.to_3x3()) @ np.array(inv_scale)
                             @ np.array(rinv.to_matrix()) @ np.array(cv.C3_INV))
                        offset = -np.array(correction.to_3x3() @ inv_scale @ rinv.to_matrix() @ rt)
                    conv = lambda a: None if a is None else a @ R.T  # noqa: E731
                    write(arm_cb(), pb_path + ".location", 3, bone.name, t, conv(v), conv(tin), conv(tout), interp,
                          offset)
                else:
                    P = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=np.float64)
                    D = np.array(correction.to_3x3(), dtype=np.float64)
                    D_inv = np.linalg.inv(D)
                    rest_scale = np.array(self.rest_scale[bone.name], dtype=np.float64)

                    def conv(a):
                        if a is None:
                            return None
                        mapped = a @ P.T / rest_scale
                        diagonal = np.empty_like(mapped)
                        max_off_diagonal = 0.0
                        for sample_index, scale_delta in enumerate(mapped):
                            transformed = D @ np.diag(scale_delta) @ D_inv
                            max_off_diagonal = max(max_off_diagonal,
                                                   float(np.max(np.abs(transformed - np.diag(np.diag(transformed))))))
                            diagonal[sample_index] = np.diag(transformed)
                        if max_off_diagonal > 1e-5:
                            raise ImportError_(f"bone '{bone.name}': animated scale cannot be represented "
                                               "without shear after the ADM joint-frame correction")
                        return diagonal

                    vv = conv(v)
                    if vv is None:
                        raise ImportError_(f"bone '{bone.name}': scale sampler has no values")
                    write(arm_cb(), pb_path + ".scale", 3, bone.name, t, vv, conv(tin), conv(tout), interp)
            elif kind == "morph":
                targets = self.morph_keys.get(tgt["name"])
                if not targets:
                    if not ch.get("optional"):
                        missing.append(f"morph {tgt['name']!r}")
                    continue
                for key, kb_name, scale in targets:
                    cb = key_cb(key)
                    fc = fcurve(cb, f'key_blocks["{bpy.utils.escape_identifier(kb_name)}"].value', 0, "Shape Keys")
                    _fill(fc, f0 + t * fps, v[:, 0] * scale, None if tin is None else tin[:, 0] * scale,
                          None if tout is None else tout[:, 0] * scale, interp, fps)
            elif kind in ("pbrParameter", "shaderParameter"):
                mat = self.materials.get(tgt["materialId"])
                if mat is None:
                    if not ch.get("optional"):
                        missing.append(f"material {tgt['materialId']!r}")
                    continue
                targets = self._material_targets(mat, tgt, v.shape[1], clip["id"])
                if targets is None:
                    continue
                frames = f0 + t * fps
                for id_kind, dpath, idx, comp, scale in targets:
                    fc = fcurve(mat_cb(mat, id_kind), dpath, idx, "ADM " + tgt["parameter"])
                    _fill(fc, frames, v[:, comp] * scale, None if tin is None else tin[:, comp] * scale,
                          None if tout is None else tout[:, comp] * scale, interp, fps)
            elif kind == "component":
                obj = self.components.get(tgt["role"])
                if obj is None:
                    continue
                rest_t, rest_q = self.component_rest[tgt["role"]]
                if path == "translation":
                    conversion = np.array(cv.C3_INV)
                    convert = lambda values: None if values is None else values @ conversion.T
                    write(component_cb(obj), "location", 3, tgt["role"], t, convert(v),
                          convert(tin), convert(tout), interp, np.array(rest_t))
                else:
                    obj.rotation_mode = "QUATERNION"
                    conversion = _qmat_left(rest_q) @ _adm_quat_map()
                    convert = lambda values: None if values is None else values @ conversion.T
                    write(component_cb(obj), "rotation_quaternion", 4, tgt["role"], t, convert(v),
                          convert(tin), convert(tout), interp)
            else:
                if arm is None:
                    if not ch.get("optional"):
                        missing.append(f"expression {tgt['name']!r}")
                    continue
                prop = EXPR_PREFIX + tgt["name"]
                if prop not in arm:
                    arm[prop] = 0.0
                    ui = arm.id_properties_ui(prop)
                    ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                              description=f"ADM expression '{tgt['name']}' weight")
                fc = fcurve(arm_cb(), f'["{prop}"]', 0, "Expressions")
                _fill(fc, f0 + t * fps, v[:, 0], None if tin is None else tin[:, 0],
                      None if tout is None else tout[:, 0], interp, fps)
        if missing:
            target_name = "model" if self.model_any or self.component_target else "rig"
            self.warn(f"clip '{clip['id']}': targets not present on the {target_name} (skipped): "
                      f"{', '.join(missing[:12])}"
                      + (" …" if len(missing) > 12 else ""))
        dur = clip["duration"]
        action.use_frame_range = True
        action.frame_start = f0
        action.frame_end = f0 + max(dur * fps, 0.0)
        action.use_cyclic = clip["loop"] == "REPEAT"
        action["adm_clip_id"] = clip["id"]
        return action


def _adm_quat_map():
    """Linear map ADM xyzw (as vector) -> Blender wxyz."""
    return np.array([[0, 0, 0, 1], [1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]], dtype=np.float64)


def _sign_continuity(q):
    q = q.copy()
    for i in range(1, len(q)):
        if np.dot(q[i - 1], q[i]) < 0:
            q[i] = -q[i]
    return q


def _sample_quat_track(track, time):
    times, values, tangents_in, tangents_out, interpolation = track
    if time <= times[0]:
        value = values[0]
    elif time >= times[-1]:
        value = values[-1]
    else:
        i = int(np.searchsorted(times, time, side="right") - 1)
        span = times[i + 1] - times[i]
        u = (time - times[i]) / span
        if interpolation == "STEP":
            value = values[i]
        elif interpolation == "CUBICSPLINE":
            u2, u3 = u * u, u * u * u
            value = ((2 * u3 - 3 * u2 + 1) * values[i]
                     + (u3 - 2 * u2 + u) * span * tangents_out[i]
                     + (-2 * u3 + 3 * u2) * values[i + 1]
                     + (u3 - u2) * span * tangents_in[i + 1])
        else:
            qa, qb = _q_bl(values[i]), _q_bl(values[i + 1])
            return qa.slerp(qb, float(u))
    q = _q_bl(value)
    if q.magnitude > 1e-12:
        q.normalize()
    return q


def _fill(fc, frames, values, tin, tout, interp, fps):
    n = len(frames)
    kps = fc.keyframe_points
    kps.add(n)
    co = np.empty(2 * n)
    co[0::2] = frames
    co[1::2] = values
    kps.foreach_set("co", co)
    if interp == "CUBICSPLINE":
        dprev = np.empty(n)
        dnext = np.empty(n)
        dprev[1:] = np.diff(frames)
        dprev[0] = dprev[1] if n > 1 else 1.0
        dnext[:-1] = np.diff(frames)
        dnext[-1] = dnext[-2] if n > 1 else 1.0
        hl = np.empty(2 * n)
        hr = np.empty(2 * n)
        hl[0::2] = frames - dprev / 3
        hl[1::2] = values - tin * (dprev / fps) / 3
        hr[0::2] = frames + dnext / 3
        hr[1::2] = values + tout * (dnext / fps) / 3
        for kp in kps:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "FREE"
            kp.handle_right_type = "FREE"
        kps.foreach_set("handle_left", hl)
        kps.foreach_set("handle_right", hr)
    else:
        mode = "CONSTANT" if interp == "STEP" else "LINEAR"
        for kp in kps:
            kp.interpolation = mode
    fc.update()
    if interp == "CUBICSPLINE":
        # update() may recalculate handles of AUTO types only; restore exact Hermite handles
        kps.foreach_set("handle_left", hl)
        kps.foreach_set("handle_right", hr)


def assign_action(arm, action, morph_keys=None, model_root=None):
    """Assign a clip action to the rig (if any), its shape-key datablocks and its animated materials."""
    from .export_anim import pick_slot
    if arm is not None:
        ad = arm.animation_data or arm.animation_data_create()
        ad.action = action
        slot = pick_slot(action, "OBJECT", (arm.name,))
        if slot is not None:
            ad.action_slot = slot
    keys = {}
    meshes = ([o for o in model_root.children_recursive if o.type == "MESH"]
              if model_root is not None else morph_meshes(arm))
    for o in meshes:
        if o.data.shape_keys is None:
            continue
        keys[o.data.shape_keys.name] = o.data.shape_keys
    for kname, key in keys.items():
        slot = None
        for s in action.slots:
            if s.target_id_type == "KEY" and s.name_display == kname:
                slot = s
        kad = key.animation_data or key.animation_data_create()
        if slot is not None:
            kad.action = action
            kad.action_slot = slot
        elif kad.action is not None and kad.action.get("adm_clip_id") is not None:
            kad.action = None
    bound = set()
    for mat, ms, ns in mat_anim.animated_materials(action):
        mat_anim.bind_material(mat, action)
        bound.add(mat.name)
    for mat in bpy.data.materials:
        if mat.name in bound:
            continue
        for idb in (mat, mat.node_tree):
            ad = getattr(idb, "animation_data", None) if idb is not None else None
            if ad is not None and ad.action is not None and ad.action.get("adm_clip_id") is not None:
                ad.action = None


def assign_component_actions(components, action):
    from .export_anim import pick_slot
    for obj in components.values():
        slot = pick_slot(action, "OBJECT", (obj.name,), strict=True)
        if slot is None:
            continue
        ad = obj.animation_data or obj.animation_data_create()
        ad.action = action
        ad.action_slot = slot


def import_library(context, filepath, options=None):
    imp = AnimImporter(context, filepath, options)
    slib = imp.run()
    return imp, slib
