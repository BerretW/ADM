"""Blender regression tests for dynamic shader enums and saved material values."""

import gc
import json
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
                    assert value.value_enum in ("NONE", "PARALLAX", "PARALLAX_OCCLUSION")
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
    material.adm.params["layer0_height_scale"].value_f = 0.37
    image = bpy.data.images.new("Archived height", 2, 2)
    image.pack()
    material.adm.params["layer0_height_texture"].image = image
    material.adm.params_shader_id = ""
    for param in material.adm.params:
        if "_schema_type" in param:
            del param["_schema_type"]
    material.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    material = bpy.data.materials["Enum persistence"]
    assert material.adm.params_shader_id == K.SHADER_TERRAIN_4[0]
    assert material.adm.params["parallax_mode"]["_schema_type"] == "ENUM"
    material.adm.shader_version = "2.0.0"
    assert material.adm.params.get("parallax_mode") is None
    warnings = []
    exporter = materials.MaterialExporter(None, warnings.append)
    exporter._export_shader(material, {})
    assert any("inactive shader parameters" in warning for warning in warnings), warnings
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    material = bpy.data.materials["Enum persistence"]
    assert material.adm.shader == "TERRAIN_4"
    assert material.adm.shader_version == "2.0.0"
    material.adm.shader_version = "2.1.0"
    assert material.adm.params["parallax_mode"].value_enum == "PARALLAX_OCCLUSION"
    assert abs(material.adm.params["layer0_height_scale"].value_f - 0.37) < 1e-6
    assert material.adm.params["layer0_height_texture"].image.name == "Archived height"
    assert material.adm.params["layer0_height_texture"].use

    print("PHASE custom enum round-trip", flush=True)
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportError_, ImportOptions, ModelImporter
    from adm_blender.core.container import read_container
    values = ["one,one", "second \N{LATIN SMALL LETTER E WITH ACUTE}\nline"]
    definition = bpy.context.scene.adm_anim.shaders.add()
    definition.shader_id = "org.example.enums"
    definition.version = "1.0.0"
    definition.description = "  Custom shader description  "
    definition.author = "  Example author  "
    parameter = definition.params.add()
    parameter.name = "mode"
    parameter.type = "ENUM"
    parameter.description = "  Custom mode  "
    parameter.enum_values = json.dumps(values, ensure_ascii=False)
    parameter.default_enum = values[0]
    numeric = definition.params.add()
    numeric.name = "strength"
    numeric.type = "F32"
    numeric.default_vec = (0.1, 0, 0, 0)
    numeric.description = "Custom strength"
    flag = definition.params.add()
    flag.name = "enabled"
    flag.type = "BOOL"
    flag.default_bool = True
    flag.description = "Custom flag"
    image = bpy.data.images.new("Custom default", 2, 2, alpha=True)
    image.pixels[:] = [1.0, 0.0, 0.0, 1.0] * 4
    image.pack()
    texture = definition.params.add()
    texture.name = "pattern"
    texture.type = "TEXTURE"
    texture.default_image = image
    texture.description = "Custom pattern"
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    custom = bpy.data.materials.new("Custom enum")
    materials.convert_to_adm_material(custom)
    cube.data.materials.append(custom)
    custom.adm.shader = "CUSTOM"
    custom.adm.custom_shader = definition.name
    materials.sync_material_params(custom, definition)
    custom.adm.params["mode"].value_enum_custom = values[1]
    custom.adm.params["pattern"].image = None
    custom.adm.params["pattern"].use = True
    parameter.type = "F32"
    materials.sync_material_params(custom, definition)
    assert not custom.adm.params["mode"].use
    custom.adm.params["mode"].value_f = 0.4
    parameter.type = "ENUM"
    materials.sync_material_params(custom, definition)
    assert custom.adm.params["mode"].value_enum_custom == values[1]
    assert custom.adm.params["mode"].use
    bpy.ops.adm.create_model_root(name="Custom enum root")
    root = bpy.data.objects["Custom enum root"]
    encoded, report = ModelExporter(bpy.context, root, ExportOptions()).export()
    assert report.ok, report.errors
    doc, _ = read_container(encoded, K.ADM_MAGIC)
    assert doc["shaderDefinitions"][0]["description"] == "  Custom shader description  "
    assert doc["shaderDefinitions"][0]["author"] == "  Example author  "
    assert doc["shaderDefinitions"][0]["parameters"][0]["description"] == "  Custom mode  "
    assert doc["shaderDefinitions"][0]["parameters"][0]["values"] == values
    assert doc["shaderDefinitions"][0]["parameters"][0]["default"] == values[0]
    assert doc["materials"][0]["shaderParameters"]["mode"] == values[1]
    assert doc["materials"][0]["shaderParameters"]["pattern"] is None
    adm_path = os.path.join(os.path.dirname(path), "custom.adm")
    with open(adm_path, "wb") as stream:
        stream.write(encoded)
    bpy.context.scene.adm_anim.shaders.clear()
    imported = ModelImporter(bpy.context, adm_path, ImportOptions())
    imported.run()
    imported_mat = imported.materials[0]
    assert imported_mat.adm.params["mode"].value_enum_custom == values[1]
    assert imported_mat.adm.params["pattern"].use
    assert imported_mat.adm.params["pattern"].image is None
    restored_definition = bpy.context.scene.adm_anim.shaders["org.example.enums@1.0.0"].params["mode"]
    assert json.loads(restored_definition.enum_values) == values
    assert restored_definition.default_enum == values[0]
    same = ModelImporter(bpy.context, adm_path, ImportOptions())
    same.run()
    imported_root_name = imported.root.name
    imported_mat_name = imported_mat.name
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    imported_mat = bpy.data.materials[imported_mat_name]
    assert imported_mat.adm.params["mode"].value_enum_custom == values[1]
    assert imported_mat.adm.params["pattern"].use
    assert imported_mat.adm.params["pattern"].image is None
    definition = bpy.context.scene.adm_anim.shaders["org.example.enums@1.0.0"]
    definition.description = "Different description"
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting metadata" in str(exc)
    else:
        raise AssertionError("Conflicting custom shader description was silently reused")
    definition.description = "  Custom shader description  "
    definition.author = "Different author"
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting metadata" in str(exc)
    else:
        raise AssertionError("Conflicting custom shader author was silently reused")
    definition.author = "  Example author  "
    definition.params["mode"].description = "Different description"
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter 'mode'" in str(exc)
    else:
        raise AssertionError("Conflicting custom parameter description was silently reused")
    definition.params["mode"].description = "  Custom mode  "
    definition.params["mode"].enum_values = json.dumps(values[::-1], ensure_ascii=False)
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting ENUM definition" in str(exc)
    else:
        raise AssertionError("Conflicting custom enum schema was silently reused")
    definition.params["mode"].enum_values = json.dumps(values, ensure_ascii=False)
    extra = definition.params.add()
    extra.name = "extra"
    extra.type = "F32"
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter names or types" in str(exc)
    else:
        raise AssertionError("Conflicting custom shader parameters were silently reused")
    definition.params.remove(len(definition.params) - 1)
    definition.params["strength"].default_vec = (0.2, 0, 0, 0)
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter 'strength'" in str(exc)
    else:
        raise AssertionError("Conflicting custom numeric default was silently reused")
    definition.params["strength"].default_vec = (0.1, 0, 0, 0)
    definition.params["enabled"].default_bool = False
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter 'enabled'" in str(exc)
    else:
        raise AssertionError("Conflicting custom boolean default was silently reused")
    definition.params["enabled"].default_bool = True
    definition.params["pattern"].default_tex_coord = 1
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter 'pattern'" in str(exc)
    else:
        raise AssertionError("Conflicting custom texture default was silently reused")
    definition.params["pattern"].default_tex_coord = 0
    pattern = definition.params["pattern"].default_image
    pattern.pixels[:] = [0.0, 0.0, 1.0, 1.0] * 4
    pattern.update()
    try:
        ModelImporter(bpy.context, adm_path, ImportOptions()).run()
    except ImportError_ as exc:
        assert "conflicting parameter 'pattern'" in str(exc)
    else:
        raise AssertionError("Conflicting custom texture pixels were silently reused")
    pattern.pixels[:] = [1.0, 0.0, 0.0, 1.0] * 4
    pattern.update()
    definition.params["mode"].enum_values = json.dumps(values[::-1], ensure_ascii=False)
    encoded, report = ModelExporter(bpy.context, bpy.data.objects[imported_root_name], ExportOptions()).export()
    assert report.ok, report.errors
    doc, _ = read_container(encoded, K.ADM_MAGIC)
    assert doc["materials"][0]["shaderParameters"]["mode"] == values[1]
    assert doc["materials"][0]["shaderParameters"]["pattern"] is None
    assert doc["shaderDefinitions"][0]["parameters"][0]["description"] == "  Custom mode  "
    assert doc["shaderDefinitions"][0]["parameters"][0]["values"] == values[::-1]
    definition.params["mode"].enum_values = "invalid JSON"
    try:
        ModelExporter(bpy.context, bpy.data.objects[imported_root_name], ExportOptions()).export()
    except ExportError as exc:
        assert "ENUM" in str(exc)
    else:
        raise AssertionError("Invalid custom enum definition was exported")
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
