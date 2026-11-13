"""Minimal dependency-free PNG encoder (8-bit RGBA / RGB)."""

import struct
import zlib


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(width, height, pixels, channels=4, level=6):
    """``pixels``: bytes-like, rows top-to-bottom, ``channels`` bytes per pixel (3 or 4)."""
    color_type = {3: 2, 4: 6}[channels]
    stride = width * channels
    raw = bytes(pixels)
    if len(raw) != stride * height:
        raise ValueError("pixel buffer size mismatch")
    rows = b"".join(b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(rows, level))
            + _chunk(b"IEND", b""))
