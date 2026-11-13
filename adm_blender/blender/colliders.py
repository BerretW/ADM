"""Display geometry for ADM collider objects (Blender-space, capsule along local +Z == ADM +Y)."""

import bmesh
import bpy


def build_collider_bmesh(shape, size, radius, height):
    bm = bmesh.new()
    if shape == "BOX":
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x *= size[0]
            v.co.y *= size[1]
            v.co.z *= size[2]
    elif shape == "SPHERE":
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=radius)
    elif shape == "CAPSULE":
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=radius)
        half = max(0.0, height * 0.5 - radius)
        for v in bm.verts:
            if v.co.z > 1e-6:
                v.co.z += half
            elif v.co.z < -1e-6:
                v.co.z -= half
    return bm


def refresh_collider_mesh(obj):
    """Regenerate the wireframe preview of a primitive collider from its ADM properties."""
    props = obj.adm
    if obj.type != "MESH" or props.collider_shape == "MESH":
        return
    bm = build_collider_bmesh(props.collider_shape, props.collider_size, props.collider_radius,
                              props.collider_height)
    me = obj.data
    if me.users > 1:
        me = me.copy()
        obj.data = me
    bm.to_mesh(me)
    bm.free()
    me.update()


def style_collider_object(obj):
    obj.display_type = "WIRE"
    obj.hide_render = True
    obj.show_in_front = True
    obj.color = (0.1, 0.9, 0.3, 1.0)


def new_collider_object(context, shape, name="Collider", size=(1, 1, 1), radius=0.5, height=2.0, mesh=None):
    me = mesh if mesh is not None else bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    obj.adm.adm_type = "COLLIDER"
    obj.adm.collider_shape = shape
    obj.adm.collider_size = size
    obj.adm.collider_radius = radius
    obj.adm.collider_height = max(height, 2 * radius)
    if shape != "MESH":
        refresh_collider_mesh(obj)
    style_collider_object(obj)
    return obj
