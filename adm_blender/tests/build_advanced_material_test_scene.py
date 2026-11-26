"""Generate a deterministic Blender scene for the four advanced layered profiles.

Run:
  blender -b --factory-startup --python adm_blender/tests/build_advanced_material_test_scene.py -- output.blend
"""

import os
import sys
from itertools import product

import bpy
import numpy as np
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import adm_blender


def make_image(name, fn, size=64):
    image = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    px = np.zeros((size * size * 4,), dtype=np.float32)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            px[i:i + 4] = fn(x, y, size)
    image.pixels.foreach_set(px)
    image.update()
    image.pack()
    return image


def main(output):
    adm_blender.register()
    from adm_blender.core import constants as K
    from adm_blender.blender import materials

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100

    red = make_image("Procedural Red Height", lambda x, y, s: (0.25, 0.25, 0.25, 1.0))
    high = make_image("Procedural High Height", lambda x, y, s:
                      (1.0 if (x // 8 + y // 8) % 2 else 0.55, 0.0, 0.0, 1.0))
    normal = make_image("Procedural Normal", lambda x, y, s:
                        (0.5 + x / s * 0.1, 0.5 + y / s * 0.1, 1.0, 1.0))
    mask = make_image("Procedural Blend Mask", lambda x, y, s: (0.5, 0.5, 0.0, 0.0))

    profiles = (
        (K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V1),
        (K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V2),
        (K.SHADER_TWO_LAYER[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V1),
        (K.SHADER_LAYERED[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V2),
    )
    for (index, (shader_id, version)), height_blend in product(enumerate(profiles), (False, True)):
        kind = K.OFFICIAL_SHADER_KINDS[(shader_id, version)]
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.7, location=((index - 1.5) * 1.8, 1.0 if height_blend else -1.0, 0.7))
        obj = bpy.context.object
        obj.name = f"{shader_id}@{version} {'Height' if height_blend else 'Classic'}"
        attr = obj.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
        attr.data.foreach_set("color", np.tile((0.5, 0.5, 0.0, 0.0), len(attr.data)).ravel())
        mat = bpy.data.materials.new(obj.name)
        obj.data.materials.append(mat)
        materials.convert_to_adm_material(mat)
        mat.adm.shader = kind
        mat.adm.shader_version = version
        mat.adm.vertex_controls_enabled = True
        count = K.SHADER_LAYERED_HEIGHT_COUNTS[(shader_id, version)]
        if mat.adm.params.get("blend_mask") is not None:
            mat.adm.params["blend_mask"].image = mask
        for i in range(count):
            mat.adm.params[f"layer{i}_base_color"].value_vec = (
                (0.8, 0.12, 0.04, 1.0) if i % 2 == 0 else (0.04, 0.15, 0.8, 1.0))
            mat.adm.params[f"layer{i}_height_texture"].image = high if i % 2 else red
            mat.adm.params[f"layer{i}_height_scale"].value_f = 1.0
            mat.adm.params[f"layer{i}_height_bias"].value_f = 0.0
            mat.adm.params[f"layer{i}_ao_strength"].value_f = 1.0
            mat.adm.params[f"layer{i}_normal"].image = normal
        mat.adm.params["height_blend_enabled"].value_bool = height_blend
        mat.adm.params["height_blend_transition"].value_f = 0.2
        mat.adm.params["height_blend_strength"].value_f = 1.0
        mat.adm.params["parallax_mode"].value_enum = "PARALLAX_OCCLUSION"
        mat.adm.params["parallax_min_steps"].value_f = 8
        mat.adm.params["parallax_max_steps"].value_f = 32
        materials.refresh_shader_preview(mat)

    bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 0.0, 0.0))
    bpy.ops.object.light_add(type="AREA", location=(-4.0, -5.0, 8.0))
    bpy.context.object.data.energy = 2000
    bpy.ops.object.camera_add(location=(0.0, -8.0, 5.0))
    camera = bpy.context.object
    camera.data.lens = 35
    camera.rotation_euler = (Vector((0.0, 0.0, 0.7)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    scene.render.filepath = "//ADM_Advanced_Material_Test_Scene.png"

    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=output)
    print(f"Generated advanced layered material scene: {output}")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    main(args[0] if args else os.path.join(REPO, "dist", "ADM_Advanced_Material_Test_Scene.blend"))
