"""Heightmap -> crack-free tiled terrain meshes (PLY + manifest.json).

Every vertex carries the surface weights of the terrain material (``w0..wN`` in the PLY,
in the order of ``manifest["texturing"]["surfaces"]``).
"""

from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np

from . import __version__
from .heightmap import Heightmap, load_heightmap, preview
from .material import TerrainMaterial
from .ply import vertex_dtype, write_ply
from .roads import rasterize

MANIFEST_FORMAT = "apparatus-world-tile"
MANIFEST_VERSION = 2
MANIFEST_NAME = "manifest.json"
TILE_DIR = "tiles"
_OLD_DIRS = ("masks",)  # written by version 1 builds; cleaned up on rebuild

Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


@dataclass
class BuildParams:
    input_path: str
    out_dir: str
    spacing_m: float = 1.0
    height_min_m: float = 0.0
    height_max_m: float = 500.0
    # Float sources are metres; set True to remap their min..max to the range.
    remap_float: bool = False
    tile_cells: int = 256
    max_errors_m: list[float] = field(default_factory=lambda: [0.25])
    origin: str = "corner"  # "corner" or "center"
    threads: int = 0  # 0 = all cores
    raw_size: tuple[int, int] | None = None
    # Extra splits where surface weights change faster than the triangles can follow
    # (0..1 of a weight; 0 = off). Only triangles with legs of at least texture_detail_m split.
    texture_error: float = 0.15
    texture_detail_m: float = 4.0

    def validate(self) -> None:
        if not (self.spacing_m > 0 and math.isfinite(self.spacing_m)):
            raise ValueError("Sample spacing must be a positive number of metres")
        if self.tile_cells < 2 or self.tile_cells > 4096 or self.tile_cells & (self.tile_cells - 1):
            raise ValueError("Tile size must be a power of two between 2 and 4096 cells")
        if not 0.0 <= self.texture_error <= 1.0:
            raise ValueError("Texture error must be between 0 and 1")
        if not (self.texture_detail_m > 0 and math.isfinite(self.texture_detail_m)):
            raise ValueError("Texture detail must be a positive number of metres")
        if not self.max_errors_m:
            raise ValueError("Set at least one maximum height error")
        for value in self.max_errors_m:
            if not (value >= 0 and math.isfinite(value)):
                raise ValueError("Maximum height errors must be finite and not negative")
        if self.origin not in ("corner", "center"):
            raise ValueError("Origin must be 'corner' or 'center'")
        if self.height_max_m < self.height_min_m:
            raise ValueError("Height maximum must not be below the minimum")


def height_transform(hm: Heightmap, params: BuildParams) -> tuple[float, float]:
    """Return ``(scale, offset)`` so that metres = sample * scale + offset."""
    span = params.height_max_m - params.height_min_m
    if hm.is_integer:
        return span / hm.normalized_max, params.height_min_m
    if params.remap_float:
        lo = float(hm.data.min())
        hi = float(hm.data.max())
        scale = span / (hi - lo) if hi > lo else 0.0
        return scale, params.height_min_m - lo * scale
    return 1.0, 0.0


def fit_material(hm: Heightmap, params: BuildParams, material: TerrainMaterial, **overrides) -> dict:
    """Place the default biomes' height bands for the height distribution of ``hm``.

    ``overrides`` replace fitted levels (``water_m``, ``shore_m``, ``snow_start_m``, ...);
    returns the levels used.
    """
    scale, offset = height_transform(hm, params)
    levels = material.fitted_levels(preview(hm.data, 512) * scale + offset)
    levels.update({key: value for key, value in overrides.items() if value is not None})
    material.place_levels(**levels)
    return levels


def tile_grid(width: int, height: int, tile_cells: int) -> tuple[int, int]:
    return max(1, math.ceil((width - 1) / tile_cells)), max(1, math.ceil((height - 1) / tile_cells))


def estimate_memory(width: int, height: int, tile_cells: int, sample_bytes: int) -> int:
    nx, ny = tile_grid(width, height, tile_cells)
    return width * height * sample_bytes + (nx * tile_cells + 1) * (ny * tile_cells + 1) * 4


def hillshade(data: np.ndarray, spacing: float, scale: float) -> np.ndarray:
    """8-bit hillshade of a (preview) height array."""
    z = data.astype(np.float32) * np.float32(scale)
    gy, gx = np.gradient(z, spacing)
    shade = (1.0 + gx * 0.6 - gy * 0.6) / np.sqrt(1.0 + gx * gx + gy * gy)
    lo, hi = float(z.min()), float(z.max())
    tint = (z - lo) / (hi - lo) if hi > lo else np.zeros_like(z)
    return np.clip(shade * (0.75 + 0.25 * tint) * 200.0 + 30.0, 0, 255).astype(np.uint8)


class _Context:
    def __init__(self, hm: Heightmap, params: BuildParams):
        self.hm = hm
        self.params = params
        self.width = hm.width
        self.height = hm.height
        self.t = params.tile_cells
        self.nx, self.ny = tile_grid(self.width, self.height, self.t)
        self.levels = 2 * int(round(math.log2(self.t)))
        self.scale, self.offset = height_transform(hm, params)
        sp = params.spacing_m
        self.size_x = (self.width - 1) * sp
        self.size_y = (self.height - 1) * sp
        if params.origin == "center":
            self.shift = (-self.size_x / 2.0, -self.size_y / 2.0)
        else:
            self.shift = (0.0, 0.0)

    def tile_origin(self, ti: int, tj: int) -> tuple[float, float]:
        sp = self.params.spacing_m
        last_y = self.height - 1
        x0 = ti * self.t * sp + self.shift[0]
        y0 = max(0, last_y - (tj + 1) * self.t) * sp + self.shift[1]
        return x0, y0

    def tile_size(self, ti: int, tj: int) -> tuple[float, float]:
        sp = self.params.spacing_m
        cols = min(self.t, self.width - 1 - ti * self.t)
        rows = min(self.t, self.height - 1 - tj * self.t)
        return cols * sp, rows * sp

    def tile_extent(self, ti: int, tj: int) -> tuple[int, int, int, int]:
        """Grid rectangle ``x0, y0, x1, y1`` of the tile's real samples."""
        x0 = ti * self.t
        y0 = tj * self.t
        return x0, y0, min(self.width - 1, x0 + self.t), min(self.height - 1, y0 + self.t)

    def heights(self, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
        values = self.hm.data[gy, gx].astype(np.float64)
        return values * self.scale + self.offset


def content_digest(*arrays: np.ndarray) -> str:
    """Short hash of array contents; tells the exporter which tiles changed between builds."""
    import hashlib

    digest = hashlib.blake2b(digest_size=16)
    for array in arrays:
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _tile_id(ix: int, iy: int) -> str:
    return f"x{ix:03d}_y{iy:03d}"


def _tile_vertices(ctx: _Context, grid: np.ndarray, ti: int, tj: int, weights: np.ndarray) -> np.ndarray:
    sp = ctx.params.spacing_m
    last_x = ctx.width - 1
    last_y = ctx.height - 1
    gx = grid[:, 0].astype(np.int64)
    gy = grid[:, 1].astype(np.int64)
    z = ctx.heights(gx, gy)
    xl = np.maximum(gx - 1, 0)
    xr = np.minimum(gx + 1, last_x)
    yn = np.maximum(gy - 1, 0)  # north = +world Y
    ys = np.minimum(gy + 1, last_y)
    dzdx = (ctx.heights(xr, gy) - ctx.heights(xl, gy)) / ((xr - xl) * sp)
    dzdy = (ctx.heights(gx, yn) - ctx.heights(gx, ys)) / ((ys - yn) * sp)
    inv = 1.0 / np.sqrt(dzdx * dzdx + dzdy * dzdy + 1.0)
    x0, y0 = ctx.tile_origin(ti, tj)
    out = np.empty(len(grid), vertex_dtype(weights.shape[1]))
    out["x"] = gx * sp + ctx.shift[0] - x0
    out["y"] = (last_y - gy) * sp + ctx.shift[1] - y0
    out["z"] = z
    out["nx"] = -dzdx * inv
    out["ny"] = -dzdy * inv
    out["nz"] = inv
    out["s"] = (gx - ti * ctx.t) / ctx.t
    out["t"] = 1.0 - (gy - tj * ctx.t) / ctx.t
    for i in range(weights.shape[1]):
        out[f"w{i}"] = weights[:, i]
    return out


def _remove_stale(out_dir: str, keep: set[str]) -> None:
    """Delete files listed by a previous manifest of ours that are no longer produced."""
    path = os.path.join(out_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as handle:
            old = json.load(handle)
    except (OSError, ValueError):
        return
    if old.get("format") != MANIFEST_FORMAT:
        return
    roots = {os.path.realpath(os.path.join(out_dir, name)) for name in (TILE_DIR,) + _OLD_DIRS}
    listed = []
    for tile in old.get("tiles", []):
        listed += [lod.get("file") for lod in tile.get("lods", [])]
        listed.append(tile.get("mask"))
    for rel in listed:
        if not isinstance(rel, str) or rel in keep:
            continue
        target = os.path.realpath(os.path.join(out_dir, rel))
        if os.path.dirname(target) in roots and target.endswith((".ply", ".png")) and os.path.isfile(target):
            os.remove(target)


def build(
    params: BuildParams,
    material: TerrainMaterial | None = None,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
    heightmap: Heightmap | None = None,
) -> dict:
    """Run the whole pipeline and return the written manifest."""
    from . import kernels, texturing

    params.validate()
    material = material or TerrainMaterial()
    material.validate_rules()
    report = progress or (lambda fraction, message: None)
    is_cancelled = cancelled or (lambda: False)
    started = time.perf_counter()
    timings: dict[str, float] = {}

    report(0.0, "Loading heightmap")
    hm = heightmap or load_heightmap(params.input_path, params.raw_size)
    timings["load_s"] = time.perf_counter() - started
    ctx = _Context(hm, params)
    source_hm, source_scale, source_offset = hm, ctx.scale, ctx.offset
    if material.roads:
        report(0.02, "Applying road grades")
        heights = hm.data.astype(np.float32, copy=True)
        heights *= np.float32(ctx.scale)
        heights += np.float32(ctx.offset)
        for road in material.roads:
            if is_cancelled():
                raise Cancelled()
            road.validate(ctx.width, ctx.height)
            for window, distance, elevation in rasterize(road, params.spacing_m, ctx.height, ctx.width):
                if is_cancelled():
                    raise Cancelled()
                if road.shoulder_m:
                    alpha = np.clip((road.width_m / 2 + road.shoulder_m - distance) / road.shoulder_m, 0, 1)
                    alpha = alpha * alpha * (3 - 2 * alpha)
                else:
                    alpha = (distance <= road.width_m / 2).astype(np.float32)
                patch = heights[window]
                patch += (elevation - patch) * alpha
        hm = Heightmap(heights, hm.path, 0.0)
        ctx.hm = hm
        ctx.scale, ctx.offset = 1.0, 0.0
    rules = texturing.compile_rules(material, params.spacing_m, ctx.width, ctx.height)
    cfg = rules.cfg(ctx.scale, ctx.offset, params.spacing_m)
    field_args = (cfg, rules.brule, rules.bsurf, rules.srule, rules.paint, rules.nsurf)
    threads = params.threads or os.cpu_count() or 1

    import numba

    numba.set_num_threads(max(1, min(threads, numba.config.NUMBA_NUM_THREADS)))
    errors = np.zeros((ctx.ny * ctx.t + 1, ctx.nx * ctx.t + 1), np.float32)
    texture_on = params.texture_error > 0
    span = 0.45 if texture_on else 0.55
    phase = time.perf_counter()
    for step, level in enumerate(range(ctx.levels - 1, -1, -1)):
        if is_cancelled():
            raise Cancelled()
        report(0.05 + span * step / ctx.levels, f"Measuring height error, level {step + 1} of {ctx.levels}")
        kernels.level_pass(hm.data, ctx.scale, ctx.offset, ctx.width, ctx.height,
                           ctx.t, ctx.nx, ctx.ny, level, ctx.levels, errors)
    timings["errors_s"] = time.perf_counter() - phase

    min_leg = max(1.0, params.texture_detail_m / params.spacing_m)  # cells
    werrors = np.zeros((1, 1), np.uint8)
    if texture_on:
        phase = time.perf_counter()
        werrors = np.zeros(errors.shape, np.uint8)
        for step, level in enumerate(range(ctx.levels - 1, -1, -1)):
            if is_cancelled():
                raise Cancelled()
            report(0.5 + 0.1 * step / ctx.levels, f"Measuring texture error, level {step + 1} of {ctx.levels}")
            texturing.weight_level_pass(hm.data, *field_args, ctx.t, ctx.nx, ctx.ny, level, ctx.levels,
                                        min_leg * min_leg, werrors)
        timings["texture_errors_s"] = time.perf_counter() - phase
    max_werror = min(255, int(math.floor(params.texture_error * 255.0)))

    no_boundary_splits = np.zeros((1, 1), np.bool_)
    boundary_splits = no_boundary_splits
    if len(params.max_errors_m) > 1:
        boundary_splits = np.zeros(errors.shape, np.bool_)
        for tj in range(ctx.ny):
            for ti in range(ctx.nx):
                if is_cancelled():
                    raise Cancelled()
                report(0.6, f"Matching LOD boundaries: tile {tj * ctx.nx + ti + 1} of {ctx.nx * ctx.ny}")
                grid, _, _ = kernels.extract_tile(
                    hm.data, ctx.scale, ctx.offset, ctx.width, ctx.height, ctx.t, ti, tj,
                    ctx.levels, errors, min(params.max_errors_m), werrors, max_werror,
                    min_leg * min_leg if texture_on else math.inf, no_boundary_splits)
                x0, y0, x1, y1 = ctx.tile_extent(ti, tj)
                edge = ((grid[:, 0] == x0) | (grid[:, 0] == x1)
                        | (grid[:, 1] == y0) | (grid[:, 1] == y1))
                boundary_splits[grid[edge, 1], grid[edge, 0]] = True
        kernels.propagate_boundary_splits(ctx.t, ctx.nx, ctx.ny, ctx.levels, boundary_splits)

    out_dir = os.path.abspath(params.out_dir)
    os.makedirs(os.path.join(out_dir, TILE_DIR), exist_ok=True)
    jobs = [(lod, ti, tj) for lod in range(len(params.max_errors_m))
            for tj in range(ctx.ny) for ti in range(ctx.nx)]
    from PIL import Image

    def run(job):
        lod, ti, tj = job
        if is_cancelled():
            raise Cancelled()
        iy = ctx.ny - 1 - tj
        leg = min_leg * 2 ** lod
        grid, faces, measured = kernels.extract_tile(
            hm.data, ctx.scale, ctx.offset, ctx.width, ctx.height, ctx.t, ti, tj,
            ctx.levels, errors, float(params.max_errors_m[lod]),
            werrors, max_werror, leg * leg if texture_on else math.inf, boundary_splits)
        weights = texturing.quantize(texturing.weights_serial(
            hm.data, *field_args, grid[:, 0].astype(np.float64), grid[:, 1].astype(np.float64)))
        rel = f"{TILE_DIR}/{_tile_id(ti, iy)}_lod{lod}.ply"
        vertices = _tile_vertices(ctx, grid, ti, tj, weights)
        write_ply(os.path.join(out_dir, rel), vertices, faces,
                  f"{MANIFEST_FORMAT} tile {_tile_id(ti, iy)} lod {lod}")
        return job, {"file": rel, "vertices": int(len(grid)), "triangles": int(len(faces)),
                     "measured_error_m": float(measured), "digest": content_digest(vertices, faces),
                     "used_surfaces": np.flatnonzero(np.any(weights > 0, axis=0)).tolist()}

    phase = time.perf_counter()
    results: dict[tuple[int, int, int], dict] = {}
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        try:
            for done, future in enumerate(as_completed(futures), 1):
                job, record = future.result()
                results[job] = record
                report(0.6 + 0.34 * done / len(jobs), f"Tiles {done} of {len(jobs)}")
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    timings["tiles_s"] = time.perf_counter() - phase

    tiles = []
    for tj in range(ctx.ny):
        for ti in range(ctx.nx):
            x0, y0 = ctx.tile_origin(ti, tj)
            iy = ctx.ny - 1 - tj
            tiles.append({
                "id": _tile_id(ti, iy),
                "ix": ti,
                "iy": iy,
                "origin_m": [x0, y0, 0.0],
                "size_m": list(ctx.tile_size(ti, tj)),
                "lods": [results[(lod, ti, tj)] for lod in range(len(params.max_errors_m))],
            })
    tiles.sort(key=lambda tile: (tile["iy"], tile["ix"]))

    report(0.95, "Writing previews and manifest")
    preview_data = preview(hm.data)
    step = max(1, int(np.ceil(max(hm.data.shape) / 1024)))
    shade = hillshade(preview_data, params.spacing_m * step, ctx.scale)
    Image.fromarray(shade).save(os.path.join(out_dir, "preview.png"))
    maps = texturing.preview(material, hm.data, ctx.scale, ctx.offset, params.spacing_m, shade=shade)
    Image.fromarray(maps.biomes).save(os.path.join(out_dir, "biomes.png"))
    Image.fromarray(maps.surfaces).save(os.path.join(out_dir, "surfaces.png"))

    lods = []
    for lod, max_error in enumerate(params.max_errors_m):
        records = [tile["lods"][lod] for tile in tiles]
        lods.append({
            "index": lod,
            "max_error_m": float(max_error),
            "vertices": sum(r["vertices"] for r in records),
            "triangles": sum(r["triangles"] for r in records),
            "measured_error_m": max(r["measured_error_m"] for r in records),
        })
    timings["total_s"] = time.perf_counter() - started
    source_params = asdict(params)
    source_params.pop("out_dir")
    manifest = {
        "format": MANIFEST_FORMAT,
        "format_version": MANIFEST_VERSION,
        "generator": f"appartus_world_tile {__version__}",
        "units": "metres, Z up, tile vertices relative to origin_m",
        "source": {
            "path": os.path.abspath(params.input_path),
            "width": ctx.width,
            "height": ctx.height,
            "dtype": str(source_hm.data.dtype),
            "height_scale": source_scale,
            "height_offset": source_offset,
            "height_range_m": [float(source_hm.data.min()) * source_scale + source_offset,
                               float(source_hm.data.max()) * source_scale + source_offset],
        },
        "params": source_params,
        "spacing_m": params.spacing_m,
        "size_m": [ctx.size_x, ctx.size_y],
        "origin": params.origin,
        "bounds_m": [ctx.shift[0], ctx.shift[1], ctx.shift[0] + ctx.size_x, ctx.shift[1] + ctx.size_y],
        "tile_cells": ctx.t,
        "tile_size_m": ctx.t * params.spacing_m,
        "tiles_x": ctx.nx,
        "tiles_y": ctx.ny,
        "uv": {
            "uv0": "0..1 across each full tile (V up); repeat surface textures with integer uv_scale",
        },
        "texturing": {
            "surfaces": material.surface_names(),
            "surface_colors": [list(s.color) for s in material.surfaces],
            "biomes": [b.name for b in material.biomes],
            "rules_digest": material.rules_digest(),
            "vertex_weights": "PLY uchar w0..wN per vertex in surface order, summing to 255",
            "unshared_neighbours": [list(pair) for pair in maps.problems],
        },
        "preview": "preview.png",
        "biomes_preview": "biomes.png",
        "surfaces_preview": "surfaces.png",
        "lods": lods,
        "tiles": tiles,
        "timings": timings,
    }
    if material.roads:
        manifest["edited_height_range_m"] = [float(hm.data.min()), float(hm.data.max())]
    keep = {record["file"] for record in results.values()}
    _remove_stale(out_dir, keep)
    temp = os.path.join(out_dir, MANIFEST_NAME + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1)
    os.replace(temp, os.path.join(out_dir, MANIFEST_NAME))
    report(1.0, f"Done in {timings['total_s']:.1f} s")
    return manifest


def load_manifest(path: str) -> dict:
    if os.path.isdir(path):
        path = os.path.join(path, MANIFEST_NAME)
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("format") != MANIFEST_FORMAT:
        raise ValueError(f"{path}: not an {MANIFEST_FORMAT} manifest")
    if manifest.get("format_version", 0) > MANIFEST_VERSION:
        raise ValueError(f"{path}: manifest version {manifest['format_version']} is newer than this tool")
    if manifest.get("format_version", 0) < MANIFEST_VERSION:
        raise ValueError(f"{path}: the tiles were built by an older version without surface weights; rebuild them")
    manifest["_dir"] = os.path.dirname(os.path.abspath(path))
    return manifest
