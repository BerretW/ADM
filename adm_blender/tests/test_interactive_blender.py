"""Headless Blender integration tests for interactive surface authoring and round-trip."""

import copy
import os
import struct
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender

FAILS = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        FAILS.append(message)


def select_faces(obj, indices):
    for candidate in bpy.context.selected_objects:
        candidate.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for poly in obj.data.polygons:
        poly.select = poly.index in indices


def main(tmp):
    from adm_blender.blender import material_anim, materials
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter, export_model
    from adm_blender.blender.export_anim import AnimExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.core import constants as K
    from adm_blender.core.buffers import read_accessor
    from adm_blender.core.container import ChunkCollection, read_container, write_container
    from adm_blender.core.validate import material_binding_issues, validate_adm, validate_adm_resolved

    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    root = bpy.data.objects.new("Terminal", None)
    root.adm.adm_type = "MODEL"
    bpy.context.scene.collection.objects.link(root)
    me = bpy.data.meshes.new("TerminalGeometry")
    me.from_pydata(
        [(0, 0, 0), (1, 0, 0.1), (2, 0, 0), (0, 1, 0), (1, 1, 0.1), (2, 1, 0),
         (3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0),
         (5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0)],
        [], [(0, 1, 4, 3), (1, 2, 5, 4), (6, 7, 8, 9), (10, 11, 12, 13)])
    me.update()
    obj = bpy.data.objects.new("ScreensAndFrame", me)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = root
    obj.location = (1, 2, 3)
    for name in ("UVMap", "UVSecond"):
        me.uv_layers.new(name=name)
    for poly in me.polygons:
        for corner, li in enumerate(poly.loop_indices):
            u, v = ((0, 0), (1, 0), (1, 1), (0, 1))[corner]
            me.uv_layers[0].uv[li].vector = (u, v)
            me.uv_layers[1].uv[li].vector = (1 - u, v)
    for name, color in (("COLOR_0", (0.25, 0.8, 0.9, 0.1)), ("COLOR_1", (0.2, 0.3, 0.4, 0.5))):
        attr = me.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
        for item in attr.data:
            item.color = color

    screen = bpy.data.materials.new("Shared Screen")
    materials.convert_to_adm_material(screen)
    screen.adm.shader = "INTERACTIVE"
    screen.adm.animation_id = "shared_screen"
    screen.adm.params["brightness"].value_f = 2.5
    screen.adm.params["emissive_strength"].value_f = 0.75
    screen.adm.params["unlit"].value_bool = False
    screen.adm.vertex_controls_enabled = True
    fallback = bpy.data.images.new("Screen Fallback", 2, 2, alpha=True)
    fallback.pixels = [0.2, 0.4, 0.6, 1.0] * 4
    fallback.pack()
    image_node = screen.node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = fallback
    screen.node_tree.links.new(image_node.outputs["Color"], materials.principled_of(screen).inputs["Base Color"])
    palette = bpy.data.images.new("Screen Palette", 2, 1, alpha=True)
    palette.pixels = [1.0, 0.5, 0.5, 1.0, 0.5, 1.0, 0.5, 1.0]
    palette.pack()
    screen.adm.vertex_tint_palette = palette
    frame = bpy.data.materials.new("Frame")
    materials.convert_to_adm_material(frame)
    me.materials.append(screen)
    me.materials.append(frame)
    me.polygons[3].material_index = 1

    for indices, ident, uv, ratio in (({0, 1}, "main_display", "0", 16 / 9),
                                      ({2}, "side_display", "1", 1.0)):
        select_faces(obj, indices)
        obj.adm.interactive_surface_id = ident
        obj.adm.interactive_tex_coord = uv
        obj.adm.interactive_aspect_ratio = ratio
        check(bpy.ops.adm.interactive_surface_assign_faces() == {"FINISHED"}, f"assign {ident}")

    options = ExportOptions(vertex_controls=True)
    data, report = ModelExporter(bpy.context, root, options).export()
    check(report.ok, "embedded fallback export validates")
    doc = report.doc
    surfaces = {s["surfaceId"]: s for s in doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]}
    check(set(surfaces) == {"main_display", "side_display"}, "two independently identified screens")
    check([surfaces[name]["bindings"][0]["texCoord"] for name in ("main_display", "side_display")] == [0, 1],
          "independent UV sets")
    binding_materials = []
    counts = []
    for name in ("main_display", "side_display"):
        binding = surfaces[name]["bindings"][0]
        node = doc["nodes"][binding["node"]]
        primitive = doc["meshes"][node["mesh"]]["primitives"][binding["primitive"]]
        binding_materials.append(primitive["material"])
        counts.append(doc["accessors"][primitive["indices"]]["count"] // 3)
        check("COLOR_0" in primitive["attributes"] and "COLOR_1" in primitive["attributes"],
              f"{name}: vertex controls preserved")
    check(binding_materials[0] == binding_materials[1] and counts == [4, 2],
          "shared material split into screen primitives; curved screen keeps four triangles")
    screen_doc = doc["materials"][binding_materials[0]]
    check(screen_doc["animationId"] == "shared_screen" and
          screen_doc["shaderParameters"] == {"brightness": 2.5, "emissive_strength": 0.75, "unlit": False},
          "typed shader parameters and material animation ID")
    check(K.VERTEX_CONTROL_EXT in doc["extensionsRequired"] and
          "tintPalette" in screen_doc["extensions"][K.VERTEX_CONTROL_EXT],
          "required vertex controls and tint palette coexist")
    check("bufferView" in doc["images"][doc["textures"][screen_doc["baseColorTexture"]["index"]]["source"]],
          "fallback texture embedded")

    path = os.path.join(tmp, "terminal.adm")
    with open(path, "wb") as stream:
        stream.write(data)
    importer = ModelImporter(bpy.context, path, ImportOptions())
    imported_root = importer.run()
    imported_obj = next(o for o in importer.node_obj.values() if o.type == "MESH")
    ids = imported_obj.data.attributes["adm_interactive_surface_id"]
    face_ids = [item.value.decode("utf-8") for item in ids.data]
    check(face_ids.count("main_display") == 4 and face_ids.count("side_display") == 2,
          "import restores face-level surface IDs")
    chosen = next(i for i, ident in enumerate(face_ids) if ident == "side_display")
    select_faces(imported_obj, {chosen})
    check(bpy.ops.adm.interactive_surface_assign_faces(load=True) == {"FINISHED"} and
          imported_obj.adm.interactive_surface_id == "side_display" and
          imported_obj.adm.interactive_tex_coord == "1", "inspect imported face assignment")
    _, again = ModelExporter(bpy.context, imported_root, options).export()
    restored = {s["surfaceId"]: s for s in again.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]}
    check(set(restored) == set(surfaces) and
          [restored[name]["bindings"][0]["texCoord"] for name in ("main_display", "side_display")] == [0, 1] and
          abs(restored["main_display"]["aspectRatio"] - 16 / 9) < 1e-6,
          "round-trip preserves IDs, UV sets and aspect ratio")
    imported_screen = next(m for m in importer.materials if m.adm.shader == "INTERACTIVE")
    check(imported_screen.adm.animation_id == "shared_screen" and
          imported_screen.adm.params["brightness"].value_f == 2.5 and
          not imported_screen.adm.params["unlit"].value_bool,
          "round-trip preserves interactive parameters")

    ordinary_doc, ordinary_chunks = read_container(data, K.ADM_MAGIC)
    for key in ("extensionsUsed", "extensionsRequired"):
        ordinary_doc[key] = [name for name in ordinary_doc.get(key, []) if name != K.VERTEX_CONTROL_EXT]
        if not ordinary_doc[key]:
            del ordinary_doc[key]
    for material in ordinary_doc["materials"]:
        if "extensions" in material:
            material["extensions"].pop(K.VERTEX_CONTROL_EXT, None)
            if not material["extensions"]:
                del material["extensions"]
    ordinary_payloads = {cid: bytes(payload) for cid, payload in ordinary_chunks.items()}
    for primitive in ordinary_doc["meshes"][0]["primitives"]:
        primitive["attributes"].pop("COLOR_1", None)
        if primitive.get("material") != binding_materials[0]:
            primitive["attributes"].pop("COLOR_0", None)
        else:
            accessor = ordinary_doc["accessors"][primitive["attributes"]["COLOR_0"]]
            view = ordinary_doc["bufferViews"][accessor["bufferView"]]
            payload = bytearray(ordinary_payloads[view["chunkId"]])
            offset = view["byteOffset"] + accessor.get("byteOffset", 0)
            for index in range(accessor["count"]):
                struct.pack_into("<4f", payload, offset + 16 * index, -0.5, 2.0, 0.25, 1.5)
            ordinary_payloads[view["chunkId"]] = bytes(payload)
    ordinary_chunks = ChunkCollection(ordinary_payloads, chunk_types={cid: entry.chunk_type
                                      for cid, entry in ordinary_chunks.entries.items()})
    ordinary_data = write_container(K.ADM_MAGIC, ordinary_doc, ordinary_chunks)
    ordinary_report = validate_adm(ordinary_data)
    check(ordinary_report.ok, f"mixed ordinary COLOR_0 model is valid: {ordinary_report.format()}")
    ordinary_path = os.path.join(tmp, "ordinary_color.adm")
    with open(ordinary_path, "wb") as stream:
        stream.write(ordinary_data)
    ordinary_root = ModelImporter(bpy.context, ordinary_path, ImportOptions()).run()
    _, ordinary_again = ModelExporter(bpy.context, ordinary_root, ExportOptions()).export()
    screen_colors, frame_colors = [], []
    for mesh in ordinary_again.doc["meshes"]:
        for primitive in mesh["primitives"]:
            material = ordinary_again.doc["materials"][primitive["material"]]
            colors = read_accessor(ordinary_again.doc, ordinary_again.bin, primitive["attributes"]["COLOR_0"])
            if material.get("shader", {}).get("id") == K.SHADER_INTERACTIVE[0]:
                screen_colors.extend(colors)
            else:
                frame_colors.extend(colors)
    check(screen_colors and frame_colors and
          all(all(abs(actual - expected) < 1e-6 for actual, expected in zip(color, (-0.5, 2.0, 0.25, 1.5)))
              for color in screen_colors) and
          all(all(abs(component - 1.0) < 1e-6 for component in color) for color in frame_colors),
          "mixed ordinary HDR COLOR_0 survives and missing colors remain neutral")

    tiny_doc, tiny_chunks = read_container(data, K.ADM_MAGIC)
    tiny_surface = tiny_doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"][0]
    tiny_surface["aspectRatio"] = 1e-45
    tiny_path = os.path.join(tmp, "tiny_aspect.adm")
    with open(tiny_path, "wb") as stream:
        stream.write(write_container(K.ADM_MAGIC, tiny_doc, tiny_chunks))
    tiny_root = ModelImporter(bpy.context, tiny_path, ImportOptions()).run()
    _, tiny_roundtrip = ModelExporter(bpy.context, tiny_root, options).export()
    tiny_actual = next(s["aspectRatio"] for s in
                       tiny_roundtrip.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]
                       if s["surfaceId"] == tiny_surface["surfaceId"])
    check(tiny_actual == struct.unpack("<f", struct.pack("<f", 1e-45))[0],
          "smallest positive binary32 aspect ratio survives round-trip")

    select_faces(obj, {0})
    obj.data.vertices[0].co.x += 0.02
    obj.data.update()
    obj.active_material_index = 1
    check(bpy.ops.object.material_slot_move(direction="UP") == {"FINISHED"}, "reorder Blender material slots")
    _, edited = ModelExporter(bpy.context, root, options).export()
    edited_ids = {s["surfaceId"] for s in edited.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]}
    check(edited_ids == set(surfaces), "geometry edits and material-slot order do not change surface IDs")
    modifier = obj.modifiers.new("Test Triangulation", "TRIANGULATE")
    _, modified = ModelExporter(bpy.context, root, options).export()
    modified_ids = {s["surfaceId"] for s in modified.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]}
    check(modified_ids == set(surfaces), "evaluated triangulation preserves surface assignments")
    obj.modifiers.remove(modifier)

    uv_node = screen.node_tree.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = "UVSecond"
    screen.node_tree.links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])
    side_uv = obj.data.attributes["adm_interactive_texcoord"].data[2]
    side_uv.value = 0
    try:
        ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True, export_uv1=False)).export()
    except ExportError as exc:
        check("UVSecond" in str(exc), "missing fallback texture UV is rejected instead of guessed")
    else:
        check(False, "missing fallback texture UV is rejected instead of guessed")
    side_uv.value = 1
    screen.node_tree.nodes.remove(uv_node)

    normal_image = bpy.data.images.new("Interactive Normal", 2, 2, alpha=True)
    normal_image.pixels = [0.5, 0.5, 1.0, 1.0] * 4
    normal_image.pack()
    normal_tex = screen.node_tree.nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal_image
    normal_map = screen.node_tree.nodes.new("ShaderNodeNormalMap")
    normal_uv = screen.node_tree.nodes.new("ShaderNodeUVMap")
    normal_uv.uv_map = normal_map.uv_map = "UVSecond"
    screen.node_tree.links.new(normal_uv.outputs["UV"], normal_tex.inputs["Vector"])
    screen.node_tree.links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    screen.node_tree.links.new(normal_map.outputs["Normal"], materials.principled_of(screen).inputs["Normal"])
    normal_map.uv_map = ""
    try:
        ModelExporter(bpy.context, root, options).export()
    except ExportError as exc:
        check("normal-map tangent and image UV sets differ" in str(exc),
              "mismatched normal-map tangent UV is rejected")
    else:
        check(False, "mismatched normal-map tangent UV is rejected")
    normal_map.uv_map = "UVSecond"
    _, with_normal = ModelExporter(bpy.context, root, options).export()
    normal_prims = []
    for surface in with_normal.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]:
        binding = surface["bindings"][0]
        node = with_normal.doc["nodes"][binding["node"]]
        normal_prims.append(with_normal.doc["meshes"][node["mesh"]]["primitives"][binding["primitive"]])
    normal_material = with_normal.doc["materials"][normal_prims[0]["material"]]
    tangent_values = [value for primitive in normal_prims for value in
                      read_accessor(with_normal.doc, with_normal.bin, primitive["attributes"]["TANGENT"])]
    check(normal_material["normalTexture"].get("texCoord") == 1 and
          all(value[0] < -0.8 and value[3] > 0.9 for value in tangent_values),
          "normal-map tangents follow the fallback texture's mirrored UV 1")
    frame_tangents = [value for mesh in with_normal.doc["meshes"] for primitive in mesh["primitives"]
                      if primitive["material"] != normal_prims[0]["material"] for value in
                      read_accessor(with_normal.doc, with_normal.bin, primitive["attributes"]["TANGENT"])]
    check(frame_tangents and all(value[0] > 0.8 and value[3] < -0.9 for value in frame_tangents),
          "other material tangents retain their own UV set and ADM handedness")
    for node in (normal_uv, normal_tex, normal_map):
        screen.node_tree.nodes.remove(node)

    uv_node = screen.node_tree.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = "UVSecond"
    screen.node_tree.links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])
    clone = obj.copy()
    clone.data = obj.data.copy()
    clone_mesh = clone.data
    bpy.context.scene.collection.objects.link(clone)
    clone.parent = root
    clone_mesh.uv_layers["UVSecond"].active_render = True
    for item in clone_mesh.attributes["adm_interactive_surface_id"].data:
        if item.value:
            item.value = item.value + b"_copy"
    try:
        ModelExporter(bpy.context, root, options).export()
    except ExportError as exc:
        check("different UV set indices" in str(exc), "shared material with inconsistent UV order is rejected")
    else:
        check(False, "shared material with inconsistent UV order is rejected")
    bpy.data.objects.remove(clone, do_unlink=True)
    bpy.data.meshes.remove(clone_mesh)
    screen.node_tree.nodes.remove(uv_node)

    mapping = screen.node_tree.nodes.new("ShaderNodeMapping")
    screen.node_tree.links.new(mapping.outputs["Vector"], image_node.inputs["Vector"])
    try:
        ModelExporter(bpy.context, root, options).export()
    except ExportError as exc:
        check("unsupported UV mapping" in str(exc), "unsupported fallback UV transformation is reported")
    else:
        check(False, "unsupported fallback UV transformation is reported")
    screen.node_tree.nodes.remove(mapping)

    alpha_tex = screen.node_tree.nodes.new("ShaderNodeTexImage")
    alpha_tex.image = fallback
    alpha_uv = screen.node_tree.nodes.new("ShaderNodeUVMap")
    alpha_uv.uv_map = "UVSecond"
    screen.node_tree.links.new(alpha_uv.outputs["UV"], alpha_tex.inputs["Vector"])
    screen.node_tree.links.new(alpha_tex.outputs["Alpha"], materials.principled_of(screen).inputs["Alpha"])
    try:
        ModelExporter(bpy.context, root, options).export()
    except ExportError as exc:
        check("base color and alpha use different UV sets" in str(exc),
              "mismatched fallback alpha UV is rejected")
    else:
        check(False, "mismatched fallback alpha UV is rejected")
    for node in (alpha_uv, alpha_tex):
        screen.node_tree.nodes.remove(node)

    metal_tex = screen.node_tree.nodes.new("ShaderNodeTexImage")
    rough_tex = screen.node_tree.nodes.new("ShaderNodeTexImage")
    metal_tex.image = rough_tex.image = fallback
    metal_uv = screen.node_tree.nodes.new("ShaderNodeUVMap")
    metal_uv.uv_map = "UVSecond"
    screen.node_tree.links.new(metal_uv.outputs["UV"], metal_tex.inputs["Vector"])
    screen.node_tree.links.new(metal_tex.outputs["Color"], materials.principled_of(screen).inputs["Metallic"])
    screen.node_tree.links.new(rough_tex.outputs["Color"], materials.principled_of(screen).inputs["Roughness"])
    try:
        ModelExporter(bpy.context, root, options).export()
    except ExportError as exc:
        check("metallic and roughness textures use different UV sets" in str(exc),
              "incompatible metallic/roughness UV sets are rejected")
    else:
        check(False, "incompatible metallic/roughness UV sets are rejected")
    for node in (metal_uv, metal_tex, rough_tex):
        screen.node_tree.nodes.remove(node)

    for bad_options, phrase in ((ExportOptions(export_uv1=False), "requires exported UV 1"),
                                (ExportOptions(export_materials=False), "require material export")):
        try:
            ModelExporter(bpy.context, root, bad_options).export()
        except ExportError as exc:
            check(phrase in str(exc), f"invalid authoring rejected: {phrase}")
        else:
            check(False, f"invalid authoring rejected: {phrase}")

    for changed_options, phrase in ((ExportOptions(vertex_controls=False), "ADM Vertex Controls are disabled"),
                                    (ExportOptions(vertex_controls=True, export_colors=False),
                                     "Vertex Colors are disabled")):
        changed_exporter = ModelExporter(bpy.context, root, changed_options)
        changed_exporter.export()
        check(any(phrase in warning for warning in changed_exporter.warnings),
              f"warn before omitting interactive controls: {phrase}")

    external_path = os.path.join(tmp, "external", "terminal.adm")
    os.makedirs(os.path.dirname(external_path))
    _, external_report = export_model(bpy.context, external_path, root,
                                      ExportOptions(embed_textures=False, vertex_controls=True))
    with open(external_path, "rb") as stream:
        external_data = stream.read()
    resolved = validate_adm_resolved(external_data, external_path)
    check(external_report.ok and resolved.ok and K.EXTERNAL_IMAGES_EXT in
          external_report.doc["extensionsRequired"], "external fallback is written and resolves")
    external_importer = ModelImporter(bpy.context, external_path, ImportOptions())
    external_root = external_importer.run()
    external_screen = next(m for m in external_importer.materials if m.adm.shader == "INTERACTIVE")
    check("adm_incomplete_textures" not in external_screen and
          any(image is not None for image in external_importer.images),
          "external fallback and palette import successfully")
    external_roundtrip = os.path.join(tmp, "external_roundtrip", "terminal.adm")
    os.makedirs(os.path.dirname(external_roundtrip))
    _, external_again = export_model(bpy.context, external_roundtrip, external_root,
                                     ExportOptions(embed_textures=False, vertex_controls=True))
    with open(external_roundtrip, "rb") as stream:
        external_again_data = stream.read()
    check(validate_adm_resolved(external_again_data, external_roundtrip).ok and
          {s["surfaceId"] for s in external_again.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]} ==
          set(surfaces), "external fallback and surface IDs survive import/re-export")

    original_doc, chunks = read_container(data, K.ADM_MAGIC)
    shared = copy.deepcopy(original_doc)
    clone_node = copy.deepcopy(shared["nodes"][0])
    shared["nodes"].append(clone_node)
    clone_index = len(shared["nodes"]) - 1
    shared["scenes"][0]["nodes"].append(clone_index)
    ext = shared["extensions"][K.INTERACTIVE_SURFACES_EXT]
    for surface in list(ext["surfaces"]):
        clone = copy.deepcopy(surface)
        clone["surfaceId"] += "_copy"
        for binding in clone["bindings"]:
            binding["node"] = clone_index
        ext["surfaces"].append(clone)
    shared_data = write_container(K.ADM_MAGIC, shared, chunks)
    check(validate_adm(shared_data).ok, "shared ADM mesh supports per-node IDs")
    shared_path = os.path.join(tmp, "shared.adm")
    with open(shared_path, "wb") as stream:
        stream.write(shared_data)
    shared_importer = ModelImporter(bpy.context, shared_path, ImportOptions())
    shared_root = shared_importer.run()
    check(shared_importer.node_obj[0].data != shared_importer.node_obj[clone_index].data,
          "different per-node IDs do not share Blender face metadata")
    _, shared_again = ModelExporter(bpy.context, shared_root, options).export()
    shared_ids = {s["surfaceId"] for s in shared_again.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"]}
    check(shared_ids == {"main_display", "side_display", "main_display_copy", "side_display_copy"},
          "shared-mesh node IDs survive import and re-export")

    uv1_only = copy.deepcopy(original_doc)
    side_binding = surfaces["side_display"]["bindings"][0]
    side_primitive = uv1_only["meshes"][0]["primitives"][side_binding["primitive"]]
    side_primitive["attributes"].pop("TEXCOORD_0")
    uv1_only["meshes"][0]["primitives"] = [side_primitive]
    uv1_only["materials"][side_primitive["material"]]["baseColorTexture"]["texCoord"] = 1
    side_surface = copy.deepcopy(surfaces["side_display"])
    side_surface["bindings"][0]["primitive"] = 0
    uv1_only["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"] = [side_surface]
    uv1_data = write_container(K.ADM_MAGIC, uv1_only, chunks)
    uv1_report = validate_adm(uv1_data)
    check(uv1_report.ok, f"screen with TEXCOORD_1 and no TEXCOORD_0 is valid: {uv1_report.format()}")
    uv1_path = os.path.join(tmp, "uv1_only.adm")
    with open(uv1_path, "wb") as stream:
        stream.write(uv1_data)
    uv1_importer = ModelImporter(bpy.context, uv1_path, ImportOptions())
    uv1_root = uv1_importer.run()
    _, uv1_again = ModelExporter(bpy.context, uv1_root, options).export()
    binding = uv1_again.doc["extensions"][K.INTERACTIVE_SURFACES_EXT]["surfaces"][0]["bindings"][0]
    node = uv1_again.doc["nodes"][binding["node"]]
    primitive = uv1_again.doc["meshes"][node["mesh"]]["primitives"][binding["primitive"]]
    before_uv = read_accessor(uv1_only, chunks, side_primitive["attributes"]["TEXCOORD_1"])
    after_uv = read_accessor(uv1_again.doc, uv1_again.bin, primitive["attributes"]["TEXCOORD_1"])
    check(binding["texCoord"] == 1 and set(before_uv) == set(after_uv) and
          any("placeholder UV 0" in warning for warning in uv1_importer.warnings),
          "UV 1-only import preserves required coordinates and reports Blender's placeholder")

    lib = bpy.context.scene.adm_anim.libraries.add()
    lib.lib_id, lib.title, lib.description, lib.target = "screen@brightness", "Screen", "Brightness track", "MODEL_ANY"
    clip = lib.clips.add()
    clip.clip_id, clip.title, clip.description = "switch", "Switch", "Change brightness"
    clip.action = bpy.data.actions.new("Screen Action")
    material_anim.bind_material(screen, clip.action)
    for frame_number, value in ((1, 0.5), (25, 2.0)):
        screen.adm.params["brightness"].value_f = value
        screen.keyframe_insert('adm.params["brightness"].value_f', frame=frame_number)
    _, anim = AnimExporter(bpy.context, lib).export()
    targets = [c["target"] for c in anim.doc["clips"][0]["channels"]]
    check(anim.ok and any(t.get("kind") == "shaderParameter" and t.get("parameter") == "brightness"
                          for t in targets) and not material_binding_issues(doc, anim.doc),
          "animated brightness binds to the same material animation ID")
    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_interactive_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
