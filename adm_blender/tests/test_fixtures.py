"""Blender background test: register add-on, import the adm-standard fixtures, re-export and validate.

Run:  blender -b --factory-startup --python adm_blender/tests/test_fixtures.py
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
FIX = os.path.join(REPO, "adm-standard", "fixtures", "valid")

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import adm_blender  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def errs(rep):
    return [] if rep is None or rep.ok else [str(e) for e in rep.errors[:4]]


def main(tmp):
    adm_blender.register()
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.export_anim import AnimExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.blender.import_anim import AnimImportOptions, import_library
    from adm_blender.core import constants as K
    from adm_blender.core.buffers import BinBuilder
    from adm_blender.core.container import write_container
    from adm_blender.core.png import encode_png
    from adm_blender.core.validate import validate_file

    bpy.ops.wm.read_homefile(use_empty=True)
    ctx = bpy.context

    print("== triangle.adm")
    root = ModelImporter(ctx, os.path.join(FIX, "triangle.adm"), ImportOptions()).run()
    check(root is not None, "triangle imported")
    data, rep = ModelExporter(ctx, root, ExportOptions()).export()
    check(rep.ok, f"triangle re-export valid {errs(rep)}")
    root = ModelImporter(ctx, os.path.join(FIX, "triangle_split.adm"), ImportOptions()).run()
    data, rep = ModelExporter(ctx, root, ExportOptions()).export()
    check(rep.ok, f"split-chunk triangle round-trip valid {errs(rep)}")

    print("== interactive_terminal.adm")
    bpy.ops.wm.read_homefile(use_empty=True)
    ctx = bpy.context
    interactive_importer = ModelImporter(ctx, os.path.join(FIX, "interactive_terminal.adm"), ImportOptions())
    interactive_root = interactive_importer.run()
    check(interactive_importer.node_obj[0].data != interactive_importer.node_obj[1].data,
          "shared source mesh has independent surface IDs per node")
    data, rep = ModelExporter(ctx, interactive_root, ExportOptions()).export()
    surfaces = rep.doc.get("extensions", {}).get(K.INTERACTIVE_SURFACES_EXT, {}).get("surfaces", [])
    check(rep.ok and {surface["surfaceId"] for surface in surfaces} ==
          {"main_display", "security_monitor_right"}, f"interactive fixture round-trip {errs(rep)}")

    print("== shader_layered.adm")
    bpy.ops.wm.read_homefile(use_empty=True)
    ctx = bpy.context
    root = ModelImporter(ctx, os.path.join(FIX, "shader_layered.adm"), ImportOptions()).run()
    mats = [m for m in bpy.data.materials if m.adm.shader == "LAYERED"]
    check(len(mats) == 1, "layered material imported")
    mat = mats[0]
    check(mat.adm.animation_id == "body_paint", f"animationId {mat.adm.animation_id!r}")
    exp = ModelExporter(ctx, root, ExportOptions())
    data, rep = exp.export()
    check(rep.ok, f"layered re-export valid {errs(rep)}")
    m0 = rep.doc["materials"][0]
    check(m0.get("shader", {}).get("id") == "adm.pbr.layered", "shader id re-exported")
    check("ADM_material_layers_v1" in rep.doc.get("extensionsUsed", []), "layers extension listed")
    print("   material:", m0)
    model_path = os.path.join(tmp, "layered.adm")
    with open(model_path, "wb") as fh:
        fh.write(data)

    print("== shader_parameter_tracks.adm_anim (model.any.v1, no rig)")
    imp, slib = import_library(ctx, os.path.join(FIX, "shader_parameter_tracks.adm_anim"),
                               AnimImportOptions(armature=None))
    print("   warnings:", imp.warnings)
    check(slib.target == "MODEL_ANY", "library target MODEL_ANY")
    act = slib.clips[0].action
    check(act is not None, "clip action created")
    kinds = sorted({s.target_id_type for s in act.slots})
    check(kinds == ["MATERIAL", "NODETREE"], f"slots {kinds}")
    sc = ctx.scene
    sc.frame_set(1)
    lf0 = mat.adm.layer_factor
    sc.frame_set(int(1 + 2 * sc.render.fps))
    lf1 = mat.adm.layer_factor
    print(f"   layer_factor {lf0} -> {lf1}")
    check(lf1 > lf0, "layer_factor animates")
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    for seconds, expected in ((0, 0.45), (1, 0.625), (2, 0.8)):
        sc.frame_set(round(1 + seconds * sc.render.fps / sc.render.fps_base))
        value = bsdf.inputs["Roughness"].default_value
        check(abs(value - expected) <= 1e-5, f"PBR fallback roughness t={seconds}: {value}")

    exp = AnimExporter(ctx, slib)
    data, rep = exp.export()
    print("   export warnings:", exp.warnings)
    check(rep is not None and rep.ok, f"anim re-export valid {errs(rep)}")
    chans = rep.doc["clips"][0]["channels"]
    got = {(c["target"]["kind"], c["target"]["parameter"]) for c in chans}
    print("   channels:", got)
    check(got == {("shaderParameter", "layer_factor"), ("pbrParameter", "roughnessFactor")}, "channels round-trip")
    anim_path = os.path.join(tmp, "dirty.adm_anim")
    with open(anim_path, "wb") as fh:
        fh.write(data)
    for p in (model_path, anim_path):
        r = validate_file(p)
        check(r.ok, f"validate_file {os.path.basename(p)} {errs(r)}")

    print("== catalog-only.adm_anim without a rig")
    try:
        imp, slib = import_library(ctx, os.path.join(FIX, "catalog-only.adm_anim"), AnimImportOptions(armature=None))
        print("   imported:", slib.lib_id, imp.warnings)
    except Exception as exc:  # noqa: BLE001
        print("   refused:", type(exc).__name__, exc)
        check(type(exc).__name__ == "ImportError_", "clean refusal without rig")

    print("== KTX2 primary / portable PNG fallback")
    from adm_blender.core import gputex
    builder = BinBuilder()
    red = np.array([[[255, 0, 0, 255]]], dtype=np.uint8)
    primary = builder.add_view(gputex.encode(red, gputex.MIME_KTX2, "BC1", srgb=True)[0], chunk_type="IMAG")
    alternate = builder.add_view(encode_png(1, 1, b"\xff\x00\x00\xff"), chunk_type="IMAG")
    doc = {"asset": {}, "nodes": [{}], "scenes": [{"nodes": [0]}], "scene": 0, "meshes": [],
           "bufferViews": builder.buffer_views, "accessors": [],
           "images": [{"bufferView": primary, "mimeType": "image/ktx2"},
                      {"bufferView": alternate, "mimeType": "image/png"}],
           "textures": [{"source": 0, "fallbackSource": 1}],
           "materials": [{"baseColorTexture": {"index": 0}}]}
    ktx_path = os.path.join(tmp, "ktx_fallback.adm")
    with open(ktx_path, "wb") as fh:
        fh.write(write_container(K.ADM_MAGIC, doc, builder.bytes()))
    importer = ModelImporter(ctx, ktx_path, ImportOptions())
    importer.run()
    check(importer.images[0] is None, "KTX2 primary left to GPU runtimes, not imported")
    check(importer.images[1] is not None, "portable PNG decoded")
    image, _ = importer.resolve_texture({"index": 0})
    check(image == importer.images[1], "material resolves portable fallback image")
    check(any(w.startswith("KTX2_FALLBACK") for w in importer.warnings), "fallback explicitly reported")

    adm_blender.unregister()


try:
    with tempfile.TemporaryDirectory(prefix="adm_test_") as tmp:
        main(tmp)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
sys.stdout.flush()
os._exit(0 if not FAILS else 1)
