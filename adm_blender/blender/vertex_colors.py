"""Authoring of linear ADM vertex controls on Blender color attributes."""

import math

import bmesh
import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import EnumProperty
from mathutils import Color

from ..core import constants as K

DEFAULTS = {"COLOR_0": (0.0, 1.0, 1.0, 0.0), "COLOR_1": (0.0, 0.0, 0.0, 0.0)}


class VertexColorError(ValueError):
    pass


def validate_layers(mesh):
    for name in DEFAULTS:
        attr = mesh.attributes.get(name)
        if attr is not None and (attr.domain not in {"POINT", "CORNER"}
                                 or attr.data_type not in {"FLOAT_COLOR", "BYTE_COLOR"}):
            raise VertexColorError(f"'{mesh.name}': {name} must be a POINT or CORNER color attribute")


def _linear_color(value, byte_color):
    if not byte_color:
        return tuple(value)
    rgb = Color(value[:3]).from_srgb_to_scene_linear()
    return (*rgb, value[3])


def ensure_layer(mesh, name):
    """Create one ADM layer as float corners without changing its authored values."""
    if name not in DEFAULTS:
        raise VertexColorError(f"unknown ADM vertex color layer '{name}'")
    validate_layers(mesh)
    active_name = mesh.color_attributes.active_color_name
    default = DEFAULTS[name]
    attr = mesh.attributes.get(name)
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        if attr is not None and attr.domain == "CORNER" and attr.data_type == "FLOAT_COLOR":
            return False
        values = None
        if attr is not None:
            source_layers = bm.verts.layers if attr.domain == "POINT" else bm.loops.layers
            source_colors = source_layers.color if attr.data_type == "BYTE_COLOR" else source_layers.float_color
            source = source_colors.get(name)
            values = [
                _linear_color((loop.vert if attr.domain == "POINT" else loop)[source],
                              attr.data_type == "BYTE_COLOR")
                for face in bm.faces for loop in face.loops
            ]
            source_colors.remove(source)
        layer = bm.loops.layers.float_color.new(name)
        for i, loop in enumerate(loop for face in bm.faces for loop in face.loops):
            loop[layer] = default if values is None else values[i]
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        if attr is not None and attr.domain == "CORNER" and attr.data_type == "FLOAT_COLOR":
            return False
        values = np.tile(default, (len(mesh.loops), 1)).astype(np.float32)
        if attr is not None:
            source = np.empty((len(attr.data), 4), dtype=np.float32)
            attr.data.foreach_get("color", source.ravel())
            if attr.domain == "POINT":
                indices = np.empty(len(mesh.loops), dtype=np.int32)
                mesh.loops.foreach_get("vertex_index", indices)
                source = source[indices]
            values = source
            mesh.color_attributes.remove(attr)
        attr = mesh.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
        attr.data.foreach_set("color", values.ravel())
        mesh.update()
    if not active_name or active_name in DEFAULTS:
        mesh.color_attributes.active_color_name = active_name or "COLOR_0"
    return True


def ensure_layers(mesh):
    """Preserve authored linear values; use float corners to avoid gamma/byte index quantization."""
    changed = False
    for name in DEFAULTS:
        changed = ensure_layer(mesh, name) or changed
    return changed


def in_adm_model(obj):
    while obj is not None:
        if obj.adm.adm_type == "MODEL":
            return True
        obj = obj.parent
    return False


def sync_control_meshes(material=None, explicit=()):
    """Initialize control layers of ADM model meshes using enabled materials.

    Objects outside an ADM Model Root are only touched when passed in ``explicit``
    by a user action (enabling vertex controls or converting them to ADM).
    """
    changed_materials = set()
    changed_meshes = set()
    seen = set()
    explicit = {obj for obj in explicit if obj is not None}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.adm.adm_type == "COLLIDER" or not obj.data.is_editable:
            continue
        if obj not in explicit and not in_adm_model(obj):
            continue
        mats = {slot.material for slot in obj.material_slots
                if slot.material is not None and slot.material.adm.vertex_controls_enabled}
        if not mats:
            continue
        try:
            if obj.data not in seen:
                seen.add(obj.data)
                if ensure_layers(obj.data):
                    changed_meshes.add(obj.data)
            if obj.data in changed_meshes:
                changed_materials.update(mats)
            changed_materials.update(
                mat for mat in mats if mat.node_tree is not None
                and not any(node.bl_idname == "ShaderNodeVertexColor" and node.layer_name == "COLOR_0"
                            for node in mat.node_tree.nodes)
            )
        except VertexColorError as exc:
            print(f"ADM Vertex Colors: {exc}")
    from .materials import refresh_shader_preview
    for mat in changed_materials:
        if mat != material:
            refresh_shader_preview(mat)
    return None


@persistent
def _queue_sync(_scene, _depsgraph=None):
    if not bpy.app.timers.is_registered(sync_control_meshes):
        bpy.app.timers.register(sync_control_meshes, first_interval=0.1)


@persistent
def _load_post(_dummy):
    for mat in bpy.data.materials:
        if mat.adm.vertex_tint_palette is not None:
            try:
                refresh_palette(mat)
            except VertexColorError as exc:
                print(f"ADM Tint Palette: {exc}")
    _queue_sync(None)


def palette_colors(image):
    """Linear RGBA swatches of the palette's first (top) row; other rows are ignored."""
    if image is None:
        raise VertexColorError("Choose a Tint Palette image on the active material")
    width, height = image.size
    if not 1 <= height <= K.TINT_PALETTE_MAX_HEIGHT or width < 1 or image.channels != 4:
        raise VertexColorError(f"'{image.name}': tint palette must be a readable RGBA image "
                               f"1-{K.TINT_PALETTE_MAX_HEIGHT} pixels high")
    pixels = np.empty(width * height * 4, dtype=np.float32)
    if len(image.pixels) != len(pixels):
        raise VertexColorError(f"'{image.name}': tint palette has no readable RGBA pixels")
    image.pixels.foreach_get(pixels)
    # Blender stores rows bottom-up, so the first (top) image row is the last one here.
    colors = pixels.reshape(height, width, 4)[height - 1]
    if not np.isfinite(colors).all():
        raise VertexColorError(f"'{image.name}': tint palette contains non-finite colors")
    # Blender byte image pixels are encoded; float image pixels are already linear unless marked sRGB.
    if not image.is_float or image.colorspace_settings.name == "sRGB":
        colors = np.array([_linear_color(color, True) for color in colors], dtype=np.float32)
    return colors


def refresh_palette(mat):
    mat.adm.tint_palette_entries.clear()
    if mat.adm.vertex_tint_palette is None:
        return
    for index, color in enumerate(palette_colors(mat.adm.vertex_tint_palette)):
        entry = mat.adm.tint_palette_entries.add()
        entry.name = f"{index}"
        entry.color = color
    mat.adm.active_tint_entry = min(mat.adm.active_tint_entry, len(mat.adm.tint_palette_entries) - 1)


def palette_position(index, size, offset):
    if not 0 <= index < size or not math.isfinite(offset):
        raise VertexColorError("Select an existing tint palette entry and a finite Tint Offset")
    red = float(np.float32(min(1.0, max(0.0, (index + 0.5 - offset) / size))))
    actual = min(size - 1, max(0, math.floor(red * size + offset)))
    if actual != index:
        raise VertexColorError("This palette entry cannot be selected with the current Tint Offset; "
                               "set Tint Offset to 0 or choose another entry")
    return red


def write_colors(mesh, names, values, channel="RGBA", selected=False, material_indices=None,
                 intensity=1.0, operation="SET"):
    """Write face corners only, including live Edit Mode data."""
    if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.0:
        raise VertexColorError("Paint Intensity must be finite and in [0,1]")
    if operation not in {"SET", "INVERT"}:
        raise VertexColorError(f"unknown vertex color operation '{operation}'")
    component = None if channel == "RGBA" else "RGBA".index(channel)

    def update(current, name):
        result = list(current)
        components = range(4) if component is None else (component,)
        target = values[name]
        for i in components:
            goal = 1.0 - result[i] if operation == "INVERT" else float(target[i])
            result[i] += (goal - result[i]) * intensity
        return result

    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        faces = [face for face in bm.faces if (not selected or (face.select and not face.hide))
                 and (material_indices is None or face.material_index in material_indices)]
        if not faces:
            raise VertexColorError("No matching faces; select faces using the active material")
        for name in names:
            ensure_layer(mesh, name)
        for name in names:
            layer = bm.loops.layers.float_color.get(name)
            for face in faces:
                for loop in face.loops:
                    loop[layer] = update(loop[layer], name)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        faces = [face for face in mesh.polygons if (not selected or (face.select and not face.hide))
                 and (material_indices is None or face.material_index in material_indices)]
        if not faces:
            raise VertexColorError("No matching faces; select faces using the active material")
        for name in names:
            ensure_layer(mesh, name)
        for name in names:
            attr = mesh.color_attributes[name]
            for face in faces:
                for i in face.loop_indices:
                    attr.data[i].color = update(attr.data[i].color, name)
        mesh.update()
    return len(faces)


class ADM_OT_vertex_colors(bpy.types.Operator):
    """Initialize without overwriting colors, reset defaults, or write linear control channels"""
    bl_idname = "adm.vertex_colors"
    bl_label = "ADM Vertex Colors"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(items=[
        ("INITIALIZE", "Initialize Layers", "Create missing ADM layers and preserve existing values"),
        ("RESET", "Reset Defaults", "COLOR_0=(0,1,1,0), COLOR_1=(0,0,0,0)"),
        ("APPLY", "Apply Channels", "Write the selected linear control channels"),
        ("FILL", "Fill", "Set the selected channel(s) to 1"),
        ("CLEAR", "Clear", "Set the selected channel(s) to 0"),
        ("INVERT", "Invert", "Invert the selected channel(s)"),
        ("TINT", "Apply Palette to R", "Write the palette position to R; keep G, B and A unchanged"),
        ("ACTIVE", "Make Active", "Activate the selected layer for Blender color painting"),
    ], default="INITIALIZE")

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "MESH" and obj.adm.adm_type != "COLLIDER" \
            and obj.data.is_editable and obj.mode in {"OBJECT", "EDIT", "VERTEX_PAINT"}

    def execute(self, context):
        obj = context.object
        wm = context.window_manager.adm
        mat = obj.active_material
        name = wm.vertex_color_layer
        selected = wm.vertex_color_scope == "SELECTED"
        slots = {i for i, slot in enumerate(obj.material_slots) if mat is not None and slot.material == mat}
        try:
            if wm.vertex_color_scope == "MATERIAL" \
                    and self.action in {"RESET", "APPLY", "FILL", "CLEAR", "INVERT", "TINT"} and not slots:
                raise VertexColorError("This Material Faces needs an active material")
            validate_layers(obj.data)
            if self.action in {"INITIALIZE", "ACTIVE"}:
                ensure_layers(obj.data)
                count = None
            elif self.action == "TINT":
                if mat is None or not mat.adm.vertex_controls_enabled:
                    raise VertexColorError("Enable ADM Vertex Controls on the active material")
                size = len(palette_colors(mat.adm.vertex_tint_palette))
                red = palette_position(mat.adm.active_tint_entry, size, mat.adm.tint_offset)
                count = write_colors(obj.data, ("COLOR_0",), {"COLOR_0": (red, 1.0, 1.0, 0.0)},
                                     "R", selected, slots, wm.vertex_color_intensity)
                name = "COLOR_0"
            else:
                names = tuple(DEFAULTS) if self.action == "RESET" else (name,)
                channel = "RGBA" if self.action == "RESET" else wm.vertex_color_channel
                intensity = 1.0 if self.action == "RESET" else wm.vertex_color_intensity
                operation = "INVERT" if self.action == "INVERT" else "SET"
                if self.action == "RESET":
                    values = DEFAULTS
                elif self.action == "FILL":
                    values = {name: (1.0, 1.0, 1.0, 1.0)}
                elif self.action in {"CLEAR", "INVERT"}:
                    values = {name: (0.0, 0.0, 0.0, 0.0)}
                else:
                    values = {name: tuple(wm.vertex_color_values)}
                count = write_colors(
                    obj.data, names, values, channel, selected,
                    slots if wm.vertex_color_scope == "MATERIAL" else None, intensity, operation)
            if self.action != "ACTIVE" and mat is not None and not mat.adm.vertex_controls_enabled:
                mat.adm.vertex_controls_enabled = True
            sync_control_meshes(explicit=(obj,))
            obj.data.color_attributes.active_color_name = name
            if obj.data.users > 1:
                self.report({"WARNING"}, "Changes affect every object sharing this mesh")
            self.report({"INFO"}, "ADM color layers ready" if count is None else f"Updated {count} face(s)")
        except VertexColorError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ADM_OT_initialize_shader_masks(bpy.types.Operator):
    """Create the active ADM shader's COLOR_1 layer with neutral mask values."""
    bl_idname = "adm.initialize_shader_masks"
    bl_label = "Initialize Shader Masks"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        mat = obj.active_material if obj is not None and obj.type == "MESH" else None
        return obj is not None and obj.type == "MESH" and obj.adm.adm_type != "COLLIDER" \
            and obj.data.is_editable and in_adm_model(obj) and mat is not None \
            and mat.adm.shader_version == K.SHADER_PROFILE_V2 and mat.adm.shader in K.COLOR1_CONTRACTS

    def execute(self, context):
        obj = context.object
        try:
            validate_layers(obj.data)
            ensure_layer(obj.data, "COLOR_1")
            obj.data.color_attributes.active_color_name = "COLOR_1"
            if obj.active_material is not None:
                from .materials import refresh_shader_preview
                refresh_shader_preview(obj.active_material)
        except VertexColorError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "COLOR_1 shader masks initialized without changing existing values")
        return {"FINISHED"}


class ADM_OT_tint_palette_refresh(bpy.types.Operator):
    """Reload the swatches after editing the Tint Palette image"""
    bl_idname = "adm.tint_palette_refresh"
    bl_label = "Refresh Palette"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.active_material is not None

    def execute(self, context):
        try:
            refresh_palette(context.object.active_material)
        except VertexColorError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (ADM_OT_vertex_colors, ADM_OT_initialize_shader_masks, ADM_OT_tint_palette_refresh)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_queue_sync)
    bpy.app.handlers.load_post.append(_load_post)
    _queue_sync(None)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_queue_sync)
    bpy.app.handlers.load_post.remove(_load_post)
    if bpy.app.timers.is_registered(sync_control_meshes):
        bpy.app.timers.unregister(sync_control_meshes)
