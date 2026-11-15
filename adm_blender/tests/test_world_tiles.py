"""Headless Blender tests for importing Apparatus World Tile output (manifest, PLY tiles, masks)."""
import json
import os
import sys
import tempfile
import traceback

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FIELDS = ("x", "y", "z", "nx", "ny", "nz", "s", "t", "s1", "t1")


def write_ply(path, cells, size, z0):
    n = cells + 1
    gx, gy = np.meshgrid(np.linspace(0.0, size, n), np.linspace(0.0, size, n))
    vert = np.zeros(n * n, dtype=[(f, "<f4") for f in FIELDS])
    vert["x"], vert["y"] = gx.ravel(), gy.ravel()
    vert["z"] = z0 + 0.1 * gx.ravel()
    vert["nz"] = 1.0
    vert["s"], vert["t"] = vert["x"] / size, vert["y"] / size
    vert["s1"], vert["t1"] = 0.1 + 0.8 * vert["s"], 0.1 + 0.8 * vert["t"]
    faces = []
    for j in range(cells):
        for i in range(cells):
            a = j * n + i
            faces += [(a, a + 1, a + n + 1), (a, a + n + 1, a + n)]
    face = np.zeros(len(faces), dtype=[("n", "u1"), ("i", "<u4", (3,))])
    face["n"], face["i"] = 3, faces
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(vert)}\n" + "".join(f"property float {f}\n" for f in FIELDS)
              + f"element face {len(face)}\nproperty list uchar uint vertex_indices\nend_header\n")
    with open(path, "wb") as handle:
        handle.write(header.encode("ascii"))
        handle.write(vert.tobytes())
        handle.write(face.tobytes())
    return len(vert), len(face)


def write_mask(path, size):
    image = bpy.data.images.new("mask_fixture", size, size, alpha=True)
    pixels = np.zeros((size, size, 4), dtype=np.float32)
    pixels[..., 0] = 1.0
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def make_fixture(root):
    os.makedirs(os.path.join(root, "tiles"))
    os.makedirs(os.path.join(root, "masks"))
    size = 20.0
    lods_meta = [{"index": 0, "max_error_m": 0.1}, {"index": 1, "max_error_m": 0.5}]
    tiles = []
    for ix in range(2):
        tile_id = f"x{ix:03d}_y000"
        lods = []
        for lod, cells in enumerate((4, 2)):
            rel = f"tiles/{tile_id}_lod{lod}.ply"
            v, f = write_ply(os.path.join(root, rel), cells, size, 100.0)
            lods.append({"file": rel, "vertices": v, "triangles": f, "measured_error_m": 0.0})
        rel_mask = f"masks/{tile_id}_mask.png"
        write_mask(os.path.join(root, rel_mask), 8)
        tiles.append({"id": tile_id, "ix": ix, "iy": 0, "origin_m": [ix * size, 0.0, 0.0],
                      "size_m": [size, size], "lods": lods, "mask": rel_mask, "mask_px": [8, 8]})
    layers = [{"channel": c, "layer": i, "name": n, "color": [100, 120, 140]}
              for i, (c, n) in enumerate(zip("RGBA", ("ground", "rock", "snow", "water")))]
    manifest = {"format": "apparatus-world-tile", "format_version": 1, "tile_size_m": size,
                "bounds_m": [0.0, 0.0, 2 * size, size], "source": {"height_range_m": [100.0, 102.0]},
                "mask_layers": layers, "lods": lods_meta, "tiles": tiles}
    path = os.path.join(root, "manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return path, manifest


def main(tmp):
    adm_blender.register()
    from adm_blender.blender import world_tiles
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter

    bpy.ops.wm.read_homefile(use_empty=True)
    path, manifest = make_fixture(os.path.join(tmp, "world"))

    assert bpy.ops.adm.import_world_tiles(filepath=path, texture_repeat_m=5.0) == {"FINISHED"}
    roots = sorted((o for o in bpy.data.objects if o.get("adm_world_tile_id") and o.type == "EMPTY"
                    and o.adm.adm_type == "MODEL"), key=lambda o: o.name)
    assert [r["adm_world_tile_id"] for r in roots] == ["x000_y000", "x001_y000"]
    assert tuple(roots[1].matrix_world.translation) == (20.0, 0.0, 0.0)
    group = roots[0].children[0]
    assert group.adm.adm_type == "LOD_GROUP" and len(group.adm.lod_levels) == 2
    assert [lvl.min_distance for lvl in group.adm.lod_levels] == [0.0, 20.0]
    lod0 = group.adm.lod_levels[0].object
    assert len(lod0.data.vertices) == 25 and len(lod0.data.polygons) == 32
    assert [uv.name for uv in lod0.data.uv_layers][:2] == ["UVMap", "UVMap_1"]
    assert abs(lod0.data.vertices[24].co.z - 102.0) < 1e-4

    template = bpy.data.materials[world_tiles.TEMPLATE_NAME]
    assert template.adm.shader == "TERRAIN_4"
    assert tuple(template.adm.params["uv_scale"].value_vec) == (4.0,) * 4
    mats = world_tiles.tile_materials(template.name)
    assert len(mats) == 2
    assert len({m.adm.animation_id for m in mats} | {template.adm.animation_id}) == 3
    masks = [m.adm.params["blend_mask"].image for m in mats]
    assert all(img is not None for img in masks) and masks[0] != masks[1]
    assert all(m.adm.params["blend_mask"].tex_coord == 1 for m in mats)
    assert masks[0].colorspace_settings.name == "Non-Color"
    swatch = next(o for o in bpy.data.objects if o.get(world_tiles.TEMPLATE_FLAG))
    assert swatch.adm.export_exclude and swatch.data.materials[0] == template

    # editing the template and syncing updates every tile but keeps its own mask, name and id
    ids = [m.adm.animation_id for m in mats]
    template.adm.params["uv_scale"].value_vec = (7.0,) * 4
    bpy.context.view_layer.objects.active = swatch
    assert bpy.ops.adm.sync_world_terrain_materials() == {"FINISHED"}
    mats = world_tiles.tile_materials(template.name)
    assert len(mats) == 2
    assert all(tuple(m.adm.params["uv_scale"].value_vec) == (7.0,) * 4 for m in mats)
    assert [m.adm.params["blend_mask"].image for m in mats] == masks
    assert [m.adm.animation_id for m in mats] == ids
    assert lod0.data.materials[0] in mats

    data, report = ModelExporter(bpy.context, roots[0], ExportOptions()).export()
    assert report.ok, report
    assert data

    # region, single LOD, invalid requests and the folder guard
    before = len(bpy.data.objects)
    assert bpy.ops.adm.import_world_tiles(filepath=path, lod_mode="ONE", lod=1, use_region=True,
                                          region_min=(1, 0), region_max=(1, 0)) == {"FINISHED"}
    assert len(bpy.data.objects) == before + 2
    assert len(world_tiles.tile_materials(template.name)) == 3
    for kwargs in ({"lod_mode": "ONE", "lod": 5},
                   {"use_region": True, "region_min": (5, 5), "region_max": (6, 6)}):
        try:
            bpy.ops.adm.import_world_tiles(filepath=path, **kwargs)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"import must fail for {kwargs}")
    manifest["tiles"][0]["lods"][0]["file"] = "../outside.ply"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.collections))
    try:
        bpy.ops.adm.import_world_tiles(filepath=path)
    except RuntimeError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("paths outside the tile folder must be refused")
    after = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.collections))
    assert after == before, (before, after)

    truncated = os.path.join(tmp, "world", "tiles", "x001_y000_lod0.ply")
    with open(truncated, "r+b") as handle:
        handle.truncate(os.path.getsize(truncated) - 200)
    try:
        world_tiles.read_ply(truncated)
    except world_tiles.WorldTileError:
        pass
    else:
        raise AssertionError("truncated PLY must be refused")
    print("world tiles: all checks passed")


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory() as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)
