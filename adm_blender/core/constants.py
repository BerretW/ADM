"""Normative constant tables of ADM 1.0 (Draft 0.4)."""

ADM_MAGIC = b"ADM0"
ANIM_MAGIC = b"AMA0"
VERSION_MAJOR = 1
VERSION_MINOR = 0
HEADER_SIZE = 64

COMPONENT_SIZES = {"F32": 4, "U32": 4, "U16": 2, "U8": 1}
COMPONENT_STRUCT = {"F32": "f", "U32": "I", "U16": "H", "U8": "B"}
COMPONENT_MAX = {"U8": 255, "U16": 65535, "U32": 4294967295}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

ADM_REQUIRED_TOP = ("asset", "nodes", "scenes", "scene", "meshes", "accessors", "bufferViews")
ADM_OPTIONAL_TOP = (
    "materials", "samplers", "images", "textures", "skins", "colliders", "lodGroups",
    "attachments", "skeletonProfiles", "facialProfiles", "expressions", "ikChains",
    "componentRoles", "shaderDefinitions", "chunkDependencies", "streamHints",
    "physicalMaterials", "hitboxes", "modelComponents",
    "extensionsUsed", "extensionsRequired", "extensions", "extras",
)
ANIM_REQUIRED_TOP = ("asset", "library", "clips", "bufferViews", "accessors")
ANIM_OPTIONAL_TOP = ("eventsSchema", "chunkDependencies", "streamHints",
                     "extensionsUsed", "extensionsRequired", "extensions", "extras")

ATTRIBUTE_SEMANTICS = (
    "POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "TEXCOORD_1", "COLOR_0", "JOINTS_0", "WEIGHTS_0",
)

# --- humanoid.vrm1 (VRM 1.0 humanoid, snapshot 2026-11-13) ----------------------------------
# role -> VRM parent role (None for the hierarchy root)
VRM1_PARENT = {
    "hips": None,
    "spine": "hips",
    "chest": "spine",
    "upperChest": "chest",
    "neck": "upperChest",
    "head": "neck",
    "leftEye": "head",
    "rightEye": "head",
    "jaw": "head",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "leftToes": "leftFoot",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
    "leftShoulder": "upperChest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "rightShoulder": "upperChest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
}
for _side in ("left", "right"):
    _hand = _side + "Hand"
    VRM1_PARENT[_side + "ThumbMetacarpal"] = _hand
    VRM1_PARENT[_side + "ThumbProximal"] = _side + "ThumbMetacarpal"
    VRM1_PARENT[_side + "ThumbDistal"] = _side + "ThumbProximal"
    for _finger in ("Index", "Middle", "Ring", "Little"):
        VRM1_PARENT[_side + _finger + "Proximal"] = _hand
        VRM1_PARENT[_side + _finger + "Intermediate"] = _side + _finger + "Proximal"
        VRM1_PARENT[_side + _finger + "Distal"] = _side + _finger + "Intermediate"
del _side, _hand, _finger

VRM1_ROLES = tuple(VRM1_PARENT.keys())
VRM1_REQUIRED = (
    "hips", "spine", "head",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
)

BUILTIN_SKELETON_PROFILES = ("humanoid.vrm1", "generic.v1")
MODEL_ANY_PROFILE = "model.any.v1"

# --- shaders (§8.1-8.4) ------------------------------------------------------------------------
SHADER_CORE = ("adm.pbr.metallic_roughness", "1.0.0")
SHADER_LAYERED = ("adm.pbr.layered", "1.0.0")
SHADER_CUTOUT = ("adm.surface.cutout", "1.0.0")
LAYERS_EXT = "ADM_material_layers_v1"
SUPPORTED_EXTENSIONS = (LAYERS_EXT,)
SHADER_PARAM_TYPES = ("F32", "VEC2", "VEC3", "VEC4", "BOOL", "TEXTURE")
SHADER_NUMERIC_DIMS = {"F32": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
# Official registry snapshot: (id, version) -> list of parameter definitions.
OFFICIAL_SHADERS = {
    SHADER_CORE: [],
    SHADER_LAYERED: [{
        "name": "layer_factor", "type": "F32", "default": 0.0, "minimum": 0.0, "maximum": 1.0,
        "animatable": True, "description": "Blend factor between the base and overlay layer.",
    }],
    SHADER_CUTOUT: [],
}
# pbrParameter animation targets: name -> (accessor type, minimum, maximum)
PBR_PARAMETERS = {
    "baseColorFactor": ("VEC4", 0.0, 1.0),
    "metallicFactor": ("SCALAR", 0.0, 1.0),
    "roughnessFactor": ("SCALAR", 0.0, 1.0),
    "emissiveFactor": ("VEC3", 0.0, None),
    "alphaCutoff": ("SCALAR", 0.0, 1.0),
    "normalScale": ("SCALAR", 0.0, None),
}
SHADER_TYPE_TO_ACCESSOR = {"F32": "SCALAR", "VEC2": "VEC2", "VEC3": "VEC3", "VEC4": "VEC4"}

# --- face.arkit52.v1 ---------------------------------------------------------------------------
ARKIT52 = (
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight", "mouthPucker", "mouthRight", "mouthRollLower",
    "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight",
    "mouthStretchLeft", "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    "noseSneerLeft", "noseSneerRight", "tongueOut",
)
ARKIT52_SET = frozenset(ARKIT52)
FACE_PROFILE_ID = "face.arkit52.v1"

EXPRESSION_GROUPS = ("face", "blink", "mouth", "look", "custom")
EXPRESSION_PRESETS = ("neutral", "happy", "sad", "angry", "relaxed", "surprised")

ALPHA_MODES = ("OPAQUE", "MASK", "BLEND")
FILTERS = ("NEAREST", "LINEAR")
WRAPS = ("REPEAT", "CLAMP_TO_EDGE", "MIRRORED_REPEAT")
IMAGE_MIMES = ("image/png", "image/jpeg", "image/ktx2", "image/vnd-ms.dds")
PORTABLE_IMAGE_MIMES = ("image/png", "image/jpeg")
GPU_IMAGE_MIMES = ("image/ktx2", "image/vnd-ms.dds")
PBR_FALLBACK_FIELDS = ("baseColorFactor", "metallicFactor", "roughnessFactor", "emissiveFactor", "alphaMode")

COLLIDER_SHAPES = ("BOX", "SPHERE", "CAPSULE", "MESH")

LOOP_MODES = ("ONCE", "REPEAT", "PINGPONG")
ROOT_MOTION_MODES = ("IN_PLACE", "EXTRACT", "IGNORE")
BINDINGS = ("SEMANTIC", "EXACT")
INTERPOLATIONS = ("STEP", "LINEAR", "CUBICSPLINE")
CHANNEL_PATHS = ("translation", "rotation", "scale", "weight", "value")
TARGET_KINDS = ("bone", "morph", "expression", "shaderParameter", "pbrParameter")
