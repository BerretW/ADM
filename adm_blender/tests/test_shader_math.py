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


if __name__ == "__main__":
    unittest.main()
