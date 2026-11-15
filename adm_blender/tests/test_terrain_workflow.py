"""Blender regression tests for terrain creation and export option defaults."""
import os
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender


def main(tmp):
    adm_blender.register()
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter, default_export_options
    from adm_blender.blender.file_io import _update_export_scope, _update_export_vertex_controls
    from adm_blender.blender.import_adm import ImportOptions, import_model

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    plain = bpy.context.active_object
    bpy.ops.adm.create_model_root(name="Root")
    root = bpy.data.objects["Root"]
    assert not default_export_options(bpy.context, root).vertex_controls
    bpy.ops.mesh.primitive_cube_add()
    overlay = bpy.context.active_object
    overlay.name = "Overlay"
    overlay.parent = root
    mat = bpy.data.materials.new("Overlay")
    mat.use_nodes = True
    overlay.data.materials.append(mat)
    mat.adm.shader_version = "2.0.0"
    mask = overlay.data.color_attributes.get("COLOR_1")
    if mask is None:
        mask = overlay.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    colors = np.zeros((len(mask.data), 4), dtype=np.float32)
    colors[0, 0] = 1.0
    mask.data.foreach_set("color", colors.ravel())
    assert default_export_options(bpy.context, root).vertex_controls
    overlay.adm.export_exclude = True
    assert not default_export_options(bpy.context, root).vertex_controls
    overlay.adm.export_exclude = False

    class Options(dict):
        scope = "ROOT"
        _vertex_controls = False

        @property
        def vertex_controls(self):
            return self._vertex_controls

        @vertex_controls.setter
        def vertex_controls(self, value):
            self._vertex_controls = value
            _update_export_vertex_controls(self, bpy.context)

    choice = Options()
    _update_export_scope(choice, bpy.context)
    assert choice.vertex_controls
    overlay.select_set(False)
    plain.select_set(True)
    choice.scope = "SELECTED"
    _update_export_scope(choice, bpy.context)
    assert not choice.vertex_controls
    overlay.select_set(True)
    _update_export_scope(choice, bpy.context)
    assert choice.vertex_controls
    choice.vertex_controls = False
    choice.scope = "ROOT"
    _update_export_scope(choice, bpy.context)
    assert not choice.vertex_controls
    for export_colors in (True, False):
        try:
            ModelExporter(bpy.context, root, ExportOptions(vertex_controls=False, export_colors=export_colors)).export()
        except ExportError as exc:
            assert "'Overlay'" in str(exc) and "Files > Export > Material > ADM Vertex Controls" in str(exc)
        else:
            raise AssertionError("explicitly disabled vertex controls must fail")
    assert bpy.ops.adm.validate_model() == {"FINISHED"}
    data, report = ModelExporter(bpy.context, root, default_export_options(bpy.context, root)).export()
    assert report.ok
    path = os.path.join(tmp, "roundtrip.adm")
    with open(path, "wb") as stream:
        stream.write(data)
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(bpy.context, path, ImportOptions())
    imported = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name == "Overlay")
    values = np.empty(len(imported.data.color_attributes["COLOR_1"].data) * 4, dtype=np.float32)
    imported.data.color_attributes["COLOR_1"].data.foreach_get("color", values)
    assert values[0::4].min() == 0 and values[0::4].max() == 1

    heightmap = bpy.data.images.new("Heightmap", width=2, height=2, float_buffer=True)
    heightmap.colorspace_settings.name = "Non-Color"
    heightmap.pixels.foreach_set(np.array([0, 0, 0, 1, 1, 1, 1, 1,
                                           0.5, 0.5, 0.5, 1, 0.25, 0.25, 0.25, 1], np.float32))
    bpy.context.view_layer.objects.active = imported
    imported_root = imported.parent
    imported_root.location = (10, 20, 0)
    bpy.context.scene.cursor.location = (3, 4, 0)
    bpy.context.view_layer.update()
    bpy.ops.adm.create_terrain_heightmap(image_name=heightmap.name, width_m=256, depth_m=128,
                                         min_height_m=-2, max_height_m=38, samples_x=3, samples_y=3)
    terrain = bpy.context.active_object
    assert terrain.parent == imported_root
    bpy.context.view_layer.update()
    assert np.allclose(terrain.matrix_world.translation[:], (3, 4, 0)), str(terrain.matrix_world.translation[:])
    assert len(terrain.data.vertices) == 9 and len(terrain.data.polygons) == 4
    assert len(terrain.data.uv_layers) == 1 and terrain.active_material.adm.shader == "TERRAIN_4"
    z = [v.co.z for v in terrain.data.vertices]
    assert abs(min(z) + 2) < 1e-5 and abs(max(z) - 38) < 1e-5
    assert abs(terrain.dimensions.x - 256) < 1e-4 and abs(terrain.dimensions.y - 128) < 1e-4
    try:
        bpy.ops.adm.create_terrain_heightmap(image_name=heightmap.name, width_m=0, depth_m=128)
    except RuntimeError as exc:
        assert "positive width and depth" in str(exc)
    else:
        raise AssertionError("unspecified physical size must be rejected")

    for path in filter(None, os.environ.get("ADM_HEIGHTMAPS", "").split(os.pathsep)):
        heightmap = bpy.data.images.load(path, check_existing=False)
        heightmap.colorspace_settings.name = "Non-Color"
        pixels = np.empty(heightmap.size[0] * heightmap.size[1] * 4, dtype=np.float32)
        heightmap.pixels.foreach_get(pixels)
        bpy.ops.adm.create_terrain_heightmap(image_name=heightmap.name, width_m=256, depth_m=256,
                                             min_height_m=0, max_height_m=38, samples_x=193, samples_y=193)
        terrain = bpy.context.active_object
        assert len(terrain.data.polygons) * 2 == 73728
        assert np.isclose(terrain.data.vertices[0].co.z, pixels[0] * 38, atol=1e-4)
        assert np.isclose(terrain.data.vertices[-1].co.z, pixels[-4] * 38, atol=1e-4)
        print(f"16-bit heightmap sampled: {os.path.basename(path)}")

    supplied = os.environ.get("ADM_TERRAIN_SCENE")
    if supplied:
        bpy.ops.wm.open_mainfile(filepath=supplied)
        root = bpy.data.objects["ADM_Terrain_and_Shader_Cubes"]
        obj = next(obj for obj in root.children_recursive if obj.type == "MESH" and "06 PBR" in obj.name)
        original = obj.data.color_attributes["COLOR_1"]
        source_colors = np.empty(len(original.data) * 4, dtype=np.float32)
        original.data.foreach_get("color", source_colors)
        print(f"Supplied COLOR_1.R: {source_colors[0::4].min()}..{source_colors[0::4].max()}")
        source_min, source_max = source_colors[0::4].min(), source_colors[0::4].max()
        bpy.context.view_layer.objects.active = obj
        assert default_export_options(bpy.context, root).vertex_controls
        assert bpy.ops.adm.validate_model() == {"FINISHED"}
        data, report = ModelExporter(bpy.context, root, default_export_options(bpy.context, root)).export()
        assert report.ok
        try:
            ModelExporter(bpy.context, root, ExportOptions(vertex_controls=False)).export()
        except ExportError as exc:
            assert obj.name in str(exc) and "Files > Export > Material > ADM Vertex Controls" in str(exc)
        else:
            raise AssertionError("supplied scene accepted disabled vertex controls")
        path = os.path.join(tmp, "supplied.adm")
        with open(path, "wb") as stream:
            stream.write(data)
        bpy.ops.wm.read_homefile(use_empty=True)
        import_model(bpy.context, path, ImportOptions())
        obj = next(o for o in bpy.context.scene.objects if o.type == "MESH" and "06 PBR" in o.name)
        attr = obj.data.color_attributes["COLOR_1"]
        colors = np.empty(len(attr.data) * 4, dtype=np.float32)
        attr.data.foreach_get("color", colors)
        assert np.isclose(colors[0::4].min(), source_min) and np.isclose(colors[0::4].max(), source_max), \
            f"{obj.name}: imported COLOR_1.R range {colors[0::4].min()}..{colors[0::4].max()}"
        print("Supplied scene validation, export and COLOR_1 round trip: PASS")


with tempfile.TemporaryDirectory() as tmp:
    main(tmp)
print("RESULT: PASS")
