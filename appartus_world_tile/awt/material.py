"""The terrain material of a world: a surface library, biomes that choose surfaces, and paint.

* :class:`Surface` is one texture set (albedo, metallic, roughness, normal) with its tiling.
* :class:`Biome` uses one to four surfaces, each optionally limited to a height or slope band.
  Biomes are placed by their own height/slope rule (``auto``) and/or painted on the map.
* The build turns biomes into per-vertex surface weights (see :mod:`awt.texturing`); the
  exporter groups triangles into primitives of at most four surfaces and writes
  ``adm.terrain.four_layer@2.0.0`` materials blended by ``COLOR_1``.

Neighbouring biomes should share at least one surface: the transition between them then
passes through the shared surfaces and no texture appears or disappears abruptly.

Texture paths are absolute in memory; projects store them relative to the project file.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import os
import struct
import threading
from dataclasses import asdict, dataclass, field

import numpy as np

from .roads import Road

SHADER_ID = "adm.terrain.four_layer"
SHADER_VERSION = "2.0.0"
CHANNELS = "RGBA"
SCALAR_GPU_ENCODINGS = ("R8", "R16", "BC4")
GPU_ENCODINGS = ("AUTO", "BC7", "RGBA8", "BC5", *SCALAR_GPU_ENCODINGS)
TEXTURE_MAPS = ("albedo", "metallic", "roughness", "normal", "ao", "height", "emission")
MAX_SURFACES = 32
MAX_BIOMES = 16
SURFACES_PER_BIOME = 4
PAINT_AUTO = 255  # paint value meaning "use the automatic rules"
PAINT_MAX_SIDE = 4096
MAX_PHYSICAL_MATERIALS = 255
PHYSICAL_SURFACE_PROFILES = (
    "adm.phys.wood.v1", "adm.phys.metal.v1", "adm.phys.stone.v1",
    "adm.phys.ground.v1", "adm.phys.glass.v1",
)
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.bmp *.dds *.ktx2 *.webp);;All files (*)"
TERRAIN_SHADER_FIELDS = frozenset({
    "version", "height_blend_enabled", "height_blend_transition", "height_blend_strength",
    "parallax_mode", "parallax_min_steps", "parallax_max_steps",
})


@dataclass
class MapSlot:
    """A metallic or roughness texture: which channel to read and whether to invert it."""

    path: str = ""
    channel: int = 0  # 0..3 = R, G, B, A
    invert: bool = False


@dataclass
class MacroColorSettings:
    """A shared Macro Color overlay applied to each local terrain layer."""

    path: str = ""
    projection: str = "LOCAL_UV"
    blend_mode: str = "MULTIPLY"
    strength: float = 1.0
    layer_influence: list[float] = field(default_factory=lambda: [1.0] * 4)
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0])
    offset: list[float] = field(default_factory=lambda: [0.0, 0.0])
    origin: list[float] = field(default_factory=lambda: [0.0, 0.0])

    def to_dict(self, base_dir: str | None) -> dict:
        path = self.path
        if path and base_dir is not None:
            try:
                path = os.path.relpath(path, base_dir).replace("\\", "/")
            except ValueError:
                pass
        return {
            "path": path,
            "projection": self.projection,
            "blend_mode": self.blend_mode,
            "strength": self.strength,
            "layer_influence": list(self.layer_influence),
            "scale": list(self.scale),
            "offset": list(self.offset),
            "origin": list(self.origin),
        }

    @classmethod
    def from_dict(cls, data: dict, base_dir: str | None) -> "MacroColorSettings":
        if not isinstance(data, dict):
            raise ValueError("Macro Color settings must be an object")
        path = data.get("path", "")
        if not isinstance(path, str):
            raise ValueError("Macro Color path must be a string")
        if path and base_dir is not None and not os.path.isabs(path):
            path = os.path.normpath(os.path.join(base_dir, path))
        result = cls(
            path=path,
            projection=data.get("projection", "LOCAL_UV"),
            blend_mode=data.get("blend_mode", "MULTIPLY"),
            strength=data.get("strength", 1.0),
            layer_influence=data.get("layer_influence", [1.0] * 4),
            scale=data.get("scale", [1.0, 1.0]),
            offset=data.get("offset", [0.0, 0.0]),
            origin=data.get("origin", [0.0, 0.0]),
        )
        result.validate_settings()
        return result

    def validate_settings(self) -> None:
        if not isinstance(self.path, str):
            raise ValueError("Macro Color path must be a string")
        if self.projection not in ("LOCAL_UV", "SHARED_WORLD_XZ"):
            raise ValueError("Macro Color projection must be LOCAL_UV or SHARED_WORLD_XZ")
        if self.blend_mode not in ("MULTIPLY", "TINT", "LERP"):
            raise ValueError("Macro Color blend mode must be MULTIPLY, TINT or LERP")
        vectors = (
            (self.layer_influence, 4, 0.0, 1.0, "layer influence"),
            (self.scale, 2, -1_000_000.0, 1_000_000.0, "scale"),
            (self.offset, 2, -1_000_000_000.0, 1_000_000_000.0, "offset"),
            (self.origin, 2, -1_000_000_000.0, 1_000_000_000.0, "origin"),
        )
        for values, length, low, high, label in vectors:
            if (not isinstance(values, (list, tuple)) or len(values) != length
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) or not low <= value <= high for value in values)):
                raise ValueError(f"Macro Color {label} must contain {length} finite values in range")
        if all(value == 0.0 for value in self.scale):
            raise ValueError("Macro Color scale must not be [0, 0]")
        if isinstance(self.strength, bool) or not isinstance(self.strength, (int, float)) \
                or not math.isfinite(self.strength) or not 0.0 <= self.strength <= 1.0:
            raise ValueError("Macro Color strength must be finite and in 0..1")

    def validate(self) -> None:
        self.validate_settings()
        if self.path:
            if not os.path.isfile(self.path):
                raise ValueError(f"Macro Color texture not found: {self.path}")
            from PIL import Image

            with open(self.path, "rb") as handle:
                signature = handle.read(12)
            if signature[:4] == b"DDS " or signature == b"\xabKTX 20\xbb\r\n\x1a\n":
                from .adm_export import _core

                _core()
                from adm_blender.core import gputex

                with open(self.path, "rb") as handle:
                    source = handle.read(MAX_TEXTURE_BYTES + 1)
                try:
                    info = gputex.parse(source, gputex.mime_of(source), strict=True)
                except gputex.GpuTextureError:
                    info = None
                if info is not None and not info["srgb"]:
                    raise ValueError("Macro Color GPU textures must use an sRGB format")
            prepared = prepare_texture(self.path)
            with Image.open(io.BytesIO(prepared.data)) as image:
                image.load()
                if len(image.getbands()) < 3:
                    raise ValueError("Macro Color texture must provide at least three color channels")


@dataclass
class Surface:
    name: str
    color: list[int] = field(default_factory=lambda: [255, 255, 255])  # sRGB tint, multiplies albedo
    repeat_m: float = 4.0  # size of one texture repeat on the ground
    albedo: str = ""
    metallic: float = 0.0
    metallic_map: MapSlot = field(default_factory=MapSlot)
    roughness: float = 0.8
    roughness_map: MapSlot = field(default_factory=MapSlot)
    normal: str = ""
    ao_map: MapSlot = field(default_factory=MapSlot)
    ao_strength: float = 1.0
    height_map: MapSlot = field(default_factory=MapSlot)
    height_scale: float = 1.0
    height_bias: float = 0.0
    parallax_scale: float = 0.0
    emission: str = ""
    gpu_encodings: dict[str, str] = field(default_factory=dict)
    id: str = ""
    physical_material_id: str = ""

    def __post_init__(self):
        if not self.id:
            digest = hashlib.sha256(
                ("appartus-world-tile\0surface\0" + self.name).encode("utf-8")).hexdigest()[:24]
            self.id = "awt.surface." + digest

    def textures(self) -> list[str]:
        return [p for p in (self.albedo, self.metallic_map.path, self.roughness_map.path, self.normal,
                            self.ao_map.path, self.height_map.path, self.emission) if p]


@dataclass
class Band:
    """A value range with soft edges; ``None`` leaves that side open.

    The factor rises from 0 to 1 across ``min ± fade/2`` and falls back across ``max ± fade/2``.
    """

    min: float | None = None
    max: float | None = None
    fade: float = 0.0

    def is_open(self) -> bool:
        return self.min is None and self.max is None


@dataclass
class BiomeSurface:
    surface: str
    height: Band = field(default_factory=Band)  # metres
    slope: Band = field(default_factory=Band)  # degrees
    strength: float = 1.0  # share taken where the bands allow it


@dataclass
class Biome:
    """Surfaces are listed base first; each later surface covers the earlier ones where its bands allow."""

    name: str
    color: list[int] = field(default_factory=lambda: [128, 128, 128])  # map preview colour (sRGB)
    surfaces: list[BiomeSurface] = field(default_factory=list)
    auto: bool = True  # placed by its height/slope rule; otherwise only where painted
    height: Band = field(default_factory=Band)
    slope: Band = field(default_factory=Band)
    noise: float = 0.0  # spatial variation between the biome's surfaces, 0..1

    def surface_names(self) -> list[str]:
        return [entry.surface for entry in self.surfaces]


@dataclass
class PhysicalMaterial:
    """A stable physical-surface reference, independent of visual terrain surfaces."""

    name: str
    friction: float
    restitution: float
    profile: str = ""
    id: str = ""

    def __post_init__(self):
        if not self.id:
            digest = hashlib.sha256(
                ("appartus-world-tile\0physical\0" + self.name).encode("utf-8")).hexdigest()[:24]
            self.id = "awt.physical." + digest


def _surface(name, color, roughness, repeat_m=4.0) -> Surface:
    return Surface(name=name, color=list(color), roughness=roughness, repeat_m=repeat_m)


def default_surfaces() -> list[Surface]:
    return [
        _surface("grass", (86, 122, 52), 0.9),
        _surface("soil", (110, 86, 60), 0.92),
        _surface("gravel", (128, 120, 110), 0.85, 3.0),
        _surface("sand", (194, 178, 128), 0.85),
        _surface("mud", (92, 74, 56), 0.55),
        _surface("algae", (62, 92, 58), 0.7),
        _surface("forest_floor", (72, 64, 40), 0.95),
        _surface("moss", (70, 100, 50), 0.9),
        _surface("rock", (120, 116, 110), 0.8, 8.0),
        _surface("scree", (140, 134, 126), 0.85, 6.0),
        _surface("snow", (236, 240, 246), 0.55, 8.0),
    ]


def default_biomes(water_m: float = 0.0, shore_m: float = 2.0, snow_start_m: float = 400.0,
                   snow_full_m: float = 450.0, depth_m: float = 1.0) -> list[Biome]:
    """Six biomes in priority order (later wins); neighbours share surfaces."""
    snow_mid = (snow_start_m + snow_full_m) / 2.0
    snow_fade = max(1.0, snow_full_m - snow_start_m)
    return [
        Biome("lowland", [104, 140, 64], [
            BiomeSurface("grass"),
            BiomeSurface("soil", slope=Band(12.0, None, 8.0)),
            BiomeSurface("gravel", slope=Band(26.0, None, 6.0)),
        ]),
        Biome("forest", [44, 84, 40], [
            BiomeSurface("forest_floor"),
            BiomeSurface("grass", strength=0.25),
            BiomeSurface("moss", strength=0.35),
            BiomeSurface("soil", slope=Band(15.0, None, 8.0)),
        ], auto=False),
        Biome("shore", [214, 196, 140], [
            BiomeSurface("sand"),
            BiomeSurface("grass", height=Band(water_m + 0.6 * shore_m, None, 0.4 * shore_m)),
            BiomeSurface("mud", height=Band(None, water_m + 0.2 * shore_m, 0.2 * shore_m)),
            BiomeSurface("gravel", slope=Band(18.0, None, 8.0)),
        ], height=Band(None, water_m + shore_m, 0.5 * shore_m)),
        Biome("water", [50, 100, 160], [
            BiomeSurface("sand"),
            BiomeSurface("mud", height=Band(None, water_m - depth_m, depth_m)),
            BiomeSurface("algae", height=Band(None, water_m - 3.0 * depth_m, 2.0 * depth_m), strength=0.6),
            BiomeSurface("gravel", slope=Band(20.0, None, 8.0)),
        ], height=Band(None, water_m, 0.5 * shore_m)),
        Biome("mountains", [200, 200, 210], [
            BiomeSurface("gravel"),
            BiomeSurface("scree", slope=Band(18.0, None, 10.0)),
            BiomeSurface("rock", slope=Band(32.0, None, 8.0)),
            BiomeSurface("snow", height=Band(snow_mid, None, snow_fade), slope=Band(None, 45.0, 10.0)),
        ], height=Band(snow_start_m, None, snow_fade)),
        Biome("rocky", [130, 120, 112], [
            BiomeSurface("rock"),
            BiomeSurface("scree", slope=Band(None, 46.0, 8.0)),
            BiomeSurface("gravel", slope=Band(None, 42.0, 6.0)),
            BiomeSurface("soil", slope=Band(None, 40.0, 4.0), strength=0.4),
        ], slope=Band(38.0, None, 10.0)),
    ]


def _band_dict(band: Band) -> dict:
    return {"min": band.min, "max": band.max, "fade": band.fade}


def _band_from(data) -> Band:
    data = data if isinstance(data, dict) else {}

    def number(value):
        return None if value is None else float(value)

    return Band(number(data.get("min")), number(data.get("max")), float(data.get("fade", 0.0)))


def _color(value, fallback: list[int]) -> list[int]:
    if isinstance(value, list) and len(value) == 3:
        return [max(0, min(255, int(c))) for c in value]
    return list(fallback)


@dataclass
class TerrainMaterial:
    surfaces: list[Surface] = field(default_factory=default_surfaces)
    biomes: list[Biome] = field(default_factory=default_biomes)
    slope_radius_m: float = 2.0  # slope is measured over this distance
    paint_softness_m: float = 8.0  # painted biome borders fade over about this distance
    double_sided: bool = False
    # Biome index per paint cell (PAINT_AUTO = automatic); row 0 = north. One cell covers
    # ``paint_cell`` x ``paint_cell`` heightmap samples.
    paint: np.ndarray | None = field(default=None, repr=False, compare=False)
    paint_cell: int = 1
    surface_paint: np.ndarray | None = field(default=None, repr=False, compare=False)
    surface_paint_cell: int = 1
    physical_materials: list[PhysicalMaterial] = field(default_factory=list)
    physical_paint: np.ndarray | None = field(default=None, repr=False, compare=False)
    physical_paint_cell: int = 1
    roads: list[Road] = field(default_factory=list)
    height_blend_enabled: bool = False
    height_blend_transition: float = 0.2
    height_blend_strength: float = 1.0
    parallax_mode: str = "NONE"
    parallax_min_steps: int = 8
    parallax_max_steps: int = 32
    terrain_shader_version: str = SHADER_VERSION
    unknown_terrain_shader_settings: dict = field(default_factory=dict, repr=False)
    external_control_map_path: str = ""
    external_control_map_surface_ids: list[str] = field(default_factory=list)
    macro_color: MacroColorSettings = field(default_factory=MacroColorSettings)

    # ------------------------------------------------------------ lookups
    def surface_names(self) -> list[str]:
        return [surface.name for surface in self.surfaces]

    def surface(self, name: str) -> Surface:
        for surface in self.surfaces:
            if surface.name == name:
                return surface
        raise KeyError(name)

    def uv_scale(self, tile_size_m: float, surfaces: list[Surface] | None = None) -> list[float]:
        """Integer repeats per tile, so textures continue across tile borders."""
        chosen = self.surfaces if surfaces is None else surfaces
        return [float(min(1000, max(1, round(tile_size_m / s.repeat_m)))) if s.repeat_m > 0 else 1.0
                for s in chosen]

    def textures(self) -> list[str]:
        seen: list[str] = []
        for surface in self.surfaces:
            for path in surface.textures():
                if path not in seen:
                    seen.append(path)
        if self.macro_color.path and self.macro_color.path not in seen:
            seen.append(self.macro_color.path)
        return seen

    # --------------------------------------------------------- editing
    def rename_surface(self, old: str, new: str) -> None:
        if old == new:
            return
        if new in self.surface_names():
            raise ValueError(f"A surface named '{new}' already exists")
        self.surface(old).name = new
        for biome in self.biomes:
            for entry in biome.surfaces:
                if entry.surface == old:
                    entry.surface = new
        for road in self.roads:
            if road.surface == old:
                road.surface = new

    def remove_surface(self, name: str) -> None:
        if len(self.surfaces) <= 1:
            raise ValueError("The library needs at least one surface")
        if any(road.surface == name for road in self.roads):
            raise ValueError(f"Surface '{name}' is used by a road")
        index = self.surface_names().index(name)
        self.surfaces.remove(self.surface(name))
        if self.surface_paint is not None:
            paint = self.surface_paint
            hit = paint == index
            paint[(paint > index) & (paint != PAINT_AUTO)] -= 1
            paint[hit] = PAINT_AUTO
        fallback = self.surfaces[0].name
        for biome in self.biomes:
            biome.surfaces = [e for e in biome.surfaces if e.surface != name] or [BiomeSurface(fallback)]

    def remove_biome(self, index: int) -> None:
        if len(self.biomes) <= 1:
            raise ValueError("At least one biome is needed")
        del self.biomes[index]
        if self.paint is not None:
            paint = self.paint
            hit = paint == index
            paint[(paint > index) & (paint != PAINT_AUTO)] -= 1
            paint[hit] = PAINT_AUTO

    def move_biome(self, index: int, target: int) -> None:
        """Reorder biomes (the order is their priority) and keep painted cells on the same biome."""
        order = list(range(len(self.biomes)))
        order.insert(target, order.pop(index))
        self.biomes = [self.biomes[i] for i in order]
        if self.paint is not None:
            lut = np.full(256, PAINT_AUTO, np.uint8)
            for new, old in enumerate(order):
                lut[old] = new
            self.paint = lut[self.paint]

    def ensure_paint(self, width: int, height: int) -> bool:
        """Allocate the paint map for a ``width`` x ``height`` heightmap; True if it was (re)created."""
        cell = max(1, math.ceil(max(width, height) / PAINT_MAX_SIDE))
        shape = (max(1, math.ceil(height / cell)), max(1, math.ceil(width / cell)))
        if self.paint is not None and self.paint.shape == shape and self.paint_cell == cell:
            return False
        self.paint = np.full(shape, PAINT_AUTO, np.uint8)
        self.paint_cell = cell
        return True

    def has_paint(self) -> bool:
        return self.paint is not None and bool(np.any(self.paint != PAINT_AUTO))

    def ensure_surface_paint(self, width: int, height: int) -> bool:
        cell = max(1, math.ceil(max(width, height) / PAINT_MAX_SIDE))
        shape = (max(1, math.ceil(height / cell)), max(1, math.ceil(width / cell)))
        if self.surface_paint is not None and self.surface_paint.shape == shape and self.surface_paint_cell == cell:
            return False
        self.surface_paint = np.full(shape, PAINT_AUTO, np.uint8)
        self.surface_paint_cell = cell
        return True

    def has_surface_paint(self) -> bool:
        return self.surface_paint is not None and bool(np.any(self.surface_paint != PAINT_AUTO))

    def ensure_physical_paint(self, width: int, height: int) -> bool:
        cell = max(1, math.ceil(max(width, height) / PAINT_MAX_SIDE))
        shape = (max(1, math.ceil(height / cell)), max(1, math.ceil(width / cell)))
        if self.physical_paint is not None and self.physical_paint.shape == shape \
                and self.physical_paint_cell == cell:
            return False
        self.physical_paint = np.full(shape, PAINT_AUTO, np.uint8)
        self.physical_paint_cell = cell
        return True

    def has_physical_paint(self) -> bool:
        return self.physical_paint is not None and bool(np.any(self.physical_paint != PAINT_AUTO))

    def remove_physical_material(self, index: int) -> None:
        if not 0 <= index < len(self.physical_materials):
            raise IndexError(index)
        removed_id = self.physical_materials[index].id
        del self.physical_materials[index]
        if self.physical_paint is not None:
            paint = self.physical_paint
            hit = paint == index
            paint[(paint > index) & (paint != PAINT_AUTO)] -= 1
            paint[hit] = PAINT_AUTO
        for surface in self.surfaces:
            if surface.physical_material_id == removed_id:
                surface.physical_material_id = ""

    @staticmethod
    def fitted_levels(heights_m: np.ndarray) -> dict:
        """Water, shore, snow and depth levels (``default_biomes`` arguments) for a height distribution."""
        lo = float(heights_m.min())
        span = max(float(heights_m.max()) - lo, 1e-6)
        p85, p95 = (float(v) for v in np.percentile(heights_m, (85, 95)))
        return {"water_m": round(lo + 0.02 * span, 2), "shore_m": round(max(0.5, 0.01 * span), 2),
                "snow_start_m": round(p85, 2), "snow_full_m": round(max(p95, p85 + 0.01 * span), 2),
                "depth_m": round(max(0.5, 0.005 * span), 2)}

    def fit_to_heights(self, heights_m: np.ndarray) -> None:
        """Re-place the height bands of the default biomes for a heightmap (preview array in metres)."""
        self.place_levels(**self.fitted_levels(heights_m))

    def place_levels(self, **levels) -> None:
        """Set the height bands of biomes named like the defaults from ``default_biomes`` levels."""
        by_name = {biome.name: biome for biome in default_biomes(**levels)}
        for biome in self.biomes:
            template = by_name.get(biome.name)
            if template is None:
                continue
            biome.height = template.height
            entries = {entry.surface: entry for entry in template.surfaces}
            for entry in biome.surfaces:
                if entry.surface in entries:
                    entry.height = entries[entry.surface].height

    # ------------------------------------------------------- validation
    def validate_rules(self) -> None:
        """Everything the build needs; does not touch texture files."""
        names = self.surface_names()
        if not names:
            raise ValueError("The surface library is empty")
        if len(names) > MAX_SURFACES:
            raise ValueError(f"At most {MAX_SURFACES} surfaces are supported")
        if len(set(names)) != len(names) or not all(n.strip() for n in names):
            raise ValueError("Surface names must be unique and not empty")
        surface_ids = [surface.id for surface in self.surfaces]
        if (not all(isinstance(ident, str) and ident.strip() for ident in surface_ids)
                or len(set(surface_ids)) != len(surface_ids)):
            raise ValueError("Surface IDs must be unique and not empty")
        if self.macro_color.path and len(surface_ids) < 4:
            raise ValueError("Macro Color requires at least four surfaces to provide four stable local IDs")
        for ident in surface_ids:
            try:
                encoded_length = len(ident.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError("Surface IDs must be valid UTF-8") from exc
            if encoded_length > 128:
                raise ValueError("Surface IDs must not exceed 128 UTF-8 bytes")
        if not 1 <= len(self.biomes) <= MAX_BIOMES:
            raise ValueError(f"Use between 1 and {MAX_BIOMES} biomes")
        for road in self.roads:
            if road.surface not in names:
                raise ValueError(f"Road uses unknown surface '{road.surface}'")
        if not (self.slope_radius_m >= 0 and self.paint_softness_m >= 0):
            raise ValueError("Slope radius and paint softness must not be negative")
        for biome in self.biomes:
            if not 0.0 <= biome.noise <= 1.0:
                raise ValueError(f"Biome '{biome.name}': noise must be 0..1")
            used = biome.surface_names()
            if not 1 <= len(used) <= SURFACES_PER_BIOME:
                raise ValueError(f"Biome '{biome.name}' needs one to four surfaces")
            if len(set(used)) != len(used):
                raise ValueError(f"Biome '{biome.name}' uses a surface twice")
            for name in used:
                if name not in names:
                    raise ValueError(f"Biome '{biome.name}' uses the unknown surface '{name}'")
            bands = [biome.height, biome.slope]
            for entry in biome.surfaces:
                bands += [entry.height, entry.slope]
                if not 0.0 <= entry.strength <= 1.0:
                    raise ValueError(f"Biome '{biome.name}': strength must be 0..1")
            for band in bands:
                if band.fade < 0 or (band.min is not None and band.max is not None and band.max < band.min):
                    raise ValueError(f"Biome '{biome.name}': a band ends below its start or fades negatively")
        self.validate_physical_materials()

    def validate(self) -> None:
        self.validate_rules()
        self.macro_color.validate()
        for surface in self.surfaces:
            if (not isinstance(surface.gpu_encodings, dict) or
                    any(name not in TEXTURE_MAPS or value not in GPU_ENCODINGS
                        or (value == "BC5" and name != "normal")
                        or (value in SCALAR_GPU_ENCODINGS and name not in ("metallic", "roughness", "ao", "height"))
                        for name, value in surface.gpu_encodings.items())):
                raise ValueError(f"Surface '{surface.name}': unsupported per-map GPU encoding")
            if not surface.repeat_m > 0:
                raise ValueError(f"Surface '{surface.name}': texture repeat must be positive")
            for value in (surface.metallic, surface.roughness):
                if not 0.0 <= value <= 1.0:
                    raise ValueError(f"Surface '{surface.name}': metallic and roughness must be 0..1")
            for slot in (surface.metallic_map, surface.roughness_map, surface.ao_map, surface.height_map):
                if slot.channel not in (0, 1, 2, 3):
                    raise ValueError(f"Surface '{surface.name}': map channel must be R, G, B or A")
            for value, label in ((surface.ao_strength, "AO strength"),
                                 (surface.height_scale, "height scale"),
                                 (surface.height_bias, "height bias"),
                                 (surface.parallax_scale, "parallax scale")):
                if not math.isfinite(value):
                    raise ValueError(f"Surface '{surface.name}': {label} must be finite")
            if not 0.0 <= surface.ao_strength <= 1.0:
                raise ValueError(f"Surface '{surface.name}': AO strength must be 0..1")
            if not 0.0 <= surface.height_scale <= 1000.0:
                raise ValueError(f"Surface '{surface.name}': height scale must be 0..1000")
            if not -1.0 <= surface.height_bias <= 1.0:
                raise ValueError(f"Surface '{surface.name}': height bias must be -1..1")
            if not 0.0 <= surface.parallax_scale <= 1.0:
                raise ValueError(f"Surface '{surface.name}': parallax scale must be 0..1")
            for path in surface.textures():
                if not os.path.isfile(path):
                    raise ValueError(f"Surface '{surface.name}': texture not found: {path}")
        if not (math.isfinite(self.height_blend_transition)
                and 0.001 <= self.height_blend_transition <= 1.0):
            raise ValueError("Height blend transition must be 0.001..1")
        if not (math.isfinite(self.height_blend_strength) and 0.0 <= self.height_blend_strength <= 1.0):
            raise ValueError("Height blend strength must be 0..1")
        if self.parallax_mode not in ("NONE", "PARALLAX", "PARALLAX_OCCLUSION"):
            raise ValueError("Parallax mode must be NONE, PARALLAX or PARALLAX_OCCLUSION")
        if not (isinstance(self.parallax_min_steps, int) and isinstance(self.parallax_max_steps, int)
                and 1 <= self.parallax_min_steps <= self.parallax_max_steps <= 256):
            raise ValueError("POM steps must satisfy 1 <= minimum <= maximum <= 256")
        if self.terrain_shader_version not in ("2.0.0", "2.1.0"):
            raise ValueError("Unsupported terrain shader version")
        if self.unknown_terrain_shader_settings:
            raise ValueError("Unsupported terrain shader settings are retained in the project but cannot be used "
                             "for validation, build or export: "
                             + ", ".join(sorted(self.unknown_terrain_shader_settings)))

    # --------------------------------------------------------- digests
    def rules_digest(self) -> str:
        """Changes whenever the per-vertex weights of a build would change."""
        data = {
            "surfaces": self.surface_names(),
            "biomes": [_biome_dict(biome) for biome in self.biomes],
            "slope_radius_m": self.slope_radius_m,
            "paint_softness_m": self.paint_softness_m,
            "paint": None if not self.has_paint() else
            [self.paint_cell, list(self.paint.shape), hashlib.sha256(self.paint.tobytes()).hexdigest()],
        }
        if self.has_surface_paint():
            data["surface_paint"] = [self.surface_paint_cell, list(self.surface_paint.shape),
                                     hashlib.sha256(self.surface_paint.tobytes()).hexdigest()]
        if self.roads:
            data["roads"] = [road.to_dict() for road in self.roads]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]

    def fingerprint(self, tile_size_m: float, surfaces: list[Surface] | None = None,
                    texture_hashes: dict[str, str] | None = None) -> str:
        """Changes whenever the look of exported tiles changes, including texture files."""
        selected = self.surfaces if surfaces is None else surfaces
        paths = dict.fromkeys(path for surface in selected for path in surface.textures())
        if self.macro_color.path:
            paths.setdefault(self.macro_color.path, None)
        hashes = texture_hashes if texture_hashes is not None else {}
        for path in paths:
            if path not in hashes:
                digest = hashlib.sha256()
                size = 0
                with open(path, "rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_TEXTURE_BYTES:
                            raise ValueError(f"Texture file is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
                        digest.update(chunk)
                hashes[path] = digest.hexdigest()
        surface_data = [_surface_dict(s, None) for s in selected]
        for item in surface_data:
            item.pop("physical_material_id", None)
        data = {"surfaces": surface_data,
                "uv_scale": self.uv_scale(tile_size_m, selected), "double_sided": self.double_sided,
                "files": {path: hashes[path] for path in paths}}
        if self.macro_color.path:
            data["macro_color"] = self.macro_color.to_dict(None)
        if surfaces is not None or self.has_advanced_shader_features():
            data["terrain_shader"] = {
                    "version": self.terrain_shader_version,
                    "height_blend_enabled": self.height_blend_enabled,
                    "height_blend_transition": self.height_blend_transition,
                    "height_blend_strength": self.height_blend_strength,
                    "parallax_mode": self.parallax_mode,
                    "parallax_min_steps": self.parallax_min_steps,
                    "parallax_max_steps": self.parallax_max_steps,
                }
            data["terrain_shader"].update(copy.deepcopy(self.unknown_terrain_shader_settings))
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]

    # ------------------------------------------------------- persistence
    def to_dict(self, base_dir: str | None) -> dict:
        data = {
            "surfaces": [_surface_dict(s, base_dir) for s in self.surfaces],
            "biomes": [_biome_dict(b) for b in self.biomes],
            "slope_radius_m": self.slope_radius_m,
            "paint_softness_m": self.paint_softness_m,
            "double_sided": self.double_sided,
        }
        if self.has_advanced_shader_features():
            data["terrain_shader"] = {
                "version": self.terrain_shader_version,
                "height_blend_enabled": self.height_blend_enabled,
                "height_blend_transition": self.height_blend_transition,
                "height_blend_strength": self.height_blend_strength,
                "parallax_mode": self.parallax_mode,
                "parallax_min_steps": self.parallax_min_steps,
                "parallax_max_steps": self.parallax_max_steps,
            }
            data["terrain_shader"].update(copy.deepcopy(self.unknown_terrain_shader_settings))
        if self.has_paint():
            from PIL import Image

            out = io.BytesIO()
            Image.fromarray(self.paint).save(out, "PNG", optimize=True)
            data["paint"] = {"cell": self.paint_cell, "png": base64.b64encode(out.getvalue()).decode("ascii")}
        if self.has_surface_paint():
            from PIL import Image

            out = io.BytesIO()
            Image.fromarray(self.surface_paint).save(out, "PNG", optimize=True)
            data["surface_paint"] = {
                "cell": self.surface_paint_cell, "png": base64.b64encode(out.getvalue()).decode("ascii")}
        if self.physical_materials:
            data["physical_materials"] = [asdict(item) for item in self.physical_materials]
        if self.has_physical_paint():
            from PIL import Image

            out = io.BytesIO()
            Image.fromarray(self.physical_paint).save(out, "PNG", optimize=True)
            data["physical_paint"] = {
                "cell": self.physical_paint_cell, "png": base64.b64encode(out.getvalue()).decode("ascii")}
        if self.roads:
            data["roads"] = [road.to_dict() for road in self.roads]
        if self.external_control_map_path or self.external_control_map_surface_ids:
            path = self.external_control_map_path
            if path and base_dir is not None:
                try:
                    path = os.path.relpath(path, base_dir).replace("\\", "/")
                except ValueError:
                    pass
            data["external_control_map"] = {
                "path": path,
                "surface_ids": list(self.external_control_map_surface_ids),
            }
        if self.macro_color != MacroColorSettings():
            data["macro_color"] = self.macro_color.to_dict(base_dir)
        return data

    @classmethod
    def from_dict(cls, data: dict, base_dir: str | None) -> "TerrainMaterial":
        def absolute(path) -> str:
            if not isinstance(path, str) or not path:
                return ""
            return os.path.normpath(path if os.path.isabs(path) or base_dir is None
                                    else os.path.join(base_dir, path))

        def slot(value) -> MapSlot:
            value = value if isinstance(value, dict) else {}
            return MapSlot(path=absolute(value.get("path")), channel=int(value.get("channel", 0)),
                           invert=bool(value.get("invert", False)))

        material = cls()
        raw_macro_color = data.get("macro_color")
        if raw_macro_color is not None:
            material.macro_color = MacroColorSettings.from_dict(raw_macro_color, base_dir)
        raw_control_map = data.get("external_control_map")
        if raw_control_map is not None:
            if not isinstance(raw_control_map, dict):
                raise ValueError("External Control Map settings must be an object")
            path = raw_control_map.get("path", "")
            surface_ids = raw_control_map.get("surface_ids", [])
            if not isinstance(path, str) or not isinstance(surface_ids, list) or len(surface_ids) not in (0, 4):
                raise ValueError("External Control Map requires a path and zero or four surface IDs")
            if not all(isinstance(ident, str) for ident in surface_ids):
                raise ValueError("External Control Map surface IDs must be strings")
            material.external_control_map_path = absolute(path)
            material.external_control_map_surface_ids = list(surface_ids)
        raw_surfaces = [s for s in data.get("surfaces", []) if isinstance(s, dict) and s.get("name")]
        if raw_surfaces:
            material.surfaces = []
            for raw in raw_surfaces:
                surface = Surface(name=str(raw["name"]), id=raw.get("id", ""))
                surface.color = _color(raw.get("color"), surface.color)
                surface.repeat_m = float(raw.get("repeat_m", surface.repeat_m))
                surface.albedo = absolute(raw.get("albedo"))
                surface.metallic = float(raw.get("metallic", surface.metallic))
                surface.metallic_map = slot(raw.get("metallic_map"))
                surface.roughness = float(raw.get("roughness", surface.roughness))
                surface.roughness_map = slot(raw.get("roughness_map"))
                surface.normal = absolute(raw.get("normal"))
                surface.ao_map = slot(raw.get("ao_map"))
                surface.ao_strength = float(raw.get("ao_strength", 1.0))
                surface.height_map = slot(raw.get("height_map"))
                surface.height_scale = float(raw.get("height_scale", 1.0))
                surface.height_bias = float(raw.get("height_bias", 0.0))
                surface.parallax_scale = float(raw.get("parallax_scale", 0.0))
                surface.emission = absolute(raw.get("emission"))
                encodings = raw.get("gpu_encodings", {})
                if not isinstance(encodings, dict):
                    raise ValueError(f"Surface '{surface.name}': per-map GPU encodings must be an object")
                surface.gpu_encodings = copy.deepcopy(encodings)
                physical_material_id = raw.get("physical_material_id", "")
                if not isinstance(physical_material_id, str):
                    raise ValueError(f"Surface '{surface.name}': physical material ID must be a string")
                surface.physical_material_id = physical_material_id
                material.surfaces.append(surface)
        raw_biomes = [b for b in data.get("biomes", []) if isinstance(b, dict) and b.get("name")]
        if raw_biomes:
            material.biomes = []
            for raw in raw_biomes:
                entries = [BiomeSurface(str(e["surface"]), _band_from(e.get("height")), _band_from(e.get("slope")),
                                        float(e.get("strength", 1.0)))
                           for e in raw.get("surfaces", []) if isinstance(e, dict) and e.get("surface")]
                noise = float(raw.get("noise", 0.0))
                if not 0.0 <= noise <= 1.0:
                    raise ValueError(f"Biome '{raw['name']}': noise must be 0..1")
                material.biomes.append(Biome(str(raw["name"]), _color(raw.get("color"), [128, 128, 128]), entries,
                                             bool(raw.get("auto", True)), _band_from(raw.get("height")),
                                             _band_from(raw.get("slope")), noise))
        material.slope_radius_m = float(data.get("slope_radius_m", material.slope_radius_m))
        material.paint_softness_m = float(data.get("paint_softness_m", material.paint_softness_m))
        material.double_sided = bool(data.get("double_sided", False))
        shader = data.get("terrain_shader")
        if shader is not None:
            if not isinstance(shader, dict):
                raise ValueError("Invalid terrain shader settings")
            material.terrain_shader_version = str(shader.get("version", SHADER_VERSION))
            material.height_blend_enabled = bool(shader.get("height_blend_enabled", False))
            material.height_blend_transition = float(shader.get("height_blend_transition", 0.2))
            material.height_blend_strength = float(shader.get("height_blend_strength", 1.0))
            material.parallax_mode = str(shader.get("parallax_mode", "NONE"))
            material.parallax_min_steps = int(shader.get("parallax_min_steps", 8))
            material.parallax_max_steps = int(shader.get("parallax_max_steps", 32))
            material.unknown_terrain_shader_settings = copy.deepcopy(
                {key: value for key, value in shader.items() if key not in TERRAIN_SHADER_FIELDS})
        paint = data.get("paint")
        if isinstance(paint, dict) and paint.get("png"):
            from PIL import Image

            with Image.open(io.BytesIO(base64.b64decode(paint["png"]))) as image:
                material.paint = np.array(image.convert("L"), np.uint8)
            material.paint_cell = max(1, int(paint.get("cell", 1)))
        paint = data.get("surface_paint")
        if isinstance(paint, dict) and paint.get("png"):
            from PIL import Image

            with Image.open(io.BytesIO(base64.b64decode(paint["png"]))) as image:
                material.surface_paint = np.array(image.convert("L"), np.uint8)
            material.surface_paint_cell = max(1, int(paint.get("cell", 1)))
        try:
            raw_physical_materials = data.get("physical_materials", [])
            if not isinstance(raw_physical_materials, list):
                raise ValueError("physical_materials must be an array")
            for raw in raw_physical_materials:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    raise ValueError("physical material record must have a string name")
                if (isinstance(raw.get("friction"), bool) or not isinstance(raw.get("friction"), (int, float))
                        or isinstance(raw.get("restitution"), bool)
                        or not isinstance(raw.get("restitution"), (int, float))):
                    raise ValueError("physical material coefficients must be numbers")
                profile = raw.get("profile", "")
                ident = raw.get("id", "")
                if not isinstance(profile, str) or not isinstance(ident, str):
                    raise ValueError("physical material profile and ID must be strings")
                material.physical_materials.append(PhysicalMaterial(
                    name=raw["name"], friction=float(raw["friction"]),
                    restitution=float(raw["restitution"]), profile=profile, id=ident))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid physical material data: {exc}") from exc
        paint = data.get("physical_paint")
        if isinstance(paint, dict) and paint.get("png"):
            from PIL import Image

            with Image.open(io.BytesIO(base64.b64decode(paint["png"]))) as image:
                material.physical_paint = np.array(image.convert("L"), np.uint8)
            material.physical_paint_cell = max(1, int(paint.get("cell", 1)))
        material.validate_physical_materials()
        try:
            for road in data.get("roads", []):
                item = Road(surface=str(road["surface"]), width_m=float(road["width_m"]),
                            shoulder_m=float(road["shoulder_m"]),
                            points=[[float(v) for v in point] for point in road["points"]])
                item.validate(1 << 31, 1 << 31, complete=False)
                material.roads.append(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid road data: {exc}") from exc
        return material

    def validate_physical_materials(self) -> None:
        if len(self.physical_materials) > MAX_PHYSICAL_MATERIALS:
            raise ValueError(f"At most {MAX_PHYSICAL_MATERIALS} physical materials are supported")
        names = [item.name for item in self.physical_materials]
        ids = [item.id for item in self.physical_materials]
        if (not all(isinstance(name, str) and name.strip() for name in names)
                or len(set(names)) != len(names)):
            raise ValueError("Physical material names must be unique and not empty")
        if (not all(isinstance(ident, str) and ident.strip() for ident in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("Physical material IDs must be unique and not empty")
        for item in self.physical_materials:
            try:
                encoded_length = len(item.id.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError(f"Physical material '{item.name}': ID must be valid UTF-8") from exc
            if encoded_length > 128:
                raise ValueError(f"Physical material '{item.name}': ID must not exceed 128 UTF-8 bytes")
            if item.profile and item.profile not in PHYSICAL_SURFACE_PROFILES:
                raise ValueError(f"Physical material '{item.name}': unsupported profile {item.profile!r}")
            for value, label in ((item.friction, "friction"), (item.restitution, "restitution")):
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not 0.0 <= value <= 1.0):
                    raise ValueError(f"Physical material '{item.name}': {label} must be finite and in 0..1")
        known_ids = set(ids)
        for surface in self.surfaces:
            if (not isinstance(surface.physical_material_id, str)
                    or surface.physical_material_id and surface.physical_material_id not in known_ids):
                raise ValueError(f"Surface '{surface.name}': physical material ID does not exist")
        if self.physical_paint is not None:
            if self.physical_paint.dtype != np.uint8 or self.physical_paint.ndim != 2:
                raise ValueError("Physical paint must be a two-dimensional uint8 image")
            if any(dimension > PAINT_MAX_SIDE for dimension in self.physical_paint.shape):
                raise ValueError(f"Physical paint dimensions cannot exceed {PAINT_MAX_SIDE} cells per side")
            if (not isinstance(self.physical_paint_cell, int) or isinstance(self.physical_paint_cell, bool)
                    or self.physical_paint_cell < 1):
                raise ValueError("Physical paint cell size must be positive")
            invalid = np.unique(self.physical_paint)
            invalid = [int(value) for value in invalid
                       if value != PAINT_AUTO and value >= len(self.physical_materials)]
            if invalid:
                raise ValueError(f"Physical paint references missing material indices: {invalid[:8]}")

    def has_advanced_shader_features(self) -> bool:
        return (bool(self.unknown_terrain_shader_settings)
                or self.terrain_shader_version != SHADER_VERSION
                or self.height_blend_enabled or self.parallax_mode != "NONE"
                or self.height_blend_transition != 0.2 or self.height_blend_strength != 1.0
                or self.parallax_min_steps != 8 or self.parallax_max_steps != 32
                or any(surface.ao_map.path or surface.ao_strength != 1.0 or surface.height_map.path
                       or surface.height_scale != 1.0 or surface.height_bias != 0.0
                       or surface.parallax_scale != 0.0 or surface.emission
                       for surface in self.surfaces))


def _surface_dict(surface: Surface, base_dir: str | None) -> dict:
    def rel(path: str) -> str:
        if not path or base_dir is None:
            return path
        try:
            return os.path.relpath(path, base_dir).replace("\\", "/")
        except ValueError:  # another drive
            return path

    data = asdict(surface)
    data["albedo"] = rel(data["albedo"])
    data["normal"] = rel(data["normal"])
    data["metallic_map"]["path"] = rel(data["metallic_map"]["path"])
    data["roughness_map"]["path"] = rel(data["roughness_map"]["path"])
    data["ao_map"]["path"] = rel(data["ao_map"]["path"])
    data["height_map"]["path"] = rel(data["height_map"]["path"])
    data["emission"] = rel(data["emission"])
    defaults = {
        "ao_map": {"path": "", "channel": 0, "invert": False},
        "ao_strength": 1.0,
        "height_map": {"path": "", "channel": 0, "invert": False},
        "height_scale": 1.0,
        "height_bias": 0.0,
        "parallax_scale": 0.0,
        "emission": "",
        "gpu_encodings": {},
        "physical_material_id": "",
    }
    for key, default in defaults.items():
        if data[key] == default:
            del data[key]
    return data


def _biome_dict(biome: Biome) -> dict:
    result = {
        "name": biome.name, "color": list(biome.color), "auto": biome.auto,
        "height": _band_dict(biome.height), "slope": _band_dict(biome.slope),
        "surfaces": [{"surface": e.surface, "height": _band_dict(e.height), "slope": _band_dict(e.slope),
                      "strength": e.strength} for e in biome.surfaces],
    }
    if biome.noise != 0.0:
        result["noise"] = biome.noise
    return result


def srgb_to_linear(value: float) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# ------------------------------------------------------------- textures
@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime: str
    sha256: str
    width: int
    height: int
    name: str

    @property
    def extension(self) -> str:
        return {"image/png": ".png", "image/jpeg": ".jpg", "image/ktx2": ".ktx2",
                "image/vnd-ms.dds": ".dds"}[self.mime]


_cache: dict[tuple, PreparedImage] = {}
_cache_lock = threading.Lock()
MAX_TEXTURE_BYTES = 512 * 1024 * 1024
MAX_TEXTURE_PIXELS = 64 * 1024 * 1024
_DDS_MAX_PIXELS = MAX_TEXTURE_PIXELS


def _eight_bit(image):
    """PIL image -> 8-bit L, LA, RGB or RGBA."""
    from PIL import Image

    if image.mode in ("L", "LA", "RGB", "RGBA"):
        return image
    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        import numpy as np

        values = np.asarray(image, dtype=np.float64)
        peak = 65535.0 if image.mode.startswith("I;16") or values.max() > 255 else 255.0
        return Image.fromarray(np.clip(values / peak * 255.0 + 0.5, 0, 255).astype(np.uint8))
    has_alpha = "A" in image.getbands() or image.info.get("transparency") is not None
    return image.convert("RGBA" if has_alpha else "RGB")


def _dds_layout(raw: bytes) -> tuple[int, int, str, int, int]:
    """Validate a single-image DDS and return width, height, BC format, offset and payload size."""
    if len(raw) < 128 or raw[:4] != b"DDS " or struct.unpack_from("<I", raw, 4)[0] != 124:
        raise ValueError("Invalid DDS header")
    height, width = struct.unpack_from("<II", raw, 12)
    if not width or not height or width * height > _DDS_MAX_PIXELS:
        raise ValueError(f"DDS dimensions must be nonzero and at most {_DDS_MAX_PIXELS:,} pixels")

    fourcc = raw[84:88]
    offset = 128
    if fourcc == b"DX10":
        if len(raw) < 148:
            raise ValueError("Truncated DDS DX10 header")
        dxgi, dimension, misc, array_size = struct.unpack_from("<4I", raw, 128)
        if dimension != 3 or array_size != 1 or misc & 0x4:
            raise ValueError("Only single 2D DDS textures are supported (no arrays or cubemaps)")
        offset = 148
        bc = {
            70: "bc1", 71: "bc1", 72: "bc1",
            73: "bc2", 74: "bc2", 75: "bc2",
            76: "bc3", 77: "bc3", 78: "bc3",
            79: "bc4", 80: "bc4", 81: "bc4",
            82: "bc5", 83: "bc5", 84: "bc5",
            94: "bc6", 95: "bc6", 96: "bc6",
            97: "bc7", 98: "bc7", 99: "bc7",
        }.get(dxgi)
    else:
        caps2 = struct.unpack_from("<I", raw, 112)[0]
        if caps2 & (0x200 | 0x200000):
            raise ValueError("Only single 2D DDS textures are supported (no cubemaps or volumes)")
        bc = {
            b"DXT1": "bc1", b"DXT2": "bc2", b"DXT3": "bc2",
            b"DXT4": "bc3", b"DXT5": "bc3",
            b"ATI1": "bc4", b"BC4U": "bc4", b"BC4S": "bc4",
            b"ATI2": "bc5", b"BC5U": "bc5", b"BC5S": "bc5",
        }.get(fourcc)
    if bc is None:
        raise ValueError("Unsupported DDS compression format")
    block_size = 8 if bc in ("bc1", "bc4") else 16
    payload_size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block_size
    if len(raw) < offset + payload_size:
        raise ValueError("DDS texture data is truncated")
    return width, height, bc, offset, payload_size


def _decode_dds(raw: bytes):
    """Decode a BC-compressed DDS to an 8-bit PIL image."""
    from PIL import Image

    width, height, bc, offset, payload_size = _dds_layout(raw)
    decoder_name = {"bc1": "decode_bc1", "bc3": "decode_bc3", "bc4": "decode_bc4",
                    "bc5": "decode_bc5", "bc6": "decode_bc6", "bc7": "decode_bc7"}.get(bc)
    if decoder_name is None:
        raise ValueError(f"DDS format {bc.upper()} is not supported by the fallback decoder")
    try:
        import texture2ddecoder
    except ImportError as exc:
        raise ValueError("DDS decoding needs texture2ddecoder; reinstall AWT dependencies") from exc
    try:
        decoded = getattr(texture2ddecoder, decoder_name)(raw[offset:offset + payload_size], width, height)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"Could not decode DDS {bc.upper()} texture: {exc}") from exc
    if len(decoded) != width * height * 4:
        raise ValueError(f"DDS {bc.upper()} decoder returned an invalid image")
    return Image.frombytes("RGBA", (width, height), decoded, "raw", "BGRA")


def prepare_texture(path: str) -> PreparedImage:
    """Encoded bytes that ADM accepts: PNG and baseline JPEG pass through, anything else becomes PNG."""
    from PIL import Image

    stat = os.stat(path)
    is_dds = os.path.splitext(path)[1].lower() == ".dds"
    if stat.st_size > MAX_TEXTURE_BYTES:
        raise ValueError(f"Texture file is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
    key = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    with open(path, "rb") as handle:
        raw = handle.read(MAX_TEXTURE_BYTES + 1)
    if len(raw) > MAX_TEXTURE_BYTES:
        raise ValueError(f"Texture file is larger than the {MAX_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
    if raw[:12] == b"\xabKTX 20\xbb\r\n\x1a\n" or raw[:4] == b"DDS ":
        from .adm_export import _core, _png_scalar_image
        _core()
        from adm_blender.core import gputex

        mime = gputex.mime_of(raw)
        try:
            info = gputex.parse(raw, mime, strict=True)
        except gputex.GpuTextureError as exc:
            if mime == gputex.MIME_KTX2:
                raise ValueError(f"Cannot read texture {path}: {exc}") from exc
            info = None
        if info is not None:
            width, height = info["width"], info["height"]
            if width * height > MAX_TEXTURE_PIXELS:
                raise ValueError(f"Cannot read texture {path}: dimensions exceed the {MAX_TEXTURE_PIXELS:,}-pixel limit")
            if info["kind"] == "R16":
                pixels = gputex.decode_scalar_level(raw, info)
                data = _png_scalar_image(pixels, os.path.splitext(os.path.basename(path))[0]).data
            else:
                pixels, _ = gputex.decode(raw, mime, strict=True)
                out = io.BytesIO()
                Image.fromarray(pixels).save(out, "PNG", compress_level=6)
                data = out.getvalue()
            prepared = PreparedImage(data, "image/png", hashlib.sha256(data).hexdigest(),
                                     width, height, os.path.splitext(os.path.basename(path))[0])
            with _cache_lock:
                _cache[key] = prepared
            return prepared
    is_dds = is_dds or raw[:4] == b"DDS "
    if raw[:4] == b"DDS ":
        if len(raw) < 128 or struct.unpack_from("<I", raw, 4)[0] != 124:
            raise ValueError(f"Cannot read texture {path}: invalid DDS header")
        height, width = struct.unpack_from("<II", raw, 12)
        if not width or not height or width * height > _DDS_MAX_PIXELS:
            raise ValueError(f"Cannot read texture {path}: DDS dimensions exceed the {_DDS_MAX_PIXELS:,}-pixel limit")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if not width or not height or width * height > MAX_TEXTURE_PIXELS:
                raise ValueError(f"Texture dimensions exceed the {MAX_TEXTURE_PIXELS:,}-pixel limit")
            image.load()
            fmt = image.format
            progressive = bool(image.info.get("progressive") or image.info.get("progression"))
            if fmt == "PNG":
                data, mime = raw, "image/png"
            elif fmt == "JPEG" and not progressive and image.mode in ("L", "RGB"):
                data, mime = raw, "image/jpeg"
            else:
                out = io.BytesIO()
                if image.mode in ("I;16", "I;16B", "I;16L"):
                    Image.fromarray(np.asarray(image, dtype=np.uint16)).save(out, "PNG", compress_level=6)
                else:
                    _eight_bit(image).save(out, "PNG", compress_level=6)
                data, mime = out.getvalue(), "image/png"
    except (OSError, ValueError, NotImplementedError) as exc:
        if not is_dds and raw[:4] != b"DDS ":
            raise ValueError(f"Cannot read texture {path}: {exc}") from exc
        try:
            image = _decode_dds(raw)
            width, height = image.size
            out = io.BytesIO()
            image.save(out, "PNG", compress_level=6)
            data, mime = out.getvalue(), "image/png"
        except (OSError, ValueError) as dds_error:
            raise ValueError(f"Cannot read texture {path}: {dds_error}") from dds_error
    prepared = PreparedImage(data, mime, hashlib.sha256(data).hexdigest(), width, height,
                             os.path.splitext(os.path.basename(path))[0])
    with _cache_lock:
        _cache[key] = prepared
    return prepared


def normal_preview_array(path: str) -> np.ndarray:
    """Decode a normal map for display, reconstructing Z for BC5 sources."""
    from PIL import Image

    prepared = prepare_texture(path)
    with Image.open(io.BytesIO(prepared.data)) as image:
        rgba = np.array(_eight_bit(image).convert("RGBA"))
    with open(path, "rb") as handle:
        header = handle.read(148)
    ktx_bc5 = (len(header) >= 16 and header[:12] == b"\xabKTX 20\xbb\r\n\x1a\n"
               and struct.unpack_from("<I", header, 12)[0] == 141)
    dds_bc5 = (len(header) >= 88 and header[:4] == b"DDS " and
               (header[84:88] in (b"ATI2", b"BC5U") or
                (header[84:88] == b"DX10" and len(header) >= 132
                 and struct.unpack_from("<I", header, 128)[0] == 83)))
    if ktx_bc5 or dds_bc5:
        from .adm_export import _core
        _core()
        from adm_blender.core import gputex

        rgba = np.rint(gputex.reconstruct_bc5_normal(rgba.astype(np.float32) / 255.0) * 255).astype(np.uint8)
    return rgba
