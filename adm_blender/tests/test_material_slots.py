"""Blender test: ADM material texture slots (Sollumz-style texture parameters).

Run: blender -b --factory-startup --python adm_blender/tests/test_material_slots.py
Checks that slot editing builds node chains the exporter reads, survives export/import, and that
removing a slot keeps factors and leaves no orphan nodes.
"""
import os
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy  # noqa: E402

import adm_blender  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def image(name, rgba, size=4):
    img = bpy.data.images.new(name, size, size, alpha=True)
    img.pixels = list(rgba) * (size * size)
    img.pack()
    return img


def main(tmp):
    adm_blender.register()
    from adm_blender.blender import materials as M
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = bpy.context.active_object
    cube.data.uv_layers.new(name="Detail")
    mat = bpy.data.materials.new("Slots")
    cube.data.materials.append(mat)
    check(bpy.ops.adm.create_model_root(name="Box") == {"FINISHED"}, "create_model_root")
    root = bpy.data.objects["Box"]
    bpy.context.view_layer.objects.active = cube

    print("== slot authoring")
    mat.adm.alpha_mode = "AUTO"
    base = image("base", (1.0, 0.5, 0.25, 0.5))
    mat.adm.pick_base_color = base
    check(mat.adm.pick_base_color is None, "picker resets after assigning")
    check(M.slot_texture_node(mat, "BASE_COLOR").image == base, "base color node created")
    check(bpy.ops.adm.material_texture_alpha(use=True) == {"FINISHED"} and M.slot_alpha_linked(mat),
          "alpha from texture")
    mat.adm.pick_metallic_roughness = image("mr", (0.0, 0.3, 0.8, 1.0))
    check(base.colorspace_settings.name == "sRGB", "base color stays sRGB")
    check(M.slot_texture_node(mat, "METALLIC_ROUGHNESS").image.colorspace_settings.name == "Non-Color",
          "metallic-roughness is Non-Color")
    npath = os.path.join(tmp, "normal.png")
    nimg = image("normal_src", (0.5, 0.5, 1.0, 1.0))
    nimg.filepath_raw, nimg.file_format = npath, "PNG"
    nimg.save()
    check(bpy.ops.adm.material_texture_open(slot="NORMAL", filepath=npath) == {"FINISHED"}, "open normal file")
    check(bpy.ops.adm.material_texture_uv(slot="NORMAL", index=1) == {"FINISHED"}, "normal uses UV1")
    M.normal_map_node(mat).inputs["Strength"].default_value = 0.5
    mat.adm.pick_occlusion = image("ao", (0.8, 0.8, 0.8, 1.0))
    mat.adm.occlusion_strength = 0.7
    mat.adm.pick_emissive = image("glow", (1.0, 1.0, 1.0, 1.0))
    M.principled_of(mat).inputs["Emission Strength"].default_value = 2.0
    check(all(M.slot_state(mat, s)[0] == "TEXTURE" for s in M.SLOT_IDS), "all five slots filled")
    uvn = M._from(M.slot_texture_node(mat, "NORMAL").inputs["Vector"]).node
    check(uvn.type == "UVMAP" and uvn.uv_map == "Detail", f"UV1 resolves to the mesh's 2nd UV ({uvn.uv_map})")

    print("== export")
    exp = ModelExporter(bpy.context, root, ExportOptions())
    data, rep = exp.export()
    check(rep.ok, "model valid")
    m = rep.doc["materials"][0]
    keys = {k for k in m if k.endswith("Texture")}
    check(keys == {"baseColorTexture", "metallicRoughnessTexture", "normalTexture", "occlusionTexture",
                   "emissiveTexture"}, f"exported textures {sorted(keys)}")
    check(m["normalTexture"].get("texCoord") == 1 and abs(m["normalTexture"].get("scale", 1) - 0.5) < 1e-6,
          f"normal texCoord/scale {m['normalTexture']}")
    check(abs(m["occlusionTexture"].get("strength", 1) - 0.7) < 1e-6, "occlusion strength")
    check(all(abs(v - 2.0) < 1e-6 for v in m.get("emissiveFactor", [])), f"emissive {m.get('emissiveFactor')}")
    check(m.get("alphaMode") == "BLEND", f"alpha mode {m.get('alphaMode')}")
    path = os.path.join(tmp, "slots.adm")
    with open(path, "wb") as fh:
        fh.write(data)

    print("== import")
    ModelImporter(bpy.context, path, ImportOptions()).run()
    mat2 = next(x for x in bpy.data.materials if x != mat and x.name.startswith("Slots"))
    check(all(M.slot_state(mat2, s)[0] == "TEXTURE" for s in M.SLOT_IDS), "imported material shows all slots")
    check(M.slot_uv_index(M.slot_texture_node(mat2, "NORMAL"), M.UV_NAMES) == 1, "imported normal on UV1")

    print("== remove slots")
    bsdf = M.principled_of(mat)
    mr = M.slot_texture_node(mat, "METALLIC_ROUGHNESS")
    check(bpy.ops.adm.material_texture_clear(slot="METALLIC_ROUGHNESS") == {"FINISHED"}, "clear metallic-roughness")
    check(mr.name not in [n.name for n in mat.node_tree.nodes] and
          not any(n.type == "SEPARATE_COLOR" for n in mat.node_tree.nodes), "MR texture and separate node removed")
    check(not bsdf.inputs["Roughness"].is_linked and abs(bsdf.inputs["Roughness"].default_value - 1.0) < 1e-6,
          "roughness keeps factor 1.0")
    check(bpy.ops.adm.material_texture_clear(slot="NORMAL") == {"FINISHED"}, "clear normal")
    check(not any(n.type in ("NORMAL_MAP", "UVMAP") for n in mat.node_tree.nodes), "normal map + UV node removed")
    check(bpy.ops.adm.material_texture_clear(slot="BASE_COLOR") == {"FINISHED"}, "clear base color")
    check(not bsdf.inputs["Alpha"].is_linked and not bsdf.inputs["Base Color"].is_linked, "base + alpha unlinked")
    m = ModelExporter(bpy.context, root, ExportOptions()).export()[1].doc["materials"][0]
    check({k for k in m if k.endswith("Texture")} == {"occlusionTexture", "emissiveTexture"},
          f"after removal {sorted(k for k in m if k.endswith('Texture'))}")

    print("== custom node setups are not overwritten")
    other = bpy.data.materials.new("Custom")
    M.convert_to_adm_material(other)
    noise = other.node_tree.nodes.new("ShaderNodeTexNoise")
    other.node_tree.links.new(noise.outputs["Color"], M.principled_of(other).inputs["Emission Color"])
    check(M.slot_state(other, "EMISSIVE")[0] == "CUSTOM", "noise-driven emission is CUSTOM")
    try:
        M.set_slot_image(other, "EMISSIVE", base)
        check(False, "custom setup protected")
    except ValueError:
        check(M.principled_of(other).inputs["Emission Color"].links[0].from_node == noise, "custom setup protected")
    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_slots_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
