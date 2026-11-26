"""Surface weights from biomes: the per-vertex ``COLOR_1`` layers of the terrain.

For a point the field works in three steps:

1. **Biome weights.** Automatic biomes are layered by priority (a later biome takes its band
   factor of whatever the earlier ones left; biome 0 keeps the rest).  Painted cells replace the
   automatic result; the paint map is sampled bilinearly and softened over ``paint_softness_m``.
2. **Inner weights.** Each biome layers its own surfaces the same way (base surface first).
3. **Bridge.** With ``D`` the strongest and ``E`` the second biome and ``t = bE / (bD + bE)``
   (0 inside ``D``, 0.5 on the border) the result is ``lerp(inner(D), bridge(D, E), 2t)``.
   The bridge only contains surfaces both biomes share, so crossing the border fades D's own
   surfaces into the shared ones and then into E's — nothing jumps.  When two biomes share
   nothing the field falls back to ``lerp(inner(D), inner(E), t)`` and :func:`check_neighbours`
   reports the pair.

A point therefore never uses more than four surfaces (those of ``D``), and near borders mostly
the shared ones, which keeps primitive splitting in the exporter cheap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numba import njit, prange

from .kernels import _side, decode
from .material import PAINT_AUTO, PAINT_MAX_SIDE, SURFACES_PER_BIOME, Band, TerrainMaterial
from .roads import rasterize

OPEN = 1.0e30
_CFG_SCALE, _CFG_OFFSET, _CFG_SPACING, _CFG_RADIUS, _CFG_CELL, _CFG_NCH, _CFG_MAP = range(7)


@dataclass
class Rules:
    """A material compiled to arrays for the kernels."""

    brule: np.ndarray  # (N, 7) auto, hmin, hmax, hfade, smin, smax, sfade
    bsurf: np.ndarray  # (N, 4) global surface index, -1 = unused
    srule: np.ndarray  # (N, 4, 7) hmin, hmax, hfade, smin, smax, sfade, strength
    # (1 + C, rows, cols) uint8 shares 0..255 of the softened paint: channel 0 = automatic,
    # channel c = biome ``paint_biomes[c - 1]``. One pixel covers ``paint_cell`` heightmap samples.
    paint: np.ndarray
    nsurf: int
    slope_radius_m: float
    paint_cell: float
    paint_biomes: list[int]

    def cfg(self, scale: float, offset: float, spacing: float) -> np.ndarray:
        radius = max(1.0, self.slope_radius_m / spacing)
        return np.array([scale, offset, spacing, radius, float(self.paint_cell), float(len(self.paint_biomes))]
                        + [float(b) for b in self.paint_biomes], np.float64)


def _band_row(band: Band) -> list[float]:
    return [-OPEN if band.min is None else band.min, OPEN if band.max is None else band.max, band.fade]


def _box_blur(a: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """Running mean over ``2 * radius + 1`` pixels with clamped edges."""
    if radius < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (radius + 1, radius)
    total = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    upper = np.take(total, np.arange(2 * radius + 1, n + 2 * radius + 1), axis=axis)
    lower = np.take(total, np.arange(n), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)


def soften_paint(paint: np.ndarray, biomes: list[int], soft: float, max_step: int | None = None) -> tuple[np.ndarray, int]:
    """Smooth shares of the automatic rules and each painted biome; returns ``(field, step)``.

    The shares are averaged over ``step`` x ``step`` paint pixels and blurred twice with a box of
    half the softness (a tent about ``soft`` pixels wide on each side of a border), so a painted
    border fades evenly instead of in steps.
    """
    step = max(1, int(soft // 2))
    if max_step is not None:
        step = min(step, max_step)
    rows, cols = paint.shape
    pr, pc = -rows % step, -cols % step
    padded = np.pad(paint, ((0, pr), (0, pc)), mode="edge") if pr or pc else paint
    shape = (padded.shape[0] // step, step, padded.shape[1] // step, step)
    radius = int(round(soft / (2.0 * step)))
    field = np.empty((1 + len(biomes),) + shape[::2], np.uint8)
    for c, value in enumerate([PAINT_AUTO] + list(biomes)):
        share = (padded == value).reshape(shape).mean(axis=(1, 3), dtype=np.float32)
        for _ in range(2):
            share = _box_blur(_box_blur(share, radius, 0), radius, 1)
        field[c] = np.clip(np.rint(share * 255.0), 0, 255).astype(np.uint8)
    return field, step


def compile_rules(material: TerrainMaterial, spacing_m: float, width: int, height: int) -> Rules:
    material.validate_rules()
    names = material.surface_names()
    original_n = len(material.biomes)
    use_surfaces = material.has_surface_paint() or bool(material.roads)
    n = original_n + (len(names) if use_surfaces else 0)
    brule = np.zeros((n, 7), np.float64)
    bsurf = np.full((n, SURFACES_PER_BIOME), -1, np.int32)
    srule = np.zeros((n, SURFACES_PER_BIOME, 7), np.float64)
    for k, biome in enumerate(material.biomes):
        brule[k] = [1.0 if biome.auto else 0.0] + _band_row(biome.height) + _band_row(biome.slope)
        for j, entry in enumerate(biome.surfaces):
            bsurf[k, j] = names.index(entry.surface)
            srule[k, j] = _band_row(entry.height) + _band_row(entry.slope) + [entry.strength]
    if use_surfaces:
        for i in range(len(names)):
            brule[original_n + i, 0] = -1.0
            bsurf[original_n + i, 0] = i
    if material.has_paint() or use_surfaces:
        cell = max(1, math.ceil(max(width, height) / PAINT_MAX_SIDE))
        rows, cols = math.ceil(height / cell), math.ceil(width / cell)
        paint = np.full((rows, cols), PAINT_AUTO, np.uint8)
        if material.has_paint():
            if material.paint_cell != cell or material.paint.shape != paint.shape:
                raise ValueError("The biome paint was made for a heightmap of another size; clear it or repaint")
            paint[:] = np.where(material.paint >= original_n, PAINT_AUTO, material.paint)
        if material.has_surface_paint():
            if material.surface_paint_cell != cell or material.surface_paint.shape != paint.shape:
                raise ValueError("The surface paint was made for a heightmap of another size; clear it or repaint")
            if np.any((material.surface_paint >= len(names)) & (material.surface_paint != PAINT_AUTO)):
                raise ValueError("Surface paint references a missing surface")
            mask = material.surface_paint < len(names)
            paint[mask] = original_n + material.surface_paint[mask]
        biomes = [int(v) for v in np.unique(paint) if v != PAINT_AUTO]
        max_step = None
        if material.roads:
            for road in material.roads:
                road.validate(width, height)
                if road.width_m < spacing_m * cell:
                    raise ValueError("Road width is smaller than the surface paint resolution")
                index = original_n + names.index(road.surface)
                if index not in biomes:
                    biomes.append(index)
            max_step = max(1, int(min(road.width_m for road in material.roads) / (2 * spacing_m * cell)))
        field, step = soften_paint(paint, biomes, material.paint_softness_m / (spacing_m * cell), max_step)
        for road in material.roads:
            for window, distance, _ in rasterize(road, spacing_m, field.shape[1], field.shape[2], cell * step,
                                                 cell_centres=True):
                if road.shoulder_m:
                    alpha = np.clip((road.width_m / 2 + road.shoulder_m - distance) / road.shoulder_m, 0, 1)
                    alpha = alpha * alpha * (3 - 2 * alpha)
                else:
                    alpha = (distance <= road.width_m / 2).astype(np.float32)
                channel = biomes.index(original_n + names.index(road.surface)) + 1
                area = field[(slice(None),) + window]
                faded = area.astype(np.float32) * (1 - alpha)
                faded[channel] += alpha * 255
                area[:] = np.clip(np.rint(faded), 0, 255).astype(np.uint8)
        return Rules(brule, bsurf, srule, field, len(names), material.slope_radius_m, float(cell * step), biomes)
    return Rules(brule, bsurf, srule, np.full((1, 1, 1), 255, np.uint8), len(names), material.slope_radius_m,
                 1.0, [])


# ------------------------------------------------------------------------------- kernels
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
def _band(x, lo, hi, fade):
    f = 1.0
    half = 0.5 * fade
    if lo > -OPEN:
        f *= _smoothstep(lo - half, lo + half, x)
    if hi < OPEN:
        f *= 1.0 - _smoothstep(hi - half, hi + half, x)
    return f


@njit(cache=True, inline="always")
def _bilinear(h, x, y):
    hgt, w = h.shape
    if x < 0.0:
        x = 0.0
    elif x > w - 1:
        x = w - 1.0
    if y < 0.0:
        y = 0.0
    elif y > hgt - 1:
        y = hgt - 1.0
    x0 = min(int(x), max(w - 2, 0))
    y0 = min(int(y), max(hgt - 2, 0))
    x1 = min(x0 + 1, w - 1)
    y1 = min(y0 + 1, hgt - 1)
    fx = x - x0
    fy = y - y0
    top = h[y0, x0] * (1.0 - fx) + h[y0, x1] * fx
    bottom = h[y1, x0] * (1.0 - fx) + h[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


@njit(cache=True, inline="always")
def _terrain(h, cfg, gx, gy):
    """Height (m) and slope (deg) at a grid position."""
    hgt, w = h.shape
    scale = cfg[_CFG_SCALE]
    z = _bilinear(h, gx, gy) * scale + cfg[_CFG_OFFSET]
    r = cfg[_CFG_RADIUS]
    xl = max(0.0, gx - r)
    xr = min(w - 1.0, gx + r)
    yn = max(0.0, gy - r)
    ys = min(hgt - 1.0, gy + r)
    sp = cfg[_CFG_SPACING]
    dzdx = 0.0
    dzdy = 0.0
    if xr > xl:
        dzdx = (_bilinear(h, xr, gy) - _bilinear(h, xl, gy)) * scale / ((xr - xl) * sp)
    if ys > yn:
        dzdy = (_bilinear(h, gx, ys) - _bilinear(h, gx, yn)) * scale / ((ys - yn) * sp)
    return z, math.degrees(math.atan(math.sqrt(dzdx * dzdx + dzdy * dzdy)))


@njit(cache=True, inline="always")
def _field_tap(field, c, r0, r1, c0, c1, fu, fv):
    top = field[c, r0, c0] * (1.0 - fu) + field[c, r0, c1] * fu
    bottom = field[c, r1, c0] * (1.0 - fu) + field[c, r1, c1] * fu
    return top * (1.0 - fv) + bottom * fv


@njit(cache=True)
def _paint_weights(paint, cfg, gx, gy, pw):
    """Painted biome shares into ``pw``; returns the share left to the automatic rules."""
    pw[:] = 0.0
    nch = int(cfg[_CFG_NCH])
    if nch == 0:
        return 1.0
    rows, cols = paint.shape[1], paint.shape[2]
    cell = cfg[_CFG_CELL]
    u = min(max(gx / cell - 0.5, 0.0), cols - 1.0)
    v = min(max(gy / cell - 0.5, 0.0), rows - 1.0)
    c0 = int(u)
    r0 = int(v)
    c1 = min(c0 + 1, cols - 1)
    r1 = min(r0 + 1, rows - 1)
    fu = u - c0
    fv = v - r0
    auto = _field_tap(paint, 0, r0, r1, c0, c1, fu, fv)
    total = auto
    for c in range(nch):
        share = _field_tap(paint, c + 1, r0, r1, c0, c1, fu, fv)
        pw[int(cfg[_CFG_MAP + c])] += share
        total += share
    if total <= 0.0:
        pw[:] = 0.0
        return 1.0
    for k in range(pw.shape[0]):
        pw[k] /= total
    return auto / total


@njit(cache=True)
def _inner(k, z, slope, bsurf, srule, slots):
    """Surface weights of biome ``k`` into ``slots[0..3]`` (base surface keeps the remainder)."""
    remaining = 1.0
    for j in range(bsurf.shape[1] - 1, 0, -1):
        if bsurf[k, j] < 0:
            slots[j] = 0.0
            continue
        f = srule[k, j, 6] * _band(z, srule[k, j, 0], srule[k, j, 1], srule[k, j, 2]) \
            * _band(slope, srule[k, j, 3], srule[k, j, 4], srule[k, j, 5])
        slots[j] = remaining * f
        remaining -= slots[j]
    slots[0] = remaining


@njit(cache=True)
def _sample(h, cfg, gx, gy, brule, bsurf, srule, paint, b, pw, sd, se, out):
    """Surface weights at a grid position into ``out``; returns ``(dominant, second, second weight)``."""
    z, slope = _terrain(h, cfg, gx, gy)
    n = brule.shape[0]
    remaining = 1.0
    for k in range(n - 1, 0, -1):
        f = 0.0
        if brule[k, 0] > 0.0:
            f = _band(z, brule[k, 1], brule[k, 2], brule[k, 3]) * _band(slope, brule[k, 4], brule[k, 5], brule[k, 6])
        b[k] = remaining * f
        remaining -= b[k]
    b[0] = remaining
    auto = _paint_weights(paint, cfg, gx, gy, pw)
    for k in range(n):
        b[k] = b[k] * auto + pw[k]
    d = 0
    for k in range(1, n):
        if b[k] > b[d]:
            d = k
    e = -1
    for k in range(n):
        if k != d and (e < 0 or b[k] > b[e]):
            e = k
    out[:] = 0.0
    _inner(d, z, slope, bsurf, srule, sd)
    be = 0.0 if e < 0 else b[e]
    if be <= 1e-6:
        for j in range(bsurf.shape[1]):
            if bsurf[d, j] >= 0:
                out[bsurf[d, j]] += sd[j]
        return d, e, 0.0
    t = be / (b[d] + be)
    _inner(e, z, slope, bsurf, srule, se)
    shared = 0
    total = 0.0
    for i in range(bsurf.shape[1]):
        if bsurf[d, i] < 0:
            continue
        for j in range(bsurf.shape[1]):
            if bsurf[e, j] == bsurf[d, i]:
                shared += 1
                total += 0.5 * (sd[i] + se[j])
    if shared == 0 or brule[d, 0] < 0 or brule[e, 0] < 0:
        for j in range(bsurf.shape[1]):
            if bsurf[d, j] >= 0:
                out[bsurf[d, j]] += (1.0 - t) * sd[j]
            if bsurf[e, j] >= 0:
                out[bsurf[e, j]] += t * se[j]
        return d, e, be
    mix = 2.0 * t
    for i in range(bsurf.shape[1]):
        s = bsurf[d, i]
        if s < 0:
            continue
        out[s] += (1.0 - mix) * sd[i]
        for j in range(bsurf.shape[1]):
            if bsurf[e, j] == s:
                bridge = 0.5 * (sd[i] + se[j]) / total if total > 1e-9 else 1.0 / shared
                out[s] += mix * bridge
    return d, e, be


@njit(cache=True, nogil=True)
def weights_serial(h, cfg, brule, bsurf, srule, paint, nsurf, gx, gy):
    """Like :func:`weights_at_points` on one thread; safe to call from worker threads."""
    n = brule.shape[0]
    out = np.empty((gx.shape[0], nsurf), np.float32)
    b = np.empty(n)
    pw = np.empty(n)
    sd = np.empty(SURFACES_PER_BIOME)
    se = np.empty(SURFACES_PER_BIOME)
    w = np.empty(nsurf)
    for i in range(gx.shape[0]):
        _sample(h, cfg, float(gx[i]), float(gy[i]), brule, bsurf, srule, paint, b, pw, sd, se, w)
        for s in range(nsurf):
            out[i, s] = w[s]
    return out


@njit(cache=True, parallel=True)
def weights_at_points(h, cfg, brule, bsurf, srule, paint, nsurf, gx, gy):
    """Float32 ``(n, nsurf)`` surface weights at grid positions."""
    n = brule.shape[0]
    out = np.empty((gx.shape[0], nsurf), np.float32)
    chunk = 1024
    for c in prange((gx.shape[0] + chunk - 1) // chunk):
        b = np.empty(n)
        pw = np.empty(n)
        sd = np.empty(SURFACES_PER_BIOME)
        se = np.empty(SURFACES_PER_BIOME)
        w = np.empty(nsurf)
        for i in range(c * chunk, min(gx.shape[0], (c + 1) * chunk)):
            _sample(h, cfg, float(gx[i]), float(gy[i]), brule, bsurf, srule, paint, b, pw, sd, se, w)
            for s in range(nsurf):
                out[i, s] = w[s]
    return out


@njit(cache=True, parallel=True)
def field_preview(h, cfg, brule, bsurf, srule, paint, nsurf, step, bcolor, scolor):
    """Map previews every ``step`` samples: biome RGB, surface RGB (linear 0..1), dominant and second biome."""
    hgt, w = h.shape
    rows = (hgt + step - 1) // step
    cols = (w + step - 1) // step
    n = brule.shape[0]
    biome_rgb = np.zeros((rows, cols, 3), np.float32)
    surface_rgb = np.zeros((rows, cols, 3), np.float32)
    first = np.empty((rows, cols), np.int8)
    second = np.empty((rows, cols), np.int8)
    second_w = np.empty((rows, cols), np.float32)
    for r in prange(rows):
        b = np.empty(n)
        pw = np.empty(n)
        sd = np.empty(SURFACES_PER_BIOME)
        se = np.empty(SURFACES_PER_BIOME)
        out = np.empty(nsurf)
        for c in range(cols):
            d, e, be = _sample(h, cfg, float(c * step), float(r * step), brule, bsurf, srule, paint, b, pw, sd, se,
                               out)
            first[r, c] = d
            second[r, c] = e
            second_w[r, c] = be
            for k in range(n):
                for ch in range(3):
                    biome_rgb[r, c, ch] += b[k] * bcolor[k, ch]
            for s in range(nsurf):
                for ch in range(3):
                    surface_rgb[r, c, ch] += out[s] * scolor[s, ch]
    return biome_rgb, surface_rgb, first, second, second_w


@njit(cache=True, parallel=True)
def weight_level_pass(h, cfg, brule, bsurf, srule, paint, nsurf, t, nx, ny, level, nonleaf_levels, lmin2,
                      werrors):
    """Texture error (0..255) per RTIN vertex for triangles whose legs are at least ``sqrt(lmin2)`` cells.

    The error is the largest difference between the field and the weights interpolated from the
    triangle corners, sampled on a lattice of about eight steps per leg.  Errors propagate from
    children to parents exactly like the height errors, so splits stay crack-free.
    """
    hgt, w = h.shape
    first_id = 1 << (level + 1)
    last_x = w - 1
    last_y = hgt - 1
    n = brule.shape[0]
    for phase in range(4):
        pi = phase & 1
        pj = phase >> 1
        nxp = (nx - pi + 1) // 2
        nyp = (ny - pj + 1) // 2
        for k in prange(nxp * nyp):
            ti = pi + 2 * (k % nxp)
            tj = pj + 2 * (k // nxp)
            ox = ti * t
            oy = tj * t
            b = np.empty(n)
            pw = np.empty(n)
            sd = np.empty(SURFACES_PER_BIOME)
            se = np.empty(SURFACES_PER_BIOME)
            wa = np.empty(nsurf)
            wb = np.empty(nsurf)
            wc = np.empty(nsurf)
            wp = np.empty(nsurf)
            for m in range(first_id):
                ax, ay, bx, by, cx, cy = decode(first_id + m, t)
                ax += ox
                bx += ox
                cx += ox
                ay += oy
                by += oy
                cy += oy
                leg2 = (cx - ax) * (cx - ax) + (cy - ay) * (cy - ay)
                if leg2 < lmin2 or _side(ax, ay, bx, by, cx, cy, last_x, last_y) != 0:
                    continue
                _sample(h, cfg, float(ax), float(ay), brule, bsurf, srule, paint, b, pw, sd, se, wa)
                _sample(h, cfg, float(bx), float(by), brule, bsurf, srule, paint, b, pw, sd, se, wb)
                _sample(h, cfg, float(cx), float(cy), brule, bsurf, srule, paint, b, pw, sd, se, wc)
                det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
                sign = 1 if det > 0 else -1
                x0 = min(ax, bx, cx)
                x1 = max(ax, bx, cx)
                y0 = min(ay, by, cy)
                y1 = max(ay, by, cy)
                stride = max(1, max(x1 - x0, y1 - y0) // 8)
                worst = 0.0
                for y in range(y0, y1 + 1, stride):
                    for x in range(x0, x1 + 1, stride):
                        nb = ((x - ax) * (cy - ay) - (cx - ax) * (y - ay)) * sign
                        nc = ((bx - ax) * (y - ay) - (x - ax) * (by - ay)) * sign
                        if nb < 0 or nc < 0 or nb + nc > det * sign:
                            continue
                        lb = nb / (det * sign)
                        lc = nc / (det * sign)
                        la = 1.0 - lb - lc
                        _sample(h, cfg, float(x), float(y), brule, bsurf, srule, paint, b, pw, sd, se, wp)
                        for s in range(nsurf):
                            d = abs(wp[s] - (la * wa[s] + lb * wb[s] + lc * wc[s]))
                            if d > worst:
                                worst = d
                e = min(255, int(math.ceil(worst * 255.0)))
                if level + 1 < nonleaf_levels:
                    lc_ = werrors[(cy + ay) >> 1, (cx + ax) >> 1]
                    rc_ = werrors[(by + cy) >> 1, (bx + cx) >> 1]
                    if lc_ > e:
                        e = lc_
                    if rc_ > e:
                        e = rc_
                my = (ay + by) >> 1
                mx = (ax + bx) >> 1
                if e > werrors[my, mx]:
                    werrors[my, mx] = e


# ------------------------------------------------------------------------------ python API
def surface_weights(rules: Rules, h: np.ndarray, scale: float, offset: float, spacing: float,
                    gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    return weights_at_points(h, rules.cfg(scale, offset, spacing), rules.brule, rules.bsurf, rules.srule,
                             rules.paint, rules.nsurf, np.ascontiguousarray(gx, np.float64),
                             np.ascontiguousarray(gy, np.float64))


def quantize(weights: np.ndarray) -> np.ndarray:
    """Float weights -> uint8 that sum to 255 per row (largest remainder)."""
    scaled = np.clip(weights, 0.0, None).astype(np.float64)
    total = scaled.sum(axis=1, keepdims=True)
    scaled = np.where(total > 0, scaled / np.maximum(total, 1e-12), 0.0) * 255.0
    base = np.floor(scaled).astype(np.int64)
    missing = 255 - base.sum(axis=1)
    order = np.argsort(-(scaled - base), axis=1, kind="stable")
    rows = np.arange(len(base))
    for k in range(scaled.shape[1]):
        add = missing > k
        base[rows[add], order[add, k]] += 1
    empty = total[:, 0] <= 0
    base[empty] = 0
    if len(base):
        base[empty, 0] = 255
    return base.astype(np.uint8)


def _linear(colors) -> np.ndarray:
    c = np.asarray(colors, np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _to_srgb8(rgb: np.ndarray) -> np.ndarray:
    c = np.clip(rgb, 0.0, 1.0)
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return (c * 255.0 + 0.5).astype(np.uint8)


@dataclass
class FieldPreview:
    step: int
    biomes: np.ndarray  # RGB uint8
    surfaces: np.ndarray  # RGB uint8
    problems: list[tuple[str, str]]  # neighbouring biomes without a shared surface


def preview(material: TerrainMaterial, data: np.ndarray, scale: float, offset: float, spacing: float,
            max_side: int = 1024, shade: np.ndarray | None = None) -> FieldPreview:
    """Biome and surface maps of the whole heightmap (row 0 = north) plus the neighbour check."""
    rows, cols = data.shape
    rules = compile_rules(material, spacing, cols, rows)
    step = max(1, int(math.ceil(max(rows, cols) / max_side)))
    bcolors = [b.color for b in material.biomes]
    if rules.brule.shape[0] > len(bcolors):
        bcolors.extend(s.color for s in material.surfaces)
    bcolor = _linear(bcolors)
    scolor = _linear([s.color for s in material.surfaces])
    biome_rgb, surface_rgb, first, second, second_w = field_preview(
        data, rules.cfg(scale, offset, spacing), rules.brule, rules.bsurf, rules.srule, rules.paint, rules.nsurf,
        step, bcolor, scolor)
    if shade is not None and shade.shape == biome_rgb.shape[:2]:
        light = (0.45 + 0.55 * shade.astype(np.float32) / 255.0)[..., None]
        biome_rgb *= light
        surface_rgb *= light
    return FieldPreview(step, _to_srgb8(biome_rgb), _to_srgb8(surface_rgb),
                        check_neighbours(material, first, second, second_w))


def check_neighbours(material: TerrainMaterial, first: np.ndarray, second: np.ndarray,
                     second_w: np.ndarray, threshold: float = 0.02) -> list[tuple[str, str]]:
    """Biome pairs that blend into each other somewhere but share no surface."""
    mask = (second >= 0) & (second_w > threshold)
    pairs = np.unique(np.stack([np.minimum(first[mask], second[mask]),
                                np.maximum(first[mask], second[mask])], axis=1), axis=0) if mask.any() else []
    problems = []
    for a, b in pairs:
        if a >= len(material.biomes) or b >= len(material.biomes):
            continue
        ba, bb = material.biomes[int(a)], material.biomes[int(b)]
        if not set(ba.surface_names()) & set(bb.surface_names()):
            problems.append((ba.name, bb.name))
    return problems


def unshared_pairs(material: TerrainMaterial) -> list[tuple[str, str]]:
    """Every biome pair without a shared surface, whether or not they touch."""
    out = []
    for i, a in enumerate(material.biomes):
        for b in material.biomes[i + 1:]:
            if not set(a.surface_names()) & set(b.surface_names()):
                out.append((a.name, b.name))
    return out
