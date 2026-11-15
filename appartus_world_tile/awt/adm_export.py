"""Write built tiles straight to ADM 1.0 files with the TERRAIN_4 material.

One ``.adm`` per tile: a root node placed at the tile centre (so the tile lands at its world
position), one child per LOD with a ``lodGroups`` entry, the tile's blend mask embedded and
the four layer textures either written once into ``textures/`` (``ADM_external_images_v1``)
or embedded into every tile.

``world.json`` in the export folder records a digest per tile; with ``mode="changed"`` only
tiles whose geometry, mask, material or export settings differ from that record are written.
"""

from __future__ import annotations

import hashlib
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
from .material import SHADER_ID, SHADER_VERSION, TerrainMaterial, prepare_texture, srgb_to_linear
from .ply import read_ply

INDEX_NAME = "world.json"
INDEX_FORMAT = "apparatus-world-tile-export"
INDEX_VERSION = 1
TEXTURE_DIR = "textures"
GENERATOR = f"Apparatus World Tile {__version__} (ADM 1.0)"
MODES = ("changed", "selected", "all")

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

    def key(self) -> dict:
        """Settings that change the written files."""
        return {"lod_distance_m": self.lod_distance_m, "embed_textures": self.embed_textures}

    def validate_values(self) -> None:
        if not self.out_dir:
            raise ValueError("Choose an export folder")
        if not (self.lod_distance_m >= 0 and np.isfinite(self.lod_distance_m)):
            raise ValueError("LOD distance must be zero or a positive number of metres")


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


# ----------------------------------------------------------------------------------- digests
def tile_digest(tile: dict, material_fp: str, settings: ExportSettings, tile_size_m: float) -> str | None:
    """Digest of everything that goes into one tile file; None when the build has no digests."""
    lods = [lod.get("digest") for lod in tile["lods"]]
    if not all(lods) or ("mask" in tile and not tile.get("mask_digest")):
        return None
    payload = {"lods": lods, "mask": tile.get("mask_digest"), "material": material_fp,
               "settings": settings.key(), "origin": tile["origin_m"], "size": tile["size_m"],
               "tile_size": tile_size_m, "format": INDEX_VERSION}
    return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(), digest_size=16).hexdigest()


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
                  material_fp: str | None = None) -> list[str]:
    """IDs of tiles whose exported file is missing or out of date."""
    out_dir = os.path.abspath(settings.out_dir)
    known = load_index(out_dir).get("tiles", {})
    tile_size = float(manifest["tile_size_m"])
    material_fp = material_fp or material.fingerprint(tile_size)
    changed = []
    for tile in manifest["tiles"]:
        record = known.get(tile["id"])
        digest = tile_digest(tile, material_fp, settings, tile_size)
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
        "TEXCOORD_1": np.column_stack([vertices["s1"], 1.0 - vertices["t1"]]).astype(np.float32),
        "indices": np.ascontiguousarray(faces, np.uint32).reshape(-1),
    }
    if tangents:
        # UV0 U runs east (+X) and V south (+Z), so w = +1: cross(N, T) points north (-Z) = -V.
        tangent = np.array([1.0, 0.0, 0.0]) - normal * normal[:, :1]
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        out["TANGENT"] = np.column_stack([tangent, np.ones(len(tangent))]).astype(np.float32)
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


def _material_params(material: TerrainMaterial, tile_size_m: float, texture_index: Callable[[str], int],
                     mask_index: int | None) -> dict:
    params: dict = {}
    for i, layer in enumerate(material.layers):
        if layer.albedo:
            params[f"layer{i}_texture"] = {"index": texture_index(layer.albedo)}
        params[f"layer{i}_base_color"] = [srgb_to_linear(c) for c in layer.color] + [1.0]
        params[f"layer{i}_metallic"] = float(layer.metallic)
        params[f"layer{i}_roughness"] = float(layer.roughness)
        for kind, slot in (("metallic", layer.metallic_map), ("roughness", layer.roughness_map)):
            if slot.path:
                params[f"layer{i}_{kind}_texture"] = {"index": texture_index(slot.path)}
                params[f"layer{i}_{kind}_channel"] = float(slot.channel)
                params[f"layer{i}_{kind}_invert"] = bool(slot.invert)
        if layer.normal:
            params[f"layer{i}_normal"] = {"index": texture_index(layer.normal)}
    if mask_index is not None:
        params["blend_mask"] = {"index": mask_index, "texCoord": 1}
    params["uv_scale"] = material.uv_scale(tile_size_m)
    return params


# ---------------------------------------------------------------------------------- tile
def build_tile_document(manifest: dict, tile: dict, material: TerrainMaterial, settings: ExportSettings,
                        texture_uris: dict[str, str]) -> tuple[dict, object]:
    """Return ``(doc, chunks)`` ready for ``write_container``."""
    buffers, constants, _container, _validate = _core()
    build_dir = manifest["_dir"]
    b = buffers.BinBuilder()
    tile_size = float(manifest["tile_size_m"])
    tangents = any(layer.normal for layer in material.layers)

    images: list[dict] = []
    textures: list[dict] = []
    by_path: dict[str, int] = {}

    def texture_index(path: str) -> int:
        if path not in by_path:
            prepared = prepare_texture(path)
            if settings.embed_textures:
                view = b.add_view(prepared.data, chunk_type="IMAG")
                images.append({"bufferView": view, "mimeType": prepared.mime, "name": prepared.name})
            else:
                images.append({"uri": texture_uris[path], "mimeType": prepared.mime,
                               "sha256": prepared.sha256, "name": prepared.name})
            textures.append({"source": len(images) - 1})
            by_path[path] = len(textures) - 1
        return by_path[path]

    for layer in material.layers:  # stable texture order: layer by layer
        for path in layer.textures():
            texture_index(path)
    mask_index = None
    if tile.get("mask"):
        with open(os.path.join(build_dir, tile["mask"]), "rb") as handle:
            view = b.add_view(handle.read(), chunk_type="IMAG")
        images.append({"bufferView": view, "mimeType": "image/png", "name": f"{tile['id']}_mask"})
        textures.append({"source": len(images) - 1})
        mask_index = len(textures) - 1

    ground = material.layers[0]
    mat = {
        "name": f"AWT Terrain {tile['id']}",
        "baseColorFactor": [srgb_to_linear(c) for c in ground.color] + [1.0],
        "metallicFactor": float(ground.metallic),
        "roughnessFactor": float(ground.roughness),
        "emissiveFactor": [0.0, 0.0, 0.0],
        "alphaMode": "OPAQUE",
        "doubleSided": bool(material.double_sided),
        "animationId": f"awt_terrain_{tile['id']}",
        "shader": {"id": SHADER_ID, "version": SHADER_VERSION},
        "shaderParameters": _material_params(material, tile_size, texture_index, mask_index),
    }

    meshes = []
    for lod, record in enumerate(tile["lods"]):
        vertices, faces = read_ply(os.path.join(build_dir, record["file"]))
        geom = tile_geometry(vertices, faces, tile["size_m"], tangents)
        attributes = {name: b.add_accessor(geom[name], "F32", acc_type) for name, acc_type in
                      (("POSITION", "VEC3"), ("NORMAL", "VEC3"), ("TANGENT", "VEC4"),
                       ("TEXCOORD_0", "VEC2"), ("TEXCOORD_1", "VEC2")) if name in geom}
        index_type = "U16" if len(vertices) <= 65535 else "U32"
        indices = b.add_accessor(geom["indices"], index_type, "SCALAR")
        meshes.append({"name": f"{tile['id']}_lod{lod}",
                       "primitives": [{"attributes": attributes, "indices": indices, "material": 0}]})

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
    doc["materials"] = [mat]
    if textures:
        doc["textures"] = textures
        doc["images"] = images
    if not settings.embed_textures and any("uri" in image for image in images):
        doc["extensionsUsed"] = [constants.EXTERNAL_IMAGES_EXT]
        doc["extensionsRequired"] = [constants.EXTERNAL_IMAGES_EXT]
    doc["accessors"] = b.accessors
    doc["bufferViews"] = b.buffer_views
    return doc, b.bytes()


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
    """Write tile ADM files; returns ``{"written": [...], "skipped": n, "seconds": s, "out_dir": ...}``."""
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
    material_fp = material.fingerprint(tile_size)
    tiles = {tile["id"]: tile for tile in manifest["tiles"]}
    if mode == "all":
        todo = list(tiles)
    elif mode == "selected":
        todo = [tile_id for tile_id in (selected or []) if tile_id in tiles]
    else:
        todo = changed_tiles(manifest, material, settings, material_fp)

    texture_uris: dict[str, str] = {}
    if todo and not settings.embed_textures:
        for path in material.textures():
            prepared = prepare_texture(path)
            uri = _texture_uri(prepared)
            _write_sidecar(out_dir, uri, prepared.data)
            texture_uris[path] = uri

    def run(tile_id: str):
        if is_cancelled():
            raise Cancelled()
        tile = tiles[tile_id]
        doc, chunks = build_tile_document(manifest, tile, material, settings, texture_uris)
        data = container.write_container(_constants.ADM_MAGIC, doc, chunks)
        path = os.path.join(out_dir, f"{tile_id}.adm")
        if settings.validate:
            result = validate.validate_adm_resolved(data, path)
            if not result.ok:
                raise ValueError(f"Tile {tile_id} failed ADM validation:\n{result.format(10)}")
        _atomic_write(path, data)
        return tile_id, len(data)

    index = load_index(out_dir)
    records = {tile_id: record for tile_id, record in index.get("tiles", {}).items() if tile_id in tiles}
    written: list[str] = []
    total_bytes = 0
    threads = settings.threads or os.cpu_count() or 1
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(threads, len(todo) or 1))) as pool:
            futures = [pool.submit(run, tile_id) for tile_id in todo]
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    tile_id, size = future.result()
                    written.append(tile_id)
                    total_bytes += size
                    tile = tiles[tile_id]
                    records[tile_id] = {"file": f"{tile_id}.adm", "digest": tile_digest(tile, material_fp, settings,
                                                                                        tile_size),
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
            "seconds": seconds, "out_dir": out_dir, "settings": asdict(settings)}
