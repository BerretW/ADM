"""Generate a small, deterministic Advanced World Tile reference project."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from adm_blender.core import gputex  # noqa: E402
from appartus_world_tile.awt.material import (  # noqa: E402
    Band,
    Biome,
    BiomeSurface,
    MapSlot,
    Surface,
    TerrainMaterial,
)
from appartus_world_tile.awt.pipeline import BuildParams  # noqa: E402
from appartus_world_tile.awt.project import Project  # noqa: E402
from appartus_world_tile.awt.roads import Road  # noqa: E402


OUT = REPO / "appartus_world_tile" / "reference_project"
SIZE = 257


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    height = (
        18 * np.sin(xx / 24)
        + 12 * np.sin(yy / 18)
        + 55 * ((xx - SIZE * 0.68) / SIZE) ** 2
        + 28 * ((yy - SIZE * 0.30) / SIZE) ** 2
    )
    height = np.clip((height - height.min()) / max(1e-6, height.max() - height.min()) * 255, 0, 255)
    Image.fromarray(height.astype(np.uint8), "L").save(OUT / "heightmap.png")

    texture_root = REPO / "adm-standard" / "fixtures" / "advanced-materials"
    gpu_dir = OUT / "textures"
    gpu_dir.mkdir(parents=True, exist_ok=True)
    gpu_sources = {
        "rock": ("R16", gputex.MIME_DDS, "height", "rock_height.dds"),
        "cobblestone": ("R8", gputex.MIME_KTX2, "height", "cobblestone_height.ktx2"),
        "sand": ("BC4", gputex.MIME_DDS, "height", "sand_height.dds"),
        "dirt": ("BC5", gputex.MIME_KTX2, "normal", "dirt_normal.ktx2"),
        "grass": ("BC7", gputex.MIME_KTX2, "albedo", "grass_albedo.ktx2"),
    }
    names = ("rock", "cobblestone", "sand", "dirt", "grass")
    surfaces = []
    for name in names:
        folder = texture_root / name
        surface = Surface(
            name=name,
            repeat_m=4.0,
            albedo=str(folder / "albedo.png"),
            roughness=0.82,
            roughness_map=MapSlot(str(folder / "roughness.png"), channel=0),
            normal=str(folder / "normal.png"),
            ao_map=MapSlot(str(folder / "ao.png"), channel=0),
            ao_strength=1.0,
            height_map=MapSlot(str(folder / "height.png"), channel=0),
            height_scale=1.0,
            height_bias=0.0,
            parallax_scale=0.08,
        )
        kind, mime, role, filename = gpu_sources[name]
        with Image.open(folder / f"{role}.png") as image:
            if role == "height":
                values = np.asarray(image.convert("L"), dtype=np.uint8)
                if kind == "R16":
                    y, x = np.indices(values.shape)
                    values = np.clip(values.astype(np.int32) * 257 + (x + 3 * y) % 97 - 48,
                                     0, 65535).astype(np.uint16)
                blob, _ = gputex.encode_scalar(values, mime, kind, mipmaps=True)
                surface.height_map.path = str(gpu_dir / filename)
            else:
                pixels = np.asarray(image.convert("RGBA"))
                blob, _ = gputex.encode(pixels, mime, kind, srgb=(role == "albedo"), mipmaps=True)
                setattr(surface, role, str(gpu_dir / filename))
        (gpu_dir / filename).write_bytes(blob)
        surfaces.append(surface)

    material = TerrainMaterial(
        surfaces=surfaces,
        biomes=[
            Biome("grassland", [82, 130, 64], [
                BiomeSurface("grass"),
                BiomeSurface("dirt", height=Band(None, 120.0, 20.0)),
            ], height=Band(None, 150.0, 30.0), noise=0.35),
            Biome("sand shore", [194, 174, 118], [
                BiomeSurface("sand"),
                BiomeSurface("grass", height=Band(45.0, None, 15.0)),
            ], height=Band(None, 55.0, 12.0), noise=0.25),
            Biome("rock ridge", [132, 128, 120], [
                BiomeSurface("rock"),
                BiomeSurface("cobblestone", slope=Band(None, 35.0, 8.0)),
                BiomeSurface("dirt", slope=Band(None, 28.0, 6.0), strength=0.45),
            ], height=Band(150.0, None, 25.0), slope=Band(20.0, None, 8.0), noise=0.45),
            Biome("road edge", [155, 145, 130], [
                BiomeSurface("cobblestone"),
                BiomeSurface("dirt", strength=0.30),
            ], auto=False, noise=0.10),
        ],
        height_blend_enabled=True,
        height_blend_transition=0.2,
        height_blend_strength=1.0,
        parallax_mode="PARALLAX_OCCLUSION",
        parallax_min_steps=8,
        parallax_max_steps=32,
        terrain_shader_version="2.1.0",
        roads=[
            Road(
                surface="cobblestone",
                width_m=8.0,
                shoulder_m=5.0,
                points=[[48.0, 48.0, 45.0], [128.0, 128.0, 90.0], [208.0, 176.0, 150.0]],
            )
        ],
    )
    params = BuildParams(
        input_path=str(OUT / "heightmap.png"),
        out_dir=str(OUT / "tiles"),
        spacing_m=2.0,
        height_min_m=0.0,
        height_max_m=500.0,
        tile_cells=128,
        max_errors_m=[1.0, 4.0, 12.0],
        texture_error=0.12,
        texture_detail_m=4.0,
    )
    project = Project(params=params, material=material)
    project.export.out_dir = str(OUT / "adm")
    project.save(str(OUT / "advanced_reference.awtp"))
    print(OUT / "advanced_reference.awtp")


if __name__ == "__main__":
    main()
