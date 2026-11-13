"""ADM Tools - Sollumz-style authoring of ADM 1.0 models (.adm) and animation libraries (.adm_anim)."""

try:
    import bpy
except ImportError:  # imported outside Blender, e.g. ``python -m adm_blender.core.validate``
    bpy = None

if bpy is not None:
    from bpy.props import StringProperty

    from . import blender as _blender

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
        bpy.utils.register_class(ADMPreferences)
        _blender.register()
        prefs = bpy.context.preferences.addons.get(__package__)
        if prefs is not None and prefs.preferences.sidebar_category.strip() not in ("", "ADM"):
            from .blender import ui
            ui.set_sidebar_category(prefs.preferences.sidebar_category.strip())

    def unregister():
        _blender.unregister()
        bpy.utils.unregister_class(ADMPreferences)
