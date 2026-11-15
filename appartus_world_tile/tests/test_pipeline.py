import json
import os
import tempfile
import unittest
from collections import Counter

import numpy as np

from awt.heightmap import load_heightmap
from awt.pipeline import BuildParams, build, load_manifest
from awt.ply import read_ply


def _terrain(rows, cols, seed=1):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    z = 40 * np.sin(x / 17.0) * np.cos(y / 23.0) + 0.02 * (x - 60) ** 2 / 10 + rng.normal(0, 0.1, (rows, cols))
    return z.astype(np.float32)


def _world_mesh(manifest, lod=0):
    """Merge every tile into world-space grid coordinates (col, row) and faces."""
    sp = manifest["spacing_m"]
    bx, by = manifest["bounds_m"][:2]
    last_y = manifest["source"]["height"] - 1
    keys = {}
    faces = []
    for tile in manifest["tiles"]:
        verts, tri = read_ply(os.path.join(manifest["_dir"], tile["lods"][lod]["file"]))
        ox, oy, _ = tile["origin_m"]
        cols = np.rint((verts["x"] + ox - bx) / sp).astype(int)
        rows = last_y - np.rint((verts["y"] + oy - by) / sp).astype(int)
        ids = [keys.setdefault((c, r), len(keys)) for c, r in zip(cols, rows)]
        faces.extend((ids[a], ids[b], ids[c]) for a, b, c in tri)
    points = np.zeros((len(keys), 2), int)
    for (c, r), i in keys.items():
        points[i] = (c, r)
    return points, np.array(faces)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _build(self, data, **kwargs):
        src = os.path.join(self.tmp.name, "src.npy")
        np.save(src, data)
        params = BuildParams(input_path=src, out_dir=os.path.join(self.tmp.name, "out"), **kwargs)
        build(params)
        return load_manifest(params.out_dir)

    def test_error_bound_watertight_and_area(self):
        data = _terrain(97, 130)  # 129 x 96 cells: not a multiple of the tile size
        eps = 0.6
        manifest = self._build(data, tile_cells=32, max_errors_m=[eps], spacing_m=2.0)
        self.assertEqual((manifest["tiles_x"], manifest["tiles_y"]), (5, 3))
        points, faces = _world_mesh(manifest)
        rows, cols = data.shape

        p = points[faces]  # (n, 3, 2) as (col, row)
        cross = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])
        # Counter-clockwise in world space means clockwise in (col, row) space.
        self.assertTrue(np.all(cross < 0))
        self.assertEqual(-cross.sum() / 2, (cols - 1) * (rows - 1))

        edges = Counter()
        for a, b, c in faces:
            for u, v in ((a, b), (b, c), (c, a)):
                edges[(min(u, v), max(u, v))] += 1
        self.assertLessEqual(max(edges.values()), 2)
        for (u, v), count in edges.items():
            if count == 1:  # boundary edges must lie on the outer border
                (cu, ru), (cv, rv) = points[u], points[v]
                self.assertTrue((cu == cv and cu in (0, cols - 1)) or (ru == rv and ru in (0, rows - 1)),
                                f"crack at {points[u]}-{points[v]}")

        worst = 0.0
        z = data.astype(np.float64)
        for tri in p:
            (ax, ay), (bx, by), (cx, cy) = tri
            det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
            ys, xs = np.mgrid[min(ay, by, cy):max(ay, by, cy) + 1, min(ax, bx, cx):max(ax, bx, cx) + 1]
            wb = ((xs - ax) * (cy - ay) - (cx - ax) * (ys - ay)) / det
            wc = ((bx - ax) * (ys - ay) - (xs - ax) * (by - ay)) / det
            inside = (wb >= -1e-9) & (wc >= -1e-9) & (wb + wc <= 1 + 1e-9)
            plane = z[ay, ax] + wb * (z[by, bx] - z[ay, ax]) + wc * (z[cy, cx] - z[ay, ax])
            worst = max(worst, float(np.abs(z[ys, xs] - plane)[inside].max()))
        self.assertLessEqual(worst, eps + 1e-4)
        self.assertLessEqual(manifest["lods"][0]["measured_error_m"], eps + 1e-4)
        self.assertLess(len(faces), 2 * (cols - 1) * (rows - 1) // 3)

    def test_zero_error_is_full_resolution_and_flat_is_two_triangles(self):
        data = _terrain(40, 50)
        manifest = self._build(data, tile_cells=16, max_errors_m=[0.0, 1e-3])
        self.assertEqual(manifest["lods"][0]["triangles"], 2 * 49 * 39)
        flat = self._build(np.full((65, 65), 3.0, np.float32), tile_cells=32, max_errors_m=[0.01])
        self.assertEqual([t["lods"][0]["triangles"] for t in flat["tiles"]], [2, 2, 2, 2])

    def test_tile_metadata_and_vertex_attributes(self):
        data = _terrain(33, 33)
        manifest = self._build(data, tile_cells=16, spacing_m=0.5, origin="center", max_errors_m=[0.2])
        self.assertEqual(manifest["bounds_m"], [-8.0, -8.0, 8.0, 8.0])
        tile = next(t for t in manifest["tiles"] if t["id"] == "x000_y001")  # north-west
        self.assertEqual(tile["origin_m"], [-8.0, 0.0, 0.0])
        verts, _ = read_ply(os.path.join(manifest["_dir"], tile["lods"][0]["file"]))
        self.assertAlmostEqual(float(verts["x"].min()), 0.0)
        self.assertAlmostEqual(float(verts["y"].max()), 8.0)
        north_west = verts[(verts["x"] == 0) & (verts["y"] == 8.0)][0]
        self.assertAlmostEqual(float(north_west["z"]), float(data[0, 0]), places=4)
        self.assertAlmostEqual(float(north_west["s"]), 0.0)
        self.assertAlmostEqual(float(north_west["t"]), 1.0)
        normal_len = np.sqrt(verts["nx"] ** 2 + verts["ny"] ** 2 + verts["nz"] ** 2)
        self.assertTrue(np.allclose(normal_len, 1.0, atol=1e-5))

    def test_rebuild_removes_stale_tiles(self):
        data = _terrain(65, 65)
        manifest = self._build(data, tile_cells=16, max_errors_m=[0.2, 1.0])
        stale = os.path.join(manifest["_dir"], manifest["tiles"][0]["lods"][1]["file"])
        self.assertTrue(os.path.isfile(stale))
        manifest = self._build(data, tile_cells=16, max_errors_m=[0.2])
        self.assertFalse(os.path.isfile(stale))
        with open(os.path.join(manifest["_dir"], "manifest.json"), encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)["lods"]), 1)

    def test_masks_classify_zones_and_meet_seamlessly(self):
        from PIL import Image

        from awt.masks import ZoneRules

        # West: sea at 0 m, then a lowland, a 72 deg cliff and a high plateau from x = 80.
        cols, rows = 97, 49
        x = np.arange(cols, dtype=np.float32)
        profile = np.where(x < 20, 0.0, np.where(x < 50, 10.0, np.minimum(10 + (x - 50) * 3.0, 100.0)))
        data = np.tile(profile, (rows, 1)).astype(np.float32)
        rules = ZoneRules(water_level_m=1.0, shore_m=2.0, snow_start_m=80, snow_full_m=95,
                          rock_start_deg=35, rock_full_deg=50)
        manifest = self._build(data, tile_cells=32, max_errors_m=[0.1], zones=rules, mask_px=32)
        self.assertEqual([layer["name"] for layer in manifest["mask_layers"]], ["ground", "rock", "snow", "water"])

        def mask(ix, iy):
            tile = next(t for t in manifest["tiles"] if (t["ix"], t["iy"]) == (ix, iy))
            with Image.open(os.path.join(manifest["_dir"], tile["mask"])) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(list(image.size), tile["mask_px"])
                return np.asarray(image).astype(int)

        west, middle, east = mask(0, 1), mask(1, 1), mask(2, 1)
        self.assertTrue(np.array_equal(west[:, -1], middle[:, 0]))
        self.assertTrue(np.array_equal(middle[:, -1], east[:, 0]))
        self.assertTrue(np.array_equal(mask(1, 1)[-1], mask(1, 0)[0]))
        for m in (west, middle, east):
            self.assertTrue(np.all(np.abs(m.sum(axis=2) - 255) <= 2))
        self.assertEqual(tuple(west[5, 2]), (0, 0, 0, 255))  # sea
        self.assertEqual(tuple(middle[5, 4]), (255, 0, 0, 0))  # lowland at x = 36
        self.assertGreater(middle[5, 26, 1], 250)  # cliff at x = 58
        self.assertGreater(east[5, -1, 2], 250)  # plateau at x = 96

        tile = next(t for t in manifest["tiles"] if (t["ix"], t["iy"]) == (2, 1))
        verts, _ = read_ply(os.path.join(manifest["_dir"], tile["lods"][0]["file"]))
        rx, ry = tile["mask_px"]
        north_west = verts[(verts["x"] == 0) & (verts["y"] == verts["y"].max())][0]
        self.assertAlmostEqual(float(north_west["s1"]), 0.5 / rx, places=6)
        self.assertAlmostEqual(float(north_west["t1"]), 1 - 0.5 / ry, places=6)
        self.assertAlmostEqual(float(north_west["s"]), 0.0)

    def test_png16_heightmap_scales_to_height_range(self):
        from PIL import Image

        data = (np.linspace(0, 65535, 17 * 17).reshape(17, 17)).astype(np.uint16)
        path = os.path.join(self.tmp.name, "h.png")
        Image.fromarray(data).save(path)
        hm = load_heightmap(path)
        self.assertEqual(hm.data.dtype, np.uint16)
        self.assertTrue(np.array_equal(hm.data, data))
        params = BuildParams(input_path=path, out_dir=os.path.join(self.tmp.name, "png"),
                             height_min_m=-10, height_max_m=90, tile_cells=16, max_errors_m=[0.0])
        manifest = build(params)
        self.assertAlmostEqual(manifest["source"]["height_range_m"][0], -10.0)
        self.assertAlmostEqual(manifest["source"]["height_range_m"][1], 90.0)


if __name__ == "__main__":
    unittest.main()
