"""Normative constant tables of ADM 1.0."""

import json
from pathlib import Path


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
    "modelProfiles",
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
SHADER_TWO_LAYER = ("adm.surface.two_layer", "1.0.0")
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
SHADER_INTERACTIVE = ("adm.surface.interactive", "1.0.0")
SHADER_PROFILE_V2 = "2.0.0"
SHADER_PROFILE_EDGE_WEAR = "2.1.0"
SHADER_PROFILE_COLOR1_VERSIONS = frozenset({SHADER_PROFILE_V2, SHADER_PROFILE_EDGE_WEAR})
SHADER_PROFILE_LAYERED_HEIGHT_V1 = "1.1.0"
SHADER_PROFILE_LAYERED_HEIGHT_V2 = "2.1.0"
SHADER_MASK_CHANNELS = ("R", "G", "B", "A")
LAYERS_EXT = "ADM_material_layers_v1"
VERTEX_CONTROL_EXT = "ADM_vertex_control_v1"
MATERIAL_HEIGHT_EXT = "ADM_material_height_v1"
MATERIAL_HEIGHT_FIELDS = frozenset(("version", "heightTexture", "channel", "invert", "scale", "bias",
                                    "referenceHeight", "parallaxMode", "parallaxScale",
                                    "pomMinSteps", "pomMaxSteps", "extras", "extensions"))
TINT_PALETTE_MAX_HEIGHT = 5
VERTEX_CONTROL_PARAMS = {
    "tintOffset": {"type": "F32", "minimum": -1024.0, "maximum": 1024.0, "animatable": True},
    "normalMultiplier": {"type": "F32", "minimum": 0.0, "maximum": 4.0, "animatable": True},
    "reflectionMultiplier": {"type": "F32", "minimum": 0.0, "maximum": 4.0, "animatable": True},
    "wetnessOffset": {"type": "F32", "minimum": -1.0, "maximum": 1.0, "animatable": True},
}
EXTERNAL_IMAGES_EXT = "ADM_external_images_v1"
PHYSICAL_SURFACES_EXT = "ADM_physical_surfaces_v1"
PHYSICAL_SURFACE_TYPES_EXT = "ADM_physical_surface_types_v1"
TERRAIN_SURFACE_EXT = "ADM_terrain_surface_v1"
TERRAIN_CONTROL_MAP_EXT = "ADM_terrain_control_map_v1"
TERRAIN_MACRO_COLOR_EXT = "ADM_terrain_macro_color_v1"
TERRAIN_MACRO_NORMAL_EXT = "ADM_terrain_macro_normal_v1"
TERRAIN_CONTROL_MAP_MODES = (
    "VERTEX_ONLY", "TEXTURE_RGBA", "TEXTURE_RGB_IMPLICIT",
    "VERTEX_MULTIPLY", "VERTEX_OVERRIDE", "VERTEX_MODULATE",
)
TERRAIN_MACRO_COLOR_MODES = ("MULTIPLY", "TINT", "LERP")
INTERACTIVE_SURFACES_EXT = "ADM_interactive_surfaces_v1"
INTERACTIVE_SURFACES_VERSION = "1.0.0"
INTERACTIVE_SURFACES_CAPABILITY = "ADM-INTERACTIVE-SURFACES-1"
HUMANOID_SOCKETS_EXT = "ADM_humanoid_sockets_v1"
HUMANOID_SOCKETS_VERSION = "1.0.0"
HUMANOID_SOCKETS_CAPABILITY = "ADM-HUMANOID-SOCKETS-1"
JOINT_DISPLAY_EXT = "ADM_joint_display_v1"
JOINT_DISPLAY_VERSION = "1.0.0"
JOINT_DISPLAY_CAPABILITY = "ADM-JOINT-DISPLAY-1"
ANIMATION_TIMING_EXT = "ADM_animation_timing_v1"
ANIMATION_TIMING_VERSION = "1.1.0"
ANIMATION_TIMING_CAPABILITY = "ADM-ANIMATION-TIMING-1"
SUPPORTED_EXTENSIONS = (LAYERS_EXT, VERTEX_CONTROL_EXT, MATERIAL_HEIGHT_EXT, EXTERNAL_IMAGES_EXT,
                        PHYSICAL_SURFACES_EXT, PHYSICAL_SURFACE_TYPES_EXT, TERRAIN_SURFACE_EXT,
                        TERRAIN_CONTROL_MAP_EXT, TERRAIN_MACRO_COLOR_EXT, TERRAIN_MACRO_NORMAL_EXT,
                        INTERACTIVE_SURFACES_EXT,
                        HUMANOID_SOCKETS_EXT, JOINT_DISPLAY_EXT, ANIMATION_TIMING_EXT)
PHYSICAL_SURFACE_PROFILES = (
    "adm.phys.wood.v1", "adm.phys.metal.v1", "adm.phys.stone.v1",
    "adm.phys.ground.v1", "adm.phys.glass.v1",
)
with Path(__file__).with_name("physical_surface_registry.json").open(encoding="utf-8") as _registry_file:
    PHYSICAL_SURFACE_REGISTRY = json.load(_registry_file)
PHYSICAL_SURFACE_TYPES = {record["id"]: record for record in PHYSICAL_SURFACE_REGISTRY["types"]}
PHYSICAL_SURFACE_TAGS = frozenset(PHYSICAL_SURFACE_REGISTRY["tags"])
SHADER_PARAM_TYPES = ("F32", "VEC2", "VEC3", "VEC4", "BOOL", "TEXTURE", "ENUM")
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
    SHADER_INTERACTIVE: "INTERACTIVE",
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


def _enum_param(name, values, default, description):
    return {"name": name, "type": "ENUM", "values": list(values), "default": default, "description": description}


def _scalar_map_params(prefix):
    return [
        item
        for prop in ("metallic", "roughness")
        for item in (
            _texture_param(f"{prefix}_{prop}_texture", f"Optional linear {prop} map for {prefix}."),
            _shader_param(f"{prefix}_{prop}_channel", "F32", 0.0,
                          f"Texture channel for {prefix} {prop}: 0=R, 1=G, 2=B, 3=A.", 0.0, 3.0),
            _shader_param(f"{prefix}_{prop}_invert", "BOOL", False,
                          f"Invert the selected {prefix} {prop} texture channel."),
        )
    ]


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
            _texture_param(f"layer{i}_metallic_texture", f"Linear metallic map for layer {i}.")
            for i in range(4)
        ],
        *[
            _texture_param(f"layer{i}_roughness_texture", f"Linear roughness map for layer {i}.")
            for i in range(4)
        ],
        *[
            _shader_param(f"layer{i}_{prop}_channel", "F32", 0.0,
                          f"Texture channel for layer {i} {prop}: 0=R, 1=G, 2=B, 3=A.", 0.0, 3.0)
            for i in range(4) for prop in ("metallic", "roughness")
        ],
        *[
            _shader_param(f"layer{i}_{prop}_invert", "BOOL", False,
                          f"Invert the selected layer {i} {prop} texture channel.")
            for i in range(4) for prop in ("metallic", "roughness")
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
    SHADER_INTERACTIVE: [
        _shader_param("brightness", "F32", 1.0, "Linear multiplier applied to runtime content RGB.",
                      0.0, 16.0, True),
        _shader_param("emissive_strength", "F32", 1.0, "Emission multiplier in lit runtime mode.",
                      0.0, 16.0, True),
        _shader_param("enabled", "BOOL", True, "When false, show the authored PBR fallback."),
        _shader_param("unlit", "BOOL", True, "Render runtime content without light-dependent shading."),
    ],
}

# TEXTURE parameters that carry sRGB-encoded albedo; every other TEXTURE parameter is linear data.
SHADER_COLOR_TEXTURES = frozenset({"detail_texture", "layer0_texture", "layer1_texture", "layer2_texture",
                                   "layer3_texture", "layer0_emissive_texture", "layer1_emissive_texture",
                                   "layer2_emissive_texture", "layer3_emissive_texture"})

COLOR1_CONTRACTS = {
    "CORE": (
        {"label": "Detail blend", "op": "surface", "color": [0.72, 0.72, 0.72], "roughness": 0.6},
        {"label": "Dirt mask", "op": "surface", "color": [0.18, 0.14, 0.1], "roughness": 0.95},
        {"label": "Edge wear", "op": "surface", "color": [0.82, 0.82, 0.82], "roughness": 0.3},
        {"label": "Clearcoat", "op": "factor", "target": "Coat Weight", "value": 0.5},
    ),
    "LAYERED": tuple({"label": f"Layer {i + 1}", "op": "layer", "index": i} for i in range(4)),
    "CUTOUT": (
        {"label": "Cutout variation", "op": "factor", "target": "Alpha", "value": 0.0},
        {"label": "Edge fade", "op": "factor", "target": "Alpha", "value": 1.0},
        {"label": "Detail mask", "op": "surface", "color": [0.8, 0.8, 0.8], "roughness": 0.7},
        {"label": "Damage", "op": "surface", "color": [0.28, 0.22, 0.18], "roughness": 0.9},
    ),
    "EMISSIVE": (
        {"label": "Emission intensity", "op": "factor", "target": "Emission Strength", "value": 1.0},
        {"label": "Color blend", "op": "color", "target": "Emission Color", "color": [1.0, 0.8, 0.55]},
        {"label": "Flicker influence", "op": "multiply", "target": "Emission Strength", "value": 0.0,
         "animatable": True},
        {"label": "Emissive coverage", "op": "coverage", "target": "Emission Strength"},
    ),
    "DECAL": (
        {"label": "Opacity", "op": "factor", "target": "Alpha", "value": 0.0},
        {"label": "Dirt blend", "op": "surface", "color": [0.18, 0.14, 0.1], "roughness": 0.95},
        {"label": "Wear", "op": "surface", "color": [0.8, 0.8, 0.8], "roughness": 0.3},
        {"label": "Detail blend", "op": "surface", "color": [0.72, 0.72, 0.72], "roughness": 0.6},
    ),
    "GLASS": (
        {"label": "Local opacity", "op": "factor", "target": "Alpha", "value": 0.5},
        {"label": "Frosting", "op": "factor", "target": "Roughness", "value": 0.65},
        {"label": "Dirt", "op": "surface", "color": [0.2, 0.18, 0.14], "roughness": 0.9},
        {"label": "Tint variation", "op": "color", "target": "Base Color", "color": [0.7, 0.85, 1.0]},
    ),
    "FOLIAGE": (
        {"label": "Translucency", "op": "factor", "target": "Subsurface Weight", "value": 0.35},
        {"label": "Color variation", "op": "surface", "color": [0.38, 0.62, 0.2], "roughness": 0.75},
        {"label": "Dryness", "op": "factor", "target": "Roughness", "value": 0.95},
        {"label": "Detail mask", "op": "surface", "color": [0.72, 0.72, 0.72], "roughness": 0.6},
    ),
    "TERRAIN_4": tuple({"label": f"Layer {i + 1}", "op": "layer", "index": i} for i in range(4)),
    "VEHICLE_PAINT": (
        {"label": "Metallic flakes", "op": "factor", "target": "Metallic", "value": 0.8},
        {"label": "Dirt", "op": "surface", "color": [0.16, 0.13, 0.1], "roughness": 0.95},
        {"label": "Scratches", "op": "surface", "color": [0.75, 0.75, 0.75], "roughness": 0.35},
        {"label": "Clearcoat", "op": "factor", "target": "Coat Weight", "value": 0.8},
    ),
    "SKIN": (
        {"label": "Subsurface", "op": "factor", "target": "Subsurface Weight", "value": 0.35},
        {"label": "Detail normals", "op": "normal"},
        {"label": "Roughness variation", "op": "factor", "target": "Roughness", "value": 0.55},
        {"label": "Scar/detail", "op": "surface", "color": [0.35, 0.08, 0.06], "roughness": 0.8},
    ),
    "FUR": (
        {"label": "Fur density", "op": "factor", "target": "Anisotropic", "value": 0.7},
        {"label": "Color variation", "op": "surface", "color": [0.65, 0.48, 0.32], "roughness": 0.55},
        {"label": "Roughness variation", "op": "factor", "target": "Roughness", "value": 0.75},
        {"label": "Detail", "op": "normal"},
    ),
    "FEATHER": (
        {"label": "Color variation", "op": "surface", "color": [0.4, 0.55, 0.8], "roughness": 0.55},
        {"label": "Iridescence", "op": "color", "target": "Emission Color", "color": [0.25, 0.35, 0.7]},
        {"label": "Detail", "op": "normal"},
        {"label": "Wear", "op": "factor", "target": "Roughness", "value": 0.9},
    ),
    "SCALES": (
        {"label": "Scale contrast", "op": "contrast", "value": 1.8},
        {"label": "Reflectivity variation", "op": "factor", "target": "Specular IOR Level", "value": 0.8},
        {"label": "Roughness variation", "op": "factor", "target": "Roughness", "value": 0.65},
        {"label": "Detail", "op": "surface", "color": [0.72, 0.72, 0.72], "roughness": 0.6},
    ),
    "CONCRETE": (
        {"label": "Dirt", "op": "surface", "color": [0.2, 0.17, 0.13], "roughness": 0.95},
        {"label": "Damage", "op": "surface", "color": [0.45, 0.38, 0.3], "roughness": 0.9},
        {"label": "Moisture stains", "op": "surface", "color": [0.16, 0.17, 0.18], "roughness": 0.28},
        {"label": "Secondary texture", "op": "surface", "color": [1.0, 1.0, 1.0], "roughness": 0.8},
    ),
    "BRICK": (
        {"label": "Mortar variation", "op": "surface", "color": [0.58, 0.54, 0.48], "roughness": 0.9},
        {"label": "Dirt", "op": "surface", "color": [0.18, 0.14, 0.1], "roughness": 0.95},
        {"label": "Wear", "op": "surface", "color": [0.78, 0.74, 0.68], "roughness": 0.55},
        {"label": "Moss", "op": "surface", "color": [0.08, 0.2, 0.04], "roughness": 0.95},
    ),
    "ROOF": (
        {"label": "Dirt", "op": "surface", "color": [0.18, 0.14, 0.1], "roughness": 0.95},
        {"label": "Wear", "op": "surface", "color": [0.78, 0.74, 0.68], "roughness": 0.55},
        {"label": "Moss", "op": "surface", "color": [0.08, 0.2, 0.04], "roughness": 0.95},
        {"label": "Secondary texture", "op": "surface", "color": [1.0, 1.0, 1.0], "roughness": 0.8},
    ),
    "BARK": (
        {"label": "Moss", "op": "surface", "color": [0.08, 0.2, 0.04], "roughness": 0.95},
        {"label": "Cracks/detail", "op": "normal"},
        {"label": "Color variation", "op": "surface", "color": [0.4, 0.26, 0.12], "roughness": 0.8},
        {"label": "Secondary texture", "op": "surface", "color": [1.0, 1.0, 1.0], "roughness": 0.8},
    ),
    "ROCK": (
        {"label": "Moss", "op": "surface", "color": [0.08, 0.2, 0.04], "roughness": 0.95},
        {"label": "Dirt", "op": "surface", "color": [0.2, 0.16, 0.12], "roughness": 0.95},
        {"label": "Snow", "op": "surface", "color": [0.92, 0.95, 1.0], "roughness": 0.75},
        {"label": "Secondary texture", "op": "surface", "color": [1.0, 1.0, 1.0], "roughness": 0.8},
    ),
    "WATER": (
        {"label": "Foam", "op": "surface", "color": [0.9, 0.95, 1.0], "roughness": 0.85},
        {"label": "Depth tint influence", "op": "color", "target": "Base Color", "color": [0.02, 0.12, 0.24]},
        {"label": "Surface variation", "op": "factor", "target": "Roughness", "value": 0.3},
        {"label": "Shoreline", "op": "factor", "target": "Alpha", "value": 0.25},
    ),
    "FABRIC": (
        {"label": "Fiber detail", "op": "normal"},
        {"label": "Dirt", "op": "surface", "color": [0.2, 0.16, 0.12], "roughness": 0.95},
        {"label": "Wear", "op": "surface", "color": [0.78, 0.74, 0.68], "roughness": 0.6},
        {"label": "Secondary texture", "op": "surface", "color": [1.0, 1.0, 1.0], "roughness": 0.8},
    ),
}

for _key, _kind in tuple(OFFICIAL_SHADER_KINDS.items()):
    if _kind == "INTERACTIVE":
        continue
    _v2_key = (_key[0], SHADER_PROFILE_V2)
    _params = list(OFFICIAL_SHADERS[_key])
    if _kind == "LAYERED":
        _params = [
            *[
                _texture_param(f"layer{i}_texture", f"Albedo texture for PBR layer {i + 1}.")
                for i in range(4)
            ],
            *[
                _shader_param(f"layer{i}_base_color", "VEC4", [1.0, 1.0, 1.0, 1.0],
                              f"Linear base color factor for layer {i + 1}.",
                              [0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0])
                for i in range(4)
            ],
            *[
                _shader_param(f"layer{i}_metallic", "F32", 0.0,
                              f"Metallic factor for layer {i + 1}.", 0.0, 1.0)
                for i in range(4)
            ],
            *[
                _shader_param(f"layer{i}_roughness", "F32", 0.8,
                              f"Roughness factor for layer {i + 1}.", 0.0, 1.0)
                for i in range(4)
            ],
            *[param for i in range(4) for param in _scalar_map_params(f"layer{i}")],
            *[
                _shader_param(f"layer{i}_emissive", "VEC3", [0.0, 0.0, 0.0],
                              f"Linear emissive factor for layer {i + 1}.",
                              [0.0, 0.0, 0.0], None)
                for i in range(4)
            ],
            *[
                _shader_param(f"layer{i}_normal", "TEXTURE", None,
                              f"Optional tangent-space normal map for layer {i + 1}.")
                for i in range(4)
            ],
            _shader_param("uv_scale", "VEC4", [1.0, 1.0, 1.0, 1.0], "Per-layer UV tiling multiplier.",
                          [0.001, 0.001, 0.001, 0.001], [1000.0, 1000.0, 1000.0, 1000.0]),
        ]
    for _i, _effect in enumerate(COLOR1_CONTRACTS[_kind]):
        _channel = SHADER_MASK_CHANNELS[_i]
        _params.append(_shader_param(
            f"color1_{_channel.lower()}_strength", "F32", 1.0,
            f"Strength for the COLOR_1.{_channel} mask ({_effect['label']}).", 0.0, 1.0))
        if _effect["op"] == "surface":
            _params.extend([
                _shader_param(f"color1_{_channel.lower()}_color", "VEC3", _effect["color"],
                              f"Linear overlay color for COLOR_1.{_channel} ({_effect['label']}).",
                              [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]),
                _shader_param(f"color1_{_channel.lower()}_metallic", "F32",
                              _effect.get("metallic", 0.0),
                              f"Overlay metallic factor for COLOR_1.{_channel}.", 0.0, 1.0),
                _shader_param(f"color1_{_channel.lower()}_roughness", "F32", _effect["roughness"],
                              f"Overlay roughness for COLOR_1.{_channel}.", 0.0, 1.0),
                _texture_param(f"color1_{_channel.lower()}_texture",
                               f"Optional sRGB albedo overlay for COLOR_1.{_channel}."),
                _texture_param(f"color1_{_channel.lower()}_normal",
                               f"Optional linear tangent-space normal overlay for COLOR_1.{_channel}."),
                *_scalar_map_params(f"color1_{_channel.lower()}"),
            ])
        elif _effect["op"] in ("factor", "multiply", "contrast"):
            maximum = 4.0 if _effect["op"] in ("multiply", "contrast") \
                or _effect.get("target") == "Emission Strength" else 1.0
            _params.append(_shader_param(
                f"color1_{_channel.lower()}_value", "F32", _effect["value"],
                f"Target value for COLOR_1.{_channel} ({_effect['label']}).",
                0.0, maximum, _effect.get("animatable", False)))
        elif _effect["op"] == "color":
            _params.append(_shader_param(
                f"color1_{_channel.lower()}_color", "VEC3", _effect["color"],
                f"Linear target color for COLOR_1.{_channel} ({_effect['label']}).",
                [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]))
        elif _effect["op"] == "normal":
            _params.append(_texture_param(
                f"color1_{_channel.lower()}_normal",
                f"Optional linear tangent-space normal detail for COLOR_1.{_channel}."))
    OFFICIAL_SHADERS[_v2_key] = _params
    OFFICIAL_SHADER_KINDS[_v2_key] = _kind

_core_edge_wear_key = (SHADER_CORE[0], SHADER_PROFILE_EDGE_WEAR)
OFFICIAL_SHADERS[_core_edge_wear_key] = [
    dict(param) for param in OFFICIAL_SHADERS[(SHADER_CORE[0], SHADER_PROFILE_V2)]
    if param["name"] not in ("color1_g_strength", "color1_b_strength")
]
OFFICIAL_SHADER_KINDS[_core_edge_wear_key] = "CORE"

OFFICIAL_SHADER_KINDS[SHADER_TWO_LAYER] = "TWO_LAYER"
OFFICIAL_SHADER_KEYS["TWO_LAYER"] = SHADER_TWO_LAYER
OFFICIAL_SHADERS[SHADER_TWO_LAYER] = [
    dict(p, description="Linear red channel blends layer 0 (black) into layer 1 (white).")
    if p["name"] == "blend_mask" else dict(p)
    for p in OFFICIAL_SHADERS[SHADER_TERRAIN_4]
    if not p["name"].startswith(("layer2_", "layer3_"))
]


def _layered_height_params(base, layer_count):
    params = [dict(parameter) for parameter in base]
    for index in range(layer_count):
        prefix = f"layer{index}"
        params.extend((
            _texture_param(f"{prefix}_ao_texture", f"Optional linear ambient-occlusion map for {prefix}."),
            _shader_param(f"{prefix}_ao_channel", "F32", 0.0,
                          f"Texture channel for {prefix} ambient occlusion: 0=R, 1=G, 2=B, 3=A.", 0.0, 3.0),
            _shader_param(f"{prefix}_ao_invert", "BOOL", False,
                          f"Invert the selected {prefix} ambient-occlusion channel."),
            _shader_param(f"{prefix}_ao_strength", "F32", 1.0,
                          f"Ambient-occlusion strength for {prefix}.", 0.0, 1.0),
            _texture_param(f"{prefix}_height_texture", f"Optional linear height map for {prefix}."),
            _shader_param(f"{prefix}_height_channel", "F32", 0.0,
                          f"Texture channel for {prefix} height: 0=R, 1=G, 2=B, 3=A.", 0.0, 3.0),
            _shader_param(f"{prefix}_height_invert", "BOOL", False,
                          f"Invert the selected {prefix} height channel."),
            _shader_param(f"{prefix}_height_scale", "F32", 1.0,
                          f"Scale the selected {prefix} height sample.", 0.0, 1000.0),
            _shader_param(f"{prefix}_height_bias", "F32", 0.0,
                          f"Bias the selected {prefix} height sample.", -1.0, 1.0),
            _shader_param(f"{prefix}_parallax_scale", "F32", 0.0,
                          f"Maximum parallax displacement for {prefix}, in scaled UV units.", 0.0, 1.0),
            _texture_param(f"{prefix}_emissive_texture", f"Optional sRGB emission map for {prefix}."),
        ))
    params.extend((
        _shader_param("height_blend_enabled", "BOOL", False, "Enable height-based layer blending."),
        _shader_param("height_blend_transition", "F32", 0.2,
                      "Positive height range controlling the height-blend transition.", 0.001, 1.0),
        _shader_param("height_blend_strength", "F32", 1.0,
                      "Blend from base weights to height-aware weights.", 0.0, 1.0),
        _enum_param("parallax_mode", ("NONE", "PARALLAX", "PARALLAX_OCCLUSION"), "NONE",
                    "Per-layer height-map parallax method."),
        _shader_param("parallax_reference_height", "F32", 0.5,
                      "Height at which parallax produces no UV offset.", 0.0, 1.0),
        _shader_param("parallax_min_steps", "F32", 8.0,
                      "Integer minimum ray-march steps for parallax occlusion.", 1.0, 256.0),
        _shader_param("parallax_max_steps", "F32", 32.0,
                      "Integer maximum ray-march steps for parallax occlusion.", 1.0, 256.0),
    ))
    return params


_advanced_layer_profiles = (
    (SHADER_TERRAIN_4[0], SHADER_PROFILE_LAYERED_HEIGHT_V1, SHADER_TERRAIN_4, 4, "TERRAIN_4"),
    (SHADER_TERRAIN_4[0], SHADER_PROFILE_LAYERED_HEIGHT_V2,
     (SHADER_TERRAIN_4[0], SHADER_PROFILE_V2), 4, "TERRAIN_4"),
    (SHADER_TWO_LAYER[0], SHADER_PROFILE_LAYERED_HEIGHT_V1, SHADER_TWO_LAYER, 2, "TWO_LAYER"),
    (SHADER_LAYERED[0], SHADER_PROFILE_LAYERED_HEIGHT_V2,
     (SHADER_LAYERED[0], SHADER_PROFILE_V2), 4, "LAYERED"),
)
for _shader_id, _version, _base_key, _layer_count, _kind in _advanced_layer_profiles:
    _key = (_shader_id, _version)
    OFFICIAL_SHADERS[_key] = _layered_height_params(OFFICIAL_SHADERS[_base_key], _layer_count)
    OFFICIAL_SHADER_KINDS[_key] = _kind

SHADER_LAYERED_HEIGHT_COUNTS = {
    (SHADER_TERRAIN_4[0], SHADER_PROFILE_LAYERED_HEIGHT_V1): 4,
    (SHADER_TERRAIN_4[0], SHADER_PROFILE_LAYERED_HEIGHT_V2): 4,
    (SHADER_TWO_LAYER[0], SHADER_PROFILE_LAYERED_HEIGHT_V1): 2,
    (SHADER_LAYERED[0], SHADER_PROFILE_LAYERED_HEIGHT_V2): 4,
}
TERRAIN_CONTROL_MAP_PROFILES = frozenset(
    key for key, kind in OFFICIAL_SHADER_KINDS.items()
    if kind == "TERRAIN_4" or SHADER_LAYERED_HEIGHT_COUNTS.get(key) == 4
)
TERRAIN_MACRO_COLOR_PROFILES = TERRAIN_CONTROL_MAP_PROFILES
TERRAIN_MACRO_NORMAL_PROFILES = TERRAIN_CONTROL_MAP_PROFILES
SHADER_PROFILE_CAPABILITIES = {
    key: "ADM-SHADER-LAYERED-HEIGHT-1" for key in SHADER_LAYERED_HEIGHT_COUNTS
}

OFFICIAL_SHADER_IDS = {kind: key[0] for key, kind in OFFICIAL_SHADER_KINDS.items()}
OFFICIAL_SHADER_COLOR1_KEYS = frozenset(
    key for key in OFFICIAL_SHADERS if key[1] in SHADER_PROFILE_COLOR1_VERSIONS
)


def has_color1_profile(shader_kind, version):
    """Return whether an official shader kind/version pair defines COLOR_1 semantics."""
    shader_id = OFFICIAL_SHADER_IDS.get(shader_kind)
    return shader_id is not None and (shader_id, version) in OFFICIAL_SHADER_COLOR1_KEYS


OFFICIAL_SHADER_V2_KEYS = {
    kind: (shader_id, SHADER_PROFILE_V2) for kind, shader_id in OFFICIAL_SHADER_IDS.items()
    if kind not in ("INTERACTIVE", "TWO_LAYER")
}
SHADER_COLOR_TEXTURES = frozenset(
    set(SHADER_COLOR_TEXTURES) | {
        p["name"] for key, params in OFFICIAL_SHADERS.items()
        if key[1] in SHADER_PROFILE_COLOR1_VERSIONS
        for p in params if p["type"] == "TEXTURE" and p["name"].endswith("_texture")
        and not p["name"].endswith(("_metallic_texture", "_roughness_texture", "_ao_texture", "_height_texture"))
    }
)

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
