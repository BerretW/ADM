"""Blender integration of the ADM tools (props, operators, file I/O, UI)."""

import bpy
from bpy.app.handlers import persistent

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


def register():
    props.register()
    from .materials import initialize_shader_param_owners
    initialize_shader_param_owners()
    for c in CLASSES:
        bpy.utils.register_class(c)
    file_io.register()
    ui.register()
    vertex_colors.register()
    bpy.app.handlers.load_post.append(_load_post)
    # WindowManager data is not writable during registration; fill on first tick
    bpy.app.timers.register(operators.ensure_role_names, first_interval=0.1)


def unregister():
    vertex_colors.unregister()
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if bpy.app.timers.is_registered(operators.ensure_role_names):
        bpy.app.timers.unregister(operators.ensure_role_names)
    ui.unregister()
    file_io.unregister()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    props.unregister()
