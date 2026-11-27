import itertools
import math
import unittest

import numpy as np

from adm_blender.core.material_math import (blend_normals, combine_ao, effective_height, evaluate_layer_ao,
                                            height_blend_weights, parallax_occlusion, parallax_offset,
                                            normal_from_macro_frame, normal_to_macro_frame,
                                            reconstruct_bc5_normal, reoriented_normal,
                                            select_channel, terrain_control_map_uv,
                                            terrain_control_map_weights, terrain_macro_color,
                                            terrain_macro_color_uv, terrain_macro_normal,
                                            terrain_macro_normal_frame, terrain_macro_normal_uv)


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
        self.assertTrue(all(math.isfinite(value) for value in offset))
        self.assertAlmostEqual(math.hypot(*offset), 0.1)

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
        self.assertAlmostEqual(math.hypot(*offset), 0.05)
        self.assertEqual(parallax_occlusion(
            (0.5, 0.5), (0.8, 0.0, 0.2), lambda _uv: 0.5, scale=0.0
        ), ((0.0, 0.0), 0))

    def test_pom_uses_unclamped_view_cosine_for_adaptive_steps(self):
        _, steps = parallax_occlusion((0, 0), (1, 0, 0.001), lambda _uv: 0.0,
                                     scale=0.1, min_steps=4, max_steps=100)
        self.assertEqual(steps, 100)

    def test_control_map_weight_modes_channel_order_and_zero_fallback(self):
        base = (0.4, 0.3, 0.2, 0.1)
        sample = (0.1, 0.2, 0.3, 0.4)
        self.assertEqual(
            terrain_control_map_weights(base, sample, "TEXTURE_RGBA", strength=0.5),
            [0.25, 0.25, 0.25, 0.25],
        )
        self.assertEqual(
            terrain_control_map_weights(base, (0.2, 0.3, 0.1), "TEXTURE_RGB_IMPLICIT",
                                        channel_order=(1, 0, 3, 2)),
            [0.2, 0.4, 0.1, 0.3],
        )
        multiplied = terrain_control_map_weights(
            (0.5, 0.3, 0.2, 0), sample, "VERTEX_MULTIPLY", strength=0.5
        )
        np.testing.assert_allclose(multiplied, (0.3970588235, 0.3264705882, 0.2764705882, 0), atol=1e-9)
        overridden = terrain_control_map_weights(
            base, sample, "VERTEX_OVERRIDE", strength=0.5, override_mask=(1, 0, 0.5, 1)
        )
        np.testing.assert_allclose(overridden, (0.2439024390, 0.2926829268, 0.2195121951, 0.2439024390),
                                   atol=1e-9)
        modulated = terrain_control_map_weights(base, sample, "VERTEX_MODULATE", strength=0.5)
        np.testing.assert_allclose(modulated, (0.3111111111, 0.3, 0.2444444444, 0.1444444444), atol=1e-9)
        self.assertEqual(terrain_control_map_weights((0, 0, 0, 0), None, "VERTEX_ONLY"),
                         [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(terrain_control_map_weights(base, (0, 0, 0, 0), "TEXTURE_RGBA"),
                         [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(terrain_control_map_weights(base, (0.25,) * 4, "VERTEX_MODULATE"), list(base))

    def test_macro_color_modes_use_linearized_samples_and_layer_influence(self):
        colors = ((0.8, 0.2, 0.1), (0.1, 0.5, 0.4), (0.2, 0.3, 0.4), (0.9, 0.9, 0.9))
        weights = (0.25, 0.75, 0.0, 0.0)
        sample = (1.0, 0.5, 0.25, 0.5)
        influence = (1.0, 0.5, 1.0, 1.0)
        results = {
            mode: terrain_macro_color(colors, weights, sample, mode, 0.8, influence)
            for mode in ("MULTIPLY", "TINT", "LERP")
        }
        self.assertNotEqual(results["MULTIPLY"], results["TINT"])
        self.assertNotEqual(results["TINT"], results["LERP"])
        np.testing.assert_allclose(results["MULTIPLY"],
                                   (0.275, 0.275667816691624, 0.192122652344018), atol=1e-12)
        np.testing.assert_allclose(results["TINT"],
                                   (0.275, 0.350333908345812, 0.258561326172009), atol=1e-12)
        np.testing.assert_allclose(results["LERP"],
                                   (0.43, 0.383510285120558, 0.267719022042889), atol=1e-12)
        self.assertTrue(all(0.0 <= value <= 1.0 for result in results.values() for value in result))

    def test_macro_color_neutral_and_invalid_inputs(self):
        colors = ((0.8, 0.2, 0.1), (0.1, 0.5, 0.4), (0.2, 0.3, 0.4), (0.9, 0.9, 0.9))
        weights = (0.25, 0.75, 0.0, 0.0)
        base = terrain_macro_color(colors, weights, None)
        np.testing.assert_allclose(base, (0.275, 0.425, 0.325), atol=1e-12)
        for mode, neutral in (
            ("MULTIPLY", (1.0, 1.0, 1.0, 1.0)),
            ("TINT", (1.0, 1.0, 1.0, 0.0)),
            ("LERP", (1.0, 0.0, 0.0, 0.0)),
        ):
            np.testing.assert_allclose(
                terrain_macro_color(colors, weights, neutral, mode),
                base, atol=1e-12,
            )
            np.testing.assert_allclose(
                terrain_macro_color(colors, weights, (0.0, 0.0, 0.0), mode, strength=0.0),
                base, atol=1e-12,
            )
            np.testing.assert_allclose(
                terrain_macro_color(colors, weights, (0.0, 0.0, 0.0), mode,
                                    layer_influence=(0.0, 0.0, 0.0, 0.0)),
                base, atol=1e-12,
            )
        with self.assertRaises(ValueError):
            terrain_macro_color(colors, weights, (0.0, 0.0), "MULTIPLY")
        with self.assertRaises(ValueError):
            terrain_macro_color(colors, weights, (0.0, 0.0, 0.0), "SCREEN")

    def test_macro_color_local_and_shared_world_coordinates(self):
        local = terrain_macro_color_uv(
            projection="LOCAL_UV", uv=(0.25, 0.75), scale=(2.0, 0.5), offset=(0.1, -0.2),
        )
        self.assertEqual(local, (0.6, 0.175))
        world = terrain_macro_color_uv(
            projection="SHARED_WORLD_XZ", position=(12.0, 4.0, 18.0), origin=(2.0, 8.0),
            scale=(0.5, 2.0), offset=(0.1, -0.2),
        )
        shifted = terrain_macro_color_uv(
            projection="SHARED_WORLD_XZ", position=(12.0 - 1000.0, 4.0, 18.0 + 500.0),
            origin=(2.0 - 1000.0, 8.0 + 500.0), scale=(0.5, 2.0), offset=(0.1, -0.2),
        )
        np.testing.assert_allclose(world, (5.1, 19.8), atol=1e-12)
        self.assertEqual(world, shifted)

    def test_macro_normal_reconstruction_rnm_and_missing_map(self):
        np.testing.assert_allclose(
            reconstruct_bc5_normal((0.8, 0.5), 0.5),
            (0.3, 0.0, math.sqrt(0.91)),
            atol=1e-12,
        )
        np.testing.assert_allclose(
            reconstruct_bc5_normal((1.0, 1.0)),
            (math.sqrt(0.5), math.sqrt(0.5), 0.0),
            atol=2e-8,
        )
        np.testing.assert_allclose(
            reoriented_normal((0.0, 0.6, 0.8), reconstruct_bc5_normal((0.8, 0.5))),
            (0.6, 0.48, 0.64),
            atol=1e-12,
        )
        self.assertEqual(reoriented_normal((0.0, 0.0, -1.0), (0.0, 0.0, 1.0)),
                         (0.0, 0.0, -1.0))

        layer_normals = ((0.0, 0.0, 1.0),) * 4
        mapped = terrain_macro_normal(
            layer_normals, (0.25,) * 4, (1.0, 0.5), layer_influence=(1.0, 0.0, 0.0, 0.0),
        )
        np.testing.assert_allclose(mapped, (1.0 / math.sqrt(10.0), 0.0, 3.0 / math.sqrt(10.0)),
                                   atol=1e-12)
        missing = terrain_macro_normal(
            ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), None, None),
            (0.5, 0.5, 0.0, 0.0), None,
        )
        np.testing.assert_allclose(missing, (math.sqrt(0.5), 0.0, math.sqrt(0.5)), atol=1e-12)
        degenerate = terrain_macro_normal(
            ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), None, None),
            (0.5, 0.5, 0.0, 0.0), (0.5, 0.5),
        )
        self.assertEqual(degenerate, (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            reconstruct_bc5_normal((float("nan"), 0.5))
        with self.assertRaises(ValueError):
            terrain_macro_normal(layer_normals, (0.25,) * 4, (1.0, 0.5), strength=1.1)

    def test_macro_normal_projection_frame_and_world_transform(self):
        local = terrain_macro_normal_uv(
            projection="LOCAL_UV", uv=(0.25, 0.75), scale=(2.0, 0.5), offset=(0.1, -0.2),
        )
        world = terrain_macro_normal_uv(
            projection="SHARED_WORLD_XZ", position=(12.0, 4.0, 18.0), origin=(2.0, 8.0),
            scale=(0.5, 2.0), offset=(0.1, -0.2),
        )
        self.assertEqual(local, (0.6, 0.175))
        self.assertEqual(world, (5.1, 19.8))

        frame = terrain_macro_normal_frame((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(frame, ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))
        fallback = terrain_macro_normal_frame((0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0))
        self.assertEqual(fallback, ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
        fallback_u = terrain_macro_normal_frame((0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(fallback_u, fallback)
        tangent_normal = normal_to_macro_frame((0.0, 0.0, 1.0), frame)
        self.assertEqual(tangent_normal, (0.0, 1.0, 0.0))
        self.assertEqual(normal_from_macro_frame(tangent_normal, frame), (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            terrain_macro_normal_frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))

    def test_control_map_coordinates_are_world_origin_invariant(self):
        world = terrain_control_map_uv(
            mapping="WORLD_PLANAR_XZ", position=(1_000_003.0, 0.0, -2_000_002.0),
            origin=(1_000_000.0, -2_000_000.0), scale=(0.25, -0.5), offset=(0.1, 0.2),
        )
        shifted = terrain_control_map_uv(
            mapping="WORLD_PLANAR_XZ", position=(3.0, 0.0, -2.0),
            origin=(0.0, 0.0), scale=(0.25, -0.5), offset=(0.1, 0.2),
        )
        self.assertEqual(world, (0.85, 1.2))
        self.assertEqual(world, shifted)
        self.assertEqual(
            terrain_control_map_uv(mapping="UV", uv=(0.25, 0.5), scale=(2, 4), offset=(0.1, -0.2)),
            (0.6, 1.8),
        )
        with self.assertRaises(ValueError):
            terrain_control_map_uv(mapping="WORLD_PLANAR_XZ", position=(float("nan"), 0, 0))

    def test_control_map_rejects_bad_channels_and_nonfinite_samples(self):
        for sample, mode, order in (
            ((0.2, 0.3, 0.5), "TEXTURE_RGBA", (0, 1, 2, 3)),
            ((0.2, 0.3, float("nan"), 0.2), "TEXTURE_RGBA", (0, 1, 2, 3)),
            ((0.2, 0.3, 0.4, 0.5), "TEXTURE_RGBA", (0, 1, 1, 3)),
        ):
            with self.subTest(sample=sample, mode=mode), self.assertRaises(ValueError):
                terrain_control_map_weights((0.25,) * 4, sample, mode, channel_order=order)


if __name__ == "__main__":
    unittest.main()
