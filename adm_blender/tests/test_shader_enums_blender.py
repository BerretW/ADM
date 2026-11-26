"""Blender regression tests for dynamic shader enums and saved material values."""

import gc
import os
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender


def main(path):
    print("PHASE register", flush=True)
    adm_blender.register()
    from adm_blender.blender import materials, props
    from adm_blender.core import constants as K

    bpy.ops.wm.read_homefile(use_empty=True)
    material = bpy.data.materials.new("Enum persistence")
    materials.convert_to_adm_material(material)
    print("PHASE profile switches", flush=True)
    for kind in ("TERRAIN_4", "TWO_LAYER", "LAYERED"):
        material.adm.shader = kind
        versions = props._official_shader_versions(kind)
        for _ in range(2):
            for version in versions:
                material.adm.shader_version = version
                assert material.adm.shader_version == version, (kind, version)
                key = material.adm.shader_key()
                if key in K.SHADER_LAYERED_HEIGHT_COUNTS:
                    value = material.adm.params["parallax_mode"]
                    assert value.value_enum == "NONE"
                    for mode in ("NONE", "PARALLAX", "PARALLAX_OCCLUSION"):
                        value.value_enum = mode
                        gc.collect()
                        assert value.value_enum == mode
                    assert [item[3] for item in props._enum_value_items(value, bpy.context)] == [0, 1, 2]

    print("PHASE invalid and unavailable enum", flush=True)
    material.adm.shader = "TERRAIN_4"
    material.adm.shader_version = "2.1.0"
    original_refresh = materials.refresh_shader_preview
    calls = []

    def count_refresh(mat):
        calls.append(mat.name)
        original_refresh(mat)

    materials.refresh_shader_preview = count_refresh
    try:
        material.adm.shader = "TWO_LAYER"
        assert material.adm.shader_version == "1.0.0"
        assert calls == [material.name], calls
    finally:
        materials.refresh_shader_preview = original_refresh
    material.adm["shader_version"] = 99
    assert material.adm.shader_version == "INVALID_99"
    material.adm.shader = "TERRAIN_4"
    material.adm.shader_version = "2.1.0"
    value = material.adm.params["parallax_mode"]
    value["value_enum"] = 99
    assert value.value_enum == "INVALID_99"
    assert K.OFFICIAL_SHADERS[material.adm.shader_key()]
    from adm_blender.core.validate import param_value_error
    schema = next(p for p in K.OFFICIAL_SHADERS[material.adm.shader_key()] if p["name"] == "parallax_mode")
    assert param_value_error(schema, value.value_enum, None)
    value.value_enum = "PARALLAX_OCCLUSION"
    orphan = material.adm.params.add()
    orphan.name = "missing_schema"
    assert orphan.value_enum == "UNAVAILABLE"
    orphan["value_enum"] = 42
    assert orphan.value_enum == "INVALID_42"
    material.adm.params.remove(len(material.adm.params) - 1)

    print("PHASE save and reopen", flush=True)
    material.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    material = bpy.data.materials["Enum persistence"]
    assert material.adm.shader == "TERRAIN_4"
    assert material.adm.shader_version == "2.1.0"
    assert material.adm.params["parallax_mode"].value_enum == "PARALLAX_OCCLUSION"
    print("RESULT: PASS", flush=True)


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_enum_") as tmp:
            main(os.path.join(tmp, "enums.blend"))
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
