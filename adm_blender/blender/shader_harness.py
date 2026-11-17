"""Interactive Blender scene for inspecting PBR metallic-roughness 2.1.0 masks."""

import bpy
from mathutils import Vector

from ..core import constants as K
from .materials import convert_to_adm_material, principled_of, refresh_shader_preview
from .shader_preview import PREVIEW_WEAR_AMOUNT

_HARNESS_TAG = "adm_pbr_edge_wear_harness"
_HARNESS_SCENE_NAME = "ADM Edge Wear Test 2.1.0"
_HARNESS_REVISION = "2.1.0-runtime-wear"


def _mesh_object(collection, name, vertices, faces, location, color1, uv_by_vertex=None):
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    if uv_by_vertex is not None:
        layer = mesh.uv_layers.new(name="UVMap")
        for loop_index, loop in enumerate(mesh.loops):
            layer.data[loop_index].uv = uv_by_vertex[loop.vertex_index]
    attr = mesh.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    for item in attr.data:
        item.color = color1
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    return obj


def _cube(collection, name, size, location, color1, material):
    half = size * 0.5
    vertices = [
        (-half, -half, -half), (half, -half, -half), (half, half, -half), (-half, half, -half),
        (-half, -half, half), (half, -half, half), (half, half, half), (-half, half, half),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    obj = _mesh_object(collection, name, vertices, faces, location, color1)
    uv = obj.data.uv_layers.new(name="UVMap")
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for face in obj.data.polygons:
        for index, loop_index in enumerate(face.loop_indices):
            uv.data[loop_index].uv = corners[index]
    obj.data.materials.append(material)
    return obj


def _plane(collection, name, location, color1, material, size=1.8, normal_image=None):
    half = size * 0.5
    obj = _mesh_object(
        collection, name,
        [(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)],
        [(0, 1, 2, 3)], location, color1,
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    )
    obj.data.materials.append(material)
    if normal_image is not None:
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "Harness Normal Map"
        texture.image = normal_image
        texture.interpolation = "Linear"
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UVMap"
        links.new(uv.outputs["UV"], texture.inputs["Vector"])
        normal = nodes.new("ShaderNodeNormalMap")
        normal.name = "Harness Normal Map Decode"
        links.new(texture.outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], principled_of(material).inputs["Normal"])
    return obj


def _normal_step_image():
    width, height = 64, 16
    image = bpy.data.images.new("ADM Harness Normal Edge", width, height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    pixels = []
    for _y in range(height):
        for x in range(width):
            pixels.extend((0.5, 0.5, 1.0, 1.0) if x < width // 2 else (1.0, 0.5, 0.5, 1.0))
    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    return image


def _base_color_image():
    size = 64
    image = bpy.data.images.new("ADM Harness Painted Surface", size, size, alpha=True)
    pixels = []
    for y in range(size):
        for x in range(size):
            variation = 0.75 if ((x // 8) + (y // 8)) % 2 else 1.0
            pixels.extend((0.12 * variation, 0.18 * variation, 0.25 * variation, 1.0))
    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    return image


def _initialize_preview_wear(obj):
    if PREVIEW_WEAR_AMOUNT not in obj:
        obj[PREVIEW_WEAR_AMOUNT] = 1.0
        obj.id_properties_ui(PREVIEW_WEAR_AMOUNT).update(
            min=0.0, max=1.0, description="Blender-only simulation of the engine wear amount")


def _material(name, base_color, dirt=False):
    material = bpy.data.materials.new(name)
    convert_to_adm_material(material)
    bsdf = principled_of(material)
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.65
    bsdf.inputs["Roughness"].default_value = 0.42
    material.adm.shader = "CORE"
    material.adm.shader_version = K.SHADER_PROFILE_EDGE_WEAR
    if dirt:
        _set_param(material, "color1_g_color", (0.18, 0.11, 0.055))
        _set_param(material, "color1_g_roughness", 0.95)
    else:
        _set_param(material, "color1_b_color", (0.86, 0.82, 0.72))
        _set_param(material, "color1_b_metallic", 0.85)
        _set_param(material, "color1_b_roughness", 0.28)
    return material


def _set_param(material, name, value):
    param = material.adm.params[name]
    param.use = True
    if isinstance(value, (tuple, list)):
        current = list(param.value_vec)
        current[:len(value)] = value
        param.value_vec = current
    else:
        param.value_f = value


def _label(collection, material, name, body, location):
    curve = bpy.data.curves.new(f"{name} Text", "FONT")
    curve.body = body
    curve.size = 0.18
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(material)
    return obj


def _camera_and_light(scene, collection):
    camera_data = bpy.data.cameras.new("Harness Camera")
    camera = bpy.data.objects.new("Harness Camera", camera_data)
    collection.objects.link(camera)
    camera.location = (0.8, -13.5, 9.0)
    target = Vector((0.8, 0.0, 0.6))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 48
    scene.camera = camera

    light_data = bpy.data.lights.new("Harness Key Light", "AREA")
    light_data.energy = 1800
    light_data.shape = "DISK"
    light_data.size = 8.0
    light = bpy.data.objects.new("Harness Key Light", light_data)
    collection.objects.link(light)
    light.location = (0.0, -4.0, 8.0)
    light.rotation_euler = (Vector((0.8, 0.0, 0.4)) - light.location).to_track_quat("-Z", "Y").to_euler()


def _create_harness_scene():
    scene = bpy.data.scenes.new(_HARNESS_SCENE_NAME)
    collection = bpy.data.collections.new("ADM Edge Wear Samples")
    scene.collection.children.link(collection)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100

    world = bpy.data.worlds.new("ADM Edge Wear World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.12, 0.14, 0.18, 1.0)
    background.inputs["Strength"].default_value = 0.35
    scene.world = world

    wear_material = _material("ADM 2.1 Edge Wear", (0.12, 0.18, 0.25))
    wear_material.adm.pick_base_color = _base_color_image()
    flat_material = _material("ADM 2.1 Flat Control", (0.12, 0.18, 0.25))
    normal_material = _material("ADM 2.1 Normal-map Wear", (0.12, 0.18, 0.25))
    dirt_material = _material("ADM 2.1 Per-instance Dirt", (0.42, 0.38, 0.31), dirt=True)

    geometry = _cube(
        collection, "Wear | convex geometry", 1.8, (-3.8, 0.0, 0.9), (0.0, 0.0, 1.0, 0.0),
        wear_material,
    )
    bevel = geometry.modifiers.new("Visible rounded edges", "BEVEL")
    bevel.width = 0.16
    bevel.segments = 4
    flat = _plane(collection, "Control | flat mask only", (-1.35, 0.0, 0.025), (0.0, 0.0, 1.0, 0.0),
                  flat_material)
    normal_image = _normal_step_image()
    normal = _plane(collection, "Wear | normal-map transition", (1.1, 0.0, 0.025),
                    (0.0, 0.0, 1.0, 0.0), normal_material, normal_image=normal_image)
    for obj in (geometry, flat, normal):
        _initialize_preview_wear(obj)
    dirt_a = _cube(
        collection, "Dirt | instance A", 1.4, (3.7, 0.0, 0.7), (0.0, 1.0, 0.0, 0.0), dirt_material,
    )
    dirt_b = _cube(
        collection, "Dirt | instance B", 1.4, (5.45, 0.0, 0.7), (0.0, 1.0, 0.0, 0.0), dirt_material,
    )
    for material in (wear_material, flat_material, normal_material, dirt_material):
        refresh_shader_preview(material)

    label_material = bpy.data.materials.new("Harness Labels")
    label_material.diffuse_color = (0.85, 0.9, 1.0, 1.0)
    _label(collection, label_material, "Label | geometry", "CONVEX GEOMETRY", (-4.65, -1.35, 0.02))
    _label(collection, label_material, "Label | flat", "FLAT MASK CONTROL", (-2.25, -1.35, 0.02))
    _label(collection, label_material, "Label | normal map", "NORMAL-MAP EDGE", (0.15, -1.35, 0.02))
    _label(collection, label_material, "Label | dirt", "PER-INSTANCE DIRT", (3.65, -1.35, 0.02))
    _camera_and_light(scene, collection)
    scene[_HARNESS_TAG] = _HARNESS_REVISION
    return scene, geometry


def _show_scene(context, scene, active_object):
    if context.window is not None:
        context.window.scene = scene
        if active_object is not None:
            for obj in context.selected_objects:
                obj.select_set(False)
            active_object.select_set(True)
            context.view_layer.objects.active = active_object
    screen = context.screen
    if screen is not None:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "RENDERED"
                area.spaces.active.region_3d.view_perspective = "CAMERA"


class ADM_OT_create_edge_wear_harness(bpy.types.Operator):
    """Create or open the interactive 2.1.0 edge wear and instance dirt test scene."""
    bl_idname = "adm.create_edge_wear_harness"
    bl_label = "Create Edge Wear Test Scene (2.1.0)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = next((item for item in bpy.data.scenes if item.get(_HARNESS_TAG) == _HARNESS_REVISION), None)
        if scene is None:
            scene, active_object = _create_harness_scene()
        else:
            active_object = scene.objects.get("Wear | convex geometry")
        _show_scene(context, scene, active_object)
        self.report({"INFO"}, "Opened the ADM shader 2.1.0 edge-wear test scene")
        return {"FINISHED"}


class ADM_OT_enable_wear_preview(bpy.types.Operator):
    """Set up a Blender-only per-object engine wear simulation."""
    bl_idname = "adm.enable_wear_preview"
    bl_label = "Enable Wear Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.object is not None and context.object.type == "MESH"
                and context.object.is_editable)

    def execute(self, context):
        _initialize_preview_wear(context.object)
        return {"FINISHED"}


CLASSES = (ADM_OT_create_edge_wear_harness, ADM_OT_enable_wear_preview)
