"""Verify reference-scene procedural image pixels survive project reload."""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy

from adm_blender.tests.build_advanced_material_test_scene import make_image


def main():
    bpy.ops.wm.read_homefile(use_empty=True)
    image = make_image("procedural_test", lambda x, y, size: (0.25, 0.5, 0.75, 1.0))
    image.use_fake_user = True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "image.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        pixels = list(bpy.data.images["procedural_test"].pixels[:4])
        assert all(abs(actual - expected) < 0.02
                   for actual, expected in zip(pixels, (0.25, 0.5, 0.75, 1.0))), pixels
    print("RESULT: PASS", flush=True)


if __name__ == "__main__":
    main()
