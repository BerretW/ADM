"""Reference scalar/vector evaluators for deterministic ADM shader-profile math."""

import math


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, float(value)))


def srgb_to_linear(value):
    value = float(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


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
