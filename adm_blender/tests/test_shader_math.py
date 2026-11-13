import unittest

from adm_blender.core import shader_math as M


class ShaderMathTests(unittest.TestCase):
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
