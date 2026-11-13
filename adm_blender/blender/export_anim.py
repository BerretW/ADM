"""Blender actions -> ADM animation library (.adm_anim)."""

import json
import re

import bpy
import numpy as np
from bpy_extras import anim_utils
from mathutils import Quaternion

from ..core import constants as K
from ..core import skeleton as SK
from ..core import skeleton_profiles as SP
from ..core.buffers import BinBuilder
from ..core.container import AdmFormatError, write_container
from ..core.validate import (BCP47_RE, EVENT_NAME_RE, LIBRARY_ID_RE, NAMESPACE_RE, SEGMENT_RE, SEMVER_RE,
                             _canonical_json, validate_anim)
from . import convert as cv
from . import material_anim as mat_anim
from .export_adm import GENERATOR, ExportError, compute_rig_id, find_model_root
from .materials import scene_shader_registry

EXPR_PREFIX = "adm_expr_"
KEY_PATH_RE = re.compile(r'^key_blocks\["(.+)"\]\.value$')
EXPR_PATH_RE = re.compile(r'^\["' + EXPR_PREFIX + r'(.+)"\]$')


class AnimExportOptions:
    def __init__(self, **kw):
        self.sample_step = 1
        self.optimize = True
        self.validate = True
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown option {k!r}")
            setattr(self, k, v)


def parse_tags(text):
    tags = sorted({t.strip().lower() for t in text.replace(";", ",").split(",") if t.strip()})
    bad = [t for t in tags if not SEGMENT_RE.match(t)]
    return tags, bad


def morph_meshes(arm):
    """Mesh objects deformed by / parented to ``arm`` that carry shape keys (all such meshes if arm is None)."""
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.data.shape_keys is None:
            continue
        driven = arm is None or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)
        p = o.parent
        while p is not None and not driven:
            driven = p == arm
            p = p.parent
        if driven:
            out.append(o)
    return sorted(out, key=lambda o: o.name)


def pick_slot(action, id_type, names=(), strict=False):
    """Slot for ``id_type`` matched by display name; with ``strict`` no fallback to an arbitrary slot."""
    slots = [s for s in action.slots if s.target_id_type in (id_type, "UNSPECIFIED")]
    for n in names:
        for s in slots:
            if s.name_display == n:
                return s
    if strict:
        return None
    typed = [s for s in slots if s.target_id_type == id_type]
    return typed[0] if typed else (slots[0] if slots else None)


def channelbag_fcurves(action, slot):
    if action is None or slot is None:
        return []
    cb = anim_utils.action_get_channelbag_for_slot(action, slot)
    return list(cb.fcurves) if cb is not None else []


class _Assign:
    """Temporarily assign an action (and slot) to an ID, restoring afterwards."""

    def __init__(self):
        self.saved = []

    def assign(self, idb, action, slot):
        ad = idb.animation_data or idb.animation_data_create()
        self.saved.append((ad, ad.action, ad.action_slot if ad.action else None, ad.use_nla))
        ad.use_nla = False
        ad.action = action
        if action is not None and slot is not None:
            ad.action_slot = slot

    def restore(self):
        for ad, action, slot, use_nla in reversed(self.saved):
            ad.action = action
            if action is not None and slot is not None:
                try:
                    ad.action_slot = slot
                except Exception:
                    pass
            ad.use_nla = use_nla
        self.saved.clear()


def _reduce(times, values, tol, is_quat=False):
    """Greedy removal of keys reproducible by linear interpolation of neighbours."""
    n = len(times)
    if n <= 2:
        return np.arange(n)
    keep = [0]
    a = 0
    j = 2
    while j < n:
        ok = True
        ta, tj = times[a], times[j]
        for i in range(a + 1, j):
            u = (times[i] - ta) / (tj - ta)
            v = values[a] * (1 - u) + values[j] * u
            if is_quat:
                v = v / max(np.linalg.norm(v), 1e-12)
            if np.max(np.abs(v - values[i])) > tol:
                ok = False
                break
        if not ok:
            keep.append(j - 1)
            a = j - 1
        j += 1
    keep.append(n - 1)
    return np.array(sorted(set(keep)))


class AnimExporter:
    def __init__(self, context, lib, options=None):
        self.context = context
        self.lib = lib
        self.opts = options or AnimExportOptions()
        self.warnings = []
        self.b = BinBuilder(chunk_type="ANIM")
        self._time_cache = {}

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ---------------------------------------------------------------------------------------------
    def library_dict(self):
        lib = self.lib
        arm = lib.armature
        model_any = lib.target == "MODEL_ANY"
        if not model_any and (arm is None or arm.type != "ARMATURE"):
            raise ExportError(f"library '{lib.lib_id}': choose the rig (armature) first")
        if not LIBRARY_ID_RE.match(lib.lib_id):
            raise ExportError(f"library id '{lib.lib_id}' must match segment('@'segment)*, lowercase")
        for field in ("title", "description"):
            if not getattr(lib, field).strip():
                raise ExportError(f"library '{lib.lib_id}': {field} is required (write it, it is never generated)")
        if not BCP47_RE.match(lib.language):
            raise ExportError(f"library language '{lib.language}' is not a BCP-47 tag")
        d = {"id": lib.lib_id, "title": lib.title.strip(), "description": lib.description.strip(),
             "language": lib.language,
             "targetProfile": K.MODEL_ANY_PROFILE if model_any else arm.data.adm.profile_id.strip(),
             "binding": "SEMANTIC" if model_any else lib.binding}
        if not model_any and lib.binding == "EXACT":
            d["rigId"] = compute_rig_id(self.context, arm)
        tags, bad = parse_tags(lib.tags)
        if bad:
            raise ExportError(f"library tags must be lowercase segments: {', '.join(bad)}")
        if tags:
            d["tags"] = tags
        for k in ("author", "license"):
            if getattr(lib, k).strip():
                d[k] = getattr(lib, k).strip()
        if lib.revision.strip():
            if not SEMVER_RE.match(lib.revision.strip()):
                raise ExportError(f"revision '{lib.revision}' is not SemVer 2.0.0")
            d["revision"] = lib.revision.strip()
        if lib.namespace.strip():
            if not NAMESPACE_RE.match(lib.namespace.strip()):
                raise ExportError(f"namespace '{lib.namespace}' is not reverse-DNS (e.g. org.example)")
            d["namespace"] = lib.namespace.strip()
        if model_any:
            return d
        if lib.binding == "SEMANTIC":
            pid = d["targetProfile"]
            if SP.status(pid) == SP.EXACT_ONLY:
                raise ExportError(f"{pid} supports only EXACT binding")
            if SP.status(pid) is None:
                raise ExportError(f"profile '{pid}' is not in the skeleton profile registry; SEMANTIC retarget "
                                  f"rules are undefined (use EXACT binding)")
            from .export_adm import EXPORT_BLOCKING_RIG_CODES
            from .rig import assignments, correction_issues, joint_table
            for i in SK.analyze_rig(pid, joint_table(arm), assignments(arm)):
                if i.code in EXPORT_BLOCKING_RIG_CODES:
                    raise ExportError(f"rig '{arm.name}'{' bone ' + repr(i.bone) if i.bone else ''}: {i.message} "
                                      f"(Validate ADM Rig)")
                if i.severity != SK.INFO:
                    self.warn(f"rig '{arm.name}': {i.code}: {i.message}")
            for i in correction_issues(arm):
                self.warn(f"rig '{arm.name}': {i.code}: {i.message}")
            if lib.use_motion_scale:
                d["motionScale"] = "SOURCE_HEIGHT"
                d["sourceHeight"] = cv.f32(lib.source_height)
            if lib.root_motion_from_hips:
                d["rootMotionSource"] = "hips"
        return d

    # ---------------------------------------------------------------------------------------------
    def _times(self, frames, fs, fps):
        t = np.array([(f - fs) / fps for f in frames], dtype=np.float32)
        return t

    def _time_accessor(self, t):
        key = t.tobytes()
        if key not in self._time_cache:
            self._time_cache[key] = self.b.add_accessor(t, "F32", "SCALAR")
        return self._time_cache[key]

    def _channel(self, clip_out, target, path, times, values, kind, rest=None, typ=None):
        """Optimize and append one channel; ``values`` is (n, k)."""
        values = np.asarray(values, dtype=np.float64)
        tol = 1e-6
        if self.opts.optimize:
            if np.max(np.abs(values - values[0])) <= tol:
                if rest is not None and np.max(np.abs(values[0] - rest)) <= tol:
                    return
                times, values = times[:1], values[:1]
            else:
                idx = _reduce(times.astype(np.float64), values, tol * 10, is_quat=(path == "rotation"))
                times, values = times[idx], values[idx]
        acc_t = self._time_accessor(np.ascontiguousarray(times, dtype=np.float32))
        if typ is None:
            typ = {"rotation": "VEC4", "translation": "VEC3", "scale": "VEC3", "weight": "SCALAR"}[path]
        acc_v = self.b.add_accessor(values.astype(np.float32), "F32", typ)
        clip_out["samplers"].append({"input": acc_t, "output": acc_v, "interpolation": "LINEAR"})
        clip_out["channels"].append({"target": target, "path": path, "sampler": len(clip_out["samplers"]) - 1})

    def export_clip(self, clip, libd, ids):
        lib = self.lib
        arm = lib.armature
        if not SEGMENT_RE.match(clip.clip_id):
            raise ExportError(f"clip id '{clip.clip_id}' must match [a-z][a-z0-9_]*")
        if clip.clip_id in ids:
            raise ExportError(f"duplicate clip id '{clip.clip_id}'")
        ids.add(clip.clip_id)
        for field in ("title", "description"):
            if not getattr(clip, field).strip():
                raise ExportError(f"clip '{clip.clip_id}': {field} is required. ADM exporters must not invent "
                                  f"descriptions - please write one in the Animation panel.")
        if not BCP47_RE.match(clip.language):
            raise ExportError(f"clip '{clip.clip_id}': language '{clip.language}' is not BCP-47")
        if clip.action is None:
            raise ExportError(f"clip '{clip.clip_id}': no action assigned")
        tags, bad = parse_tags(clip.tags)
        if bad:
            raise ExportError(f"clip '{clip.clip_id}': invalid tags {', '.join(bad)}")
        scene = self.context.scene
        fps = scene.render.fps / scene.render.fps_base
        fs, fe = (float(clip.action.frame_range[0]), float(clip.action.frame_range[1])) if clip.use_action_range \
            else (float(clip.frame_start), float(clip.frame_end))
        if fe < fs:
            raise ExportError(f"clip '{clip.clip_id}': end frame before start frame")
        step = max(1, self.opts.sample_step)
        frames = list(np.arange(fs, fe, step, dtype=np.float64))
        if not frames or fe - frames[-1] > 1e-6:
            frames.append(fe)
        times = self._times(frames, fs, fps)
        duration = cv.f32_exact((fe - fs) / fps)
        out = {"id": clip.clip_id, "title": clip.title.strip(), "description": clip.description.strip(),
               "language": clip.language}
        if tags:
            out["tags"] = tags
        out.update({"duration": duration, "loop": clip.loop, "rootMotion": clip.root_motion,
                    "channels": [], "samplers": []})

        model_any = lib.target == "MODEL_ANY"
        binding = "SEMANTIC" if model_any else lib.binding
        if model_any:
            if clip.root_motion == "EXTRACT":
                raise ExportError(f"clip '{clip.clip_id}': model.any.v1 libraries cannot use root motion EXTRACT")
            bones, role_of = [], {}
        else:
            bones = list(arm.data.bones)
            role_of = {b.name: b.adm.role.strip() for b in bones if b.adm.role.strip()}
        if model_any:
            pass
        elif binding == "SEMANTIC":
            if not role_of:
                raise ExportError(f"armature '{arm.name}' has no semantic roles; map bones in the Skeleton panel")
            bones = [b for b in bones if b.name in role_of]
            if clip.root_motion == "EXTRACT" and not lib.root_motion_from_hips:
                raise ExportError(f"clip '{clip.clip_id}': EXTRACT with SEMANTIC binding needs "
                                  f"'Root Motion From Hips' on the library (humanoid.vrm1 has no 'root' role)")
        elif clip.root_motion == "EXTRACT":
            if not clip.root_bone or clip.root_bone not in arm.data.bones:
                raise ExportError(f"clip '{clip.clip_id}': EXTRACT needs the root motion bone")

        # assign action + slots
        assign = _Assign()
        act = clip.action
        meshes = morph_meshes(arm)
        frame_saved = scene.frame_current
        pose_saved = arm.data.pose_position if arm is not None else None
        registry = scene_shader_registry(scene)
        try:
            exprs = []
            if arm is not None:
                arm.data.pose_position = "POSE"
                arm_slot = pick_slot(act, "OBJECT", (arm.name,), strict=model_any)
                if arm_slot is not None:
                    assign.assign(arm, act, arm_slot)
                arm_fcurves = channelbag_fcurves(act, arm_slot)
                exprs = sorted({m.group(1) for fc in arm_fcurves for m in [EXPR_PATH_RE.match(fc.data_path)] if m})
            morph_src = {}  # key name -> (key datablock)
            for o in meshes:
                key = o.data.shape_keys
                slot = pick_slot(act, "KEY", (key.name, o.name, o.data.name), strict=arm is None)
                if slot is None:
                    continue
                assign.assign(key, act, slot)
                for fc in channelbag_fcurves(act, slot):
                    m = KEY_PATH_RE.match(fc.data_path)
                    if m and m.group(1) in key.key_blocks and m.group(1) not in morph_src:
                        morph_src[m.group(1)] = key
            mat_tracks = []  # (mat, explicit shader params, sample pbr?)
            for mat, ms, ns in mat_anim.animated_materials(act):
                for idb, slot in ((mat, ms), (mat.node_tree, ns)):
                    if slot is not None and idb is not None:
                        assign.assign(idb, act, slot)
                m_fc = channelbag_fcurves(act, ms)
                explicit = mat_anim.animated_shader_params(mat, m_fc)
                pbr_cutoff = any(fc.data_path == "adm.alpha_cutoff" for fc in m_fc)
                mat_tracks.append((mat, explicit, ns is not None and bool(channelbag_fcurves(act, ns)), pbr_cutoff))

            rest = {}
            arm_rot = None
            if arm is not None:
                for b in arm.data.bones:
                    rl = b.parent.matrix_local.inverted_safe() @ b.matrix_local if b.parent else b.matrix_local.copy()
                    rest[b.name] = cv.mat_to_adm(rl)
                arm_rot = (find_model_root_inv(arm) @ arm.matrix_world).to_3x3()
            samples = {b.name: {"t": [], "r": [], "s": []} for b in bones}
            msamples = {k: [] for k in morph_src}
            esamples = {e: [] for e in exprs}
            psamples = {mat.name: [] for mat, *_ in mat_tracks}
            ssamples = {mat.name: [] for mat, *_ in mat_tracks}
            for f in frames:
                fi = int(np.floor(f))
                scene.frame_set(fi, subframe=float(f - fi))
                for b in bones:
                    pb = arm.pose.bones[b.name]
                    local = pb.parent.matrix.inverted_safe() @ pb.matrix if pb.parent else pb.matrix.copy()
                    t, r, s = cv.mat_to_adm(local).decompose()
                    sm = samples[b.name]
                    if binding == "SEMANTIC" and role_of[b.name] == "hips":
                        off = cv.C3 @ (arm_rot @ (pb.matrix.to_translation() - b.matrix_local.to_translation()))
                        sm["t"].append((off.x, off.y, off.z))
                    else:
                        sm["t"].append(tuple(t))
                    sm["r"].append(r)
                    sm["s"].append(tuple(s))
                for k, key in morph_src.items():
                    msamples[k].append(min(1.0, max(0.0, key.key_blocks[k].value)))
                for e in exprs:
                    esamples[e].append(min(1.0, max(0.0, float(arm.get(EXPR_PREFIX + e, 0.0)))))
                for mat, *_ in mat_tracks:
                    psamples[mat.name].append(mat_anim.pbr_values(mat))
                    ssamples[mat.name].append(mat_anim.shader_param_values(mat, registry))
        finally:
            assign.restore()
            if arm is not None:
                arm.data.pose_position = pose_saved
            scene.frame_set(frame_saved)

        for b in sorted(bones, key=lambda b: (role_of.get(b.name, ""), b.name)):
            sm = samples[b.name]
            rt, rr, rs = rest[b.name].decompose()
            if binding == "SEMANTIC":
                role = role_of[b.name]
                target = {"kind": "bone", "role": role}
                corr = Quaternion((1, 0, 0, 0))
                if b.adm.use_reference_correction:
                    corr = _adm_q(cv.quat_to_adm(Quaternion(b.adm.reference_correction)))
                rot = [corr.inverted() @ rr.inverted() @ q @ corr for q in sm["r"]]
                self._channel(out, target, "rotation", times, _quat_track(rot), "bone", rest=np.array([0, 0, 0, 1.0]))
                if role == "hips":
                    keep = clip.root_motion == "EXTRACT"
                    self._channel(out, dict(target), "translation", times, np.array(sm["t"]), "bone",
                                  rest=None if keep else np.zeros(3))
            else:
                target = {"kind": "bone", "nodeName": b.name}
                is_root = clip.root_motion == "EXTRACT" and b.name == clip.root_bone
                self._channel(out, target, "rotation", times, _quat_track(sm["r"]), "bone",
                              rest=None if is_root else np.array(_q_xyzw(rr)))
                self._channel(out, dict(target), "translation", times, np.array(sm["t"]), "bone",
                              rest=None if is_root else np.array(tuple(rt)))
                self._channel(out, dict(target), "scale", times, np.array(sm["s"]), "bone",
                              rest=np.array(tuple(rs)))
        for k in sorted(msamples):
            self._channel(out, {"kind": "morph", "name": k}, "weight", times, np.array(msamples[k])[:, None], "morph")
        for e in sorted(esamples):
            self._channel(out, {"kind": "expression", "name": e}, "weight", times,
                          np.array(esamples[e])[:, None], "expression")
        for mat, explicit, _nt_anim, _cut in mat_tracks:
            self._material_channels(out, mat, explicit, psamples[mat.name], ssamples[mat.name], times, registry)

        events = []
        for ev in clip.events:
            if not EVENT_NAME_RE.match(ev.name):
                raise ExportError(f"clip '{clip.clip_id}': event name '{ev.name}' must match [a-z][a-z0-9_.]*")
            e = {"time": min(duration, max(0.0, cv.f32(ev.time))), "name": ev.name}
            if ev.payload.strip():
                try:
                    payload = json.loads(ev.payload)
                except ValueError as exc:
                    raise ExportError(f"clip '{clip.clip_id}': event '{ev.name}' payload is not JSON: {exc}")
                if not isinstance(payload, dict):
                    raise ExportError(f"clip '{clip.clip_id}': event payload must be a JSON object")
                e["payload"] = payload
            events.append(e)
        events.sort(key=lambda e: (e["time"], e["name"], _canonical_json(e.get("payload", {})) if "payload" in e
                                   else b""))
        if events:
            out["events"] = events
        if not out["channels"]:
            self.warn(f"clip '{clip.clip_id}': no animated channels")
        return out

    def _material_channels(self, out, mat, explicit, psamp, ssamp, times, registry):
        aid = mat.adm.animation_id.strip()
        for name, (typ, lo, hi) in K.PBR_PARAMETERS.items():
            if not psamp or name not in psamp[0]:
                continue
            vals = np.array([np.atleast_1d(np.asarray(s[name], dtype=np.float64)) for s in psamp])
            if np.max(np.abs(vals - vals[0])) <= 1e-6:
                continue
            vals = np.clip(vals, lo, hi if hi is not None else np.inf)
            self._channel(out, {"kind": "pbrParameter", "materialId": aid, "parameter": name}, "value",
                          times, vals, "pbr", typ=typ)
        key = mat.adm.shader_key()
        params = registry.get(key, {})
        for name in sorted(explicit):
            prm = params.get(name)
            if prm is None or not prm.get("animatable") or prm.get("type") not in K.SHADER_TYPE_TO_ACCESSOR:
                self.warn(f"material '{mat.name}': parameter '{name}' is not an animatable numeric parameter "
                          f"of shader {key[0]}@{key[1]}; skipped")
                continue
            vals = np.array([np.asarray(s[name], dtype=np.float64) for s in ssamp])
            lo, hi = prm.get("minimum"), prm.get("maximum")
            if lo is not None:
                vals = np.maximum(vals, np.asarray(lo, dtype=np.float64))
            if hi is not None:
                vals = np.minimum(vals, np.asarray(hi, dtype=np.float64))
            target = {"kind": "shaderParameter", "materialId": aid, "shaderId": key[0], "shaderVersion": key[1],
                      "parameter": name}
            self._channel(out, target, "value", times, vals, "shader",
                          typ=K.SHADER_TYPE_TO_ACCESSOR[prm["type"]])

    def export(self):
        try:
            return self._export()
        except AdmFormatError as exc:
            raise ExportError(str(exc)) from exc

    def _export(self):
        libd = self.library_dict()
        clips = []
        ids = set()
        for clip in self.lib.clips:
            clips.append(self.export_clip(clip, libd, ids))
        if not clips:
            raise ExportError(f"library '{self.lib.lib_id}' has no clips")
        doc = {"asset": {"generator": GENERATOR}, "library": libd, "clips": clips,
               "accessors": self.b.accessors, "bufferViews": self.b.buffer_views}
        data = write_container(K.ANIM_MAGIC, doc, self.b.bytes())
        report = validate_anim(data) if self.opts.validate else None
        if report is not None and not report.ok:
            raise ExportError("exported animation library failed ADM validation", report)
        return data, report


def find_model_root_inv(arm):
    root = find_model_root(arm)
    from mathutils import Matrix
    return root.matrix_world.inverted_safe() if root is not None else Matrix.Identity(4)


def _adm_q(xyzw):
    x, y, z, w = xyzw
    return Quaternion((w, x, y, z))


def _q_xyzw(q):
    q = q.normalized()
    if q.w < 0:
        q = -q
    return (q.x, q.y, q.z, q.w)


def _quat_track(quats):
    out = []
    prev = None
    for q in quats:
        q = q.normalized()
        v = np.array((q.x, q.y, q.z, q.w))
        if prev is None:
            if v[3] < 0:
                v = -v
        elif np.dot(prev, v) < 0:
            v = -v
        out.append(v)
        prev = v
    return np.array(out)


def export_library(context, lib, filepath, options=None):
    exp = AnimExporter(context, lib, options)
    data, report = exp.export()
    with open(filepath, "wb") as fh:
        fh.write(data)
    return exp, report
