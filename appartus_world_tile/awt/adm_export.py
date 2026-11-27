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
from .material import (GPU_ENCODINGS, SCALAR_GPU_ENCODINGS, SHADER_ID, SHADER_VERSION, SURFACES_PER_BIOME,
                       MapSlot, PreparedImage, Surface, TerrainMaterial,
                       MAX_TEXTURE_BYTES, MAX_TEXTURE_PIXELS, prepare_texture, srgb_to_linear)
from .ply import read_ply, weight_fields

INDEX_NAME = "world.json"
INDEX_FORMAT = "apparatus-world-tile-export"
INDEX_VERSION = 5
TEXTURE_DIR = "textures"
GENERATOR = f"Apparatus World Tile {__version__} (ADM 1.0)"
MODES = ("changed", "selected", "all")
GPU_CONTAINERS = ("DDS", "KTX2")
GPU_EXPORT_ENCODINGS = ("AUTO", "BC7", "RGBA8")
PRESENT = 2  # a surface counts for a triangle when one corner weighs more than 2/255

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
    convert_gpu_sources: bool = False

    def key(self) -> dict:
        """Settings that change the written files."""
        return {"lod_distance_m": self.lod_distance_m, "embed_textures": self.embed_textures,
                "gpu_container": self.gpu_container, "gpu_encoding": self.gpu_encoding,
                "convert_gpu_sources": self.convert_gpu_sources}

    def validate_values(self) -> None:
        if not self.out_dir:
            raise ValueError("Choose an export folder")
        if not (self.lod_distance_m >= 0 and np.isfinite(self.lod_distance_m)):
            raise ValueError("LOD distance must be zero or a positive number of metres")
        if self.gpu_container not in GPU_CONTAINERS or self.gpu_encoding not in GPU_EXPORT_ENCODINGS:
            raise ValueError("Unsupported GPU container or encoding; choose a supported export setting")
        if not isinstance(self.convert_gpu_sources, bool):
            raise ValueError("GPU source conversion setting must be true or false")


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

    color_role = role == "albedo"
    compression = {"albedo": "AUTO", "normal": "RGBA8", "data": "BC3"}.get(role)
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
    settings_key = settings.key()
    if not uses_textures:
        settings_key.pop("gpu_container")
        settings_key.pop("gpu_encoding")
        settings_key.pop("convert_gpu_sources")
    elif not uses_default_encoding:
        settings_key.pop("gpu_encoding")
    payload = {"lods": lods, "material": material_fp, "settings": settings_key, "origin": tile["origin_m"],
               "size": tile["size_m"], "tile_size": tile_size_m, "format": INDEX_VERSION}
    return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(), digest_size=16).hexdigest()


def material_key(manifest: dict, material: TerrainMaterial, texture_hashes: dict[str, str] | None = None) -> str:
    """Material fingerprint plus the build's surface order (it maps weights to surfaces)."""
    tile_size = float(manifest["tile_size_m"])
    order = (manifest.get("texturing") or {}).get("surfaces") or []
    return hashlib.blake2b(json.dumps([material.fingerprint(tile_size, texture_hashes=texture_hashes), order]).encode(),
                           digest_size=16).hexdigest()


def _tile_material_keys(manifest: dict, material: TerrainMaterial, fallback: str,
                        texture_hashes: dict[str, str]) -> dict[str, str]:
    surfaces = build_surfaces(manifest, material)
    tile_size = float(manifest["tile_size_m"])
    order = (manifest.get("texturing") or {}).get("surfaces") or []
    cached: dict[tuple[int, ...], str] = {}
    keys = {}
    for tile in manifest["tiles"]:
        lods = tile["lods"]
        if not lods or any("used_surfaces" not in lod for lod in lods):
            keys[tile["id"]] = fallback
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
        if subset not in cached:
            fingerprint = material.fingerprint(tile_size, [surfaces[i] for i in subset], texture_hashes)
            cached[subset] = hashlib.blake2b(
                json.dumps([fingerprint, order, subset]).encode(), digest_size=16).hexdigest()
        keys[tile["id"]] = cached[subset]
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
                  material_fp: str | None = None, tile_material_keys: dict[str, str] | None = None) -> list[str]:
    """IDs of tiles whose exported file is missing or out of date."""
    out_dir = os.path.abspath(settings.out_dir)
    known = load_index(out_dir).get("tiles", {})
    tile_size = float(manifest["tile_size_m"])
    texture_hashes: dict[str, str] = {}
    material_fp = material_fp or material_key(manifest, material, texture_hashes)
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


def triangle_masks(weights: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, int]:
    """Bitmask of the surfaces each triangle needs (at most four) and how many triangles needed more."""
    corner = weights[faces]  # (nf, 3, S)
    present = corner.max(axis=1) > PRESENT
    counts = present.sum(axis=1)
    over = counts > SURFACES_PER_BIOME
    if over.any():
        totals = corner[over].astype(np.int32).sum(axis=1)
        keep = np.argsort(-totals, axis=1, kind="stable")[:, :SURFACES_PER_BIOME]
        trimmed = np.zeros_like(present[over])
        np.put_along_axis(trimmed, keep, True, axis=1)
        present[over] &= trimmed
    empty = counts == 0
    if empty.any():  # all corners at <= 2/255 everywhere cannot happen with sums of 255, but stay safe
        present[empty, np.argmax(corner[empty].sum(axis=1), axis=1)] = True
    bits = (present.astype(np.uint64) << np.arange(weights.shape[1], dtype=np.uint64)).sum(axis=1, dtype=np.uint64)
    return bits, int(over.sum())


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
                        texture_uris: dict[tuple[str, str, str, int | None], tuple[str, str | None]]) -> tuple[dict, object, dict]:
    """Return ``(doc, chunks, stats)``; ``doc`` and ``chunks`` are ready for ``write_container``.

    ``stats`` holds ``primitives`` (per LOD) and ``conflicts`` (triangles that needed more than
    four surfaces and lost the weakest ones).
    """
    buffers, constants, _container, _validate = _core()
    if material.terrain_shader_version == SHADER_VERSION and material.has_advanced_shader_features():
        raise ValueError("Advanced terrain settings require the explicit terrain shader version 2.1.0.")
    build_dir = manifest["_dir"]
    b = buffers.BinBuilder()
    tile_size = float(manifest["tile_size_m"])
    surfaces = build_surfaces(manifest, material)
    uv_all = material.uv_scale(tile_size, surfaces)

    lods = []
    for record in tile["lods"]:
        vertices, faces = read_ply(os.path.join(build_dir, record["file"]))
        weights = np.column_stack([vertices[name] for name in weight_fields(vertices)]).astype(np.uint8)
        if weights.shape[1] != len(surfaces):
            raise ValueError(f"{record['file']}: {weights.shape[1]} weights for {len(surfaces)} surfaces; rebuild")
        used_surfaces = np.flatnonzero(np.any(weights > 0, axis=0)).tolist()
        if "used_surfaces" in record and record["used_surfaces"] != used_surfaces:
            raise ValueError(f"{record['file']}: used_surfaces metadata does not match the tile; rebuild")
        masks, conflicts = triangle_masks(weights, faces)
        lods.append((vertices, faces, masks, conflicts))
    sets, assign = group_masks(np.concatenate([lod[2] for lod in lods]))
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
    by_slot: dict[tuple[str, str, str, int | None], int] = {}

    def texture_index(surface: Surface, name: str) -> int:
        key = _texture_key(surface, name, settings.gpu_encoding)
        path, role, encoding, channel = key
        prepared = texture_assets[key]
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

    for i in used:  # stable texture order: surface by surface
        for name in ("albedo", "metallic", "roughness", "normal", "ao", "height", "emission"):
            if _texture_key(surfaces[i], name, settings.gpu_encoding)[0]:
                texture_index(surfaces[i], name)

    materials = []
    for k, set_mask in enumerate(sets):
        slots = _slots(set_mask)
        chosen = [surfaces[i] for i in slots]
        base = chosen[0]
        exported_material = {
            "name": f"AWT Terrain {tile['id']} {'+'.join(s.name for s in chosen)}",
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
        if base.albedo:
            exported_material["baseColorTexture"] = {"index": texture_index(base, "albedo")}
        if base.normal:
            exported_material["normalTexture"] = {"index": pbr_normal_index(base)}
        if base.emission:
            exported_material["emissiveTexture"] = {"index": texture_index(base, "emission")}
        materials.append(exported_material)

    meshes = []
    stats = {"primitives": [], "conflicts": 0}
    for lod, (vertices, faces, masks, conflicts) in enumerate(lods):
        stats["conflicts"] += conflicts
        geom = tile_geometry(vertices, faces, tile["size_m"], tangents)
        set_of_face = np.array([assign[int(m)] for m in masks], np.int64) if len(masks) else np.zeros(0, np.int64)
        primitives = []
        for k in np.unique(set_of_face):
            face_rows = geom["indices"][set_of_face == k]
            keep, local = np.unique(face_rows.reshape(-1), return_inverse=True)
            attributes = {name: b.add_accessor(geom[name][keep], "F32", acc_type) for name, acc_type in
                          (("POSITION", "VEC3"), ("NORMAL", "VEC3"), ("TANGENT", "VEC4"), ("TEXCOORD_0", "VEC2"))
                          if name in geom}
            attributes["COLOR_1"] = b.add_accessor(color1(geom["weights"][keep], _slots(sets[int(k)])), "U8", "VEC4",
                                                   normalized=True)
            index_type = "U16" if len(keep) <= 65535 else "U32"
            indices = b.add_accessor(local.astype(np.uint32), index_type, "SCALAR")
            primitives.append({"attributes": attributes, "indices": indices, "material": int(k)})
        stats["primitives"].append(len(primitives))
        meshes.append({"name": f"{tile['id']}_lod{lod}", "primitives": primitives})

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
    doc["meshes"] = meshes
    doc["materials"] = materials
    if textures:
        doc["textures"] = textures
        doc["images"] = images
    extensions = [constants.VERTEX_CONTROL_EXT]
    if not settings.embed_textures and any("uri" in image for image in images):
        extensions.append(constants.EXTERNAL_IMAGES_EXT)
    doc["extensionsUsed"] = list(extensions)
    doc["extensionsRequired"] = list(extensions)
    doc["accessors"] = b.accessors
    doc["bufferViews"] = b.buffer_views
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
    tile_material_keys = _tile_material_keys(manifest, material, material_fp, texture_hashes)
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
        todo = changed_tiles(manifest, material, settings, material_fp, tile_material_keys)

    texture_assets: dict[tuple[str, str, str, int | None], PreparedTexture] = {}
    texture_uris: dict[tuple[str, str, str, int | None], tuple[str, str | None]] = {}
    if todo:
        texture_keys = dict.fromkeys(key for surface in surfaces
                                     for key in _surface_texture_slots(surface, settings.gpu_encoding))
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
        doc, chunks, stats = build_tile_document(manifest, tile, material, settings, texture_assets, texture_uris)
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
    max_primitives = 0
    threads = settings.threads or os.cpu_count() or 1
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(threads, len(todo) or 1))) as pool:
            futures = [pool.submit(run, tile_id) for tile_id in todo]
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    tile_id, size, stats = future.result()
                    conflicts += stats["conflicts"]
                    max_primitives = max([max_primitives] + stats["primitives"])
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
    return {"written": sorted(written), "skipped": len(tiles) - len(written), "bytes": total_bytes,
            "seconds": seconds, "out_dir": out_dir, "settings": asdict(settings), "conflicts": conflicts,
            "max_primitives": max_primitives, "warnings": warnings}
