"""Pure-Python tests for bounded BVH parsing and cautious humanoid analysis."""

from pathlib import Path
import unittest
from unittest import mock

from adm_blender.core.bvh import (
    BvhError,
    analyze_skeleton,
    parse_bvh_file,
    parse_bvh_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "bvh"


class BvhParserTests(unittest.TestCase):
    def test_parser_preserves_hierarchy_channel_order_values_and_end_sites(self):
        motion = parse_bvh_file(FIXTURES / "euler_order_end_site.bvh")

        self.assertEqual([node.name for node in motion.nodes], ["Hips", "Spine", "Head"])
        self.assertEqual([node.parent for node in motion.nodes], [None, 0, 1])
        self.assertEqual(motion.nodes[1].channels, ("Yrotation", "Xrotation", "Zrotation"))
        self.assertEqual(motion.nodes[2].end_sites, ((0.0, 4.0, 0.0),))
        self.assertEqual(motion.frames[1][6:], (30.0, 40.0, 50.0))
        self.assertAlmostEqual(motion.frame_rate, 30.0, places=7)
        self.assertAlmostEqual(motion.duration, motion.frame_time)

    def test_cmu_style_joint_names_produce_suggestions_not_false_compatibility(self):
        analysis = analyze_skeleton(parse_bvh_file(FIXTURES / "cmu_names.bvh"))

        self.assertEqual(analysis["mapping"]["Hips"], "hips")
        self.assertEqual(analysis["mapping"]["LowerBack"], "spine")
        self.assertEqual(analysis["mapping"]["LClavicle"], "leftShoulder")
        self.assertEqual(analysis["mapping"]["RHumerus"], "rightUpperArm")
        self.assertEqual(analysis["profile"], None)
        self.assertFalse(analysis["semanticCompatible"])
        self.assertTrue(analysis["missingRoles"])

    def test_unknown_skeleton_is_not_claimed_as_humanoid(self):
        text = """HIERARCHY
ROOT Root
{
 OFFSET 0 0 0
 CHANNELS 0
}
MOTION
Frames: 1
Frame Time: 0.1

"""
        analysis = analyze_skeleton(parse_bvh_text(text))

        self.assertIsNone(analysis["profile"])
        self.assertEqual(analysis["confidence"], "low")

    def test_invalid_frame_time_and_frame_value_count_are_rejected(self):
        prefix = """HIERARCHY
ROOT Root
{
 OFFSET 0 0 0
 CHANNELS 1 Xposition
}
MOTION
"""
        with self.assertRaisesRegex(BvhError, "Frame Time"):
            parse_bvh_text(prefix + "Frames: 1\nFrame Time: 0\n0\n")
        with self.assertRaisesRegex(BvhError, "trailing token"):
            parse_bvh_text(prefix + "Frames: 1\nFrame Time: 0.1\n0 1\n")
        with self.assertRaisesRegex(BvhError, "expected 2 frames"):
            parse_bvh_text(prefix + "Frames: 2\nFrame Time: 0.1\n0\n")

    def test_html_download_is_reported_as_not_bvh(self):
        with self.assertRaisesRegex(BvhError, "HTML, not BVH"):
            parse_bvh_text("<!DOCTYPE html><html><body>Not found</body></html>")

    def test_duplicate_names_channels_and_malformed_hierarchy_are_rejected(self):
        duplicate_channel = """HIERARCHY
ROOT Root { OFFSET 0 0 0 CHANNELS 2 Xrotation Xrotation }
MOTION Frames: 1 Frame Time: 0.1 0 0
"""
        duplicate_name = """HIERARCHY
ROOT Root { OFFSET 0 0 0 CHANNELS 0 JOINT Root { OFFSET 0 1 0 CHANNELS 0 } }
MOTION Frames: 1 Frame Time: 0.1
"""
        missing_channels = """HIERARCHY
ROOT Root { OFFSET 0 0 0 }
MOTION Frames: 1 Frame Time: 0.1
"""
        bad_close = """HIERARCHY
ROOT Root { OFFSET 0 0 0 CHANNELS 0
MOTION Frames: 1 Frame Time: 0.1
"""
        cases = (
                (duplicate_channel, "duplicate channels"),
                (duplicate_name, "duplicate joint name"),
                (missing_channels, "missing CHANNELS"),
                (bad_close, "expected"))
        for text, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(BvhError, message):
                    parse_bvh_text(text)

    def test_node_depth_frame_and_sample_limits_are_enforced(self):
        simple = """HIERARCHY
ROOT Root { OFFSET 0 0 0 CHANNELS 1 Xposition }
MOTION Frames: 1 Frame Time: 0.1
0
"""
        with mock.patch("adm_blender.core.bvh.MAX_NODES", 0):
            with self.assertRaisesRegex(BvhError, "exceeds 0 joints"):
                parse_bvh_text(simple)
        with mock.patch("adm_blender.core.bvh.MAX_FRAMES", 0):
            with self.assertRaisesRegex(BvhError, "frame count"):
                parse_bvh_text(simple)
        with mock.patch("adm_blender.core.bvh.MAX_SAMPLES", 0):
            with self.assertRaisesRegex(BvhError, "sample safety limit"):
                parse_bvh_text(simple)

        nested = """HIERARCHY
ROOT Root { OFFSET 0 0 0 CHANNELS 0 JOINT Child { OFFSET 0 1 0 CHANNELS 0 } }
MOTION Frames: 1 Frame Time: 0.1
"""
        with mock.patch("adm_blender.core.bvh.MAX_DEPTH", 0):
            with self.assertRaisesRegex(BvhError, "nesting exceeds 0"):
                parse_bvh_text(nested)

    def test_nonfinite_and_oversized_input_are_rejected(self):
        nonfinite = """HIERARCHY
ROOT Root { OFFSET NaN 0 0 CHANNELS 0 }
MOTION Frames: 1 Frame Time: 0.1
"""
        with self.assertRaisesRegex(BvhError, "finite number"):
            parse_bvh_text(nonfinite)
        with mock.patch("adm_blender.core.bvh.MAX_FILE_BYTES", 8):
            with self.assertRaisesRegex(BvhError, "8-byte limit"):
                parse_bvh_text(" " * 9)


if __name__ == "__main__":
    unittest.main()
