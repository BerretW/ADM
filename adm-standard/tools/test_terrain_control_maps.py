#!/usr/bin/env python3
"""Verify independent golden vectors for ADM terrain Control Maps."""

import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads(
    (ROOT / "fixtures" / "expectations" / "terrain_control_maps_v1.json").read_text(encoding="utf-8")
)
FILTERING = json.loads(
    (ROOT / "fixtures" / "expectations" / "terrain_control_map_filtering_v1.json")
    .read_text(encoding="utf-8")
)


def normalize(values):
    positive = [max(0.0, value) for value in values]
    total = sum(positive)
    if total == 0.0:
        return [1.0, 0.0, 0.0, 0.0]
    return [value / total for value in positive]


def evaluate(vector):
    base = normalize(vector["base"])
    mode = vector["mode"]
    sample = vector["sample"]
    strength = vector.get("strength", 1.0)
    order = vector.get("channelOrder", [0, 1, 2, 3])
    if mode == "VERTEX_ONLY" or sample is None:
        return base
    if mode == "TEXTURE_RGB_IMPLICIT":
        red, green, blue = sample
        decoded = normalize([max(0.0, 1.0 - red - green - blue), red, green, blue])
    else:
        decoded = normalize(sample)
    control = [decoded[index] for index in order]
    if mode in ("TEXTURE_RGBA", "TEXTURE_RGB_IMPLICIT"):
        result = [(1.0 - strength) * old + strength * new for old, new in zip(base, control)]
    elif mode == "VERTEX_MULTIPLY":
        product = normalize([old * new for old, new in zip(base, control)])
        result = [(1.0 - strength) * old + strength * new for old, new in zip(base, product)]
    elif mode == "VERTEX_OVERRIDE":
        mask = vector.get("overrideMask", [1.0] * 4)
        result = [old * (1.0 - strength * weight) + new * strength * weight
                  for old, new, weight in zip(base, control, mask)]
    elif mode == "VERTEX_MODULATE":
        result = [old * (1.0 - strength + strength * 4.0 * new)
                  for old, new in zip(base, control)]
    else:
        raise AssertionError(f"unregistered vector mode {mode!r}")
    return normalize(result)


def evaluate_coordinates(vector):
    scale, offset = vector["scale"], vector["offset"]
    if vector["mapping"] == "UV":
        source = vector["uv"]
    else:
        position, origin = vector["position"], vector["origin"]
        source = [position[0] - origin[0], position[2] - origin[1]]
    return [source[axis] * scale[axis] + offset[axis] for axis in range(2)]


class TerrainControlMapVectors(unittest.TestCase):
    def test_shared_filtering_checker_vector_is_balanced(self):
        self.assertEqual(FILTERING["extension"], VECTORS["extension"])
        width, height = FILTERING["width"], FILTERING["height"]
        self.assertGreaterEqual(width, 2)
        self.assertGreaterEqual(height, 2)
        self.assertEqual(width % 2, 0)
        self.assertEqual(height % 2, 0)
        red_sum = sum((x + y) % 2 for y in range(height) for x in range(width))
        red = red_sum / (width * height)
        green = 1.0 - red
        self.assertEqual(
            FILTERING["expectedLinearAverage"],
            [red, green, 0.0, 0.0],
        )

    def test_registered_mode_vectors(self):
        self.assertEqual(VECTORS["extension"], "ADM_terrain_control_map_v1@1.0.0")
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate(vector)
                for value, expected in zip(actual, vector["expected"]):
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(value, expected, places=12)
                self.assertAlmostEqual(sum(actual), 1.0, places=12)

    def test_uv_world_origin_and_floating_origin_vectors(self):
        for vector in VECTORS["coordinates"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate_coordinates(vector)
                for value, expected in zip(actual, vector["expected"]):
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(value, expected, places=12)
        first, shifted = VECTORS["coordinates"][:2]
        self.assertEqual(evaluate_coordinates(first), evaluate_coordinates(shifted))


if __name__ == "__main__":
    unittest.main()
