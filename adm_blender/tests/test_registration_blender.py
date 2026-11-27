"""Exercise registration through Blender's restricted add-on loader."""

import os
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import addon_utils
import bpy


def main():
    print("PHASE enable through addon_utils", flush=True)
    addon = addon_utils.enable("adm_blender")
    assert addon is not None, "Blender could not enable the add-on"
    from adm_blender.blender import _initialize_existing_materials, operators
    from adm_blender.core import constants as K

    mat = bpy.data.materials.new("Registration migration")
    mat.adm.shader = "TERRAIN_4"
    mat.adm.shader_version = "2.1.0"
    mat.adm.params_shader_id = ""
    for param in mat.adm.params:
        if "_schema_type" in param:
            del param["_schema_type"]
    assert bpy.app.timers.is_registered(_initialize_existing_materials)
    _initialize_existing_materials()
    assert mat.adm.params_shader_id == K.SHADER_TERRAIN_4[0]
    assert mat.adm.params["parallax_mode"]["_schema_type"] == "ENUM"
    print("PHASE disable and re-enable", flush=True)
    addon_utils.disable("adm_blender")
    assert not bpy.app.timers.is_registered(_initialize_existing_materials)
    assert not bpy.app.timers.is_registered(operators.ensure_role_names)
    assert addon_utils.enable("adm_blender") is not None
    addon_utils.disable("adm_blender")

    print("PHASE interrupted registration rollback", flush=True)
    import adm_blender
    from adm_blender.blender import file_io, props, ui

    real_register = bpy.utils.register_class
    for target in (props.CLASSES[2], adm_blender._blender.CLASSES[2], file_io.CLASSES[2], ui.CLASSES[2]):
        print(f"PHASE inject failure {target.__name__}", flush=True)

        def fail_registration(cls):
            if cls is target:
                raise RuntimeError("injected registration failure")
            real_register(cls)

        bpy.utils.register_class = fail_registration
        try:
            try:
                adm_blender.register()
            except RuntimeError as exc:
                assert str(exc) == "injected registration failure"
            else:
                raise AssertionError("Expected injected registration failure")
        finally:
            bpy.utils.register_class = real_register
        assert not props.ADMFaceBinding.is_registered
        assert not adm_blender.ADMPreferences.is_registered
        assert not hasattr(bpy.types.Material, "adm")
        assert addon_utils.enable("adm_blender") is not None
        addon_utils.disable("adm_blender")
    print("PASS restricted registration and rollback", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
