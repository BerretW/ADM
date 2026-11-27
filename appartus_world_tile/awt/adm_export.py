"""Write built tiles straight to ADM 1.0 files with versioned layered terrain materials.

One ``.adm`` per tile: a root node placed at the tile centre (so the tile lands at its world
position), one child per LOD with a ``lodGroups`` entry.  The build stores per-vertex surface
weights; every triangle is assigned to a primitive whose material holds at most four surfaces,
and the weights of those surfaces become ``COLOR_1`` (``ADM_vertex_control_v1``).  Surface
textures are either written once into ``textures/`` (``ADM_external_images_v1``) or embedded.

``world.json`` in the export folder records a digest per tile; with ``mode="changed"`` only
tiles whose geometry, weights, material or export settings differ from that record are written.
"""

from __future__ import annotations

import hashlib
import io
import json
import ntpath
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass

import numpy as np

from . import __version__
from .heightmap import Heightmap, load_heightmap, sample_digest
from .material import (GPU_ENCODINGS, SCALAR_GPU_ENCODINGS, SHADER_ID, SHADER_VERSION, SURFACES_PER_BIOME,
                       MapSlot, PreparedImage, Surface, TerrainMaterial,
                       MAX_TEXTURE_BYTES, MAX_TEXTURE_PIXELS, prepare_texture, srgb_to_linear)
from .ply import read_ply, weight_fields
from .roads import rasterize as rasterize_road
from .texturing import (compile_rules, load_external_control_map, rasterize_control_map,
                        rasterize_external_control_map)

INDEX_NAME = "world.json"
INDEX_FORMAT = "apparatus-world-tile-export"
INDEX_VERSION = 8
TEXTURE_DIR = "textures"
GENERATOR = f"Apparatus World Tile {__version__} (ADM 1.0)"
MODES = ("changed", "selected", "all")
GPU_CONTAINERS = ("DDS", "KTX2")
GPU_EXPORT_ENCODINGS = ("AUTO", "BC7", "RGBA8")
PALETTE_CONFLICT_POLICIES = ("STRICT", "APPROXIMATE")
PRESENT = 2  # a surface counts for a triangle when one corner weighs more than 2/255
MAX_PALETTE_CONFLICT_DETAILS = 20

Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


@dataclass
class ExportSettings:
    out_dir: str = ""
    lod_distance_m: float = 0.0  # LOD1 switch distance; each further LOD doubles it. 0 = tile size
    embed_textures: bool = False
    validate: bool = True
    threads: int = 0
    gpu_container: str = "DDS"
    gpu_encoding: str = "AUTO"
    palette_conflict_policy: str = "STRICT"
    convert_gpu_sources: bool = False
    control_map_resolution: int = 0  # 0 = disabled

    def key(self) -> dict:
        """Settings that change the written files."""
        return {"lod_distance_m": self.lod_distance_m, "embed_textures": self.embed_textures,
                "gpu_container": self.gpu_container, "gpu_encoding": self.gpu_encoding,
                "palette_conflict_policy": self.palette_conflict_policy,
                "convert_gpu_sources": self.convert_gpu_sources,
                "control_map_resolution": self.control_map_resolution}

    def validate_values(self) -> None:
        if not self.out_dir:
            raise ValueError("Choose an export folder")
        if not (self.lod_distance_m >= 0 and np.isfinite(self.lod_distance_m)):
            raise ValueError("LOD distance must be zero or a positive number of metres")
        if self.gpu_container not in GPU_CONTAINERS or self.gpu_encoding not in GPU_EXPORT_ENCODINGS:
            raise ValueError("Unsupported GPU container or encoding; choose a supported export setting")
        if self.palette_conflict_policy not in PALETTE_CONFLICT_POLICIES:
            raise ValueError("Unsupported palette conflict policy; choose Strict or Approximate")
        if not isinstance(self.convert_gpu_sources, bool):
            raise ValueError("GPU source conversion setting must be true or false")
        if (type(self.control_map_resolution) is not int
                or self.control_map_resolution != 0 and not 2 <= self.control_map_resolution <= 4096):
            raise ValueError("Control Map resolution must be 0 (disabled) or an integer from 2 to 4096")


@dataclass(frozen=True)
class PreparedTexture:
    primary: PreparedImage
    fallback: PreparedImage | None
    grayscale_source: bool = False
    pbr_normal: PreparedImage | None = None
    reencoded_source: bool = False
    channel_remapped: bool = False


def _png_image(rgba: np.ndarray, name: str) -> PreparedImage:
    from PIL import Image

    h, w = rgba.shape[:2]
    stream = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba, dtype=np.uint8)).save(stream, "PNG", optimize=True)
    data = stream.getvalue()
    return PreparedImage(data, "image/png", hashlib.sha256(data).hexdigest(), w, h, name)


def _control_map_source(manifest: dict, material: TerrainMaterial) -> dict:
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise ValueError("Control Map export requires the original heightmap recorded in the build manifest")
    params = manifest.get("params", {})
    raw_size = params.get("raw_size") if isinstance(params, dict) else None
    raw_size = tuple(raw_size) if isinstance(raw_size, list) and len(raw_size) == 2 else None
    path = source["path"]
    if not os.path.isfile(path):
        raise ValueError(f"Control Map export cannot read the source heightmap: {path}")
    heightmap = load_heightmap(path, raw_size)
    if (heightmap.width != source.get("width") or heightmap.height != source.get("height")):
        raise ValueError("Control Map source dimensions differ from the build manifest; rebuild the terrain")
    expected_digest = source.get("sample_digest")
    if not isinstance(expected_digest, str):
        raise ValueError("Control Map export requires a build manifest with a source sample fingerprint; rebuild")
    if sample_digest(heightmap.data) != expected_digest:
        raise ValueError("The source heightmap changed since the terrain build; rebuild before Control Map export")
    spacing = float(manifest["spacing_m"])
    if material.external_control_map_path:
        material.validate_rules()
        surface_ids = tuple(material.external_control_map_surface_ids)
        known_ids = {surface.id for surface in material.surfaces}
        if (len(surface_ids) != 4 or len(set(surface_ids)) != 4
                or any(not surface_id or surface_id not in known_ids for surface_id in surface_ids)):
            raise ValueError("External Control Map requires four unique, existing stable surface IDs")
        return {
            "heightmap": heightmap.data,
            "external_mask": load_external_control_map(material.external_control_map_path),
            "surface_ids": surface_ids,
            "spacing": spacing,
        }
    scale = float(source["height_scale"])
    offset = float(source["height_offset"])
    if material.roads:
        heights = heightmap.data.astype(np.float32, copy=True)
        heights *= np.float32(scale)
        heights += np.float32(offset)
        for road in material.roads:
            road.validate(heightmap.width, heightmap.height)
            for window, distance, elevation in rasterize_road(
                    road, spacing, heightmap.height, heightmap.width):
                if road.shoulder_m:
                    alpha = np.clip((road.width_m / 2 + road.shoulder_m - distance) / road.shoulder_m, 0, 1)
                    alpha = alpha * alpha * (3 - 2 * alpha)
                else:
                    alpha = (distance <= road.width_m / 2).astype(np.float32)
                patch = heights[window]
                patch += (elevation - patch) * alpha
        heightmap = Heightmap(heights, heightmap.path, 0.0)
        scale, offset = 1.0, 0.0
    return {
        "heightmap": heightmap.data,
        "rules": compile_rules(material, spacing, heightmap.width, heightmap.height),
        "scale": scale,
        "offset": offset,
        "spacing": spacing,
    }


def _tile_source_bounds(manifest: dict, tile: dict, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    height, width = shape
    tile_cells = int(manifest["tile_cells"])
    x0 = int(tile["ix"]) * tile_cells
    y0 = (int(manifest["tiles_y"]) - 1 - int(tile["iy"])) * tile_cells
    return x0, y0, min(width - 1, x0 + tile_cells), min(height - 1, y0 + tile_cells)


def _control_map_source_fingerprint(source: dict) -> str:
    height_digest = sample_digest(source["heightmap"])
    if "external_mask" not in source:
        return height_digest
    values = [height_digest, sample_digest(source["external_mask"]), list(source["surface_ids"])]
    return hashlib.blake2b(json.dumps(values, sort_keys=True).encode(), digest_size=16).hexdigest()


def _control_map_material_fingerprint(material_fp: str, source_fp: str) -> str:
    return hashlib.blake2b(json.dumps([material_fp, source_fp]).encode(), digest_size=16).hexdigest()


def _include_control_map_source(keys: dict[str, str], source_fp: str) -> dict[str, str]:
    return {
        tile_id: hashlib.blake2b(json.dumps([key, source_fp]).encode(), digest_size=16).hexdigest()
        for tile_id, key in keys.items()
    }


def _png_scalar_image(values: np.ndarray, name: str) -> PreparedImage:
    from adm_blender.core.png import encode_png

    pixels = np.ascontiguousarray(values)
    if pixels.ndim != 2 or pixels.dtype not in (np.dtype(np.uint8), np.dtype(np.uint16)):
        raise ValueError("Scalar fallback must be a 2D 8-bit or 16-bit image")
    height, width = pixels.shape
    rgba = np.zeros((height, width, 4), dtype=pixels.dtype)
    rgba[..., 0] = pixels
    rgba[..., 3] = np.iinfo(pixels.dtype).max
    depth = pixels.dtype.itemsize * 8
    if depth == 16:
        rgba = rgba.astype(">u2")
    data = encode_png(width, height, rgba.tobytes(), 4, bit_depth=depth)
    return PreparedImage(data, "image/png", hashlib.sha256(data).hexdigest(), width, height, name)


def _multichannel_tiff16(path: str, name: str) -> PreparedImage | None:
    import tifffile
    from adm_blender.core.png import encode_png

    if os.stat(path).st_size > MAX_TEXTURE_BYTES:
        raise ValueError(f"Texture is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
    with tifffile.TiffFile(path) as tiff:
        page = tiff.pages[0]
        if page.dtype != np.dtype(np.uint16) or page.samplesperpixel == 1:
            return None
        width, height, channels = page.imagewidth, page.imagelength, page.samplesperpixel
        if not width or not height or width * height > MAX_TEXTURE_PIXELS:
            raise ValueError(f"Texture dimensions exceed the {MAX_TEXTURE_PIXELS:,}-pixel limit")
        planar = page.planarconfig
        expected = (channels, height, width) if planar == 2 else (height, width, channels)
        if (page.photometric != 2 or channels not in (3, 4) or planar not in (1, 2)
                or page.shape != expected):
            raise ValueError(f"Cannot preserve 16-bit TIFF channel layout in '{path}'")
        values = page.asarray()
        if planar == 2:
            values = np.moveaxis(values, 0, -1)
        if values.shape != (height, width, channels) or values.dtype != np.uint16:
            raise ValueError(f"Invalid decoded 16-bit TIFF samples in '{path}'")
        data = encode_png(width, height, values.astype(">u2").tobytes(), channels, bit_depth=16)
        return PreparedImage(data, "image/png", hashlib.sha256(data).hexdigest(), width, height, name)


def _bc5_fallbacks(blob: bytes, mime: str, name: str) -> tuple[PreparedImage, PreparedImage]:
    from adm_blender.core import gputex

    rgba = gputex.decode(blob, mime, strict=True)[0]
    normal = gputex.reconstruct_bc5_normal(rgba.astype(np.float32) / 255.0)
    return _png_image(rgba, name), _png_image(np.rint(normal * 255.0).astype(np.uint8), name + "_pbr_normal")


def _selected_scalar_texture(rgba: np.ndarray, channel: int, kind: str, mime: str, name: str,
                             reencoded_source: bool = False) -> PreparedTexture:
    from adm_blender.core import gputex

    values = np.ascontiguousarray(rgba[..., channel])
    if kind == "R16":
        values = values.astype(np.uint16) * 257
    blob, _ = gputex.encode_scalar(values, mime, kind, mipmaps=True)
    fallback = _png_scalar_image(values, name)
    primary = PreparedImage(blob, mime, hashlib.sha256(blob).hexdigest(),
                            values.shape[1], values.shape[0], name)
    return PreparedTexture(primary, fallback, reencoded_source=reencoded_source, channel_remapped=True)


def prepare_adm_texture(path: str, role: str, gpu_container: str = "DDS",
                        gpu_encoding: str = "AUTO", convert_gpu_sources: bool = False,
                        selected_channel: int | None = None) -> PreparedTexture:
    """Prepare a texture, preserving compatible GPU sources and 16-bit data."""
    from PIL import Image
    from adm_blender.core import gputex

    color_role = role in ("albedo", "macro_color")
    compression = {"albedo": "AUTO", "macro_color": "AUTO", "normal": "RGBA8", "data": "BC3"}.get(role)
    if compression is None:
        raise ValueError(f"Unknown texture role {role!r}")
    if gpu_container not in GPU_CONTAINERS or gpu_encoding not in GPU_ENCODINGS:
        raise ValueError("Unsupported GPU container or encoding")
    if gpu_encoding == "BC5" and role != "normal":
        raise ValueError("BC5 encoding is available only for normal maps")
    if gpu_encoding in SCALAR_GPU_ENCODINGS and (
            role != "data" or type(selected_channel) is not int or selected_channel not in (0, 1, 2, 3)):
        raise ValueError("Scalar GPU encoding requires a data map and a selected channel")
    if not isinstance(convert_gpu_sources, bool):
        raise ValueError("GPU source conversion setting must be true or false")
    gpu_mime = gputex.MIME_DDS if gpu_container == "DDS" else gputex.MIME_KTX2
    if gpu_encoding != "AUTO":
        compression = gpu_encoding

    stat = os.stat(path)
    name = os.path.splitext(os.path.basename(path))[0]
    with open(path, "rb") as handle:
        source_mime = gputex.mime_of(handle.read(12))
    source_bytes = b""
    if source_mime is not None:
        if stat.st_size > MAX_TEXTURE_BYTES:
            raise ValueError(f"Texture is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
        with open(path, "rb") as handle:
            source_bytes = handle.read(MAX_TEXTURE_BYTES + 1)
        if len(source_bytes) > MAX_TEXTURE_BYTES:
            raise ValueError(f"Texture is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
    source_info = None
    if source_mime is not None:
        try:
            source_info = gputex.parse(source_bytes, source_mime, strict=True)
        except gputex.GpuTextureError:
            if source_mime == gputex.MIME_KTX2:
                raise

    if source_info and source_info["width"] * source_info["height"] > MAX_TEXTURE_PIXELS:
        raise ValueError(f"Texture dimensions exceed the {MAX_TEXTURE_PIXELS:,}-pixel limit")

    if source_info and source_info["kind"] in ("R8", "R16", "BC4") and role == "data" and not convert_gpu_sources:
        values, _ = gputex.decode_scalar(source_bytes, source_mime, strict=True)
        fallback = _png_scalar_image(values, name)
        primary = PreparedImage(source_bytes, source_mime, hashlib.sha256(source_bytes).hexdigest(),
                                source_info["width"], source_info["height"], name)
        return PreparedTexture(primary, fallback)

    if source_info and source_info["srgb"] != color_role:
        raise ValueError(f"GPU texture color space does not match the {role} role; convert the source explicitly")

    if source_info and not convert_gpu_sources:
        rgba = gputex.decode(source_bytes, source_mime, strict=True)[0]
        fallback = _png_image(rgba, name)
        pbr_normal = None
        if source_info["kind"] == "BC5" and role == "normal":
            normal = gputex.reconstruct_bc5_normal(rgba.astype(np.float32) / 255.0)
            pbr_normal = _png_image(np.rint(normal * 255.0).astype(np.uint8), name + "_pbr_normal")
        primary = PreparedImage(source_bytes, source_mime, hashlib.sha256(source_bytes).hexdigest(),
                                source_info["width"], source_info["height"], name)
        return PreparedTexture(primary, fallback, pbr_normal=pbr_normal)

    if source_info and convert_gpu_sources:
        pbr_normal = None
        if gpu_encoding in SCALAR_GPU_ENCODINGS and source_info["kind"] != "R16":
            rgba = gputex.decode(source_bytes, source_mime, strict=True)[0]
            return _selected_scalar_texture(rgba, selected_channel, gpu_encoding, gpu_mime, name, True)
        if source_info["kind"] in ("R8", "R16", "BC4") and role == "data":
            scalar, _ = gputex.decode_scalar(source_bytes, source_mime, strict=True)
            fallback = _png_scalar_image(scalar, name)
            if scalar.dtype == np.uint16:
                blob, _kind = gputex.encode_scalar(scalar, gpu_mime, "R16", mipmaps=True)
            else:
                rgba = np.zeros((*scalar.shape, 4), dtype=np.uint8)
                rgba[..., 0] = scalar
                rgba[..., 3] = 255
                blob, _kind = gputex.encode(rgba, gpu_mime, compression, srgb=False, mipmaps=True)
        else:
            rgba = gputex.decode(source_bytes, source_mime, strict=True)[0]
            fallback = _png_image(rgba, name)
            if source_info["kind"] == "BC5" and role == "normal":
                normal = gputex.reconstruct_bc5_normal(rgba.astype(np.float32) / 255.0)
                pbr_normal = _png_image(np.rint(normal * 255.0).astype(np.uint8), name + "_pbr_normal")
            blob, _kind = gputex.encode(rgba, gpu_mime, compression, srgb=color_role, mipmaps=True)
        primary = PreparedImage(blob, gpu_mime, hashlib.sha256(blob).hexdigest(),
                                source_info["width"], source_info["height"], name)
        if compression == "BC5":
            fallback, pbr_normal = _bc5_fallbacks(blob, gpu_mime, name)
        return PreparedTexture(primary, fallback, pbr_normal=pbr_normal, reencoded_source=True)

    if role == "data":
        if stat.st_size > MAX_TEXTURE_BYTES:
            raise ValueError(f"Texture is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
        with open(path, "rb") as handle:
            signature = handle.read(4)
        if signature in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            converted = _multichannel_tiff16(path, name)
            if converted is not None:
                return PreparedTexture(converted, None)
    decoded = prepare_texture(path)
    with Image.open(io.BytesIO(decoded.data)) as image:
        image.load()
        scalar16 = np.asarray(image)
        if role == "data" and scalar16.ndim == 2 and scalar16.dtype == np.uint16:
            blob, _kind = gputex.encode_scalar(scalar16, gpu_mime, "R16", mipmaps=True)
            fallback = _png_scalar_image(scalar16, decoded.name)
            primary = PreparedImage(blob, gpu_mime, hashlib.sha256(blob).hexdigest(),
                                    scalar16.shape[1], scalar16.shape[0], decoded.name)
            return PreparedTexture(primary, fallback, grayscale_source=True)
        if role == "data" and decoded.mime == "image/png" and decoded.data[24] == 16:
            return PreparedTexture(decoded, None)
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if gpu_encoding in SCALAR_GPU_ENCODINGS:
        return _selected_scalar_texture(rgba, selected_channel, gpu_encoding, gpu_mime, name)
    fallback = decoded if decoded.mime == "image/png" else _png_image(rgba, decoded.name)
    blob, _kind = gputex.encode(rgba, gpu_mime, compression, srgb=color_role, mipmaps=True)
    primary = PreparedImage(blob, gpu_mime, hashlib.sha256(blob).hexdigest(),
                            rgba.shape[1], rgba.shape[0], name)
    if compression == "BC5":
        fallback, pbr_normal = _bc5_fallbacks(blob, gpu_mime, name)
        return PreparedTexture(primary, fallback, pbr_normal=pbr_normal)
    return PreparedTexture(primary, fallback)


def _core():
    """``adm_blender.core`` from this repository (it does not need Blender)."""
    try:
        from adm_blender import core  # noqa: F401
    except ImportError:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isdir(os.path.join(repo, "adm_blender", "core")):
            raise ImportError("ADM export needs the adm_blender package from the ADM repository") from None
        sys.path.insert(0, repo)
        from adm_blender import core  # noqa: F401
    import adm_blender.core.buffers as buffers
    import adm_blender.core.constants as constants
    import adm_blender.core.container as container
    import adm_blender.core.validate as validate

    return buffers, constants, container, validate


def build_surfaces(manifest: dict, material: TerrainMaterial) -> list[Surface]:
    """Library surfaces in the order of the build's vertex weights."""
    names = (manifest.get("texturing") or {}).get("surfaces")
    if not names:
        raise ValueError("The build has no surface weights; rebuild the tiles")
    missing = [name for name in names if name not in material.surface_names()]
    if missing:
        raise ValueError(f"The tiles were built with surfaces that are no longer in the library: "
                         f"{', '.join(missing)}. Rebuild the tiles.")
    return [material.surface(name) for name in names]


def rules_outdated(manifest: dict, material: TerrainMaterial) -> bool:
    """True when biomes, paint or the surface list changed since the build."""
    return (manifest.get("texturing") or {}).get("rules_digest") != material.rules_digest()


# ----------------------------------------------------------------------------------- digests
def tile_digest(tile: dict, material_fp: str, settings: ExportSettings, tile_size_m: float,
                uses_textures: bool = True, uses_default_encoding: bool = True) -> str | None:
    """Digest of everything that goes into one tile file; None when the build has no digests."""
    lods = [lod.get("digest") for lod in tile["lods"]]
    if not all(lods):
        return None
    collision = tile.get("collision")
    collision_digest = collision.get("digest") if isinstance(collision, dict) else None
    if isinstance(collision, dict) and not collision_digest:
        return None
    settings_key = settings.key()
    if not uses_textures:
        settings_key.pop("gpu_container")
        settings_key.pop("gpu_encoding")
        settings_key.pop("convert_gpu_sources")
    elif not uses_default_encoding:
        settings_key.pop("gpu_encoding")
    payload = {"lods": lods, "collision": collision_digest, "material": material_fp, "settings": settings_key,
               "origin": tile["origin_m"], "size": tile["size_m"], "tile_size": tile_size_m,
               "format": INDEX_VERSION}
    return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(), digest_size=16).hexdigest()


def material_key(manifest: dict, material: TerrainMaterial, texture_hashes: dict[str, str] | None = None) -> str:
    """Material fingerprint plus the build's surface order (it maps weights to surfaces)."""
    tile_size = float(manifest["tile_size_m"])
    order = (manifest.get("texturing") or {}).get("surfaces") or []
    return hashlib.blake2b(json.dumps([material.fingerprint(tile_size, texture_hashes=texture_hashes), order]).encode(),
                           digest_size=16).hexdigest()


def _physical_paint_window(manifest: dict, tile: dict, material: TerrainMaterial):
    paint = material.physical_paint
    if paint is None or not material.has_physical_paint():
        return None
    source = manifest.get("source")
    bounds = manifest.get("bounds_m")
    width = source.get("width") if isinstance(source, dict) else None
    height = source.get("height") if isinstance(source, dict) else None
    spacing = manifest.get("spacing_m")
    valid_bounds = (isinstance(bounds, list) and len(bounds) == 4
                    and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            and np.isfinite(value) for value in bounds))
    if (not isinstance(width, int) or isinstance(width, bool) or not isinstance(height, int)
            or isinstance(height, bool) or width < 1 or height < 1
            or not valid_bounds
            or isinstance(spacing, bool) or not isinstance(spacing, (int, float))
            or not np.isfinite(spacing) or spacing <= 0):
        raise ValueError("Physical paint requires valid heightmap dimensions, bounds and spacing in the build manifest")
    cell = material.physical_paint_cell
    if not isinstance(cell, int) or isinstance(cell, bool) or cell < 1:
        raise ValueError("Physical paint cell size must be a positive integer")
    if paint.dtype != np.uint8 or paint.ndim != 2:
        raise ValueError("Physical paint must be a two-dimensional uint8 image")
    expected_shape = (int(np.ceil(height / cell)), int(np.ceil(width / cell)))
    if paint.shape != expected_shape:
        raise ValueError("Physical paint dimensions do not match the heightmap used to build these tiles")
    origin, size = tile.get("origin_m"), tile.get("size_m")
    if (not isinstance(origin, list) or len(origin) < 2 or not isinstance(size, list) or len(size) < 2
            or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not np.isfinite(value)
                   for value in (*origin[:2], *size[:2]))):
        raise ValueError(f"{tile.get('id', 'Tile')}: invalid bounds for physical paint")
    col0 = int(np.floor((origin[0] - bounds[0]) / spacing))
    col1 = int(np.ceil((origin[0] + size[0] - bounds[0]) / spacing))
    row0 = int(np.floor((height - 1) - (origin[1] + size[1] - bounds[1]) / spacing))
    row1 = int(np.ceil((height - 1) - (origin[1] - bounds[1]) / spacing))
    col0, col1 = np.clip((col0, col1), 0, width - 1)
    row0, row1 = np.clip((row0, row1), 0, height - 1)
    return (int(row0 // cell), int(row1 // cell + 1),
            int(col0 // cell), int(col1 // cell + 1))


def _physical_tile_key(manifest: dict, tile: dict, material: TerrainMaterial) -> str:
    window = _physical_paint_window(manifest, tile, material)
    used_manual = []
    paint_payload = None
    if window is not None:
        r0, r1, c0, c1 = window
        paint = material.physical_paint[r0:r1, c0:c1]
        used_manual = [int(index) for index in np.unique(paint) if index != 255]
        if used_manual:
            paint_payload = {
                "window": [r0, r1, c0, c1],
                "paint_cell": material.physical_paint_cell,
                "paint": hashlib.sha256(paint.tobytes()).hexdigest(),
            }
    if any(index >= len(material.physical_materials) for index in used_manual):
        raise ValueError(f"{tile['id']}: physical paint references a missing physical material")
    collision = tile.get("collision")
    manifest_version = manifest.get("format_version", 0)
    if (manifest_version >= 4 and isinstance(collision, dict)
            and "used_surfaces" not in collision):
        raise ValueError(f"{tile['id']}: collision used_surfaces metadata is missing; rebuild")
    used_surfaces = collision.get("used_surfaces", []) if isinstance(collision, dict) else []
    if (not isinstance(used_surfaces, list)
            or any(isinstance(index, bool) or not isinstance(index, int) or index < 0
                   for index in used_surfaces)):
        raise ValueError(f"{tile['id']}: invalid collision used_surfaces metadata")
    if manifest_version >= 4 and isinstance(collision, dict) and not used_surfaces:
        raise ValueError(f"{tile['id']}: empty collision used_surfaces metadata; rebuild")
    surfaces = build_surfaces(manifest, material) if used_surfaces else []
    if any(index >= len(surfaces) for index in used_surfaces):
        raise ValueError(f"{tile['id']}: collision used_surfaces metadata is out of range")
    automatic = [
        [index, surfaces[index].id, surfaces[index].physical_material_id]
        for index in sorted(set(used_surfaces)) if surfaces[index].physical_material_id
    ]
    used_ids = {material.physical_materials[index].id for index in used_manual}
    used_ids.update(record[2] for record in automatic)
    if not used_ids:
        return ""
    materials_by_id = {item.id: item for item in material.physical_materials}
    if used_ids - set(materials_by_id):
        raise ValueError(f"{tile['id']}: automatic physical mapping references a missing material")
    payload = {
        "paint": paint_payload,
        "automatic_surfaces": automatic,
        "materials": [asdict(materials_by_id[ident]) for ident in sorted(used_ids)],
    }
    return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(), digest_size=16).hexdigest()


def _tile_material_keys(manifest: dict, material: TerrainMaterial, fallback: str,
                        texture_hashes: dict[str, str]) -> dict[str, str]:
    surfaces = build_surfaces(manifest, material)
    tile_size = float(manifest["tile_size_m"])
    order = (manifest.get("texturing") or {}).get("surfaces") or []
    cached: dict[tuple[tuple[int, ...], str], str] = {}
    keys = {}
    for tile in manifest["tiles"]:
        physical_key = _physical_tile_key(manifest, tile, material)
        lods = tile["lods"]
        if not lods or any("used_surfaces" not in lod for lod in lods):
            keys[tile["id"]] = (fallback if not physical_key else
                                hashlib.blake2b(json.dumps([fallback, physical_key]).encode(),
                                                digest_size=16).hexdigest())
            continue
        used = set()
        for lod in lods:
            indices = lod["used_surfaces"]
            if not isinstance(indices, list) or any(
                    isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(surfaces)
                    for i in indices):
                raise ValueError(f"{tile['id']}: invalid used_surfaces metadata")
            used.update(indices)
        if not used:
            raise ValueError(f"{tile['id']}: empty used_surfaces metadata")
        subset = tuple(sorted(used))
        cache_key = (subset, physical_key)
        if cache_key not in cached:
            fingerprint = material.fingerprint(tile_size, [surfaces[i] for i in subset], texture_hashes)
            cached[cache_key] = hashlib.blake2b(
                json.dumps([fingerprint, order, subset, physical_key]).encode(), digest_size=16).hexdigest()
        keys[tile["id"]] = cached[cache_key]
    return keys


def _tile_texture_settings(manifest: dict, material: TerrainMaterial) -> dict[str, tuple[bool, bool]]:
    surfaces = build_surfaces(manifest, material)
    result = {}
    for tile in manifest["tiles"]:
        lods = tile["lods"]
        if not lods or any("used_surfaces" not in lod for lod in lods):
            used = range(len(surfaces))
        else:
            used = {i for lod in lods for i in lod["used_surfaces"]}
        has_texture = False
        uses_default = False
        for i in used:
            surface = surfaces[i]
            for name in ("albedo", "metallic", "roughness", "normal", "ao", "height", "emission"):
                if _texture_key(surface, name, "AUTO")[0]:
                    has_texture = True
                    uses_default |= name not in surface.gpu_encodings
        result[tile["id"]] = (has_texture, uses_default)
    return result


def _collision_file_path(build_dir: str, relative_path: str) -> str:
    """Resolve a collision asset only when it remains inside the build directory."""
    if (not isinstance(relative_path, str) or not relative_path or os.path.isabs(relative_path)
            or ntpath.isabs(relative_path) or ntpath.splitdrive(relative_path)[0]):
        raise ValueError("Collision mesh path must be relative to the build directory")
    root = os.path.realpath(build_dir)
    target = os.path.realpath(os.path.join(root, relative_path))
    try:
        common = os.path.commonpath((root, target))
    except ValueError as exc:
        raise ValueError("Collision mesh path must remain inside the build directory") from exc
    if os.path.normcase(common) != os.path.normcase(root) or os.path.normcase(target) == os.path.normcase(root):
        raise ValueError("Collision mesh path must remain inside the build directory")
    return target


def _physical_face_assignments(manifest: dict, tile: dict, material: TerrainMaterial,
                               vertices: np.ndarray, faces: np.ndarray) -> list[str | None]:
    """Apply manual paint over stable dominant-surface physical assignments."""
    surfaces = build_surfaces(manifest, material)
    automatic: list[str | None] = [None] * len(faces)
    collision = tile.get("collision")
    manifest_version = manifest.get("format_version", 0)
    if (manifest_version >= 4 and isinstance(collision, dict)
            and "used_surfaces" not in collision):
        raise ValueError(f"{tile['id']}: collision used_surfaces metadata is missing; rebuild")
    used_surfaces = collision.get("used_surfaces", []) if isinstance(collision, dict) else []
    if (not isinstance(used_surfaces, list)
            or any(isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(surfaces)
                   for index in used_surfaces)):
        raise ValueError(f"{tile['id']}: invalid collision used_surfaces metadata")
    if manifest_version >= 4 and isinstance(collision, dict) and not used_surfaces:
        raise ValueError(f"{tile['id']}: empty collision used_surfaces metadata; rebuild")
    fields = weight_fields(vertices) if manifest_version >= 4 else []
    if fields:
        if len(fields) != len(surfaces):
            raise ValueError(f"{tile['id']}: collision surface weights do not match the build surface order")
        weights = np.column_stack([vertices[name] for name in fields])
        dominant = np.empty(len(faces), np.int64)
        for start in range(0, len(faces), 65_536):
            stop = min(start + 65_536, len(faces))
            chunk_weights = weights[faces[start:stop]].sum(axis=1, dtype=np.uint16)
            dominant[start:stop] = np.argmax(chunk_weights, axis=1)
        automatic = [surfaces[int(index)].physical_material_id or "" for index in dominant]
        automatic = [ident or None for ident in automatic]

    paint = material.physical_paint
    if paint is None or not material.has_physical_paint():
        return automatic
    _physical_paint_window(manifest, tile, material)
    source = manifest.get("source")
    bounds = manifest.get("bounds_m")
    source_width = source.get("width") if isinstance(source, dict) else None
    source_height = source.get("height") if isinstance(source, dict) else None
    spacing = manifest.get("spacing_m")
    if (not isinstance(source_width, int) or not isinstance(source_height, int)
            or source_width < 1 or source_height < 1
            or not isinstance(bounds, list) or len(bounds) != 4
            or not isinstance(spacing, (int, float)) or not np.isfinite(spacing) or spacing <= 0):
        raise ValueError("Physical paint requires valid heightmap dimensions, bounds and spacing in the build manifest")
    cell = material.physical_paint_cell
    expected_shape = (int(np.ceil(source_height / cell)), int(np.ceil(source_width / cell)))
    if paint.shape != expected_shape:
        raise ValueError("Physical paint dimensions do not match the heightmap used to build these tiles")
    if not np.isfinite(vertices["x"]).all() or not np.isfinite(vertices["y"]).all():
        raise ValueError(f"{tile.get('id', 'Tile')}: collision coordinates must be finite for physical paint")
    origin = tile.get("origin_m")
    if not isinstance(origin, list) or len(origin) < 2:
        raise ValueError(f"{tile.get('id', 'Tile')}: invalid tile origin for physical paint")
    center_x = float(origin[0]) + vertices["x"][faces].mean(axis=1)
    center_y = float(origin[1]) + vertices["y"][faces].mean(axis=1)
    columns = np.rint((center_x - float(bounds[0])) / spacing).astype(np.int64)
    rows = np.rint((source_height - 1) - (center_y - float(bounds[1])) / spacing).astype(np.int64)
    columns = np.clip(columns, 0, source_width - 1) // cell
    rows = np.clip(rows, 0, source_height - 1) // cell
    labels = paint[rows, columns]
    return [
        automatic[index] if int(label) == 255 else material.physical_materials[int(label)].id
        for index, label in enumerate(labels)
    ]


def _tile_has_physical_paint(manifest: dict, tile: dict, material: TerrainMaterial) -> bool:
    window = _physical_paint_window(manifest, tile, material)
    if window is None:
        return False
    r0, r1, c0, c1 = window
    return bool(np.any(material.physical_paint[r0:r1, c0:c1] != 255))


def _validate_collision_records(manifest: dict) -> None:
    """Reject partial collision builds instead of exporting a misleading collider subset."""
    tiles = manifest.get("tiles", [])
    if not isinstance(tiles, list):
        raise ValueError("Manifest tiles must be an array")
    if any(not isinstance(tile, dict) for tile in tiles):
        raise ValueError("Manifest tile records must be objects")
    present = [tile.get("collision") is not None for tile in tiles]
    summary = manifest.get("collision")
    has_collision = summary is not None
    if any(present) and (not all(present) or not has_collision):
        raise ValueError("Collision data must be present for every tile and in the manifest summary")
    if has_collision and (not tiles or not all(present)):
        raise ValueError("Collision summary does not match the tile collision records")
    if has_collision and not isinstance(summary, dict):
        raise ValueError("Collision summary must be an object")
    for tile in tiles:
        record = tile.get("collision")
        if record is None:
            continue
        if (not isinstance(record, dict) or not isinstance(record.get("file"), str)
                or not record["file"] or not isinstance(record.get("digest"), str)
                or not record["digest"]):
            raise ValueError(f"{tile['id']}: invalid collision mesh record")
        _collision_file_path(manifest["_dir"], record["file"])


def load_index(out_dir: str) -> dict:
    path = os.path.join(out_dir, INDEX_NAME)
    try:
        with open(path, encoding="utf-8") as handle:
            index = json.load(handle)
    except (OSError, ValueError):
        return {}
    if index.get("format") != INDEX_FORMAT or not isinstance(index.get("tiles"), dict):
        return {}
    return index


def changed_tiles(manifest: dict, material: TerrainMaterial, settings: ExportSettings,
                  material_fp: str | None = None, tile_material_keys: dict[str, str] | None = None,
                  control_map_source_digest: str | None = None) -> list[str]:
    """IDs of tiles whose exported file is missing or out of date."""
    out_dir = os.path.abspath(settings.out_dir)
    known = load_index(out_dir).get("tiles", {})
    tile_size = float(manifest["tile_size_m"])
    texture_hashes: dict[str, str] = {}
    material_fp = material_fp or material_key(manifest, material, texture_hashes)
    if settings.control_map_resolution:
        if control_map_source_digest is None:
            control_map_source_digest = _control_map_source_fingerprint(_control_map_source(manifest, material))
            material_fp = _control_map_material_fingerprint(material_fp, control_map_source_digest)
            tile_material_keys = None
        if tile_material_keys is None:
            tile_material_keys = _include_control_map_source(
                _tile_material_keys(manifest, material, material_fp, texture_hashes),
                control_map_source_digest)
    else:
        tile_material_keys = tile_material_keys if tile_material_keys is not None else _tile_material_keys(
            manifest, material, material_fp, texture_hashes)
    texture_flags = _tile_texture_settings(manifest, material)
    changed = []
    for tile in manifest["tiles"]:
        record = known.get(tile["id"])
        digest = tile_digest(tile, tile_material_keys[tile["id"]], settings, tile_size, *texture_flags[tile["id"]])
        if (digest is None or not isinstance(record, dict) or record.get("digest") != digest
                or not os.path.isfile(os.path.join(out_dir, f"{tile['id']}.adm"))):
            changed.append(tile["id"])
    return changed


# ------------------------------------------------------------------------------ geometry
def tile_geometry(vertices: np.ndarray, faces: np.ndarray, size_m: list[float], tangents: bool) -> dict:
    """PLY tile (Z up, origin at the tile corner) -> ADM arrays (Y up, origin at the tile centre)."""
    hx, hy = size_m[0] / 2.0, size_m[1] / 2.0
    position = np.column_stack([vertices["x"] - hx, vertices["z"], -(vertices["y"] - hy)]).astype(np.float32)
    normal = np.column_stack([vertices["nx"], vertices["nz"], -vertices["ny"]]).astype(np.float64)
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    out = {
        "POSITION": position,
        "NORMAL": normal.astype(np.float32),
        "TEXCOORD_0": np.column_stack([vertices["s"], 1.0 - vertices["t"]]).astype(np.float32),
        "weights": np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.uint8),
        "indices": np.ascontiguousarray(faces, np.int64),
    }
    if tangents:
        # UV0 U runs east (+X) and V south (+Z), so w = +1: cross(N, T) points north (-Z) = -V.
        tangent = np.array([1.0, 0.0, 0.0]) - normal * normal[:, :1]
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        out["TANGENT"] = np.column_stack([tangent, np.ones(len(tangent))]).astype(np.float32)
    return out


def _tile_palette_conflicts_by_lod(manifest: dict, tile: dict) -> list[int]:
    """Count palette-conflicting triangles separately for each tile LOD."""
    build_dir = manifest["_dir"]
    counts = []
    for record in tile["lods"]:
        vertices, faces = read_ply(os.path.join(build_dir, record["file"]))
        weights = np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.uint8)
        _, count = triangle_masks(weights, faces)
        counts.append(count)
    return counts


def triangle_masks(weights: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, int]:
    """Return each triangle's four-layer palette and the number needing reduction.

    On conflicting triangles, retain the dominant surface at every corner before
    filling the remaining palette slots by stable aggregate weight.
    """
    corner = weights[faces]  # (nf, 3, S)
    present = corner.max(axis=1) > PRESENT
    counts = present.sum(axis=1)
    over = counts > SURFACES_PER_BIOME
    if over.any():
        conflicting = corner[over].astype(np.int32)
        required = np.zeros_like(present[over])
        for corner_index in range(3):
            corner_weights = conflicting[:, corner_index]
            nonzero = corner_weights.sum(axis=1) > 0
            rows = np.flatnonzero(nonzero)
            required[rows, corner_weights[nonzero].argmax(axis=1)] = True
        totals = conflicting.sum(axis=1)
        eligible = present[over] & ~required
        scores = np.where(eligible, totals, -1)
        order = np.argsort(-scores, axis=1, kind="stable")
        ranks = np.empty_like(order)
        np.put_along_axis(ranks, order, np.broadcast_to(np.arange(weights.shape[1]), order.shape), axis=1)
        remaining = SURFACES_PER_BIOME - required.sum(axis=1)
        present[over] = required | (eligible & (ranks < remaining[:, None]))
    empty = counts == 0
    if empty.any():  # all corners at <= 2/255 everywhere cannot happen with sums of 255, but stay safe
        present[empty, np.argmax(corner[empty].sum(axis=1), axis=1)] = True
    bits = (present.astype(np.uint64) << np.arange(weights.shape[1], dtype=np.uint64)).sum(axis=1, dtype=np.uint64)
    return bits, int(over.sum())


def _palette_conflict_details(weights: np.ndarray, faces: np.ndarray, surfaces: list[Surface], tile_id: str,
                              lod: int, limit: int) -> list[dict]:
    """Describe omitted corner weights for a bounded, deterministic sample of conflicting triangles."""
    masks, _ = triangle_masks(weights, faces)
    corners = weights[faces]
    present = corners.max(axis=1) > PRESENT
    conflict_indices = np.flatnonzero(present.sum(axis=1) > SURFACES_PER_BIOME)
    details = []
    for triangle_index in conflict_indices[:max(0, limit)]:
        palette = int(masks[triangle_index])
        dropped = []
        for surface_index, surface in enumerate(surfaces):
            corner_weights = corners[triangle_index, :, surface_index]
            if corner_weights.max() <= PRESENT or palette & (1 << surface_index):
                continue
            dropped.append({
                "id": surface.id,
                "name": surface.name,
                "corner_weights": [int(weight) for weight in corner_weights],
            })
        details.append({
            "tile_id": tile_id,
            "lod": lod,
            "triangle_index": int(triangle_index),
            "dropped_surfaces": dropped,
        })
    return details


def _tile_palette_conflict_details(manifest: dict, tile: dict, material: TerrainMaterial,
                                   limit: int = MAX_PALETTE_CONFLICT_DETAILS) -> list[dict]:
    surfaces = build_surfaces(manifest, material)
    details = []
    for lod, record in enumerate(tile["lods"]):
        if len(details) >= limit:
            break
        vertices, faces = read_ply(os.path.join(manifest["_dir"], record["file"]))
        weights = np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.uint8)
        details.extend(_palette_conflict_details(
            weights, faces, surfaces, tile["id"], lod, limit - len(details)))
    return details


def seam_consistent_weights(
    weights: np.ndarray, faces: np.ndarray, face_palettes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce weights to the common palette at each shared vertex.

    Each face palette must include its vertices' dominant surfaces. The
    intersection across incident face palettes then guarantees that a vertex
    has the same effective surface weights in every primitive using it.
    Returned errors are per-vertex total-variation distances from the original
    normalized weights, in the range [0, 1].
    """
    weights = np.asarray(weights)
    faces = np.asarray(faces)
    face_palettes = np.asarray(face_palettes, dtype=np.uint64)
    if weights.ndim != 2 or weights.shape[1] > 64:
        raise ValueError("Surface weights must be a 2D array with at most 64 layers")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("Faces must be a triangle index array")
    if face_palettes.shape != (len(faces),):
        raise ValueError("Each face must have one material palette")
    if len(faces) and (faces.min() < 0 or faces.max() >= len(weights)):
        raise ValueError("Face index is outside the vertex-weight array")

    allowed = np.full(len(weights), np.iinfo(np.uint64).max, dtype=np.uint64)
    if len(faces):
        np.bitwise_and.at(allowed, faces.reshape(-1), np.repeat(face_palettes, 3))
    channels = np.left_shift(np.uint64(1), np.arange(weights.shape[1], dtype=np.uint64))
    included = (allowed[:, None] & channels[None, :]) != 0
    reduced = np.where(included, weights, 0).astype(weights.dtype, copy=False)
    totals = weights.astype(np.uint64).sum(axis=1)
    retained = reduced.astype(np.uint64).sum(axis=1)
    errors = np.zeros(len(weights), dtype=np.float64)
    valid = totals > 0
    errors[valid] = (totals[valid] - retained[valid]) / totals[valid]
    return reduced, errors


def _popcount(value: int) -> int:
    return bin(value).count("1")


def group_masks(masks: Iterable[int]) -> tuple[list[int], dict[int, int]]:
    """Greedy cover of triangle masks by sets of at most four surfaces.

    Returns ``(sets, assign)``: the set bitmasks and, per input mask, the index of its set.
    """
    sets: list[int] = []
    assign: dict[int, int] = {}
    for mask in sorted(set(int(m) for m in masks), key=lambda m: (-_popcount(m), m)):
        best = None
        for i, s in enumerate(sets):
            if mask & ~s == 0:
                cost = (0, _popcount(s))
            elif _popcount(s | mask) <= SURFACES_PER_BIOME:
                cost = (1, _popcount(s | mask))
            else:
                continue
            if best is None or cost < best[0]:
                best = (cost, i)
        if best is None:
            sets.append(mask)
            assign[mask] = len(sets) - 1
        else:
            sets[best[1]] |= mask
            assign[mask] = best[1]
    return sets, assign


def _slots(set_mask: int) -> list[int]:
    return [i for i in range(64) if set_mask >> i & 1]


def color1(weights: np.ndarray, slots: list[int]) -> np.ndarray:
    """U8 COLOR_1 for the given surfaces: their weights renormalised to 255, unused channels 0."""
    chosen = weights[:, slots].astype(np.float64)
    total = chosen.sum(axis=1, keepdims=True)
    out = np.zeros((len(weights), 4), np.uint8)
    scaled = np.where(total > 0, chosen / np.maximum(total, 1e-9), 0.0)
    out[:, :len(slots)] = np.clip(np.round(scaled * 255.0), 0, 255).astype(np.uint8)
    return out


# ----------------------------------------------------------------------------- textures
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _texture_uri(prepared) -> str:
    stem = _SAFE.sub("_", prepared.name).strip("._") or "texture"
    return f"{TEXTURE_DIR}/{stem[:48]}_{prepared.sha256[:12]}{prepared.extension}"


def _write_sidecar(out_dir: str, uri: str, data: bytes) -> None:
    target = os.path.join(out_dir, *uri.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        with open(target, "rb") as handle:
            if handle.read() != data:
                raise ValueError(f"{uri} already exists with different content") from None


def _texture_key(surface: Surface, name: str, default_encoding: str) -> tuple[str, str, str, int | None]:
    encoding = surface.gpu_encodings.get(name, default_encoding)
    if name in ("metallic", "roughness", "ao", "height"):
        slot = getattr(surface, f"{name}_map")
        path, role = slot.path, "data"
        channel = slot.channel if encoding in SCALAR_GPU_ENCODINGS else None
    else:
        path, role = getattr(surface, name), "normal" if name == "normal" else "albedo"
        channel = None
    return path, role, encoding, channel


def _surface_texture_slots(surface: Surface, default_encoding: str):
    for name in ("albedo", "metallic", "roughness", "normal", "ao", "height", "emission"):
        key = _texture_key(surface, name, default_encoding)
        if key[0]:
            yield key


def _material_params(surfaces: list[Surface], uv_scale: list[float],
                     texture_index: Callable[[Surface, str], int], material: TerrainMaterial,
                     advanced: bool, texture_assets: dict[tuple[str, str, str, int | None], PreparedTexture],
                     default_encoding: str) -> dict:
    def channel(surface: Surface, name: str, slot: MapSlot) -> int:
        if slot.path:
            prepared = texture_assets[_texture_key(surface, name, default_encoding)]
            if prepared.channel_remapped or (slot.channel in (1, 2) and prepared.grayscale_source):
                return 0
        return slot.channel

    params: dict = {}
    for i, surface in enumerate(surfaces):
        if surface.albedo:
            params[f"layer{i}_texture"] = {"index": texture_index(surface, "albedo")}
        params[f"layer{i}_base_color"] = [srgb_to_linear(c) for c in surface.color] + [1.0]
        params[f"layer{i}_metallic"] = float(surface.metallic)
        params[f"layer{i}_roughness"] = float(surface.roughness)
        for kind, slot in (("metallic", surface.metallic_map), ("roughness", surface.roughness_map)):
            if slot.path:
                params[f"layer{i}_{kind}_texture"] = {"index": texture_index(surface, kind)}
                params[f"layer{i}_{kind}_channel"] = float(channel(surface, kind, slot))
                params[f"layer{i}_{kind}_invert"] = bool(slot.invert)
        if surface.normal:
            params[f"layer{i}_normal"] = {"index": texture_index(surface, "normal")}
        if advanced:
            for name, slot in (("ao", surface.ao_map), ("height", surface.height_map)):
                if slot.path:
                    params[f"layer{i}_{name}_texture"] = {"index": texture_index(surface, name)}
                params[f"layer{i}_{name}_channel"] = float(channel(surface, name, slot))
                params[f"layer{i}_{name}_invert"] = bool(slot.invert)
            params[f"layer{i}_ao_strength"] = float(surface.ao_strength)
            params[f"layer{i}_height_scale"] = float(surface.height_scale)
            params[f"layer{i}_height_bias"] = float(surface.height_bias)
            params[f"layer{i}_parallax_scale"] = float(surface.parallax_scale)
            if surface.emission:
                params[f"layer{i}_emissive_texture"] = {
                    "index": texture_index(surface, "emission")}
            params[f"layer{i}_emissive"] = [1.0, 1.0, 1.0] if surface.emission else [0.0, 0.0, 0.0]
    params["uv_scale"] = (list(uv_scale) + [1.0] * 4)[:4]
    if advanced:
        params.update({
            "height_blend_enabled": bool(material.height_blend_enabled),
            "height_blend_transition": float(material.height_blend_transition),
            "height_blend_strength": float(material.height_blend_strength),
            "parallax_mode": material.parallax_mode,
            "parallax_min_steps": float(material.parallax_min_steps),
            "parallax_max_steps": float(material.parallax_max_steps),
        })
    return params


# ---------------------------------------------------------------------------------- tile
def build_tile_document(manifest: dict, tile: dict, material: TerrainMaterial, settings: ExportSettings,
                        texture_assets: dict[tuple[str, str, str, int | None], PreparedTexture],
                        texture_uris: dict[tuple[str, str, str, int | None], tuple[str, str | None]],
                        control_map_source: dict | None = None) -> tuple[dict, object, dict]:
    """Return ``(doc, chunks, stats)``; ``doc`` and ``chunks`` are ready for ``write_container``.

    ``stats`` reports per-LOD primitive counts, palette conflicts, and the
    per-vertex total-variation error introduced by approximate reduction.
    """
    buffers, constants, _container, _validate = _core()
    if material.terrain_shader_version == SHADER_VERSION and material.has_advanced_shader_features():
        raise ValueError("Advanced terrain settings require the explicit terrain shader version 2.1.0.")
    if settings.control_map_resolution and control_map_source is None:
        raise ValueError("Control Map export requires a prepared source heightmap and surface rules")
    build_dir = manifest["_dir"]
    b = buffers.BinBuilder()
    tile_size = float(manifest["tile_size_m"])
    surfaces = build_surfaces(manifest, material)
    uv_all = material.uv_scale(tile_size, surfaces)

    lods = []
    conflict_details = []
    for lod_index, record in enumerate(tile["lods"]):
        vertices, faces = read_ply(os.path.join(build_dir, record["file"]))
        weights = np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.uint8)
        if weights.shape[1] != len(surfaces):
            raise ValueError(f"{record['file']}: {weights.shape[1]} weights for {len(surfaces)} surfaces; rebuild")
        used_surfaces = np.flatnonzero(np.any(weights > 0, axis=0)).tolist()
        if "used_surfaces" in record and record["used_surfaces"] != used_surfaces:
            raise ValueError(f"{record['file']}: used_surfaces metadata does not match the tile; rebuild")
        masks, conflicts = triangle_masks(weights, faces)
        if len(conflict_details) < MAX_PALETTE_CONFLICT_DETAILS:
            conflict_details.extend(_palette_conflict_details(
                weights, faces, surfaces, tile["id"], lod_index,
                MAX_PALETTE_CONFLICT_DETAILS - len(conflict_details)))
        lods.append((vertices, faces, masks, conflicts, weights))
    sets, assign = group_masks(np.concatenate([lod[2] for lod in lods]))
    if control_map_source is not None and "external_mask" in control_map_source:
        surface_index = {surface.id: index for index, surface in enumerate(surfaces)}
        external_slots = [surface_index[ident] for ident in control_map_source["surface_ids"]]
        external_mask = sum(1 << index for index in external_slots)
        sets = [external_mask]
        assign = {int(mask): 0 for mask in assign}
    if control_map_source is not None:
        palette_pixels = len(sets) * settings.control_map_resolution ** 2
        if palette_pixels > 16_777_216:
            raise ValueError(f"{tile['id']}: Control Maps for {len(sets)} palettes at "
                             f"{settings.control_map_resolution}px exceed the per-tile pixel limit")
    resolved_lods = []
    for vertices, faces, masks, conflicts, weights in lods:
        face_palettes = np.fromiter(
            (sets[assign[int(mask)]] for mask in masks), dtype=np.uint64, count=len(masks))
        effective_weights, reduction_errors = seam_consistent_weights(weights, faces, face_palettes)
        resolved_lods.append((vertices, faces, masks, conflicts, effective_weights, reduction_errors))
    lods = resolved_lods
    total_conflicts = sum(lod[3] for lod in lods)
    if (total_conflicts and settings.palette_conflict_policy == "STRICT"
            and not (control_map_source is not None and "external_mask" in control_map_source)):
        raise ValueError(f"Strict export rejected {total_conflicts:,} triangles that need more than four "
                         "surfaces. Choose the explicit Approximate palette policy to export with "
                         "measurable weight reduction.")
    used = sorted({i for s in sets for i in _slots(s)})
    advanced = material.terrain_shader_version == "2.1.0"
    tangents = any(
        surfaces[i].normal
        or (advanced and material.parallax_mode != "NONE" and surfaces[i].height_map.path
            and surfaces[i].parallax_scale > 0.0)
        for i in used
    )

    images: list[dict] = []
    textures: list[dict] = []
    samplers = ([{"wrapS": "CLAMP_TO_EDGE", "wrapT": "CLAMP_TO_EDGE"}]
                if control_map_source is not None else [])
    by_slot: dict[tuple[str, str, str, int | None], int] = {}

    def prepared_texture_index(key: tuple[str, str, str, int | None], prepared: PreparedTexture) -> int:
        path, role, encoding, channel = key
        shared_key = key if prepared.channel_remapped else (path, role, encoding, None)
        if shared_key not in by_slot:
            if settings.embed_textures:
                primary_view = b.add_view(prepared.primary.data, chunk_type="IMAG")
                images.append({"bufferView": primary_view, "mimeType": prepared.primary.mime,
                               "name": prepared.primary.name})
            else:
                primary_uri, fallback_uri = texture_uris[key]
                images.append({"uri": primary_uri, "mimeType": prepared.primary.mime,
                               "sha256": prepared.primary.sha256, "name": prepared.primary.name})
            texture = {"source": len(images) - 1}
            if prepared.fallback is not None:
                if settings.embed_textures:
                    fallback_view = b.add_view(prepared.fallback.data, chunk_type="IMAG")
                    images.append({"bufferView": fallback_view, "mimeType": prepared.fallback.mime,
                                   "name": prepared.fallback.name})
                else:
                    if fallback_uri is None:
                        raise ValueError(f"Missing fallback URI for texture '{path}'")
                    images.append({"uri": fallback_uri, "mimeType": prepared.fallback.mime,
                                   "sha256": prepared.fallback.sha256, "name": prepared.fallback.name})
                texture["fallbackSource"] = len(images) - 1
            textures.append(texture)
            by_slot[shared_key] = len(textures) - 1
        return by_slot[shared_key]

    def texture_index(surface: Surface, name: str) -> int:
        key = _texture_key(surface, name, settings.gpu_encoding)
        return prepared_texture_index(key, texture_assets[key])

    def pbr_normal_index(surface: Surface) -> int:
        path, _, encoding, channel = _texture_key(surface, "normal", settings.gpu_encoding)
        image = texture_assets[(path, "normal", encoding, channel)].pbr_normal
        if image is None:
            return texture_index(surface, "normal")
        key = (path, "pbr_normal", encoding, None)
        if key not in by_slot:
            if settings.embed_textures:
                view = b.add_view(image.data, chunk_type="IMAG")
                images.append({"bufferView": view, "mimeType": image.mime, "name": image.name})
            else:
                images.append({"uri": _texture_uri(image), "mimeType": image.mime,
                               "sha256": image.sha256, "name": image.name})
            textures.append({"source": len(images) - 1})
            by_slot[key] = len(textures) - 1
        return by_slot[key]

    def control_map_texture_index(palette_index: int, slots: list[int]) -> int:
        if control_map_source is None:
            raise ValueError("Control Map source was not prepared")
        bounds = _tile_source_bounds(manifest, tile, control_map_source["heightmap"].shape)
        output_size = (settings.control_map_resolution, settings.control_map_resolution)
        if "external_mask" in control_map_source:
            target_ids = tuple(surfaces[slot].id for slot in slots)
            pixels = rasterize_external_control_map(
                control_map_source["external_mask"], control_map_source["heightmap"].shape,
                bounds, output_size, tuple(control_map_source["surface_ids"]), target_ids,
            )
        else:
            map_slots = tuple(slots + [-1] * (4 - len(slots)))
            pixels = rasterize_control_map(
                control_map_source["rules"], control_map_source["heightmap"],
                control_map_source["scale"], control_map_source["offset"],
                control_map_source["spacing"], bounds, output_size, map_slots,
            )
        image = _png_image(pixels, f"{tile['id']}_control_{palette_index}")
        if settings.embed_textures:
            view = b.add_view(image.data, chunk_type="IMAG")
            images.append({"bufferView": view, "mimeType": image.mime, "name": image.name})
        else:
            uri = _texture_uri(image)
            _write_sidecar(os.path.abspath(settings.out_dir), uri, image.data)
            images.append({"uri": uri, "mimeType": image.mime, "sha256": image.sha256, "name": image.name})
        textures.append({"source": len(images) - 1, "sampler": 0})
        return len(textures) - 1

    macro_texture_index = None
    macro_color_enabled = bool(material.macro_color.path)
    if macro_color_enabled:
        macro_key = (material.macro_color.path, "macro_color", settings.gpu_encoding, None)
        macro_texture_index = prepared_texture_index(macro_key, texture_assets[macro_key])

    for i in used:  # stable texture order: surface by surface
        for name in ("albedo", "metallic", "roughness", "normal", "ao", "height", "emission"):
            if _texture_key(surfaces[i], name, settings.gpu_encoding)[0]:
                texture_index(surfaces[i], name)

    materials = []
    palette_slots: list[list[int]] = []
    for k, set_mask in enumerate(sets):
        slots = _slots(set_mask)
        if control_map_source is not None:
            slots = slots + [i for i in range(len(surfaces)) if i not in slots][:4 - len(slots)]
        if macro_color_enabled:
            slots = slots + [i for i in range(len(surfaces)) if i not in slots][:4 - len(slots)]
        palette_slots.append(slots)
        chosen = [surfaces[i] for i in slots]
        base = chosen[0]
        exported_material = {
            "name": f"AWT Terrain {tile['id']} {'+'.join(s.name for s in chosen)}",
            "extensions": {
                constants.TERRAIN_SURFACE_EXT: {
                    "version": "1.0.0",
                    "surfaceIds": [surface.id for surface in chosen],
                },
            },
            "baseColorFactor": [srgb_to_linear(c) for c in base.color] + [1.0],
            "metallicFactor": float(base.metallic),
            "roughnessFactor": float(base.roughness),
            "emissiveFactor": [1.0, 1.0, 1.0] if base.emission else [0.0, 0.0, 0.0],
            "alphaMode": "OPAQUE",
            "doubleSided": bool(material.double_sided),
            "animationId": f"awt_terrain_{tile['id']}_{k}",
            "shader": {"id": SHADER_ID, "version": material.terrain_shader_version},
            "shaderParameters": _material_params(
                chosen, [uv_all[i] for i in slots], texture_index, material, advanced, texture_assets,
                settings.gpu_encoding),
        }
        if control_map_source is not None:
            exported_material["extensions"][constants.TERRAIN_CONTROL_MAP_EXT] = {
                "version": "1.0.0",
                "mode": "TEXTURE_RGBA",
                "texture": {"index": control_map_texture_index(k, _slots(set_mask)), "texCoord": 0},
                "mapping": "UV",
            }
        if macro_color_enabled:
            macro = material.macro_color
            texture_ref = {"index": macro_texture_index}
            if macro.projection == "LOCAL_UV":
                texture_ref["texCoord"] = 0
            macro_extension = {
                "version": "1.0.0",
                "texture": texture_ref,
                "projection": macro.projection,
                "blendMode": macro.blend_mode,
                "strength": float(macro.strength),
                "layerInfluence": [float(value) for value in macro.layer_influence],
                "scale": [float(value) for value in macro.scale],
                "offset": [float(value) for value in macro.offset],
            }
            if macro.projection == "SHARED_WORLD_XZ":
                macro_extension["origin"] = [float(value) for value in macro.origin]
            exported_material["extensions"][constants.TERRAIN_MACRO_COLOR_EXT] = macro_extension
        if base.albedo:
            exported_material["baseColorTexture"] = {"index": texture_index(base, "albedo")}
        if base.normal:
            exported_material["normalTexture"] = {"index": pbr_normal_index(base)}
        if base.emission:
            exported_material["emissiveTexture"] = {"index": texture_index(base, "emission")}
        materials.append(exported_material)

    meshes = []
    stats = {"primitives": [], "conflicts": 0, "reduced_vertices": 0, "physical_triangles": 0,
             "painted_physical_tile": False,
             "reduction_error_sum": 0.0, "max_reduction_error": 0.0,
             "conflict_details": conflict_details, "conflicts_by_lod": [],
             "vertex_weight_samples_by_lod": [], "vertex_weight_sums_by_lod": []}
    for lod, (vertices, faces, masks, conflicts, effective_weights, reduction_errors) in enumerate(lods):
        stats["conflicts"] += conflicts
        stats["conflicts_by_lod"].append(conflicts)
        geom = tile_geometry(vertices, faces, tile["size_m"], tangents)
        geom["weights"] = effective_weights
        affected = reduction_errors[reduction_errors > 0]
        stats["reduced_vertices"] += int(len(affected))
        stats["reduction_error_sum"] += float(affected.sum())
        if len(affected):
            stats["max_reduction_error"] = max(stats["max_reduction_error"], float(affected.max()))
        set_of_face = np.array([assign[int(m)] for m in masks], np.int64) if len(masks) else np.zeros(0, np.int64)
        primitives = []
        vertex_weight_samples = 0
        vertex_weight_sums = np.zeros(len(surfaces), dtype=np.uint64)
        for k in np.unique(set_of_face):
            face_rows = geom["indices"][set_of_face == k]
            keep, local = np.unique(face_rows.reshape(-1), return_inverse=True)
            slots = palette_slots[int(k)]
            encoded_weights = color1(geom["weights"][keep], slots)
            vertex_weight_sums[slots] += encoded_weights[:, :len(slots)].sum(axis=0, dtype=np.uint64)
            vertex_weight_samples += len(keep)
            attributes = {name: b.add_accessor(geom[name][keep], "F32", acc_type) for name, acc_type in
                          (("POSITION", "VEC3"), ("NORMAL", "VEC3"), ("TANGENT", "VEC4"), ("TEXCOORD_0", "VEC2"))
                          if name in geom}
            attributes["COLOR_1"] = b.add_accessor(encoded_weights, "U8", "VEC4", normalized=True)
            index_type = "U16" if len(keep) <= 65535 else "U32"
            indices = b.add_accessor(local.astype(np.uint32), index_type, "SCALAR")
            primitives.append({"attributes": attributes, "indices": indices, "material": int(k)})
        stats["vertex_weight_samples_by_lod"].append(vertex_weight_samples)
        stats["vertex_weight_sums_by_lod"].append({
            surfaces[index].id: int(vertex_weight_sums[index])
            for index in np.flatnonzero(vertex_weight_sums)
        })
        stats["primitives"].append(len(primitives))
        meshes.append({"name": f"{tile['id']}_lod{lod}", "primitives": primitives})

    collision_record = tile.get("collision")
    collision_mesh = None
    physical_material_records = []
    if collision_record is not None:
        if not isinstance(collision_record, dict) or not isinstance(collision_record.get("file"), str):
            raise ValueError(f"{tile['id']}: invalid collision mesh record")
        vertices, faces = read_ply(_collision_file_path(build_dir, collision_record["file"]))
        hx, hy = tile["size_m"][0] / 2.0, tile["size_m"][1] / 2.0
        position = np.column_stack(
            [vertices["x"] - hx, vertices["z"], -(vertices["y"] - hy)]).astype(np.float32)
        position_accessor = b.add_accessor(position, "F32", "VEC3")
        face_materials = _physical_face_assignments(manifest, tile, material, vertices, faces)
        stats["physical_triangles"] = sum(ident is not None for ident in face_materials)
        stats["painted_physical_tile"] = _tile_has_physical_paint(manifest, tile, material)
        primitives = []
        unassigned = np.asarray([ident is None for ident in face_materials], dtype=bool)

        def append_primitive(face_mask: np.ndarray, material_id: str | None = None) -> None:
            primitive_indices = np.ascontiguousarray(faces[face_mask].reshape(-1), np.int64)
            index_type = "U16" if len(position) <= 65535 else "U32"
            index_dtype = np.uint16 if index_type == "U16" else np.uint32
            primitive = {
                "attributes": {"POSITION": position_accessor},
                "indices": b.add_accessor(primitive_indices.astype(index_dtype), index_type, "SCALAR"),
            }
            if material_id is not None:
                primitive["extensions"] = {
                    constants.PHYSICAL_SURFACES_EXT: {
                        "faceMaterials": [material_id] * int(np.count_nonzero(face_mask))
                    }
                }
            primitives.append(primitive)

        if np.any(unassigned):
            append_primitive(unassigned)
        used_ids = list(dict.fromkeys(ident for ident in face_materials if ident is not None))
        materials_by_id = {item.id: item for item in material.physical_materials}
        for material_id in used_ids:
            mask = np.asarray([ident == material_id for ident in face_materials], dtype=bool)
            append_primitive(mask, material_id)
            item = materials_by_id[material_id]
            record = {"id": item.id, "friction": float(item.friction), "restitution": float(item.restitution)}
            if item.profile:
                record["profile"] = item.profile
            physical_material_records.append(record)
        collision_mesh = {
            "name": f"{tile['id']}_collision",
            "primitives": primitives,
        }

    x0, y0 = tile["origin_m"][0], tile["origin_m"][1]
    cx, cy = x0 + tile["size_m"][0] / 2.0, y0 + tile["size_m"][1] / 2.0
    root = {"name": tile["id"], "translation": [cx, 0.0, -cy]}
    nodes = [root]
    doc: dict = {"asset": {"generator": GENERATOR}, "scene": 0,
                 "scenes": [{"name": tile["id"], "nodes": [0]}], "nodes": nodes}
    if len(meshes) == 1:
        root["mesh"] = 0
    else:
        root["children"] = list(range(1, len(meshes) + 1))
        first = settings.lod_distance_m or tile_size
        levels = []
        for lod in range(len(meshes)):
            nodes.append({"name": f"{tile['id']}_LOD{lod}", "mesh": lod})
            levels.append({"node": lod + 1, "minDistance": 0.0 if lod == 0 else first * 2 ** (lod - 1)})
        doc["lodGroups"] = [{"name": f"{tile['id']}_LODs", "levels": levels}]
    if collision_mesh is not None:
        collision_mesh_index = len(meshes)
        meshes.append(collision_mesh)
        collider_node = len(nodes)
        nodes.append({"name": f"{tile['id']}_Collision"})
        root.setdefault("children", []).append(collider_node)
        doc["colliders"] = [{
            "name": f"{tile['id']}_TerrainCollider",
            "node": collider_node,
            "shape": "MESH",
            "mesh": collision_mesh_index,
        }]
    doc["meshes"] = meshes
    doc["materials"] = materials
    if physical_material_records:
        doc["physicalMaterials"] = physical_material_records
    if textures:
        doc["textures"] = textures
        doc["images"] = images
    if samplers:
        doc["samplers"] = samplers
    extensions = [constants.VERTEX_CONTROL_EXT, constants.TERRAIN_SURFACE_EXT]
    required_extensions = [constants.VERTEX_CONTROL_EXT]
    if control_map_source is not None:
        extensions.append(constants.TERRAIN_CONTROL_MAP_EXT)
        required_extensions.append(constants.TERRAIN_CONTROL_MAP_EXT)
    if macro_color_enabled:
        extensions.append(constants.TERRAIN_MACRO_COLOR_EXT)
        required_extensions.append(constants.TERRAIN_MACRO_COLOR_EXT)
    if physical_material_records:
        extensions.append(constants.PHYSICAL_SURFACES_EXT)
        required_extensions.append(constants.PHYSICAL_SURFACES_EXT)
    if not settings.embed_textures and any("uri" in image for image in images):
        extensions.append(constants.EXTERNAL_IMAGES_EXT)
        required_extensions.append(constants.EXTERNAL_IMAGES_EXT)
    doc["extensionsUsed"] = list(extensions)
    doc["extensionsRequired"] = required_extensions
    doc["accessors"] = b.accessors
    doc["bufferViews"] = b.buffer_views
    if stats["reduced_vertices"]:
        stats["mean_reduction_error"] = stats["reduction_error_sum"] / stats["reduced_vertices"]
    else:
        stats["mean_reduction_error"] = 0.0
    return doc, b.bytes(), stats


def _atomic_write(path: str, data: bytes) -> None:
    temp = f"{path}.{threading.get_ident()}.tmp"
    with open(temp, "wb") as handle:
        handle.write(data)
    os.replace(temp, path)


# -------------------------------------------------------------------------------- export
def export_tiles(
    manifest: dict,
    material: TerrainMaterial,
    settings: ExportSettings,
    mode: str = "changed",
    selected: Iterable[str] | None = None,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Write tile ADM files.

    Returns ``{"written", "skipped", "bytes", "seconds", "out_dir", "settings", "conflicts",
    "max_primitives", "warnings"}``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    settings.validate_values()
    material.validate()
    _validate_collision_records(manifest)
    if material.has_physical_paint() and not manifest.get("collision"):
        raise ValueError("Physical surface paint requires built collision meshes; enable collision generation and rebuild")
    _buffers, _constants, container, validate = _core()
    report = progress or (lambda fraction, message: None)
    is_cancelled = cancelled or (lambda: False)
    started = time.perf_counter()
    out_dir = os.path.abspath(settings.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    tile_size = float(manifest["tile_size_m"])

    report(0.0, "Hashing material")
    surfaces = build_surfaces(manifest, material)
    texture_hashes: dict[str, str] = {}
    material_fp = material_key(manifest, material, texture_hashes)
    control_map_data = None
    control_map_digest = None
    if settings.control_map_resolution:
        if len(surfaces) < 4:
            raise ValueError("Control Map export requires at least four defined terrain surfaces")
        _buffers, constants, _container, _validate = _core()
        if (SHADER_ID, material.terrain_shader_version) not in constants.TERRAIN_CONTROL_MAP_PROFILES:
            raise ValueError(f"Control Map export is unsupported by terrain shader profile "
                             f"{SHADER_ID}@{material.terrain_shader_version}")
        control_map_data = _control_map_source(manifest, material)
        control_map_digest = _control_map_source_fingerprint(control_map_data)
        material_fp = _control_map_material_fingerprint(material_fp, control_map_digest)
    tile_material_keys = _tile_material_keys(manifest, material, material_fp, texture_hashes)
    if control_map_digest is not None:
        tile_material_keys = _include_control_map_source(tile_material_keys, control_map_digest)
    texture_flags = _tile_texture_settings(manifest, material)
    warnings = []
    if rules_outdated(manifest, material):
        warnings.append("Biomes, paint or surfaces changed since the build; rebuild to update the vertex layers")
    if material.terrain_shader_version == "2.1.0":
        warnings.append("Portable PBR fallbacks use only the first layer's textures and factors; they do not "
                        "represent vertex-weighted layers, metallic/roughness maps, AO maps, "
                        "height blending or parallax.")
    tiles = {tile["id"]: tile for tile in manifest["tiles"]}
    if mode == "all":
        todo = list(tiles)
    elif mode == "selected":
        todo = [tile_id for tile_id in (selected or []) if tile_id in tiles]
    else:
        todo = changed_tiles(manifest, material, settings, material_fp, tile_material_keys,
                             control_map_digest)

    if settings.palette_conflict_policy == "STRICT" and todo:
        conflicts_by_tile_lod = {}
        conflicts = 0
        for tile_id in todo:
            lod_counts = _tile_palette_conflicts_by_lod(manifest, tiles[tile_id])
            tile_conflicts = sum(lod_counts)
            conflicts += tile_conflicts
            if tile_conflicts:
                conflicts_by_tile_lod[tile_id] = lod_counts
        if conflicts:
            conflicts_by_lod = {}
            for counts in conflicts_by_tile_lod.values():
                for lod, count in enumerate(counts):
                    conflicts_by_lod[lod] = conflicts_by_lod.get(lod, 0) + count
            details = []
            for tile_id in sorted(todo):
                if len(details) >= MAX_PALETTE_CONFLICT_DETAILS:
                    break
                details.extend(_tile_palette_conflict_details(
                    manifest, tiles[tile_id], material, MAX_PALETTE_CONFLICT_DETAILS - len(details)))
            detail_lines = [
                f"  {item['tile_id']} LOD {item['lod']} triangle {item['triangle_index']}: omitted "
                + ", ".join(
                    f"{surface['name']} ({surface['id']}) U8 corner weights (0-255) "
                    f"{surface['corner_weights']}" for surface in item["dropped_surfaces"])
                for item in details
            ]
            if conflicts > len(details):
                detail_lines.append(f"  ... {conflicts - len(details):,} more conflicting triangles")
            lod_summary = ", ".join(
                f"LOD {lod}: {count:,}" for lod, count in sorted(conflicts_by_lod.items()) if count)
            tile_lod_summary = [
                f"  {tile_id} LOD {lod}: {count:,} conflicts"
                for tile_id, counts in sorted(conflicts_by_tile_lod.items())
                for lod, count in enumerate(counts) if count
            ]
            if len(tile_lod_summary) > 20:
                tile_lod_summary = tile_lod_summary[:20] + [
                    f"  ... {len(tile_lod_summary) - 20:,} more tile/LOD entries"
                ]
            detail_text = "\nAffected triangle details:\n" + "\n".join(detail_lines) if detail_lines else ""
            summary_text = (f"\nConflicts by LOD across selected tiles: {lod_summary}\n"
                            "Conflicts by tile and LOD:\n" + "\n".join(tile_lod_summary))
            raise ValueError(f"Strict export rejected {conflicts:,} triangles that need more than four surfaces. "
                             "Choose the explicit Approximate palette policy to export with measurable "
                             f"weight reduction.{summary_text}{detail_text}\nSuggestion: reduce overlapping surface weights "
                             "or paint fewer active surfaces with Surface on the Map tab.")

    texture_assets: dict[tuple[str, str, str, int | None], PreparedTexture] = {}
    texture_uris: dict[tuple[str, str, str, int | None], tuple[str, str | None]] = {}
    if todo:
        texture_keys = dict.fromkeys(key for surface in surfaces
                                     for key in _surface_texture_slots(surface, settings.gpu_encoding))
        if material.macro_color.path:
            texture_keys[(material.macro_color.path, "macro_color", settings.gpu_encoding, None)] = None
        for key in texture_keys:
            path, role, encoding, channel = key
            prepared = prepare_adm_texture(path, role, settings.gpu_container, encoding,
                                           settings.convert_gpu_sources, channel)
            texture_assets[key] = prepared
            if prepared.reencoded_source:
                warnings.append(f"Texture '{path}' was explicitly re-encoded; original GPU bytes and mip levels "
                                "were replaced.")
            if prepared.channel_remapped and channel != 0:
                warnings.append(f"Texture '{path}' exports its selected channel in red for {encoding}.")
            if prepared.fallback is None:
                warnings.append(f"Texture '{path}' uses a 16-bit PNG primary to avoid precision loss.")
            elif settings.gpu_container != "DDS" or encoding != "AUTO":
                from adm_blender.core import gputex
                info = gputex.parse(prepared.primary.data, prepared.primary.mime, strict=True)
                expected_mime = (gputex.MIME_DDS if settings.gpu_container == "DDS" else gputex.MIME_KTX2)
                if (prepared.primary.mime != expected_mime or
                        (encoding != "AUTO" and info["kind"] != encoding)):
                    warnings.append(f"Texture '{path}' retains {info['kind']} in "
                                    f"{'DDS' if prepared.primary.mime == gputex.MIME_DDS else 'KTX2'} "
                                    "to preserve its source or 16-bit precision.")
            if prepared.grayscale_source and any(
                slot.path == path and slot.channel in (1, 2)
                for surface in surfaces
                for slot in (surface.metallic_map, surface.roughness_map, surface.ao_map, surface.height_map)
            ):
                warnings.append(f"Grayscale texture '{path}' uses red for green/blue channel selections in ADM.")
            if not settings.embed_textures:
                primary_uri = _texture_uri(prepared.primary)
                fallback_uri = None
                _write_sidecar(out_dir, primary_uri, prepared.primary.data)
                if prepared.fallback is not None:
                    fallback_uri = _texture_uri(prepared.fallback)
                    _write_sidecar(out_dir, fallback_uri, prepared.fallback.data)
                if prepared.pbr_normal is not None:
                    _write_sidecar(out_dir, _texture_uri(prepared.pbr_normal), prepared.pbr_normal.data)
                texture_uris[key] = (primary_uri, fallback_uri)

    def run(tile_id: str):
        if is_cancelled():
            raise Cancelled()
        tile = tiles[tile_id]
        doc, chunks, stats = build_tile_document(
            manifest, tile, material, settings, texture_assets, texture_uris, control_map_data)
        data = container.write_container(_constants.ADM_MAGIC, doc, chunks)
        path = os.path.join(out_dir, f"{tile_id}.adm")
        if settings.validate:
            result = validate.validate_adm_resolved(data, path)
            if not result.ok:
                raise ValueError(f"Tile {tile_id} failed ADM validation:\n{result.format(10)}")
        _atomic_write(path, data)
        return tile_id, len(data), stats

    index = load_index(out_dir)
    records = {tile_id: record for tile_id, record in index.get("tiles", {}).items() if tile_id in tiles}
    written: list[str] = []
    total_bytes = 0
    conflicts = 0
    reduced_vertices = 0
    reduction_error_sum = 0.0
    max_reduction_error = 0.0
    conflict_details = []
    conflicts_by_lod = {}
    conflicts_by_tile_lod = {}
    vertex_weight_totals_by_lod = {}
    vertex_weight_samples_by_lod = {}
    vertex_weight_totals_by_tile_lod = {}
    vertex_weight_samples_by_tile_lod = {}
    max_primitives = 0
    physical_triangles = 0
    physical_tiles_without_assignments = 0
    threads = settings.threads or os.cpu_count() or 1
    worker_limit = min(threads, 2) if settings.control_map_resolution else threads
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(worker_limit, len(todo) or 1))) as pool:
            futures = [pool.submit(run, tile_id) for tile_id in todo]
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    tile_id, size, stats = future.result()
                    conflicts += stats["conflicts"]
                    tile_lod_counts = stats["conflicts_by_lod"]
                    conflicts_by_tile_lod[tile_id] = {
                        lod: count for lod, count in enumerate(tile_lod_counts) if count
                    }
                    for lod, count in enumerate(tile_lod_counts):
                        conflicts_by_lod[lod] = conflicts_by_lod.get(lod, 0) + count
                    tile_weight_sums = stats["vertex_weight_sums_by_lod"]
                    tile_weight_samples = stats["vertex_weight_samples_by_lod"]
                    vertex_weight_totals_by_tile_lod[tile_id] = {}
                    vertex_weight_samples_by_tile_lod[tile_id] = {}
                    for lod, sums in enumerate(tile_weight_sums):
                        samples = tile_weight_samples[lod]
                        vertex_weight_samples_by_tile_lod[tile_id][lod] = samples
                        vertex_weight_totals_by_tile_lod[tile_id][lod] = sums
                        vertex_weight_samples_by_lod[lod] = (
                            vertex_weight_samples_by_lod.get(lod, 0) + samples)
                        lod_totals = vertex_weight_totals_by_lod.setdefault(lod, {})
                        for surface_id, value in sums.items():
                            lod_totals[surface_id] = lod_totals.get(surface_id, 0) + value
                    reduced_vertices += stats["reduced_vertices"]
                    reduction_error_sum += stats["reduction_error_sum"]
                    max_reduction_error = max(max_reduction_error, stats["max_reduction_error"])
                    conflict_details.extend(stats["conflict_details"])
                    conflict_details = sorted(conflict_details, key=lambda item: (
                        item["tile_id"], item["lod"], item["triangle_index"]))[:MAX_PALETTE_CONFLICT_DETAILS]
                    max_primitives = max([max_primitives] + stats["primitives"])
                    physical_triangles += stats["physical_triangles"]
                    if stats["painted_physical_tile"] and stats["physical_triangles"] == 0:
                        physical_tiles_without_assignments += 1
                    written.append(tile_id)
                    total_bytes += size
                    tile = tiles[tile_id]
                    records[tile_id] = {"file": f"{tile_id}.adm", "digest": tile_digest(tile, tile_material_keys[tile_id], settings,
                                                                                        tile_size, *texture_flags[tile_id]),
                                        "origin_m": tile["origin_m"], "size_m": tile["size_m"]}
                    report(done / len(todo), f"Exported {done} of {len(todo)} tiles")
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
    finally:
        # Record what was written even when a later tile failed or the user cancelled.
        index_doc = {
            "format": INDEX_FORMAT,
            "format_version": INDEX_VERSION,
            "generator": GENERATOR,
            "source_manifest": os.path.join(manifest["_dir"], "manifest.json"),
            "tile_size_m": tile_size,
            "tiles_x": manifest.get("tiles_x"),
            "tiles_y": manifest.get("tiles_y"),
            "settings": settings.key(),
            "material": material_fp,
            "tiles": dict(sorted(records.items())),
        }
        _atomic_write(os.path.join(out_dir, INDEX_NAME), json.dumps(index_doc, indent=1).encode("utf-8"))
    seconds = time.perf_counter() - started
    report(1.0, f"Exported {len(written)} tiles in {seconds:.1f} s")
    mean_reduction_error = reduction_error_sum / reduced_vertices if reduced_vertices else 0.0
    mean_exported_weights_by_lod = {
        lod: {
            surface_id: value / (255.0 * vertex_weight_samples_by_lod[lod])
            for surface_id, value in sorted(totals.items())
        }
        for lod, totals in sorted(vertex_weight_totals_by_lod.items())
        if vertex_weight_samples_by_lod.get(lod, 0)
    }
    mean_exported_weights_by_tile_lod = {
        tile_id: {
            lod: {
                surface_id: value / (255.0 * vertex_weight_samples_by_tile_lod[tile_id][lod])
                for surface_id, value in sorted(totals.items())
            }
            for lod, totals in sorted(lod_totals.items())
            if vertex_weight_samples_by_tile_lod[tile_id][lod]
        }
        for tile_id, lod_totals in sorted(vertex_weight_totals_by_tile_lod.items())
    }
    if settings.palette_conflict_policy == "APPROXIMATE" and conflicts:
        warnings.append(
            f"Approximate palette reduction affected {reduced_vertices:,} vertex instances across exported "
            f"tile LODs; per-vertex total-variation error ranged from "
            f"{mean_reduction_error:.1%} mean to {max_reduction_error:.1%} maximum.")
    if material.has_physical_paint() and physical_tiles_without_assignments:
        warnings.append(
            f"Physical paint produced no assigned collision triangles in "
            f"{physical_tiles_without_assignments:,} exported tile(s); increase collision detail or widen the painted areas.")
    return {"written": sorted(written), "skipped": len(tiles) - len(written), "bytes": total_bytes,
            "seconds": seconds, "out_dir": out_dir, "settings": asdict(settings), "conflicts": conflicts,
            "max_primitives": max_primitives, "reduced_vertices": reduced_vertices,
            "physical_triangles": physical_triangles,
            "physical_tiles_without_assignments": physical_tiles_without_assignments,
            "mean_reduction_error": mean_reduction_error, "max_reduction_error": max_reduction_error,
            "conflicts_by_lod": dict(sorted(conflicts_by_lod.items())),
            "conflicts_by_tile_lod": {
                tile_id: counts for tile_id, counts in sorted(conflicts_by_tile_lod.items()) if counts
            },
            "mean_exported_weights_by_lod": mean_exported_weights_by_lod,
            "mean_exported_weights_by_tile_lod": mean_exported_weights_by_tile_lod,
            "conflict_details": conflict_details,
            "conflict_details_truncated": max(0, conflicts - len(conflict_details)),
            "warnings": warnings}
