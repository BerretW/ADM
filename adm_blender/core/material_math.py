"""Renderer-independent scalar contracts for layered material effects."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _unit(value: float, name: str) -> float:
    value = _finite(value, name)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in 0..1")
    return value


def _srgb_to_linear(value: float) -> float:
    value = _unit(value, "sRGB channel")
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def select_channel(sample: Sequence[float] | None, channel: int = 0, invert: bool = False) -> float | None:
    """Return one normalized linear channel, or None when the map is absent."""
    if sample is None:
        return None
    if not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel < len(sample):
        raise ValueError("channel must select an available channel")
    value = _unit(sample[channel], "texture channel")
    return 1.0 - value if invert else value


def effective_height(
    sample: Sequence[float] | None,
    channel: int = 0,
    invert: bool = False,
    scale: float = 1.0,
    bias: float = 0.0,
) -> float:
    """Return a linear 0..1 surface height; a missing map is neutral at 0.5."""
    value = select_channel(sample, channel, invert)
    if value is None:
        value = 0.5
    scale = _finite(scale, "height scale")
    bias = _finite(bias, "height bias")
    return min(1.0, max(0.0, value * scale + bias))


def evaluate_layer_ao(
    weights: Sequence[float],
    samples: Sequence[Sequence[float] | None],
    channels: Sequence[int] | None = None,
    inversions: Sequence[bool] | None = None,
    strengths: Sequence[float] | None = None,
) -> float:
    """Mix layer AO by normalized weights; absent maps contribute unoccluded light."""
    count = len(weights)
    if len(samples) != count:
        raise ValueError("weights and AO samples must have equal lengths")
    channels = [0] * count if channels is None else channels
    inversions = [False] * count if inversions is None else inversions
    strengths = [1.0] * count if strengths is None else strengths
    if not all(len(values) == count for values in (channels, inversions, strengths)):
        raise ValueError("AO settings must match the layer count")
    normalized = _normalized_weights(weights)
    total = 0.0
    for weight, sample, channel, invert, strength in zip(
        normalized, samples, channels, inversions, strengths
    ):
        strength = _unit(strength, "AO strength")
        value = select_channel(sample, channel, invert)
        ao = 1.0 if value is None else 1.0 + (value - 1.0) * strength
        total += weight * ao
    return min(1.0, max(0.0, total))


def combine_ao(layer_ao: float, top_level_sample: float | None, strength: float = 1.0) -> float:
    """Multiply layered AO by top-level AO mixed from unoccluded at the given strength."""
    layer_ao = _unit(layer_ao, "layer AO")
    strength = _unit(strength, "top-level AO strength")
    if top_level_sample is None:
        return layer_ao
    top_level_sample = _unit(top_level_sample, "top-level AO")
    return layer_ao * (1.0 + (top_level_sample - 1.0) * strength)


def blend_normals(
    weights: Sequence[float],
    normals: Sequence[Sequence[float] | None],
) -> tuple[float, float, float]:
    """Blend tangent-space layer normals and normalize; absent maps use +Z."""
    if len(weights) != len(normals):
        raise ValueError("weights and normals must have equal lengths")
    normalized = _normalized_weights(weights)
    result = [0.0, 0.0, 0.0]
    for weight, normal in zip(normalized, normals):
        if normal is None:
            vector = (0.0, 0.0, 1.0)
        else:
            if len(normal) != 3:
                raise ValueError("each normal must have three components")
            vector = tuple(_finite(component, "normal component") for component in normal)
            length = math.sqrt(sum(component * component for component in vector))
            if length <= 1e-12:
                raise ValueError("normal must be non-zero")
            vector = tuple(component / length for component in vector)
        for axis in range(3):
            result[axis] += weight * vector[axis]
    length = math.sqrt(sum(component * component for component in result))
    if length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return tuple(component / length for component in result)


def _normalized_weights(weights: Sequence[float]) -> list[float]:
    if not weights:
        raise ValueError("at least one layer weight is required")
    values = [_finite(value, "layer weight") for value in weights]
    if any(value < 0.0 for value in values):
        raise ValueError("layer weights must be non-negative")
    total = sum(values)
    if total <= 0.0:
        return [1.0] + [0.0] * (len(values) - 1)
    return [value / total for value in values]


def terrain_control_map_uv(
    *,
    mapping: str,
    scale: Sequence[float] = (1.0, 1.0),
    offset: Sequence[float] = (0.0, 0.0),
    uv: Sequence[float] | None = None,
    position: Sequence[float] | None = None,
    origin: Sequence[float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Return transformed UV or model-space XZ coordinates for a Control Map."""
    if len(scale) != 2 or len(offset) != 2 or len(origin) != 2:
        raise ValueError("Control Map scale, offset, and origin must have two components")
    sx, sy = (_finite(value, "Control Map scale") for value in scale)
    ox, oy = (_finite(value, "Control Map offset") for value in offset)
    origin_x, origin_y = (_finite(value, "Control Map origin") for value in origin)
    if abs(sx) > 1e6 or abs(sy) > 1e6 or (sx == 0.0 and sy == 0.0):
        raise ValueError("Control Map scale must be bounded and non-zero")
    if abs(ox) > 1e9 or abs(oy) > 1e9 or abs(origin_x) > 1e9 or abs(origin_y) > 1e9:
        raise ValueError("Control Map offset and origin must be bounded")
    if mapping == "UV":
        if uv is None or len(uv) != 2:
            raise ValueError("UV mapping requires two texture coordinates")
        u, v = (_finite(value, "texture coordinate") for value in uv)
        x, y = u, v
    elif mapping == "WORLD_PLANAR_XZ":
        if position is None or len(position) != 3:
            raise ValueError("world-planar mapping requires a three-component position")
        px, _, pz = (_finite(value, "model position") for value in position)
        x, y = px - origin_x, pz - origin_y
    else:
        raise ValueError("mapping must be UV or WORLD_PLANAR_XZ")
    result = (x * sx + ox, y * sy + oy)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("transformed Control Map coordinates must be finite")
    return result


def terrain_macro_color_uv(
    *,
    projection: str,
    scale: Sequence[float] = (1.0, 1.0),
    offset: Sequence[float] = (0.0, 0.0),
    uv: Sequence[float] | None = None,
    position: Sequence[float] | None = None,
    origin: Sequence[float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Return local-UV or shared-world XZ coordinates for a Macro Color map."""
    mapping = {"LOCAL_UV": "UV", "SHARED_WORLD_XZ": "WORLD_PLANAR_XZ"}.get(projection)
    if mapping is None:
        raise ValueError("projection must be LOCAL_UV or SHARED_WORLD_XZ")
    return terrain_control_map_uv(mapping=mapping, scale=scale, offset=offset,
                                  uv=uv, position=position, origin=origin)


def terrain_macro_normal_uv(
    *,
    projection: str,
    scale: Sequence[float] = (1.0, 1.0),
    offset: Sequence[float] = (0.0, 0.0),
    uv: Sequence[float] | None = None,
    position: Sequence[float] | None = None,
    origin: Sequence[float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Return local-UV or shared-world XZ coordinates for a Macro Normal map."""
    return terrain_macro_color_uv(projection=projection, scale=scale, offset=offset,
                                  uv=uv, position=position, origin=origin)


def terrain_control_map_weights(
    vertex_weights: Sequence[float],
    control_sample: Sequence[float] | None,
    mode: str,
    strength: float = 1.0,
    channel_order: Sequence[int] = (0, 1, 2, 3),
    override_mask: Sequence[float] = (1.0, 1.0, 1.0, 1.0),
) -> list[float]:
    """Evaluate one four-layer Control Map sample before height blending."""
    modes = {
        "VERTEX_ONLY",
        "TEXTURE_RGBA",
        "TEXTURE_RGB_IMPLICIT",
        "VERTEX_MULTIPLY",
        "VERTEX_OVERRIDE",
        "VERTEX_MODULATE",
    }
    if mode not in modes:
        raise ValueError("unsupported Control Map mode")
    if len(vertex_weights) != 4:
        raise ValueError("Control Map evaluation requires four vertex weights")
    base = _normalized_weights(vertex_weights)
    strength = _unit(strength, "Control Map strength")
    if len(channel_order) != 4 or any(type(value) is not int for value in channel_order) or \
            sorted(channel_order) != [0, 1, 2, 3]:
        raise ValueError("channel order must be a permutation of 0, 1, 2, 3")
    if len(override_mask) != 4:
        raise ValueError("override mask must have four components")
    mask = [_unit(value, "Control Map override mask") for value in override_mask]
    if mode == "VERTEX_ONLY" or control_sample is None:
        return base

    sample = [_unit(value, "Control Map sample") for value in control_sample]
    if mode == "TEXTURE_RGB_IMPLICIT":
        if len(sample) != 3:
            raise ValueError("TEXTURE_RGB_IMPLICIT requires three sampled channels")
        red, green, blue = sample
        canonical = [max(0.0, 1.0 - red - green - blue), red, green, blue]
    else:
        if len(sample) != 4:
            raise ValueError("Control Map sample must have four channels")
        canonical = sample
    control = _normalized_weights([canonical[index] for index in channel_order])

    if mode in {"TEXTURE_RGBA", "TEXTURE_RGB_IMPLICIT"}:
        result = [(1.0 - strength) * old + strength * new for old, new in zip(base, control)]
    elif mode == "VERTEX_MULTIPLY":
        multiplied = _normalized_weights([old * new for old, new in zip(base, control)])
        result = [(1.0 - strength) * old + strength * new
                  for old, new in zip(base, multiplied)]
    elif mode == "VERTEX_OVERRIDE":
        result = [
            old * (1.0 - strength * weight) + new * strength * weight
            for old, new, weight in zip(base, control, mask)
        ]
    else:
        result = [
            old * (1.0 - strength + strength * 4.0 * new)
            for old, new in zip(base, control)
        ]
    return _normalized_weights(result)


def terrain_macro_color(
    layer_colors: Sequence[Sequence[float]],
    weights: Sequence[float],
    macro_sample_srgb: Sequence[float] | None,
    mode: str = "MULTIPLY",
    strength: float = 1.0,
    layer_influence: Sequence[float] | None = None,
) -> tuple[float, float, float]:
    """Apply one sRGB Macro Color sample to four linear layer albedos."""
    if mode not in {"MULTIPLY", "TINT", "LERP"}:
        raise ValueError("unsupported Macro Color mode")
    if len(layer_colors) != 4 or len(weights) != 4:
        raise ValueError("Macro Color evaluation requires four layer colors and weights")
    if layer_influence is None:
        layer_influence = (1.0, 1.0, 1.0, 1.0)
    if len(layer_influence) != 4:
        raise ValueError("Macro Color layer influence must have four components")
    strength = _unit(strength, "Macro Color strength")
    influences = [_unit(value, "Macro Color layer influence") for value in layer_influence]
    base = []
    for color in layer_colors:
        if len(color) != 3:
            raise ValueError("each Macro Color layer albedo must have three components")
        base.append(tuple(_unit(value, "linear layer albedo") for value in color))
    normalized = _normalized_weights(weights)
    if macro_sample_srgb is None:
        macro = None
        alpha = 1.0
    else:
        if len(macro_sample_srgb) not in (3, 4):
            raise ValueError("Macro Color samples must have three or four components")
        macro = tuple(_srgb_to_linear(value) for value in macro_sample_srgb[:3])
        alpha = _unit(macro_sample_srgb[3], "Macro Color alpha") if len(macro_sample_srgb) == 4 else 1.0

    result = [0.0, 0.0, 0.0]
    for index, (color, weight) in enumerate(zip(base, normalized)):
        amount = strength * influences[index]
        if macro is not None:
            if mode != "MULTIPLY":
                amount *= alpha
            if mode == "LERP":
                shaded = tuple((1.0 - amount) * old + amount * new
                               for old, new in zip(color, macro))
            else:
                shaded = tuple(old * (1.0 - amount + amount * new)
                               for old, new in zip(color, macro))
        else:
            shaded = color
        for channel in range(3):
            result[channel] += weight * shaded[channel]
    return tuple(result)


def _normalized_normal(normal: Sequence[float], name: str) -> tuple[float, float, float]:
    if len(normal) != 3:
        raise ValueError(f"{name} must have three components")
    values = tuple(_finite(value, name) for value in normal)
    length = math.hypot(*values)
    if length <= 1e-12 or not math.isfinite(length):
        raise ValueError(f"{name} must be non-zero")
    return tuple(value / length for value in values)


def reconstruct_bc5_normal(
    sample: Sequence[float],
    strength: float = 1.0,
) -> tuple[float, float, float]:
    """Decode BC5 XY, clamp over-disk samples, and apply tangent-space strength."""
    if len(sample) not in (2, 3):
        raise ValueError("BC5 normal samples must have two channels or reconstructed RGB")
    strength = _unit(strength, "Macro Normal strength")
    x = 2.0 * _unit(sample[0], "BC5 red") - 1.0
    y = 2.0 * _unit(sample[1], "BC5 green") - 1.0
    radius = math.hypot(x, y)
    if radius > 1.0:
        x /= radius
        y /= radius
    x *= strength
    y *= strength
    z = math.sqrt(max(0.0, 1.0 - x * x - y * y))
    return _normalized_normal((x, y, z), "reconstructed BC5 normal")


def reoriented_normal(
    base_normal: Sequence[float],
    detail_normal: Sequence[float],
) -> tuple[float, float, float]:
    """Compose tangent-space normals with reoriented normal mapping (RNM)."""
    base = _normalized_normal(base_normal, "base normal")
    detail = _normalized_normal(detail_normal, "detail normal")
    tangent = (base[0], base[1], base[2] + 1.0)
    tangent_length = math.hypot(*tangent)
    if tangent_length <= 1e-8:
        return base
    reoriented_detail = (-detail[0], -detail[1], detail[2])
    dot = sum(a * b for a, b in zip(tangent, reoriented_detail))
    result = tuple(
        tangent[index] * dot - reoriented_detail[index] * tangent[2]
        for index in range(3)
    )
    length = math.hypot(*result)
    if length <= 1e-8:
        return base
    return tuple(value / length for value in result)


def _blend_macro_normals(
    weights: Sequence[float],
    normals: Sequence[Sequence[float] | None],
) -> tuple[float, float, float]:
    if len(weights) != 4 or len(normals) != 4:
        raise ValueError("Macro Normal blending requires four weights and normals")
    normalized_weights = _normalized_weights(weights)
    vectors = [
        (0.0, 0.0, 1.0) if normal is None else _normalized_normal(normal, "layer normal")
        for normal in normals
    ]
    result = tuple(
        sum(weight * vector[axis] for weight, vector in zip(normalized_weights, vectors))
        for axis in range(3)
    )
    length = math.hypot(*result)
    if length <= 1e-8:
        return (0.0, 0.0, 1.0)
    return tuple(value / length for value in result)


def terrain_macro_normal(
    layer_normals: Sequence[Sequence[float] | None],
    weights: Sequence[float],
    macro_sample: Sequence[float] | None,
    strength: float = 1.0,
    layer_influence: Sequence[float] | None = None,
) -> tuple[float, float, float]:
    """RNM-compose one BC5 Macro Normal sample with four common-frame layer normals."""
    if len(layer_normals) != 4 or len(weights) != 4:
        raise ValueError("Macro Normal evaluation requires four layer normals and weights")
    if layer_influence is None:
        layer_influence = (1.0, 1.0, 1.0, 1.0)
    if len(layer_influence) != 4:
        raise ValueError("Macro Normal layer influence must have four components")
    strength = _unit(strength, "Macro Normal strength")
    influences = [_unit(value, "Macro Normal layer influence") for value in layer_influence]
    normalized_weights = _normalized_weights(weights)
    if macro_sample is None:
        return _blend_macro_normals(normalized_weights, layer_normals)
    adjusted = []
    for normal, influence in zip(layer_normals, influences):
        base = (0.0, 0.0, 1.0) if normal is None else _normalized_normal(normal, "layer normal")
        detail = reconstruct_bc5_normal(macro_sample, strength * influence)
        adjusted.append(reoriented_normal(base, detail))
    return _blend_macro_normals(normalized_weights, adjusted)


def terrain_macro_normal_frame(
    geometric_normal: Sequence[float],
    position_du: Sequence[float],
    position_dv: Sequence[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Build a deterministic tangent frame from macro-map coordinate derivatives."""
    normal = _normalized_normal(geometric_normal, "geometric normal")
    du = tuple(_finite(value, "position derivative") for value in position_du)
    dv = tuple(_finite(value, "position derivative") for value in position_dv)
    if len(du) != 3 or len(dv) != 3:
        raise ValueError("macro coordinate derivatives must have three components")
    dot_u = sum(du[j] * normal[j] for j in range(3))
    projected_u = tuple(du[i] - normal[i] * dot_u for i in range(3))
    if not all(math.isfinite(value) for value in projected_u):
        raise ValueError("macro coordinate derivatives must produce a finite tangent frame")
    tangent_length = math.hypot(*projected_u)
    fallback_tangent = tangent_length <= 1e-12
    if fallback_tangent:
        axis = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 0.0, 1.0)
        projected_u = tuple(axis[i] - normal[i] * sum(axis[j] * normal[j] for j in range(3))
                            for i in range(3))
        tangent_length = math.hypot(*projected_u)
    tangent = tuple(value / tangent_length for value in projected_u)
    dot_v = sum(dv[j] * normal[j] for j in range(3))
    projected_v = tuple(dv[i] - normal[i] * dot_v
                        for i in range(3))
    if not all(math.isfinite(value) for value in projected_v):
        raise ValueError("macro coordinate derivatives must produce a finite tangent frame")
    projected_v_length = math.hypot(*projected_v)
    if fallback_tangent or projected_v_length <= 1e-12:
        handedness = 1.0
    else:
        projected_v = tuple(value / projected_v_length for value in projected_v)
        cross = (
            tangent[1] * projected_v[2] - tangent[2] * projected_v[1],
            tangent[2] * projected_v[0] - tangent[0] * projected_v[2],
            tangent[0] * projected_v[1] - tangent[1] * projected_v[0],
        )
        handedness = -1.0 if sum(cross[i] * normal[i] for i in range(3)) < 0.0 else 1.0
    bitangent = (
        handedness * (normal[1] * tangent[2] - normal[2] * tangent[1]),
        handedness * (normal[2] * tangent[0] - normal[0] * tangent[2]),
        handedness * (normal[0] * tangent[1] - normal[1] * tangent[0]),
    )
    return tangent, bitangent, normal


def normal_to_macro_frame(
    world_normal: Sequence[float],
    frame: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    """Transform a world normal into a (tangent, bitangent, normal) frame."""
    normal = _normalized_normal(world_normal, "world normal")
    if len(frame) != 3:
        raise ValueError("macro tangent frame must have three axes")
    axes = tuple(_normalized_normal(axis, "macro tangent frame axis") for axis in frame)
    return _normalized_normal(tuple(sum(normal[i] * axis[i] for i in range(3)) for axis in axes),
                              "transformed tangent normal")


def normal_from_macro_frame(
    tangent_normal: Sequence[float],
    frame: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    """Transform a macro-frame normal back to world space."""
    normal = _normalized_normal(tangent_normal, "tangent normal")
    if len(frame) != 3:
        raise ValueError("macro tangent frame must have three axes")
    axes = tuple(_normalized_normal(axis, "macro tangent frame axis") for axis in frame)
    return _normalized_normal(tuple(
        sum(normal[axis] * frame_axis[component] for axis, frame_axis in enumerate(axes))
        for component in range(3)
    ), "world normal")


def _bounded_offset(x: float, y: float, scale: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length > scale:
        return x * scale / length, y * scale / length
    return x, y


def height_blend_weights(
    weights: Sequence[float],
    heights: Sequence[float],
    transition: float = 0.2,
    strength: float = 1.0,
    present: Sequence[bool] | None = None,
) -> list[float]:
    """Blend normalized base weights toward stable height-aware weights.

    Missing maps use neutral height 0.5. If no map is present, this returns the
    normalized base weights unchanged.
    """
    count = len(weights)
    if len(heights) != count or (present is not None and len(present) != count):
        raise ValueError("weights, heights, and presence flags must have equal lengths")
    base = _normalized_weights(weights)
    strength = _unit(strength, "height blend strength")
    transition = _finite(transition, "height blend transition")
    if transition <= 0.0:
        raise ValueError("height blend transition must be positive")
    if strength == 0.0 or present is not None and not any(present):
        return base
    has_height = [True] * count if present is None else list(present)
    values = [
        _unit(value, "surface height") if has_map else 0.5
        for value, has_map in zip(heights, has_height)
    ]
    if sum(value > 0.0 for value in base) == 1:
        return base
    highest = max(height for weight, height in zip(base, values) if weight > 0.0)
    scaled = [
        weight * math.exp(max(-80.0, min(0.0, (height - highest) / transition)))
        for weight, height in zip(base, values)
    ]
    denominator = sum(scaled)
    aware = [value / denominator for value in scaled]
    result = [(1.0 - strength) * old + strength * new for old, new in zip(base, aware)]
    total = sum(result)
    return [value / total for value in result]


def parallax_offset(
    uv: Sequence[float],
    view_tangent: Sequence[float],
    height: float,
    reference_height: float = 0.5,
    scale: float = 0.05,
    minimum_view_z: float = 0.1,
) -> tuple[float, float]:
    """Return the two-component tangent-UV offset for a single-step parallax ray."""
    if len(uv) != 2 or len(view_tangent) != 3:
        raise ValueError("UV and tangent-space view direction must have 2 and 3 components")
    x, y = (_finite(v, "UV") for v in uv)
    vx, vy, vz = (_finite(v, "view direction") for v in view_tangent)
    height = _unit(height, "surface height")
    reference_height = _unit(reference_height, "reference height")
    scale = _finite(scale, "parallax scale")
    minimum_view_z = _finite(minimum_view_z, "minimum view z")
    if scale < 0.0 or not 0.0 < minimum_view_z <= 1.0:
        raise ValueError("parallax scale must be non-negative and minimum view z must be in (0, 1]")
    length = math.sqrt(vx * vx + vy * vy + vz * vz)
    if length <= 1e-12:
        raise ValueError("view direction must be non-zero")
    vx, vy, vz = vx / length, vy / length, vz / length
    if vz <= 0.0 or scale == 0.0:
        return (0.0, 0.0)
    depth = (height - reference_height) * scale
    denominator = max(vz, minimum_view_z)
    return _bounded_offset(-vx / denominator * depth, -vy / denominator * depth, scale)


def parallax_occlusion(
    uv: Sequence[float],
    view_tangent: Sequence[float],
    sample_height: Callable[[tuple[float, float]], float],
    scale: float = 0.05,
    min_steps: int = 8,
    max_steps: int = 32,
    minimum_view_z: float = 0.1,
) -> tuple[tuple[float, float], int]:
    """Ray-march a linear height field and return refined UV offset and step count."""
    if len(uv) != 2 or len(view_tangent) != 3:
        raise ValueError("UV and tangent-space view direction must have 2 and 3 components")
    x, y = (_finite(v, "UV") for v in uv)
    vx, vy, vz = (_finite(v, "view direction") for v in view_tangent)
    scale = _finite(scale, "parallax scale")
    minimum_view_z = _finite(minimum_view_z, "minimum view z")
    if scale < 0.0 or not 0.0 < minimum_view_z <= 1.0:
        raise ValueError("parallax scale must be non-negative and minimum view z must be in (0, 1]")
    if not isinstance(min_steps, int) or not isinstance(max_steps, int) or not 1 <= min_steps <= max_steps <= 256:
        raise ValueError("POM steps must satisfy 1 <= min_steps <= max_steps <= 256")
    length = math.sqrt(vx * vx + vy * vy + vz * vz)
    if length <= 1e-12:
        raise ValueError("view direction must be non-zero")
    vx, vy, vz = vx / length, vy / length, vz / length
    if vz <= 0.0 or scale == 0.0:
        return (0.0, 0.0), 0

    cosine = min(1.0, vz)
    count = round(min_steps + (max_steps - min_steps) * (1.0 - cosine))
    denominator = max(minimum_view_z, cosine)
    ray_u, ray_v = _bounded_offset(-vx / denominator * scale, -vy / denominator * scale, scale)
    previous_depth = 0.0
    initial_height = _unit(sample_height((x, y)), "sampled height")
    previous_delta = -(1.0 - initial_height)
    if previous_delta >= 0.0:
        return (0.0, 0.0), 0
    for index in range(1, count + 1):
        depth = index / count
        sampled = _unit(sample_height((x + ray_u * depth, y + ray_v * depth)), "sampled height")
        delta = depth - (1.0 - sampled)
        if delta >= 0.0:
            fraction = 0.0 if delta == previous_delta else -previous_delta / (delta - previous_delta)
            refined = previous_depth + (depth - previous_depth) * min(1.0, max(0.0, fraction))
            return (ray_u * refined, ray_v * refined), index
        previous_depth, previous_delta = depth, delta
    return (ray_u, ray_v), count
