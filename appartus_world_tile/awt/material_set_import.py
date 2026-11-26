"""Deterministic discovery and import of split terrain material texture sets."""

from __future__ import annotations

import io
import os
import stat
import warnings
from dataclasses import dataclass

from .material import MAX_SURFACES, MAX_TEXTURE_BYTES, MAX_TEXTURE_PIXELS, Surface, TerrainMaterial

DEFAULT_SUFFIXES = {
    "albedo": ("_abte", "_albedo", "_basecolor", "_diffuse"),
    "normal": ("_nm", "_normal"),
    "ao": ("_ao", "_occlusion"),
    "roughness": ("_roughness",),
    "metallic": ("_metallic",),
    "height": ("_height", "_displacement"),
    "emission": ("_emission", "_emissive"),
}
MAP_NAMES = tuple(DEFAULT_SUFFIXES)
MAX_MATERIAL_SET_FILES = 10000
MAX_MATERIAL_SET_ENTRIES = 20000
MAX_MATERIAL_SET_IMPORT_BYTES = 1024 * 1024 * 1024
_PACKED_SUFFIX = "_ma"
_UNKNOWN_SUFFIX = "_unknown"
_SUPPORTED_IMAGE_FORMATS = frozenset({"PNG", "TIFF", "TGA"})


@dataclass(frozen=True)
class MaterialSet:
    name: str
    root: str
    files: dict[str, tuple[str, ...]]
    packed_maps: tuple[str, ...] = ()

    @property
    def missing_maps(self) -> tuple[str, ...]:
        return tuple(name for name in MAP_NAMES if not self.files.get(name))

    @property
    def conflicts(self) -> tuple[str, ...]:
        return tuple(name for name in MAP_NAMES if len(self.files.get(name, ())) > 1)


@dataclass(frozen=True)
class MaterialSetScan:
    root: str
    sets: tuple[MaterialSet, ...]
    unknown_files: tuple[str, ...]
    ignored_packed_files: tuple[str, ...]
    skipped_links: tuple[str, ...]
    suffixes: dict[str, tuple[str, ...]]


def normalize_suffixes(suffixes: dict[str, object] | None = None) -> dict[str, tuple[str, ...]]:
    """Validate configurable map suffixes and return normalized, non-ambiguous aliases."""
    supplied = DEFAULT_SUFFIXES if suffixes is None else suffixes
    if not isinstance(supplied, dict) or set(supplied) != set(MAP_NAMES):
        raise ValueError(f"Suffix configuration must define exactly: {', '.join(MAP_NAMES)}")
    normalized: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    reserved = {_PACKED_SUFFIX, _UNKNOWN_SUFFIX}
    for map_name in MAP_NAMES:
        values = supplied[map_name]
        if isinstance(values, str):
            values = values.split(",")
        if not isinstance(values, (tuple, list)):
            raise ValueError(f"Suffixes for {map_name} must be a comma-separated string or list")
        aliases = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError(f"Suffixes for {map_name} must be text")
            suffix = value.strip().casefold()
            if not suffix:
                continue
            if not suffix.startswith("_"):
                suffix = "_" + suffix
            if (len(suffix) > 40 or any(char in suffix for char in ("/", "\\", ".", ":", "\0"))
                    or suffix in reserved):
                raise ValueError(f"Invalid or reserved suffix {value!r}")
            if suffix in owners and owners[suffix] != map_name:
                raise ValueError(f"Suffix {suffix!r} is assigned to both {owners[suffix]} and {map_name}")
            owners[suffix] = map_name
            if suffix not in aliases:
                aliases.append(suffix)
        normalized[map_name] = tuple(aliases)
    return normalized


def _sort_path(root: str, path: str) -> tuple[str, str]:
    relative = os.path.relpath(path, root).replace("\\", "/")
    return relative.casefold(), relative


def _inside_root(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, os.path.realpath(path))) == root
    except ValueError:
        return False


def _recognized_map(stem: str, suffixes: dict[str, tuple[str, ...]]) -> tuple[str, str] | None:
    lowered = stem.casefold()
    options = sorted(((suffix, map_name) for map_name, aliases in suffixes.items()
                      for suffix in aliases), key=lambda option: (-len(option[0]), option[0], option[1]))
    for suffix, map_name in options:
        if lowered.endswith(suffix):
            name = stem[:-len(suffix)]
            if name.strip() and not any(ord(char) < 32 for char in name):
                return name, map_name
    return None


def scan_material_sets(root: str, suffixes: dict[str, object] | None = None) -> MaterialSetScan:
    """Recursively find split maps without following links or depending on file extensions."""
    if not isinstance(root, str) or not root or os.path.islink(root) or not os.path.isdir(root):
        raise ValueError("Choose a regular directory that is not a symbolic link")
    root = os.path.realpath(root)
    aliases = normalize_suffixes(suffixes)
    folders = [root]
    candidates: dict[str, dict[str, object]] = {}
    unknown: list[str] = []
    packed_files: dict[str, tuple[str, list[str]]] = {}
    skipped_links: list[str] = []
    file_count = 0
    entry_count = 0

    while folders:
        folder = folders.pop()
        with os.scandir(folder) as iterator:
            entries = sorted(iterator, key=lambda entry: (entry.name.casefold(), entry.name))
        child_dirs = []
        for entry in entries:
            entry_count += 1
            if entry_count > MAX_MATERIAL_SET_ENTRIES:
                raise ValueError(f"Directory contains more than {MAX_MATERIAL_SET_ENTRIES} entries")
            path = entry.path
            if entry.is_symlink() or not _inside_root(root, path):
                skipped_links.append(path)
            elif entry.is_dir(follow_symlinks=False):
                child_dirs.append(path)
            elif entry.is_file(follow_symlinks=False):
                file_count += 1
                if file_count > MAX_MATERIAL_SET_FILES:
                    raise ValueError(f"Directory contains more than {MAX_MATERIAL_SET_FILES} files")
                stem = os.path.splitext(entry.name)[0]
                if stem.casefold().endswith(_UNKNOWN_SUFFIX):
                    unknown.append(path)
                    continue
                if stem.casefold().endswith(_PACKED_SUFFIX):
                    name = stem[:-len(_PACKED_SUFFIX)]
                    if name:
                        key = name.casefold()
                        packed_files.setdefault(key, (name, []))[1].append(path)
                    else:
                        unknown.append(path)
                    continue
                recognized = _recognized_map(stem, aliases)
                if recognized is None:
                    unknown.append(path)
                    continue
                name, map_name = recognized
                key = name.casefold()
                record = candidates.setdefault(key, {"name": name, "files": {}})
                record["files"].setdefault(map_name, []).append(path)
        folders.extend(reversed(child_dirs))

    found = []
    for key, record in candidates.items():
        if not record["files"]:
            continue
        files = {
            map_name: tuple(sorted(paths, key=lambda path: _sort_path(root, path)))
            for map_name, paths in record["files"].items()
        }
        packed = packed_files.get(key, (record["name"], []))[1]
        found.append(MaterialSet(
            name=record["name"],
            root=root,
            files=files,
            packed_maps=tuple(sorted(packed, key=lambda path: _sort_path(root, path))),
        ))
    found.sort(key=lambda item: (item.name.casefold(), item.name))
    return MaterialSetScan(
        root=root,
        sets=tuple(found),
        unknown_files=tuple(sorted(unknown, key=lambda path: _sort_path(root, path))),
        ignored_packed_files=tuple(sorted(
            (path for _name, paths in packed_files.values() for path in paths),
            key=lambda path: _sort_path(root, path))),
        skipped_links=tuple(sorted(skipped_links, key=lambda path: _sort_path(root, path))),
        suffixes=aliases,
    )


def resolve_material_set(material_set: MaterialSet, choices: dict[tuple[str, str], str]) -> dict[str, str]:
    """Resolve map conflicts using explicit per-material, per-map file choices."""
    resolved = {}
    for map_name in MAP_NAMES:
        paths = material_set.files.get(map_name, ())
        if not paths:
            continue
        if len(paths) == 1:
            resolved[map_name] = paths[0]
            continue
        selected = choices.get((material_set.name, map_name))
        if selected not in paths:
            raise ValueError(f"Choose one {map_name} file for material set '{material_set.name}'")
        resolved[map_name] = selected
    return resolved


def _role_for_map(map_name: str) -> str:
    if map_name in ("albedo", "emission"):
        return "albedo"
    if map_name == "normal":
        return "normal"
    return "data"


def validate_material_set_files(material_set: MaterialSet, resolved: dict[str, str]) -> None:
    """Validate selected source files and their decoded image dimensions before applying them."""
    from PIL import Image
    from .adm_export import _core, prepare_adm_texture

    _core()
    from adm_blender.core import gputex
    if not isinstance(resolved, dict) or not set(resolved).issubset(MAP_NAMES):
        raise ValueError("Selected maps contain an unsupported material property")
    unique_paths = set(resolved.values())
    total_size = 0
    for path in unique_paths:
        if os.path.islink(path) or not _inside_root(material_set.root, path):
            raise ValueError(f"Texture is a symbolic link or outside the selected directory: {path}")
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Texture is not a regular file: {path}")
        if info.st_size > MAX_TEXTURE_BYTES:
            raise ValueError(f"Texture is larger than {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB: {path}")
        total_size += info.st_size
        if total_size > MAX_MATERIAL_SET_IMPORT_BYTES:
            raise ValueError(f"Selected textures exceed the {MAX_MATERIAL_SET_IMPORT_BYTES // (1024 * 1024)} MiB import limit")

    prepared = set()
    for map_name, path in resolved.items():
        role = _role_for_map(map_name)
        cache_key = (path, role)
        if cache_key in prepared:
            continue
        with open(path, "rb") as handle:
            signature = handle.read(12)
        mime = gputex.mime_of(signature)
        if mime not in (gputex.MIME_DDS, gputex.MIME_KTX2):
            with open(path, "rb") as handle:
                raw = handle.read(MAX_TEXTURE_BYTES + 1)
            if len(raw) > MAX_TEXTURE_BYTES:
                raise ValueError(f"Texture is larger than {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB: {path}")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format not in _SUPPORTED_IMAGE_FORMATS:
                            raise ValueError(f"Unsupported texture format {image.format!r}: {path}")
                        width, height = image.size
                        if width <= 0 or height <= 0 or width * height > MAX_TEXTURE_PIXELS:
                            raise ValueError(f"Texture exceeds the {MAX_TEXTURE_PIXELS:,}-pixel limit: {path}")
                        image.verify()
            except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
                raise ValueError(f"Cannot validate texture {path}: {error}") from error
        prepare_adm_texture(path, role)
        prepared.add(cache_key)


def apply_material_sets(
    material: TerrainMaterial,
    scan: MaterialSetScan,
    selected_names: set[str],
    choices: dict[tuple[str, str], str] | None = None,
    update_existing: bool = False,
) -> dict[str, int]:
    """Apply selected split maps while preserving absent maps and unselected surfaces."""
    choices = choices or {}
    by_name = {item.name: item for item in scan.sets}
    if not selected_names or not selected_names.issubset(by_name):
        raise ValueError("Select at least one discovered material set")
    resolved_sets = [(by_name[name], resolve_material_set(by_name[name], choices))
                     for name in sorted(selected_names, key=lambda value: (value.casefold(), value))]
    existing: dict[str, list[Surface]] = {}
    for surface in material.surfaces:
        existing.setdefault(surface.name.casefold(), []).append(surface)
    to_add = [item for item, _resolved in resolved_sets
              if item.name.casefold() not in existing]
    if len(material.surfaces) + len(to_add) > MAX_SURFACES:
        raise ValueError(f"The library can hold at most {MAX_SURFACES} surfaces")

    added = updated = skipped = 0
    for item, resolved in resolved_sets:
        matches = existing.get(item.name.casefold(), [])
        if len(matches) > 1:
            raise ValueError(f"More than one existing surface matches '{item.name}'")
        if matches and not update_existing:
            skipped += 1
            continue
        surface = matches[0] if matches else Surface(item.name)
        if not matches:
            material.surfaces.append(surface)
            existing.setdefault(item.name.casefold(), []).append(surface)
            added += 1
        else:
            updated += 1
        for map_name, path in resolved.items():
            if map_name == "albedo":
                surface.albedo = path
            elif map_name == "normal":
                surface.normal = path
            elif map_name == "emission":
                surface.emission = path
            else:
                getattr(surface, f"{map_name}_map").path = path
    return {"added": added, "updated": updated, "skipped": skipped}
