#!/usr/bin/env python3
"""Verify independent golden vectors for ADM 2.0.0 COLOR_1 shader profiles."""

import json
import math
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "adm-standard" / "fixtures"
REGISTRY = json.loads((ROOT / "adm-standard" / "shaders" / "registry.json").read_text(encoding="utf-8"))
EXPECTED = json.loads(
    (FIXTURES / "expectations" / "shader_masks_v2.json").read_text(encoding="utf-8")
)
CONTRACT = (ROOT / "adm-standard" / "shaders" / "ADM_shader_vertex_masks_v2.md").read_text(encoding="utf-8")


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


def mix(a, b, weight):
    return a * (1.0 - weight) + b * weight


def srgb_to_linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def overlay_alpha(base_alpha, texture_alpha, weight):
    target = base_alpha if texture_alpha is None else base_alpha * texture_alpha
    return mix(base_alpha, target, weight)


def normalized_weights(raw):
    total = sum(raw)
    return [value / total for value in raw] if total else [1.0, 0.0, 0.0, 0.0]


class ShaderVertexMaskVectors(unittest.TestCase):
    def test_profile_channel_maps_cover_every_v2_registry_profile(self):
        registry_v2 = {
            f'{entry["id"]}@{entry["version"]}': entry
            for entry in REGISTRY["shaders"] if entry["version"] == "2.0.0"
        }
        fixture_profiles = {profile["id"]: profile for profile in EXPECTED["profiles"]}
        self.assertEqual(set(fixture_profiles), set(registry_v2))
        self.assertEqual(len(fixture_profiles), 20)
        self.assertEqual(EXPECTED["maskSamples"], [0.0, 0.25, 0.5, 0.75, 1.0])

        documented = {}
        operation_pattern = re.compile(
            r"\((?:`)?(surface|factor|multiply|color|coverage|contrast|normal|layer)"
            r"(?:\s+\d+)?(?:`)?(?:,|\))"
        )
        for line in CONTRACT.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells or "@2.0.0`" not in cells[0]:
                continue
            profile_id = cells[0].strip("`")
            documented[profile_id] = [
                operation_pattern.search(cell).group(1) if operation_pattern.search(cell) else None
                for cell in cells[1:5]
            ]
        self.assertEqual(documented, {profile_id: profile["operations"]
                                      for profile_id, profile in fixture_profiles.items()})

        for profile_id, profile in fixture_profiles.items():
            with self.subTest(profile=profile_id):
                self.assertEqual(len(profile["operations"]), 4)
                parameters = {parameter["name"]: parameter for parameter in registry_v2[profile_id]["parameters"]}
                for channel in "rgba":
                    strength = parameters[f"color1_{channel}_strength"]
                    self.assertEqual(strength["default"], 1.0)
                    for sample in EXPECTED["maskSamples"]:
                        self.assertEqual(clamp(sample * strength["default"]), sample)

    def test_surface_overlay_srgb_alpha_and_scalar_outputs(self):
        vector = EXPECTED["vectors"]["surfaceOverlay"]
        weight = clamp(vector["mask"] * vector["strength"])
        tex = [srgb_to_linear(value) for value in vector["textureSrgb"]]
        overlay = [a * b for a, b in zip(vector["overlayColor"], tex)]
        expected_color = [mix(base, target, weight)
                          for base, target in zip(vector["baseColor"][:3], overlay)]
        expected_alpha = overlay_alpha(vector["baseColor"][3], vector["textureAlpha"], weight)
        expected = vector["expected"]
        self.assertAlmostEqual(weight, expected["effectiveMask"], places=7)
        for actual, target in zip(expected_color + [expected_alpha], expected["baseColor"]):
            self.assertAlmostEqual(actual, target, places=7)
        self.assertAlmostEqual(
            mix(vector["baseMetallic"], vector["overlayMetallic"], weight),
            expected["metallic"], places=7,
        )
        self.assertAlmostEqual(
            mix(vector["baseRoughness"], vector["overlayRoughness"], weight),
            expected["roughness"], places=7,
        )
        without_texture = EXPECTED["vectors"]["surfaceOverlayWithoutTexture"]
        self.assertAlmostEqual(
            overlay_alpha(without_texture["baseAlpha"], without_texture["textureAlpha"],
                          without_texture["effectiveMask"]),
            without_texture["expectedAlpha"], places=7,
        )

    def test_factor_multiply_coverage_and_contrast(self):
        vectors = EXPECTED["vectors"]
        factor = vectors["factor"]
        self.assertAlmostEqual(
            mix(factor["current"], factor["target"], factor["effectiveMask"]),
            factor["expected"], places=7,
        )

        multiply = vectors["multiply"]
        self.assertAlmostEqual(
            multiply["current"] * mix(1.0, multiply["target"], multiply["effectiveMask"]),
            multiply["expected"], places=7,
        )

        coverage = vectors["coverage"]
        self.assertAlmostEqual(
            coverage["current"] * coverage["effectiveMask"], coverage["expected"], places=7,
        )

        contrast = vectors["contrast"]
        actual = []
        for value in contrast["baseColor"]:
            target = clamp(0.5 + (value - 0.5) * contrast["value"])
            actual.append(mix(value, target, contrast["effectiveMask"]))
        for value, expected in zip(actual, contrast["expected"]):
            self.assertAlmostEqual(value, expected, places=7)

    def test_normal_blend_is_normalized(self):
        vector = EXPECTED["vectors"]["normal"]
        decoded = [2.0 * value - 1.0 for value in vector["textureRgb"]]
        blended = [mix(base, detail, vector["effectiveMask"])
                   for base, detail in zip(vector["base"], decoded)]
        length = math.sqrt(sum(value * value for value in blended))
        actual = [value / length for value in blended]
        for value, expected in zip(actual, vector["expected"]):
            self.assertAlmostEqual(value, expected, places=7)

    def test_layer_weights_and_layer_color(self):
        vector = EXPECTED["vectors"]["layerWeights"]
        raw = [clamp(mask * strength) * texture
               for mask, strength, texture in zip(vector["mask"], vector["strength"], vector["blendMask"])]
        weights = normalized_weights(raw)
        for value, expected in zip(weights, vector["expectedWeights"]):
            self.assertAlmostEqual(value, expected, places=7)
        color = [
            sum(weights[index] * vector["layerColors"][index][channel] for index in range(4))
            for channel in range(3)
        ]
        for value, expected in zip(color, vector["expectedColor"]):
            self.assertAlmostEqual(value, expected, places=7)
        zero = EXPECTED["vectors"]["zeroLayerWeights"]
        zero_weights = normalized_weights([0.0, 0.0, 0.0, 0.0])
        self.assertEqual(zero_weights, zero["expectedWeights"])

    def test_color1_precedes_color0_wetness(self):
        vector = EXPECTED["vectors"]["color1ThenColor0Wetness"]
        wetness = clamp(vector["wetnessMask"] + vector["wetnessOffset"])
        self.assertAlmostEqual(wetness, vector["expectedWetness"], places=7)
        factor = 1.0 - 0.15 * wetness
        color = [component * factor for component in vector["color1Color"]]
        for value, expected in zip(color, vector["expectedColor"]):
            self.assertAlmostEqual(value, expected, places=7)


if __name__ == "__main__":
    unittest.main()
