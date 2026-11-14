"""Reference scalar/vector evaluators for deterministic ADM shader-profile math."""

import math

VERTEX_CONTROL_DEFAULTS = {
    "tintOffset": 0.0,
    "normalMultiplier": 1.0,
    "reflectionMultiplier": 1.0,
    "wetnessOffset": 0.0,
}
COLOR0_DEFAULT = (0.0, 1.0, 1.0, 0.0)


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, float(value)))


def srgb_to_linear(value):
    value = float(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def tint_palette_index(position, offset, palette_size):
    if type(palette_size) is not int or palette_size < 1:
        raise ValueError("palette_size must be a positive integer")
    index = math.floor(clamp(position) * palette_size + float(offset))
    return min(palette_size - 1, max(0, index))


def vertex_tint(base_rgba, palette_rgba, mode="MULTIPLY"):
    """Apply one sRGB palette entry to linear base RGBA."""
    if len(base_rgba) != 4 or len(palette_rgba) != 4:
        raise ValueError("base and palette colors must be RGBA")
    palette = tuple(srgb_to_linear(c) for c in palette_rgba[:3]) + (float(palette_rgba[3]),)
    if mode == "MULTIPLY":
        return tuple(float(base_rgba[i]) * palette[i] for i in range(4))
    if mode == "REPLACE":
        return palette[:3] + (float(base_rgba[3]),)
    raise ValueError("tint mode must be MULTIPLY or REPLACE")


def vertex_control_normal(normal_rgb, base_scale, color0_green, multiplier):
    """Scale tangent-space xy by the control, retain z, and normalize."""
    if normal_rgb is None:
        return None
    q = tuple(2.0 * float(channel) - 1.0 for channel in normal_rgb[:3])
    strength = float(base_scale) * clamp(float(color0_green) * float(multiplier))
    scaled = (q[0] * strength, q[1] * strength, q[2])
    length = math.sqrt(sum(component * component for component in scaled))
    if not math.isfinite(length) or length <= 1e-12:
        raise ValueError("scaled tangent-space normal must be nonzero and finite")
    return tuple(component / length for component in scaled)


def vertex_control_f0(f0, color0_blue, multiplier):
    """Scale linear dielectric/metal mixture F0, without changing diffuse color."""
    scale = clamp(float(color0_blue) * float(multiplier))
    if isinstance(f0, (int, float)):
        return float(f0) * scale
    return tuple(float(component) * scale for component in f0)


def vertex_control_wetness(base_rgb, base_roughness, f0, color0_alpha, offset):
    """Return wet base RGB, roughness, effective F0 and effective wetness."""
    wetness = clamp(float(color0_alpha) + float(offset))
    color_scale = 1.0 - 0.15 * wetness
    color = tuple(float(component) * color_scale for component in base_rgb)
    roughness = float(base_roughness)
    wet_roughness = roughness + (min(roughness, 0.10) - roughness) * wetness
    water_f0 = ((1.333 - 1.0) / (1.333 + 1.0)) ** 2
    if isinstance(f0, (int, float)):
        base_f0 = float(f0)
        coat_f0 = water_f0 + (1.0 - water_f0) ** 2 * base_f0
        effective_f0 = base_f0 + (coat_f0 - base_f0) * wetness
    else:
        base_f0 = tuple(float(component) for component in f0)
        coat_f0 = tuple(water_f0 + (1.0 - water_f0) ** 2 * component for component in base_f0)
        effective_f0 = tuple(base + (coat - base) * wetness for base, coat in zip(base_f0, coat_f0))
    return color, wet_roughness, effective_f0, wetness


def schlick(cos_theta, ior):
    c = clamp(abs(cos_theta))
    f0 = ((float(ior) - 1.0) / (float(ior) + 1.0)) ** 2
    return f0 + (1.0 - f0) * (1.0 - c) ** 5


def cutout_keep(base_alpha, texture_alpha, cutoff):
    return float(base_alpha) * float(texture_alpha) >= float(cutoff)


def straight_alpha(source, alpha, destination):
    a = clamp(alpha)
    return tuple(float(s) * a + float(d) * (1.0 - a) for s, d in zip(source, destination))


def emissive(factor, texture_rgb=None):
    tex = (1.0, 1.0, 1.0) if texture_rgb is None else tuple(srgb_to_linear(c) for c in texture_rgb)
    return tuple(float(f) * t for f, t in zip(factor, tex))


def glass(cos_theta, ior, transparency, glass_tint, reflection_tint):
    f = schlick(cos_theta, ior)
    color = tuple(float(g) * (1.0 - f) + float(r) * f for g, r in zip(glass_tint, reflection_tint))
    alpha = 1.0 - clamp(transparency) * (1.0 - f)
    return color, alpha


def foliage_color(base_color, backface_tint, transmission, back_facing):
    weight = clamp(transmission) if back_facing else 0.0
    return tuple(float(c) * ((1.0 - weight) + float(t) * weight)
                 for c, t in zip(base_color, backface_tint))


def terrain_weights(mask_rgba):
    weights = [max(0.0, float(c)) for c in mask_rgba]
    total = sum(weights)
    return (1.0, 0.0, 0.0, 0.0) if total == 0.0 else tuple(c / total for c in weights)


def terrain_color(mask_rgba, layer_colors):
    weights = terrain_weights(mask_rgba)
    return tuple(sum(weights[i] * float(layer_colors[i][channel]) for i in range(4)) for channel in range(3))


def wrapped_diffuse(ndotl, strength):
    s = clamp(strength)
    return max(0.0, min(1.0, (float(ndotl) + s) / (1.0 + s)))


def triplanar_weights(normal):
    weights = [abs(float(n)) ** 4 for n in normal]
    total = sum(weights)
    if total == 0.0 or not math.isfinite(total):
        return (0.0, 1.0, 0.0)
    return tuple(value / total for value in weights)


def weather_color(base_color, tint, mask, amount, darken=0.35):
    weight = clamp(float(mask) * float(amount))
    return tuple(float(a) * (1.0 - weight) + float(a) * float(darken) * weight
                 for a in base_color)


def brick(brick_rgb, mortar_rgb, mortar_mask, brick_roughness, mortar_roughness, dirt_mask=None):
    """adm.building.brick@1.0.0: returns (linear rgb, roughness)."""
    m = clamp(mortar_mask)
    color = [float(b) * (1.0 - m) + float(o) * m for b, o in zip(brick_rgb, mortar_rgb)]
    if dirt_mask is not None:
        k = 1.0 + (0.35 - 1.0) * clamp(dirt_mask)
        color = [c * k for c in color]
    return tuple(color), float(brick_roughness) * (1.0 - m) + float(mortar_roughness) * m


def mortar_mask_pixels(width, height, rows, columns, mortar, offset=0.5):
    """Running-bond mortar mask (1 = mortar) as float32 array (height, width), bottom row first.

    ``mortar`` is the joint width as a fraction of one brick row height; odd rows shift by ``offset`` bricks.
    """
    import numpy as np
    v = (np.arange(height, dtype=np.float64) + 0.5) / height * rows
    u = (np.arange(width, dtype=np.float64) + 0.5) / width * columns
    row = np.floor(v)
    fv = v - row
    half = mortar * 0.5
    horiz = (fv < half) | (fv > 1.0 - half)
    uu = u[None, :] + (row[:, None] % 2) * offset
    fu = uu - np.floor(uu)
    # Same joint width in UV space as the horizontal joints: (mortar / rows) UV = mortar * columns / rows bricks.
    half_u = half * columns / rows
    vert = (fu < half_u) | (fu > 1.0 - half_u)
    return (horiz[:, None] | vert).astype(np.float32)
