"""Authoring of linear ADM vertex controls on Blender color attributes."""

import math

import bmesh
import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import EnumProperty
from mathutils import Color

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


def ensure_layers(mesh):
    """Preserve authored linear values; use float corners to avoid gamma/byte index quantization."""
    validate_layers(mesh)
    active_name = mesh.color_attributes.active_color_name
    changed = False
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        for name, default in DEFAULTS.items():
            attr = mesh.attributes.get(name)
            layer = bm.loops.layers.float_color.get(name)
            if attr is not None and attr.domain == "CORNER" and attr.data_type == "FLOAT_COLOR":
                continue
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
            changed = True
        if changed:
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        for name, default in DEFAULTS.items():
            attr = mesh.color_attributes.get(name)
            if attr is not None and attr.domain == "CORNER" and attr.data_type == "FLOAT_COLOR":
                continue
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
            changed = True
        if changed:
            mesh.update()
    if changed and (not active_name or active_name in DEFAULTS):
        mesh.color_attributes.active_color_name = active_name or "COLOR_0"
    return changed


def sync_control_meshes(material=None):
    changed_materials = set()
    seen = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.adm.adm_type == "COLLIDER" or not obj.data.is_editable:
            continue
        mats = {slot.material for slot in obj.material_slots
                if slot.material is not None and slot.material.adm.vertex_controls_enabled}
        if not mats or (material is not None and material not in mats) or obj.data in seen:
            continue
        seen.add(obj.data)
        try:
            if ensure_layers(obj.data):
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
    if image is None:
        raise VertexColorError("Choose a Tint Palette image on the active material")
    width, height = image.size
    if height != 1 or width < 1 or image.channels != 4:
        raise VertexColorError(f"'{image.name}': tint palette must be a readable one-row RGBA image")
    pixels = np.empty(width * 4, dtype=np.float32)
    if len(image.pixels) != len(pixels):
        raise VertexColorError(f"'{image.name}': tint palette has no readable RGBA pixels")
    image.pixels.foreach_get(pixels)
    if not np.isfinite(pixels).all():
        raise VertexColorError(f"'{image.name}': tint palette contains non-finite colors")
    colors = pixels.reshape(-1, 4)
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


def write_colors(mesh, names, values, channel="RGBA", selected=False, material_index=None):
    """Write face corners only, including live Edit Mode data."""
    component = None if channel == "RGBA" else "RGBA".index(channel)
    if mesh.is_editmode:
        bm = bmesh.from_edit_mesh(mesh)
        faces = [face for face in bm.faces if (not selected or (face.select and not face.hide))
                 and (material_index is None or face.material_index == material_index)]
        if not faces:
            raise VertexColorError("No matching faces; select faces using the active material")
        ensure_layers(mesh)
        for name in names:
            layer = bm.loops.layers.float_color.get(name)
            for face in faces:
                for loop in face.loops:
                    value = list(loop[layer])
                    if component is None:
                        value = values[name]
                    else:
                        value[component] = values[name][component]
                    loop[layer] = value
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        faces = [face for face in mesh.polygons if (not selected or (face.select and not face.hide))
                 and (material_index is None or face.material_index == material_index)]
        if not faces:
            raise VertexColorError("No matching faces; select faces using the active material")
        ensure_layers(mesh)
        for name in names:
            attr = mesh.color_attributes[name]
            for face in faces:
                for i in face.loop_indices:
                    value = list(attr.data[i].color)
                    if component is None:
                        value = values[name]
                    else:
                        value[component] = values[name][component]
                    attr.data[i].color = value
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
        try:
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
                                     "R", wm.vertex_color_scope == "SELECTED", obj.active_material_index)
                name = "COLOR_0"
            else:
                names = tuple(DEFAULTS) if self.action == "RESET" else (name,)
                values = DEFAULTS if self.action == "RESET" else {name: tuple(wm.vertex_color_values)}
                count = write_colors(obj.data, names, values,
                                     "RGBA" if self.action == "RESET" else wm.vertex_color_channel,
                                     wm.vertex_color_scope == "SELECTED")
            if self.action != "ACTIVE" and mat is not None and not mat.adm.vertex_controls_enabled:
                mat.adm.vertex_controls_enabled = True
            sync_control_meshes()
            obj.data.color_attributes.active_color_name = name
            if obj.data.users > 1:
                self.report({"WARNING"}, "Changes affect every object sharing this mesh")
            self.report({"INFO"}, "ADM color layers ready" if count is None else f"Updated {count} face(s)")
        except VertexColorError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
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


CLASSES = (ADM_OT_vertex_colors, ADM_OT_tint_palette_refresh)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_queue_sync)
    bpy.app.handlers.load_post.append(_load_post)
    _queue_sync(None)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_queue_sync)
    bpy.app.handlers.load_post.remove(_load_post)
    if bpy.app.timers.is_registered(sync_control_meshes):
        bpy.app.timers.unregister(sync_control_meshes)
