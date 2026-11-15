"""Terrain zone classification and TERRAIN_4 blend masks.

Channels follow ``adm.terrain.four_layer``: R/G/B/A weight layers 0/1/2/3.
Layer 0 = ground (everything else), 1 = rock (steep slopes), 2 = snow (high
altitude), 3 = water / shore (low altitude).  Weights always sum to one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from numba import njit, prange

LAYERS = (
    {"channel": "R", "layer": 0, "name": "ground", "color": [96, 128, 62]},
    {"channel": "G", "layer": 1, "name": "rock", "color": [128, 118, 108]},
    {"channel": "B", "layer": 2, "name": "snow", "color": [236, 240, 246]},
    {"channel": "A", "layer": 3, "name": "water", "color": [44, 96, 150]},
)


@dataclass
class ZoneRules:
    water: bool = True
    water_level_m: float = 0.0  # fully water at and below this height
    shore_m: float = 2.0  # blend band above the water level
    snow: bool = True
    snow_start_m: float = 400.0  # snow starts fading in
    snow_full_m: float = 450.0  # full snow
    rock_start_deg: float = 30.0  # rock starts fading in
    rock_full_deg: float = 45.0  # full rock
    snow_max_slope_deg: float = 55.0  # snow slides off steeper terrain

    def as_array(self) -> np.ndarray:
        return np.array([
            1.0 if self.water else 0.0, self.water_level_m, self.shore_m,
            1.0 if self.snow else 0.0, self.snow_start_m, self.snow_full_m,
            self.rock_start_deg, self.rock_full_deg, self.snow_max_slope_deg,
        ], np.float64)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ZoneRules":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in fields})


def suggest_rules(heights_m: np.ndarray) -> ZoneRules:
    """Starting thresholds from the height distribution (preview array in metres)."""
    lo = float(heights_m.min())
    hi = float(heights_m.max())
    span = max(hi - lo, 1e-6)
    p85, p95 = (float(v) for v in np.percentile(heights_m, (85, 95)))
    return ZoneRules(
        water_level_m=round(lo + 0.02 * span, 2),
        shore_m=round(max(0.5, 0.01 * span), 2),
        snow_start_m=round(p85, 2),
        snow_full_m=round(max(p95, p85 + 0.01 * span), 2),
    )


@njit(cache=True, inline="always")
def _smoothstep(edge0, edge1, x):
    if edge1 <= edge0:
        return 1.0 if x >= edge0 else 0.0
    t = (x - edge0) / (edge1 - edge0)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


@njit(cache=True, inline="always")
def _bilinear(h, w, hgt, x, y):
    if x < 0.0:
        x = 0.0
    elif x > w - 1:
        x = w - 1.0
    if y < 0.0:
        y = 0.0
    elif y > hgt - 1:
        y = hgt - 1.0
    x0 = min(int(x), w - 2)
    y0 = min(int(y), hgt - 2)
    fx = x - x0
    fy = y - y0
    top = h[y0, x0] * (1.0 - fx) + h[y0, x0 + 1] * fx
    bottom = h[y0 + 1, x0] * (1.0 - fx) + h[y0 + 1, x0 + 1] * fx
    return top * (1.0 - fy) + bottom * fy


@njit(cache=True, inline="always")
def _weights(h, scale, offset, w, hgt, gx, gy, spacing, radius, rules):
    z = _bilinear(h, w, hgt, gx, gy) * scale + offset
    xl = max(0.0, gx - radius)
    xr = min(w - 1.0, gx + radius)
    yn = max(0.0, gy - radius)
    ys = min(hgt - 1.0, gy + radius)
    dzdx = (_bilinear(h, w, hgt, xr, gy) - _bilinear(h, w, hgt, xl, gy)) * scale / ((xr - xl) * spacing)
    dzdy = (_bilinear(h, w, hgt, gx, ys) - _bilinear(h, w, hgt, gx, yn)) * scale / ((ys - yn) * spacing)
    slope = math.degrees(math.atan(math.sqrt(dzdx * dzdx + dzdy * dzdy)))
    rock = _smoothstep(rules[6], rules[7], slope)
    snow = 0.0
    if rules[3] > 0.0:
        snow = _smoothstep(rules[4], rules[5], z) * (1.0 - _smoothstep(rules[8] - 10.0, rules[8], slope))
    water = 0.0
    if rules[0] > 0.0:
        water = 1.0 - _smoothstep(rules[1], rules[1] + rules[2], z)
    # Priority water > snow > rock > ground; the products keep the sum at one.
    w_water = water
    w_snow = (1.0 - water) * snow
    w_rock = (1.0 - water) * (1.0 - snow) * rock
    w_ground = 1.0 - w_water - w_snow - w_rock
    return w_ground, w_rock, w_snow, w_water


@njit(cache=True, nogil=True)
def tile_mask(h, scale, offset, w, hgt, x0, y0, x1, y1, rx, ry, spacing, radius, rules):
    """RGBA uint8 mask whose pixel centres span the grid rectangle exactly.

    Edge pixels sit on the tile border, so neighbouring tiles produce identical
    edge pixels and the half-texel-inset mask UV shows no seam.
    """
    out = np.empty((ry, rx, 4), np.uint8)
    for r in range(ry):
        gy = y0 + (y1 - y0) * r / (ry - 1)
        for c in range(rx):
            gx = x0 + (x1 - x0) * c / (rx - 1)
            a, b, s, wt = _weights(h, scale, offset, w, hgt, gx, gy, spacing, radius, rules)
            out[r, c, 0] = int(a * 255.0 + 0.5)
            out[r, c, 1] = int(b * 255.0 + 0.5)
            out[r, c, 2] = int(s * 255.0 + 0.5)
            out[r, c, 3] = int(wt * 255.0 + 0.5)
    return out


@njit(cache=True, parallel=True)
def classify_points(h, scale, offset, w, hgt, gx, gy, spacing, radius, rules):
    """Float32 (n, 4) layer weights at grid positions ``gx``/``gy``."""
    out = np.empty((gx.shape[0], 4), np.float32)
    for i in prange(gx.shape[0]):
        a, b, s, wt = _weights(h, scale, offset, w, hgt, gx[i], gy[i], spacing, radius, rules)
        out[i, 0] = a
        out[i, 1] = b
        out[i, 2] = s
        out[i, 3] = wt
    return out


def layer_colors() -> np.ndarray:
    return np.array([layer["color"] for layer in LAYERS], np.float32) / 255.0


def zones_preview(data: np.ndarray, scale: float, offset: float, spacing: float,
                  rules: ZoneRules, max_side: int = 1024, shade: np.ndarray | None = None) -> np.ndarray:
    """RGB uint8 preview of the zones over the whole map (row 0 = north)."""
    rows, cols = data.shape
    step = max(1, int(math.ceil(max(rows, cols) / max_side)))
    gy, gx = np.mgrid[0:rows:step, 0:cols:step]
    shape = gx.shape
    weights = classify_points(data, scale, offset, cols, rows,
                              gx.ravel().astype(np.float64), gy.ravel().astype(np.float64),
                              spacing, float(max(1, step // 2)), rules.as_array())
    rgb = weights @ layer_colors()
    if shade is not None and shade.shape == shape:
        rgb *= (0.45 + 0.55 * shade.astype(np.float32) / 255.0).ravel()[:, None]
    return np.clip(rgb * 255.0, 0, 255).astype(np.uint8).reshape(shape + (3,))
