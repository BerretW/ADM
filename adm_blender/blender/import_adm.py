"""ADM model (.adm) -> Blender importer."""

import os
import re
import shutil
import tempfile
from collections import defaultdict

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from ..core import constants as K
from ..core.buffers import read_accessor_np, read_view
from ..core.external_images import resolve_image_uri
from ..core.validate import validate_adm
from . import convert as cv
from .colliders import new_collider_object
from .export_adm import rest_fingerprint
from .materials import UV_NAMES, apply_shader, build_material, has_profile_preview, import_shader_definitions
from .props import SKELETON_PROFILES


class ImportError_(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class ImportOptions:
    def __init__(self, **kw):
        self.import_normals = True
        self.weld = True
        self.collection = True
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown import option {k!r}")
            setattr(self, k, v)


def _safe(name, fallback):
    name = (name or "").strip()
    return name if name else fallback


class ModelImporter:
    def __init__(self, context, filepath, options=None):
        self.context = context
        self.filepath = filepath
        self.opts = options or ImportOptions()
        self.warnings = []

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def acc(self, index, dtype=np.float64):
        return read_accessor_np(self.doc, self.bin, index, dtype)

    # ---------------------------------------------------------------------------------------------
    def run(self):
        with open(self.filepath, "rb") as fh:
            data = fh.read()
        report = validate_adm(data)
        self.report = report
        if not report.ok:
            raise ImportError_("file is not a valid ADM 1.0 model", report)
        self.doc, self.bin = report.doc, report.bin
        d = self.doc
        self.interactive_by_node = defaultdict(dict)
        interactive = (d.get("extensions") or {}).get(K.INTERACTIVE_SURFACES_EXT, {})
        for surface in interactive.get("surfaces", []):
            for binding in surface["bindings"]:
                self.interactive_by_node[binding["node"]][binding["primitive"]] = (
                    surface["surfaceId"], binding["texCoord"], surface.get("aspectRatio", 0.0))
        self.nodes = d["nodes"]
        n = len(self.nodes)
        self.parent = [None] * n
        for i, node in enumerate(self.nodes):
            for c in node.get("children", []):
                self.parent[c] = i
        self.world_adm = [None] * n
        for sc in d["scenes"]:
            stack = [(r, Matrix.Identity(4)) for r in sc["nodes"]]
            while stack:
                i, pw = stack.pop()
                self.world_adm[i] = pw @ cv.trs_matrix_from_adm_node(self.nodes[i])
                for c in self.nodes[i].get("children", []):
                    stack.append((c, self.world_adm[i]))
        self.world = [cv.mat_from_adm(w) for w in self.world_adm]

        stem = os.path.splitext(os.path.basename(self.filepath))[0]
        self.collection = self.context.collection
        if self.opts.collection:
            self.collection = bpy.data.collections.new(stem)
            self.context.scene.collection.children.link(self.collection)
        self.root = bpy.data.objects.new(stem, None)
        self.root.empty_display_type = "PLAIN_AXES"
        self.root.empty_display_size = 0.25
        self.root.adm.adm_type = "MODEL"
        self.root.adm.copyright = d["asset"].get("copyright", "")
        self.root.adm.default_scene = d.get("scene", 0)
        self.collection.objects.link(self.root)

        self._tmpdir = tempfile.mkdtemp(prefix="adm_import_")
        try:
            self.load_images()
        finally:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        resolve_image = lambda ref: self.resolve_texture(ref)[0]  # noqa: E731
        import_shader_definitions(self.context.scene, d, resolve_image)
        self.materials = []
        for m in d.get("materials", []):
            mat = build_material(m, self.resolve_texture)
            missing_image_uris = []
            if "adm_incomplete_textures" in mat:
                for image_index in mat["adm_incomplete_textures"]:
                    try:
                        image = d["images"][int(image_index)]
                    except (IndexError, TypeError, ValueError):
                        continue
                    missing_image_uris.append(image.get("uri", f"image:{image_index}"))
            vertex_controls = (m.get("extensions") or {}).get(K.VERTEX_CONTROL_EXT)
            if K.VERTEX_CONTROL_EXT in d.get("extensionsRequired", []):
                mat.adm.vertex_controls_enabled = True
            if isinstance(vertex_controls, dict):
                mat.adm.vertex_controls_enabled = True
                params = vertex_controls.get("parameters", {})
                mat.adm.tint_offset = params.get("tintOffset", 0.0)
                mat.adm.normal_multiplier = params.get("normalMultiplier", 1.0)
                mat.adm.reflection_multiplier = params.get("reflectionMultiplier", 1.0)
                mat.adm.wetness_offset = params.get("wetnessOffset", 0.0)
                mat.adm.vertex_tint_mode = vertex_controls.get("tintMode", "MULTIPLY")
                if "tintPalette" in vertex_controls:
                    image, _sampler = self.resolve_texture(vertex_controls["tintPalette"])
                    mat.adm.vertex_tint_palette = image
                    if image is None:
                        index = vertex_controls["tintPalette"]["index"]
                        uri = d["images"][d["textures"][index]["source"]].get("uri", f"image:{index}")
                        missing_image_uris.append(uri)
            if missing_image_uris:
                mat["adm_incomplete_textures"] = sorted(set(missing_image_uris))
            apply_shader(mat, m, self.context.scene, resolve_image)
            if not has_profile_preview(mat.adm.shader):
                self.warn(f"SHADER_FALLBACK: material '{mat.name}' uses portable PBR shading; "
                          f"{mat.adm.shader_key()[0]}@{mat.adm.shader_key()[1]} is preserved for export")
            self.materials.append(mat)
        self.plan_armatures()
        self.create_objects()
        from .materials import refresh_shader_preview
        for mat in self.materials:
            if mat.adm.vertex_controls_enabled:
                refresh_shader_preview(mat)
        self.metadata()
        return self.root

    # ---------------------------------------------------------------------------------------------
    def load_images(self):
        self.images = []
        asset_root = os.path.dirname(os.path.abspath(self.filepath))
        for i, im in enumerate(self.doc.get("images", [])):
            if im["mimeType"] in K.GPU_IMAGE_MIMES:
                self.images.append(None)
                continue
            ext = ".png" if im["mimeType"] == "image/png" else ".jpg"
            name = _safe(im.get("name"), f"Image_{i}")
            fname = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            if not fname.lower().endswith(ext):
                fname += ext
            if "uri" in im:
                try:
                    path = resolve_image_uri(asset_root, im["uri"], must_exist=True)
                    if "sha256" in im:
                        from ..core.external_images import sha256_hex
                        if sha256_hex(path.read_bytes()) != im["sha256"]:
                            self.warn(f"image {i} '{im['uri']}' SHA-256 mismatch; image not loaded")
                            self.images.append(None)
                            continue
                except (OSError, ValueError) as exc:
                    self.warn(f"image {i} '{im['uri']}' could not be resolved: {exc}")
                    self.images.append(None)
                    continue
            else:
                blob = read_view(self.doc, self.bin, im["bufferView"])
                path = os.path.join(self._tmpdir, f"{i}_{fname}")
                with open(path, "wb") as fh:
                    fh.write(blob)
            try:
                img = bpy.data.images.load(os.fspath(path), check_existing=True)
                if "uri" not in im:
                    img.pack()
                else:
                    img["adm_external_uri"] = im["uri"]
                    img["adm_external_sha256"] = im.get("sha256", "")
                img.name = name
                if "uri" not in im:
                    img.filepath_raw = "//" + fname
            except RuntimeError as exc:
                self.warn(f"image {i} '{name}' could not be decoded: {exc}")
                img = None
            self.images.append(img)

    def resolve_texture(self, ref):
        tex = self.doc["textures"][ref["index"]]
        source = tex["source"]
        mime = self.doc["images"][source]["mimeType"]
        if mime in K.GPU_IMAGE_MIMES:
            source = tex["fallbackSource"]
            code = "KTX2_FALLBACK" if mime == "image/ktx2" else "DDS_FALLBACK"
            self.warn(f"{code}: texture {ref['index']} uses the embedded PNG/JPEG fallback "
                      f"(the {mime} primary is kept only for GPU runtimes)")
        img = self.images[source]
        if img is None and "fallbackSource" in tex and source == tex["source"]:
            fallback = tex["fallbackSource"]
            if self.images[fallback] is not None:
                img = self.images[fallback]
                self.warn(f"EXTERNAL_IMAGE_FALLBACK: texture {ref['index']} uses fallback image {fallback}")
        if img is None:
            uri = self.doc["images"][source].get("uri")
            self.warn(f"EXTERNAL_IMAGE_MISSING: texture {ref['index']} image is unavailable"
                      + (f" ({uri})" if uri else ""))
        smp = self.doc["samplers"][tex["sampler"]] if "sampler" in tex else None
        return img, smp

    # ---------------------------------------------------------------------------------------------
    # armature planning
    # ---------------------------------------------------------------------------------------------
    def _ancestors(self, i):
        out = []
        a = self.parent[i]
        while a is not None:
            out.append(a)
            a = self.parent[a]
        return out

    def plan_armatures(self):
        skins = self.doc.get("skins", [])
        joints = set(j for s in skins for j in s["joints"])
        bones = set(joints)
        for j in joints:
            path = []
            a = self.parent[j]
            while a is not None and a not in joints:
                path.append(a)
                a = self.parent[a]
            if a is not None:
                bones.update(path)

        def bone_root(i):
            while self.parent[i] is not None and self.parent[i] in bones:
                i = self.parent[i]
            return i

        # union roots that share a skin
        uf = {}

        def find(x):
            while uf.get(x, x) != x:
                x = uf[x]
            return x

        roots = {bone_root(b) for b in bones}
        for r in roots:
            uf[r] = r
        for s in skins:
            rs = sorted({bone_root(j) for j in s["joints"]})
            for r in rs[1:]:
                uf[find(r)] = find(rs[0])
        groups = defaultdict(set)
        for r in roots:
            groups[find(r)].add(r)

        self.arm_groups = []  # dict(roots, parent_node, bones)
        for key in sorted(groups):
            rs = sorted(groups[key])
            parents = {self.parent[r] for r in rs}
            if len(parents) > 1:
                chains = [[r] + self._ancestors(r) for r in rs]
                common = set(chains[0][1:])
                for ch in chains[1:]:
                    common &= set(ch[1:])
                lca = next((a for a in chains[0][1:] if a in common), None)
                for ch in chains:
                    for a in ch[1:]:
                        if a == lca:
                            break
                        bones.add(a)
                rs = sorted({bone_root(r) for r in rs})
                parents = {self.parent[r] for r in rs}
            self.arm_groups.append({"roots": rs, "parent": next(iter(parents))})
        self.bones = bones
        self.node_arm = {}
        for gi, g in enumerate(self.arm_groups):
            stack = list(g["roots"])
            members = []
            while stack:
                i = stack.pop()
                members.append(i)
                self.node_arm[i] = gi
                stack.extend(c for c in self.nodes[i].get("children", []) if c in bones)
            g["members"] = sorted(members)
        colliders_by_node = defaultdict(list)
        self.collider_objects = {}
        for c in self.doc.get("colliders", []):
            colliders_by_node[c["node"]].append(c)
        self.colliders_by_node = colliders_by_node
        used_as_arm = set()
        for g in self.arm_groups:
            p = g["parent"]
            g["own_object"] = (p is not None and p not in bones and "mesh" not in self.nodes[p]
                               and p not in colliders_by_node and p not in used_as_arm)
            if g["own_object"]:
                used_as_arm.add(p)

    # ---------------------------------------------------------------------------------------------
    # objects
    # ---------------------------------------------------------------------------------------------
    def _link(self, obj):
        self.collection.objects.link(obj)
        return obj

    def _place(self, obj, parent_node, world_b):
        """Parent ``obj`` to the Blender representation of ``parent_node`` and set its world matrix."""
        if parent_node is None:
            obj.parent = self.scene_parent_obj
            pw = self.scene_parent_obj.matrix_world.copy() if self.scene_parent_obj else Matrix.Identity(4)
            obj.matrix_basis = pw.inverted_safe() @ world_b
            return
        if parent_node in self.bone_of:
            arm_obj, bname = self.bone_of[parent_node]
            bone = arm_obj.data.bones[bname]
            obj.parent = arm_obj
            obj.parent_type = "BONE"
            obj.parent_bone = bname
            pw = self.arm_world[arm_obj.name] @ bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = pw.inverted_safe() @ world_b
            return
        pobj = self.node_obj[parent_node]
        obj.parent = pobj
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = self.obj_world[pobj.name].inverted_safe() @ world_b

    def create_objects(self):
        d = self.doc
        self.node_obj = {}
        self.obj_world = {}
        self.bone_of = {}
        self.arm_world = {}
        self.arm_objs = []
        self.mesh_data = {}
        scenes = d["scenes"]
        self.scene_objs = []
        for si, sc in enumerate(scenes):
            if len(scenes) > 1:
                e = self._link(bpy.data.objects.new(_safe(sc.get("name"), f"Scene_{si}"), None))
                e.adm.adm_type = "SCENE"
                e.empty_display_size = 0.2
                e.parent = self.root
                self.scene_objs.append(e)
            else:
                self.scene_objs.append(self.root)
        self.obj_world[self.root.name] = Matrix.Identity(4)
        for e in self.scene_objs:
            self.obj_world[e.name] = Matrix.Identity(4)

        node_scene = {}
        for si, sc in enumerate(scenes):
            stack = list(sc["nodes"])
            while stack:
                i = stack.pop()
                node_scene[i] = si
                stack.extend(self.nodes[i].get("children", []))
        self.node_scene = node_scene

        # traverse in parent-first order
        order = []
        for sc in scenes:
            stack = list(reversed(sc["nodes"]))
            while stack:
                i = stack.pop()
                order.append(i)
                stack.extend(reversed(self.nodes[i].get("children", [])))
        built_groups = set()
        for i in order:
            self.scene_parent_obj = self.scene_objs[node_scene[i]]
            if i in self.bones:
                gi = self.node_arm[i]
                if gi not in built_groups:
                    built_groups.add(gi)
                    self.build_armature(gi)
                node = self.nodes[i]
                if "mesh" in node:
                    holder = self._link(bpy.data.objects.new(_safe(node.get("name"), f"node_{i}") + "_mesh",
                                                             self._mesh_obj_data(i)))
                    self._place(holder, i, self.world[i])
                    self._finish_mesh_object(holder, i)
                if i in self.colliders_by_node:
                    self._extra_colliders(i, None, as_child_of=i)
                continue
            if any(g["own_object"] and g["parent"] == i for g in self.arm_groups):
                gi = next(k for k, g in enumerate(self.arm_groups) if g["own_object"] and g["parent"] == i)
                obj = self.build_armature(gi, as_node=i)
                built_groups.add(gi)
                self._extra_colliders(i, obj)
                continue
            self._create_node_object(i)

        for gi in range(len(self.arm_groups)):
            if gi not in built_groups:
                self.build_armature(gi)

    def _mesh_obj_data(self, i):
        node = self.nodes[i]
        if "mesh" not in node:
            return None
        bindings = self.interactive_by_node.get(i, {})
        signature = tuple((primitive, *value) for primitive, value in sorted(bindings.items()))
        key = (node["mesh"], node.get("skin"), signature)
        if key not in self.mesh_data:
            self.mesh_data[key] = self.build_mesh(node["mesh"], node.get("skin"), interactive_bindings=bindings)
        return self.mesh_data[key]

    def _create_node_object(self, i):
        node = self.nodes[i]
        name = _safe(node.get("name"), f"node_{i}")
        cols = self.colliders_by_node.get(i, [])
        if "mesh" not in node and len(cols) == 1:
            obj = self._collider_object(cols[0], name)
            self._place(obj, self.parent[i], self.world[i])
            self.node_obj[i] = obj
            self.obj_world[obj.name] = self.world[i]
            return obj
        data = self._mesh_obj_data(i)
        obj = self._link(bpy.data.objects.new(name, data))
        if data is None:
            obj.empty_display_type = "PLAIN_AXES"
            obj.empty_display_size = 0.1
        self._place(obj, self.parent[i], self.world[i])
        self.node_obj[i] = obj
        self.obj_world[obj.name] = self.world[i]
        if data is not None:
            self._finish_mesh_object(obj, i)
        self._extra_colliders(i, obj)
        return obj

    def _extra_colliders(self, i, owner, as_child_of=None):
        cols = self.colliders_by_node.get(i, [])
        if "mesh" not in self.nodes[i] and len(cols) == 1 and as_child_of is None:
            return
        for c in cols:
            co = self._collider_object(c, _safe(c.get("name"), "Collider"))
            if as_child_of is not None:
                self._place(co, as_child_of, self.world[i])
            else:
                co.parent = owner
                co.matrix_parent_inverse = Matrix.Identity(4)
                co.matrix_basis = Matrix.Identity(4)

    def _collider_object(self, c, name):
        shape = c["shape"]
        mesh = None
        if shape == "MESH":
            mesh = self.build_mesh(c["mesh"], None, collision=True)
        size = c.get("size", [1.0, 1.0, 1.0])
        obj = new_collider_object(self.context, shape, name, size=(size[0], size[2], size[1]),
                                  radius=c.get("radius", 0.5), height=c.get("height", 2.0), mesh=mesh)
        obj.adm.collider_trigger = c.get("trigger", False)
        obj.adm.physical_material = c.get("physicalMaterial", "")
        self.collider_objects[id(c)] = obj
        self._link(obj)
        return obj

    def _finish_mesh_object(self, obj, i):
        node = self.nodes[i]
        me = obj.data
        meshdef = self.doc["meshes"][node["mesh"]]
        info = self.mesh_extra[me.name]
        if info["targets"] and me.shape_keys is None:
            obj.shape_key_add(name="Basis", from_mix=False)
            base = info["co"]
            for k, name in enumerate(info["targets"]):
                kb = obj.shape_key_add(name=name, from_mix=False)
                kb.data.foreach_set("co", (base + info["deltas"][k]).astype(np.float32).ravel())
                kb.slider_min = 0.0
                kb.slider_max = 1.0
            weights = node.get("weights", meshdef.get("weights"))
            if weights:
                for name, w in zip(info["targets"], weights):
                    me.shape_keys.key_blocks[name].value = w
        if "skin" in node:
            skin = self.doc["skins"][node["skin"]]
            arm_obj = None
            names = []
            for j in skin["joints"]:
                a, b = self.bone_of[j]
                arm_obj = arm_obj or a
                names.append(b)
            groups = [obj.vertex_groups.get(nm) or obj.vertex_groups.new(name=nm) for nm in names]
            J, W = info["joints"], info["weights"]
            vidx, cols = np.nonzero(W > 0)
            jj = J[vidx, cols]
            key = vidx * len(groups) + jj
            ukey, kinv = np.unique(key, return_inverse=True)
            acc = np.zeros(len(ukey))
            np.add.at(acc, kinv.reshape(-1), W[vidx, cols])
            uv, uj = ukey // len(groups), ukey % len(groups)
            for jidx in np.unique(uj):
                sel = uj == jidx
                vg = groups[int(jidx)]
                vs, ws = uv[sel], np.round(acc[sel], 6)
                for w in np.unique(ws):
                    vg.add(vs[ws == w].tolist(), float(w), "REPLACE")
            mod = obj.modifiers.new("Armature", "ARMATURE")
            mod.object = arm_obj
            self._check_bind(i, node["skin"])

    def _check_bind(self, i, skin_index):
        skin = self.doc["skins"][skin_index]
        ibm = self.acc(skin["inverseBindMatrices"])
        wm = self.world_adm[i]
        worst = 0.0
        for k, j in enumerate(skin["joints"]):
            expect = self.world_adm[j].inverted_safe() @ wm
            got = cv.matrix_from_list(list(ibm[k]))
            worst = max(worst, max(abs(expect[r][c] - got[r][c]) for r in range(4) for c in range(4)))
        if worst > 1e-3:
            self.warn(f"skin {skin_index}: bind pose differs from node rest pose (max error {worst:.4g}); "
                      f"mesh '{self.nodes[i].get('name', i)}' may appear deformed at rest")

    # ---------------------------------------------------------------------------------------------
    def build_armature(self, gi, as_node=None):
        g = self.arm_groups[gi]
        p = g["parent"]
        if as_node is not None:
            name = _safe(self.nodes[as_node].get("name"), f"Armature_{gi}")
            world = self.world[as_node]
        else:
            name = f"Armature_{gi}" if p is None else _safe(self.nodes[p].get("name"), "node") + "_Armature"
            world = self.world[p] if p is not None else Matrix.Identity(4)
        arm = bpy.data.armatures.new(name)
        arm.display_type = "OCTAHEDRAL"
        obj = self._link(bpy.data.objects.new(name, arm))
        obj.show_in_front = True
        if as_node is not None:
            self._place(obj, self.parent[as_node], world)
            self.node_obj[as_node] = obj
        else:
            self._place(obj, p, world)
        self.obj_world[obj.name] = world
        self.arm_world[obj.name] = world
        self.arm_objs.append(obj)
        arm_inv = world.inverted_safe()

        view_layer = self.context.view_layer
        prev_active = view_layer.objects.active
        if self.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        ebs = {}
        mats = {}
        used = set()
        scale_warn = []
        for i in g["members"]:
            m = arm_inv @ self.world[i]
            loc, rot, sca = m.decompose()
            if abs(sca.x - 1) > 1e-4 or abs(sca.y - 1) > 1e-4 or abs(sca.z - 1) > 1e-4:
                scale_warn.append(self.nodes[i].get("name", str(i)))
            mats[i] = Matrix.LocRotScale(loc, rot, None)
            bname = _safe(self.nodes[i].get("name"), f"joint_{i}")
            base, k = bname, 1
            while bname in used:
                bname = f"{base}.{k:03d}"
                k += 1
            used.add(bname)
            eb = arm.edit_bones.new(bname)
            eb.head = (0.0, 0.0, 0.0)
            eb.tail = (0.0, 1.0, 0.0)
            ebs[i] = eb
        for i in g["members"]:
            eb = ebs[i]
            eb.length = self._bone_length(i, mats)
            eb.matrix = mats[i]
            par = self.parent[i]
            if par in ebs:
                eb.parent = ebs[par]
        names = {i: ebs[i].name for i in g["members"]}
        bpy.ops.object.mode_set(mode="OBJECT")
        view_layer.objects.active = prev_active
        for i, bname in names.items():
            self.bone_of[i] = (obj, bname)
        if scale_warn:
            self.warn(f"armature '{name}': rest scale on joints ignored ({', '.join(scale_warn[:5])}...)")
        g["object"] = obj
        return obj

    def _bone_length(self, i, mats):
        head = mats[i].to_translation()
        yaxis = mats[i].to_3x3().col[1].normalized()
        best = None
        kids = [c for c in self.nodes[i].get("children", []) if c in mats]
        for c in kids:
            v = mats[c].to_translation() - head
            proj = v.dot(yaxis)
            if proj > 1e-4 and (v - yaxis * proj).length < 0.2 * proj:
                best = proj if best is None else min(best, proj)
        if best is None and kids:
            dists = [(mats[c].to_translation() - head).length for c in kids]
            dists = [x for x in dists if x > 1e-4]
            if dists:
                best = sum(dists) / len(dists)
        if best is None:
            par = self.parent[i]
            if par in mats:
                best = max(0.02, (head - mats[par].to_translation()).length * 0.5)
            else:
                best = 0.1
        return max(best, 1e-3)

    # ---------------------------------------------------------------------------------------------
    def build_mesh(self, mesh_index, skin_index, collision=False, interactive_bindings=None):
        m = self.doc["meshes"][mesh_index]
        prims = m["primitives"]
        interactive_bindings = interactive_bindings or {}
        pos, tris, nrm, uv, col, col1, jnt, wgt, mats, face_physical = (
            [], [], [], [[], []], [], [], [], [], [], [])
        face_interactive, vertex_groups = [], []
        deltas = []
        vertex_control = K.VERTEX_CONTROL_EXT in self.doc.get("extensionsRequired", [])
        ntarg = len(m.get("targetNames", [])) if not collision else 0
        if not collision:
            ntarg = max(ntarg, len(prims[0].get("targets", [])))
        offset = 0
        has_n = all("NORMAL" in p["attributes"] for p in prims) and self.opts.import_normals and not collision
        if interactive_bindings:
            uv_sets = [any(f"TEXCOORD_{k}" in p["attributes"] for p in prims) for k in (0, 1)]
            if uv_sets[1] and not uv_sets[0]:
                uv_sets[0] = True
                self.warn(f"mesh '{m.get('name', mesh_index)}': Blender needs a placeholder UV 0 to retain UV 1")
        else:
            uv_sets = [all(f"TEXCOORD_{k}" in p["attributes"] for p in prims) for k in (0, 1)]
            if not uv_sets[0]:
                uv_sets[1] = False
        has_c = (vertex_control or (any("COLOR_0" in p["attributes"] for p in prims) if interactive_bindings
                                   else all("COLOR_0" in p["attributes"] for p in prims))) and not collision
        has_c1 = vertex_control and not collision
        has_s = all("JOINTS_0" in p["attributes"] for p in prims) and not collision and skin_index is not None
        if collision:
            uv_sets = [False, False]
        for pi, p in enumerate(prims):
            a = p["attributes"]
            P = self.acc(a["POSITION"])
            n = len(P)
            pos.append(cv.np_vec_from_adm(P))
            I = self.acc(p["indices"], np.int64).reshape(-1, 3) + offset
            tris.append(I)
            mats.append(np.full(len(I), p.get("material", -1), dtype=np.int64))
            face_interactive.extend([interactive_bindings.get(pi, ("", 0, 0.0))] * len(I))
            if interactive_bindings:
                vertex_groups.append(np.full(n, pi + 1, dtype=np.int64))
            physical_ext = (p.get("extensions") or {}).get(K.PHYSICAL_SURFACES_EXT, {})
            face_physical.extend(physical_ext.get("faceMaterials", [""] * len(I)))
            if has_n:
                nrm.append(cv.np_vec_from_adm(self.acc(a["NORMAL"])))
            for k in (0, 1):
                if uv_sets[k]:
                    name = f"TEXCOORD_{k}"
                    if name in a:
                        uv[k].append(cv.np_uv_from_adm(self.acc(a[name])))
                    else:
                        uv[k].append(np.zeros((n, 2)))
                        self.warn(f"mesh '{m.get('name', mesh_index)}': Blender filled unused {name} "
                                  f"on primitive {pi}")
            if has_c:
                if "COLOR_0" in a:
                    col.append(self.acc(a["COLOR_0"]))
                else:
                    default_color = (0.0, 1.0, 1.0, 0.0) if vertex_control else (1.0, 1.0, 1.0, 1.0)
                    col.append(np.tile(default_color, (n, 1)))
            if has_c1:
                col1.append(self.acc(a["COLOR_1"]) if "COLOR_1" in a else np.zeros((n, 4)))
            if has_s:
                jnt.append(self.acc(a["JOINTS_0"], np.int64))
                wgt.append(self.acc(a["WEIGHTS_0"]))
            pd = []
            for t in range(ntarg):
                tg = p.get("targets", [])[t] if t < len(p.get("targets", [])) else {}
                pd.append(cv.np_vec_from_adm(self.acc(tg["POSITION"])) if "POSITION" in tg else np.zeros((n, 3)))
            deltas.append(pd)
            offset += n
        P = np.vstack(pos)
        T = np.vstack(tris)
        MI = np.concatenate(mats)
        face_physical = np.asarray(face_physical, dtype=object)
        face_ids = np.asarray([entry[0] for entry in face_interactive], dtype=object)
        face_uv = np.asarray([entry[1] for entry in face_interactive], dtype=np.int32)
        face_ratio = np.asarray([entry[2] for entry in face_interactive], dtype=np.float64)
        D = [np.vstack([deltas[pi][t] for pi in range(len(prims))]) for t in range(ntarg)]
        Jv = np.vstack(jnt) if has_s else None
        Wv = np.vstack(wgt) if has_s else None
        if Wv is not None:
            s = Wv.sum(axis=1, keepdims=True)
            Wv = np.where(s > 0, Wv / np.where(s > 0, s, 1.0), Wv)
        corner = T.reshape(-1)

        # weld duplicated vertices so the Blender mesh stays connected across seams
        if self.opts.weld:
            parts = [np.round(P, 6)] + [np.round(x, 6) for x in D]
            if interactive_bindings:
                parts.append(np.concatenate(vertex_groups).reshape(-1, 1))
            if Jv is not None:
                parts += [Jv.astype(np.float64), np.round(Wv, 5)]
            _, first, inv = np.unique(np.hstack(parts), axis=0, return_index=True, return_inverse=True)
            inv = inv.reshape(-1)
            order = np.argsort(first)
            remap = np.empty_like(order)
            remap[order] = np.arange(len(order))
            vid = remap[inv]
            keep = first[order]
        else:
            vid = np.arange(len(P))
            keep = vid
        TV = vid[T]
        good = (TV[:, 0] != TV[:, 1]) & (TV[:, 1] != TV[:, 2]) & (TV[:, 0] != TV[:, 2])
        st = np.sort(TV, axis=1)
        _, ufirst = np.unique(st, axis=0, return_index=True)
        uniq = np.zeros(len(TV), dtype=bool)
        uniq[ufirst] = True
        good &= uniq
        dropped = int(len(TV) - good.sum())
        if dropped and interactive_bindings and bool(np.any((~good) & (face_ids != ""))):
            raise ImportError_(f"mesh '{m.get('name', mesh_index)}': Blender cannot preserve a degenerate or "
                               "duplicate interactive triangle")
        if dropped:
            self.warn(f"mesh '{m.get('name', mesh_index)}': {dropped} degenerate/duplicate triangles not imported")
        TV = TV[good]
        corner = T[good].reshape(-1)
        MI = MI[good]
        face_physical = face_physical[good]
        face_ids, face_uv, face_ratio = face_ids[good], face_uv[good], face_ratio[good]

        name = _safe(m.get("name"), f"Mesh_{mesh_index}")
        me = bpy.data.meshes.new(name)
        co = P[keep]
        me.vertices.add(len(co))
        me.vertices.foreach_set("co", co.astype(np.float32).ravel())
        nt = len(TV)
        me.loops.add(nt * 3)
        me.loops.foreach_set("vertex_index", TV.astype(np.int32).ravel())
        me.polygons.add(nt)
        me.polygons.foreach_set("loop_start", np.arange(0, nt * 3, 3, dtype=np.int32))
        me.update(calc_edges=True)
        if collision and len(face_physical) and any(face_physical):
            attr = me.attributes.new("adm_physical_material_id", "STRING", "FACE")
            for poly, ident in zip(attr.data, face_physical):
                poly.value = ident.encode("utf-8")
        if interactive_bindings:
            ids = me.attributes.new("adm_interactive_surface_id", "STRING", "FACE")
            texcoords = me.attributes.new("adm_interactive_texcoord", "INT", "FACE")
            ratios = me.attributes.new("adm_interactive_aspect_ratio", "FLOAT", "FACE")
            for poly, ident, texcoord, ratio in zip(range(nt), face_ids, face_uv, face_ratio):
                ids.data[poly].value = ident.encode("ascii")
                texcoords.data[poly].value = int(texcoord)
                ratios.data[poly].value = float(ratio)

        # materials
        used = sorted(set(MI.tolist()))
        slot_of = {}
        if not collision:
            for mi in used:
                slot_of[mi] = len(me.materials)
                me.materials.append(self.materials[mi] if mi >= 0 else None)
            if len(used) > 1:
                me.polygons.foreach_set("material_index", np.array([slot_of[x] for x in MI], dtype=np.int32))
        for k in (0, 1):
            if uv_sets[k]:
                layer = me.uv_layers.new(name=UV_NAMES[k])
                layer.uv.foreach_set("vector", np.vstack(uv[k])[corner].astype(np.float32).ravel())
        if has_c:
            ca = me.color_attributes.new("COLOR_0" if vertex_control else "Color", "FLOAT_COLOR", "CORNER")
            ca.data.foreach_set("color", np.vstack(col)[corner].astype(np.float32).ravel())
            me.color_attributes.active_color = ca
        if has_c1:
            ca1 = me.color_attributes.new("COLOR_1", "FLOAT_COLOR", "CORNER")
            ca1.data.foreach_set("color", np.vstack(col1)[corner].astype(np.float32).ravel())
        invalid = me.validate(verbose=False, clean_customdata=False)
        if invalid:
            if interactive_bindings and len(me.polygons) != nt:
                raise ImportError_(f"mesh '{name}': Blender changed interactive face topology during import")
            self.warn(f"mesh '{name}': geometry was corrected by Blender's mesh validation")
        if has_n:
            me.shade_smooth()
            if len(me.loops) == len(corner):
                N = np.vstack(nrm)[corner]
                me.normals_split_custom_set([tuple(v) for v in N])
        self.mesh_extra = getattr(self, "mesh_extra", {})
        self.mesh_extra[me.name] = {
            "co": co,
            "targets": list(m.get("targetNames", [f"target_{t}" for t in range(ntarg)])) if ntarg else [],
            "deltas": [x[keep] for x in D],
            "joints": Jv[keep] if Jv is not None else None,
            "weights": Wv[keep] if Wv is not None else None,
        }
        return me

    # ---------------------------------------------------------------------------------------------
    def metadata(self):
        d = self.doc
        # LOD groups
        for gi, g in enumerate(d.get("lodGroups", [])):
            objs = [self.node_obj.get(lv["node"]) for lv in g["levels"]]
            if any(o is None for o in objs):
                self.warn(f"LOD group {gi}: level on a bone node is not supported in Blender, skipped")
                continue
            parents = {o.parent for o in objs}
            holder = None
            if len(parents) == 1:
                p = next(iter(parents))
                if p is not None and p.type == "EMPTY" and p.adm.adm_type == "NONE" and p is not self.root:
                    holder = p
            if holder is None:
                holder = self._link(bpy.data.objects.new(_safe(g.get("name"), f"LOD_{gi}"), None))
                holder.parent = self.root
            holder.adm.adm_type = "LOD_GROUP"
            if g.get("name"):
                holder.name = g["name"]
            holder.adm.lod_levels.clear()
            for lv, o in zip(g["levels"], objs):
                item = holder.adm.lod_levels.add()
                item.object = o
                item.min_distance = lv["minDistance"]
        # attachments and component roles
        for a in d.get("attachments", []):
            i = a["node"]
            if i in self.bone_of:
                arm_obj, b = self.bone_of[i]
                arm_obj.data.bones[b].adm.attachment_name = a["name"]
                continue
            obj = self.node_obj.get(i)
            if obj is None:
                continue
            if obj.type == "EMPTY" and obj.adm.adm_type == "NONE":
                obj.adm.adm_type = "ATTACHMENT"
                obj.empty_display_type = "ARROWS"
                if obj.name != a["name"]:
                    obj.adm.attachment_name = a["name"]
            else:
                obj.adm.attachment_name = a["name"]
        for r in d.get("componentRoles", []):
            i = r["node"]
            target = None
            if i in self.bone_of:
                arm_obj, b = self.bone_of[i]
                target = arm_obj.data.bones[b].adm
            elif i in self.node_obj:
                target = self.node_obj[i].adm
            if target is not None:
                target.component_role = r["role"]
                target.component_profile = r["profile"]
        # skeleton profiles
        for prof in d.get("skeletonProfiles", []):
            skin = d["skins"][prof["skin"]]
            arm_obj = self.bone_of[skin["joints"][0]][0]
            sk = arm_obj.data.adm
            sk.export_profile = True
            if prof["id"] in {item[0] for item in SKELETON_PROFILES} - {"CUSTOM"}:
                sk.profile = prof["id"]
            else:
                sk.profile = "CUSTOM"
                sk.custom_profile = prof["id"]
            if "targetHeight" in prof:
                sk.use_target_height = True
                sk.target_height = prof["targetHeight"]
            sk.write_rig_id = "rigId" in prof
            sk.rig_id = prof.get("rigId", "")
            sk.imported_rig_id = prof.get("rigId", "")
            for role, i in prof["roles"].items():
                if i in self.bone_of:
                    a, b = self.bone_of[i]
                    a.data.bones[b].adm.role = role
            sk.imported_rest = rest_fingerprint(arm_obj) if "rigId" in prof else ""
            for role, q in prof.get("referenceCorrection", {}).items():
                i = prof["roles"].get(role)
                if i in self.bone_of:
                    a, b = self.bone_of[i]
                    bp = a.data.bones[b].adm
                    bp.use_reference_correction = True
                    bp.reference_correction = cv.quat_from_adm(q)
        # face + expressions (stored on the model root)
        for fp in d.get("facialProfiles", []):
            if fp["id"] != K.FACE_PROFILE_ID:
                self.warn(f"facial profile {fp['id']!r} not supported, skipped")
                continue
            self.root.adm.face_enabled = True
            for b in fp["bindings"]:
                obj = self.node_obj.get(b["node"])
                if obj is None:
                    continue
                item = self.root.adm.face_bindings.add()
                item.channel = b["channel"]
                item.object = obj
                item.target = b["target"]
                item.scale = b.get("scale", 1.0)
        for ex in d.get("expressions", []):
            e = self.root.adm.expressions.add()
            e.name = ex["name"]
            e.priority = ex.get("priority", 0)
            e.group = ex.get("group", "face")
            for b in ex["bindings"]:
                item = e.bindings.add()
                item.object = self.node_obj.get(b["node"])
                item.target = b["target"]
                item.weight = b["weight"]
        # IK
        for ch in d.get("ikChains", []):
            if ch["root"] not in self.bone_of:
                continue
            arm_obj = self.bone_of[ch["root"]][0]
            c = arm_obj.data.adm.ik_chains.add()
            c.chain_id = ch["id"]
            c.root = self.bone_of[ch["root"]][1]
            c.mid = self.bone_of[ch["mid"]][1]
            c.end = self.bone_of[ch["end"]][1]
            pole = self.arm_world[arm_obj.name].to_3x3().inverted_safe() @ (cv.C3_INV @ Vector(ch["pole"]))
            c.pole = pole.normalized() if pole.length > 1e-9 else Vector((0.0, -1.0, 0.0))
            c.weight = ch.get("weight", 1.0)
        for material in d.get("physicalMaterials", []):
            item = self.root.adm.physical_materials.add()
            item.name = material["id"]
            item.profile = material.get("profile", "UNSPECIFIED")
            item.friction = material["friction"]
            item.restitution = material["restitution"]
        for component in d.get("modelComponents", []):
            item = self.root.adm.model_components.add()
            item.name, item.role = component["id"], component["role"]
            item.socket = component.get("socket", "")
            self._metadata_target(item, component["node"])
        for hitbox in d.get("hitboxes", []):
            item = self.root.adm.hitboxes.add()
            item.name, item.role = hitbox["id"], hitbox.get("role", "")
            collider = d["colliders"][hitbox["collider"]]
            item.collider = self.collider_objects[id(collider)]
            if "boneNode" in hitbox:
                self._metadata_target(item, hitbox["boneNode"])

    def _metadata_target(self, item, node):
        if node in self.bone_of:
            item.object, item.bone = self.bone_of[node]
        else:
            item.object = self.node_obj[node]


def import_model(context, filepath, options=None):
    imp = ModelImporter(context, filepath, options)
    root = imp.run()
    return imp, root
