#!/usr/bin/env python3
"""Verify independent golden vectors for ADM terrain Macro Color."""

import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads(
    (ROOT / "fixtures" / "expectations" / "terrain_macro_color_v1.json")
    .read_text(encoding="utf-8")
)


def decode_srgb(value):
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def evaluate(vector):
    weights = [max(0.0, value) for value in vector["weights"]]
    total = sum(weights)
    if total <= 0.0:
        weights = [1.0, 0.0, 0.0, 0.0]
    else:
        weights = [value / total for value in weights]
    sample = vector["sampleSrgb"]
    macro = [decode_srgb(value) for value in sample[:3]]
    alpha = sample[3] if len(sample) == 4 else 1.0
    strength = vector["strength"]
    influence = vector["layerInfluence"]
    output = [0.0, 0.0, 0.0]
    for index in range(4):
        amount = strength * influence[index]
        if vector["mode"] != "MULTIPLY":
            amount *= alpha
        base = vector["layerColors"][index]
        if vector["mode"] == "LERP":
            color = [(1.0 - amount) * base[c] + amount * macro[c] for c in range(3)]
        else:
            color = [
                base[c] * (1.0 - amount + amount * macro[c])
                for c in range(3)
            ]
        for channel in range(3):
            output[channel] += weights[index] * color[channel]
    return output


def evaluate_coordinates(vector):
    if vector["projection"] == "LOCAL_UV":
        source = vector["uv"]
    else:
        position, origin = vector["position"], vector["origin"]
        source = [position[0] - origin[0], position[2] - origin[1]]
    return [
        source[axis] * vector["scale"][axis] + vector["offset"][axis]
        for axis in range(2)
    ]


class TerrainMacroColorVectors(unittest.TestCase):
    def test_blend_modes_and_linear_color_vectors(self):
        self.assertEqual(VECTORS["extension"], "ADM_terrain_macro_color_v1@1.0.0")
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate(vector)
                for value, expected in zip(actual, vector["expected"]):
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(value, expected, places=12)

    def test_local_shared_and_floating_origin_coordinates(self):
        for vector in VECTORS["coordinates"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate_coordinates(vector)
                for value, expected in zip(actual, vector["expected"]):
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(value, expected, places=12)
        self.assertEqual(
            evaluate_coordinates(VECTORS["coordinates"][1]),
            evaluate_coordinates(VECTORS["coordinates"][2]),
        )


if __name__ == "__main__":
    unittest.main()
