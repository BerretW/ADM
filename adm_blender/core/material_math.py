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
    return (-vx / denominator * depth, -vy / denominator * depth)


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

    cosine = max(minimum_view_z, min(1.0, vz))
    count = round(min_steps + (max_steps - min_steps) * (1.0 - cosine))
    ray_u = -vx / cosine * scale
    ray_v = -vy / cosine * scale
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
