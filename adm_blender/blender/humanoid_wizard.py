"""Guided orchestration of the existing ADM humanoid authoring tools."""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from mathutils import Matrix, Vector

from ..core import skeleton_profiles as SP
from . import convert as cv
from . import rig as R
from .export_adm import find_model_root
from .operators import active_armature, link_to_active_collection, make_active
from .colliders import new_collider_object

STEPS = (
    "Analyze Model", "Skeleton", "Position Skeleton", "Skinning", "Rig Test", "IK",
    "Hitboxes & Colliders", "Sockets", "Materials", "Face & Morphs", "LOD",
    "Animation Compatibility", "Validate & Export",
)
POSE_BACKUP_KEY = "adm_hw_pose_backup"
TEST_POSES = {
    "RAISE_ARMS": {"leftUpperArm": ("Y", 1.0), "rightUpperArm": ("Y", -1.0)},
    "BEND_ELBOWS": {"leftLowerArm": ("Y", 0.8), "rightLowerArm": ("Y", -0.8)},
    "ROTATE_WRISTS": {"leftHand": ("X", 0.5), "rightHand": ("X", -0.5)},
    "BEND_KNEES": {"leftLowerLeg": ("X", -0.65), "rightLowerLeg": ("X", -0.65)},
    "HIP_ROTATION": {"hips": ("Z", 0.35)},
    "SPINE_BEND": {"spine": ("X", 0.2), "chest": ("X", 0.15)},
    "HEAD_ROTATION": {"head": ("Z", 0.35)},
    "SHOULDER_MOVEMENT": {"leftShoulder": ("Y", 0.25), "rightShoulder": ("Y", -0.25)},
}


def _test_pose_changes(arm, pose):
    changes = dict(TEST_POSES.get(pose, {}))
    if pose == "FINGER_CURL":
        for bone in arm.data.bones:
            role = bone.adm.role
            if role.endswith(("Proximal", "Intermediate")) and any(
                    finger in role for finger in ("Thumb", "Index", "Middle", "Ring", "Little")):
                changes[role] = ("Y", 0.35 if role.startswith("right") else -0.35)
    elif pose == "FULL_BODY":
        for name, mapping in TEST_POSES.items():
            if name in {"RAISE_ARMS", "BEND_ELBOWS", "BEND_KNEES", "SPINE_BEND", "HEAD_ROTATION"}:
                changes.update(mapping)
    return changes


def _save_test_pose(arm):
    snapshot = {}
    for bone in arm.pose.bones:
        snapshot[bone.name] = {
            "mode": bone.rotation_mode,
            "location": list(bone.location),
            "euler": list(bone.rotation_euler),
            "quaternion": list(bone.rotation_quaternion),
            "axis_angle": list(bone.rotation_axis_angle),
            "scale": list(bone.scale),
        }
    arm[POSE_BACKUP_KEY] = json.dumps(snapshot, separators=(",", ":"))


def _restore_test_pose(arm):
    if POSE_BACKUP_KEY not in arm:
        return False
    snapshot = json.loads(arm[POSE_BACKUP_KEY])
    for name, values in snapshot.items():
        bone = arm.pose.bones.get(name)
        if bone is None:
            continue
        bone.rotation_mode = values["mode"]
        bone.location = values["location"]
        bone.rotation_euler = values["euler"]
        bone.rotation_quaternion = values["quaternion"]
        bone.rotation_axis_angle = values["axis_angle"]
        bone.scale = values["scale"]
    del arm[POSE_BACKUP_KEY]
    return True


def _scope(context, state):
    root = state.model_root
    active = context.active_object
    if root is None and active is not None:
        root = find_model_root(active)
        if active.adm.adm_type == "MODEL":
            root = active

    objects = []
    if root is not None:
        stack = [root]
        while stack:
            obj = stack.pop()
            objects.append(obj)
            stack.extend(obj.children)
    else:
        objects.extend(context.selected_objects)
        if active is not None and active not in objects:
            objects.append(active)

    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    for obj in tuple(objects):
        if obj.type == "MESH":
            armatures.extend(mod.object for mod in obj.modifiers
                             if mod.type == "ARMATURE" and mod.object is not None)
    chosen = state.armature if state.armature in armatures else None
    if chosen is None:
        chosen = next((obj for obj in armatures if obj == active), armatures[0] if armatures else None)
    if chosen is not None and chosen not in objects:
        objects.append(chosen)
    if not objects and active is not None:
        objects.append(active)
    return root, objects, chosen


def _mesh_objects(objects):
    return [obj for obj in objects if obj.type == "MESH" and obj.adm.adm_type != "COLLIDER"]


def _invalid_humanoid_roles(arm):
    valid = set(SP.roles(SP.HUMANOID))
    return [(bone, bone.adm.role.strip()) for bone in arm.data.bones
            if bone.adm.role.strip() and bone.adm.role.strip() not in valid]


def _set_humanoid_profile(arm, repair_invalid):
    invalid = _invalid_humanoid_roles(arm)
    if invalid and not repair_invalid:
        return None
    for bone, _role in invalid:
        bone.adm.role = ""
    arm.data.adm.profile = SP.HUMANOID
    arm.data.adm.export_profile = True
    mapped = R.auto_map_profile(arm, overwrite=False, profile_id=SP.HUMANOID)
    return len(invalid), mapped


def _add_missing_eye_bones(context, arm):
    role_bones = {bone.adm.role: bone for bone in arm.data.bones if bone.adm.role}
    missing = [role for role in ("leftEye", "rightEye") if role not in role_bones]
    if not missing:
        return [], None
    head = role_bones.get("head")
    if head is None:
        return [], "the head role is not mapped"

    hips = role_bones.get("hips")
    up = head.head_local - hips.head_local if hips else head.tail_local - head.head_local
    if up.length <= 1e-8:
        up = Vector((0.0, 0.0, 1.0))
    else:
        up.normalize()

    left = role_bones.get("leftUpperArm") or role_bones.get("leftShoulder")
    right = role_bones.get("rightUpperArm") or role_bones.get("rightShoulder")
    if left is not None and right is not None:
        side = right.head_local - left.head_local
        side -= up * side.dot(up)
    else:
        side = Vector((1.0, 0.0, 0.0)) - up * up.x
    if side.length <= 1e-8:
        side = Vector((1.0, 0.0, 0.0))
        side -= up * side.dot(up)
    side.normalize()
    forward = up.cross(side).normalized()

    head_length = max(head.length, 0.01)
    shoulder_width = ((right.head_local - left.head_local).length
                      if left is not None and right is not None else head_length * 0.7)
    center = head.head_local.lerp(head.tail_local, 0.6) + forward * max(head_length * 0.15, 0.01)
    eye_spacing = max(shoulder_width * 0.08, head_length * 0.12)
    eye_length = max(head_length * 0.12, 0.01)
    positions = {
        "leftEye": center - side * eye_spacing * 0.5,
        "rightEye": center + side * eye_spacing * 0.5,
    }

    previous_active = context.view_layer.objects.active
    previous_selection = list(context.selected_objects)
    previous_mode = arm.mode
    if previous_mode != "OBJECT":
        if previous_active != arm:
            return [], "switch the armature to Object Mode first"
        bpy.ops.object.mode_set(mode="OBJECT")
    created = {}
    try:
        make_active(context, arm)
        bpy.ops.object.mode_set(mode="EDIT")
        for role in missing:
            eye = arm.data.edit_bones.new("ADM_" + role)
            eye.head = positions[role]
            eye.tail = positions[role] + forward * eye_length
            eye.parent = arm.data.edit_bones.get(head.name)
            eye.use_deform = False
            created[role] = eye.name
        bpy.ops.object.mode_set(mode="OBJECT")
        for role, name in created.items():
            arm.data.bones[name].adm.role = role
    finally:
        if arm.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in previous_selection:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        context.view_layer.objects.active = previous_active
        if previous_active == arm and previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=previous_mode)
    return list(created), None


def _analysis(context, state):
    root, objects, arm = _scope(context, state)
    meshes = _mesh_objects(objects)
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    for obj in meshes:
        armatures.extend(mod.object for mod in obj.modifiers
                         if mod.type == "ARMATURE" and mod.object is not None
                         and mod.object not in armatures)
    if arm is not None:
        state.armature = arm
    if root is not None:
        state.model_root = root
    required = set(SP.required_roles(SP.HUMANOID))
    mapped = {bone.adm.role for bone in arm.data.bones if bone.adm.role} if arm else set()
    skinned = [mesh for mesh in meshes if arm and any(
        mod.type == "ARMATURE" and mod.object == arm for mod in mesh.modifiers)]
    if arm is None:
        detected = "UNRIGGED"
    elif required.issubset(mapped) and skinned:
        detected = "RIGGED"
    else:
        detected = "PARTIAL"
    state.detected_mode = detected
    if state.mode == "AUTO":
        state.mode = detected

    materials = {slot.material for mesh in meshes for slot in mesh.material_slots if slot.material}
    images = set()
    for material in materials:
        if material.use_nodes and material.node_tree:
            images.update(node.image for node in material.node_tree.nodes
                          if node.type == "TEX_IMAGE" and node.image)
    shape_keys = sum(max(0, len(mesh.data.shape_keys.key_blocks) - 1)
                     for mesh in meshes if mesh.data.shape_keys)
    uv_maps = sum(len(mesh.data.uv_layers) for mesh in meshes)
    vertex_groups = sum(len(mesh.vertex_groups) for mesh in meshes)
    modifier_names = sorted({mod.name for obj in objects for mod in obj.modifiers})
    action_names = set()
    nla_tracks = 0
    for obj in objects:
        animation = obj.animation_data
        if animation:
            if animation.action:
                action_names.add(animation.action.name)
            nla_tracks += sum(len(track.strips) for track in animation.nla_tracks)
    if root is not None:
        transform = f"root location={tuple(round(v, 3) for v in root.location)}, " \
                    f"rotation={tuple(round(v, 3) for v in root.rotation_euler)}, " \
                    f"scale={tuple(round(v, 3) for v in root.scale)}"
        rig_metadata = (f"; rig profile={arm.data.adm.profile_id}, "
                        f"rigId={arm.data.adm.rig_id or '(not computed)'}" if arm else "; no armature metadata")
        metadata = f"ADM root; profiles={root.adm.model_profiles_json or '[]'}{rig_metadata}"
    elif arm is not None:
        transform = f"armature location={tuple(round(v, 3) for v in arm.location)}, " \
                    f"rotation={tuple(round(v, 3) for v in arm.rotation_euler)}, " \
                    f"scale={tuple(round(v, 3) for v in arm.scale)}"
        metadata = f"profile={arm.data.adm.profile_id}, rigId={arm.data.adm.rig_id or '(not computed)'}"
    else:
        obj = meshes[0] if meshes else (objects[0] if objects else None)
        transform = "no model transform" if obj is None else \
            f"active object location={tuple(round(v, 3) for v in obj.location)}, " \
            f"rotation={tuple(round(v, 3) for v in obj.rotation_euler)}, " \
            f"scale={tuple(round(v, 3) for v in obj.scale)}"
        metadata = "no ADM skeleton metadata"
    hierarchy = sum(1 for obj in objects if obj.parent is not None)
    lines = [
        f"Detected mode: {detected}",
        f"Model root: {root.name if root else '(not assigned)'}",
        f"Meshes: {len(meshes)} ({', '.join(obj.name for obj in meshes[:5]) or 'none'})",
        f"Armatures: {len(armatures)}; active: {arm.name if arm else 'none'}; skinned meshes: {len(skinned)}",
        f"Shape keys: {shape_keys}; materials: {len(materials)}; image textures: {len(images)}",
        f"UV maps: {uv_maps}; vertex groups: {vertex_groups}",
        f"Modifiers: {', '.join(modifier_names) or 'none'}",
        f"Actions: {', '.join(sorted(action_names)) or 'none'}; NLA strips: {nla_tracks}",
        f"Hierarchy links: {hierarchy}; {transform}",
        f"ADM metadata: {metadata}",
    ]
    state.analysis_report = "\n".join(lines)
    state.status = f"Analysis complete: {detected.lower()} model."
    return root, objects, arm, meshes


def _role_position(role):
    """Fixed neutral template coordinates in ADM space; never derived from mesh geometry."""
    torso = {
        "hips": (0.0, 0.92, 0.0), "spine": (0.0, 1.12, 0.0),
        "chest": (0.0, 1.36, 0.0), "upperChest": (0.0, 1.51, 0.0),
        "neck": (0.0, 1.66, 0.0), "head": (0.0, 1.82, 0.0),
        "jaw": (0.0, 1.76, -0.035), "leftEye": (-0.032, 1.84, -0.055),
        "rightEye": (0.032, 1.84, -0.055),
    }
    if role in torso:
        return torso[role]
    side = "left" if role.startswith("left") else "right"
    sign = -1.0 if side == "left" else 1.0
    suffix = role[len(side):]
    limb = {
        "Shoulder": (0.13, 1.51, 0.0), "UpperArm": (0.25, 1.50, 0.0),
        "LowerArm": (0.52, 1.50, 0.0), "Hand": (0.76, 1.50, 0.0),
        "UpperLeg": (0.12, 0.91, 0.0), "LowerLeg": (0.12, 0.49, 0.0),
        "Foot": (0.12, 0.10, -0.015), "Toes": (0.12, 0.075, -0.15),
    }
    for name, pos in limb.items():
        if suffix == name:
            return (sign * pos[0], pos[1], pos[2])
    finger_names = ("Index", "Middle", "Ring", "Little")
    for index, name in enumerate(finger_names):
        if suffix.startswith(name):
            segment = suffix[len(name):]
            depth = {"Proximal": 0.0, "Intermediate": 0.035, "Distal": 0.065}.get(segment, 0.0)
            z = (-0.035, -0.012, 0.012, 0.036)[index]
            return (sign * (0.80 + depth), 1.50 - (0.01 if index == 3 else 0.0), z)
    if suffix.startswith("Thumb"):
        segment = suffix[len("Thumb"):]
        offset = {"Metacarpal": 0.0, "Proximal": 0.035, "Distal": 0.065}.get(segment, 0.0)
        return (sign * (0.75 + offset), 1.45 - offset * 0.55, -0.045 - offset)
    return (0.0, 1.0, 0.0)


def _generate_skeleton(context, state):
    root, objects, arm, meshes = _analysis(context, state)
    if arm is not None:
        raise ValueError("An armature already exists; use Skeleton Mapping instead of generating another.")
    if not meshes:
        raise ValueError("Select or assign at least one mesh before generating a humanoid skeleton.")
    data = bpy.data.armatures.new("ADM_Humanoid")
    obj = bpy.data.objects.new("ADM_Humanoid", data)
    link_to_active_collection(context, obj)
    if root is not None:
        obj.parent = root
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
    else:
        obj.location = meshes[0].matrix_world.translation
    previous_active = context.view_layer.objects.active
    previous_selection = list(context.selected_objects)
    try:
        for selected in previous_selection:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        role_defs = SP.roles(SP.HUMANOID)
        edit_bones = {}
        positions = {role: cv.vec_from_adm(_role_position(role)) for role in role_defs}
        children = {role: [] for role in role_defs}
        for role, definition in role_defs.items():
            parent_role = definition["parent"]
            if parent_role:
                children[parent_role].append(role)
        for role in role_defs:
            edit_bone = data.edit_bones.new(role)
            edit_bone.head = positions[role]
            candidates = children[role]
            preferred = {
                "hips": "spine", "spine": "chest", "chest": "upperChest",
                "upperChest": "neck", "neck": "head", "head": "jaw",
                "leftHand": "leftMiddleProximal", "rightHand": "rightMiddleProximal",
            }.get(role)
            child = next((candidate for candidate in candidates if candidate == preferred), None)
            if child is None and candidates:
                child = max(candidates, key=lambda candidate: (positions[candidate] - positions[role]).length)
            if child:
                edit_bone.tail = positions[child]
            else:
                direction = Vector((0.0, 0.04, 0.0))
                if role.endswith(("Toes", "Distal")) or role in {"leftEye", "rightEye", "jaw"}:
                    direction = Vector((0.0, 0.0, -0.04))
                elif role.startswith(("left", "right")) and "Hand" not in role:
                    direction.x = -0.04 if role.startswith("left") else 0.04
                edit_bone.tail = edit_bone.head + direction
            edit_bone.use_deform = True
            edit_bones[role] = edit_bone
        for role, definition in role_defs.items():
            if definition["parent"]:
                edit_bones[role].parent = edit_bones[definition["parent"]]
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.armatures.remove(data)
        raise
    for bone in data.bones:
        bone.adm.role = bone.name
    data.adm.profile = SP.HUMANOID
    data.adm.export_profile = True
    obj.show_in_front = True
    data.use_mirror_x = True
    state.armature = obj
    state.status = "Template skeleton created. Position it in Edit Mode; no mesh anatomy was inferred."
    make_active(context, obj)
    return obj


def _generate_hitboxes(context, root, arm):
    if root is None:
        raise ValueError("Assign or create an ADM Model Root before generating hitboxes.")
    role_bones = R.role_bone_map(arm)
    definitions = [
        ("head", "head", "SPHERE", 0.12),
        ("neck", "neck", "CAPSULE", 0.07),
        ("chest", "chest", "CAPSULE", 0.17),
        ("abdomen", "spine", "CAPSULE", 0.13),
        ("pelvis", "hips", "CAPSULE", 0.16),
    ]
    for side in ("left", "right"):
        definitions.extend([
            (f"{side}_upper_arm", side + "UpperArm", "CAPSULE", 0.065),
            (f"{side}_forearm", side + "LowerArm", "CAPSULE", 0.05),
            (f"{side}_hand", side + "Hand", "SPHERE", 0.07),
            (f"{side}_thigh", side + "UpperLeg", "CAPSULE", 0.11),
            (f"{side}_calf", side + "LowerLeg", "CAPSULE", 0.08),
            (f"{side}_foot", side + "Foot", "CAPSULE", 0.09),
        ])
    existing = {item.name for item in root.adm.hitboxes}
    created, skipped = [], []
    for ident, role, shape, radius in definitions:
        if ident in existing:
            skipped.append(ident)
            continue
        bone_name = role_bones.get(role)
        if bone_name is None:
            skipped.append(f"{ident} (role {role} not mapped)")
            continue
        bone = arm.data.bones[bone_name]
        head = arm.matrix_world @ bone.head_local
        tail = arm.matrix_world @ bone.tail_local
        segment = tail - head
        if segment.length <= 1e-8:
            skipped.append(f"{ident} (zero-length bone)")
            continue
        center = (head + tail) * 0.5
        rotation = Vector((0.0, 0.0, 1.0)).rotation_difference(segment.normalized())
        collider = new_collider_object(
            context, shape, "Hitbox_" + ident,
            radius=radius, height=max(segment.length + 2.0 * radius, 2.0 * radius))
        link_to_active_collection(context, collider)
        collider.parent = arm
        collider.parent_type = "BONE"
        collider.parent_bone = bone_name
        collider.matrix_parent_inverse = Matrix.Identity(4)
        context.view_layer.update()
        collider.matrix_world = Matrix.LocRotScale(center, rotation, Vector((1.0, 1.0, 1.0)))
        item = root.adm.hitboxes.add()
        item.name = ident
        item.collider = collider
        item.object = arm
        item.bone = bone_name
        item.role = role
        existing.add(ident)
        created.append(ident)
    return created, skipped


class ADM_OT_hw_analyze(bpy.types.Operator):
    bl_idname = "adm.hw_analyze"
    bl_label = "Analyze Model"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _analysis(context, context.scene.adm_humanoid_wizard)
        return {"FINISHED"}


class ADM_OT_hw_generate_skeleton(bpy.types.Operator):
    bl_idname = "adm.hw_generate_skeleton"
    bl_label = "Generate Humanoid Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        try:
            _generate_skeleton(context, state)
        except (RuntimeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            state.status = str(exc)
            return {"CANCELLED"}
        state.step = 2
        return {"FINISHED"}


class ADM_OT_hw_map_skeleton(bpy.types.Operator):
    bl_idname = "adm.hw_map_skeleton"
    bl_label = "Suggest Skeleton Mapping"
    bl_options = {"REGISTER", "UNDO"}

    repair_invalid: BoolProperty(
        name="Clear roles not valid for humanoid.vrm1", default=True,
        description="Clear stale roles from another profile, then suggest humanoid roles from bone names")

    def invoke(self, context, event):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm = _scope(context, state)
        if arm is not None and _invalid_humanoid_roles(arm):
            return context.window_manager.invoke_props_dialog(self, width=520)
        return self.execute(context)

    def draw(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm = _scope(context, state)
        if arm is not None:
            invalid = _invalid_humanoid_roles(arm)
            self.layout.label(text=f"{len(invalid)} existing role assignment(s) are invalid for humanoid.vrm1.")
            for bone, role in invalid[:12]:
                self.layout.label(text=f"{bone.name}: {role}")
        self.layout.prop(self, "repair_invalid")

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "No armature found.")
            return {"CANCELLED"}
        configured = _set_humanoid_profile(arm, self.repair_invalid)
        if configured is None:
            state.status = "Mapping cancelled; existing non-humanoid roles were preserved."
            self.report({"WARNING"}, state.status)
            return {"CANCELLED"}
        cleared, mapped = configured
        eye_roles, eye_issue = _add_missing_eye_bones(context, arm)
        state.status = (f"Cleared {cleared} role(s) from other profiles and suggested {mapped} humanoid "
                        "mapping(s). Review the result before export.")
        if eye_roles:
            state.status += " Added estimated non-deforming eye bones; adjust placement in Edit Mode."
        elif eye_issue:
            state.status += f" Eye bones were not added because {eye_issue}."
        self.report({"WARNING"} if eye_issue else {"INFO"}, state.status)
        return {"FINISHED"}


class ADM_OT_hw_enter_edit_mode(bpy.types.Operator):
    bl_idname = "adm.hw_enter_edit_mode"
    bl_label = "Position Skeleton"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = active_armature(context)
        if arm is None:
            self.report({"ERROR"}, "Select an armature first.")
            return {"CANCELLED"}
        make_active(context, arm)
        bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}


def _vertex_group_snapshot(mesh):
    groups = [{"name": group.name, "lock_weight": group.lock_weight, "weights": []}
              for group in mesh.vertex_groups]
    by_index = {group.index: groups[index] for index, group in enumerate(mesh.vertex_groups)}
    for vertex in mesh.data.vertices:
        for assignment in vertex.groups:
            by_index[assignment.group]["weights"].append((vertex.index, assignment.weight))
    return groups


def _restore_vertex_groups(mesh, snapshot):
    for group in list(mesh.vertex_groups):
        mesh.vertex_groups.remove(group)
    for item in snapshot:
        group = mesh.vertex_groups.new(name=item["name"])
        group.lock_weight = item["lock_weight"]
        for index, weight in item["weights"]:
            group.add([index], weight, "REPLACE")


def _object_parent_snapshot(mesh):
    return (mesh.parent, mesh.parent_type, mesh.parent_bone,
            mesh.matrix_parent_inverse.copy(), mesh.matrix_world.copy())


def _restore_object_parent(mesh, snapshot):
    mesh.parent, mesh.parent_type, mesh.parent_bone = snapshot[:3]
    mesh.matrix_parent_inverse = snapshot[3]
    mesh.matrix_world = snapshot[4]


def _adopt_existing_weights(mesh, arm):
    deform_names = {bone.name for bone in arm.data.bones if bone.use_deform}
    matching = deform_names.intersection(group.name for group in mesh.vertex_groups)
    if not matching:
        raise ValueError(f"{mesh.name}: no vertex-group name matches a deform bone on {arm.name}.")
    armature_modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
    if len(armature_modifiers) > 1:
        raise ValueError(f"{mesh.name}: has multiple armature modifiers; resolve them before adopting weights.")

    parent = _object_parent_snapshot(mesh)
    old_modifier = armature_modifiers[0] if armature_modifiers else None
    old_target = old_modifier.object if old_modifier else None
    old_vertex_groups = old_modifier.use_vertex_groups if old_modifier else None
    old_bone_envelopes = old_modifier.use_bone_envelopes if old_modifier else None
    modifier = old_modifier
    created_modifier = False
    try:
        if modifier is None:
            modifier = mesh.modifiers.new(name="ADM Armature", type="ARMATURE")
            created_modifier = True
        modifier.object = arm
        modifier.use_vertex_groups = True
        modifier.use_bone_envelopes = False
        world = mesh.matrix_world.copy()
        mesh.parent = arm
        mesh.parent_type = "OBJECT"
        mesh.parent_bone = ""
        mesh.matrix_parent_inverse = Matrix.Identity(4)
        mesh.matrix_world = world
    except Exception:
        if created_modifier and modifier in mesh.modifiers:
            mesh.modifiers.remove(modifier)
        elif old_modifier is not None:
            old_modifier.object = old_target
            old_modifier.use_vertex_groups = old_vertex_groups
            old_modifier.use_bone_envelopes = old_bone_envelopes
        _restore_object_parent(mesh, parent)
        raise
    ignored = sorted(group.name for group in mesh.vertex_groups if group.name not in deform_names)
    return ignored


def _auto_weight_mesh(context, mesh, arm, replace_existing):
    if not any(bone.use_deform for bone in arm.data.bones):
        raise ValueError(f"{mesh.name}: the selected armature has no deform bones.")
    groups = _vertex_group_snapshot(mesh) if replace_existing else None
    old_group_names = {group.name for group in mesh.vertex_groups}
    parent = _object_parent_snapshot(mesh)
    old_modifiers = {modifier.as_pointer() for modifier in mesh.modifiers}
    old_armature_modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
    old_modifier_settings = [
        (modifier, modifier.object, modifier.use_vertex_groups, modifier.use_bone_envelopes)
        for modifier in old_armature_modifiers
    ]
    try:
        if replace_existing:
            for group in list(mesh.vertex_groups):
                mesh.vertex_groups.remove(group)
        for selected in context.selected_objects:
            selected.select_set(False)
        mesh.select_set(True)
        arm.select_set(True)
        context.view_layer.objects.active = arm
        result = bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        generated = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"
                     and modifier.object == arm]
        if "FINISHED" not in result:
            raise RuntimeError("Blender Automatic Weights did not create an armature binding.")
        if not generated and replace_existing and old_armature_modifiers:
            generated = [old_armature_modifiers[0]]
        if not generated:
            raise RuntimeError("Blender Automatic Weights did not create an armature binding.")
        stats = R.skin_stats(mesh, arm)
        if replace_existing:
            keep = old_armature_modifiers[0] if old_armature_modifiers else generated[0]
            keep.object = arm
            keep.use_vertex_groups = True
            keep.use_bone_envelopes = False
            for modifier in list(mesh.modifiers):
                if modifier.type == "ARMATURE" and modifier != keep:
                    mesh.modifiers.remove(modifier)
        return stats
    except Exception:
        for modifier in list(mesh.modifiers):
            if modifier.as_pointer() not in old_modifiers:
                mesh.modifiers.remove(modifier)
        for modifier, target, use_vertex_groups, use_bone_envelopes in old_modifier_settings:
            if modifier in mesh.modifiers:
                modifier.object = target
                modifier.use_vertex_groups = use_vertex_groups
                modifier.use_bone_envelopes = use_bone_envelopes
        if groups is not None:
            _restore_vertex_groups(mesh, groups)
        else:
            for group in list(mesh.vertex_groups):
                if group.name not in old_group_names:
                    mesh.vertex_groups.remove(group)
        _restore_object_parent(mesh, parent)
        raise


class ADM_OT_hw_skinning(bpy.types.Operator):
    bl_idname = "adm.hw_skinning"
    bl_label = "Suggest Skinning"
    bl_options = {"REGISTER", "UNDO"}

    existing_action: EnumProperty(name="Meshes with Existing Data", items=[
        ("SKIP", "Skip", "Leave existing vertex groups and armature modifiers unchanged"),
        ("ADOPT", "Adopt Existing Weights", "Keep current weights and bind them to the selected armature"),
        ("REWEIGHT", "Delete and Recompute", "Delete existing vertex groups and generate Automatic Weights"),
    ], default="SKIP")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "existing_action")
        state = context.scene.adm_humanoid_wizard
        _root, objects, _arm = _scope(context, state)
        affected = [mesh for mesh in _mesh_objects(objects)
                    if mesh.vertex_groups or any(mod.type == "ARMATURE" for mod in mesh.modifiers)]
        if affected:
            box = layout.box()
            box.label(text=f"{len(affected)} mesh(es) already contain groups or armature modifiers:")
            for mesh in affected:
                armature_names = [mod.object.name if mod.object else "(unassigned)"
                                  for mod in mesh.modifiers if mod.type == "ARMATURE"]
                box.label(text=f"{mesh.name}: {len(mesh.vertex_groups)} group(s)"
                          + (f", armature modifier: {', '.join(armature_names)}" if armature_names else ""))
        if self.existing_action == "REWEIGHT":
            layout.label(text="This removes existing vertex groups before recalculating. Undo remains available.",
                         icon="ERROR")
        elif self.existing_action == "ADOPT":
            layout.label(text="Groups are kept; only groups matching deform-bone names can affect the mesh.",
                         icon="INFO")

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "Create or select an armature before suggesting skinning.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object Mode before suggesting skinning.")
            return {"CANCELLED"}
        weighted, adopted, skipped, failures = [], [], [], []
        for mesh in meshes:
            has_existing_data = bool(mesh.vertex_groups) or any(
                mod.type == "ARMATURE" for mod in mesh.modifiers)
            if has_existing_data and self.existing_action == "SKIP":
                skipped.append(mesh.name)
                continue
            try:
                if has_existing_data and self.existing_action == "ADOPT":
                    ignored_groups = _adopt_existing_weights(mesh, arm)
                    stats = R.skin_stats(mesh, arm)
                    adopted.append((mesh.name, stats, ignored_groups))
                    continue
                stats = _auto_weight_mesh(
                    context, mesh, arm, replace_existing=has_existing_data and
                    self.existing_action == "REWEIGHT")
                details = []
                if stats["unweighted"]:
                    details.append(f"{stats['unweighted']} unweighted vertices")
                if stats["over"]:
                    details.append(f"{stats['over']} vertices over the influence limit")
                if stats["unnormalized"]:
                    details.append(f"{stats['unnormalized']} vertices with unnormalized weights")
                weighted.append(mesh.name + (f" ({', '.join(details)})" if details else ""))
            except Exception as exc:
                failures.append(f"{mesh.name}: {exc}")
        if failures:
            state.status = "Some skinning actions failed; failed meshes were restored. " + "; ".join(failures)
            self.report({"WARNING"}, state.status)
        else:
            state.status = (f"Generated weights: {len(weighted)} mesh(es); adopted: {len(adopted)}; "
                            f"skipped: {len(skipped)}.")
            if weighted:
                state.status += " Review weights in Weight Paint."
            if adopted:
                state.status += " Adopted weights were not recalculated."
                unmatched = sorted({name for _mesh, _stats, names in adopted for name in names})
                if unmatched:
                    state.status += " Unused group names: " + ", ".join(unmatched[:8]) + "."
                for mesh_name, stats, _names in adopted:
                    issues = []
                    if stats["unweighted"]:
                        issues.append(f"{stats['unweighted']} unweighted vertices")
                    if stats["over"]:
                        issues.append(f"{stats['over']} over the influence limit")
                    if stats["unnormalized"]:
                        issues.append(f"{stats['unnormalized']} unnormalized")
                    if issues:
                        state.status += f" {mesh_name}: {', '.join(issues)}."
            if skipped:
                state.status += " Preserved: " + ", ".join(skipped) + "."
            self.report({"WARNING"} if skipped else {"INFO"}, state.status)
        for mesh in meshes:
            mesh.select_set(False)
        arm.select_set(True)
        context.view_layer.objects.active = arm
        return {"FINISHED"} if weighted or adopted or skipped or (not meshes and not failures) else {"CANCELLED"}


class ADM_OT_hw_generate_hitboxes(bpy.types.Operator):
    bl_idname = "adm.hw_generate_hitboxes"
    bl_label = "Generate Bone Hitboxes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "Select a mapped humanoid armature before generating hitboxes.")
            return {"CANCELLED"}
        try:
            created, skipped = _generate_hitboxes(context, root, arm)
        except ValueError as exc:
            state.status = str(exc)
            self.report({"ERROR"}, state.status)
            return {"CANCELLED"}
        state.status = (f"Generated {len(created)} bone hitbox(es); preserved {len(skipped)} existing or "
                        f"unavailable area(s). Review placement and dimensions before export.")
        self.report({"WARNING"} if skipped else {"INFO"}, state.status)
        return {"FINISHED"}


class ADM_OT_hw_create_sockets(bpy.types.Operator):
    bl_idname = "adm.hw_create_sockets"
    bl_label = "Create 20 Humanoid Sockets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None or arm.data.adm.profile_id != SP.HUMANOID:
            self.report({"ERROR"}, "Select an armature mapped to humanoid.vrm1 first.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object Mode before creating sockets.")
            return {"CANCELLED"}
        created, skipped = R.create_profile_sockets(context, arm, SP.HUMANOID_SOCKET_NAMES)
        state.status = (f"Created {len(created)} standard humanoid socket(s); skipped {len(skipped)}. "
                        "Place markers at the authored mount points.")
        self.report({"WARNING"} if skipped else {"INFO"}, state.status)
        return {"FINISHED"}


class ADM_OT_hw_validate(bpy.types.Operator):
    bl_idname = "adm.hw_validate"
    bl_label = "Validate Humanoid Rig"

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "No armature found.")
            return {"CANCELLED"}
        issues = R.analyze(arm)
        errors = sum(issue.severity == "ERROR" for issue in issues)
        warnings = sum(issue.severity == "WARNING" for issue in issues)
        details = [f"{issue.code} [{issue.role or issue.bone}]: {issue.message}" for issue in issues
                   if issue.severity in {"ERROR", "WARNING"}][:4]
        state.status = f"Rig validation: {errors} error(s), {warnings} warning(s)." + \
            ((" " + " | ".join(details)) if details else "")
        self.report({"ERROR"} if errors else {"WARNING"} if warnings else {"INFO"}, state.status)
        return {"FINISHED"}


class ADM_OT_hw_confirm_placement(bpy.types.Operator):
    bl_idname = "adm.hw_confirm_placement"
    bl_label = "Confirm Placement"

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "No armature found.")
            return {"CANCELLED"}
        errors = [issue for issue in R.analyze(arm) if issue.severity == "ERROR"]
        if errors:
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:3])
            state.status = "Placement not confirmed: " + summary
            self.report({"ERROR"}, state.status)
            return {"CANCELLED"}
        state.step = 3
        state.status = "Placement confirmed. The wizard will not move the skeleton automatically."
        self.report({"INFO"}, state.status)
        return {"FINISHED"}


class ADM_OT_hw_apply_test_pose(bpy.types.Operator):
    bl_idname = "adm.hw_apply_test_pose"
    bl_label = "Apply Test Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "No armature found.")
            return {"CANCELLED"}
        if POSE_BACKUP_KEY in arm:
            _restore_test_pose(arm)
        else:
            _save_test_pose(arm)
        role_bones = {bone.adm.role: arm.pose.bones.get(bone.name) for bone in arm.data.bones if bone.adm.role}
        changes = _test_pose_changes(arm, state.test_pose)
        applied = 0
        for role, (axis, angle) in changes.items():
            pose_bone = role_bones.get(role)
            if pose_bone is None:
                continue
            pose_bone.rotation_mode = "XYZ"
            rotation = pose_bone.rotation_euler.copy()
            rotation.rotate_axis(axis, angle)
            pose_bone.rotation_euler = rotation
            applied += 1
        if not applied:
            _restore_test_pose(arm)
            self.report({"ERROR"}, "This test pose has no mapped roles on the selected rig.")
            return {"CANCELLED"}
        state.status = f"Applied {state.test_pose.replace('_', ' ').lower()} test pose. Reset restores the prior pose."
        return {"FINISHED"}


class ADM_OT_hw_reset_test_pose(bpy.types.Operator):
    bl_idname = "adm.hw_reset_test_pose"
    bl_label = "Reset Test Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            self.report({"ERROR"}, "No armature found.")
            return {"CANCELLED"}
        if not _restore_test_pose(arm):
            self.report({"WARNING"}, "No saved test pose to reset.")
            return {"CANCELLED"}
        state.status = "Restored the original pose; the rest pose and animation actions were not edited."
        return {"FINISHED"}


class ADM_OT_hw_navigate(bpy.types.Operator):
    bl_idname = "adm.hw_navigate"
    bl_label = "Wizard Step"

    step: IntProperty(min=0, max=len(STEPS) - 1)

    def execute(self, context):
        context.scene.adm_humanoid_wizard.step = self.step
        return {"FINISHED"}


class ADM_PT_character(bpy.types.Panel):
    bl_label = "Character"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ADM"
    bl_order = 1

    def draw(self, context):
        self.layout.label(text="Character authoring tools", icon="ARMATURE_DATA")


class ADM_PT_humanoid_wizard(bpy.types.Panel):
    bl_label = "Humanoid Wizard"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ADM"
    bl_parent_id = "ADM_PT_character"

    def draw(self, context):
        layout = self.layout
        state = context.scene.adm_humanoid_wizard
        layout.prop(state, "model_root")
        layout.prop(state, "armature")
        layout.prop(state, "mode")
        row = layout.row(align=True)
        row.operator("adm.hw_analyze", icon="VIEWZOOM")
        row.operator("adm.hw_validate", icon="CHECKMARK")
        if state.detected_mode:
            layout.label(text=f"Detected: {state.detected_mode.replace('_', ' ').title()}")
        if state.analysis_report:
            box = layout.box()
            for line in state.analysis_report.splitlines():
                box.label(text=line)
        if state.status:
            layout.label(text=state.status, icon="INFO")
        layout.separator()
        for index, title in enumerate(STEPS):
            row = layout.row(align=True)
            button = row.operator("adm.hw_navigate", text=f"{index + 1}. {title}",
                                  depress=index == state.step)
            button.step = index
        layout.separator()
        step = state.step
        if step == 0:
            layout.operator("adm.hw_analyze", text="Analyze Model", icon="VIEWZOOM")
            layout.operator("adm.hw_auto_configure", text="Auto Configure Humanoid", icon="AUTOMERGE_ON")
        elif step == 1:
            if state.mode == "UNRIGGED":
                layout.operator("adm.hw_generate_skeleton", icon="ARMATURE_DATA")
            else:
                layout.operator("adm.hw_map_skeleton", icon="BONE_DATA")
            layout.label(text="Unmapped helper bones and existing weights are preserved.", icon="INFO")
        elif step == 2:
            layout.operator("adm.hw_enter_edit_mode", icon="EDITMODE_HLT")
            arm = state.armature or active_armature(context)
            if arm:
                layout.prop(arm, "show_in_front", text="Show Bones Through Mesh")
                layout.prop(arm.data, "use_mirror_x", text="Mirror Editing")
            layout.operator("adm.hw_validate", text="Validate Skeleton", icon="CHECKMARK")
            layout.operator("adm.hw_confirm_placement", icon="RIGHTARROW")
        elif step == 3:
            layout.operator("adm.hw_skinning", icon="MOD_VERTEX_WEIGHT")
            layout.label(text="Existing data can be skipped, adopted, or explicitly replaced.")
        elif step == 4:
            layout.prop(state, "test_pose")
            row = layout.row(align=True)
            row.operator("adm.hw_apply_test_pose", icon="PLAY")
            row.operator("adm.hw_reset_test_pose", icon="LOOP_BACK")
            layout.label(text="Review deformation visually; test poses do not edit rest pose or actions.")
        elif step == 5:
            layout.operator("adm.ik_from_profile", icon="CON_KINEMATIC")
            layout.operator("adm.ik_add_target", icon="EMPTY_AXIS")
            layout.operator("adm.ik_preview", icon="PLAY")
        elif step == 6:
            layout.operator("adm.hw_generate_hitboxes", icon="MESH_ICOSPHERE")
            layout.operator("adm.create_collider", icon="MESH_ICOSPHERE")
            layout.label(text="Hitboxes are independent geometry metadata; gameplay damage is not defined.")
        elif step == 7:
            layout.operator("adm.hw_create_sockets", icon="EMPTY_ARROWS")
            layout.operator("adm.align_socket_frames", icon="ORIENTATION_GLOBAL")
            layout.label(text="Socket placeholders start at role origins; place them at authored mount points.")
        elif step == 8:
            layout.operator("adm.convert_materials", icon="MATERIAL")
            layout.label(text="Review shader profiles and portable fallbacks in the Materials panels.")
        elif step == 9:
            layout.operator("adm.auto_bind_face", icon="SHAPEKEY_DATA")
            layout.label(text="ARKit bindings and expression setup are managed by the existing Face panels.")
        elif step == 10:
            layout.operator("adm.generate_lods", icon="MOD_DECIM")
            layout.label(text="LOD0 remains the source; review generated levels before export.")
        elif step == 11:
            layout.operator("adm.anim_compat_test", icon="LINKED")
            layout.operator("import_anim.adm_anim", icon="IMPORT")
        else:
            layout.operator("adm.hw_validate", text="Validate Humanoid Rig", icon="CHECKMARK")
            layout.operator("adm.validate_model", text="Validate Complete Model", icon="CHECKMARK")
            layout.operator("export_scene.adm", text="Export ADM", icon="EXPORT")


class ADM_OT_hw_auto_configure(bpy.types.Operator):
    bl_idname = "adm.hw_auto_configure"
    bl_label = "Auto Configure Humanoid"
    bl_options = {"REGISTER", "UNDO"}

    repair_invalid: BoolProperty(
        name="Clear roles not valid for humanoid.vrm1", default=True,
        description="Clear stale roles from another profile, then map bone names to humanoid roles")

    def invoke(self, context, event):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm = _scope(context, state)
        if arm is not None and _invalid_humanoid_roles(arm):
            return context.window_manager.invoke_props_dialog(self, width=520)
        return self.execute(context)

    def draw(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm = _scope(context, state)
        if arm is not None:
            invalid = _invalid_humanoid_roles(arm)
            self.layout.label(text=f"{len(invalid)} existing role assignment(s) are invalid for humanoid.vrm1.")
            for bone, role in invalid[:12]:
                self.layout.label(text=f"{bone.name}: {role}")
        self.layout.prop(self, "repair_invalid")

    def execute(self, context):
        state = context.scene.adm_humanoid_wizard
        _root, _objects, arm, _meshes = _analysis(context, state)
        if arm is None:
            try:
                _generate_skeleton(context, state)
            except (RuntimeError, ValueError) as exc:
                self.report({"ERROR"}, str(exc))
                state.status = str(exc)
                return {"CANCELLED"}
            state.step = 2
            state.status = "Template created. Place and confirm the skeleton before continuing; skinning was not run."
            self.report({"INFO"}, state.status)
            return {"FINISHED"}
        configured = _set_humanoid_profile(arm, self.repair_invalid)
        if configured is None:
            state.status = "Auto Configure cancelled; existing non-humanoid roles were preserved."
            self.report({"WARNING"}, state.status)
            return {"CANCELLED"}
        cleared, mapped = configured
        eye_roles, eye_issue = _add_missing_eye_bones(context, arm)
        corrections = R.apply_normalized_corrections(arm)
        chains, skipped = R.add_chains_from_profile(arm, replace=False)
        state.status = (f"Cleared {cleared} role(s) from other profiles, mapped {mapped} role(s), "
                        f"normalized {corrections} reference correction(s), "
                        f"added IK chains: {', '.join(chains) or 'none'}."
                        + (f" Unmapped chain roles: {', '.join(skipped)}." if skipped else ""))
        if eye_roles:
            state.status += " Added estimated non-deforming eye bones; adjust placement in Edit Mode."
        elif eye_issue:
            state.status += f" Eye bones were not added because {eye_issue}."
        self.report({"WARNING"} if eye_issue else {"INFO"}, state.status)
        return {"FINISHED"}


CLASSES = (
    ADM_OT_hw_analyze, ADM_OT_hw_generate_skeleton, ADM_OT_hw_map_skeleton,
    ADM_OT_hw_enter_edit_mode, ADM_OT_hw_skinning, ADM_OT_hw_generate_hitboxes, ADM_OT_hw_create_sockets,
    ADM_OT_hw_validate, ADM_OT_hw_confirm_placement,
    ADM_OT_hw_apply_test_pose, ADM_OT_hw_reset_test_pose, ADM_OT_hw_navigate,
    ADM_OT_hw_auto_configure, ADM_PT_character, ADM_PT_humanoid_wizard,
)
