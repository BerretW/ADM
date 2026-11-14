import unittest

from adm_blender.core import shader_math as M


class ShaderMathTests(unittest.TestCase):
    def test_vertex_control_palette_index_and_tint_color_space(self):
        index = M.tint_palette_index
        self.assertEqual([index(value, 0.0, 4) for value in (0.0, 0.25, 0.5, 0.75, 1.0)],
                         [0, 1, 2, 3, 3])
        self.assertEqual(index(0.5, -1.0, 4), 1)
        self.assertEqual(index(0.0, -1024.0, 4), 0)
        self.assertEqual(index(0.0, 1024.0, 4), 3)
        with self.assertRaises(ValueError):
            index(0.0, 0.0, 0)

        base = (0.25, 0.5, 0.75, 0.8)
        palette = (0.5, 1.0, 0.0, 0.5)
        self.assertEqual(M.vertex_tint(base, palette, "MULTIPLY"),
                         (0.25 * 0.21404114048223255, 0.5, 0.0, 0.4))
        self.assertEqual(M.vertex_tint(base, palette, "REPLACE"),
                         (0.21404114048223255, 1.0, 0.0, 0.8))
        with self.assertRaises(ValueError):
            M.vertex_tint(base, palette, "ADD")

    def test_vertex_control_normal_strength_exact_samples(self):
        expected_xz = {
            0.0: (0.0, 1.0),
            0.25: (0.1961161351, 0.9805806757),
            0.5: (0.3713906764, 0.9284766909),
            0.75: (0.5144957554, 0.8574929257),
            1.0: (0.6246950476, 0.7808688094),
        }
        for value, expected in expected_xz.items():
            with self.subTest(color0_green=value):
                normal = M.vertex_control_normal((1.0, 0.5, 1.0), 0.8, value, 1.0)
                self.assertAlmostEqual(normal[0], expected[0], places=9)
                self.assertAlmostEqual(normal[1], 0.0, places=9)
                self.assertAlmostEqual(normal[2], expected[1], places=9)
                self.assertAlmostEqual(sum(c * c for c in normal), 1.0, places=9)
        self.assertIsNone(M.vertex_control_normal(None, 1.0, 0.5, 1.0))
        self.assertAlmostEqual(M.vertex_control_normal((1, 0.5, 1), 0.8, 0.5, 2)[0],
                               0.6246950476, places=9)

    def test_vertex_control_reflectivity_and_wetness(self):
        self.assertEqual(M.vertex_control_f0((0.04, 0.2, 0.6), 0.25, 2.0), (0.02, 0.1, 0.3))
        color, roughness, f0, wetness = M.vertex_control_wetness(
            (0.8, 0.4, 0.2), 0.6, (0.04, 0.2, 0.6), 0.0, 0.0
        )
        self.assertEqual((color, roughness, f0, wetness), ((0.8, 0.4, 0.2), 0.6, (0.04, 0.2, 0.6), 0.0))

        color, roughness, f0, wetness = M.vertex_control_wetness(
            (0.8, 0.4, 0.2), 0.6, (0.04, 0.2, 0.6), 0.25, 0.25
        )
        self.assertEqual(wetness, 0.5)
        for actual, expected in zip(color, (0.74, 0.37, 0.185)):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(roughness, 0.35)
        water_f0 = ((1.333 - 1.0) / (1.333 + 1.0)) ** 2
        for base, effective in zip((0.04, 0.2, 0.6), f0):
            expected_coat = water_f0 + (1.0 - water_f0) ** 2 * base
            self.assertAlmostEqual(effective, base + (expected_coat - base) * 0.5)

        color, roughness, f0, wetness = M.vertex_control_wetness(
            (0.8, 0.4, 0.2), 0.6, 0.04, 0.0, 1.0
        )
        self.assertEqual(wetness, 1.0)
        self.assertEqual(color, (0.68, 0.34, 0.17))
        self.assertAlmostEqual(roughness, 0.1)
        self.assertAlmostEqual(f0, water_f0 + (1.0 - water_f0) ** 2 * 0.04)

    def test_schlick_endpoints_and_thin_glass(self):
        self.assertAlmostEqual(M.schlick(1.0, 1.5), 0.04)
        self.assertAlmostEqual(M.schlick(0.0, 1.5), 1.0)
        color, alpha = M.glass(1.0, 1.5, 0.9, (0.8, 0.9, 1.0), (1.0, 1.0, 1.0))
        self.assertAlmostEqual(color[0], 0.808)
        self.assertAlmostEqual(color[1], 0.904)
        self.assertEqual(color[2], 1.0)
        self.assertAlmostEqual(alpha, 0.136)

    def test_cutout_and_straight_alpha_boundaries(self):
        self.assertTrue(M.cutout_keep(0.5, 1.0, 0.5))
        self.assertFalse(M.cutout_keep(0.499, 1.0, 0.5))
        self.assertEqual(M.straight_alpha((1, 0, 0), 0.25, (0, 0, 1)), (0.25, 0.0, 0.75))

    def test_emissive_srgb_and_foliage_orientation(self):
        self.assertAlmostEqual(M.emissive((1, 1, 1), (0.5, 0.5, 0.5))[0], 0.21404114048223255)
        self.assertEqual(M.foliage_color((1, 1, 1), (0.5, 0.25, 0.0), 0.5, False), (1, 1, 1))
        self.assertEqual(M.foliage_color((1, 1, 1), (0.5, 0.25, 0.0), 0.5, True),
                         (0.75, 0.625, 0.5))

    def test_terrain_normalization_and_zero_mask_fallback(self):
        self.assertEqual(M.terrain_weights((0.2, 0.3, 0.1, 0.4)), (0.2, 0.3, 0.1, 0.4))
        self.assertEqual(M.terrain_weights((0, 0, 0, 0)), (1, 0, 0, 0))
        color = M.terrain_color((1, 0, 0, 0), ((0.2, 0.3, 0.4), (0, 0, 0), (0, 0, 0), (0, 0, 0)))
        self.assertEqual(color, (0.2, 0.3, 0.4))

    def test_wrap_and_triplanar_weights(self):
        self.assertAlmostEqual(M.wrapped_diffuse(-1.0, 0.5), 0.0)
        self.assertAlmostEqual(M.wrapped_diffuse(0.0, 0.5), 1.0 / 3.0)
        self.assertEqual(M.triplanar_weights((1, 0, 0)), (1.0, 0.0, 0.0))
        self.assertEqual(M.triplanar_weights((0, 0, 0)), (0.0, 1.0, 0.0))

    def test_brick_mortar_mix_and_dirt(self):
        color, rough = M.brick((0.8, 0.1, 0.1), (0.2, 0.4, 0.6), 1.0, 0.75, 0.9)
        self.assertEqual(color, (0.2, 0.4, 0.6))
        self.assertAlmostEqual(rough, 0.9)
        color, rough = M.brick((0.8, 0.1, 0.1), (0.2, 0.4, 0.6), 0.25, 0.75, 0.95, dirt_mask=1.0)
        self.assertAlmostEqual(rough, 0.8)
        self.assertAlmostEqual(color[0], (0.8 * 0.75 + 0.2 * 0.25) * 0.35)

    def test_mortar_mask_running_bond(self):
        px = M.mortar_mask_pixels(64, 64, rows=4, columns=2, mortar=0.25)
        self.assertEqual(px.shape, (64, 64))
        self.assertEqual(px[0, 16], 1.0)    # bottom horizontal joint
        self.assertEqual(px[8, 16], 0.0)    # brick centre, row 0
        self.assertEqual(px[8, 0], 1.0)     # vertical joint at u=0 in row 0
        self.assertEqual(px[24, 0], 0.0)    # row 1 is offset by half a brick
        self.assertEqual(px[24, 16], 1.0)   # ...so its joint sits at u=0.25


if __name__ == "__main__":
    unittest.main()
