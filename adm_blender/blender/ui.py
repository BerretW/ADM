"""Sollumz-style UI: 3D View sidebar tab "ADM", Properties editor panels, Add menu."""

import bpy

from ..core import constants as K
from .export_adm import find_model_root
from .operators import _active_clip, _active_library, active_armature

from .props import ADM_TYPES

TYPE_ICON = {t[0]: t[3] for t in ADM_TYPES}


def _list_buttons(layout, owner, coll, index_prop, move=False):
    col = layout.column(align=True)
    op = col.operator("adm.list_add", icon="ADD", text="")
    op.owner, op.coll, op.index_prop = owner, coll, index_prop
    op = col.operator("adm.list_remove", icon="REMOVE", text="")
    op.owner, op.coll, op.index_prop = owner, coll, index_prop
    if move:
        col.separator()
        for d, icon in (("UP", "TRIA_UP"), ("DOWN", "TRIA_DOWN")):
            op = col.operator("adm.list_move", icon=icon, text="")
            op.owner, op.coll, op.index_prop, op.direction = owner, coll, index_prop, d
    return col


# ==================================================================================================
# UI lists
# ==================================================================================================
class ADM_UL_lod_levels(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"LOD{index}")
        row.prop(item, "object", text="")
        row.prop(item, "min_distance", text="")


class ADM_UL_face_bindings(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "channel", text="")
        row.prop(item, "object", text="")
        if item.object and item.object.data.shape_keys:
            row.prop_search(item, "target", item.object.data.shape_keys, "key_blocks", text="")
        else:
            row.prop(item, "target", text="")
        row.prop(item, "scale", text="")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt = []
        if self.filter_name:
            f = self.filter_name.lower()
            flt = [self.bitflag_filter_item if f in it.channel.lower() or f in it.target.lower() else 0
                   for it in items]
        order = bpy.types.UI_UL_list.sort_items_by_name(items, "channel") if self.use_filter_sort_alpha else []
        return flt, order


class ADM_UL_expressions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="SHAPEKEY_DATA")
        row.label(text=f"{item.group} · {len(item.bindings)}")


class ADM_UL_expression_bindings(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "object", text="")
        if item.object and item.object.data.shape_keys:
            row.prop_search(item, "target", item.object.data.shape_keys, "key_blocks", text="")
        else:
            row.prop(item, "target", text="")
        row.prop(item, "weight", text="")


class ADM_UL_ik_chains(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "chain_id", text="", emboss=False, icon="CON_KINEMATIC")
        row.label(text=f"{item.root} › {item.mid} › {item.end}")


class ADM_UL_bone_roles(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="BONE_DATA" if item.use_deform else "BONE_DATA")
        arm_props = data.adm if hasattr(data, "adm") else None
        wm = context.window_manager.adm
        if arm_props is not None and arm_props.profile == "humanoid.vrm1" and len(wm.role_names):
            row.prop_search(item.adm, "role", wm, "role_names", text="", icon="NONE")
        else:
            row.prop(item.adm, "role", text="")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        mapped_only = data.adm.roles_mapped_only
        f = self.filter_name.lower()
        flt = []
        for b in items:
            ok = (not mapped_only or bool(b.adm.role)) and (not f or f in b.name.lower() or f in b.adm.role.lower())
            flt.append(self.bitflag_filter_item if ok else 0)
        return flt, []


class ADM_UL_libraries(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "lib_id", text="", emboss=False, icon="ACTION")
        row.label(text=f"{'model.any' if item.target == 'MODEL_ANY' else item.binding.lower()} · {len(item.clips)}")


class ADM_UL_shader_defs(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name or "?", icon="SCRIPT")
        row.label(text=f"{len(item.params)} params")


class ADM_UL_shader_params(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="ANIM" if item.animatable else "DOT")
        row.label(text=item.type)


class ADM_UL_clips(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        ok = bool(item.title.strip() and item.description.strip() and item.action)
        row.prop(item, "clip_id", text="", emboss=False, icon="PLAY" if ok else "ERROR")
        row.label(text=item.action.name if item.action else "—")


class ADM_UL_events(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "time", text="")
        row.prop(item, "name", text="")


class ADM_UL_report(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        ic = {"ERROR": "CANCEL", "WARNING": "ERROR"}.get(item.severity, "INFO")
        row = layout.row(align=True)
        row.label(text=f"{item.code}: {item.message}", icon=ic)


# ==================================================================================================
# drawing helpers shared by sidebar and properties editor
# ==================================================================================================
def draw_object_props(layout, context, obj):
    p = obj.adm
    layout.use_property_split = True
    layout.use_property_decorate = False
    row = layout.row()
    row.prop(p, "adm_type", text="Type")
    root = find_model_root(obj)
    if root is not None and root != obj:
        row = layout.row()
        row.enabled = False
        row.prop(root, "name", text="Model", icon="OUTLINER_OB_EMPTY")
    layout.prop(p, "export_exclude")
    t = p.adm_type
    if t == "MODEL":
        layout.prop(p, "copyright")
        layout.prop(p, "default_scene")
        draw_model_metadata(layout, p)
    elif t == "COLLIDER":
        box = layout.box()
        box.prop(p, "collider_shape")
        if p.collider_shape == "BOX":
            box.prop(p, "collider_size")
        elif p.collider_shape == "SPHERE":
            box.prop(p, "collider_radius")
        elif p.collider_shape == "CAPSULE":
            box.prop(p, "collider_radius")
            box.prop(p, "collider_height")
        else:
            box.label(text="Uses this object's mesh triangles", icon="INFO")
        box.prop(p, "collider_trigger")
        if root is not None:
            box.prop_search(p, "physical_material", root.adm, "physical_materials")
        else:
            box.prop(p, "physical_material")
    elif t == "LOD_GROUP":
        layout.use_property_split = False
        row = layout.row()
        row.template_list("ADM_UL_lod_levels", "", p, "lod_levels", p, "active_lod_level", rows=3)
        col = row.column(align=True)
        col.operator("adm.lod_level_add", icon="ADD", text="")
        col.operator("adm.lod_level_remove", icon="REMOVE", text="")
        row = layout.row(align=True)
        row.prop(p, "lod_preview_distance", text="Preview")
        row.operator("adm.lod_preview", text="", icon="HIDE_OFF").show_all = False
        op = row.operator("adm.lod_preview", text="", icon="RESTRICT_VIEW_OFF")
        op.show_all = True
    if t in {"NONE", "ATTACHMENT", "LOD_GROUP"}:
        col = layout.column()
        col.prop(p, "attachment_name", text="Attachment" if t != "ATTACHMENT" else "Name")
    if t in {"NONE", "ATTACHMENT"}:
        col = layout.column()
        col.prop(p, "component_role")
        if p.component_role.strip():
            col.prop(p, "component_profile")


def draw_model_metadata(layout, props):
    for collection, index, title, fields in (
            ("physical_materials", "active_physical_material", "Physical Materials", ("friction", "restitution")),
            ("model_components", "active_model_component", "Model Components", ("role", "object", "bone", "socket")),
            ("hitboxes", "active_hitbox", "Hitboxes", ("collider", "object", "bone", "role"))):
        box = layout.box()
        box.label(text=title)
        row = box.row()
        row.template_list("UI_UL_list", collection, props, collection, props, index, rows=2)
        _list_buttons(row, "root", collection, index)
        items = getattr(props, collection)
        active = getattr(props, index)
        if 0 <= active < len(items):
            item = items[active]
            box.prop(item, "name")
            for field in fields:
                if field == "bone":
                    if item.object is not None and item.object.type == "ARMATURE":
                        box.prop_search(item, field, item.object.data, "bones")
                    elif item.bone:
                        box.prop(item, field)
                else:
                    box.prop(item, field)
    layout.label(text="Vehicle / weapon profiles remain provisional", icon="INFO")


def draw_bone_props(layout, context, arm, bone):
    p = bone.adm
    layout.use_property_split = True
    layout.use_property_decorate = False
    wm = context.window_manager.adm
    if arm.data.adm.profile == "humanoid.vrm1" and len(wm.role_names):
        layout.prop_search(p, "role", wm, "role_names")
    else:
        layout.prop(p, "role")
    col = layout.column(heading="Reference")
    col.prop(p, "use_reference_correction", text="Correction")
    if p.use_reference_correction:
        col.prop(p, "reference_correction", text="")
    layout.prop(p, "attachment_name", text="Attachment")
    layout.prop(p, "component_role")
    if p.component_role.strip():
        layout.prop(p, "component_profile")


def draw_skeleton(layout, context, arm):
    sk = arm.data.adm
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(sk, "export_profile")
    col = layout.column()
    col.enabled = sk.export_profile
    col.prop(sk, "profile")
    if sk.profile == "CUSTOM":
        col.prop(sk, "custom_profile")
    row = col.row(heading="Target Height")
    row.prop(sk, "use_target_height", text="")
    sub = row.row()
    sub.enabled = sk.use_target_height
    sub.prop(sk, "target_height", text="")
    col.prop(sk, "write_rig_id")
    row = layout.row(align=True)
    row.operator("adm.auto_map_roles", icon="AUTOMERGE_ON")
    row.operator("adm.clear_roles", icon="X", text="")
    if sk.profile == "humanoid.vrm1":
        roles = {b.adm.role for b in arm.data.bones if b.adm.role}
        missing = [r for r in K.VRM1_REQUIRED if r not in roles]
        if missing:
            box = layout.box()
            box.label(text=f"Missing {len(missing)} required role(s):", icon="ERROR")
            flow = box.grid_flow(columns=2, align=True)
            for r in missing:
                flow.label(text=r)
        else:
            layout.label(text=f"{len(roles)} roles mapped · all required present", icon="CHECKMARK")
    layout.use_property_split = False
    row = layout.row()
    row.prop(sk, "roles_mapped_only", toggle=True, icon="FILTER")
    layout.template_list("ADM_UL_bone_roles", "", arm.data, "bones", sk, "active_bone_index", rows=6)
    row = layout.row(align=True)
    row.operator("adm.compute_rig_id", icon="KEY_HLT")
    if sk.rig_id:
        layout.label(text=sk.rig_id[:32] + "…", icon="LINKED")


def draw_ik(layout, context, arm):
    sk = arm.data.adm
    row = layout.row()
    row.template_list("ADM_UL_ik_chains", "", sk, "ik_chains", sk, "active_ik_chain", rows=3)
    col = row.column(align=True)
    col.operator("adm.ik_chain_add", icon="ADD", text="")
    op = col.operator("adm.list_remove", icon="REMOVE", text="")
    op.owner, op.coll, op.index_prop = "armature", "ik_chains", "active_ik_chain"
    if 0 <= sk.active_ik_chain < len(sk.ik_chains):
        ch = sk.ik_chains[sk.active_ik_chain]
        col = layout.column()
        col.use_property_split = True
        col.prop(ch, "chain_id")
        for f in ("root", "mid", "end"):
            col.prop_search(ch, f, arm.data, "bones")
        col.prop(ch, "pole")
        col.prop(ch, "weight")


# ==================================================================================================
# sidebar panels
# ==================================================================================================
class _Side:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ADM"


class ADM_PT_tools(_Side, bpy.types.Panel):
    bl_label = "ADM Tools"
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(icon="MOD_BUILD")

    def draw(self, context):
        lay = self.layout
        wm = context.window_manager.adm
        box = lay.box()
        box.label(text="Create", icon="ADD")
        col = box.column(align=True)
        col.operator("adm.create_model_root", icon="OUTLINER_OB_EMPTY")
        col.operator("adm.create_scene", icon="SCENE_DATA")
        row = col.row(align=True)
        row.operator("adm.create_collider", icon="MESH_ICOSPHERE")
        row.prop(wm, "collider_shape", text="")
        col.operator("adm.create_lod_group", icon="MOD_DECIM")
        col.operator("adm.create_attachment", icon="EMPTY_ARROWS")
        box = lay.box()
        box.label(text="Convert", icon="FILE_REFRESH")
        col = box.column(align=True)
        col.operator_menu_enum("adm.set_type", "adm_type", text="Set ADM Type", icon="OBJECT_DATA")
        col.operator("adm.convert_to_collider", icon="MOD_PHYSICS")
        col.operator("adm.convert_materials", icon="MATERIAL")
        box = lay.box()
        box.label(text="Files", icon="FILE")
        row = box.row(align=True)
        row.operator("import_scene.adm", text="Import", icon="IMPORT")
        row.operator("export_scene.adm", text="Export", icon="EXPORT")
        row = box.row(align=True)
        row.operator("import_anim.adm_anim", text="Import Anim", icon="IMPORT")
        row.operator("export_anim.adm_anim", text="Export Anim", icon="EXPORT")


class ADM_PT_object(_Side, bpy.types.Panel):
    bl_label = "Object"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw_header(self, context):
        self.layout.label(icon=TYPE_ICON.get(context.active_object.adm.adm_type, "OBJECT_DATA"))

    def draw(self, context):
        obj = context.active_object
        if obj.type == "ARMATURE" and obj.mode == "POSE" and context.active_bone is not None:
            self.layout.label(text=f"Bone: {context.active_bone.name}", icon="BONE_DATA")
            draw_bone_props(self.layout, context, obj, obj.data.bones[context.active_bone.name])
            self.layout.separator()
        draw_object_props(self.layout, context, obj)


class ADM_PT_skeleton(_Side, bpy.types.Panel):
    bl_label = "Skeleton"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def draw_header(self, context):
        self.layout.label(icon="ARMATURE_DATA")

    def draw(self, context):
        draw_skeleton(self.layout, context, active_armature(context))


class ADM_PT_ik(_Side, bpy.types.Panel):
    bl_label = "IK Chains"
    bl_parent_id = "ADM_PT_skeleton"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_ik(self.layout, context, active_armature(context))


class ADM_PT_face(_Side, bpy.types.Panel):
    bl_label = "Face & Expressions"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and find_model_root(context.active_object) is not None

    def draw_header(self, context):
        self.layout.label(icon="SHAPEKEY_DATA")

    def draw(self, context):
        lay = self.layout
        root = find_model_root(context.active_object)
        p = root.adm
        lay.prop(p, "face_enabled")
        row = lay.row(align=True)
        row.operator("adm.add_arkit_shape_keys", icon="SHAPEKEY_DATA")
        row.operator("adm.auto_bind_face", icon="LINKED", text="Auto-Bind")
        bound = len({b.channel for b in p.face_bindings})
        lay.label(text=f"ARKit channels bound: {bound}/52", icon="CHECKMARK" if bound == 52 else "INFO")
        row = lay.row()
        row.template_list("ADM_UL_face_bindings", "", p, "face_bindings", p, "active_face_binding", rows=4)
        _list_buttons(row, "root", "face_bindings", "active_face_binding")


class ADM_PT_expressions(_Side, bpy.types.Panel):
    bl_label = "Expressions"
    bl_parent_id = "ADM_PT_face"

    def draw(self, context):
        lay = self.layout
        p = find_model_root(context.active_object).adm
        row = lay.row()
        row.template_list("ADM_UL_expressions", "", p, "expressions", p, "active_expression", rows=3)
        _list_buttons(row, "root", "expressions", "active_expression")
        if 0 <= p.active_expression < len(p.expressions):
            ex = p.expressions[p.active_expression]
            col = lay.column()
            col.use_property_split = True
            col.prop(ex, "name")
            col.prop(ex, "group")
            col.prop(ex, "priority")
            row = lay.row()
            row.template_list("ADM_UL_expression_bindings", "", ex, "bindings", ex, "active_binding", rows=3)
            _list_buttons(row, "expression", "bindings", "active_binding")
            lay.operator("adm.expression_key", icon="KEYFRAME").name = ex.name


class ADM_PT_animation(_Side, bpy.types.Panel):
    bl_label = "Animation Libraries"
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(icon="ACTION")

    def draw(self, context):
        lay = self.layout
        s = context.scene.adm_anim
        row = lay.row()
        row.template_list("ADM_UL_libraries", "", s, "libraries", s, "active_library", rows=2)
        _list_buttons(row, "scene", "libraries", "active_library")
        lib = _active_library(context)
        if lib is None:
            lay.label(text="Add a library to author .adm_anim clips", icon="INFO")
            return
        col = lay.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(lib, "lib_id")
        col.prop(lib, "target")
        if lib.target == "MODEL_ANY":
            col.prop(lib, "armature", text="Rig (Optional)")
            r = col.row()
            r.enabled = False
            r.label(text=f"Target profile: {K.MODEL_ANY_PROFILE} (semantic)")
        else:
            col.prop(lib, "armature")
            col.prop(lib, "binding")
        if lib.armature is not None and lib.target != "MODEL_ANY":
            r = col.row()
            r.enabled = False
            r.label(text=f"Target profile: {lib.armature.data.adm.profile_id}")
        col.prop(lib, "title")
        col.prop(lib, "description")
        col.prop(lib, "language")
        col.prop(lib, "tags")
        sub = lay.column()
        sub.use_property_split = True
        hdr, body = sub.panel("adm_lib_meta", default_closed=True)
        hdr.label(text="Distribution & Motion")
        if body is not None:
            for k in ("author", "license", "revision", "namespace"):
                body.prop(lib, k)
            if lib.binding == "SEMANTIC" and lib.target != "MODEL_ANY":
                body.prop(lib, "use_motion_scale")
                rr = body.row()
                rr.enabled = lib.use_motion_scale
                rr.prop(lib, "source_height")
                body.prop(lib, "root_motion_from_hips")
        lay.separator()
        row = lay.row()
        row.template_list("ADM_UL_clips", "", lib, "clips", lib, "active_clip", rows=4)
        col = _list_buttons(row, "library", "clips", "active_clip", move=True)
        col.separator()
        col.operator("adm.clips_from_actions", icon="IMPORT", text="")
        clip = _active_clip(context)
        if clip is None:
            return
        col = lay.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(clip, "clip_id")
        col.prop(clip, "action")
        col.prop(clip, "use_action_range")
        r = col.row(align=True)
        r.enabled = not clip.use_action_range
        r.prop(clip, "frame_start")
        r.prop(clip, "frame_end")
        col.prop(clip, "title")
        col.prop(clip, "description")
        if not clip.description.strip():
            col.label(text="Description is required (never auto-generated)", icon="ERROR")
        col.prop(clip, "language")
        col.prop(clip, "tags")
        col.prop(clip, "loop")
        col.prop(clip, "root_motion")
        if clip.root_motion == "EXTRACT" and lib.binding == "EXACT" and lib.armature is not None:
            col.prop_search(clip, "root_bone", lib.armature.data, "bones")
        row = lay.row(align=True)
        row.scale_y = 1.3
        row.operator("adm.play_clip", icon="PLAY")
        row = lay.row(align=True)
        row.operator("adm.validate_library", icon="CHECKMARK")
        row.operator("export_anim.adm_anim", icon="EXPORT", text="Export")
        hdr, body = lay.panel("adm_clip_events", default_closed=True)
        hdr.label(text=f"Events ({len(clip.events)})")
        if body is not None:
            row = body.row()
            row.template_list("ADM_UL_events", "", clip, "events", clip, "active_event", rows=3)
            _list_buttons(row, "clip", "events", "active_event")
            body.operator("adm.events_from_markers", icon="MARKER_HLT")
            if 0 <= clip.active_event < len(clip.events):
                body.prop(clip.events[clip.active_event], "payload")


class ADM_PT_validation(_Side, bpy.types.Panel):
    bl_label = "Validation"
    bl_order = 6

    def draw_header(self, context):
        self.layout.label(icon="CHECKMARK")

    def draw(self, context):
        lay = self.layout
        wm = context.window_manager.adm
        row = lay.row(align=True)
        row.operator("adm.validate_model", icon="CHECKMARK")
        row.operator("adm.validate_file", icon="FILE_TICK", text="File…")
        if wm.report_title:
            nerr = sum(1 for r in wm.report if r.severity == "ERROR")
            nwarn = sum(1 for r in wm.report if r.severity == "WARNING")
            row = lay.row()
            row.label(text=wm.report_title, icon="CANCEL" if nerr else "CHECKMARK")
            row.label(text=f"{nerr} errors · {nwarn} warnings")
            row.operator("adm.clear_report", icon="X", text="")
            if len(wm.report):
                lay.template_list("ADM_UL_report", "", wm, "report", wm, "active_report", rows=4)
                if 0 <= wm.active_report < len(wm.report):
                    it = wm.report[wm.active_report]
                    box = lay.box()
                    col = box.column(align=True)
                    if it.path:
                        col.label(text=it.path, icon="RNA")
                    _wrap(col, it.message)


def _wrap(layout, text, width=48):
    line = ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            layout.label(text=line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        layout.label(text=line)


# ==================================================================================================
# properties editor panels
# ==================================================================================================
class ADM_PT_object_properties(bpy.types.Panel):
    bl_label = "ADM"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        draw_object_props(self.layout, context, context.object)


class ADM_PT_bone_properties(bpy.types.Panel):
    bl_label = "ADM"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE" and context.bone is not None

    def draw(self, context):
        draw_bone_props(self.layout, context, context.object, context.bone)


class ADM_PT_armature_properties(bpy.types.Panel):
    bl_label = "ADM Skeleton"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def draw(self, context):
        draw_skeleton(self.layout, context, context.object)
        hdr, body = self.layout.panel("adm_arm_ik", default_closed=True)
        hdr.label(text="IK Chains")
        if body is not None:
            draw_ik(body, context, context.object)


class ADM_PT_material_properties(bpy.types.Panel):
    bl_label = "ADM"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        draw_material(self.layout, context, context.material)


def _vec_prop(layout, owner, attr, n, text=""):
    if n == 1:
        layout.prop(owner, attr, index=0, text=text)
        return
    row = layout.row(align=True)
    for i in range(n):
        row.prop(owner, attr, index=i, text=text if i == 0 else "")


def draw_material(lay, context, mat):
    from .materials import scene_shader_registry
    p = mat.adm
    col = lay.column()
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(p, "alpha_mode")
    if p.alpha_mode in {"MASK", "AUTO"}:
        col.prop(p, "alpha_cutoff")
    col.prop(p, "occlusion_strength")
    lay.operator("adm.convert_materials", icon="MATERIAL")

    box = lay.box()
    box.label(text="Shader", icon="NODE_MATERIAL")
    col = box.column()
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(p, "shader")
    if p.shader != "CORE":
        col.label(text="SHADER_FALLBACK: portable PBR preview", icon="INFO")
    if p.shader == "CUSTOM":
        col.prop_search(p, "custom_shader", context.scene.adm_anim, "shaders", icon="SCRIPT")
    row = col.row(align=True)
    row.prop(p, "animation_id")
    row.operator("adm.material_auto_animation_id", icon="FILE_REFRESH", text="")
    if p.shader != "CORE" and not p.animation_id.strip():
        col.label(text="Shader materials need an Animation ID", icon="ERROR")

    registry = scene_shader_registry(context.scene)
    if p.shader == "LAYERED":
        r = col.row(align=True)
        r.prop(p, "layer_factor")
        r.operator("adm.material_key_param", icon="KEYFRAME", text="").name = "layer_factor"
        col.prop(p, "layer_mask")
        if p.layer_mask is not None:
            col.prop(p, "layer_mask_uv")
        col.prop(p, "layers_required")
        for label, rec in (("Base Layer", p.layer_base), ("Overlay Layer", p.layer_overlay)):
            hdr, body = box.panel(f"adm_mat_{label.split()[0].lower()}", default_closed=label != "Base Layer")
            hdr.label(text=label)
            if body is not None:
                b = body.column()
                b.use_property_split = True
                for k in ("base_color", "metallic", "roughness", "emissive", "use_normal_factor"):
                    b.prop(rec, k)
                if rec.use_normal_factor:
                    b.prop(rec, "normal_factor")
        box.operator("adm.material_layers_from_pbr", icon="IMPORT")
    elif p.shader == "CUSTOM":
        params = registry.get(p.shader_key())
        if params is None:
            col.label(text="Pick a shader definition (ADM > Shaders)", icon="ERROR")
        else:
            box.operator("adm.material_sync_params", icon="FILE_REFRESH")
            for v in p.params:
                prm = params.get(v.name)
                if prm is None:
                    continue
                typ = prm.get("type")
                r = box.row(align=True)
                r.prop(v, "use", text="")
                sub = r.row(align=True)
                sub.active = v.use
                sub.label(text=v.name)
                if typ == "F32":
                    sub.prop(v, "value_f", text="")
                elif typ in ("VEC2", "VEC3", "VEC4"):
                    _vec_prop(sub, v, "value_vec", K.SHADER_NUMERIC_DIMS[typ])
                elif typ == "BOOL":
                    sub.prop(v, "value_bool", text="")
                else:
                    sub.template_ID(v, "image", open="image.open")
                    sub.prop(v, "tex_coord", text="UV")
                if prm.get("animatable"):
                    r.operator("adm.material_key_param", icon="KEYFRAME", text="").name = v.name

    clip = _active_clip(context)
    box = lay.box()
    box.label(text="Material Animation", icon="ACTION")
    if clip is None or clip.action is None:
        box.label(text="Select a clip in ADM > Animation Libraries", icon="INFO")
        return
    from .material_anim import material_slots
    ms, ns = material_slots(clip.action, mat)
    linked = ms is not None or ns is not None
    box.label(text=f"Clip '{clip.clip_id}': {'linked' if linked else 'not linked'}",
              icon="LINKED" if linked else "UNLINKED")
    row = box.row(align=True)
    row.operator("adm.material_link_clip", icon="LINKED", text="Link / Bind" if not linked else "Rebind")
    if linked:
        row.operator("adm.material_link_clip", icon="UNLINKED", text="Unlink").unlink = True
        box.label(text="Key BSDF factors → pbrParameter, ADM params → shaderParameter")


class ADM_PT_shaders(_Side, bpy.types.Panel):
    bl_label = "Shaders"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(icon="NODE_MATERIAL")

    def draw(self, context):
        lay = self.layout
        ob = context.object
        mat = ob.active_material if ob is not None else None
        if mat is not None:
            hdr, body = lay.panel("adm_side_material", default_closed=False)
            hdr.label(text=f"Material: {mat.name}", icon="MATERIAL")
            if body is not None:
                draw_material(body, context, mat)
        hdr, body = lay.panel("adm_side_shader_defs", default_closed=True)
        s = context.scene.adm_anim
        hdr.label(text=f"Custom Shader Definitions ({len(s.shaders)})", icon="SCRIPT")
        if body is None:
            return
        row = body.row()
        row.template_list("ADM_UL_shader_defs", "", s, "shaders", s, "active_shader", rows=2)
        _list_buttons(row, "scene", "shaders", "active_shader")
        if not 0 <= s.active_shader < len(s.shaders):
            return
        sd = s.shaders[s.active_shader]
        col = body.column()
        col.use_property_split = True
        col.use_property_decorate = False
        for k in ("shader_id", "version", "description", "author"):
            col.prop(sd, k)
        if sd.shader_id.startswith("adm."):
            col.label(text="'adm.*' ids are reserved for official shaders", icon="ERROR")
        row = body.row()
        row.template_list("ADM_UL_shader_params", "", sd, "params", sd, "active_param", rows=3)
        _list_buttons(row, "shader", "params", "active_param", move=True)
        if 0 <= sd.active_param < len(sd.params):
            prm = sd.params[sd.active_param]
            col = body.column()
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(prm, "name")
            col.prop(prm, "type")
            col.prop(prm, "description")
            if prm.type in K.SHADER_NUMERIC_DIMS:
                n = K.SHADER_NUMERIC_DIMS[prm.type]
                _vec_prop(col, prm, "default_vec", n, "Default")
                col.prop(prm, "animatable")
                for use, attr in (("use_minimum", "minimum"), ("use_maximum", "maximum")):
                    r = col.row(align=True)
                    r.prop(prm, use)
                    sub = r.row(align=True)
                    sub.enabled = getattr(prm, use)
                    _vec_prop(sub, prm, attr, n)
            elif prm.type == "BOOL":
                col.prop(prm, "default_bool")
            else:
                col.template_ID(prm, "default_image", open="image.open")
                col.prop(prm, "default_tex_coord")


# ==================================================================================================
# Add menu
# ==================================================================================================
class ADM_MT_add(bpy.types.Menu):
    bl_idname = "ADM_MT_add"
    bl_label = "ADM"

    def draw(self, context):
        lay = self.layout
        lay.operator("adm.create_model_root", icon="OUTLINER_OB_EMPTY")
        lay.operator("adm.create_scene", icon="SCENE_DATA")
        lay.separator()
        for shape, label, icon in (("BOX", "Box Collider", "MESH_CUBE"), ("SPHERE", "Sphere Collider", "MESH_UVSPHERE"),
                                   ("CAPSULE", "Capsule Collider", "MESH_CAPSULE")):
            op = lay.operator("adm.create_collider", text=label, icon=icon)
            op.shape, op.fit = shape, False
        lay.separator()
        lay.operator("adm.create_lod_group", icon="MOD_DECIM")
        lay.operator("adm.create_attachment", icon="EMPTY_ARROWS")


def menu_add(self, context):
    self.layout.menu(ADM_MT_add.bl_idname, icon="MOD_BUILD")


SIDEBAR_PANELS = (ADM_PT_tools, ADM_PT_object, ADM_PT_skeleton, ADM_PT_ik, ADM_PT_face, ADM_PT_expressions,
                  ADM_PT_shaders, ADM_PT_animation, ADM_PT_validation)

CLASSES = (
    ADM_UL_lod_levels, ADM_UL_face_bindings, ADM_UL_expressions, ADM_UL_expression_bindings, ADM_UL_ik_chains,
    ADM_UL_bone_roles, ADM_UL_libraries, ADM_UL_clips, ADM_UL_events, ADM_UL_report,
    ADM_UL_shader_defs, ADM_UL_shader_params,
    *SIDEBAR_PANELS,
    ADM_PT_object_properties, ADM_PT_bone_properties, ADM_PT_armature_properties, ADM_PT_material_properties,
    ADM_MT_add,
)


def set_sidebar_category(name):
    children = [c for c in SIDEBAR_PANELS if getattr(c, "bl_parent_id", None)]
    parents = [c for c in SIDEBAR_PANELS if not getattr(c, "bl_parent_id", None)]
    for cls in children + parents:
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for cls in parents + children:
        cls.bl_category = name or "ADM"
        bpy.utils.register_class(cls)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_add.append(menu_add)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_add)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
