import math
import unittest

from adm_blender.core.terrain import adaptive_partition, sector_cells


def connected(region, cells_x, cells_y):
    remaining = set(region)
    if not remaining:
        return False
    visited = {remaining.pop()}
    frontier = list(visited)
    while frontier:
        cell = frontier.pop()
        row, column = divmod(cell, cells_x)
        neighbors = []
        if row:
            neighbors.append(cell - cells_x)
        if column:
            neighbors.append(cell - 1)
        if column + 1 < cells_x:
            neighbors.append(cell + 1)
        if row + 1 < cells_y:
            neighbors.append(cell + cells_x)
        for neighbor in neighbors:
            if neighbor in remaining:
                remaining.remove(neighbor)
                visited.add(neighbor)
                frontier.append(neighbor)
    return not remaining


class TerrainPartitionTests(unittest.TestCase):
    def setUp(self):
        self.samples_x = 13
        self.samples_y = 9
        self.width_m = 12.0
        self.depth_m = 8.0
        self.heights = [
            math.sin(x * 0.4) + math.cos(y * 0.6) + 0.05 * x * y
            for y in range(self.samples_y) for x in range(self.samples_x)
        ]

    def partition(self, **overrides):
        settings = dict(
            target_area_m2=48.0, min_area_m2=30.0, max_area_m2=70.0,
            sensitivity=0.8, natural_boundary=0.7, max_cells_per_tile=64,
        )
        settings.update(overrides)
        return adaptive_partition(
            self.heights, self.samples_x, self.samples_y, self.width_m, self.depth_m, **settings)

    def test_adaptive_is_complete_connected_and_deterministic(self):
        first = self.partition()
        second = self.partition()
        expected = set(range((self.samples_x - 1) * (self.samples_y - 1)))
        self.assertEqual(first, second)
        self.assertEqual(set(cell for region in first for cell in region), expected)
        self.assertEqual(sum(map(len, first)), len(expected))
        self.assertTrue(all(30 <= len(region) <= 64 for region in first))
        self.assertTrue(all(connected(region, self.samples_x - 1, self.samples_y - 1)
                            for region in first))
        self.assertTrue(any(
            (max(cell % 12 for cell in region) - min(cell % 12 for cell in region) + 1)
            * (max(cell // 12 for cell in region) - min(cell // 12 for cell in region) + 1) > len(region)
            for region in first))

    def test_hybrid_regions_stay_inside_regular_sectors(self):
        sectors = sector_cells(self.samples_x, self.samples_y, self.width_m, self.depth_m, 6, 4)
        partition = []
        for sector in sectors:
            partition.extend(self.partition(
                target_area_m2=12, min_area_m2=8, max_area_m2=18, max_cells_per_tile=18,
                allowed_cells=sector))
        self.assertEqual(set(cell for region in partition for cell in region),
                         set(range(12 * 8)))
        self.assertTrue(all(connected(region, 12, 8) for region in partition))
        self.assertEqual(len(set(cell for region in partition for cell in region)),
                         sum(len(region) for region in partition))
        for region in partition:
            self.assertTrue(any(set(region).issubset(sector) for sector in sectors))

    def test_single_region_and_infeasible_area_limits(self):
        regions = adaptive_partition([0, 0, 0, 0, 0, 0, 0, 0, 0], 3, 3, 2, 2,
                                     target_area_m2=4, min_area_m2=1, max_area_m2=4)
        self.assertEqual(regions, [[0, 1, 2, 3]])
        with self.assertRaisesRegex(ValueError, "cannot partition"):
            adaptive_partition([0] * 9, 3, 3, 2, 2, target_area_m2=3,
                               min_area_m2=3, max_area_m2=3)
        with self.assertRaisesRegex(ValueError, "smaller than one terrain grid cell"):
            adaptive_partition([0] * 9, 3, 3, 2, 2, target_area_m2=4,
                               min_area_m2=0.1, max_area_m2=0.5)
        with self.assertRaisesRegex(ValueError, "region limit"):
            self.partition(max_regions=2, target_area_m2=12)

    def test_rejects_empty_or_out_of_range_sectors(self):
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            sector_cells(3, 3, 2, 2, 0, 1)
        with self.assertRaisesRegex(ValueError, "valid terrain cells"):
            adaptive_partition(self.heights, self.samples_x, self.samples_y,
                               self.width_m, self.depth_m, 48, 30, 70,
                               allowed_cells=[-1])

    def test_rejects_invalid_area_and_nonfinite_data(self):
        with self.assertRaisesRegex(ValueError, "minimum area"):
            self.partition(min_area_m2=80, max_area_m2=70)
        heights = list(self.heights)
        heights[0] = float("nan")
        with self.assertRaisesRegex(ValueError, "NaN or infinity"):
            adaptive_partition(heights, self.samples_x, self.samples_y, self.width_m, self.depth_m,
                              48, 30, 70)


if __name__ == "__main__":
    unittest.main()
