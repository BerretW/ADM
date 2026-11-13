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
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter
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

    print("== custom node setups are replaced, not destroyed")
    other = bpy.data.materials.new("Custom")
    M.convert_to_adm_material(other)
    nt = other.node_tree
    bsdf = M.principled_of(other)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    nt.links.new(noise.outputs["Color"], bsdf.inputs["Emission Color"])
    check(M.slot_state(other, "EMISSIVE")[0] == "CUSTOM", "noise-driven emission is CUSTOM")
    M.set_slot_image(other, "EMISSIVE", base)
    check(M.slot_texture_node(other, "EMISSIVE").image == base, "picking replaces the custom setup")
    check(noise.name in nt.nodes and not noise.outputs["Color"].is_linked, "custom nodes kept, only detached")

    print("== texture adoption from imported-style graphs")
    albedo, dirt = image("wall_ab", (0.5, 0.4, 0.3, 1.0)), image("walldirt", (0.2, 0.2, 0.2, 1.0))
    pal, mrao = image("house_pal", (1, 0, 0, 1)), image("wall_ma", (0.0, 0.5, 1.0, 1.0))
    mrao.colorspace_settings.name = "Non-Color"

    def tex(img, label, y):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image, n.label, n.location = img, label, (-1200, y)
        return n
    t_dirt, t_alb = tex(dirt, "", 0), tex(albedo, "Albedo", 300)
    t_pal, t_mr = tex(pal, "Palette", 600), tex(mrao, "MRAO", -300)
    t_alb.interpolation, t_alb.extension = "Closest", "MIRROR"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    pmix = nt.nodes.new("ShaderNodeMix")
    pmix.data_type = "RGBA"
    nt.links.new(t_dirt.outputs["Color"], M._sock(mix, "A_Color"))
    nt.links.new(t_pal.outputs["Color"], M._sock(pmix, "A_Color"))
    nt.links.new(t_alb.outputs["Color"], M._sock(pmix, "B_Color"))
    nt.links.new(M._out(pmix, "Result_Color"), M._sock(mix, "B_Color"))
    nt.links.new(M._out(mix, "Result_Color"), bsdf.inputs["Base Color"])
    math = nt.nodes.new("ShaderNodeMath")
    nt.links.new(t_mr.outputs["Color"], math.inputs[0])
    nt.links.new(t_alb.outputs["Alpha"], math.inputs[1])
    nt.links.new(math.outputs[0], bsdf.inputs["Roughness"])
    cands = M.custom_source_candidates(other, "BASE_COLOR")
    check([n.image for n in cands] == [albedo, dirt], f"albedo ranked first, palette excluded: "
                                                       f"{[n.image.name for n in cands]}")
    check(M.custom_source_node(other, "METALLIC_ROUGHNESS") == t_mr, "MRAO chosen for metallic-roughness")
    bpy.context.view_layer.objects.active = cube
    cube.active_material_index = 0
    cube.data.materials[0] = other
    check(bpy.ops.adm.material_texture_adopt(slot="BASE_COLOR") == {"FINISHED"}, "adopt operator")
    node = M.slot_texture_node(other, "BASE_COLOR")
    check(node is not None and node.image == albedo and node != t_alb, "adopted albedo as simple chain")
    check((node.interpolation, node.extension) == ("Closest", "MIRROR"), "sampler copied from source")
    check(not M._out(mix, "Result_Color").is_linked and mix.name in nt.nodes, "original graph detached and kept")

    print("== switching shader rebuilds the viewport preview")
    other.adm.shader = "LAYERED"
    active = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output]
    check(len(active) == 1 and M.is_preview_node(active[0]), "layered preview output active")
    check(M.principled_of(other) == bsdf, "exporter still reads the material's own BSDF")
    other.adm.layer_base.base_color = (0.0, 0.0, 1.0, 1.0)
    other.adm.layer_overlay.base_color = (1.0, 0.0, 0.0, 1.0)
    other.adm.layer_overlay.roughness = 0.2
    other.adm.layer_factor = 0.25
    bpy.context.view_layer.update()
    pb = nt.nodes[M.PREVIEW_PREFIX + " BSDF"]
    fac = nt.nodes[M.PREVIEW_PREFIX + " Layer Factor"]
    check(abs(fac.inputs[0].default_value - 0.25) < 1e-6, "layer_factor drives the preview")
    rmix = M._from(pb.inputs["Roughness"]).node
    check(abs(M._sock(rmix, "B_Float").default_value - 0.2) < 1e-6, "overlay roughness in preview")
    cmix = M._from(pb.inputs["Base Color"]).node
    check(tuple(M._sock(cmix, "A_Color").default_value) == (0.0, 0.0, 1.0, 1.0), "base color in preview")
    other.adm.layer_mask = pal
    check(M.PREVIEW_PREFIX + " Mask" in nt.nodes, "mask texture in preview")
    other.adm.shader = "CORE"
    check(not any(M.is_preview_node(n) for n in nt.nodes), "preview removed on CORE")
    check(not nt.animation_data or not len(nt.animation_data.drivers), "preview drivers removed")
    check(M.material_output(other).is_active_output, "own output active again")
    other.adm.shader = "CUSTOM"
    check(not any(M.is_preview_node(n) for n in nt.nodes), "custom shows PBR fallback")
    from adm_blender.core import constants as K
    probe_key = ("org.example.registry_probe", "1.0.0")
    K.OFFICIAL_SHADERS[probe_key] = [
        {"name": "gain", "type": "F32", "default": 1.5, "minimum": 0.0, "maximum": 3.0,
         "description": "Probe scalar."},
        {"name": "tint", "type": "VEC3", "default": [0.2, 0.4, 0.6],
         "description": "Probe vector."},
        {"name": "image", "type": "TEXTURE", "default": None, "description": "Probe texture."},
    ]
    M.sync_official_shader_params(other, probe_key)
    check(abs(other.adm.params["gain"].value_f - 1.5) < 1e-6 and
          all(abs(float(a) - b) < 1e-6 for a, b in zip(other.adm.params["tint"].value_vec[:3],
                                                        (0.2, 0.4, 0.6))) and
          other.adm.params["image"].image is None, "official typed parameter defaults synchronize")
    del K.OFFICIAL_SHADERS[probe_key]
    M.sync_official_shader_params(other, K.SHADER_EMISSIVE)
    check(len(other.adm.params) == 0, "official parameter synchronization removes stale entries")

    print("== cutout shader profile")
    other.adm.shader = "CUTOUT"
    check(other.adm.alpha_mode == "MASK", "selecting cutout requires Mask alpha mode")
    check(not any(M.is_preview_node(n) for n in nt.nodes), "cutout uses the standard PBR node tree")
    cutout_data, cutout_report = ModelExporter(bpy.context, root, ExportOptions()).export()
    check(cutout_report.ok, "cutout model validates on export")
    cutout_mat = cutout_report.doc["materials"][0]
    check(cutout_mat.get("shader") == {"id": "adm.surface.cutout", "version": "1.0.0"},
          "cutout shader identity exported exactly")
    check(cutout_mat.get("alphaMode") == "MASK", "cutout alpha mode exported")
    cutout_path = os.path.join(tmp, "cutout.adm")
    with open(cutout_path, "wb") as fh:
        fh.write(cutout_data)
    ModelImporter(bpy.context, cutout_path, ImportOptions()).run()
    imported_cutout = next(x for x in bpy.data.materials if x.adm.shader == "CUTOUT")
    check(imported_cutout.adm.alpha_mode == "MASK", "cutout alpha mode survives import")
    other.adm.alpha_mode = "OPAQUE"
    try:
        ModelExporter(bpy.context, root, ExportOptions()).export()
        check(False, "invalid cutout alpha mode rejected on export")
    except ExportError as exc:
        check("requires Alpha Mode MASK" in str(exc), f"invalid cutout alpha mode rejected: {exc}")

    print("== emissive shader profile")
    other.adm.alpha_mode = "AUTO"
    other.adm.shader = "EMISSIVE"
    bsdf = M.principled_of(other)
    for link in list(bsdf.inputs["Emission Color"].links):
        nt.links.remove(link)
    bsdf.inputs["Emission Color"].default_value = (0.2, 0.3, 0.4, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 2.0
    emissive_data, emissive_report = ModelExporter(bpy.context, root, ExportOptions()).export()
    check(emissive_report.ok, "emissive model validates on export")
    emissive_mat = emissive_report.doc["materials"][0]
    check(emissive_mat.get("shader") == {"id": "adm.surface.emissive", "version": "1.0.0"},
          "emissive shader identity exported exactly")
    check(all(abs(a - b) < 1e-6 for a, b in zip(emissive_mat.get("emissiveFactor", []), (0.4, 0.6, 0.8))),
          f"emissive factor includes strength: {emissive_mat.get('emissiveFactor')}")
    emissive_path = os.path.join(tmp, "emissive.adm")
    with open(emissive_path, "wb") as fh:
        fh.write(emissive_data)
    ModelImporter(bpy.context, emissive_path, ImportOptions()).run()
    imported_emissive = next(x for x in bpy.data.materials if x.adm.shader == "EMISSIVE")
    check(imported_emissive.adm.shader_key() == ("adm.surface.emissive", "1.0.0"),
          "emissive identity survives import")
    bsdf.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 0.0
    try:
        ModelExporter(bpy.context, root, ExportOptions()).export()
        check(False, "empty emissive profile rejected on export")
    except ExportError as exc:
        check("requires nonzero emissive output" in str(exc), f"empty emission rejected: {exc}")

    print("== decal shader profile")
    other.adm.shader = "DECAL"
    check(other.adm.alpha_mode == "BLEND", "selecting decal requires Blend alpha mode")
    decal_data, decal_report = ModelExporter(bpy.context, root, ExportOptions()).export()
    check(decal_report.ok, "decal model validates on export")
    decal_mat = decal_report.doc["materials"][0]
    check(decal_mat.get("shader") == {"id": "adm.surface.decal", "version": "1.0.0"} and
          decal_mat.get("alphaMode") == "BLEND", "decal identity and blend mode exported")
    decal_path = os.path.join(tmp, "decal.adm")
    with open(decal_path, "wb") as fh:
        fh.write(decal_data)
    ModelImporter(bpy.context, decal_path, ImportOptions()).run()
    imported_decal = next(x for x in bpy.data.materials if x.adm.shader == "DECAL")
    check(imported_decal.adm.alpha_mode == "BLEND", "decal alpha mode survives import")
    other.adm.alpha_mode = "OPAQUE"
    try:
        ModelExporter(bpy.context, root, ExportOptions()).export()
        check(False, "invalid decal alpha mode rejected on export")
    except ExportError as exc:
        check("requires Alpha Mode BLEND" in str(exc), f"invalid decal alpha mode rejected: {exc}")

    print("== generic official shader parameter round-trip")
    other.adm.shader = "GLASS"
    check(other.adm.alpha_mode == "BLEND", "glass selection requires Blend alpha mode")
    check(all(other.adm.params.get(name) is not None for name in
              ("glass_tint", "reflection_tint", "transparency", "ior")),
          "glass schema defaults synchronize")
    other.adm.params["transparency"].use = True
    other.adm.params["transparency"].value_f = 0.6
    glass_data, glass_report = ModelExporter(bpy.context, root, ExportOptions()).export()
    check(glass_report.ok, "glass model validates on export")
    glass_mat = glass_report.doc["materials"][0]
    check(glass_mat.get("shader") == {"id": "adm.surface.glass", "version": "1.0.0"} and
          abs(glass_mat.get("shaderParameters", {}).get("transparency", 0.0) - 0.6) < 1e-6,
          "glass identity and typed parameter exported")
    glass_path = os.path.join(tmp, "glass.adm")
    with open(glass_path, "wb") as fh:
        fh.write(glass_data)
    ModelImporter(bpy.context, glass_path, ImportOptions()).run()
    imported_glass = next(x for x in bpy.data.materials if x.adm.shader == "GLASS")
    check(abs(imported_glass.adm.params["transparency"].value_f - 0.6) < 1e-6 and
          imported_glass.adm.params["transparency"].use, "glass parameter survives import")
    other.adm.alpha_mode = "OPAQUE"
    try:
        ModelExporter(bpy.context, root, ExportOptions()).export()
        check(False, "invalid glass alpha mode rejected on export")
    except ExportError as exc:
        check("requires Alpha Mode BLEND" in str(exc), f"invalid glass alpha mode rejected: {exc}")
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
