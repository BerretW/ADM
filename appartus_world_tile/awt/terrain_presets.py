"""Portable named terrain presets with their referenced textures."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import unicodedata

from .material import TerrainMaterial, prepare_texture

PRESET_FILE = "preset.json"
PRESET_FORMAT = "appartus-world-tile-terrain-preset"
PRESET_VERSION = 4
MAX_PRESET_BYTES = 5 * 1024 * 1024
_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def preset_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
        raise ValueError("Preset name must contain 1 to 64 characters")
    ascii_name = unicodedata.normalize("NFKD", name.strip()).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold()).strip("-")
    if not key:
        raise ValueError("Preset name must contain at least one letter or number")
    return key[:64].strip("-")


def _inside(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
    except ValueError:
        return False


def _document(path: str) -> dict:
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError(f"Preset file is missing or is a link: {path}")
    if os.path.getsize(path) > MAX_PRESET_BYTES:
        raise ValueError("Preset file is larger than 5 MiB")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if (not isinstance(data, dict) or data.get("format") != PRESET_FORMAT
            or data.get("version") not in (1, 2, 3, PRESET_VERSION) or not isinstance(data.get("material"), dict)
            or not isinstance(data.get("name"), str)):
        raise ValueError("This is not a supported AWT terrain preset")
    return data


def _texture_paths(surface) -> list[tuple[object, str]]:
    return [
        (surface, "albedo"),
        (surface, "normal"),
        (surface.metallic_map, "path"),
        (surface.roughness_map, "path"),
        (surface.ao_map, "path"),
        (surface.height_map, "path"),
        (surface, "emission"),
    ]


def save_preset(root: str, name: str, material: TerrainMaterial, overwrite: bool = False) -> str:
    """Save material rules and validated image copies; return the preset directory."""
    key = preset_key(name)
    os.makedirs(root, exist_ok=True)
    root = os.path.realpath(root)
    folder = os.path.join(root, key)
    if os.path.islink(folder):
        raise ValueError("Preset folder cannot be a symbolic link")
    if os.path.exists(folder) and not os.path.isdir(folder):
        raise ValueError("A non-folder already uses this preset name")
    if os.path.isdir(folder) and not overwrite:
        raise FileExistsError(f"A preset named '{name.strip()}' already exists")
    if not _inside(root, folder) or folder == root:
        raise ValueError("Preset path is outside the preset library")
    if not os.path.isdir(folder):
        os.mkdir(folder)

    texture_dir = os.path.join(folder, "textures")
    if os.path.islink(texture_dir):
        raise ValueError("Preset texture folder cannot be a symbolic link")
    if not os.path.isdir(texture_dir):
        os.mkdir(texture_dir)
    if not _inside(folder, texture_dir):
        raise ValueError("Preset texture path is outside its folder")

    prepared_material = copy.deepcopy(material)
    prepared_material.paint = None
    prepared_material.surface_paint = None
    prepared_material.roads = []
    prepared_material.validate()
    for surface in prepared_material.surfaces:
        for slot, attr in _texture_paths(surface):
            source = getattr(slot, attr)
            if not source:
                continue
            prepared = prepare_texture(source)
            relative = os.path.join("textures", prepared.sha256 + prepared.extension)
            target = os.path.join(folder, relative)
            if not _inside(folder, target):
                raise ValueError("Texture path is outside the preset folder")
            if os.path.lexists(target):
                if os.path.islink(target) or not os.path.isfile(target):
                    raise ValueError("Preset texture target is not a regular file")
                with open(target, "rb") as handle:
                    if handle.read() != prepared.data:
                        raise ValueError("Existing preset texture has unexpected content")
            else:
                with open(target, "xb") as handle:
                    handle.write(prepared.data)
            setattr(slot, attr, target)

    document = {
        "format": PRESET_FORMAT,
        "version": (4 if any(s.gpu_encodings for s in prepared_material.surfaces) else
                    3 if prepared_material.has_advanced_shader_features() else
                    2 if any(b.noise != 0.0 for b in prepared_material.biomes) else 1),
        "name": name.strip(),
        "material": prepared_material.to_dict(folder),
    }
    preset_path = os.path.join(folder, PRESET_FILE)
    if os.path.islink(preset_path):
        raise ValueError("Preset file cannot be a symbolic link")
    fd, temporary = tempfile.mkstemp(prefix=".preset-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, preset_path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return folder


def list_presets(root: str) -> list[tuple[str, str]]:
    if not os.path.isdir(root):
        return []
    root = os.path.realpath(root)
    presets = []
    for entry in os.scandir(root):
        if not entry.is_dir(follow_symlinks=False) or not _KEY_RE.fullmatch(entry.name):
            continue
        path = os.path.join(entry.path, PRESET_FILE)
        if not os.path.exists(path):
            continue
        if not _inside(root, path):
            raise ValueError("Preset path is outside the preset library")
        document = _document(path)
        presets.append((document["name"], entry.name))
    return sorted(presets, key=lambda item: item[0].casefold())


def load_preset(root: str, key: str) -> TerrainMaterial:
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise ValueError("Invalid preset name")
    root = os.path.realpath(root)
    folder = os.path.join(root, key)
    if os.path.islink(folder) or not _inside(root, folder) or folder == root:
        raise ValueError("Preset folder is outside the preset library")
    document = _document(os.path.join(folder, PRESET_FILE))
    if any(key in document["material"] for key in ("paint", "surface_paint", "roads")):
        raise ValueError("Terrain presets cannot contain map-specific paint or roads")

    material = TerrainMaterial.from_dict(document["material"], folder)
    for surface in material.surfaces:
        for slot, attr in _texture_paths(surface):
            path = getattr(slot, attr)
            if not path:
                continue
            if not _inside(folder, path):
                raise ValueError(f"Preset texture is outside its folder: {path}")
            prepare_texture(path)
    material.validate()
    return material
