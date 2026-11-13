"""ADM data model stored on Blender datablocks (objects, bones, armatures, materials, scene)."""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

from ..core import constants as K

ADM_TYPES = [
    ("NONE", "None", "Regular object exported as a plain node", "OBJECT_DATA", 0),
    ("MODEL", "Model Root", "Root of one .adm model (like a Sollumz Drawable); not exported as a node", "OUTLINER_OB_EMPTY", 1),
    ("SCENE", "Scene", "Groups the nodes of one ADM scene (only needed for multi-scene models)", "SCENE_DATA", 2),
    ("COLLIDER", "Collider", "Geometric collision descriptor (BOX/SPHERE/CAPSULE/MESH)", "MESH_ICOSPHERE", 3),
    ("LOD_GROUP", "LOD Group", "Group of alternative subtrees selected by camera distance", "MOD_DECIM", 4),
    ("ATTACHMENT", "Attachment", "Named attachment frame", "EMPTY_ARROWS", 5),
]

SKELETON_PROFILES = [
    ("humanoid.vrm1", "Humanoid (VRM 1.0)", "Semantic humanoid roles from VRM 1.0 (retargetable)", "ARMATURE_DATA", 0),
    ("animal.generic_quadruped.v1", "Quadruped (provisional)",
     "PROVISIONAL generic quadruped mammal proposal - not a registered ADM profile", "OUTLINER_OB_ARMATURE", 3),
    ("animal.canine.v1", "Canine (provisional)", "PROVISIONAL dog/wolf proposal (digitigrade)", "BLANK1", 4),
    ("animal.feline.v1", "Feline (provisional)", "PROVISIONAL cat proposal (digitigrade)", "BLANK1", 5),
    ("animal.equine.v1", "Equine (provisional)", "PROVISIONAL horse proposal (unguligrade)", "BLANK1", 6),
    ("generic.v1", "Generic / Custom Rig", "Exact-rig only (rigId); roles optional", "BONE_DATA", 1),
    ("CUSTOM", "Custom ID…", "Registered versioned custom profile id (org.domain.profile.vN)", "TEXT", 2),
]

COLLIDER_SHAPES = [
    ("BOX", "Box", "", "MESH_CUBE", 0),
    ("SPHERE", "Sphere", "", "MESH_UVSPHERE", 1),
    ("CAPSULE", "Capsule", "Y-aligned (Blender Z) capsule", "MESH_CAPSULE", 2),
    ("MESH", "Mesh", "Triangle soup collision surface", "MESH_DATA", 3),
]


def _collider_update(self, context):
    obj = self.id_data
    if isinstance(obj, bpy.types.Object) and obj.adm.adm_type == "COLLIDER":
        from .colliders import refresh_collider_mesh
        if obj.adm.collider_shape == "CAPSULE" and obj.adm.collider_height < 2 * obj.adm.collider_radius:
            obj.adm["collider_height"] = 2 * obj.adm.collider_radius
        refresh_collider_mesh(obj)


def _mesh_poll(self, obj):
    return obj.type == "MESH"


def _armature_poll(self, obj):
    return obj.type == "ARMATURE"


# --- face / expressions ------------------------------------------------------------------------
class ADMFaceBinding(PropertyGroup):
    channel: EnumProperty(name="Channel", items=[(c, c, "") for c in K.ARKIT52])
    object: PointerProperty(name="Mesh", type=bpy.types.Object, poll=_mesh_poll)
    target: StringProperty(name="Shape Key", description="Morph target (shape key) name on the mesh")
    scale: FloatProperty(name="Scale", default=1.0, min=0.0, max=1.0)


class ADMExpressionBinding(PropertyGroup):
    object: PointerProperty(name="Mesh", type=bpy.types.Object, poll=_mesh_poll)
    target: StringProperty(name="Shape Key")
    weight: FloatProperty(name="Weight", default=1.0, min=0.0, max=1.0)


class ADMExpression(PropertyGroup):
    name: StringProperty(name="Name", default="happy")
    priority: IntProperty(name="Priority", default=0, min=0)
    group: EnumProperty(name="Group", items=[(g, g.capitalize(), "") for g in K.EXPRESSION_GROUPS], default="face")
    bindings: CollectionProperty(type=ADMExpressionBinding)
    active_binding: IntProperty()


class ADMLodLevel(PropertyGroup):
    object: PointerProperty(name="Level", type=bpy.types.Object)
    min_distance: FloatProperty(name="Min Distance", min=0.0, unit="LENGTH")


class ADMPhysicalMaterial(PropertyGroup):
    name: StringProperty(name="ID", default="surface")
    friction: FloatProperty(name="Friction", default=0.5, min=0.0, max=1.0)
    restitution: FloatProperty(name="Restitution", default=0.0, min=0.0, max=1.0)


class ADMModelComponent(PropertyGroup):
    name: StringProperty(name="ID", default="part")
    role: StringProperty(name="Role", default="custom.part")
    object: PointerProperty(name="Node", type=bpy.types.Object)
    bone: StringProperty(name="Bone", description="Optional bone on the selected armature")
    socket: StringProperty(name="Socket", description="Optional attachment name")


class ADMHitbox(PropertyGroup):
    name: StringProperty(name="ID", default="hitbox")
    collider: PointerProperty(name="Collider", type=bpy.types.Object)
    object: PointerProperty(name="Bone Node", type=bpy.types.Object,
                            description="Optional collider node or ancestor")
    bone: StringProperty(name="Bone", description="Optional bone on the selected armature")
    role: StringProperty(name="Role")


# --- object --------------------------------------------------------------------------------------
class ADMObjectProps(PropertyGroup):
    adm_type: EnumProperty(name="ADM Type", items=ADM_TYPES, default="NONE")
    export_exclude: BoolProperty(name="Exclude From Export", default=False,
                                 description="Skip this object and its children when exporting")
    # model root
    copyright: StringProperty(name="Copyright")
    default_scene: IntProperty(name="Default Scene", min=0, default=0)
    face_enabled: BoolProperty(name="Export ARKit52 Facial Profile", default=False)
    face_bindings: CollectionProperty(type=ADMFaceBinding)
    active_face_binding: IntProperty()
    expressions: CollectionProperty(type=ADMExpression)
    active_expression: IntProperty()
    physical_materials: CollectionProperty(type=ADMPhysicalMaterial)
    active_physical_material: IntProperty()
    model_components: CollectionProperty(type=ADMModelComponent)
    active_model_component: IntProperty()
    hitboxes: CollectionProperty(type=ADMHitbox)
    active_hitbox: IntProperty()
    # generic node metadata
    attachment_name: StringProperty(name="Attachment Name",
                                    description="Non-empty: export this node as a named attachment frame")
    component_role: StringProperty(name="Component Role", description="e.g. wheel.axle0.left, door.front.left")
    component_profile: StringProperty(name="Component Profile", default="custom.vehicle.v1")
    # collider
    collider_shape: EnumProperty(name="Shape", items=COLLIDER_SHAPES, default="BOX", update=_collider_update)
    collider_size: FloatVectorProperty(name="Size", size=3, default=(1.0, 1.0, 1.0), min=1e-4, subtype="XYZ",
                                       unit="LENGTH", update=_collider_update)
    collider_radius: FloatProperty(name="Radius", default=0.5, min=1e-4, unit="LENGTH", update=_collider_update)
    collider_height: FloatProperty(name="Height", default=2.0, min=1e-4, unit="LENGTH",
                                   description="Total capsule height including caps", update=_collider_update)
    collider_trigger: BoolProperty(name="Trigger", description="Semantic overlap-only collider")
    physical_material: StringProperty(name="Physical Material", description="ID from the model's physical materials")
    # LOD group
    lod_levels: CollectionProperty(type=ADMLodLevel)
    active_lod_level: IntProperty()
    lod_preview_distance: FloatProperty(name="Preview Distance", min=0.0, unit="LENGTH")


# --- bones / skeleton ----------------------------------------------------------------------------
class ADMBoneProps(PropertyGroup):
    role: StringProperty(name="Role", description="Semantic skeleton role (explicit mapping, never guessed on export)")
    attachment_name: StringProperty(name="Attachment Name")
    component_role: StringProperty(name="Component Role")
    component_profile: StringProperty(name="Component Profile", default="custom.vehicle.v1")
    use_reference_correction: BoolProperty(name="Reference Correction")
    reference_correction: FloatVectorProperty(name="Correction", size=4, subtype="QUATERNION",
                                              default=(1.0, 0.0, 0.0, 0.0),
                                              description="Per-role correction quaternion (Blender space)")


class ADMIKChain(PropertyGroup):
    chain_id: StringProperty(name="ID", default="leftLeg")
    root: StringProperty(name="Root Bone")
    mid: StringProperty(name="Mid Bone")
    end: StringProperty(name="End Bone")
    pole: FloatVectorProperty(name="Pole", size=3, default=(0.0, -1.0, 0.0), subtype="DIRECTION",
                              description="Pole direction in armature space (Blender axes)")
    weight: FloatProperty(name="Weight", default=1.0, min=0.0, max=1.0)
    target: PointerProperty(type=bpy.types.Object, name="Preview Target",
                            description="Editor-only object used as runtime IK target for the ADM-IK-1 preview "
                                        "(never exported: ADM IK targets are runtime inputs)")


class ADMSkeletonProps(PropertyGroup):
    export_profile: BoolProperty(name="Export Skeleton Profile", default=False)
    profile: EnumProperty(name="Profile", items=SKELETON_PROFILES, default="humanoid.vrm1")
    custom_profile: StringProperty(name="Profile ID", default="org.example.creature.v1")
    use_target_height: BoolProperty(name="Target Height", default=False)
    target_height: FloatProperty(name="Height", default=1.7, min=0.001, unit="LENGTH")
    write_rig_id: BoolProperty(name="Write Exact rigId", default=True,
                               description="Compute and store the §11.1 rig fingerprint")
    rig_id: StringProperty(name="rigId", description="Last computed rig fingerprint (read only)")
    imported_rig_id: StringProperty(name="Imported rigId",
                                    description="rigId of the file this rig was imported from")
    imported_rest: StringProperty(name="Imported Rest Fingerprint",
                                  description="Rest-pose fingerprint at import time; while unchanged, "
                                              "EXACT libraries made for the source file stay compatible")
    ik_chains: CollectionProperty(type=ADMIKChain)
    active_ik_chain: IntProperty()
    active_bone_index: IntProperty()
    roles_mapped_only: BoolProperty(name="Mapped Only", description="Show only bones with a role")

    @property
    def profile_id(self):
        return self.custom_profile if self.profile == "CUSTOM" else self.profile


# --- shaders (§8.1-8.4) ----------------------------------------------------------------------------
SHADER_KINDS = [
    ("CORE", "PBR Metallic-Roughness", "adm.pbr.metallic_roughness@1.0.0 (default, always supported)", "SHADING_SOLID", 0),
    ("LAYERED", "PBR Layered", "adm.pbr.layered@1.0.0: two PBR layers blended by animatable layer_factor",
     "RENDERLAYERS", 1),
    ("CUSTOM", "Custom Shader", "Custom shader with an embedded typed parameter schema", "NODE_MATERIAL", 2),
]
PARAM_TYPES = [(t, t, "") for t in K.SHADER_PARAM_TYPES]


def _def_name_update(self, context):
    name = f"{self.shader_id}@{self.version}"
    if self.name != name:
        self.name = name


class ADMShaderParamDef(PropertyGroup):
    name: StringProperty(name="Name", default="amount", description="[a-z][a-z0-9_]*, max 64 characters")
    type: EnumProperty(name="Type", items=PARAM_TYPES, default="F32")
    description: StringProperty(name="Description", description="Required human readable meaning")
    animatable: BoolProperty(name="Animatable", description="Only F32/VEC2/VEC3/VEC4 can be animated")
    default_vec: FloatVectorProperty(name="Default", size=4)
    default_bool: BoolProperty(name="Default")
    default_image: PointerProperty(name="Default Texture", type=bpy.types.Image)
    default_tex_coord: IntProperty(name="UV", min=0, max=1)
    use_minimum: BoolProperty(name="Minimum")
    minimum: FloatVectorProperty(name="Minimum", size=4)
    use_maximum: BoolProperty(name="Maximum")
    maximum: FloatVectorProperty(name="Maximum", size=4, default=(1.0, 1.0, 1.0, 1.0))


class ADMShaderDef(PropertyGroup):
    name: StringProperty()
    shader_id: StringProperty(name="Shader ID", default="org.example.custom", update=_def_name_update,
                              description="Dot-qualified id; adm.* is reserved for the official registry")
    version: StringProperty(name="Version", default="1.0.0", update=_def_name_update,
                            description="Exact SemVer without build metadata")
    description: StringProperty(name="Description")
    author: StringProperty(name="Author")
    params: CollectionProperty(type=ADMShaderParamDef)
    active_param: IntProperty()


class ADMShaderParamValue(PropertyGroup):
    """Per-material value of a typed shader parameter.  Animate ``value_f`` / ``value_vec``."""
    name: StringProperty(name="Name")
    use: BoolProperty(name="Override", description="Write this value (otherwise the schema default applies)")
    value_f: FloatProperty(name="Value")
    value_vec: FloatVectorProperty(name="Value", size=4)
    value_bool: BoolProperty(name="Value")
    image: PointerProperty(name="Texture", type=bpy.types.Image)
    tex_coord: IntProperty(name="UV", min=0, max=1)


def _preview_update(self, context):
    mat = self.id_data
    if isinstance(mat, bpy.types.Material) and mat.adm.shader == "LAYERED":
        from .materials import refresh_shader_preview
        refresh_shader_preview(mat)


def _shader_update(self, context):
    from .materials import refresh_shader_preview
    refresh_shader_preview(self.id_data)


class ADMLayerRecord(PropertyGroup):
    base_color: FloatVectorProperty(name="Base Color", size=4, subtype="COLOR", min=0.0, max=1.0,
                                    default=(1.0, 1.0, 1.0, 1.0), update=_preview_update)
    metallic: FloatProperty(name="Metallic", min=0.0, max=1.0, default=1.0, update=_preview_update)
    roughness: FloatProperty(name="Roughness", min=0.0, max=1.0, default=1.0, update=_preview_update)
    emissive: FloatVectorProperty(name="Emissive", size=3, subtype="COLOR", min=0.0, soft_max=1.0,
                                  update=_preview_update)
    use_normal_factor: BoolProperty(name="Normal Factor", update=_preview_update)
    normal_factor: FloatVectorProperty(name="Normal", size=3, default=(0.0, 0.0, 1.0), subtype="XYZ",
                                       update=_preview_update)


# --- materials -------------------------------------------------------------------------------------
def _texture_pick_update(slot):
    attr = "pick_" + slot.lower()

    def update(self, context):
        img = getattr(self, attr)
        if img is None:
            return
        from .materials import set_slot_image
        try:
            set_slot_image(self.id_data, slot, img)
        finally:
            setattr(self, attr, None)
    return update


def _custom_shader_update(self, context):
    sdef = context.scene.adm_anim.shaders.get(self.custom_shader) if context and context.scene else None
    if sdef is not None:
        from .materials import sync_material_params
        sync_material_params(self.id_data, sdef)


def _pick(slot, label):
    return PointerProperty(name=label, type=bpy.types.Image, update=_texture_pick_update(slot),
                           description=f"Pick or open an image for the {label} texture slot")


class ADMMaterialProps(PropertyGroup):
    pick_base_color: _pick("BASE_COLOR", "Base Color")
    pick_metallic_roughness: _pick("METALLIC_ROUGHNESS", "Metallic-Roughness")
    pick_normal: _pick("NORMAL", "Normal")
    pick_occlusion: _pick("OCCLUSION", "Occlusion")
    pick_emissive: _pick("EMISSIVE", "Emissive")
    alpha_mode: EnumProperty(name="Alpha Mode", default="AUTO", items=[
        ("AUTO", "Auto", "Derive from the node tree / render method"),
        ("OPAQUE", "Opaque", ""), ("MASK", "Mask", ""), ("BLEND", "Blend", "")])
    alpha_cutoff: FloatProperty(name="Alpha Cutoff", default=0.5, min=0.0, max=1.0)
    occlusion_strength: FloatProperty(name="Occlusion Strength", default=1.0, min=0.0, max=1.0)
    shader: EnumProperty(name="Shader", items=SHADER_KINDS, default="CORE", update=_shader_update,
                         description="ADM shader of this material; switching rebuilds the viewport preview")
    custom_shader: StringProperty(name="Custom Shader", description="id@version of a scene shader definition",
                                  update=_custom_shader_update)
    animation_id: StringProperty(name="Animation ID",
                                 description="Portable material binding key for shader/PBR animation tracks "
                                             "([a-z][a-z0-9_]*, unique per model)")
    layer_factor: FloatProperty(name="Layer Factor", min=0.0, max=1.0, default=0.0,
                                description="Animatable blend between base and overlay layer")
    layer_base: PointerProperty(type=ADMLayerRecord)
    layer_overlay: PointerProperty(type=ADMLayerRecord)
    layer_mask: PointerProperty(name="Mask Texture", type=bpy.types.Image, update=_preview_update,
                                description="Optional mask; the linear red channel scales layer_factor")
    layer_mask_uv: IntProperty(name="Mask UV", min=0, max=1, update=_preview_update)
    layers_required: BoolProperty(name="Require Layered Rendering",
                                  description="List ADM_material_layers_v1 under extensionsRequired")
    params: CollectionProperty(type=ADMShaderParamValue)
    active_param: IntProperty()

    def shader_key(self, scene=None):
        if self.shader == "LAYERED":
            return K.SHADER_LAYERED
        if self.shader == "CUSTOM":
            sid, _, ver = self.custom_shader.partition("@")
            return (sid, ver)
        return K.SHADER_CORE


# --- animation ---------------------------------------------------------------------------------------
class ADMAnimEvent(PropertyGroup):
    time: FloatProperty(name="Time", min=0.0, unit="TIME_ABSOLUTE", description="Seconds from clip start")
    name: StringProperty(name="Name", default="footstep")
    payload: StringProperty(name="Payload", description="Optional JSON object, e.g. {\"foot\":\"left\"}")


def _clip_action_update(self, context):
    if self.action and self.use_action_range:
        r = self.action.frame_range
        self.frame_start, self.frame_end = int(r[0]), int(r[1])


class ADMAnimClip(PropertyGroup):
    clip_id: StringProperty(name="Clip ID", default="clip", description="Lowercase segment [a-z][a-z0-9_]*")
    title: StringProperty(name="Title")
    description: StringProperty(name="Description", description="Required, human written (never auto-synthesized)")
    language: StringProperty(name="Language", default="en", description="BCP-47 language tag")
    tags: StringProperty(name="Tags", description="Comma separated lowercase tags")
    action: PointerProperty(name="Action", type=bpy.types.Action, update=_clip_action_update)
    use_action_range: BoolProperty(name="Use Action Range", default=True, update=_clip_action_update)
    frame_start: IntProperty(name="Start", default=1)
    frame_end: IntProperty(name="End", default=25)
    loop: EnumProperty(name="Loop", items=[(m, m.capitalize(), "") for m in K.LOOP_MODES], default="REPEAT")
    root_motion: EnumProperty(name="Root Motion", default="IN_PLACE", items=[
        ("IN_PLACE", "In Place", ""), ("EXTRACT", "Extract", ""), ("IGNORE", "Ignore", "")])
    root_bone: StringProperty(name="Root Bone", description="EXACT binding: bone carrying root motion")
    events: CollectionProperty(type=ADMAnimEvent)
    active_event: IntProperty()


class ADMAnimLibrary(PropertyGroup):
    lib_id: StringProperty(name="Library ID", default="human@locomotion", description="segment('@'segment)*")
    title: StringProperty(name="Title")
    description: StringProperty(name="Description")
    language: StringProperty(name="Language", default="en")
    target: EnumProperty(name="Target", default="RIG", items=[
        ("RIG", "Rig Profile", "Library targets the skeleton profile of the chosen rig"),
        ("MODEL_ANY", "Any Model (model.any.v1)",
         "Material / morph / expression-only library without bone tracks")])
    armature: PointerProperty(name="Rig", type=bpy.types.Object, poll=_armature_poll)
    binding: EnumProperty(name="Binding", default="SEMANTIC", items=[
        ("SEMANTIC", "Semantic", "Retargetable rotation deltas by profile role"),
        ("EXACT", "Exact", "Absolute local TRS for one exact rig (rigId)")])
    tags: StringProperty(name="Tags")
    author: StringProperty(name="Author")
    license: StringProperty(name="License")
    revision: StringProperty(name="Revision", description="Optional SemVer 2.0.0")
    namespace: StringProperty(name="Namespace", description="Optional reverse-DNS, e.g. org.example")
    use_motion_scale: BoolProperty(name="Scale By Source Height")
    source_height: FloatProperty(name="Source Height", default=1.7, min=0.001, unit="LENGTH")
    root_motion_from_hips: BoolProperty(name="Root Motion From Hips")
    clips: CollectionProperty(type=ADMAnimClip)
    active_clip: IntProperty()


class ADMSceneProps(PropertyGroup):
    libraries: CollectionProperty(type=ADMAnimLibrary)
    active_library: IntProperty()
    shaders: CollectionProperty(type=ADMShaderDef)
    active_shader: IntProperty()


# --- validation report ----------------------------------------------------------------------------------
class ADMReportItem(PropertyGroup):
    severity: StringProperty()
    code: StringProperty()
    path: StringProperty()
    message: StringProperty()
    bone: StringProperty()
    role: StringProperty()
    fix: StringProperty()


class ADMRoleName(PropertyGroup):
    name: StringProperty()


class ADMWindowProps(PropertyGroup):
    report: CollectionProperty(type=ADMReportItem)
    active_report: IntProperty()
    report_title: StringProperty()
    rig_report: CollectionProperty(type=ADMReportItem)
    active_rig_issue: IntProperty()
    rig_report_title: StringProperty()
    compat_report: CollectionProperty(type=ADMReportItem)
    active_compat: IntProperty()
    compat_title: StringProperty()
    role_names: CollectionProperty(type=ADMRoleName)
    collider_shape: EnumProperty(name="Shape", items=COLLIDER_SHAPES, default="BOX")


CLASSES = (
    ADMFaceBinding, ADMExpressionBinding, ADMExpression, ADMLodLevel,
    ADMPhysicalMaterial, ADMModelComponent, ADMHitbox, ADMObjectProps,
    ADMBoneProps, ADMIKChain, ADMSkeletonProps,
    ADMShaderParamDef, ADMShaderDef, ADMShaderParamValue, ADMLayerRecord, ADMMaterialProps,
    ADMAnimEvent, ADMAnimClip, ADMAnimLibrary, ADMSceneProps,
    ADMReportItem, ADMRoleName, ADMWindowProps,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.adm = PointerProperty(type=ADMObjectProps)
    bpy.types.Bone.adm = PointerProperty(type=ADMBoneProps)
    bpy.types.EditBone.adm = PointerProperty(type=ADMBoneProps)
    bpy.types.Armature.adm = PointerProperty(type=ADMSkeletonProps)
    bpy.types.Material.adm = PointerProperty(type=ADMMaterialProps)
    bpy.types.Scene.adm_anim = PointerProperty(type=ADMSceneProps)
    bpy.types.WindowManager.adm = PointerProperty(type=ADMWindowProps)


def unregister():
    del bpy.types.WindowManager.adm
    del bpy.types.Scene.adm_anim
    del bpy.types.Material.adm
    del bpy.types.Armature.adm
    del bpy.types.EditBone.adm
    del bpy.types.Bone.adm
    del bpy.types.Object.adm
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
