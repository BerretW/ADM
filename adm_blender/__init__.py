"""ADM Tools - Sollumz-style authoring of ADM 1.0 models (.adm) and animation libraries (.adm_anim)."""

try:
    import bpy
except ImportError:  # imported outside Blender, e.g. ``python -m adm_blender.core.validate``
    bpy = None

if bpy is not None:
    import importlib
    import sys
    from contextlib import ExitStack

    from bpy.props import StringProperty

    # Blender unregisters before reloading only this entry point on an update.
    # Reimport our submodules together so old RNA classes cannot mix with new code.
    if "_blender" in locals():
        for module_name in tuple(sys.modules):
            if module_name.startswith(__name__ + "."):
                del sys.modules[module_name]
    _blender = importlib.import_module(".blender", __name__)

    def _category_update(self, _context):
        from .blender import ui
        ui.set_sidebar_category(self.sidebar_category.strip() or "ADM")

    class ADMPreferences(bpy.types.AddonPreferences):
        bl_idname = __package__

        sidebar_category: StringProperty(name="Sidebar Tab", default="ADM", update=_category_update,
                                         description="Name of the 3D View sidebar (N panel) tab")

        def draw(self, context):
            self.layout.prop(self, "sidebar_category")

    def register():
        with ExitStack() as rollback:
            bpy.utils.register_class(ADMPreferences)
            rollback.callback(bpy.utils.unregister_class, ADMPreferences)
            _blender.register()
            rollback.callback(_blender.unregister)
            prefs = bpy.context.preferences.addons.get(__package__)
            if prefs is not None and prefs.preferences.sidebar_category.strip() not in ("", "ADM"):
                from .blender import ui
                ui.set_sidebar_category(prefs.preferences.sidebar_category.strip())
            rollback.pop_all()

    def unregister():
        _blender.unregister()
        bpy.utils.unregister_class(ADMPreferences)
