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
    "POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "TEXCOORD_1", "COLOR_0", "COLOR_1",
    "JOINTS_0", "WEIGHTS_0",
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
SHADER_EMISSIVE = ("adm.surface.emissive", "1.0.0")
SHADER_DECAL = ("adm.surface.decal", "1.0.0")
SHADER_GLASS = ("adm.surface.glass", "1.0.0")
SHADER_FOLIAGE = ("adm.surface.foliage", "1.0.0")
SHADER_TERRAIN_4 = ("adm.terrain.four_layer", "1.0.0")
SHADER_VEHICLE_PAINT = ("adm.vehicle.paint", "1.0.0")
SHADER_SKIN = ("adm.character.skin", "1.0.0")
SHADER_FUR = ("adm.animal.fur", "1.0.0")
SHADER_FEATHER = ("adm.animal.feather", "1.0.0")
SHADER_SCALES = ("adm.animal.scales", "1.0.0")
SHADER_CONCRETE = ("adm.building.concrete", "1.0.0")
SHADER_BRICK = ("adm.building.brick", "1.0.0")
SHADER_ROOF = ("adm.building.roof", "1.0.0")
SHADER_BARK = ("adm.nature.bark", "1.0.0")
SHADER_ROCK = ("adm.nature.rock", "1.0.0")
SHADER_WATER = ("adm.nature.water", "1.0.0")
SHADER_FABRIC = ("adm.surface.fabric", "1.0.0")
LAYERS_EXT = "ADM_material_layers_v1"
VERTEX_CONTROL_EXT = "ADM_vertex_control_v1"
VERTEX_CONTROL_PARAMS = {
    "tintOffset": {"type": "F32", "minimum": -1024.0, "maximum": 1024.0, "animatable": True},
    "normalMultiplier": {"type": "F32", "minimum": 0.0, "maximum": 4.0, "animatable": True},
    "reflectionMultiplier": {"type": "F32", "minimum": 0.0, "maximum": 4.0, "animatable": True},
    "wetnessOffset": {"type": "F32", "minimum": -1.0, "maximum": 1.0, "animatable": True},
}
EXTERNAL_IMAGES_EXT = "ADM_external_images_v1"
PHYSICAL_SURFACES_EXT = "ADM_physical_surfaces_v1"
SUPPORTED_EXTENSIONS = (LAYERS_EXT, VERTEX_CONTROL_EXT, EXTERNAL_IMAGES_EXT, PHYSICAL_SURFACES_EXT)
PHYSICAL_SURFACE_PROFILES = (
    "adm.phys.wood.v1", "adm.phys.metal.v1", "adm.phys.stone.v1",
    "adm.phys.ground.v1", "adm.phys.glass.v1",
)
SHADER_PARAM_TYPES = ("F32", "VEC2", "VEC3", "VEC4", "BOOL", "TEXTURE")
SHADER_NUMERIC_DIMS = {"F32": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
OFFICIAL_SHADER_KINDS = {
    SHADER_CORE: "CORE",
    SHADER_LAYERED: "LAYERED",
    SHADER_CUTOUT: "CUTOUT",
    SHADER_EMISSIVE: "EMISSIVE",
    SHADER_DECAL: "DECAL",
    SHADER_GLASS: "GLASS",
    SHADER_FOLIAGE: "FOLIAGE",
    SHADER_TERRAIN_4: "TERRAIN_4",
    SHADER_VEHICLE_PAINT: "VEHICLE_PAINT",
    SHADER_SKIN: "SKIN",
    SHADER_FUR: "FUR",
    SHADER_FEATHER: "FEATHER",
    SHADER_SCALES: "SCALES",
    SHADER_CONCRETE: "CONCRETE",
    SHADER_BRICK: "BRICK",
    SHADER_ROOF: "ROOF",
    SHADER_BARK: "BARK",
    SHADER_ROCK: "ROCK",
    SHADER_WATER: "WATER",
    SHADER_FABRIC: "FABRIC",
}
OFFICIAL_SHADER_KEYS = {kind: key for key, kind in OFFICIAL_SHADER_KINDS.items()}


def _shader_param(name, typ, default, description, minimum=None, maximum=None, animatable=False):
    p = {"name": name, "type": typ, "default": default, "description": description}
    if minimum is not None:
        p["minimum"] = minimum
    if maximum is not None:
        p["maximum"] = maximum
    if animatable:
        p["animatable"] = True
    return p


def _texture_param(name, description):
    return _shader_param(name, "TEXTURE", None, description)


# Official registry snapshot: (id, version) -> list of parameter definitions.
OFFICIAL_SHADERS = {
    SHADER_CORE: [],
    SHADER_LAYERED: [{
        "name": "layer_factor", "type": "F32", "default": 0.0, "minimum": 0.0, "maximum": 1.0,
        "animatable": True, "description": "Blend factor between the base and overlay layer.",
    }],
    SHADER_CUTOUT: [],
    SHADER_EMISSIVE: [],
    SHADER_DECAL: [],
    SHADER_GLASS: [
        _shader_param("glass_tint", "VEC3", [0.8, 0.9, 1.0], "Linear tint applied to transmitted light.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("reflection_tint", "VEC3", [1.0, 1.0, 1.0], "Linear tint applied to Fresnel reflection.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("transparency", "F32", 0.9, "Fraction of non-reflected light passed through.",
                      0.0, 1.0, True),
        _shader_param("ior", "F32", 1.5, "Index of refraction used only by the thin-surface Fresnel term.",
                      1.0, 2.5),
    ],
    SHADER_FOLIAGE: [
        _shader_param("backface_tint", "VEC3", [0.75, 0.9, 0.65], "Linear tint for the back-face contribution.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("transmission", "F32", 0.2, "Bounded back-light transmission weight.", 0.0, 1.0),
    ],
    SHADER_TERRAIN_4: [
        _texture_param("layer0_texture", "Albedo texture for terrain layer 0."),
        _texture_param("layer1_texture", "Albedo texture for terrain layer 1."),
        _texture_param("layer2_texture", "Albedo texture for terrain layer 2."),
        _texture_param("layer3_texture", "Albedo texture for terrain layer 3."),
        *[
            _shader_param(f"layer{i}_base_color", "VEC4", [1.0, 1.0, 1.0, 1.0],
                          f"Linear base color factor for layer {i}.", [0.0, 0.0, 0.0, 0.0],
                          [1.0, 1.0, 1.0, 1.0])
            for i in range(4)
        ],
        *[
            _shader_param(f"layer{i}_metallic", "F32", 0.0, f"Metallic factor for layer {i}.", 0.0, 1.0)
            for i in range(4)
        ],
        *[
            _shader_param(f"layer{i}_roughness", "F32", 0.8, f"Roughness factor for layer {i}.", 0.0, 1.0)
            for i in range(4)
        ],
        *[
            _shader_param(f"layer{i}_emissive", "VEC3", [0.0, 0.0, 0.0],
                          f"Linear emissive factor for layer {i}.", [0.0, 0.0, 0.0], None)
            for i in range(4)
        ],
        *[
            _texture_param(f"layer{i}_normal", f"Optional tangent-space normal map for layer {i}.")
            for i in range(4)
        ],
        _texture_param("blend_mask", "Linear RGBA weights for terrain layers 0 through 3."),
        _shader_param("uv_scale", "VEC4", [1.0, 1.0, 1.0, 1.0], "Per-layer UV tiling multiplier.",
                      [0.001, 0.001, 0.001, 0.001], [1000.0, 1000.0, 1000.0, 1000.0]),
    ],
    SHADER_VEHICLE_PAINT: [
        _shader_param("clearcoat", "F32", 0.5, "Clearcoat lobe weight.", 0.0, 1.0, True),
        _shader_param("clearcoat_roughness", "F32", 0.1, "Clearcoat lobe roughness.", 0.0, 1.0, True),
        _shader_param("edge_tint", "VEC3", [1.0, 0.8, 0.5], "Linear grazing-angle tint.", [0.0, 0.0, 0.0],
                      [1.0, 1.0, 1.0]),
        _shader_param("edge_tint_strength", "F32", 0.15, "Grazing-angle tint weight.", 0.0, 1.0),
    ],
    SHADER_SKIN: [
        _shader_param("subsurface_strength", "F32", 0.1, "Portable diffuse wrap approximation weight.",
                      0.0, 1.0),
        _shader_param("subsurface_color", "VEC3", [1.0, 0.5, 0.35], "Linear wrap-light tint.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _texture_param("detail_normal", "Optional detail normal map."),
    ],
    SHADER_FUR: [
        _texture_param("fur_detail", "Linear fur-strand modulation texture."),
        _shader_param("fiber_tint", "VEC3", [0.8, 0.7, 0.6], "Linear tint for the fiber lobe.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("fiber_roughness", "F32", 0.35, "Roughness of the fiber lobe.", 0.0, 1.0),
        _shader_param("anisotropy", "F32", 0.35, "Tangent-oriented specular lobe strength.", 0.0, 1.0),
    ],
    SHADER_FEATHER: [
        _texture_param("detail_normal", "Optional feather-card detail normal map."),
        _shader_param("sheen_strength", "F32", 0.3, "Grazing-angle feather sheen weight.", 0.0, 1.0),
        _shader_param("sheen_tint", "VEC3", [0.8, 0.85, 1.0], "Linear feather sheen tint.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
    ],
    SHADER_SCALES: [
        _texture_param("detail_texture", "Scale pattern detail texture."),
        _texture_param("scale_normal", "Tangent-space scale normal texture."),
        _shader_param("specular_strength", "F32", 0.5, "Bounded scale specular response.", 0.0, 1.0),
        _shader_param("scale_metallic", "F32", 0.0, "Metallic factor for the scale surface.", 0.0, 1.0),
    ],
    SHADER_CONCRETE: [
        _texture_param("detail_texture", "Albedo detail texture."),
        _texture_param("detail_normal", "Detail normal texture."),
        _texture_param("dirt_mask", "Linear dirt coverage mask."),
        _shader_param("detail_scale", "F32", 4.0, "Detail UV tiling multiplier.", 0.01, 100.0),
        _shader_param("dirt_amount", "F32", 0.0, "Dirt coverage multiplier.", 0.0, 1.0, True),
    ],
    SHADER_BRICK: [
        _texture_param("mortar_mask", "Linear mask: 1 selects mortar, 0 selects brick."),
        _texture_param("dirt_mask", "Optional linear dirt coverage mask."),
        _shader_param("mortar_color", "VEC3", [0.55, 0.53, 0.5], "Linear mortar albedo.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("mortar_roughness", "F32", 0.9, "Mortar roughness.", 0.0, 1.0),
        _shader_param("brick_roughness", "F32", 0.75, "Brick roughness.", 0.0, 1.0),
        _shader_param("uv_scale", "VEC2", [1.0, 1.0], "Brick texture tiling multiplier.",
                      [0.001, 0.001], [1000.0, 1000.0]),
    ],
    SHADER_ROOF: [
        _texture_param("detail_mask", "Linear weathering/overlap mask."),
        _shader_param("weather_tint", "VEC3", [0.5, 0.5, 0.5], "Linear weathering tint.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("weather_amount", "F32", 0.0, "Weathering mask multiplier.", 0.0, 1.0, True),
    ],
    SHADER_BARK: [
        _texture_param("detail_normal", "Optional bark detail normal texture."),
        _texture_param("moss_mask", "Linear moss/dirt coverage mask."),
        _shader_param("uv_scale", "VEC2", [1.0, 1.0], "Bark texture tiling multiplier.",
                      [0.001, 0.001], [1000.0, 1000.0]),
        _shader_param("moss_amount", "F32", 0.0, "Moss mask multiplier.", 0.0, 1.0, True),
    ],
    SHADER_ROCK: [
        _texture_param("detail_texture", "Rock albedo detail texture."),
        _texture_param("detail_normal", "Rock detail normal texture."),
        _texture_param("moss_mask", "Linear moss/dirt mask."),
        _shader_param("detail_scale", "F32", 4.0, "Detail texture tiling multiplier.", 0.01, 100.0),
        _shader_param("triplanar_scale", "F32", 1.0, "Object-space triplanar frequency.", 0.001, 1000.0),
    ],
    SHADER_WATER: [
        _shader_param("water_tint", "VEC3", [0.05, 0.25, 0.35], "Linear water color.", [0.0, 0.0, 0.0],
                      [1.0, 1.0, 1.0]),
        _shader_param("transparency", "F32", 0.8, "Base thin-surface transparency.", 0.0, 1.0, True),
        _shader_param("ior", "F32", 1.333, "Index of refraction for Schlick Fresnel.", 1.0, 2.5),
        _shader_param("uv_velocity", "VEC2", [0.0, 0.0], "UV offset velocity in cycles per second.",
                      [-10.0, -10.0], [10.0, 10.0], True),
    ],
    SHADER_FABRIC: [
        _texture_param("fiber_detail", "Linear fabric fiber detail texture."),
        _texture_param("detail_normal", "Tangent-space fabric detail normal texture."),
        _shader_param("fiber_tint", "VEC3", [0.9, 0.85, 0.8], "Linear grazing-angle fiber tint.",
                      [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
        _shader_param("fiber_strength", "F32", 0.25, "Grazing-angle fiber lobe weight.", 0.0, 1.0),
        _shader_param("anisotropy", "F32", 0.4, "Tangent-oriented specular lobe strength.", 0.0, 1.0),
    ],
}

# TEXTURE parameters that carry sRGB-encoded albedo; every other TEXTURE parameter is linear data.
SHADER_COLOR_TEXTURES = frozenset({"detail_texture", "layer0_texture", "layer1_texture", "layer2_texture",
                                   "layer3_texture"})
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
