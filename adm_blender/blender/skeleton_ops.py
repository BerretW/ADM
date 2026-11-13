"""Operators of the 'ADM Skeleton & Animation' panel: profile detection, rig validation with fixes,
normalized reference corrections, IK chain authoring / preview, profile sockets, skin checks and
animation library compatibility tests."""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from ..core import skeleton as SK
from ..core import skeleton_profiles as SP
from ..core.validate import validate_anim
from . import rig as R
from .operators import active_armature

SEVERITY_ORDER = {SK.ERROR: 0, SK.WARNING: 1, SK.INFO: 2}


def fill_rig_report(context, arm, issues=None):
    wm = context.window_manager.adm
    issues = R.analyze(arm) if issues is None else issues
    issues = sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 3), i.code, i.role, i.bone))
    wm.rig_report.clear()
    for i in issues:
        it = wm.rig_report.add()
        it.severity, it.code, it.message = i.severity, i.code, i.message
        it.bone, it.role, it.fix = i.bone, i.role, i.fix
    errors = sum(1 for i in issues if i.severity == SK.ERROR)
    warnings = sum(1 for i in issues if i.severity == SK.WARNING)
    pid = arm.data.adm.profile_id.strip()
    state = "INVALID" if errors else "VALID"
    wm.rig_report_title = f"{arm.name} [{pid}]: {state}, {errors} error(s), {warnings} warning(s)"
    wm.active_rig_issue = 0
    return issues, errors, warnings


class _ArmOp:
    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None


class ADM_OT_detect_profile(_ArmOp, bpy.types.Operator):
    """Detect the skeleton profile from hierarchy, bone names and proportions, then map roles"""
    bl_idname = "adm.detect_profile"
    bl_label = "Detect Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    map_roles: BoolProperty(name="Map Roles", default=True)
    overwrite: BoolProperty(name="Overwrite Existing Roles", default=False)

    def execute(self, context):
        arm = active_armature(context)
        pid, mapping, reason = R.detect(arm)
        sk = arm.data.adm
        sk.profile = pid
        n = R.apply_mapping(arm, mapping, self.overwrite) if self.map_roles else 0
        sk.export_profile = pid != SP.GENERIC
        fill_rig_report(context, arm)
        note = " (PROVISIONAL profile)" if SP.status(pid) == SP.PROVISIONAL else ""
        self.report({"INFO"}, f"detected {pid}{note}: {reason}; mapped {n} bone(s) - review the mapping")
        return {"FINISHED"}


class ADM_OT_validate_rig(_ArmOp, bpy.types.Operator):
    """Validate the active rig against its ADM skeleton profile (roles, hierarchy, reference pose, IK,
    corrections, constraints, skinning)"""
    bl_idname = "adm.validate_rig"
    bl_label = "Validate ADM Rig"

    def execute(self, context):
        arm = active_armature(context)
        _issues, errors, warnings = fill_rig_report(context, arm)
        if errors:
            self.report({"ERROR"}, f"rig INVALID: {errors} error(s), {warnings} warning(s)")
        else:
            self.report({"INFO"}, f"rig VALID ({warnings} warning(s))")
        return {"FINISHED"}


class ADM_OT_rig_fix(_ArmOp, bpy.types.Operator):
    """Apply the unambiguous automatic fix offered for a rig issue"""
    bl_idname = "adm.rig_fix"
    bl_label = "Apply Fix"
    bl_options = {"REGISTER", "UNDO"}

    fix: StringProperty()
    role: StringProperty()
    bone: StringProperty()

    def execute(self, context):
        arm = active_armature(context)
        msg = R.apply_fix(context, arm, self.fix, self.role, self.bone)
        if not msg:
            self.report({"WARNING"}, f"no automatic fix for {self.fix!r}")
            return {"CANCELLED"}
        fill_rig_report(context, arm)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class ADM_OT_select_issue(_ArmOp, bpy.types.Operator):
    """Select the bone (or object) named by a rig issue"""
    bl_idname = "adm.select_issue"
    bl_label = "Select"
    bl_options = {"REGISTER", "UNDO"}

    bone: StringProperty()

    def execute(self, context):
        arm = active_armature(context)
        if self.bone in arm.data.bones:
            arm.data.bones.active = arm.data.bones[self.bone]
            for b in arm.data.bones:
                b.select = b.name == self.bone
            return {"FINISHED"}
        obj = bpy.data.objects.get(self.bone)
        if obj is not None and obj.name in context.view_layer.objects and context.mode == "OBJECT":
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            return {"FINISHED"}
        return {"CANCELLED"}


def _role_items(self, context):
    arm = active_armature(context)
    pid = arm.data.adm.profile_id.strip() if arm else ""
    items = [("__CLEAR__", "(clear role)", "")]
    roles = SP.roles(pid) or {}
    for i, r in enumerate(sorted(roles)):
        d = roles[r]
        items.append((r, r + (" *" if d["required"] else ""), d.get("description", "") or
                      ("required" if d["required"] else "optional")))
    _role_items.cache = items  # keep python strings alive (Blender enum callback requirement)
    return items


class ADM_OT_set_bone_role(_ArmOp, bpy.types.Operator):
    """Assign a semantic role of the active profile to a bone (searchable, * = required)"""
    bl_idname = "adm.set_bone_role"
    bl_label = "Set Role"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "role"

    bone: StringProperty()
    role: EnumProperty(name="Role", items=_role_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        arm = active_armature(context)
        name = self.bone or (arm.data.bones.active.name if arm.data.bones.active else "")
        if name not in arm.data.bones:
            return {"CANCELLED"}
        role = "" if self.role == "__CLEAR__" else self.role
        if role:
            for b in arm.data.bones:
                if b.name != name and b.adm.role == role:
                    self.report({"ERROR"}, f"role '{role}' is already assigned to '{b.name}' (roles are unique)")
                    return {"CANCELLED"}
        arm.data.bones[name].adm.role = role
        return {"FINISHED"}


class ADM_OT_normalize_corrections(_ArmOp, bpy.types.Operator):
    """Store normalized reference corrections (inverse rest rotation in model space) on all mapped bones so
    SEMANTIC clips retarget between rigs with different bone rolls/proportions"""
    bl_idname = "adm.normalize_corrections"
    bl_label = "Normalize Corrections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = active_armature(context)
        n = R.apply_normalized_corrections(arm)
        self.report({"INFO"}, f"normalized corrections on {n} mapped bone(s)")
        return {"FINISHED"}


class ADM_OT_clear_corrections(_ArmOp, bpy.types.Operator):
    """Remove all reference corrections (identity)"""
    bl_idname = "adm.clear_corrections"
    bl_label = "Clear Corrections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for b in active_armature(context).data.bones:
            b.adm.use_reference_correction = False
            b.adm.reference_correction = (1.0, 0.0, 0.0, 0.0)
        return {"FINISHED"}


class ADM_OT_ik_from_profile(_ArmOp, bpy.types.Operator):
    """Create the profile's two-bone IK chains (ADM-IK-1) from the role mapping"""
    bl_idname = "adm.ik_from_profile"
    bl_label = "Chains From Profile"
    bl_options = {"REGISTER", "UNDO"}

    replace: BoolProperty(name="Replace Existing", default=False)

    def execute(self, context):
        arm = active_armature(context)
        added, skipped = R.add_chains_from_profile(arm, self.replace)
        if skipped:
            self.report({"WARNING"}, f"added {', '.join(added) or 'none'}; skipped (roles not mapped): "
                                     f"{', '.join(skipped)}")
        else:
            self.report({"INFO"}, f"added {', '.join(added) or 'none (already present)'}")
        return {"FINISHED"}


class ADM_OT_ik_from_constraints(_ArmOp, bpy.types.Operator):
    """Convert two-bone Blender IK constraints to ADM IK chains (unsupported settings are reported)"""
    bl_idname = "adm.ik_from_constraints"
    bl_label = "From Blender IK"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = active_armature(context)
        created, notes = R.chains_from_blender_ik(arm)
        for n in notes:
            self.report({"WARNING"}, n)
        self.report({"INFO"}, f"created {len(created)} chain(s): {', '.join(created)}")
        return {"FINISHED"}


class ADM_OT_ik_add_target(_ArmOp, bpy.types.Operator):
    """Create preview target empties for IK chains (editor only, never exported)"""
    bl_idname = "adm.ik_add_target"
    bl_label = "Add Preview Targets"
    bl_options = {"REGISTER", "UNDO"}

    all_chains: BoolProperty(name="All Chains", default=True)

    def execute(self, context):
        arm = active_armature(context)
        sk = arm.data.adm
        chains = list(sk.ik_chains) if self.all_chains else \
            [sk.ik_chains[sk.active_ik_chain]] if 0 <= sk.active_ik_chain < len(sk.ik_chains) else []
        for c in chains:
            R.ensure_preview_target(context, arm, c)
        return {"FINISHED"}


class ADM_OT_ik_preview(_ArmOp, bpy.types.Operator):
    """Solve the chains with the ADM-IK-1 reference solver (§20) toward their preview targets"""
    bl_idname = "adm.ik_preview"
    bl_label = "Preview IK"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = active_armature(context)
        if context.mode != "POSE" and context.mode != "OBJECT":
            self.report({"WARNING"}, "use Object or Pose mode")
            return {"CANCELLED"}
        res = R.preview_ik(context, arm)
        if not res:
            self.report({"WARNING"}, "no chain has a preview target")
            return {"CANCELLED"}
        txt = ", ".join(f"{cid}: {st}" + (f" ({err * 1000:.1f} mm)" if err == err else "") for cid, st, err in res)
        self.report({"INFO"}, txt)
        return {"FINISHED"}


class ADM_OT_ik_reset(_ArmOp, bpy.types.Operator):
    """Reset the root/mid bones of all IK chains to the rest pose"""
    bl_idname = "adm.ik_reset"
    bl_label = "Reset Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        R.reset_chain_pose(active_armature(context))
        return {"FINISHED"}


class ADM_OT_create_profile_sockets(_ArmOp, bpy.types.Operator):
    """Create the profile's attachment sockets (hand.left, hand.right, head, ...) on mapped role bones"""
    bl_idname = "adm.create_profile_sockets"
    bl_label = "Create Profile Sockets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "switch to Object Mode")
            return {"CANCELLED"}
        created, skipped = R.create_profile_sockets(context, active_armature(context))
        self.report({"WARNING"} if skipped and not created else {"INFO"},
                    f"created {', '.join(created) or 'none'}" + (f"; skipped {', '.join(skipped)}" if skipped else ""))
        return {"FINISHED"}


class ADM_OT_skin_fix(_ArmOp, bpy.types.Operator):
    """Limit every skinned vertex to 4 influences and normalize weights (exact export result, no surprises)"""
    bl_idname = "adm.skin_fix"
    bl_label = "Limit & Normalize Weights"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = active_armature(context)
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "switch to Object Mode")
            return {"CANCELLED"}
        n = sum(R.limit_and_normalize_weights(o, arm) for o in R.skinned_meshes(arm))
        self.report({"INFO"}, f"updated {n} vertices")
        return {"FINISHED"}


class ADM_OT_anim_compat_test(_ArmOp, bpy.types.Operator, ImportHelper):
    """Check whether an .adm_anim library can bind to the active rig (EXACT / SEMANTIC / INCOMPATIBLE)
    without importing it"""
    bl_idname = "adm.anim_compat_test"
    bl_label = "Test Animation Compatibility"

    filename_ext = ".adm_anim"
    filter_glob: StringProperty(default="*.adm_anim", options={"HIDDEN"})

    def execute(self, context):
        from .import_anim import check_library_compat, library_channel_roles
        arm = active_armature(context)
        wm = context.window_manager.adm
        wm.compat_report.clear()
        name = os.path.basename(self.filepath)
        try:
            with open(self.filepath, "rb") as fh:
                rep = validate_anim(fh.read())
        except OSError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not rep.ok:
            wm.compat_title = f"{name}: INVALID library ({len(rep.errors)} errors)"
            for i in rep.errors[:50]:
                it = wm.compat_report.add()
                it.severity, it.code, it.path, it.message = "ERROR", i.code, i.path, i.message
            self.report({"ERROR"}, wm.compat_title)
            return {"CANCELLED"}
        lib = rep.doc["library"]
        level, reasons, rig_warn = check_library_compat(context, arm, rep.doc)
        wm.compat_title = (f"{name} [{lib['id']}] -> {arm.name}: {level} "
                           f"({lib['binding']}, {lib['targetProfile']})")
        sev = {SK.INCOMPATIBLE: "ERROR", SK.PROVISIONAL_SEMANTIC: "WARNING"}.get(level, "INFO")
        for r in reasons:
            it = wm.compat_report.add()
            it.severity, it.code, it.message = sev, level, r
        for w in rig_warn:
            it = wm.compat_report.add()
            it.severity, it.code, it.message = "WARNING", "RIG", w
        roles = {b.adm.role for b in arm.data.bones if b.adm.role}
        for clip in rep.doc["clips"]:
            used = library_channel_roles({"clips": [clip]})
            missing = sorted(used - roles) if lib["binding"] == "SEMANTIC" else []
            it = wm.compat_report.add()
            it.severity = "WARNING" if missing else "INFO"
            it.code = "CLIP"
            it.path = clip["id"]
            it.message = (f"{lib['id']}:{clip['id']} '{clip['title']}' - {len(clip['channels'])} channel(s)"
                          + (f"; roles absent on rig: {', '.join(missing)}" if missing else ""))
        wm.active_compat = 0
        self.report({"ERROR"} if level == SK.INCOMPATIBLE else {"INFO"}, wm.compat_title)
        return {"FINISHED"}


CLASSES = (
    ADM_OT_detect_profile, ADM_OT_validate_rig, ADM_OT_rig_fix, ADM_OT_select_issue, ADM_OT_set_bone_role,
    ADM_OT_normalize_corrections, ADM_OT_clear_corrections, ADM_OT_ik_from_profile, ADM_OT_ik_from_constraints,
    ADM_OT_ik_add_target, ADM_OT_ik_preview, ADM_OT_ik_reset, ADM_OT_create_profile_sockets, ADM_OT_skin_fix,
    ADM_OT_anim_compat_test,
)
