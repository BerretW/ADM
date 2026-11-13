"""Blender headless test for official shader identity and typed-data round trips."""
import os
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FAILS = []


def check(condition, message):
    print(("  ok  " if condition else "  FAIL ") + message)
    if not condition:
        FAILS.append(message)


def main(tmp):
    adm_blender.register()
    from adm_blender.core import constants as K
    from adm_blender.blender import materials as M
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = bpy.context.active_object
    mat = bpy.data.materials.new("Core20")
    cube.data.materials.append(mat)
    M.convert_to_adm_material(mat)
    check(bpy.ops.adm.create_model_root(name="ShaderRoot") == {"FINISHED"}, "create model root")
    root = bpy.data.objects["ShaderRoot"]

    for key, kind in K.OFFICIAL_SHADER_KINDS.items():
        mat.adm.shader = kind
        if kind == "EMISSIVE":
            bsdf = M.principled_of(mat)
            bsdf.inputs["Emission Color"].default_value = (0.25, 0.5, 0.75, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 2.0
        bpy.context.view_layer.update()
        exporter = ModelExporter(bpy.context, root, ExportOptions())
        data, report = exporter.export()
        check(report.ok, f"{kind}: export validates")
        if not report.ok:
            continue
        material = report.doc["materials"][0]
        check(material.get("shader", {"id": K.SHADER_CORE[0], "version": K.SHADER_CORE[1]}) ==
              {"id": key[0], "version": key[1]}, f"{kind}: exact shader ID/version")
        if kind != "CORE":
            check(all(field in material for field in K.PBR_FALLBACK_FIELDS), f"{kind}: explicit PBR fallback")
        path = os.path.join(tmp, f"{kind.lower()}.adm")
        with open(path, "wb") as stream:
            stream.write(data)
        ModelImporter(bpy.context, path, ImportOptions()).run()
        imported = next((candidate for candidate in bpy.data.materials
                         if candidate != mat and candidate.adm.shader == kind), None)
        check(imported is not None, f"{kind}: import restores profile")
        if imported is not None and kind == "LAYERED":
            check(abs(imported.adm.layer_factor) < 1e-6, "LAYERED: layer factor restored")
        elif imported is not None and key in K.OFFICIAL_SHADERS:
            expected_params = {p["name"] for p in K.OFFICIAL_SHADERS[key]}
            actual_params = {p.name for p in imported.adm.params}
            check(actual_params == expected_params, f"{kind}: typed parameter schema restored")
        if kind not in ("CORE", "LAYERED", "CUTOUT", "EMISSIVE", "DECAL"):
            check(any("portable PBR fallback" in warning for warning in exporter.warnings),
                  f"{kind}: unsupported preview is reported")

    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_shaders_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
