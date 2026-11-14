"""Generate a reproducible Blender scene containing all registered Core 20 shader previews.

Run: blender -b --factory-startup --python adm_blender/tests/build_material_test_scene.py -- output.blend
"""

import os
import sys

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import adm_blender


def make_image(name, size, pixel_fn):
    image = bpy.data.images.new(name, size[0], size[1], alpha=True, float_buffer=True)
    pixels = np.array([pixel_fn(x, y) for y in range(size[1]) for x in range(size[0])], dtype=np.float32)
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    return image


def add_label(text, location):
    data = bpy.data.curves.new(f"Label_{text}", "FONT")
    data.body = text
    data.align_x = "CENTER"
    data.size = 0.22
    obj = bpy.data.objects.new(f"Label_{text}", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location


def main(output):
    adm_blender.register()
    from adm_blender.blender import materials
    from adm_blender.core import constants as K

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100

    texture = make_image("Core20_Checker", (8, 8), lambda x, y:
                         ((0.75, 0.5, 0.25, 1.0) if (x + y) % 2 else (0.25, 0.5, 0.75, 1.0)))
    palette = make_image("Core20_Tint_Palette", (4, 1), lambda x, _y:
                         ((0.8, 0.2, 0.1, 1.0), (0.1, 0.7, 0.2, 1.0),
                          (0.1, 0.3, 0.9, 1.0), (0.8, 0.7, 0.1, 1.0))[x])
    samples = [(key, kind) for key, kind in K.OFFICIAL_SHADER_KINDS.items() if key != K.SHADER_INTERACTIVE]
    for index, (key, kind) in enumerate(samples):
        x = (index % 5 - 2) * 2.4
        y = (1.5 - index // 5) * 2.4
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.85, location=(x, y, 0.85))
        obj = bpy.context.object
        obj.name = f"MaterialTest_{kind}"
        obj.data.name = f"MaterialTestMesh_{kind}"
        color0 = obj.data.color_attributes.new(name="COLOR_0", type="FLOAT_COLOR", domain="CORNER")
        color0.data.foreach_set("color", np.tile((0.25, 1.0, 1.0, 0.25), len(color0.data)).ravel())
        color1 = obj.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
        color1.data.foreach_set("color", np.tile((0.9, 0.1, 0.7, 0.3), len(color1.data)).ravel())

        mat = bpy.data.materials.new(f"MaterialTest_{kind}")
        obj.data.materials.append(mat)
        materials.convert_to_adm_material(mat)
        fallback = materials.principled_of(mat)
        fallback.inputs["Base Color"].default_value = (0.65, 0.55, 0.4, 1.0)
        fallback.inputs["Metallic"].default_value = 0.15
        fallback.inputs["Roughness"].default_value = 0.45
        mat.adm.shader = kind
        materials.sync_official_shader_params(mat, key)
        schema = {parameter["name"]: parameter for parameter in K.OFFICIAL_SHADERS[key]}
        for value in mat.adm.params:
            parameter = schema[value.name]
            value.use = True
            if parameter["type"] == "TEXTURE":
                value.image = texture
            elif parameter["type"] == "F32":
                value.value_f = float(parameter["default"])
            elif parameter["type"] == "BOOL":
                value.value_bool = bool(parameter["default"])
            else:
                vector = list(value.value_vec)
                defaults = parameter["default"]
                vector[:len(defaults)] = defaults
                value.value_vec = vector
        mat.adm.vertex_tint_palette = palette
        mat.adm.vertex_controls_enabled = True
        add_label(kind, (x, y - 1.1, 0.02))

    bpy.ops.mesh.primitive_plane_add(size=13.0, location=(0.0, 0.0, 0.0))
    bpy.context.object.name = "MaterialTest_Floor"
    bpy.ops.object.light_add(type="AREA", location=(0.0, -4.0, 10.0))
    bpy.context.object.data.energy = 2200
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 8.0
    bpy.ops.object.camera_add(location=(0.0, -9.0, 12.0))
    camera = bpy.context.object
    from mathutils import Vector
    camera.rotation_euler = (Vector((0.0, 0.0, 0.0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 40
    scene.camera = camera
    scene.render.filepath = "//ADM_Core20_Material_Test_Scene.png"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Core20_Material_Test_World")
    scene.world.color = (0.08, 0.08, 0.08)

    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=output)
    print(f"Generated {len(samples)} shader swatches: {output}")


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    destination = arguments[0] if arguments else os.path.join(REPO, "dist", "ADM_Core20_Material_Test_Scene.blend")
    main(destination)
