import json
import os
import tempfile
import unittest
from collections import Counter

import numpy as np

from awt.heightmap import load_heightmap
from awt.material import PAINT_AUTO, Band, Biome, BiomeSurface, TerrainMaterial, default_biomes
from awt.pipeline import BuildParams, build, load_manifest
from awt.ply import read_ply, weight_fields
from awt.roads import Road, rasterize, segments
from awt.texturing import compile_rules, surface_weights


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
        tile_lod = lod[(tile["ix"], tile["iy"])] if isinstance(lod, dict) else lod
        verts, tri = read_ply(os.path.join(manifest["_dir"], tile["lods"][tile_lod]["file"]))
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

    def test_biome_noise_varies_surfaces_without_changing_old_rules(self):
        data = np.zeros((65, 65), np.float32)
        material = TerrainMaterial()
        material.biomes = [Biome("plain", surfaces=[BiomeSurface("grass"),
                            BiomeSurface("soil", slope=Band(20.0, None, 0.0))])]
        original_digest = material.rules_digest()
        material_dict = material.to_dict(None)
        self.assertNotIn("noise", material_dict["biomes"][0])
        self.assertEqual(TerrainMaterial.from_dict(material_dict, None).rules_digest(), original_digest)
        x, y = np.meshgrid(np.arange(65), np.arange(65))
        def sample():
            return surface_weights(compile_rules(material, 1, 65, 65), data, 1, 0, 1, x.ravel(), y.ravel())
        baseline = sample()
        grass, soil = (material.surface_names().index(name) for name in ("grass", "soil"))
        self.assertTrue(np.all(baseline[:, grass] == 1))
        material.biomes[0].noise = 1.0
        varied = sample()
        self.assertGreater(float(np.ptp(varied[:, soil])), 0.3)
        self.assertGreater(float(varied[:, soil].mean()), 0.1)
        self.assertTrue(np.allclose(varied.sum(axis=1), 1))
        self.assertTrue(np.array_equal(varied, sample()))
        self.assertNotEqual(material.rules_digest(), original_digest)
        material.biomes[0].noise = 0.5
        self.assertTrue(np.allclose(sample(), (baseline + varied) / 2))
        material.biomes[0].noise = 0
        self.assertTrue(np.array_equal(baseline, sample()))
        self.assertEqual(material.rules_digest(), original_digest)

    def test_noise_preserves_painted_surface_and_single_surface_biome(self):
        data = np.zeros((33, 33), np.float32)
        material = TerrainMaterial()
        material.biomes = [Biome("plain", surfaces=[BiomeSurface("grass"), BiomeSurface("soil")], noise=1)]
        material.ensure_surface_paint(33, 33)
        gravel = material.surface_names().index("gravel")
        material.surface_paint[:, :] = gravel
        rules = compile_rules(material, 1, 33, 33)
        x = np.arange(33, dtype=float)
        weights = surface_weights(rules, data, 1, 0, 1, x, x)
        self.assertTrue(np.all(weights[:, gravel] == 1))
        material.surface_paint = None
        material.biomes[0].surfaces = [BiomeSurface("grass")]
        rules = compile_rules(material, 1, 33, 33)
        weights = surface_weights(rules, data, 1, 0, 1, x, x)
        self.assertTrue(np.all(weights[:, material.surface_names().index("grass")] == 1))

    def test_noise_is_independent_for_manually_painted_biomes(self):
        data = np.zeros((33, 33), np.float32)
        material = TerrainMaterial()
        entries = [BiomeSurface("grass"), BiomeSurface("soil", slope=Band(20.0, None, 0.0))]
        material.biomes = [Biome("plain", surfaces=entries),
                           Biome("painted", surfaces=entries, auto=False)]
        material.paint_softness_m = 0
        material.ensure_paint(33, 33)
        material.paint[:, 17:] = 1
        x, y = np.array([8., 24.]), np.array([16., 16.])
        def sample():
            return surface_weights(compile_rules(material, 1, 33, 33), data, 1, 0, 1, x, y)
        baseline = sample()
        material.biomes[1].noise = 1
        painted = sample()
        np.testing.assert_array_equal(painted[0], baseline[0])
        self.assertFalse(np.array_equal(painted[1], baseline[1]))
        material.biomes[0].noise = 1
        both = sample()
        self.assertFalse(np.array_equal(both[0], painted[0]))
        np.testing.assert_array_equal(both[1], painted[1])
        material.paint_softness_m = 4
        x, y = np.array([16.]), np.array([16.])
        mixed = sample()
        material.biomes[0].noise = 0
        self.assertFalse(np.allclose(sample(), mixed))
        material.biomes[0].noise = 1
        material.biomes[1].noise = 0
        self.assertFalse(np.allclose(sample(), mixed))

    def test_noise_rejects_out_of_range_and_nonfinite_values(self):
        material = TerrainMaterial()
        for value in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                material.biomes[0].noise = value
                with self.assertRaisesRegex(ValueError, "noise must be 0..1"):
                    material.validate_rules()
                with self.assertRaisesRegex(ValueError, "noise must be 0..1"):
                    TerrainMaterial.from_dict(material.to_dict(None), None)

    def test_noise_build_keeps_matching_weights_between_tiles_and_lods(self):
        data = np.zeros((33, 65), np.float32)
        source = os.path.join(self.tmp.name, "noise.npy")
        np.save(source, data)
        material = TerrainMaterial()
        material.biomes = [Biome("plain", surfaces=[BiomeSurface("grass"), BiomeSurface("soil")], noise=1)]
        params = BuildParams(source, os.path.join(self.tmp.name, "noise"), tile_cells=32,
                             max_errors_m=[0.1, 2.0], texture_error=0.1, texture_detail_m=2, threads=2)
        build(params, material)
        manifest = load_manifest(params.out_dir)
        self.assertGreater(manifest["lods"][0]["triangles"], 4)
        seam, owners = {}, {}
        for tile in manifest["tiles"]:
            for lod in range(2):
                verts, _ = read_ply(os.path.join(manifest["_dir"], tile["lods"][lod]["file"]))
                weights = np.column_stack([verts[f] for f in weight_fields(verts)])
                self.assertTrue(np.all(weights.sum(axis=1) == 255))
                x = verts["x"] + tile["origin_m"][0]
                y = verts["y"] + tile["origin_m"][1]
                for i in np.flatnonzero(np.isclose(x, 32)):
                    key = float(y[i])
                    if key in seam:
                        np.testing.assert_array_equal(seam[key], weights[i])
                    else:
                        seam[key] = weights[i]
                    owners.setdefault(key, set()).add((tile["id"], lod))
        self.assertGreater(sum(len(entries) == 4 for entries in owners.values()), 2)

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

    def test_mixed_lods_have_identical_shared_edges(self):
        data = _terrain(39, 51)
        for texture_error, errors in ((0.0, [3.0, 0.03, 0.8]), (0.1, [3.0, 0.0, 0.8])):
            with self.subTest(texture_error=texture_error, errors=errors):
                manifest = self._build(data, tile_cells=16, max_errors_m=errors,
                                       texture_error=texture_error, texture_detail_m=1.0, threads=2)
                tiles = {(tile["ix"], tile["iy"]): tile for tile in manifest["tiles"]}
                meshes = {}
                for key, tile in tiles.items():
                    for lod in range(3):
                        vertices, faces = read_ply(os.path.join(manifest["_dir"], tile["lods"][lod]["file"]))
                        meshes[key, lod] = (vertices, faces)

                def boundary(key, lod, axis, coordinate):
                    tile = tiles[key]
                    vertices, faces = meshes[key, lod]
                    x = vertices["x"] + tile["origin_m"][0]
                    y = vertices["y"] + tile["origin_m"][1]
                    on_edge = np.isclose((x, y)[axis], coordinate)
                    segments = set()
                    for face in faces:
                        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                            if on_edge[a] and on_edge[b]:
                                points = []
                                for index in (a, b):
                                    points.append((float(x[index]), float(y[index]), float(vertices["z"][index])))
                                segments.add(tuple(sorted(points)))
                    return segments

                for (ix, iy), tile in tiles.items():
                    for delta, axis in (((1, 0), 0), ((0, 1), 1)):
                        neighbor = (ix + delta[0], iy + delta[1])
                        if neighbor not in tiles:
                            continue
                        coordinate = tile["origin_m"][axis] + tile["size_m"][axis]
                        edges = [boundary((ix, iy), lod, axis, coordinate) for lod in range(3)]
                        other_edges = [boundary(neighbor, lod, axis, coordinate) for lod in range(3)]
                        self.assertTrue(edges[0])
                        for edge in edges + other_edges:
                            self.assertEqual(edge, edges[0], f"LOD seam between {(ix, iy)} and {neighbor}")

                self.assertGreater(manifest["lods"][1]["triangles"], manifest["lods"][0]["triangles"])
                for lod, error in enumerate(errors):
                    self.assertLessEqual(manifest["lods"][lod]["measured_error_m"], error + 1e-4)
                    points, faces = _world_mesh(manifest, lod)
                    self._assert_watertight(points, faces, data.shape[1], data.shape[0])
                selection = {key: (key[0] + 2 * key[1]) % 3 for key in tiles}
                points, faces = _world_mesh(manifest, selection)
                self._assert_watertight(points, faces, data.shape[1], data.shape[0])

        flat = self._build(np.full((33, 33), 3.0, np.float32), tile_cells=16,
                           max_errors_m=[0.1, 1.0], texture_error=0.0)
        self.assertTrue(all(lod["triangles"] == 2 for tile in flat["tiles"] for lod in tile["lods"]))

    def _assert_watertight(self, points, faces, cols, rows):
        edges = Counter()
        for a, b, c in faces:
            for u, v in ((a, b), (b, c), (c, a)):
                edges[(min(u, v), max(u, v))] += 1
        self.assertLessEqual(max(edges.values()), 2)
        for (u, v), count in edges.items():
            if count == 1:
                (cu, ru), (cv, rv) = points[u], points[v]
                self.assertTrue((cu == cv and cu in (0, cols - 1)) or (ru == rv and ru in (0, rows - 1)),
                                f"crack at {points[u]}-{points[v]}")

    def test_vertex_weights_follow_biomes_and_meet_seamlessly(self):
        # West: sea at -3 m, then a lowland at 10 m, a 72 deg cliff and a plateau at 100 m from x = 80.
        cols, rows = 97, 49
        x = np.arange(cols, dtype=np.float32)
        profile = np.where(x < 20, -3.0, np.where(x < 50, 10.0, np.minimum(10 + (x - 50) * 3.0, 100.0)))
        data = np.tile(profile, (rows, 1)).astype(np.float32)
        material = TerrainMaterial(biomes=default_biomes(water_m=0.0, shore_m=2.0, snow_start_m=80.0,
                                                         snow_full_m=95.0))
        src = os.path.join(self.tmp.name, "src.npy")
        np.save(src, data)
        plain = BuildParams(input_path=src, out_dir=os.path.join(self.tmp.name, "plain"), tile_cells=32,
                            max_errors_m=[0.1], texture_error=0.0)
        build(plain, material)
        params = BuildParams(input_path=src, out_dir=os.path.join(self.tmp.name, "out"), tile_cells=32,
                             max_errors_m=[0.1], texture_error=0.1, texture_detail_m=1.0)
        build(params, material)
        manifest = load_manifest(params.out_dir)
        names = manifest["texturing"]["surfaces"]
        self.assertEqual(names, material.surface_names())
        self.assertEqual(manifest["texturing"]["rules_digest"], material.rules_digest())
        self.assertGreater(manifest["lods"][0]["triangles"], load_manifest(plain.out_dir)["lods"][0]["triangles"])

        points, faces = _world_mesh(manifest)
        self._assert_watertight(points, faces, cols, rows)

        sp, (bx, by) = manifest["spacing_m"], manifest["bounds_m"][:2]
        seen = {}
        for tile in manifest["tiles"]:
            verts, _ = read_ply(os.path.join(manifest["_dir"], tile["lods"][0]["file"]))
            fields = weight_fields(verts)
            self.assertEqual(len(fields), len(names))
            weights = np.column_stack([verts[f] for f in fields]).astype(int)
            self.assertTrue(np.all(weights.sum(axis=1) == 255))
            ox, oy = tile["origin_m"][:2]
            for vx, vy, w in zip(verts["x"], verts["y"], weights):
                key = (int(round((vx + ox - bx) / sp)), rows - 1 - int(round((vy + oy - by) / sp)))
                if key in seen:  # vertices on tile edges carry the same weights in both tiles
                    self.assertTrue(np.array_equal(seen[key], w), f"seam at {key}")
                seen[key] = w

        def dominant(c0, c1):
            found = {names[int(np.argmax(w))] for (c, _r), w in seen.items() if c0 <= c <= c1}
            self.assertTrue(found)
            return found

        self.assertLessEqual(dominant(0, 15), {"sand", "mud", "algae"})
        self.assertEqual(dominant(25, 45), {"grass"})
        self.assertEqual(dominant(56, 74), {"rock"})
        self.assertEqual(dominant(90, 96), {"snow"})

    def test_surface_paint_blends_over_biomes_and_can_be_removed(self):
        data = np.full((33, 49), 10.0, np.float32)
        material = TerrainMaterial()
        material.paint_softness_m = 2.0
        material.ensure_surface_paint(49, 33)
        soil = material.surface_names().index("soil")
        material.surface_paint[8:25, 10:30] = soil
        rules = compile_rules(material, 1.0, 49, 33)
        weights = surface_weights(rules, data, 1, 0, 1, np.array([3, 10, 20], float),
                                  np.array([16, 16, 16], float))
        self.assertAlmostEqual(weights[2, soil], 1.0, places=5)
        self.assertEqual(weights[0, soil], 0)
        self.assertGreater(weights[1, soil], 0)
        self.assertLess(weights[1, soil], 1)
        self.assertTrue(np.allclose(weights.sum(axis=1), 1))
        material.remove_surface("soil")
        self.assertFalse(material.has_surface_paint())

    def test_road_grade_and_surface_cross_tile_boundaries(self):
        data = np.full((33, 49), 10.0, np.float32)
        src = os.path.join(self.tmp.name, "road.npy")
        np.save(src, data)
        material = TerrainMaterial()
        material.roads = [Road("gravel", 4.0, 2.0, [[4.0, 16.0, 5.0], [44.0, 16.0, 15.0]])]
        params = BuildParams(src, os.path.join(self.tmp.name, "road"), tile_cells=16,
                             max_errors_m=[0.0, 0.5], texture_error=0.1, texture_detail_m=1.0, threads=2)
        build(params, material)
        manifest = load_manifest(params.out_dir)
        self.assertTrue(np.array_equal(np.load(src), data))
        self.assertEqual(manifest["source"]["height_range_m"], [10.0, 10.0])
        self.assertEqual(manifest["edited_height_range_m"], [5.0, 15.0])
        gravel = material.surface_names().index("gravel")
        found = {}
        for tile in manifest["tiles"]:
            verts, _ = read_ply(os.path.join(manifest["_dir"], tile["lods"][0]["file"]))
            x = verts["x"] + tile["origin_m"][0]
            y = verts["y"] + tile["origin_m"][1]
            for col in (16, 32):
                matches = np.flatnonzero((x == col) & (y == 16))
                for i in matches:
                    found.setdefault(col, []).append((float(verts["z"][i]), int(verts[f"w{gravel}"][i])))
        self.assertEqual(set(found), {16, 32})
        for col, entries in found.items():
            for height, weight in entries:
                self.assertAlmostEqual(height, 5 + (col - 4) / 4, places=4)
                self.assertGreater(weight, 245)
        for lod in range(2):
            points, faces = _world_mesh(manifest, lod)
            self._assert_watertight(points, faces, data.shape[1], data.shape[0])

    def test_road_raster_is_bounded_and_continuous_across_blocks(self):
        road = Road("soil", 4, 2, [[0, 100, 0], [300, 100, 10], [519, 100, 20]])
        pieces = segments(road, 1)
        self.assertAlmostEqual(pieces[0][0][2], 0)
        self.assertAlmostEqual(pieces[-1][1][2], 20)
        boundary = {}
        for window, distance, height in rasterize(road, 1, 200, 520):
            self.assertLessEqual(max(distance.shape), 256)
            for col in (255, 256):
                if window[1].start <= col < window[1].stop and window[0].start <= 100 < window[0].stop:
                    row, x = 100 - window[0].start, col - window[1].start
                    boundary[col] = (float(distance[row, x]), float(height[row, x]))
        self.assertEqual(set(boundary), {255, 256})
        self.assertLess(boundary[255][0], 1e-5)
        self.assertLess(boundary[256][0], 1e-5)
        self.assertLess(abs(boundary[256][1] - boundary[255][1]), 0.1)
        i = next(i for i, (_, b) in enumerate(pieces) if np.allclose(b[:2], [300, 100]))
        before, after = pieces[i], pieces[i + 1]
        slope_before = (before[1][2] - before[0][2]) / np.linalg.norm(before[1][:2] - before[0][:2])
        slope_after = (after[1][2] - after[0][2]) / np.linalg.norm(after[1][:2] - after[0][:2])
        self.assertLess(abs(slope_before - slope_after), 0.001)

    def test_paint_places_biome_with_smooth_bridge(self):
        size = 129
        data = np.full((size, size), 10.0, np.float32)
        material = TerrainMaterial()
        material.paint_softness_m = 8.0
        material.ensure_paint(size, size)
        forest = [b.name for b in material.biomes].index("forest")
        yy, xx = np.mgrid[0:size, 0:size]
        material.paint[(xx - 64) ** 2 + (yy - 64) ** 2 <= 20 ** 2] = forest
        rules = compile_rules(material, 1.0, size, size)
        gx = np.arange(0.0, size - 1, 0.25)
        weights = surface_weights(rules, data, 1.0, 0.0, 1.0, gx, np.full_like(gx, 64.0))
        names = material.surface_names()
        self.assertTrue(np.allclose(weights.sum(axis=1), 1.0, atol=1e-4))
        self.assertEqual(names[int(np.argmax(weights[len(gx) // 2]))], "forest_floor")
        self.assertEqual(names[int(np.argmax(weights[0]))], "grass")
        self.assertLess(float(np.abs(np.diff(weights, axis=0)).max()), 0.04)  # no hard edge
        grass = weights[: len(gx) // 2, names.index("grass")]
        fading = (grass > 0.2) & (grass < 0.95)
        self.assertTrue(np.all(np.diff(grass)[fading[1:]] < -1e-4))  # fades evenly, no terraces
        with self.assertRaises(ValueError):
            compile_rules(material, 1.0, size + 1, size)  # paint made for another heightmap
        material.paint[:] = PAINT_AUTO
        self.assertFalse(material.has_paint())

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
