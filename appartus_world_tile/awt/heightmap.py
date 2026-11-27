"""Heightmap loading.

Integer sources keep their dtype (uint8/uint16) to save memory; conversion to
metres happens inside the kernels through ``scale`` and ``offset``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import numpy as np

MAX_SAMPLES = 1 << 30  # 32768 x 32768


def sample_digest(data: np.ndarray) -> str:
    """Hash heightmap samples together with their dtype and dimensions."""
    samples = np.ascontiguousarray(data)
    digest = hashlib.blake2b(digest_size=16)
    digest.update(samples.dtype.str.encode("ascii"))
    digest.update(str(samples.shape).encode("ascii"))
    digest.update(samples.view(np.uint8))
    return digest.hexdigest()


@dataclass
class Heightmap:
    data: np.ndarray  # (rows, cols), row 0 is north
    path: str
    normalized_max: float  # 255 / 65535 for integers, 0 for float metres

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    @property
    def height(self) -> int:
        return int(self.data.shape[0])

    @property
    def is_integer(self) -> bool:
        return self.normalized_max > 0


def _check_shape(data: np.ndarray, path: str) -> np.ndarray:
    if data.ndim != 2:
        raise ValueError(f"{os.path.basename(path)}: expected a single-channel heightmap, got shape {data.shape}")
    rows, cols = data.shape
    if rows < 2 or cols < 2:
        raise ValueError(f"{os.path.basename(path)}: heightmap must be at least 2 x 2 samples")
    if rows * cols > MAX_SAMPLES:
        raise ValueError(f"{os.path.basename(path)}: {cols} x {rows} exceeds the supported {MAX_SAMPLES:,} samples")
    return data


def _from_array(data: np.ndarray, path: str) -> Heightmap:
    if data.ndim == 3:
        if data.shape[2] in (2, 4):  # grey + alpha / RGBA
            data = data[:, :, 0] if data.shape[2] == 2 else data[:, :, :3]
        if data.ndim == 3:
            # Grey stored as RGB: use the first channel when all channels match.
            if np.array_equal(data[::64, ::64, 0], data[::64, ::64, 1]):
                data = data[:, :, 0]
            else:
                raise ValueError(f"{os.path.basename(path)}: colour image; export the heightmap as greyscale")
    data = _check_shape(data, path)
    if data.dtype == np.uint8:
        return Heightmap(np.ascontiguousarray(data), path, 255.0)
    if data.dtype == np.uint16:
        return Heightmap(np.ascontiguousarray(data), path, 65535.0)
    if data.dtype.kind in "iu":
        lo, hi = int(data.min()), int(data.max())
        if lo >= 0 and hi <= 65535:
            return Heightmap(data.astype(np.uint16), path, 65535.0)
        return Heightmap(data.astype(np.float32), path, 0.0)
    if data.dtype.kind == "f":
        out = np.ascontiguousarray(data, dtype=np.float32)
        if not np.isfinite(out).all():
            raise ValueError(f"{os.path.basename(path)}: heightmap contains NaN or infinite values")
        return Heightmap(out, path, 0.0)
    raise ValueError(f"{os.path.basename(path)}: unsupported sample type {data.dtype}")


def load_heightmap(path: str, raw_size: tuple[int, int] | None = None) -> Heightmap:
    """Load PNG/TIFF (Pillow or tifffile), RAW 16-bit (.r16/.raw) or .npy."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npy":
        return _from_array(np.load(path), path)
    if ext in (".r16", ".raw"):
        size = os.path.getsize(path)
        if raw_size is None:
            side = int(round((size / 2) ** 0.5))
            if side * side * 2 != size:
                raise ValueError(f"{os.path.basename(path)}: RAW is not square, set its width and height")
            raw_size = (side, side)
        cols, rows = raw_size
        if cols * rows * 2 != size:
            raise ValueError(f"{os.path.basename(path)}: {cols} x {rows} x 16-bit needs {cols * rows * 2:,} bytes, file has {size:,}")
        return _from_array(np.fromfile(path, dtype="<u2").reshape(rows, cols), path)
    if ext in (".tif", ".tiff"):
        try:
            import tifffile
        except ImportError:
            tifffile = None
        if tifffile is not None:
            return _from_array(tifffile.imread(path), path)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_SAMPLES
    with Image.open(path) as image:
        if image.mode in ("I;16", "I;16L", "I;16B"):
            data = np.asarray(image).astype(np.uint16, copy=False)
        elif image.mode == "P":
            data = np.asarray(image.convert("L"))
        else:
            data = np.asarray(image)
    return _from_array(data, path)


def preview(data: np.ndarray, max_side: int = 1024) -> np.ndarray:
    """Strided float32 copy of at most ``max_side`` samples per side."""
    step = max(1, int(np.ceil(max(data.shape) / max_side)))
    return np.asarray(data[::step, ::step], dtype=np.float32)
