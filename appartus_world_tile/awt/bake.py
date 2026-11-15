"""Bake the terrain material into one preview image for the 3D viewer.

The result approximates what ``four_layer@2.0.0`` shows: each surface's albedo repeated
``uv_scale`` times per tile and tinted, blended by the LOD0 vertex weights (COLOR_1) as the
shader interpolates them across triangles. Lighting and normal maps are left out.
"""

from __future__ import annotations

import io
import math
import os
import threading

import numba as nb
import numpy as np

from .material import Surface, TerrainMaterial, prepare_texture
from .ply import read_ply, weight_fields

MAX_SIDE = 4096
MAX_TILE_PX = 1024

_albedo_cache: dict[tuple, np.ndarray] = {}
_lock = threading.Lock()


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _albedo(path: str, side: int) -> np.ndarray:
    """Linear RGB float32 (side, side, 3) of a texture, cached."""
    from PIL import Image

    stat = os.stat(path)
    key = (os.path.abspath(path), stat.st_mtime_ns, side)
    with _lock:
        cached = _albedo_cache.get(key)
    if cached is not None:
        return cached
    prepared = prepare_texture(path)
    with Image.open(io.BytesIO(prepared.data)) as image:
        rgb = image.convert("RGB").resize((side, side), Image.Resampling.BOX if min(image.size) > side
                                          else Image.Resampling.BILINEAR)
    linear = _srgb_to_linear(np.asarray(rgb, np.float32) / 255.0).astype(np.float32)
    with _lock:
        if len(_albedo_cache) > 32:
            _albedo_cache.clear()
        _albedo_cache[key] = linear
    return linear



def surface_pattern(surface: Surface, repeats: float, px: int) -> np.ndarray:
    """One full tile of a surface: linear RGB (px, px, 3), row 0 = north edge."""
    tint = _srgb_to_linear(np.array(surface.color, np.float32) / 255.0)
    if surface.albedo and os.path.isfile(surface.albedo):
        count = max(1, int(repeats))
        side = max(1, math.ceil(px / count))
        tiled = np.tile(_albedo(surface.albedo, side), (count, count, 1))[:px, :px]
        if tiled.shape[0] < px:  # repeats did not cover the tile exactly
            tiled = np.pad(tiled, ((0, px - tiled.shape[0]), (0, px - tiled.shape[1]), (0, 0)), mode="wrap")
        return np.ascontiguousarray(tiled * tint, np.float32)
    return np.ascontiguousarray(np.broadcast_to(tint, (px, px, 3)), np.float32)


@nb.njit(cache=True, nogil=True)
def _raster(px_x, px_y, faces, weights, slot, patterns, out, scale_x, scale_y):
    """Barycentric fill of ``out`` (h, w, 3) with Σ weight · pattern over the triangles."""
    h, w = out.shape[0], out.shape[1]
    ns = weights.shape[1]
    for f in range(faces.shape[0]):
        a, b, c = faces[f, 0], faces[f, 1], faces[f, 2]
        ax, ay = px_x[a] * scale_x, px_y[a] * scale_y
        bx, by = px_x[b] * scale_x, px_y[b] * scale_y
        cx, cy = px_x[c] * scale_x, px_y[c] * scale_y
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        c0 = max(0, int(math.floor(min(ax, bx, cx) - 0.5)))
        c1 = min(w - 1, int(math.ceil(max(ax, bx, cx) - 0.5)))
        r0 = max(0, int(math.floor(min(ay, by, cy) - 0.5)))
        r1 = min(h - 1, int(math.ceil(max(ay, by, cy) - 0.5)))
        for r in range(r0, r1 + 1):
            y = r + 0.5
            for col in range(c0, c1 + 1):
                x = col + 0.5
                l0 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
                l1 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
                l2 = 1.0 - l0 - l1
                if l0 < -1e-6 or l1 < -1e-6 or l2 < -1e-6:
                    continue
                total = 0.0
                rr = 0.0
                gg = 0.0
                bb = 0.0
                for s in range(ns):
                    k = slot[s]
                    if k < 0:
                        continue
                    wt = l0 * weights[a, s] + l1 * weights[b, s] + l2 * weights[c, s]
                    if wt <= 0.0:
                        continue
                    total += wt
                    rr += wt * patterns[k, r, col, 0]
                    gg += wt * patterns[k, r, col, 1]
                    bb += wt * patterns[k, r, col, 2]
                if total > 0.0:
                    out[r, col, 0] = rr / total
                    out[r, col, 1] = gg / total
                    out[r, col, 2] = bb / total


def bake(manifest: dict, material: TerrainMaterial, tiles, cancelled=None) -> tuple[np.ndarray, tuple]:
    """Return ``(rgb uint8 image, (x0, y0, x1, y1) world metres)`` covering the selected tiles."""
    from .adm_export import build_surfaces

    wanted = set(tiles)
    chosen = [t for t in manifest["tiles"] if (t["ix"], t["iy"]) in wanted]
    if not chosen:
        raise ValueError("No tiles to bake")
    surfaces = build_surfaces(manifest, material)
    tile_size = float(manifest["tile_size_m"])
    uv = material.uv_scale(tile_size, surfaces)
    x0 = min(t["origin_m"][0] for t in chosen)
    y0 = min(t["origin_m"][1] for t in chosen)
    x1 = max(t["origin_m"][0] + t["size_m"][0] for t in chosen)
    y1 = max(t["origin_m"][1] + t["size_m"][1] for t in chosen)
    span = max(x1 - x0, y1 - y0) / tile_size
    px = max(16, min(MAX_TILE_PX, int(MAX_SIDE / max(span, 1.0))))
    width = max(1, round((x1 - x0) / tile_size * px))
    height = max(1, round((y1 - y0) / tile_size * px))
    image = np.zeros((height, width, 3), np.uint8)
    patterns: dict[int, np.ndarray] = {}
    for tile in chosen:
        if cancelled is not None and cancelled():
            raise InterruptedError()
        vertices, faces = read_ply(os.path.join(manifest["_dir"], tile["lods"][0]["file"]))
        weights = np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.float32)
        for s in np.flatnonzero(weights.max(axis=0) > 0):
            if int(s) not in patterns:
                patterns[int(s)] = surface_pattern(surfaces[s], uv[s], px)
        order = sorted(patterns)
        slot = np.full(len(surfaces), -1, np.int64)
        slot[order] = np.arange(len(order))
        stack = np.stack([patterns[s] for s in order])
        ox, oy = tile["origin_m"][:2]
        w = max(1, round(tile["size_m"][0] / tile_size * px))
        h = max(1, round(tile["size_m"][1] / tile_size * px))
        left = round((ox - x0) / tile_size * px)
        top = round((y1 - (oy + tile["size_m"][1])) / tile_size * px)
        w, h = min(w, width - left), min(h, height - top)
        # Partial tiles at the east and south edges keep the north-west part of a full tile's UVs.
        rgb = np.zeros((h, w, 3), np.float32)
        ppm = px / tile_size
        _raster(vertices["x"].astype(np.float64), (tile["size_m"][1] - vertices["y"]).astype(np.float64),
                np.ascontiguousarray(faces, np.int64), weights, slot, stack[:, :h, :w], rgb, ppm, ppm)
        image[top:top + h, left:left + w] = (_linear_to_srgb(rgb) * 255.0 + 0.5).astype(np.uint8)
    return image, (x0, y0, x1, y1)
