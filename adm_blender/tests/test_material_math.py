import itertools
import math
import unittest

from adm_blender.core.material_math import (blend_normals, combine_ao, effective_height, evaluate_layer_ao,
                                            height_blend_weights, parallax_occlusion, parallax_offset,
                                            select_channel)


class MaterialMathTest(unittest.TestCase):
    def test_channel_selection_inversion_and_missing_height(self):
        self.assertEqual(select_channel((0.2, 0.6, 0.8, 1.0), 2), 0.8)
        self.assertAlmostEqual(select_channel((0.2, 0.6), 1, True), 0.4)
        self.assertIsNone(select_channel(None))
        self.assertEqual(effective_height(None), 0.5)
        self.assertEqual(effective_height((0.8, 0.2), 1, True, 2.0, -0.1), 1.0)
        with self.assertRaises(ValueError):
            select_channel((0.2,), 1)

    def test_layer_ao_uses_strength_and_neutral_missing_maps(self):
        ao = evaluate_layer_ao(
            (0.25, 0.75),
            ((0.2,), None),
            strengths=(1.0, 0.0),
        )
        self.assertAlmostEqual(ao, 0.8)
        self.assertAlmostEqual(combine_ao(ao, 0.5, 0.5), 0.6)
        self.assertAlmostEqual(evaluate_layer_ao((0.3, 0.7), (None, None)), 1.0)

    def test_blended_normals_are_normalized_and_missing_maps_are_flat(self):
        result = blend_normals((0.5, 0.5), ((1.0, 0.0, 0.0), None))
        self.assertAlmostEqual(sum(value * value for value in result), 1.0)
        self.assertGreater(result[0], 0.0)
        self.assertGreater(result[2], 0.0)
        self.assertEqual(blend_normals((1.0,), (None,)), (0.0, 0.0, 1.0))

    def test_height_blending_preserves_required_invariants(self):
        base = (0.2, 0.3, 0.5)
        self.assertEqual(height_blend_weights(base, (0.1, 0.9, 0.4), strength=0), list(base))
        self.assertEqual(height_blend_weights(base, (0.5, 0.5, 0.5)), list(base))
        self.assertEqual(height_blend_weights((0, 1, 0), (0.1, 0.9, 0.4)), [0.0, 1.0, 0.0])
        self.assertEqual(height_blend_weights((0, 0, 0), (0.1, 0.9, 0.4)), [1.0, 0.0, 0.0])
        self.assertEqual(height_blend_weights(base, (0.1, 0.9, 0.4), present=(False,) * 3), list(base))
        missing = height_blend_weights(base, (0.1, 0.9, 0.4), present=(True, False, True))
        neutral = height_blend_weights(base, (0.1, 0.5, 0.4))
        self.assertEqual(missing, neutral)
        self.assertEqual(missing[1] > 0, True)
        blended = height_blend_weights(base, (0.1, 0.9, 0.4), transition=0.1)
        self.assertGreater(blended[1], base[1])
        self.assertAlmostEqual(sum(blended), 1.0)
        self.assertTrue(all(value >= 0 and math.isfinite(value) for value in blended))

    def test_height_blending_is_layer_order_independent(self):
        weights = (0.1, 0.35, 0.55)
        heights = (0.2, 0.9, 0.4)
        reference = height_blend_weights(weights, heights, 0.15, 0.8)
        for order in itertools.permutations(range(3)):
            result = height_blend_weights([weights[i] for i in order],
                                          [heights[i] for i in order], 0.15, 0.8)
            reordered = [result[order.index(i)] for i in range(3)]
            for actual, expected in zip(reordered, reference):
                self.assertAlmostEqual(actual, expected, places=14)

    def test_invalid_blend_inputs_are_rejected(self):
        for args in (((-0.1, 1.1), (0.2, 0.4)),
                     ((0.5, 0.5), (float("nan"), 0.4))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                height_blend_weights(*args)
        with self.assertRaises(ValueError):
            height_blend_weights((0.5, 0.5), (0.2, 0.4), transition=0)

    def test_parallax_direction_and_grazing_angle_are_bounded(self):
        self.assertEqual(parallax_offset((0.4, 0.5), (0, 0, 1), 0.9), (0.0, 0.0))
        offset = parallax_offset((0.4, 0.5), (1, 0, 0.01), 1.0, scale=0.1)
        self.assertLess(offset[0], 0)
        self.assertEqual(parallax_offset((0.4, 0.5), (1, 0, -1), 1.0), (0.0, 0.0))
        self.assertTrue(all(math.isfinite(value) and abs(value) <= 1 for value in offset))

    def test_pom_interpolates_surface_intersection_and_respects_step_bounds(self):
        offset, steps = parallax_occlusion(
            (0.5, 0.5), (0.5, 0.0, 1.0), lambda _uv: 1.0, min_steps=4, max_steps=12
        )
        self.assertEqual(offset, (0.0, 0.0))
        self.assertEqual(steps, 0)
        offset, steps = parallax_occlusion(
            (0.5, 0.5), (0.8, 0.0, 0.2), lambda _uv: 0.5,
            scale=0.1, min_steps=5, max_steps=16,
        )
        self.assertGreaterEqual(steps, 5)
        self.assertLessEqual(steps, 16)
        self.assertLess(offset[0], 0.0)
        self.assertEqual(parallax_occlusion(
            (0.5, 0.5), (0.8, 0.0, 0.2), lambda _uv: 0.5, scale=0.0
        ), ((0.0, 0.0), 0))


if __name__ == "__main__":
    unittest.main()
