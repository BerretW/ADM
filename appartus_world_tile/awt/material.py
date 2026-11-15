"""The one terrain material of a world: ``adm.terrain.four_layer`` with four layers.

Layer order follows the blend mask channels: 0 ground (R), 1 rock (G), 2 snow (B), 3 water (A).
Texture paths are absolute in memory; projects store them relative to the project file.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
from dataclasses import asdict, dataclass, field

from .masks import LAYERS

SHADER_ID = "adm.terrain.four_layer"
SHADER_VERSION = "1.0.0"
CHANNELS = "RGBA"
DEFAULT_ROUGHNESS = {"ground": 0.9, "rock": 0.8, "snow": 0.55, "water": 0.08}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.bmp *.dds *.webp);;All files (*)"


@dataclass
class MapSlot:
    """A metallic or roughness texture: which channel to read and whether to invert it."""

    path: str = ""
    channel: int = 0  # 0..3 = R, G, B, A
    invert: bool = False


@dataclass
class Layer:
    name: str
    color: list[int] = field(default_factory=lambda: [255, 255, 255])  # sRGB tint, multiplies albedo
    repeat_m: float = 4.0  # size of one texture repeat on the ground
    albedo: str = ""
    metallic: float = 0.0
    metallic_map: MapSlot = field(default_factory=MapSlot)
    roughness: float = 0.8
    roughness_map: MapSlot = field(default_factory=MapSlot)
    normal: str = ""

    def textures(self) -> list[str]:
        return [p for p in (self.albedo, self.metallic_map.path, self.roughness_map.path, self.normal) if p]


def _default_layers() -> list[Layer]:
    return [Layer(name=info["name"], color=list(info["color"]),
                  roughness=DEFAULT_ROUGHNESS.get(info["name"], 0.8)) for info in LAYERS]


@dataclass
class TerrainMaterial:
    layers: list[Layer] = field(default_factory=_default_layers)
    double_sided: bool = False

    # ------------------------------------------------------------ values
    def uv_scale(self, tile_size_m: float) -> list[float]:
        """Integer repeats per tile, so textures continue across tile borders."""
        return [float(min(1000, max(1, round(tile_size_m / layer.repeat_m)))) if layer.repeat_m > 0 else 1.0
                for layer in self.layers]

    def textures(self) -> list[str]:
        seen: list[str] = []
        for layer in self.layers:
            for path in layer.textures():
                if path not in seen:
                    seen.append(path)
        return seen

    def validate(self) -> None:
        if len(self.layers) != 4:
            raise ValueError("The terrain material needs exactly four layers")
        for layer in self.layers:
            if not layer.repeat_m > 0:
                raise ValueError(f"Layer '{layer.name}': texture repeat must be positive")
            for value in (layer.metallic, layer.roughness):
                if not 0.0 <= value <= 1.0:
                    raise ValueError(f"Layer '{layer.name}': metallic and roughness must be 0..1")
            for slot in (layer.metallic_map, layer.roughness_map):
                if slot.channel not in (0, 1, 2, 3):
                    raise ValueError(f"Layer '{layer.name}': map channel must be R, G, B or A")
            for path in layer.textures():
                if not os.path.isfile(path):
                    raise ValueError(f"Layer '{layer.name}': texture not found: {path}")

    def fingerprint(self, tile_size_m: float) -> str:
        """Changes whenever anything that ends up in an exported tile changes, including texture files."""
        data = self.to_dict(None)
        data["uv_scale"] = self.uv_scale(tile_size_m)
        data["files"] = {path: prepare_texture(path).sha256 for path in self.textures()}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]

    # ------------------------------------------------------- persistence
    def to_dict(self, base_dir: str | None) -> dict:
        def rel(path: str) -> str:
            if not path or base_dir is None:
                return path
            try:
                return os.path.relpath(path, base_dir).replace("\\", "/")
            except ValueError:  # another drive
                return path

        data = asdict(self)
        for layer in data["layers"]:
            layer["albedo"] = rel(layer["albedo"])
            layer["normal"] = rel(layer["normal"])
            layer["metallic_map"]["path"] = rel(layer["metallic_map"]["path"])
            layer["roughness_map"]["path"] = rel(layer["roughness_map"]["path"])
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
            return MapSlot(path=absolute(value.get("path")), channel=int(value.get("channel", 0)) % 4,
                           invert=bool(value.get("invert", False)))

        layers = _default_layers()
        for layer, raw in zip(layers, data.get("layers", [])):
            if not isinstance(raw, dict):
                continue
            color = raw.get("color", layer.color)
            if isinstance(color, list) and len(color) == 3:
                layer.color = [max(0, min(255, int(c))) for c in color]
            layer.repeat_m = float(raw.get("repeat_m", layer.repeat_m))
            layer.albedo = absolute(raw.get("albedo"))
            layer.metallic = float(raw.get("metallic", layer.metallic))
            layer.metallic_map = slot(raw.get("metallic_map"))
            layer.roughness = float(raw.get("roughness", layer.roughness))
            layer.roughness_map = slot(raw.get("roughness_map"))
            layer.normal = absolute(raw.get("normal"))
        return cls(layers=layers, double_sided=bool(data.get("double_sided", False)))


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
        return ".png" if self.mime == "image/png" else ".jpg"


_cache: dict[tuple, PreparedImage] = {}
_cache_lock = threading.Lock()


def _eight_bit(image):
    """PIL image -> 8-bit L, LA, RGB or RGBA."""
    from PIL import Image

    if image.mode in ("L", "LA", "RGB", "RGBA"):
        return image
    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        import numpy as np

        values = np.asarray(image, dtype=np.float64)
        peak = 65535.0 if image.mode.startswith("I;16") or values.max() > 255 else 255.0
        return Image.fromarray(np.clip(values / peak * 255.0 + 0.5, 0, 255).astype(np.uint8), "L")
    has_alpha = "A" in image.getbands() or image.info.get("transparency") is not None
    return image.convert("RGBA" if has_alpha else "RGB")


def prepare_texture(path: str) -> PreparedImage:
    """Encoded bytes that ADM accepts: PNG and baseline JPEG pass through, anything else becomes PNG."""
    from PIL import Image

    stat = os.stat(path)
    key = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.size
            fmt = image.format
            progressive = bool(image.info.get("progressive") or image.info.get("progression"))
            if fmt == "PNG":
                data, mime = raw, "image/png"
            elif fmt == "JPEG" and not progressive and image.mode in ("L", "RGB"):
                data, mime = raw, "image/jpeg"
            else:
                out = io.BytesIO()
                _eight_bit(image).save(out, "PNG", compress_level=6)
                data, mime = out.getvalue(), "image/png"
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read texture {path}: {exc}") from exc
    prepared = PreparedImage(data, mime, hashlib.sha256(data).hexdigest(), width, height,
                             os.path.splitext(os.path.basename(path))[0])
    with _cache_lock:
        _cache[key] = prepared
    return prepared
