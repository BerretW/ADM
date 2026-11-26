"""Generate original procedural material references and an Advanced Terrain fixture manifest.

Run with an authoring Python environment:
    python adm-standard/tools/generate_advanced_material_references.py

The generated PNG files contain deterministic noise and have no third-party assets.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required: python -m pip install Pillow") from exc


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "adm-standard" / "fixtures" / "advanced-materials"
SIZE = 256


def noise(x: int, y: int, seed: int) -> float:
    n = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    n ^= n >> 16
    return (n & 0xFFFF) / 65535.0


def normal_bytes(x: int, y: int, height: bytes, side: int) -> tuple[int, int, int, int]:
    cx = min(side - 1, max(0, x))
    cy = min(side - 1, max(0, y))
    left = height[cy * side + max(0, cx - 1)] / 255.0
    right = height[cy * side + min(side - 1, cx + 1)] / 255.0
    down = height[max(0, cy - 1) * side + cx] / 255.0
    up = height[min(side - 1, cy + 1) * side + cx] / 255.0
    dx = (left - right) * 3.0
    dy = (down - up) * 3.0
    length = math.sqrt(dx * dx + dy * dy + 1.0)
    return (
        int((dx / length * 0.5 + 0.5) * 255),
        int((dy / length * 0.5 + 0.5) * 255),
        int(((1.0 / length) * 0.5 + 0.5) * 255),
        255,
    )


def generate(name: str, seed: int, albedo: tuple[int, int, int]) -> dict:
    height = bytearray(SIZE * SIZE)
    roughness = bytearray(SIZE * SIZE)
    ao = bytearray(SIZE * SIZE)
    albedo_pixels = bytearray(SIZE * SIZE * 4)
    for y in range(SIZE):
        for x in range(SIZE):
            coarse = noise(x // 8, y // 8, seed)
            fine = noise(x, y, seed + 101)
            ridge = abs(math.sin((x + y) * 0.045 + seed)) * (0.18 if name != "sand" else 0.05)
            h = max(0.0, min(1.0, coarse * 0.58 + fine * 0.22 + ridge))
            r = int(h * 255)
            i = y * SIZE + x
            height[i] = r
            roughness[i] = int(max(16, min(255, (185 + (1.0 - h) * 50 + (fine - 0.5) * 24))))
            ao[i] = int(max(128, min(255, 255 - h * 70 + fine * 12)))
            grain = (fine - 0.5) * 22
            j = i * 4
            albedo_pixels[j:j + 4] = bytes((
                max(0, min(255, int(albedo[0] + grain))),
                max(0, min(255, int(albedo[1] + grain))),
                max(0, min(255, int(albedo[2] + grain))),
                255,
            ))

    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    Image.frombytes("L", (SIZE, SIZE), bytes(height)).save(folder / "height.png")
    Image.frombytes("L", (SIZE, SIZE), bytes(roughness)).save(folder / "roughness.png")
    Image.frombytes("L", (SIZE, SIZE), bytes(ao)).save(folder / "ao.png")
    Image.frombytes("RGBA", (SIZE, SIZE), bytes(albedo_pixels)).save(folder / "albedo.png")
    normals = bytearray(SIZE * SIZE * 4)
    for y in range(SIZE):
        for x in range(SIZE):
            normals[(y * SIZE + x) * 4:(y * SIZE + x + 1) * 4] = bytes(normal_bytes(x, y, height, SIZE))
    Image.frombytes("RGBA", (SIZE, SIZE), bytes(normals)).save(folder / "normal.png")
    return {
        "id": name,
        "maps": {
            "albedo": f"advanced-materials/{name}/albedo.png",
            "normal": f"advanced-materials/{name}/normal.png",
            "roughness": f"advanced-materials/{name}/roughness.png",
            "ao": f"advanced-materials/{name}/ao.png",
            "height": f"advanced-materials/{name}/height.png",
        },
    }


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    OUT = parser.parse_args().output_dir
    OUT.mkdir(parents=True, exist_ok=True)
    materials = [
        generate("rock", 11, (105, 104, 96)),
        generate("cobblestone", 23, (98, 102, 98)),
        generate("sand", 37, (184, 154, 103)),
        generate("dirt", 49, (112, 78, 48)),
        generate("grass", 61, (72, 112, 48)),
    ]
    manifest = {
        "format": "ADM-procedural-material-reference",
        "formatVersion": 1,
        "materials": materials,
        "notes": [
            "All pixels and texture data are generated deterministically.",
            "Height and AO are single-channel linear grayscale.",
            "Normal maps use the ADM tangent-space +Y convention.",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
