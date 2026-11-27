"""Blender integration of the ADM tools (props, operators, file I/O, UI)."""

import bpy
from bpy.app.handlers import persistent
from contextlib import ExitStack

from . import file_io, humanoid_wizard, lod_gen, operators, props, shader_harness, skeleton_ops, ui, vertex_colors

CLASSES = (
    operators.CLASSES + shader_harness.CLASSES + skeleton_ops.CLASSES + vertex_colors.CLASSES + lod_gen.CLASSES
    + humanoid_wizard.CLASSES
)


@persistent
def _load_post(_dummy):
    operators.ensure_role_names()
    from .materials import initialize_shader_param_owners
    initialize_shader_param_owners()


def _initialize_existing_materials():
    from .materials import initialize_shader_param_owners
    initialize_shader_param_owners()
    return None


def register():
    with ExitStack() as rollback:
        props.register()
        rollback.callback(props.unregister)
        for c in CLASSES:
            bpy.utils.register_class(c)
            rollback.callback(bpy.utils.unregister_class, c)
        file_io.register()
        rollback.callback(file_io.unregister)
        ui.register()
        rollback.callback(ui.unregister)
        vertex_colors.register()
        rollback.callback(vertex_colors.unregister)
        bpy.app.handlers.load_post.append(_load_post)
        rollback.callback(bpy.app.handlers.load_post.remove, _load_post)
        # Blender restricts data access during add-on registration.
        bpy.app.timers.register(operators.ensure_role_names, first_interval=0.1)
        rollback.callback(bpy.app.timers.unregister, operators.ensure_role_names)
        bpy.app.timers.register(_initialize_existing_materials, first_interval=0.1)
        rollback.callback(bpy.app.timers.unregister, _initialize_existing_materials)
        rollback.pop_all()


def unregister():
    vertex_colors.unregister()
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if bpy.app.timers.is_registered(operators.ensure_role_names):
        bpy.app.timers.unregister(operators.ensure_role_names)
    if bpy.app.timers.is_registered(_initialize_existing_materials):
        bpy.app.timers.unregister(_initialize_existing_materials)
    ui.unregister()
    file_io.unregister()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    props.unregister()
