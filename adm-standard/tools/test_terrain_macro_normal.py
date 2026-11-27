#!/usr/bin/env python3
"""Verify independent golden vectors for ADM terrain Macro Normal."""

import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads(
    (ROOT / "fixtures" / "expectations" / "terrain_macro_normal_v1.json")
    .read_text(encoding="utf-8")
)


def normalize(vector):
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-12:
        raise ValueError("zero vector")
    return [value / length for value in vector]


def reconstruct(sample, strength=1.0):
    x, y = (2.0 * value - 1.0 for value in sample[:2])
    radius = math.hypot(x, y)
    if radius > 1.0:
        x, y = x / radius, y / radius
    x, y = x * strength, y * strength
    return normalize([x, y, math.sqrt(max(0.0, 1.0 - x * x - y * y))])


def compose(base, detail):
    base = normalize(base)
    detail = normalize(detail)
    tangent = [base[0], base[1], base[2] + 1.0]
    if math.hypot(*tangent) <= 1e-8:
        return base
    signed_detail = [-detail[0], -detail[1], detail[2]]
    dot = sum(a * b for a, b in zip(tangent, signed_detail))
    result = [
        tangent[i] * dot - signed_detail[i] * tangent[2]
        for i in range(3)
    ]
    if math.hypot(*result) <= 1e-8:
        return base
    return normalize(result)


def evaluate(vector):
    if "layerNormals" in vector:
        normals = vector["layerNormals"]
        weights = vector["weights"]
        sample = vector["sample"]
        strength = vector.get("strength", 1.0)
        influence = vector.get("layerInfluence", [1.0] * 4)
        adjusted = normals if sample is None else [
            compose(normal or [0.0, 0.0, 1.0], reconstruct(sample, strength * amount))
            for normal, amount in zip(normals, influence)
        ]
        total = sum(weights)
        weights = [1.0, 0.0, 0.0, 0.0] if total <= 0 else [
            weight / total for weight in weights
        ]
        return normalize([
            sum(weights[i] * adjusted[i][axis] for i in range(4))
            for axis in range(3)
        ])
    return compose(
        vector.get("base", [0.0, 0.0, 1.0]),
        reconstruct(vector["sample"], vector.get("strength", 1.0)),
    )


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


def evaluate_frame(vector):
    normal = normalize(vector["geometricNormal"])
    du, dv = vector["positionDu"], vector["positionDv"]

    def project(source):
        scale = sum(source[i] * normal[i] for i in range(3))
        return [source[i] - normal[i] * scale for i in range(3)]

    tangent = project(du)
    fallback_tangent = math.hypot(*tangent) <= 1e-12
    if fallback_tangent:
        axis = [1.0, 0.0, 0.0] if abs(normal[0]) < 0.9 else [0.0, 0.0, 1.0]
        tangent = project(axis)
    tangent = normalize(tangent)
    bitangent_source = project(dv)
    if fallback_tangent or math.hypot(*bitangent_source) <= 1e-12:
        handedness = 1.0
    else:
        bitangent_source = normalize(bitangent_source)
        cross = [
            tangent[1] * bitangent_source[2] - tangent[2] * bitangent_source[1],
            tangent[2] * bitangent_source[0] - tangent[0] * bitangent_source[2],
            tangent[0] * bitangent_source[1] - tangent[1] * bitangent_source[0],
        ]
        handedness = -1.0 if sum(cross[i] * normal[i] for i in range(3)) < 0 else 1.0
    cross_nt = [
        normal[1] * tangent[2] - normal[2] * tangent[1],
        normal[2] * tangent[0] - normal[0] * tangent[2],
        normal[0] * tangent[1] - normal[1] * tangent[0],
    ]
    bitangent = [handedness * value for value in cross_nt]
    return [tangent, bitangent, normal]


class TerrainMacroNormalVectors(unittest.TestCase):
    def test_bc5_rnm_missing_map_and_layer_weight_vectors(self):
        self.assertEqual(VECTORS["extension"], "ADM_terrain_macro_normal_v1@1.0.0")
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate(vector)
                for value, expected in zip(actual, vector["expected"]):
                    self.assertTrue(math.isfinite(value))
                    self.assertAlmostEqual(value, expected, places=12)

    def test_projection_coordinates_and_floating_origin(self):
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

    def test_tangent_frame_and_degenerate_derivative_vectors(self):
        for vector in VECTORS["frames"]:
            with self.subTest(vector=vector["name"]):
                actual = evaluate_frame(vector)
                for actual_axis, expected_axis in zip(actual, vector["expected"]):
                    for value, expected in zip(actual_axis, expected_axis):
                        self.assertTrue(math.isfinite(value))
                        self.assertAlmostEqual(value, expected, places=12)


if __name__ == "__main__":
    unittest.main()
