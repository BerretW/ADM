"""Blender scene -> ADM model (.adm) exporter.

Structure (Sollumz-like): an empty with ``adm.adm_type == 'MODEL'`` is the model root. It is NOT written as a
node; its children become scene roots (transforms relative to the root). Children of type SCENE start
additional scenes. Without a model root the whole view layer (or the selection) is exported as one scene.
"""

import hashlib
import os
from collections import defaultdict

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from ..core import constants as K
from ..core import skeleton as SK
from ..core import skeleton_profiles as SP
from ..core.buffers import BinBuilder
from ..core.container import AdmFormatError, write_container
from ..core.rigid import rig_id_from_document
from ..core.validate import validate_adm
from . import convert as cv
from .materials import MaterialExporter, ShaderExportError, TextureExportError

GENERATOR = "ADM Tools for Blender 1.9.0 (ADM Draft 0.4 P9)"
MESHLIKE = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
NON_GEOMETRY_TYPES = {"MODEL", "SCENE", "COLLIDER", "LOD_GROUP", "ATTACHMENT"}
# rig analysis results that would produce a structurally invalid skeletonProfiles entry
EXPORT_BLOCKING_RIG_CODES = {"PROFILE_ID", "ROLE_UNKNOWN", "ROLE_DUPLICATE", "ROLE_MISSING", "ROLE_NEEDS_PARENT",
                             "ROLE_HIERARCHY", "ROLE_BONE_MISSING"}


def rig_issue_blocks_semantic(pid, code):
    return code in EXPORT_BLOCKING_RIG_CODES or (
        pid == "humanoid.vrm1" and code in {"REFERENCE_POSE", "REFERENCE_FACING", "REFERENCE_CORRECTION"})


class ExportError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class ExportOptions:
    def __init__(self, **kw):
        self.selected_only = False
        self.apply_modifiers = True
        self.export_normals = True
        self.export_tangents = "AUTO"  # AUTO | ALWAYS | NEVER
        self.export_uv1 = True
        self.export_colors = True
        self.export_morph_normals = True
        self.export_materials = True
        self.embed_textures = True
        self.vertex_controls = False
        self.image_format = "PNG"  # PNG | AUTO (keep PNG/JPEG) | KTX2 | DDS
        self.gpu_compression = "AUTO"  # AUTO | BC1 | BC3 | RGBA8 (KTX2/DDS payload)
        self.gpu_mipmaps = True
        self.validate = True
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown export option {k!r}")
            setattr(self, k, v)


class NodeRec:
    __slots__ = ("index", "name", "local", "world", "parent", "children", "kind", "obj", "arm", "bone")

    def __init__(self, index, name, local, world, parent, kind, obj=None, arm=None, bone=None):
        self.index, self.name, self.local, self.world, self.parent = index, name, local, world, parent
        self.children = []
        self.kind, self.obj, self.arm, self.bone = kind, obj, arm, bone


def find_model_root(obj):
    o = obj
    while o is not None:
        if o.adm.adm_type == "MODEL":
            return o
        o = o.parent
    return None


class RestPose:
    """Temporarily switch armatures to rest position so matrices reflect the bind pose."""

    def __init__(self, context):
        self.context = context
        self.saved = []

    def __enter__(self):
        for arm in {o.data for o in self.context.scene.objects if o.type == "ARMATURE"}:
            if arm.pose_position != "REST":
                self.saved.append((arm, arm.pose_position))
                arm.pose_position = "REST"
        self.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        for arm, pos in self.saved:
            arm.pose_position = pos
        self.context.view_layer.update()
        return False


def _np_get(coll, attr, n, width, dtype=np.float32):
    out = np.empty(n * width, dtype=dtype)
    if n:
        coll.foreach_get(attr, out)
    return out.reshape(n, width) if width > 1 else out


def _normalize_rows(a, fallback):
    lens = np.linalg.norm(a, axis=1)
    bad = lens < 1e-12
    a = a / np.where(bad, 1.0, lens)[:, None]
    if bad.any():
        a[bad] = fallback
    return a


def _material_texcoords(m):
    need = set()
    for k in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture", "occlusionTexture",
              "emissiveTexture"):
        if k in m:
            need.add(m[k].get("texCoord", 0))
    layers = (m.get("extensions") or {}).get(K.LAYERS_EXT) or {}
    if "maskTexture" in layers:
        need.add(layers["maskTexture"].get("texCoord", 0))
    for v in (m.get("shaderParameters") or {}).values():
        if isinstance(v, dict) and "index" in v:
            need.add(v.get("texCoord", 0))
    return need


# ================================================================================================
class ModelExporter:
    def __init__(self, context, root=None, options=None):
        self.context = context
        self.root = root
        self.opts = options or ExportOptions()
        self.warnings = []
        self.nodes = []
        self.obj_node = {}
        self.bone_node = {}
        self.arm_joints = {}
        self.scenes = []
        self.root_inv = root.matrix_world.inverted_safe() if root else Matrix.Identity(4)
        self.b = BinBuilder()
        self.meshes = []
        self.mesh_cache = {}
        self.node_mesh = {}
        self.node_skin = {}
        self.skins = []
        self.skin_cache = {}
        self.mat = MaterialExporter(self.b, self.warn, self.opts.image_format,
                                    gpu_compression=self.opts.gpu_compression, gpu_mipmaps=self.opts.gpu_mipmaps,
                                    embed_images=self.opts.embed_textures,
                                    vertex_controls=self.opts.vertex_controls)
        self.mat.shader_defs = {(d.shader_id.strip(), d.version.strip()): d
                                for d in context.scene.adm_anim.shaders}
        self.allowed = self._allowed_objects()

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ---------------------------------------------------------------------------------------------
    # phase 1: node graph
    # ---------------------------------------------------------------------------------------------
    def _allowed_objects(self):
        vl_objs = list(self.context.view_layer.objects)
        names = set()

        def excluded(o):
            while o is not None:
                if o.adm.export_exclude:
                    return True
                o = o.parent
            return False

        if self.root is not None:
            stack = list(self.root.children)
            while stack:
                o = stack.pop()
                if o.adm.export_exclude:
                    continue
                names.add(o.name)
                stack.extend(o.children)
            return names
        for o in vl_objs:
            if excluded(o):
                continue
            if self.opts.selected_only and not o.select_get():
                continue
            names.add(o.name)
        return names

    def _children(self, obj):
        return sorted((c for c in obj.children if c.name in self.allowed), key=lambda o: o.name)

    def _new(self, name, local, world, parent, kind, **kw):
        rec = NodeRec(len(self.nodes), name, local, world, parent, kind, **kw)
        self.nodes.append(rec)
        if parent is not None:
            self.nodes[parent].children.append(rec.index)
        return rec.index

    def _visit_object(self, obj, parent, parent_world):
        world = self.root_inv @ obj.matrix_world
        local = parent_world.inverted_safe() @ world
        idx = self._new(obj.name, local, world, parent, "OBJECT", obj=obj)
        self.obj_node[obj.name] = idx
        bone_kids = defaultdict(list)
        for c in self._children(obj):
            if obj.type == "ARMATURE" and c.parent_type == "BONE" and c.parent_bone in obj.data.bones:
                bone_kids[c.parent_bone].append(c)
        if obj.type == "ARMATURE":
            self._visit_bones(obj, idx, world, bone_kids)
        for c in self._children(obj):
            if obj.type == "ARMATURE" and c.parent_type == "BONE" and c.parent_bone in obj.data.bones:
                continue
            self._visit_object(c, idx, world)

    def _visit_bones(self, arm, arm_idx, arm_world, bone_kids):
        order = []

        def rec(bone, pidx, pworld, pmat):
            local = pmat.inverted_safe() @ bone.matrix_local if pmat is not None else bone.matrix_local.copy()
            world = pworld @ local
            i = self._new(bone.name, local, world, pidx, "BONE", arm=arm, bone=bone)
            self.bone_node[(arm.name, bone.name)] = i
            order.append(i)
            for c in bone_kids.get(bone.name, []):
                self._visit_object(c, i, world)
            for ch in sorted(bone.children, key=lambda b: b.name):
                rec(ch, i, world, bone.matrix_local)

        for b in sorted((b for b in arm.data.bones if b.parent is None), key=lambda b: b.name):
            rec(b, arm_idx, arm_world, None)
        if order:
            self.arm_joints[arm.name] = order

    def build_graph(self):
        if self.root is not None:
            kids = self._children(self.root)
            scene_objs = [c for c in kids if c.adm.adm_type == "SCENE"]
            loose = [c for c in kids if c.adm.adm_type != "SCENE"]
            groups = []
            if loose or not scene_objs:
                groups.append((self.root.name, loose, Matrix.Identity(4)))
            for s in scene_objs:
                groups.append((s.name, self._children(s), self.root_inv @ s.matrix_world))
        else:
            roots = sorted((self.context.view_layer.objects[n] for n in self.allowed
                            if self.context.view_layer.objects[n].parent is None
                            or self.context.view_layer.objects[n].parent.name not in self.allowed),
                           key=lambda o: o.name)
            groups = [(self.context.scene.name, roots, Matrix.Identity(4))]
        for name, objs, base in groups:
            roots = []
            for o in objs:
                roots.append(len(self.nodes))
                self._visit_object(o, None, base)
            self.scenes.append({"name": name, "nodes": roots})
        if not self.nodes:
            raise ExportError("nothing to export (no objects)")

    # ---------------------------------------------------------------------------------------------
    # skins
    # ---------------------------------------------------------------------------------------------
    def skin_for(self, arm, mesh_world):
        key = (arm.name, tuple(round(v, 6) for row in mesh_world for v in row))
        if key in self.skin_cache:
            return self.skin_cache[key]
        joints = self.arm_joints[arm.name]
        ibm = []
        for j in joints:
            m = cv.mat_to_adm(self.nodes[j].world.inverted_safe() @ mesh_world)
            ibm.extend(cv.matrix_to_list(m))
        acc = self.b.add_accessor(np.array(ibm, dtype=np.float32), "F32", "MAT4")
        self.skins.append({"name": arm.name, "joints": list(joints), "inverseBindMatrices": acc})
        self.skin_cache[key] = len(self.skins) - 1
        return self.skin_cache[key]

    def profile_skin(self, arm):
        return self.skin_for(arm, self.nodes[self.obj_node[arm.name]].world)

    def _skin_armature(self, obj):
        for m in obj.modifiers:
            if m.type == "ARMATURE" and m.object is not None and m.object.name in self.arm_joints and m.show_viewport:
                return m.object
        p = obj.parent
        if p is not None and p.type == "ARMATURE" and obj.parent_type == "ARMATURE" and p.name in self.arm_joints:
            return p
        return None

    # ---------------------------------------------------------------------------------------------
    # meshes
    # ---------------------------------------------------------------------------------------------
    def _materials_for(self, obj, uv_names):
        out = []
        for slot in obj.material_slots:
            if self.opts.export_materials and slot.material is not None:
                out.append(self.mat.index(slot.material, uv_names))
            else:
                out.append(None)
        return out

    def mesh_index_for(self, obj, collision=False):
        if obj.type not in MESHLIKE:
            return None
        arm = None if collision else self._skin_armature(obj)
        has_keys = (obj.type == "MESH" and obj.data.shape_keys is not None
                    and len(obj.data.shape_keys.key_blocks) > 1 and not collision)
        extra_mods = [m for m in obj.modifiers if m.show_viewport and m.type != "ARMATURE"]
        use_eval = obj.type != "MESH" or (self.opts.apply_modifiers and extra_mods and not has_keys)
        if has_keys and extra_mods and self.opts.apply_modifiers:
            self.warn(f"'{obj.name}': modifiers {', '.join(m.name for m in extra_mods)} ignored because the mesh "
                      f"has shape keys (apply them first)")
        mats = tuple(s.material.name if s.material else "" for s in obj.material_slots)
        key = None if use_eval else (obj.data.name, mats, arm.name if arm else "", collision,
                                     tuple(vg.name for vg in obj.vertex_groups) if arm else ())
        if key is not None and key in self.mesh_cache:
            return self.mesh_cache[key]
        me = None
        obj_eval = None
        try:
            if use_eval:
                dg = self.context.evaluated_depsgraph_get()
                obj_eval = obj.evaluated_get(dg)
                me = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
            else:
                me = obj.data
            mesh = self._build_mesh(obj, me, arm, has_keys, collision)
        finally:
            if obj_eval is not None:
                obj_eval.to_mesh_clear()
        if mesh is None:
            result = None
        else:
            self.meshes.append(mesh)
            result = (len(self.meshes) - 1, arm) if arm is not None else len(self.meshes) - 1
        if key is not None:
            self.mesh_cache[key] = result
        return result

    def _uv_layers(self, me):
        layers = list(me.uv_layers)
        if not layers:
            return []
        first = next((l for l in layers if l.active_render), layers[0])
        rest = [l for l in layers if l.name != first.name]
        out = [first]
        if self.opts.export_uv1 and rest:
            out.append(rest[0])
        return out

    def _build_mesh(self, obj, me, arm, has_keys, collision):
        me.calc_loop_triangles()
        ntri = len(me.loop_triangles)
        if ntri == 0:
            self.warn(f"'{obj.name}': mesh has no faces, skipped")
            return None
        tri_loops = _np_get(me.loop_triangles, "loops", ntri, 3, np.int64).reshape(-1)
        tri_mat = _np_get(me.loop_triangles, "material_index", ntri, 1, np.int64)
        tri_polygons = _np_get(me.loop_triangles, "polygon_index", ntri, 1, np.int64)
        nloops = len(me.loops)
        nverts = len(me.vertices)
        loop_vert = _np_get(me.loops, "vertex_index", nloops, 1, np.int64)
        if has_keys:
            ref = me.shape_keys.reference_key
            co = _np_get(ref.data, "co", nverts, 3).astype(np.float64)
        else:
            co = _np_get(me.vertices, "co", nverts, 3).astype(np.float64)

        uv_layers = [] if collision else self._uv_layers(me)
        uv_names = [l.name for l in uv_layers]
        mat_slots = [] if collision else self._materials_for(obj, uv_names)
        prim_mats = []
        for mi in tri_mat:
            prim_mats.append(mat_slots[mi] if 0 <= mi < len(mat_slots) else None)
        prim_mats = np.array([-1 if m is None else m for m in prim_mats], dtype=np.int64)
        face_physical_ids = None
        physical_attr = me.attributes.get("adm_physical_material_id") if collision else None
        if physical_attr is not None:
            if physical_attr.domain != "FACE" or physical_attr.data_type != "STRING":
                raise ExportError(f"collider '{obj.name}': adm_physical_material_id must be a FACE string attribute")
            try:
                face_physical_ids = [
                    value.decode("utf-8") if isinstance(value, bytes) else value
                    for value in (physical_attr.data[int(poly)].value for poly in tri_polygons)
                ]
            except UnicodeDecodeError as exc:
                raise ExportError(f"collider '{obj.name}': adm_physical_material_id contains invalid UTF-8") from exc

        columns = [loop_vert[tri_loops].astype(np.float64)[:, None]]
        normals = tangents = None
        if not collision and self.opts.export_normals:
            normals = _np_get(me.corner_normals, "vector", nloops, 3).astype(np.float64)
            normals = _normalize_rows(normals, (0.0, 0.0, 1.0))
            columns.append(normals[tri_loops])
        uvs = []
        need_uv = set()
        for m in set(prim_mats.tolist()):
            if m >= 0:
                need_uv |= _material_texcoords(self.mat.materials[m])
        for i, layer in enumerate(uv_layers):
            uv = _np_get(layer.uv, "vector", nloops, 2).astype(np.float64)
            uvs.append(cv.np_uv_to_adm(uv))
        if need_uv:
            if not uvs:
                self.warn(f"'{obj.name}': material uses textures but the mesh has no UV map (zeros written)")
                uvs.append(np.zeros((nloops, 2)))
            if 1 in need_uv and len(uvs) < 2:
                self.warn(f"'{obj.name}': material needs TEXCOORD_1 but mesh has one UV map (copied)")
                uvs.append(uvs[0].copy())
        for uv in uvs:
            columns.append(uv[tri_loops])
        colors = None
        colors1 = None
        if not collision and self.opts.export_colors:
            if self.opts.vertex_controls:
                ca = me.color_attributes.get("COLOR_0")
                ca1 = me.color_attributes.get("COLOR_1")
            else:
                ca = me.color_attributes.get(obj.data.color_attributes.active_color_name) \
                    if obj.type == "MESH" and obj.data.color_attributes.active_color_name else None
                if ca is None and me.color_attributes.active_color is not None:
                    ca = me.color_attributes.active_color
                ca1 = None
            if ca is not None:
                n = nverts if ca.domain == "POINT" else nloops
                col = _np_get(ca.data, "color", n, 4).astype(np.float64)
                colors = col[loop_vert] if ca.domain == "POINT" else col
                colors = np.clip(colors, 0.0, 1.0)
                columns.append(colors[tri_loops])
            if ca1 is not None:
                n = nverts if ca1.domain == "POINT" else nloops
                col = _np_get(ca1.data, "color", n, 4).astype(np.float64)
                colors1 = col[loop_vert] if ca1.domain == "POINT" else col
                colors1 = np.clip(colors1, 0.0, 1.0)
                columns.append(colors1[tri_loops])
        normal_mapped = any(m >= 0 and "normalTexture" in self.mat.materials[m] for m in set(prim_mats.tolist()))
        want_tangents = normals is not None and uvs and (
            self.opts.export_tangents == "ALWAYS" or (self.opts.export_tangents == "AUTO" and normal_mapped))
        if want_tangents:
            tangents = self._tangents(me, uv_layers, uvs[0], normals, loop_vert, tri_loops, co, obj)
            columns.append(tangents[tri_loops])

        # skinning (per vertex)
        joints = weights = None
        if arm is not None:
            joints, weights = self._skin_weights(obj, me, arm)

        # morph targets
        key_names, key_weights, key_pos, key_nrm = [], [], [], []
        if has_keys:
            kbs = me.shape_keys.key_blocks
            ref = me.shape_keys.reference_key
            cache = {}

            def kco(kb):
                if kb.name not in cache:
                    cache[kb.name] = _np_get(kb.data, "co", nverts, 3).astype(np.float64)
                return cache[kb.name]

            base_n = normals
            for kb in kbs:
                if kb.name == ref.name:
                    continue
                rel = kb.relative_key if kb.relative_key is not None else ref
                key_names.append(kb.name)
                key_weights.append(0.0 if kb.mute else min(1.0, max(0.0, kb.value)))
                key_pos.append(kco(kb) - kco(rel))
                if base_n is not None and self.opts.export_morph_normals:
                    kn = np.array(kb.normals_split_get(), dtype=np.float64).reshape(-1, 3)
                    if rel.name != ref.name:
                        rn = np.array(rel.normals_split_get(), dtype=np.float64).reshape(-1, 3)
                    else:
                        rn = base_n
                    key_nrm.append(kn - rn if len(kn) == nloops else None)
                else:
                    key_nrm.append(None)

        prims = []
        mesh_targets_used = bool(key_names)
        for m in sorted(set(prim_mats.tolist())):
            tri_sel = np.nonzero(prim_mats == m)[0]
            corner_sel = (tri_sel[:, None] * 3 + np.arange(3)[None, :]).reshape(-1)
            rows = np.hstack([c[corner_sel] for c in columns])
            _, first, inverse = np.unique(rows, axis=0, return_index=True, return_inverse=True)
            inverse = inverse.reshape(-1)
            order = np.argsort(first)
            remap = np.empty_like(order)
            remap[order] = np.arange(len(order))
            first = first[order]
            indices = remap[inverse]
            src_corner = tri_loops[corner_sel[first]]
            src_vert = loop_vert[src_corner]
            attrs = {"POSITION": self.b.add_accessor(cv.np_vec_to_adm(co[src_vert]), "F32", "VEC3")}
            if normals is not None:
                attrs["NORMAL"] = self.b.add_accessor(cv.np_vec_to_adm(normals[src_corner]), "F32", "VEC3")
            if tangents is not None:
                t = tangents[src_corner]
                txyz = cv.np_vec_to_adm(t[:, :3])
                attrs["TANGENT"] = self.b.add_accessor(np.hstack([txyz, t[:, 3:4]]), "F32", "VEC4")
            for i, uv in enumerate(uvs[:2]):
                attrs["TEXCOORD_%d" % i] = self.b.add_accessor(uv[src_corner], "F32", "VEC2")
            if colors is not None:
                attrs["COLOR_0"] = self.b.add_accessor(colors[src_corner], "F32", "VEC4")
            if colors1 is not None:
                attrs["COLOR_1"] = self.b.add_accessor(colors1[src_corner], "F32", "VEC4")
            if joints is not None:
                jt = joints[src_vert]
                attrs["JOINTS_0"] = self.b.add_accessor(jt, "U8" if jt.max() < 256 else "U16", "VEC4")
                attrs["WEIGHTS_0"] = self.b.add_accessor(weights[src_vert], "F32", "VEC4")
            ct = "U16" if len(first) <= 65535 else "U32"
            prim = {"attributes": attrs, "indices": self.b.add_accessor(indices, ct, "SCALAR")}
            if m >= 0:
                prim["material"] = int(m)
            if face_physical_ids is not None and any(face_physical_ids[i] for i in tri_sel):
                fallback_id = obj.adm.physical_material.strip()
                resolved_ids = [face_physical_ids[i] or fallback_id for i in tri_sel]
                if any(not ident for ident in resolved_ids):
                    raise ExportError(f"collider '{obj.name}': every face with physical material data must name "
                                      "a physical material ID or use the collider default")
                prim.setdefault("extensions", {})[K.PHYSICAL_SURFACES_EXT] = {
                    "faceMaterials": resolved_ids,
                }
                self.mat.extensions_used.add(K.PHYSICAL_SURFACES_EXT)
                self.mat.extensions_required.add(K.PHYSICAL_SURFACES_EXT)
            if mesh_targets_used:
                targets = []
                for kp, kn in zip(key_pos, key_nrm):
                    t = {}
                    d = kp[src_vert]
                    if np.any(np.abs(d) > 0):
                        t["POSITION"] = self.b.add_accessor(cv.np_vec_to_adm(d), "F32", "VEC3")
                    if kn is not None and normals is not None:
                        dn = kn[src_corner]
                        if np.any(np.abs(dn) > 1e-7):
                            t["NORMAL"] = self.b.add_accessor(cv.np_vec_to_adm(dn), "F32", "VEC3")
                    targets.append(t)
                prim["targets"] = targets
            prims.append(prim)
        out = {"name": obj.data.name if obj.type == "MESH" else obj.name, "primitives": prims}
        if mesh_targets_used:
            out["targetNames"] = key_names
            if any(w != 0.0 for w in key_weights):
                out["weights"] = [cv.f32(w) for w in key_weights]
        return out

    def _tangents(self, me, uv_layers, uv0_adm, normals, loop_vert, tri_loops, co, obj):
        nloops = len(me.loops)
        try:
            me.calc_tangents(uvmap=uv_layers[0].name)
            t = _np_get(me.loops, "tangent", nloops, 3).astype(np.float64)
            s = _np_get(me.loops, "bitangent_sign", nloops, 1).astype(np.float64)
            me.free_tangents()
        except (RuntimeError, AttributeError):
            t, s = self._tangents_fallback(me, uv0_adm, normals, loop_vert, tri_loops, co)
        t = t - normals * np.sum(t * normals, axis=1)[:, None]
        lens = np.linalg.norm(t, axis=1)
        bad = lens < 1e-10
        if bad.any():
            alt = np.cross(normals[bad], np.array([0.0, 0.0, 1.0]))
            small = np.linalg.norm(alt, axis=1) < 1e-6
            alt[small] = np.cross(normals[bad][small], np.array([1.0, 0.0, 0.0]))
            t[bad] = alt
            lens = np.linalg.norm(t, axis=1)
        t = t / lens[:, None]
        s = np.where(s < 0, -1.0, 1.0)
        return np.hstack([t, s[:, None]])

    def _tangents_fallback(self, me, uv_adm, normals, loop_vert, tri_loops, co):
        nloops = len(me.loops)
        uv = uv_adm.copy()
        uv[:, 1] = 1.0 - uv[:, 1]  # back to Blender convention for derivation
        tl = tri_loops.reshape(-1, 3)
        p = co[loop_vert[tl]]
        w = uv[tl]
        e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
        d1, d2 = w[:, 1] - w[:, 0], w[:, 2] - w[:, 0]
        r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        r = np.where(np.abs(r) < 1e-20, 1.0, 1.0 / np.where(r == 0, 1.0, r))
        sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
        tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r[:, None]
        tan = np.zeros((nloops, 3))
        bit = np.zeros((nloops, 3))
        for k in range(3):
            np.add.at(tan, tl[:, k], sdir)
            np.add.at(bit, tl[:, k], tdir)
        sign = np.where(np.sum(np.cross(normals, tan) * bit, axis=1) < 0.0, -1.0, 1.0)
        return tan, sign

    def _skin_weights(self, obj, me, arm):
        joints = self.arm_joints[arm.name]
        name_to_joint = {}
        for ji, ni in enumerate(joints):
            bone = self.nodes[ni].bone
            if bone.use_deform:
                name_to_joint[bone.name] = ji
        group_to_joint = {vg.index: name_to_joint[vg.name] for vg in obj.vertex_groups if vg.name in name_to_joint}
        fallback = 0
        if obj.parent_type == "BONE" and obj.parent_bone:
            for ji, ni in enumerate(joints):
                if self.nodes[ni].bone.name == obj.parent_bone:
                    fallback = ji
        nverts = len(me.vertices)
        J = np.zeros((nverts, 4), dtype=np.uint16)
        W = np.zeros((nverts, 4), dtype=np.float64)
        unweighted = 0
        dropped = 0
        for v in me.vertices:
            inf = [(g.weight, group_to_joint[g.group]) for g in v.groups
                   if g.group in group_to_joint and g.weight > 0.0]
            if not inf:
                unweighted += 1
                inf = [(1.0, fallback)]
            if len(inf) > 4:
                dropped += 1
                inf.sort(key=lambda x: (-x[0], x[1]))
                inf = inf[:4]
            s = sum(w for w, _ in inf)
            for k, (w, j) in enumerate(inf):
                J[v.index, k] = j
                W[v.index, k] = w / s
        if unweighted:
            self.warn(f"'{obj.name}': {unweighted} vertices without deform weights bound rigidly to "
                      f"'{self.nodes[joints[fallback]].name}'")
        if dropped:
            self.warn(f"'{obj.name}': {dropped} vertices had more than 4 influences (smallest dropped, renormalized)")
        W = W.astype(np.float32)
        W[:, 0] += np.float32(1.0) - W.sum(axis=1)
        return J, W

    # ---------------------------------------------------------------------------------------------
    # phase 2: content
    # ---------------------------------------------------------------------------------------------
    def build_content(self):
        for rec in self.nodes:
            obj = rec.obj
            if rec.kind != "OBJECT" or obj.adm.adm_type in NON_GEOMETRY_TYPES or obj.type not in MESHLIKE:
                continue
            res = self.mesh_index_for(obj)
            if res is None:
                continue
            if isinstance(res, tuple):
                mi, arm = res
                self.node_mesh[rec.index] = mi
                self.node_skin[rec.index] = self.skin_for(arm, rec.world)
            else:
                self.node_mesh[rec.index] = res

    def _node_dicts(self):
        out = []
        for rec in self.nodes:
            n = {"name": rec.name}
            if rec.children:
                n["children"] = list(rec.children)
            n.update(cv.node_transform_fields(rec.local, force_trs=rec.kind == "BONE"))
            if rec.index in self.node_mesh:
                n["mesh"] = self.node_mesh[rec.index]
            if rec.index in self.node_skin:
                n["skin"] = self.node_skin[rec.index]
            out.append(n)
        return out

    def _colliders(self):
        out = []
        self.collider_index = {}
        for rec in self.nodes:
            obj = rec.obj
            if rec.kind != "OBJECT" or obj.adm.adm_type != "COLLIDER":
                continue
            p = obj.adm
            c = {"name": obj.name, "node": rec.index, "shape": p.collider_shape}
            if p.collider_shape == "BOX":
                s = p.collider_size
                c["size"] = [cv.f32(s[0]), cv.f32(s[2]), cv.f32(s[1])]
            elif p.collider_shape == "SPHERE":
                c["radius"] = cv.f32(p.collider_radius)
            elif p.collider_shape == "CAPSULE":
                c["radius"] = cv.f32(p.collider_radius)
                c["height"] = cv.f32(max(p.collider_height, 2 * p.collider_radius))
            else:
                if obj.type not in MESHLIKE:
                    self.warn(f"collider '{obj.name}': MESH shape needs mesh geometry, skipped")
                    continue
                mi = self.mesh_index_for(obj, collision=True)
                if mi is None:
                    continue
                c["mesh"] = mi
            if p.collider_trigger:
                c["trigger"] = True
            if p.physical_material:
                c["physicalMaterial"] = p.physical_material
            self.collider_index[obj.name] = len(out)
            out.append(c)
        return out

    def _metadata_node(self, item, label):
        obj = item.object
        if obj is None:
            raise ExportError(f"{label}: select an exported node")
        key = (obj.name, item.bone)
        if item.bone:
            if key not in self.bone_node:
                raise ExportError(f"{label}: bone '{item.bone}' is not exported on '{obj.name}'")
            return self.bone_node[key]
        if obj.name not in self.obj_node:
            raise ExportError(f"{label}: node '{obj.name}' is not exported")
        return self.obj_node[obj.name]

    def _physical_components(self):
        if self.root is None:
            return [], [], []
        props = self.root.adm
        physical = []
        for item in props.physical_materials:
            record = {"id": item.name, "friction": float(item.friction),
                      "restitution": float(item.restitution)}
            if item.profile != "UNSPECIFIED":
                record["profile"] = item.profile
                self.mat.extensions_used.add(K.PHYSICAL_SURFACES_EXT)
                self.mat.extensions_required.add(K.PHYSICAL_SURFACES_EXT)
            physical.append(record)
        components = []
        for item in props.model_components:
            record = {"id": item.name, "role": item.role,
                      "node": self._metadata_node(item, f"component '{item.name}'")}
            if item.socket:
                record["socket"] = item.socket
            components.append(record)
        hitboxes = []
        for item in props.hitboxes:
            if item.collider is None or item.collider.name not in self.collider_index:
                raise ExportError(f"hitbox '{item.name}': select an exported collider")
            record = {"id": item.name, "collider": self.collider_index[item.collider.name]}
            if item.object is not None or item.bone:
                record["boneNode"] = self._metadata_node(item, f"hitbox '{item.name}'")
            if item.role:
                record["role"] = item.role
            hitboxes.append(record)
        return physical, components, hitboxes

    def _lod_groups(self):
        out = []
        for rec in self.nodes:
            obj = rec.obj
            if rec.kind != "OBJECT" or obj.adm.adm_type != "LOD_GROUP":
                continue
            levels = [(lv.min_distance, lv.object.name) for lv in obj.adm.lod_levels
                      if lv.object is not None and lv.object.name in self.obj_node]
            levels.sort()
            if len(levels) < 2:
                self.warn(f"LOD group '{obj.name}': needs at least two exported levels, skipped")
                continue
            if levels[0][0] != 0.0:
                self.warn(f"LOD group '{obj.name}': first level distance forced to 0")
            res = []
            prev = None
            ok = True
            for i, (d, name) in enumerate(levels):
                d = 0.0 if i == 0 else cv.f32(d)
                if prev is not None and not d > prev:
                    self.warn(f"LOD group '{obj.name}': distances must be strictly increasing, skipped")
                    ok = False
                    break
                prev = d
                res.append({"node": self.obj_node[name], "minDistance": d})
            if ok:
                out.append({"name": obj.name, "levels": res})
        return out

    def _attachments_roles(self):
        atts, roles = [], []
        seen_att, seen_role = set(), set()
        for rec in self.nodes:
            if rec.kind == "OBJECT":
                p = rec.obj.adm
                aname = p.attachment_name.strip() or (rec.obj.name if p.adm_type == "ATTACHMENT" else "")
            else:
                p = rec.bone.adm
                aname = p.attachment_name.strip()
            if aname:
                if aname in seen_att:
                    self.warn(f"duplicate attachment name '{aname}' skipped on '{rec.name}'")
                else:
                    seen_att.add(aname)
                    atts.append({"name": aname, "node": rec.index})
            role = p.component_role.strip()
            if role:
                prof = p.component_profile.strip() or "custom.vehicle.v1"
                if (prof, role) in seen_role:
                    self.warn(f"duplicate component role '{role}' ({prof}) skipped on '{rec.name}'")
                else:
                    seen_role.add((prof, role))
                    roles.append({"role": role, "node": rec.index, "profile": prof})
        return atts, roles

    def _profiles(self):
        profiles = []
        rigid_requests = []
        for arm_name in sorted(self.arm_joints):
            arm = self.context.view_layer.objects.get(arm_name) or bpy.data.objects[arm_name]
            sk = arm.data.adm
            if not sk.export_profile:
                continue
            pid = sk.profile_id.strip()
            roles = {}
            corr = {}
            from .rig import normalized_correction
            for bone in arm.data.bones:
                r = bone.adm.role.strip()
                if not r:
                    continue
                if r in roles:
                    raise ExportError(f"armature '{arm.name}': role '{r}' assigned to more than one bone")
                roles[r] = self.bone_node[(arm.name, bone.name)]
                if pid == "humanoid.vrm1":
                    q = normalized_correction(arm, bone)
                    if bone.adm.use_reference_correction:
                        stored = Quaternion(bone.adm.reference_correction)
                        stored.normalize()
                        actual = tuple(stored)
                        expected = tuple(q)
                        error = min(max(abs(a - b) for a, b in zip(actual, expected)),
                                    max(abs(a + b) for a, b in zip(actual, expected)))
                        if error > 1e-4:
                            raise ExportError(f"armature '{arm.name}' bone '{bone.name}': reference correction "
                                              "does not match the normative inverse rest rotation")
                    corr[r] = cv.quat_to_adm(q)
                elif bone.adm.use_reference_correction:
                    q = Quaternion(bone.adm.reference_correction)
                    corr[r] = cv.quat_to_adm(q)
            if pid == "humanoid.vrm1":
                bad = [r for r in roles if r not in K.VRM1_PARENT]
                if bad:
                    raise ExportError(f"armature '{arm.name}': unknown VRM roles {', '.join(sorted(bad))}")
                missing = [r for r in K.VRM1_REQUIRED if r not in roles]
                if missing:
                    raise ExportError(f"armature '{arm.name}': missing required humanoid roles: {', '.join(missing)}")
            reg = SP.get(pid)
            if reg is not None and reg["status"] in (SP.NORMATIVE, SP.PROVISIONAL):
                from .rig import joint_table
                for issue in SK.analyze_rig(pid, joint_table(arm), [(b.name, b.adm.role.strip())
                                                                     for b in arm.data.bones if b.adm.role.strip()]):
                    where = f"armature '{arm.name}'" + (f" bone '{issue.bone}'" if issue.bone else "")
                    if rig_issue_blocks_semantic(pid, issue.code):
                        raise ExportError(f"{where}: {issue.message}")
                    if issue.severity != SK.INFO:
                        self.warn(f"{where}: {issue.code}: {issue.message}")
            elif reg is None:
                self.warn(f"armature '{arm.name}': skeleton profile '{pid}' is not in the profile registry; "
                          f"only EXACT (rigId) animation binding is portable")
            skin = self.profile_skin(arm)
            if "skeletonProfile" in self.skins[skin]:
                continue
            prof = {"id": pid, "skin": skin, "roles": dict(sorted(roles.items()))}
            if reg is not None and reg.get("referencePose"):
                prof["referencePose"] = reg["referencePose"]["name"]
            if sk.use_target_height:
                prof["targetHeight"] = cv.f32(sk.target_height)
            if corr:
                prof["referenceCorrection"] = dict(sorted(corr.items()))
            self.skins[skin]["skeletonProfile"] = len(profiles)
            profiles.append(prof)
            if sk.write_rig_id:
                rigid_requests.append((len(profiles) - 1, arm))
        return profiles, rigid_requests

    def _face_and_expressions(self):
        faces, exprs = [], []
        if self.root is None:
            return faces, exprs
        p = self.root.adm

        def target_ok(obj, target):
            if obj is None or obj.name not in self.obj_node:
                return False
            mi = self.node_mesh.get(self.obj_node[obj.name])
            return mi is not None and target in self.meshes[mi].get("targetNames", [])

        if p.face_enabled:
            binds = []
            seen = set()
            for b in p.face_bindings:
                if not target_ok(b.object, b.target):
                    self.warn(f"face binding {b.channel}: '{b.target}' on '{b.object.name if b.object else '?'}' "
                              f"not exported, skipped")
                    continue
                key = (b.channel, self.obj_node[b.object.name], b.target)
                if key in seen:
                    continue
                seen.add(key)
                e = {"channel": b.channel, "node": key[1], "target": b.target}
                if b.scale != 1.0:
                    e["scale"] = cv.f32(b.scale)
                binds.append(e)
            channels = {b["channel"] for b in binds}
            faces.append({"id": K.FACE_PROFILE_ID, "coverage": "complete" if len(channels) == 52 else "partial",
                          "bindings": binds})
        names = set()
        for ex in p.expressions:
            name = ex.name.strip()
            if not name or name in names:
                self.warn(f"expression '{ex.name}': empty or duplicate name, skipped")
                continue
            names.add(name)
            binds = []
            for b in ex.bindings:
                if not target_ok(b.object, b.target):
                    self.warn(f"expression '{name}': target '{b.target}' not exported, skipped")
                    continue
                binds.append({"node": self.obj_node[b.object.name], "target": b.target, "weight": cv.f32(b.weight)})
            e = {"name": name, "bindings": binds}
            if ex.priority:
                e["priority"] = ex.priority
            if ex.group != "face":
                e["group"] = ex.group
            exprs.append(e)
        return faces, exprs

    def _ik_chains(self):
        from .rig import constraint_issues
        out = []
        for arm_name in sorted(self.arm_joints):
            arm = bpy.data.objects[arm_name]
            for issue in constraint_issues(arm):
                self.warn(f"armature '{arm_name}': {issue.code}: {issue.message}")
            arm_world = self.nodes[self.obj_node[arm_name]].world
            for ch in arm.data.adm.ik_chains:
                keys = [(arm_name, ch.root), (arm_name, ch.mid), (arm_name, ch.end)]
                if not all(k in self.bone_node for k in keys):
                    self.warn(f"IK chain '{ch.chain_id}': bones not found, skipped")
                    continue
                pole = cv.C3 @ (arm_world.to_3x3() @ Vector(ch.pole))
                if pole.length < 1e-9:
                    self.warn(f"IK chain '{ch.chain_id}': zero pole vector, skipped")
                    continue
                pole.normalize()
                c = {"id": ch.chain_id, "solver": "TWO_BONE", "root": self.bone_node[keys[0]],
                     "mid": self.bone_node[keys[1]], "end": self.bone_node[keys[2]],
                     "pole": [cv.f32(pole.x), cv.f32(pole.y), cv.f32(pole.z)]}
                if ch.weight != 1.0:
                    c["weight"] = cv.f32(ch.weight)
                out.append(c)
        return out

    # ---------------------------------------------------------------------------------------------
    def export(self):
        try:
            return self._export()
        except (ShaderExportError, TextureExportError, AdmFormatError) as exc:
            raise ExportError(str(exc)) from exc

    def _export(self):
        if self.opts.vertex_controls:
            self.mat.extensions_used.add(K.VERTEX_CONTROL_EXT)
            self.mat.extensions_required.add(K.VERTEX_CONTROL_EXT)
        with RestPose(self.context):
            self.build_graph()
            self.build_content()
            colliders = self._colliders()
            profiles, rigid_requests = self._profiles()
            nodes = self._node_dicts()
        lods = self._lod_groups()
        attachments, comp_roles = self._attachments_roles()
        physical, components, hitboxes = self._physical_components()
        faces, exprs = self._face_and_expressions()
        iks = self._ik_chains()

        asset = {"generator": GENERATOR}
        if self.root is not None and self.root.adm.copyright.strip():
            asset["copyright"] = self.root.adm.copyright.strip()
        default_scene = min(self.root.adm.default_scene, len(self.scenes) - 1) if self.root is not None else 0
        doc = {"asset": asset}
        for key, val in (("scene", default_scene), ("scenes", self.scenes), ("nodes", nodes),
                         ("meshes", self.meshes)):
            doc[key] = val
        optional = (("materials", self.mat.materials), ("textures", self.mat.textures),
                    ("samplers", self.mat.samplers), ("images", self.mat.images), ("skins", self.skins),
                    ("skeletonProfiles", profiles), ("facialProfiles", faces), ("expressions", exprs),
                    ("ikChains", iks), ("componentRoles", comp_roles), ("colliders", colliders),
                    ("lodGroups", lods), ("attachments", attachments),
                    ("physicalMaterials", physical), ("modelComponents", components), ("hitboxes", hitboxes),
                    ("shaderDefinitions", [self.mat.used_definitions[k] for k in sorted(self.mat.used_definitions)]),
                    ("extensionsUsed", sorted(self.mat.extensions_used)),
                    ("extensionsRequired", sorted(self.mat.extensions_required)))
        for key, val in optional:
            if val:
                doc[key] = val
        doc["accessors"] = self.b.accessors
        doc["bufferViews"] = self.b.buffer_views
        bin_bytes = self.b.bytes()
        for pi, arm in rigid_requests:
            prof = profiles[pi]
            rid = rig_id_from_document(doc, bin_bytes, prof["skin"], prof["roles"])
            prof["rigId"] = rid
            arm.data.adm.rig_id = rid
        data = write_container(K.ADM_MAGIC, doc, bin_bytes)
        report = validate_adm(data) if self.opts.validate else None
        if report is not None and not report.ok:
            raise ExportError("exported model failed ADM validation", report)
        self.doc = doc
        return data, report

    # ---------------------------------------------------------------------------------------------
    def rig_info(self, arm):
        """Graph-only pass for an armature: (rigId or None, {bone_name: node_name}, profile_roles)."""
        with RestPose(self.context):
            self.build_graph()
        if arm.name not in self.arm_joints:
            raise ExportError(f"armature '{arm.name}' is not part of the exported model")
        skin = self.profile_skin(arm)
        roles = {}
        for bone in arm.data.bones:
            r = bone.adm.role.strip()
            if r:
                roles[r] = self.bone_node[(arm.name, bone.name)]
        doc = {"nodes": [dict(cv.node_transform_fields(r.local, force_trs=r.kind == "BONE")) for r in self.nodes],
               "skins": self.skins, "accessors": self.b.accessors, "bufferViews": self.b.buffer_views}
        rid = rig_id_from_document(doc, self.b.bytes(), skin, dict(sorted(roles.items())))
        return rid


def export_model(context, filepath, root=None, options=None):
    exp = ModelExporter(context, root, options)
    exp.mat.external_root = os.path.dirname(os.path.abspath(filepath))
    data, report = exp.export()
    if exp.mat.external_files:
        from ..core.external_images import resolve_image_uri
        root_dir = exp.mat.external_root
        try:
            for uri, blob in exp.mat.external_files.items():
                target = resolve_image_uri(root_dir, uri)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(target, "xb") as fh:
                        fh.write(blob)
                except FileExistsError:
                    if target.read_bytes() != blob:
                        raise ExportError(f"external texture target already exists with different content: {uri}")
        except (OSError, ValueError) as exc:
            if isinstance(exc, ExportError):
                raise
            raise ExportError(f"could not write external textures: {exc}") from exc
    with open(filepath, "wb") as fh:
        fh.write(data)
    return exp, report


def rest_fingerprint(arm):
    """Tolerant digest of an armature's rest pose (names, parents, rest matrices rounded to 1e-4)."""
    h = hashlib.sha256()
    for b in sorted(arm.data.bones, key=lambda b: b.name):
        h.update(b.name.encode("utf-8") + b"\0" + (b.parent.name if b.parent else "").encode("utf-8") + b"\0")
        h.update(repr([round(v, 4) + 0.0 for row in b.matrix_local for v in row]).encode("ascii"))
        h.update(b.adm.role.strip().encode("utf-8") + b"\0")
    return h.hexdigest()


def rig_id_matches(context, arm, rig_id):
    """True when ``rig_id`` is this rig's computed rigId, or the imported one and the rest pose is untouched."""
    sk = arm.data.adm
    if sk.imported_rig_id == rig_id and sk.imported_rest and sk.imported_rest == rest_fingerprint(arm):
        return True
    return compute_rig_id(context, arm) == rig_id


def compute_rig_id(context, arm):
    root = find_model_root(arm)
    exp = ModelExporter(context, root, ExportOptions())
    return exp.rig_info(arm)
