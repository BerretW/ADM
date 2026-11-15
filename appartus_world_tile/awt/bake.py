"""Bake the terrain material into one preview image for the 3D viewer.

The result approximates what TERRAIN_4 shows: each layer's albedo repeated ``uv_scale`` times
per tile and tinted, blended by the tile's mask. Lighting and normal maps are left out.
"""

from __future__ import annotations

import math
import os
import threading

import numpy as np

from .material import TerrainMaterial

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
    with Image.open(path) as image:
        rgb = image.convert("RGB").resize((side, side), Image.Resampling.BOX if min(image.size) > side
                                          else Image.Resampling.BILINEAR)
    linear = _srgb_to_linear(np.asarray(rgb, np.float32) / 255.0).astype(np.float32)
    with _lock:
        if len(_albedo_cache) > 32:
            _albedo_cache.clear()
        _albedo_cache[key] = linear
    return linear


def layer_patterns(material: TerrainMaterial, tile_size_m: float, px: int) -> list[np.ndarray]:
    """One full tile of each layer: linear RGB (px, px, 3), row 0 = north edge."""
    patterns = []
    for layer, repeats in zip(material.layers, material.uv_scale(tile_size_m)):
        tint = _srgb_to_linear(np.array(layer.color, np.float32) / 255.0)
        if layer.albedo and os.path.isfile(layer.albedo):
            count = int(repeats)
            side = max(1, math.ceil(px / count))
            tiled = np.tile(_albedo(layer.albedo, side), (count, count, 1))[:px, :px]
            if tiled.shape[0] < px:  # repeats did not cover the tile exactly
                tiled = np.pad(tiled, ((0, px - tiled.shape[0]), (0, px - tiled.shape[1]), (0, 0)), mode="wrap")
            patterns.append(tiled * tint)
        else:
            patterns.append(np.broadcast_to(tint, (px, px, 3)))
    return patterns


def bake(manifest: dict, material: TerrainMaterial, tiles, cancelled=None) -> tuple[np.ndarray, tuple]:
    """Return ``(rgb uint8 image, (x0, y0, x1, y1) world metres)`` covering the selected tiles."""
    from PIL import Image

    wanted = set(tiles)
    chosen = [t for t in manifest["tiles"] if (t["ix"], t["iy"]) in wanted]
    if not chosen:
        raise ValueError("No tiles to bake")
    tile_size = float(manifest["tile_size_m"])
    x0 = min(t["origin_m"][0] for t in chosen)
    y0 = min(t["origin_m"][1] for t in chosen)
    x1 = max(t["origin_m"][0] + t["size_m"][0] for t in chosen)
    y1 = max(t["origin_m"][1] + t["size_m"][1] for t in chosen)
    span = max(x1 - x0, y1 - y0) / tile_size
    px = max(16, min(MAX_TILE_PX, int(MAX_SIDE / max(span, 1.0))))
    width = max(1, round((x1 - x0) / tile_size * px))
    height = max(1, round((y1 - y0) / tile_size * px))
    image = np.zeros((height, width, 3), np.uint8)
    patterns = layer_patterns(material, tile_size, px)
    for tile in chosen:
        if cancelled is not None and cancelled():
            raise InterruptedError()
        ox, oy = tile["origin_m"][:2]
        w = max(1, round(tile["size_m"][0] / tile_size * px))
        h = max(1, round(tile["size_m"][1] / tile_size * px))
        left = round((ox - x0) / tile_size * px)
        top = round((y1 - (oy + tile["size_m"][1])) / tile_size * px)
        w, h = min(w, width - left), min(h, height - top)
        mask_file = tile.get("mask")
        if mask_file and os.path.isfile(os.path.join(manifest["_dir"], mask_file)):
            with Image.open(os.path.join(manifest["_dir"], mask_file)) as mask_image:
                # Per channel: resizing RGBA would premultiply by A (the water weight) and wipe the others.
                channels = mask_image.convert("RGBA").split()
                weights = np.stack([np.asarray(c.resize((w, h), Image.Resampling.BILINEAR), np.float32)
                                    for c in channels], axis=2)
            total = weights.sum(axis=2, keepdims=True)
            weights = np.where(total > 0, weights / np.maximum(total, 1e-6), [1.0, 0.0, 0.0, 0.0])
        else:
            weights = np.zeros((h, w, 4), np.float32)
            weights[..., 0] = 1.0
        # Partial tiles at the east and south edges keep the north-west part of a full tile's UVs.
        rgb = sum(weights[..., i:i + 1] * patterns[i][:h, :w] for i in range(4))
        image[top:top + h, left:left + w] = (_linear_to_srgb(rgb) * 255.0 + 0.5).astype(np.uint8)
    return image, (x0, y0, x1, y1)
