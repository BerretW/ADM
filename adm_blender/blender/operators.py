"""ADM tool operators (Sollumz-style create / convert / setup tools)."""

import re

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from ..core import constants as K
from ..core.validate import PARAM_NAME_RE, validate_file
from . import props as P
from .colliders import new_collider_object, refresh_collider_mesh, style_collider_object
from .export_adm import ExportError, ExportOptions, ModelExporter, compute_rig_id, find_model_root
from .materials import convert_to_adm_material


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def show_report(context, title, report=None, extra_errors=(), warnings=()):
    """Fill the validation list shown in the ADM sidebar."""
    wm = context.window_manager.adm
    wm.report.clear()
    wm.report_title = title
    for msg in extra_errors:
        it = wm.report.add()
        it.severity, it.code, it.path, it.message = "ERROR", "EXPORT", "", str(msg)
    if report is not None:
        for i in report.issues:
            it = wm.report.add()
            it.severity, it.code, it.path, it.message = i.severity.upper(), i.code, i.path, i.message
    for msg in warnings:
        it = wm.report.add()
        it.severity, it.code, it.path, it.message = "WARNING", "BLENDER", "", msg
    wm.active_report = 0


def link_to_active_collection(context, obj):
    coll = context.collection or context.scene.collection
    coll.objects.link(obj)
    return obj


def make_active(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def active_root(context):
    obj = context.active_object
    return find_model_root(obj) if obj is not None else None


def active_armature(context):
    obj = context.active_object
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    if obj.parent is not None and obj.parent.type == "ARMATURE":
        return obj.parent
    for m in getattr(obj, "modifiers", []):
        if m.type == "ARMATURE" and m.object is not None:
            return m.object
    return None


def ensure_role_names(_dummy=None):
    """Fill the role search list (WindowManager data; never called from draw())."""
    for wm in bpy.data.window_managers:
        names = list(K.VRM1_ROLES)
        if [r.name for r in wm.adm.role_names] != names:
            wm.adm.role_names.clear()
            for r in names:
                wm.adm.role_names.add().name = r
    return None


def selection_bounds(objs):
    pts = []
    for o in objs:
        if o.type in {"MESH", "CURVE", "SURFACE", "FONT", "META"}:
            pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
        else:
            pts.append(o.matrix_world.to_translation())
    if not pts:
        return None
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def parent_keep_transform(child, parent):
    mw = child.matrix_world.copy()
    child.parent = parent
    child.parent_type = "OBJECT"
    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_world = mw


# --------------------------------------------------------------------------------------------------
# create tools
# --------------------------------------------------------------------------------------------------
class ADM_OT_create_model_root(bpy.types.Operator):
    """Create an ADM Model Root and parent the selected top-level objects under it"""
    bl_idname = "adm.create_model_root"
    bl_label = "Create Model Root"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="ADM_Model")
    use_selection: BoolProperty(name="Parent Selection", default=True)

    def execute(self, context):
        sel = [o for o in context.selected_objects if find_model_root(o) is None]
        root = bpy.data.objects.new(self.name, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.5
        root.adm.adm_type = "MODEL"
        link_to_active_collection(context, root)
        if self.use_selection and sel:
            lo, hi = selection_bounds(sel)
            root.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
            context.view_layer.update()
            names = {o.name for o in sel}
            for o in sel:
                if o.parent is None or o.parent.name not in names:
                    parent_keep_transform(o, root)
        else:
            root.location = context.scene.cursor.location
        make_active(context, root)
        return {"FINISHED"}


class ADM_OT_create_scene(bpy.types.Operator):
    """Add an ADM Scene group under the active Model Root (for multi-scene models)"""
    bl_idname = "adm.create_scene"
    bl_label = "Create Scene"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_root(context) is not None

    def execute(self, context):
        root = active_root(context)
        sc = bpy.data.objects.new("ADM_Scene", None)
        sc.empty_display_type = "CUBE"
        sc.empty_display_size = 0.25
        sc.adm.adm_type = "SCENE"
        link_to_active_collection(context, sc)
        sc.parent = root
        make_active(context, sc)
        return {"FINISHED"}


class ADM_OT_create_collider(bpy.types.Operator):
    """Create a collider. With objects selected it is fitted to their bounds and parented to the active one"""
    bl_idname = "adm.create_collider"
    bl_label = "Create Collider"
    bl_options = {"REGISTER", "UNDO"}

    shape: EnumProperty(name="Shape", items=P.COLLIDER_SHAPES, default="BOX")
    fit: BoolProperty(name="Fit To Selection", default=True)
    trigger: BoolProperty(name="Trigger", default=False)

    def invoke(self, context, event):
        if not self.properties.is_property_set("shape"):
            self.shape = context.window_manager.adm.collider_shape
        return self.execute(context)

    def execute(self, context):
        sel = list(context.selected_objects)
        active = context.active_object
        if self.shape == "MESH":
            src = active if active is not None and active.type == "MESH" else None
            if src is None:
                self.report({"ERROR"}, "Select a mesh to create a MESH collider (use Convert To Collider)")
                return {"CANCELLED"}
            me = src.data.copy()
            me.materials.clear()
            obj = new_collider_object(context, "MESH", src.name + "_col", mesh=me)
            link_to_active_collection(context, obj)
            obj.parent = src
            obj.matrix_parent_inverse = Matrix.Identity(4)
        else:
            obj = new_collider_object(context, self.shape, "Collider")
            link_to_active_collection(context, obj)
            bounds = selection_bounds(sel) if (self.fit and sel) else None
            if bounds:
                lo, hi = bounds
                size = hi - lo
                centre = (lo + hi) / 2
                props = obj.adm
                if self.shape == "BOX":
                    props.collider_size = [max(1e-3, s) for s in size]
                elif self.shape == "SPHERE":
                    props.collider_radius = max(1e-3, max(size) / 2)
                else:
                    props.collider_radius = max(1e-3, max(size.x, size.y) / 2)
                    props.collider_height = max(size.z, 2 * props.collider_radius)
                refresh_collider_mesh(obj)
                parent = active if active is not None and active.adm.adm_type != "COLLIDER" else None
                obj.matrix_world = Matrix.Translation(centre)
                if parent is not None:
                    parent_keep_transform(obj, parent)
            else:
                obj.location = context.scene.cursor.location
                root = active_root(context)
                if root is not None:
                    parent_keep_transform(obj, root)
        obj.adm.collider_trigger = self.trigger
        make_active(context, obj)
        return {"FINISHED"}


class ADM_OT_convert_to_collider(bpy.types.Operator):
    """Turn the selected meshes into MESH colliders (collision only, not rendered)"""
    bl_idname = "adm.convert_to_collider"
    bl_label = "Convert To Mesh Collider"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.selected_objects)

    def execute(self, context):
        n = 0
        for o in context.selected_objects:
            if o.type != "MESH":
                continue
            o.adm.adm_type = "COLLIDER"
            o.adm["collider_shape"] = 3  # MESH, bypass update (keeps geometry)
            style_collider_object(o)
            n += 1
        self.report({"INFO"}, f"{n} collider(s)")
        return {"FINISHED"}


class ADM_OT_physical_material_assign_faces(bpy.types.Operator):
    """Assign the collider's stable physical-material ID to selected mesh faces"""
    bl_idname = "adm.physical_material_assign_faces"
    bl_label = "Assign Surface To Selected Faces"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj is not None and obj.type == "MESH" and obj.mode == "OBJECT"
                and obj.adm.adm_type == "COLLIDER" and obj.adm.collider_shape == "MESH")

    def execute(self, context):
        obj = context.object
        ident = obj.adm.physical_material.strip()
        root = find_model_root(obj)
        if not ident or root is None or not any(item.name == ident for item in root.adm.physical_materials):
            self.report({"ERROR"}, "Set the collider's default to a registered physical material first")
            return {"CANCELLED"}
        selected = [poly.index for poly in obj.data.polygons if poly.select]
        if not selected:
            self.report({"ERROR"}, "Select one or more faces in Edit Mode, then return to Object Mode")
            return {"CANCELLED"}
        attr = obj.data.attributes.get("adm_physical_material_id")
        if attr is None:
            attr = obj.data.attributes.new("adm_physical_material_id", "STRING", "FACE")
        elif attr.domain != "FACE" or attr.data_type != "STRING":
            self.report({"ERROR"}, "adm_physical_material_id exists but is not a FACE string attribute")
            return {"CANCELLED"}
        for index in selected:
            attr.data[index].value = ident.encode("utf-8")
        self.report({"INFO"}, f"Assigned '{ident}' to {len(selected)} face(s)")
        return {"FINISHED"}


class ADM_OT_interactive_surface_assign_faces(bpy.types.Operator):
    """Assign or clear an interactive surface on selected mesh faces"""
    bl_idname = "adm.interactive_surface_assign_faces"
    bl_label = "Assign Interactive Surface"
    bl_options = {"REGISTER", "UNDO"}

    clear: BoolProperty(default=False, options={"HIDDEN"})
    load: BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj is not None and obj.type == "MESH" and obj.mode == "OBJECT"
                and obj.adm.adm_type != "COLLIDER")

    def execute(self, context):
        obj = context.object
        selected = [poly for poly in obj.data.polygons if poly.select]
        if not selected:
            self.report({"ERROR"}, "Select one or more faces in Edit Mode, then return to Object Mode")
            return {"CANCELLED"}
        fields = (("adm_interactive_surface_id", "STRING"),
                  ("adm_interactive_texcoord", "INT"),
                  ("adm_interactive_aspect_ratio", "FLOAT"))
        for name, kind in fields:
            attr = obj.data.attributes.get(name)
            if attr is not None and (attr.domain != "FACE" or attr.data_type != kind):
                self.report({"ERROR"}, f"{name} must be a FACE {kind} attribute")
                return {"CANCELLED"}
        if self.load:
            attrs = [obj.data.attributes.get(name) for name, _ in fields]
            if any(attr is None for attr in attrs):
                self.report({"ERROR"}, "Selected mesh has no complete interactive surface assignments")
                return {"CANCELLED"}
            try:
                values = {
                    (attrs[0].data[poly.index].value.decode("utf-8"),
                     attrs[1].data[poly.index].value, attrs[2].data[poly.index].value)
                    for poly in selected
                }
            except UnicodeDecodeError:
                self.report({"ERROR"}, "Selected surface ID contains invalid UTF-8")
                return {"CANCELLED"}
            if len(values) != 1:
                self.report({"ERROR"}, "Selected faces do not share one surface ID, UV set and aspect ratio")
                return {"CANCELLED"}
            ident, texcoord, ratio = values.pop()
            if not PARAM_NAME_RE.fullmatch(ident) or texcoord not in (0, 1) or not 0 <= ratio <= 1000:
                self.report({"ERROR"}, "Selected faces have an invalid interactive surface assignment")
                return {"CANCELLED"}
            obj.adm.interactive_surface_id = ident
            obj.adm.interactive_tex_coord = str(texcoord)
            obj.adm.interactive_aspect_ratio = ratio
            self.report({"INFO"}, f"Loaded surface '{ident}' from selected faces")
            return {"FINISHED"}
        ident = obj.adm.interactive_surface_id.strip()
        texcoord = int(obj.adm.interactive_tex_coord)
        if not self.clear:
            if not PARAM_NAME_RE.fullmatch(ident):
                self.report({"ERROR"}, "Surface ID must match [a-z][a-z0-9_]*, at most 64 characters")
                return {"CANCELLED"}
            if len(obj.data.uv_layers) <= texcoord:
                self.report({"ERROR"}, f"UV {texcoord} does not exist on this mesh")
                return {"CANCELLED"}
            for poly in selected:
                slots = obj.material_slots
                mat = slots[poly.material_index].material if poly.material_index < len(slots) else None
                if mat is None or mat.adm.shader_key() != K.SHADER_INTERACTIVE:
                    self.report({"ERROR"}, "Every selected face must use the Interactive Surface ADM material")
                    return {"CANCELLED"}
        if self.clear and obj.data.attributes.get(fields[0][0]) is None:
            self.report({"ERROR"}, "Selected mesh has no interactive surface assignments to clear")
            return {"CANCELLED"}
        attrs = [obj.data.attributes.get(name) or obj.data.attributes.new(name, kind, "FACE")
                 for name, kind in fields]
        for poly in selected:
            attrs[0].data[poly.index].value = b"" if self.clear else ident.encode("ascii")
            attrs[1].data[poly.index].value = 0 if self.clear else texcoord
            attrs[2].data[poly.index].value = 0.0 if self.clear else obj.adm.interactive_aspect_ratio
        if obj.data.users > 1:
            self.report({"WARNING"}, "Assignments affect every object sharing this mesh; make it single-user "
                                    "for independent IDs")
        else:
            self.report({"INFO"}, f"{'Cleared' if self.clear else 'Assigned'} {len(selected)} face(s)")
        return {"FINISHED"}


class ADM_OT_create_lod_group(bpy.types.Operator):
    """Group the selected objects into an ADM LOD group (ordered by name, LOD0 first)"""
    bl_idname = "adm.create_lod_group"
    bl_label = "Create LOD Group"
    bl_options = {"REGISTER", "UNDO"}

    step: FloatProperty(name="Distance Step", default=20.0, min=0.01, unit="LENGTH")

    def execute(self, context):
        sel = sorted((o for o in context.selected_objects if o.adm.adm_type != "LOD_GROUP"), key=lambda o: o.name)
        grp = bpy.data.objects.new("ADM_LOD", None)
        grp.empty_display_type = "SPHERE"
        grp.empty_display_size = 0.3
        grp.adm.adm_type = "LOD_GROUP"
        link_to_active_collection(context, grp)
        if sel:
            common = sel[0].parent if all(o.parent == sel[0].parent for o in sel) else active_root(context)
            grp.matrix_world = Matrix.Translation(sel[0].matrix_world.to_translation())
            if common is not None:
                parent_keep_transform(grp, common)
            context.view_layer.update()
            for i, o in enumerate(sel):
                parent_keep_transform(o, grp)
                lv = grp.adm.lod_levels.add()
                lv.object = o
                lv.min_distance = i * self.step
        else:
            grp.location = context.scene.cursor.location
        make_active(context, grp)
        return {"FINISHED"}


class ADM_OT_lod_level_add(bpy.types.Operator):
    """Add selected children (or an empty slot) as LOD levels"""
    bl_idname = "adm.lod_level_add"
    bl_label = "Add LOD Level"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.adm.adm_type == "LOD_GROUP"

    def execute(self, context):
        grp = context.active_object
        levels = grp.adm.lod_levels
        present = {lv.object for lv in levels}
        last = max((lv.min_distance for lv in levels), default=-20.0)
        added = 0
        for o in sorted(context.selected_objects, key=lambda o: o.name):
            if o == grp or o in present:
                continue
            if o.parent != grp:
                parent_keep_transform(o, grp)
            last += 20.0
            lv = levels.add()
            lv.object, lv.min_distance = o, max(0.0, last)
            added += 1
        if not added:
            lv = levels.add()
            lv.min_distance = max(0.0, last + 20.0)
        grp.adm.active_lod_level = len(levels) - 1
        return {"FINISHED"}


class ADM_OT_lod_level_remove(bpy.types.Operator):
    bl_idname = "adm.lod_level_remove"
    bl_label = "Remove LOD Level"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.adm.adm_type == "LOD_GROUP" and len(o.adm.lod_levels)

    def execute(self, context):
        p = context.active_object.adm
        p.lod_levels.remove(p.active_lod_level)
        p.active_lod_level = max(0, min(p.active_lod_level, len(p.lod_levels) - 1))
        return {"FINISHED"}


class ADM_OT_lod_preview(bpy.types.Operator):
    """Show only the LOD level selected for the preview distance (or show all)"""
    bl_idname = "adm.lod_preview"
    bl_label = "Preview LOD"
    bl_options = {"REGISTER", "UNDO"}

    show_all: BoolProperty(name="Show All", default=False)
    level: IntProperty(name="Level", default=-1)

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.adm.adm_type == "LOD_GROUP"

    def execute(self, context):
        p = context.active_object.adm
        levels = sorted((lv for lv in p.lod_levels if lv.object), key=lambda lv: lv.min_distance)
        if not levels:
            return {"CANCELLED"}
        pick = None
        if not self.show_all:
            if self.level >= 0:
                pick = levels[min(self.level, len(levels) - 1)]
            else:
                for lv in levels:
                    if p.lod_preview_distance >= lv.min_distance:
                        pick = lv
        for lv in levels:
            hide = pick is not None and lv is not pick

            def rec(o):
                o.hide_set(hide)
                for c in o.children:
                    rec(c)
            rec(lv.object)
        return {"FINISHED"}


class ADM_OT_create_attachment(bpy.types.Operator):
    """Create a named attachment frame at the 3D cursor (bone-parented in Pose Mode)"""
    bl_idname = "adm.create_attachment"
    bl_label = "Create Attachment"
    bl_options = {"REGISTER", "UNDO"}

    attachment_name: StringProperty(name="Name", default="prop.socket.right_hand")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        active = context.active_object
        bone = context.active_pose_bone if active is not None and active.mode == "POSE" else None
        mode = active.mode if active is not None else "OBJECT"
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        obj = bpy.data.objects.new("ATT_" + self.attachment_name, None)
        obj.empty_display_type = "ARROWS"
        obj.empty_display_size = 0.15
        obj.adm.adm_type = "ATTACHMENT"
        obj.adm.attachment_name = self.attachment_name
        link_to_active_collection(context, obj)
        obj.matrix_world = Matrix.Translation(context.scene.cursor.location)
        if bone is not None:
            mw = obj.matrix_world.copy()
            obj.parent = active
            obj.parent_type = "BONE"
            obj.parent_bone = bone.name
            context.view_layer.update()
            obj.matrix_world = mw
        elif active is not None:
            parent_keep_transform(obj, active)
        make_active(context, obj)
        return {"FINISHED"}


class ADM_OT_set_type(bpy.types.Operator):
    """Set the ADM type of the selected objects"""
    bl_idname = "adm.set_type"
    bl_label = "Set ADM Type"
    bl_options = {"REGISTER", "UNDO"}

    adm_type: EnumProperty(name="Type", items=P.ADM_TYPES)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        for o in context.selected_objects:
            if self.adm_type in {"MODEL", "SCENE", "LOD_GROUP", "ATTACHMENT"} and o.type not in {"EMPTY", "MESH"}:
                self.report({"WARNING"}, f"{o.name}: {self.adm_type} is normally an empty")
            o.adm.adm_type = self.adm_type
            if self.adm_type == "COLLIDER" and o.type == "MESH":
                o.adm["collider_shape"] = 3
                style_collider_object(o)
        return {"FINISHED"}


class ADM_OT_convert_materials(bpy.types.Operator):
    """Rebuild materials of the selected objects as ADM-compatible Principled BSDF node trees"""
    bl_idname = "adm.convert_materials"
    bl_label = "Convert Materials To ADM"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mats = {s.material for o in context.selected_objects for s in getattr(o, "material_slots", []) if s.material}
        if not mats and context.active_object is not None:
            mats = {s.material for s in context.active_object.material_slots if s.material}
        n = sum(1 for m in mats if convert_to_adm_material(m))
        self.report({"INFO"}, f"converted {n} of {len(mats)} material(s) (others were already ADM-ready)")
        return {"FINISHED"}


# --------------------------------------------------------------------------------------------------
# skeleton
# --------------------------------------------------------------------------------------------------
class ADM_OT_auto_map_roles(bpy.types.Operator):
    """Suggest roles of the selected skeleton profile from bone names/hierarchy (humanoid: Mixamo, Rigify, UE,
    VRoid, CC; quadrupeds: provisional heuristics). Review the result!"""
    bl_idname = "adm.auto_map_roles"
    bl_label = "Auto-Map Roles"
    bl_options = {"REGISTER", "UNDO"}

    overwrite: BoolProperty(name="Overwrite Existing", default=False)

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        from ..core import skeleton_profiles as SP
        from .rig import auto_map_profile
        arm = active_armature(context)
        pid = arm.data.adm.profile_id.strip()
        if SP.status(pid) not in (SP.NORMATIVE, SP.PROVISIONAL):
            self.report({"WARNING"}, f"'{pid}' has no semantic roles to map")
            return {"CANCELLED"}
        n = auto_map_profile(arm, overwrite=self.overwrite)
        roles = {b.adm.role for b in arm.data.bones if b.adm.role}
        req = SP.required_roles(pid)
        missing = [r for r in req if r not in roles]
        arm.data.adm.export_profile = True
        if missing:
            self.report({"WARNING"}, f"mapped {n} bones; missing required: {', '.join(missing)}")
        else:
            self.report({"INFO"}, f"mapped {n} bones; all {len(req)} required roles present")
        return {"FINISHED"}


class ADM_OT_clear_roles(bpy.types.Operator):
    bl_idname = "adm.clear_roles"
    bl_label = "Clear Roles"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        for b in active_armature(context).data.bones:
            b.adm.role = ""
        return {"FINISHED"}


class ADM_OT_select_role_bone(bpy.types.Operator):
    """Select (make active) the bone mapped to a role"""
    bl_idname = "adm.select_role_bone"
    bl_label = "Select Bone"
    bl_options = {"REGISTER", "UNDO"}

    bone: StringProperty()

    def execute(self, context):
        arm = active_armature(context)
        if arm is None or self.bone not in arm.data.bones:
            return {"CANCELLED"}
        arm.data.bones.active = arm.data.bones[self.bone]
        for b in arm.data.bones:
            b.select = b.name == self.bone
        return {"FINISHED"}


class ADM_OT_compute_rig_id(bpy.types.Operator):
    """Compute the exact rig fingerprint (§11.1) of the active armature"""
    bl_idname = "adm.compute_rig_id"
    bl_label = "Compute rigId"

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        arm = active_armature(context)
        try:
            rig = compute_rig_id(context, arm)
        except ExportError as exc:
            show_report(context, f"rigId: {arm.name}", exc.report, [exc])
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        arm.data.adm.rig_id = rig
        context.window_manager.clipboard = rig
        self.report({"INFO"}, f"rigId {rig} (copied)")
        return {"FINISHED"}


class ADM_OT_ik_chain_add(bpy.types.Operator):
    """Add an IK chain; in Pose Mode the active bone and its two parents are used (end, mid, root)"""
    bl_idname = "adm.ik_chain_add"
    bl_label = "Add IK Chain"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        arm = active_armature(context)
        sk = arm.data.adm
        ch = sk.ik_chains.add()
        b = arm.data.bones.active
        if b is not None and b.parent is not None and b.parent.parent is not None:
            ch.end, ch.mid, ch.root = b.name, b.parent.name, b.parent.parent.name
            role = b.adm.role
            from ..core import skeleton_profiles as SP
            from .rig import pole_from_adm
            tmpl = {t["end"]: t for t in SP.ik_templates(sk.profile_id.strip())}
            if role in tmpl:
                ch.chain_id = tmpl[role]["id"]
                ch.pole = pole_from_adm(arm, tmpl[role]["pole"])
            else:
                ch.chain_id = re.sub(r"[^A-Za-z0-9_]", "_", b.name) + "Chain"
                if not ch.chain_id[0].isalpha():
                    ch.chain_id = "ik_" + ch.chain_id
        ids = {c.chain_id for c in sk.ik_chains if c != ch}
        base, i = ch.chain_id, 1
        while ch.chain_id in ids:
            ch.chain_id = f"{base}{i}"
            i += 1
        sk.active_ik_chain = len(sk.ik_chains) - 1
        return {"FINISHED"}


# --------------------------------------------------------------------------------------------------
# face / expressions
# --------------------------------------------------------------------------------------------------
def _norm_key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("blendshape", "").replace("arkit", ""))


class ADM_OT_add_arkit_shape_keys(bpy.types.Operator):
    """Add the 52 ARKit shape keys (empty) to the active mesh and bind them"""
    bl_idname = "adm.add_arkit_shape_keys"
    bl_label = "Add ARKit 52 Shape Keys"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == "MESH"

    def execute(self, context):
        o = context.active_object
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        have = set(o.data.shape_keys.key_blocks.keys())
        for ch in K.ARKIT52:
            if ch not in have:
                o.shape_key_add(name=ch, from_mix=False)
        root = find_model_root(o)
        if root is not None:
            root.adm.face_enabled = True
            bpy.ops.adm.auto_bind_face()
        return {"FINISHED"}


class ADM_OT_auto_bind_face(bpy.types.Operator):
    """Bind ARKit channels to shape keys with matching names on all meshes of the model"""
    bl_idname = "adm.auto_bind_face"
    bl_label = "Auto-Bind ARKit Channels"
    bl_options = {"REGISTER", "UNDO"}

    replace: BoolProperty(name="Replace Existing", default=True)

    @classmethod
    def poll(cls, context):
        return active_root(context) is not None

    def execute(self, context):
        root = active_root(context)
        meshes = []
        stack = list(root.children)
        while stack:
            o = stack.pop()
            stack.extend(o.children)
            if o.type == "MESH" and o.data.shape_keys is not None and o.adm.adm_type == "NONE":
                meshes.append(o)
        meshes.sort(key=lambda o: o.name)
        p = root.adm
        if self.replace:
            p.face_bindings.clear()
        existing = {(b.channel, b.object.name if b.object else "", b.target) for b in p.face_bindings}
        lookup = {_norm_key(c): c for c in K.ARKIT52}
        n = 0
        for o in meshes:
            for kb in o.data.shape_keys.key_blocks[1:]:
                ch = lookup.get(_norm_key(kb.name))
                if ch is None or (ch, o.name, kb.name) in existing:
                    continue
                b = p.face_bindings.add()
                b.channel, b.object, b.target, b.scale = ch, o, kb.name, 1.0
                existing.add((ch, o.name, kb.name))
                n += 1
        p.face_enabled = p.face_enabled or n > 0
        bound = {b.channel for b in p.face_bindings}
        self.report({"INFO"}, f"{n} binding(s); {len(bound)}/52 channels bound")
        return {"FINISHED"}


class _ListOp:
    """Generic add/remove for collection properties addressed by a data path string."""
    bl_options = {"REGISTER", "UNDO"}
    owner: StringProperty(options={"HIDDEN"})
    coll: StringProperty(options={"HIDDEN"})
    index_prop: StringProperty(options={"HIDDEN"})

    def _resolve(self, context):
        owner = {"root": lambda: (active_root(context) or context.active_object).adm,
                 "object": lambda: context.active_object.adm,
                 "armature": lambda: active_armature(context).data.adm,
                 "scene": lambda: context.scene.adm_anim,
                 "library": lambda: _active_library(context),
                 "clip": lambda: _active_clip(context),
                 "expression": lambda: _active_expression(context),
                 "shader": lambda: _active_shader_def(context),
                 "material": lambda: context.object.active_material.adm}[self.owner]()
        return owner


class ADM_OT_list_add(_ListOp, bpy.types.Operator):
    bl_idname = "adm.list_add"
    bl_label = "Add Item"

    def execute(self, context):
        try:
            owner = self._resolve(context)
        except (AttributeError, TypeError, KeyError):
            return {"CANCELLED"}
        if owner is None:
            return {"CANCELLED"}
        coll = getattr(owner, self.coll)
        item = coll.add()
        if self.coll == "clips":
            _init_clip(context, item)
        elif self.coll == "libraries":
            item.armature = active_armature(context)
        elif self.coll == "expressions":
            names = {e.name for e in coll}
            base, i = "custom", 1
            while f"{base}{i}" in names:
                i += 1
            item.name = f"{base}{i}"
        elif self.coll == "events":
            fps = context.scene.render.fps / context.scene.render.fps_base
            clip = owner
            item.time = max(0.0, (context.scene.frame_current - clip.frame_start) / fps)
        elif self.coll == "shaders":
            names = {s.name for s in coll}
            sid, i = "studio.custom", 1
            while f"{sid}@1.0.0" in names:
                i += 1
                sid = f"studio.custom{i}"
            item.shader_id, item.version = sid, "1.0.0"
        elif self.coll == "params":
            names = {p.name for p in coll}
            base, i = "param", 1
            while f"{base}_{i}" in names:
                i += 1
            item.name = f"{base}_{i}"
        elif self.coll in {"physical_materials", "model_components", "hitboxes"}:
            names = {entry.name for entry in coll if entry != item}
            base, i = item.name, 1
            while item.name in names:
                item.name = f"{base}.{i}"
                i += 1
            if self.coll == "model_components":
                item.object = context.active_object
        setattr(owner, self.index_prop, len(coll) - 1)
        return {"FINISHED"}


class ADM_OT_list_remove(_ListOp, bpy.types.Operator):
    bl_idname = "adm.list_remove"
    bl_label = "Remove Item"

    def execute(self, context):
        try:
            owner = self._resolve(context)
        except (AttributeError, TypeError, KeyError):
            return {"CANCELLED"}
        if owner is None:
            return {"CANCELLED"}
        coll = getattr(owner, self.coll)
        idx = getattr(owner, self.index_prop)
        if 0 <= idx < len(coll):
            coll.remove(idx)
            setattr(owner, self.index_prop, max(0, min(idx, len(coll) - 1)))
        return {"FINISHED"}


class ADM_OT_list_move(_ListOp, bpy.types.Operator):
    bl_idname = "adm.list_move"
    bl_label = "Move Item"

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        owner = self._resolve(context)
        coll = getattr(owner, self.coll)
        idx = getattr(owner, self.index_prop)
        new = idx - 1 if self.direction == "UP" else idx + 1
        if 0 <= new < len(coll):
            coll.move(idx, new)
            setattr(owner, self.index_prop, new)
        return {"FINISHED"}


def _active_expression(context):
    root = active_root(context)
    if root is None:
        return None
    p = root.adm
    return p.expressions[p.active_expression] if 0 <= p.active_expression < len(p.expressions) else None


def _active_shader_def(context):
    s = context.scene.adm_anim
    return s.shaders[s.active_shader] if 0 <= s.active_shader < len(s.shaders) else None


def _active_library(context):
    s = context.scene.adm_anim
    return s.libraries[s.active_library] if 0 <= s.active_library < len(s.libraries) else None


def _active_clip(context):
    lib = _active_library(context)
    if lib is None:
        return None
    return lib.clips[lib.active_clip] if 0 <= lib.active_clip < len(lib.clips) else None


def _init_clip(context, clip):
    arm = getattr(_active_library(context), "armature", None)
    act = arm.animation_data.action if arm is not None and arm.animation_data else None
    ids = {c.clip_id for c in _active_library(context).clips if c != clip}
    base = re.sub(r"[^a-z0-9_]", "_", (act.name if act else "clip").lower()).strip("_") or "clip"
    if not base[0].isalpha():
        base = "clip_" + base
    cid, i = base, 1
    while cid in ids:
        cid = f"{base}_{i}"
        i += 1
    clip.clip_id = cid
    if act is not None:
        clip.action = act


# --------------------------------------------------------------------------------------------------
# animation
# --------------------------------------------------------------------------------------------------
class ADM_OT_clips_from_actions(bpy.types.Operator):
    """Create a clip for every action that animates the library rig and is not yet in the library"""
    bl_idname = "adm.clips_from_actions"
    bl_label = "Clips From Actions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        lib = _active_library(context)
        return lib is not None and (lib.armature is not None or lib.target == "MODEL_ANY")

    def execute(self, context):
        lib = _active_library(context)
        arm = lib.armature
        from .export_anim import channelbag_fcurves
        if arm is not None:
            bone_paths = tuple(f'pose.bones["{b.name}"]' for b in arm.data.bones)
            hit_of = lambda act: any(fc.data_path.startswith(bone_paths)  # noqa: E731
                                     for s in act.slots for fc in channelbag_fcurves(act, s))
        else:
            hit_of = lambda act: any(s.target_id_type in ("MATERIAL", "NODETREE", "KEY")  # noqa: E731
                                     and channelbag_fcurves(act, s) for s in act.slots)
        used = {c.action for c in lib.clips}
        n = 0
        for act in sorted(bpy.data.actions, key=lambda a: a.name):
            if act in used:
                continue
            if not hit_of(act):
                continue
            clip = lib.clips.add()
            arm_ad = arm.animation_data if arm is not None else None
            saved = arm_ad.action if arm_ad else None
            _init_clip(context, clip)
            clip.action = act
            if act.get("adm_clip_id") and act["adm_clip_id"] not in {c.clip_id for c in lib.clips if c != clip}:
                clip.clip_id = act["adm_clip_id"]
            elif saved is None or saved != act:
                base = re.sub(r"[^a-z0-9_]", "_", act.name.lower()).strip("_") or "clip"
                if not base[0].isalpha():
                    base = "clip_" + base
                ids = {c.clip_id for c in lib.clips if c != clip}
                cid, i = base, 1
                while cid in ids:
                    cid = f"{base}_{i}"
                    i += 1
                clip.clip_id = cid
            n += 1
        lib.active_clip = len(lib.clips) - 1
        self.report({"INFO"}, f"added {n} clip(s) - write a title and description for each")
        return {"FINISHED"}


class ADM_OT_play_clip(bpy.types.Operator):
    """Assign the clip action to the rig, set the scene frame range and play"""
    bl_idname = "adm.play_clip"
    bl_label = "Play Clip"

    play: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        clip, lib = _active_clip(context), _active_library(context)
        return clip is not None and clip.action is not None and \
            (lib.armature is not None or lib.target == "MODEL_ANY")

    def execute(self, context):
        from .import_anim import assign_action
        lib, clip = _active_library(context), _active_clip(context)
        assign_action(lib.armature, clip.action)
        sc = context.scene
        if clip.use_action_range:
            fs, fe = clip.action.frame_range
        else:
            fs, fe = clip.frame_start, clip.frame_end
        sc.frame_start, sc.frame_end = int(fs), max(int(fs), int(round(fe)))
        sc.frame_set(int(fs))
        if self.play and not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        return {"FINISHED"}


class ADM_OT_events_from_markers(bpy.types.Operator):
    """Create clip events from timeline markers inside the clip range (marker name = event name)"""
    bl_idname = "adm.events_from_markers"
    bl_label = "Events From Markers"
    bl_options = {"REGISTER", "UNDO"}

    replace: BoolProperty(name="Replace Events", default=True)

    @classmethod
    def poll(cls, context):
        return _active_clip(context) is not None

    def execute(self, context):
        clip = _active_clip(context)
        sc = context.scene
        fps = sc.render.fps / sc.render.fps_base
        fs, fe = (clip.action.frame_range if clip.use_action_range and clip.action else
                  (clip.frame_start, clip.frame_end))
        markers = list(sc.timeline_markers)
        if clip.action is not None and len(clip.action.pose_markers):
            markers = list(clip.action.pose_markers)
        if self.replace:
            clip.events.clear()
        n = 0
        for m in sorted(markers, key=lambda m: (m.frame, m.name)):
            if not fs <= m.frame <= fe:
                continue
            name = re.sub(r"[^a-z0-9_.]", "_", m.name.lower())
            if not name or not name[0].isalpha():
                name = "event_" + name
            e = clip.events.add()
            e.time, e.name = (m.frame - fs) / fps, name
            n += 1
        self.report({"INFO"}, f"{n} event(s)")
        return {"FINISHED"}


class ADM_OT_expression_preview(bpy.types.Operator):
    """Key the expression weight custom property on the rig (adm_expr_<name>) at the current frame"""
    bl_idname = "adm.expression_key"
    bl_label = "Key Expression Weight"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        lib = _active_library(context)
        arm = lib.armature if lib else active_armature(context)
        if arm is None:
            self.report({"ERROR"}, "no rig")
            return {"CANCELLED"}
        from .export_anim import EXPR_PREFIX
        prop = EXPR_PREFIX + self.name
        if prop not in arm:
            arm[prop] = 0.0
            arm.id_properties_ui(prop).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0)
        arm.keyframe_insert(f'["{prop}"]')
        return {"FINISHED"}


def _active_material(context):
    mat = getattr(context, "material", None)
    if mat is not None:
        return mat
    ob = context.object
    return ob.active_material if ob is not None else None


def _uv_names(context):
    ob = context.object
    if ob is not None and ob.type == "MESH":
        return [layer.name for layer in ob.data.uv_layers]
    return []


_SLOT_ITEMS = [("BASE_COLOR", "Base Color", ""), ("METALLIC_ROUGHNESS", "Metallic-Roughness", ""),
               ("NORMAL", "Normal", ""), ("OCCLUSION", "Occlusion", ""), ("EMISSIVE", "Emissive", "")]


class _SlotOp:
    bl_options = {"REGISTER", "UNDO"}
    slot: EnumProperty(items=_SLOT_ITEMS)

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None


class ADM_OT_material_texture_open(_SlotOp, bpy.types.Operator):
    """Load an image file into this ADM texture slot (creates the matching node chain)"""
    bl_idname = "adm.material_texture_open"
    bl_label = "Open Texture"
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.tiff;*.exr;*.hdr;*.webp;*.dds;*.ktx2",
                                options={"HIDDEN", "SKIP_SAVE"})
    filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from .materials import load_image_file, set_slot_image
        try:
            img = load_image_file(self.filepath)
            set_slot_image(_active_material(context), self.slot, img)
        except (RuntimeError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class ADM_OT_material_texture_clear(_SlotOp, bpy.types.Operator):
    """Remove the texture from this slot (constant factors are kept)"""
    bl_idname = "adm.material_texture_clear"
    bl_label = "Remove Texture"

    def execute(self, context):
        from .materials import clear_slot
        if not clear_slot(_active_material(context), self.slot):
            return {"CANCELLED"}
        return {"FINISHED"}


class ADM_OT_material_texture_adopt(_SlotOp, bpy.types.Operator):
    """Replace the slot's custom node setup with a simple ADM chain using the texture found in it.
The custom nodes are only disconnected, not deleted"""
    bl_idname = "adm.material_texture_adopt"
    bl_label = "Use Detected Texture"
    bl_options = {"REGISTER", "UNDO"}
    node: StringProperty(name="Node", description="Image texture node of the custom setup (empty = best match)")

    def execute(self, context):
        from .materials import custom_source_candidates, set_slot_image
        mat = _active_material(context)
        cands = custom_source_candidates(mat, self.slot)
        src = next((n for n in cands if n.name == self.node), None) if self.node else (cands[0] if cands else None)
        if src is None:
            self.report({"WARNING"}, "No image texture found in the custom node setup")
            return {"CANCELLED"}
        set_slot_image(mat, self.slot, src.image, source=src)
        return {"FINISHED"}


class ADM_OT_material_texture_uv(_SlotOp, bpy.types.Operator):
    """Choose which UV map (texCoord 0 or 1) the texture uses"""
    bl_idname = "adm.material_texture_uv"
    bl_label = "Texture UV"
    index: IntProperty(min=0, max=1)

    def execute(self, context):
        from .materials import set_slot_uv
        if not set_slot_uv(_active_material(context), self.slot, self.index, _uv_names(context)):
            return {"CANCELLED"}
        return {"FINISHED"}


class ADM_OT_material_texture_alpha(bpy.types.Operator):
    """Use the base color texture alpha channel as material alpha"""
    bl_idname = "adm.material_texture_alpha"
    bl_label = "Use Texture Alpha"
    bl_options = {"REGISTER", "UNDO"}
    use: BoolProperty()

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None

    def execute(self, context):
        from .materials import set_slot_alpha
        mat = _active_material(context)
        if not set_slot_alpha(mat, self.use):
            return {"CANCELLED"}
        if self.use and mat.adm.alpha_mode == "OPAQUE":
            mat.adm.alpha_mode = "AUTO"
        return {"FINISHED"}


class ADM_OT_material_auto_animation_id(bpy.types.Operator):
    """Derive a unique animationId ([a-z][a-z0-9_]*) from the material name"""
    bl_idname = "adm.material_auto_animation_id"
    bl_label = "Auto Animation ID"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None

    def execute(self, context):
        from .materials import unique_animation_id
        mat = _active_material(context)
        taken = {m.adm.animation_id.strip() for m in bpy.data.materials if m != mat} - {""}
        mat.adm.animation_id = unique_animation_id(mat.name, taken)
        return {"FINISHED"}


class ADM_OT_material_sync_params(bpy.types.Operator):
    """Rebuild the material's parameter list from the selected custom shader definition"""
    bl_idname = "adm.material_sync_params"
    bl_label = "Sync Parameters"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        mat = _active_material(context)
        return mat is not None and mat.adm.shader == "CUSTOM"

    def execute(self, context):
        from .materials import sync_material_params
        mat = _active_material(context)
        sdef = context.scene.adm_anim.shaders.get(mat.adm.custom_shader)
        if sdef is None:
            self.report({"ERROR"}, f"shader definition '{mat.adm.custom_shader}' not found in the scene")
            return {"CANCELLED"}
        sync_material_params(mat, sdef)
        return {"FINISHED"}


class ADM_OT_material_refresh_preview(bpy.types.Operator):
    """Rebuild the ADM shader viewport preview (ADM Preview nodes) from the current parameters and the
portable PBR node chain"""
    bl_idname = "adm.material_refresh_preview"
    bl_label = "Refresh Shader Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None

    def execute(self, context):
        from .materials import refresh_shader_preview
        refresh_shader_preview(_active_material(context))
        return {"FINISHED"}


class ADM_OT_material_generate_mortar_mask(bpy.types.Operator):
    """Generate a running-bond brick mortar mask (white = mortar, black = brick) and assign it to the
material's mortar_mask parameter. Align rows/columns with the bricks of the Base Color texture"""
    bl_idname = "adm.material_generate_mortar_mask"
    bl_label = "Generate Mortar Mask"
    bl_options = {"REGISTER", "UNDO"}

    rows: IntProperty(name="Brick Rows", default=8, min=1, max=256)
    columns: IntProperty(name="Bricks Per Row", default=4, min=1, max=256)
    mortar: FloatProperty(name="Mortar Width", default=0.08, min=0.0, max=0.5, subtype="FACTOR",
                          description="Joint width as a fraction of the brick height")
    offset: FloatProperty(name="Row Offset", default=0.5, min=0.0, max=1.0, subtype="FACTOR")
    resolution: IntProperty(name="Resolution", default=512, min=16, max=4096)

    @classmethod
    def poll(cls, context):
        mat = _active_material(context)
        return mat is not None and mat.adm.params.get("mortar_mask") is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import numpy as np
        from ..core.shader_math import mortar_mask_pixels
        mat = _active_material(context)
        res = self.resolution
        px = mortar_mask_pixels(res, res, self.rows, self.columns, self.mortar, self.offset)
        img = bpy.data.images.new(f"{mat.name}_mortar_mask", res, res, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        rgba = np.repeat(px[..., None], 4, axis=2)
        rgba[..., 3] = 1.0
        img.pixels.foreach_set(rgba.astype(np.float32).ravel())
        img.update()
        img.pack()
        mat.adm.params["mortar_mask"].image = img
        return {"FINISHED"}


class ADM_OT_material_layers_from_pbr(bpy.types.Operator):
    """Copy the current Principled BSDF factors into the base layer record"""
    bl_idname = "adm.material_layers_from_pbr"
    bl_label = "Base Layer From PBR"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None

    def execute(self, context):
        from .materials import layers_from_pbr
        layers_from_pbr(_active_material(context))
        return {"FINISHED"}


class ADM_OT_material_link_clip(bpy.types.Operator):
    """Animate this material inside the active clip: assigns the clip action (material + node tree slots)
so keyframes on shader parameters and PBR factors become pbrParameter / shaderParameter channels"""
    bl_idname = "adm.material_link_clip"
    bl_label = "Link Material To Clip"
    bl_options = {"REGISTER", "UNDO"}

    unlink: BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        clip = _active_clip(context)
        return _active_material(context) is not None and clip is not None and clip.action is not None

    def execute(self, context):
        from . import material_anim as mat_anim
        from .materials import unique_animation_id
        mat, clip = _active_material(context), _active_clip(context)
        if self.unlink:
            act = clip.action
            ms, ns = mat_anim.material_slots(act, mat)
            for s in (ms, ns):
                if s is not None:
                    act.slots.remove(s)
            for idb in (mat, mat.node_tree):
                if idb is not None and idb.animation_data and idb.animation_data.action == act:
                    idb.animation_data.action = None
            return {"FINISHED"}
        if not mat.adm.animation_id.strip():
            taken = {m.adm.animation_id.strip() for m in bpy.data.materials if m != mat} - {""}
            mat.adm.animation_id = unique_animation_id(mat.name, taken)
        if not clip.action.get("adm_clip_id"):
            clip.action["adm_clip_id"] = clip.clip_id
        mat_anim.bind_material(mat, clip.action)
        self.report({"INFO"}, f"'{mat.name}' animates in clip '{clip.clip_id}' - key its ADM / BSDF values")
        return {"FINISHED"}


class ADM_OT_material_key_param(bpy.types.Operator):
    """Insert a keyframe for an animatable ADM shader parameter at the current frame"""
    bl_idname = "adm.material_key_param"
    bl_label = "Key Parameter"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    @classmethod
    def poll(cls, context):
        return _active_material(context) is not None

    def execute(self, context):
        mat = _active_material(context)
        a = mat.adm
        from .material_anim import VERTEX_CONTROL_PROP_BY_PARAM
        control_prop = VERTEX_CONTROL_PROP_BY_PARAM.get(self.name)
        if control_prop is not None:
            if not a.vertex_controls_enabled:
                self.report({"ERROR"}, "Enable ADM Vertex Controls before keying these parameters")
                return {"CANCELLED"}
            mat.keyframe_insert(f"adm.{control_prop}")
            return {"FINISHED"}
        if a.shader == "LAYERED" and self.name == "layer_factor":
            mat.keyframe_insert("adm.layer_factor")
            return {"FINISHED"}
        v = a.params.get(self.name)
        if v is None:
            self.report({"ERROR"}, f"parameter '{self.name}' not on material (sync parameters first)")
            return {"CANCELLED"}
        v.use = True
        from .materials import scene_shader_registry
        prm = scene_shader_registry(context.scene).get(a.shader_key(), {}).get(self.name, {})
        prop = "value_f" if prm.get("type") == "F32" else "value_vec"
        mat.keyframe_insert(f'adm.params["{self.name}"].{prop}')
        return {"FINISHED"}


# --------------------------------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------------------------------
class ADM_OT_validate_model(bpy.types.Operator):
    """Build the ADM model in memory and validate it against the ADM 1.0 rules (nothing is written)"""
    bl_idname = "adm.validate_model"
    bl_label = "Validate Model"

    def execute(self, context):
        root = active_root(context)
        exp = ModelExporter(context, root, ExportOptions())
        title = f"Model: {root.name if root else 'Scene'}"
        try:
            _data, report = exp.export()
        except ExportError as exc:
            show_report(context, title, exc.report, [exc], exp.warnings)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        show_report(context, title, report, (), exp.warnings)
        self.report({"INFO"}, f"VALID ({len(report.warnings)} spec warnings, {len(exp.warnings)} export notes)")
        return {"FINISHED"}


class ADM_OT_validate_library(bpy.types.Operator):
    """Build the active animation library in memory and validate it"""
    bl_idname = "adm.validate_library"
    bl_label = "Validate Library"

    @classmethod
    def poll(cls, context):
        return _active_library(context) is not None

    def execute(self, context):
        from .export_anim import AnimExporter
        lib = _active_library(context)
        exp = AnimExporter(context, lib)
        title = f"Library: {lib.lib_id}"
        try:
            _data, report = exp.export()
        except ExportError as exc:
            show_report(context, title, exc.report, [exc], exp.warnings)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        show_report(context, title, report, (), exp.warnings)
        self.report({"INFO"}, "VALID")
        return {"FINISHED"}


class ADM_OT_validate_file(bpy.types.Operator):
    """Validate an .adm / .adm_anim file on disk"""
    bl_idname = "adm.validate_file"
    bl_label = "Validate ADM File"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.adm;*.adm_anim", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        rep = validate_file(self.filepath)
        show_report(context, bpy.path.basename(self.filepath), rep)
        if rep.ok:
            self.report({"INFO"}, f"VALID ({len(rep.warnings)} warnings)")
        else:
            self.report({"ERROR"}, f"INVALID ({len(rep.errors)} errors) - see ADM > Validation")
        return {"FINISHED"}


class ADM_OT_clear_report(bpy.types.Operator):
    bl_idname = "adm.clear_report"
    bl_label = "Clear Report"

    def execute(self, context):
        context.window_manager.adm.report.clear()
        context.window_manager.adm.report_title = ""
        return {"FINISHED"}


CLASSES = (
    ADM_OT_create_model_root, ADM_OT_create_scene, ADM_OT_create_collider, ADM_OT_convert_to_collider,
    ADM_OT_physical_material_assign_faces, ADM_OT_interactive_surface_assign_faces,
    ADM_OT_create_lod_group, ADM_OT_lod_level_add, ADM_OT_lod_level_remove, ADM_OT_lod_preview,
    ADM_OT_create_attachment, ADM_OT_set_type, ADM_OT_convert_materials,
    ADM_OT_auto_map_roles, ADM_OT_clear_roles, ADM_OT_select_role_bone, ADM_OT_compute_rig_id,
    ADM_OT_ik_chain_add,
    ADM_OT_add_arkit_shape_keys, ADM_OT_auto_bind_face,
    ADM_OT_list_add, ADM_OT_list_remove, ADM_OT_list_move,
    ADM_OT_clips_from_actions, ADM_OT_play_clip, ADM_OT_events_from_markers, ADM_OT_expression_preview,
    ADM_OT_material_auto_animation_id, ADM_OT_material_sync_params, ADM_OT_material_refresh_preview,
    ADM_OT_material_generate_mortar_mask, ADM_OT_material_layers_from_pbr,
    ADM_OT_material_texture_open, ADM_OT_material_texture_clear, ADM_OT_material_texture_adopt,
    ADM_OT_material_texture_uv,
    ADM_OT_material_texture_alpha,
    ADM_OT_material_link_clip, ADM_OT_material_key_param,
    ADM_OT_validate_model, ADM_OT_validate_library, ADM_OT_validate_file, ADM_OT_clear_report,
)
