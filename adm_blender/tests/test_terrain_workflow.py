"""Blender regression tests for terrain creation and export option defaults."""
import math
import os
import struct
import sys
import tempfile
import zlib

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender


def main(tmp):
    adm_blender.register()
    from adm_blender.blender.export_adm import ExportError, ExportOptions, ModelExporter, default_export_options
    from adm_blender.blender.operators import _terrain_grid_boundaries
    from adm_blender.blender.file_io import _update_export_scope, _update_export_vertex_controls
    from adm_blender.blender.import_adm import ImportOptions, import_model

    bpy.ops.wm.read_homefile(use_empty=True)
    assert _terrain_grid_boundaries(794, 793, 100) == [0, 100, 200, 300, 400, 500, 600, 700, 793]
    assert _terrain_grid_boundaries(3, 10, 5) == [0, 1, 2]
    assert _terrain_grid_boundaries(3, 10, 100) == [0, 2]
    try:
        _terrain_grid_boundaries(2, 0, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("zero terrain extent must be rejected")
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

    class Options:
        # like a Blender 5 operator: attributes only, no IDProperty item access
        __slots__ = ("scope", "_vertex_controls", "vertex_controls_manual", "vertex_controls_auto")

        def __init__(self):
            self.scope = "ROOT"
            self._vertex_controls = False
            self.vertex_controls_manual = False
            self.vertex_controls_auto = False

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

    absolute = bpy.data.images.new("Absolute Heightmap", width=4, height=3, float_buffer=True)
    absolute.colorspace_settings.name = "Non-Color"
    absolute_pixels = np.zeros((12, 4), dtype=np.float32)
    absolute_pixels[:, 0] = np.arange(12)
    absolute_pixels[:, 3] = 1
    absolute.pixels.foreach_set(absolute_pixels.ravel())
    bpy.ops.adm.create_terrain_heightmap(image_name=absolute.name, dimensions_mode="SPACING",
                                         spacing_x_m=3, spacing_y_m=5, height_mode="ABSOLUTE",
                                         height_scale=2, height_offset_m=1, flip_x=True, flip_y=True,
                                         origin="CORNER")
    terrain = bpy.context.active_object
    assert terrain["adm_terrain_samples_x"] == 4 and terrain["adm_terrain_samples_y"] == 3
    assert np.allclose([vertex.co.z for vertex in terrain.data.vertices],
                       [23, 21, 19, 17, 15, 13, 11, 9, 7, 5, 3, 1])
    assert np.allclose(terrain.data.vertices[0].co[:2], (0, 0))
    assert np.allclose(terrain.data.vertices[-1].co[:2], (9, 10))
    assert terrain["adm_terrain_source_image"] == absolute.name
    assert terrain["adm_terrain_width_m"] == 9 and terrain["adm_terrain_depth_m"] == 10
    assert terrain["adm_terrain_height_mode"] == "ABSOLUTE"
    assert terrain["adm_terrain_flip_x"] and terrain["adm_terrain_flip_y"]
    color = terrain.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
    color_values = np.zeros((len(color.data), 4), dtype=np.float32)
    color_values[:, 0] = np.linspace(0, 1, len(color.data))
    color_values[:, 1] = 0.5
    color_values[:, 3] = 1
    color.data.foreach_set("color", color_values.ravel())
    mesh_count = len(bpy.data.meshes)
    object_count = len(bpy.data.objects)
    assert bpy.ops.adm.terrain_preview_fixed_grid(tile_width_m=4, tile_length_m=5) == {"FINISHED"}
    preview = next(obj for obj in bpy.data.objects if obj.get("adm_terrain_preview_for") == terrain["adm_terrain_id"])
    assert preview.type == "CURVE" and len(preview.data.splines) == 7
    assert len(bpy.data.meshes) == mesh_count and len(bpy.data.objects) == object_count + 1
    assert bpy.ops.adm.terrain_cancel_preview() == {"FINISHED"}
    assert not any(obj.get("adm_terrain_preview_for") == terrain["adm_terrain_id"] for obj in bpy.data.objects)
    assert len(bpy.data.objects) == object_count
    assert bpy.ops.adm.terrain_preview_fixed_grid(tile_width_m=4, tile_length_m=5) == {"FINISHED"}
    assert bpy.ops.adm.terrain_apply_tiling() == {"FINISHED"}
    tile_collection = bpy.data.collections[f"{terrain.name}_Tiles"]
    tile_roots = [obj for obj in tile_collection.objects if obj.adm.adm_type == "MODEL"]
    assert len(tile_roots) == 6
    tile_objects = [root.children[0] for root in tile_roots]
    assert len({obj.data.as_pointer() for obj in tile_objects}) == 6
    assert all(len(obj.data.vertices) == 4 and len(obj.data.polygons) == 1 for obj in tile_objects)
    assert all(obj.data.uv_layers.get("UVMap") is not None
               and obj.data.color_attributes.get("COLOR_1") is not None for obj in tile_objects)
    assert all(obj.data.materials[0] == terrain.data.materials[0] for obj in tile_objects)

    def duplicate_working_terrain(suffix):
        duplicate = terrain.copy()
        duplicate.data = terrain.data.copy()
        duplicate.name = f"{terrain.name}_{suffix}"
        duplicate.parent = None
        duplicate.matrix_world = terrain.matrix_world.copy()
        bpy.context.collection.objects.link(duplicate)
        duplicate.hide_set(False)
        duplicate.adm.export_exclude = False
        for key in ("adm_terrain_id", "adm_terrain_preview_settings",
                    "adm_terrain_preview_signature", "adm_terrain_preview_width_m",
                    "adm_terrain_preview_length_m"):
            if key in duplicate:
                del duplicate[key]
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        duplicate.select_set(True)
        bpy.context.view_layer.objects.active = duplicate
        return duplicate

    adaptive_source = duplicate_working_terrain("Adaptive")
    assert bpy.ops.adm.terrain_preview_fixed_grid(
        mode="ADAPTIVE", target_area_m2=30, min_area_m2=15, max_area_m2=45,
        max_cells_per_tile=3) == {"FINISHED"}
    assert adaptive_source["adm_terrain_preview_settings"]
    adaptive_preview = next(obj for obj in bpy.data.objects
                            if obj.get("adm_terrain_preview_for") == adaptive_source["adm_terrain_id"])
    assert len(adaptive_preview.data.splines) > 0
    assert bpy.ops.adm.terrain_apply_tiling() == {"FINISHED"}
    adaptive_collection = bpy.data.collections[f"{adaptive_source.name}_Tiles"]
    adaptive_roots = [obj for obj in adaptive_collection.objects if obj.adm.adm_type == "MODEL"]
    assert sum(root["adm_terrain_tile_cell_count"] for root in adaptive_roots) == 6
    assert all(root["adm_terrain_tiling_mode"] == "ADAPTIVE" for root in adaptive_roots)
    adaptive_cells = []
    for root in adaptive_roots:
        adaptive_tile = next(child for child in root.children if child.type == "MESH")
        adaptive_cells.extend(adaptive_tile.data.polygons)
    assert len(adaptive_cells) == 6

    hybrid_source = duplicate_working_terrain("Hybrid")
    assert bpy.ops.adm.terrain_preview_fixed_grid(
        mode="HYBRID", target_area_m2=30, min_area_m2=15, max_area_m2=45,
        max_cells_per_tile=3, sector_width_m=4.5, sector_length_m=5) == {"FINISHED"}
    assert bpy.ops.adm.terrain_apply_tiling() == {"FINISHED"}
    hybrid_collection = bpy.data.collections[f"{hybrid_source.name}_Tiles"]
    hybrid_roots = [obj for obj in hybrid_collection.objects if obj.adm.adm_type == "MODEL"]
    assert len(hybrid_roots) == 4
    assert sum(root["adm_terrain_tile_cell_count"] for root in hybrid_roots) == 6
    assert all(root["adm_terrain_tiling_mode"] == "HYBRID" for root in hybrid_roots)

    stale_source = duplicate_working_terrain("Stale")
    assert bpy.ops.adm.terrain_preview_fixed_grid(
        mode="FIXED", tile_width_m=4, tile_length_m=5) == {"FINISHED"}
    stale_source.data.vertices[0].co.z += 0.1
    try:
        bpy.ops.adm.terrain_apply_tiling()
    except RuntimeError as exc:
        assert "terrain changed after preview" in str(exc)
    else:
        raise AssertionError("applying a stale terrain preview must be rejected")
    assert not bpy.data.collections.get(f"{stale_source.name}_Tiles")
    assert bpy.ops.adm.terrain_cancel_preview() == {"FINISHED"}
    # Tile 1 and tile 2 share the same sampled edge; no geometric gap is introduced.
    left_edge = sorted(tuple(v.co) for v in tile_objects[0].data.vertices if abs(v.co.x - 3) < 1e-6)
    right_edge = sorted(tuple(v.co) for v in tile_objects[1].data.vertices if abs(v.co.x - 3) < 1e-6)
    assert left_edge == right_edge and len(left_edge) == 2
    left_indices = [v.index for v in tile_objects[0].data.vertices if abs(v.co.x - 3) < 1e-6]
    right_indices = [v.index for v in tile_objects[1].data.vertices if abs(v.co.x - 3) < 1e-6]
    for vertex_index in left_indices:
        tile_objects[0].data.vertices[vertex_index].co.z += 2
    bpy.context.view_layer.objects.active = tile_objects[0]
    tile_objects[0].select_set(True)
    assert bpy.ops.adm.terrain_sync_borders() == {"FINISHED"}
    assert np.allclose([tile_objects[0].data.vertices[i].co.z for i in left_indices],
                       [tile_objects[1].data.vertices[i].co.z for i in right_indices])
    before = len(bpy.data.objects)
    try:
        bpy.ops.adm.create_terrain_heightmap(image_name=absolute.name, width_m=10, depth_m=10,
                                             height_mode="ABSOLUTE", use_no_data=True, no_data_value=4)
    except RuntimeError as exc:
        assert "NoData" in str(exc)
    else:
        raise AssertionError("NoData must be rejected")
    assert len(bpy.data.objects) == before
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    tile_data, tile_report = ModelExporter(
        bpy.context, tile_roots[0], ExportOptions(vertex_controls=True)).export()
    assert tile_report.ok
    tile_path = os.path.join(tmp, "terrain_tile.adm")
    with open(tile_path, "wb") as stream:
        stream.write(tile_data)
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(bpy.context, tile_path, ImportOptions())
    imported_tile = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    assert len(imported_tile.data.vertices) == 4 and len(imported_tile.data.polygons) == 2, \
        f"imported tile geometry: {len(imported_tile.data.vertices)} vertices, {len(imported_tile.data.polygons)} faces"
    assert imported_tile.data.uv_layers.get("UVMap") is not None
    assert imported_tile.data.color_attributes.get("COLOR_1") is not None
    bpy.context.view_layer.objects.active = imported_tile
    imported_tile.select_set(True)
    assert bpy.ops.adm.generate_lods(
        levels=2, ratios=(0.5, 0.25, 0.1, 0.05, 0.02),
        distances=(15, 40, 100, 200, 400), morph_max_lod=0) == {"FINISHED"}
    assert imported_tile.parent.adm.adm_type == "LOD_GROUP"
    assert len(imported_tile.parent.adm.lod_levels) == 2

    def png_chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))

    source_path = os.path.join(tmp, "height16.png")
    png = (b"\x89PNG\r\n\x1a\n"
           + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 16, 0, 0, 0, 0))
           + png_chunk(b"IDAT", zlib.compress(b"\x00" + struct.pack(">HH", 0, 1)
                                              + b"\x00" + struct.pack(">HH", 32769, 65535)))
           + png_chunk(b"IEND", b""))
    with open(source_path, "wb") as stream:
        stream.write(png)
    bpy.ops.adm.create_terrain_heightmap(image_path=source_path, width_m=1, depth_m=1)
    terrain = bpy.context.active_object
    expected = np.array([0, 1, 32769, 65535], np.float64) / 65535
    assert np.allclose(sorted(vertex.co.z for vertex in terrain.data.vertices), expected, atol=1e-7)
    assert bpy.data.images[terrain["adm_terrain_source_image"]].colorspace_settings.is_data

    from adm_blender.blender.operators import _terrain_boundary

    dense = bpy.data.images.new("Native Density", width=65, height=33, float_buffer=True)
    dense.colorspace_settings.name = "Non-Color"
    dense_pixels = np.zeros((33, 65, 4), dtype=np.float32)
    yy, xx = np.mgrid[:33, :65]
    dense_pixels[:, :, 0] = 0.5 + 0.2 * np.sin(xx * 0.2) * np.cos(yy * 0.15)
    dense_pixels[:, :, 3] = 1
    dense.pixels.foreach_set(dense_pixels.ravel())
    counts = []
    for preset in ("0.15", "0.3", "0.7"):
        assert bpy.ops.adm.create_terrain_heightmap(
            image_name=dense.name, width_m=64, depth_m=32,
            min_height_m=0, max_height_m=10) == {"FINISHED"}
        source = bpy.context.active_object
        assert len(source.data.vertices) == 65 * 33
        assert np.allclose([vertex.co.z for vertex in source.data.vertices],
                           dense_pixels[:, :, 0].ravel() * 10)
        mask = source.data.color_attributes.new(name="COLOR_1", type="FLOAT_COLOR", domain="CORNER")
        mask.data.foreach_set("color", np.tile([0.25, 0.5, 0.75, 1], len(mask.data)))
        assert bpy.ops.adm.terrain_preview_fixed_grid(
            tile_width_m=32, tile_length_m=32, reduction_method="DECIMATE",
            reduction=preset) == {"FINISHED"}
        assert bpy.ops.adm.terrain_apply_tiling() == {"FINISHED"}
        collection = bpy.context.active_object.users_collection[0]
        tiles = [obj for obj in collection.objects if obj.type == "MESH"]
        assert len(tiles) == 2
        total = 0
        seams = []
        for tile in tiles:
            triangles = sum(len(poly.vertices) - 2 for poly in tile.data.polygons)
            assert abs(triangles / 2048 - float(preset)) < 0.02, (preset, triangles)
            assert len(tile.data.vertices) < 33 * 33
            assert len(tile.data.uv_layers["UVMap"].data) == len(tile.data.loops)
            assert len(tile.data.color_attributes["COLOR_1"].data) == len(tile.data.loops)
            assert all(np.allclose(value.color, (0.25, 0.5, 0.75, 1))
                       for value in tile.data.color_attributes["COLOR_1"].data)
            boundary_vertices, _edges = _terrain_boundary(tile.data)
            assert len(boundary_vertices) == 128
            seams.append(sorted(tuple(tile.data.vertices[index].co) for index in boundary_vertices
                                if abs(tile.data.vertices[index].co.x) < 1e-6))
            total += triangles
        assert seams[0] == seams[1] and len(seams[0]) == 33
        assert len(source.data.vertices) == 65 * 33 and len(source.data.polygons) == 64 * 32
        counts.append(total)
    assert counts[0] < counts[1] < counts[2]

    from adm_blender.blender.operators import _terrain_max_height_error

    mixed = bpy.data.images.new("Adaptive Density", width=65, height=33, float_buffer=True)
    mixed.colorspace_settings.name = "Non-Color"
    mixed_pixels = np.zeros((33, 65, 4), dtype=np.float32)
    mixed_pixels[:, :, 0] = 0.5 + np.where(xx >= 32, 0.2 * np.sin(xx * 0.5) * np.cos(yy * 0.4), 0.0)
    mixed_pixels[:, :, 3] = 1
    mixed.pixels.foreach_set(mixed_pixels.ravel())
    adaptive_totals = []
    for tolerance in (0.2, 0.05):
        assert bpy.ops.adm.create_terrain_heightmap(
            image_name=mixed.name, width_m=64, depth_m=32,
            min_height_m=0, max_height_m=10, origin="CORNER") == {"FINISHED"}
        source = bpy.context.active_object
        grid = np.empty(len(source.data.vertices) * 3)
        source.data.vertices.foreach_get("co", grid)
        grid = grid.reshape(33, 65, 3)
        assert bpy.ops.adm.terrain_preview_fixed_grid(
            tile_width_m=32, tile_length_m=32, reduction_method="ADAPTIVE",
            max_error_m=tolerance) == {"FINISHED"}
        assert bpy.ops.adm.terrain_apply_tiling() == {"FINISHED"}
        collection = bpy.context.active_object.users_collection[0]
        tiles = sorted((obj for obj in collection.objects if obj.type == "MESH"),
                       key=lambda obj: obj.parent["adm_terrain_bounds_grid_x0"])
        assert len(tiles) == 2
        triangles = [sum(len(poly.vertices) - 2 for poly in tile.data.polygons) for tile in tiles]
        assert triangles[0] < triangles[1] < 2048, triangles
        assert triangles[0] < 0.1 * 2048, triangles
        for tile, columns in zip(tiles, (slice(0, 33), slice(32, 65))):
            assert tile["adm_terrain_reduction"] == "ADAPTIVE"
            assert tile["adm_terrain_measured_error_m"] <= tolerance
            samples = grid[:, columns].reshape(-1, 3)
            assert _terrain_max_height_error(tile.data, samples, math.inf) <= tolerance + 1e-6
            assert len(_terrain_boundary(tile.data)[0]) == 128
        adaptive_totals.append(sum(triangles))
    assert adaptive_totals[0] < adaptive_totals[1]
    root = tiles[0].parent
    data, report = ModelExporter(bpy.context, root, ExportOptions(vertex_controls=True)).export()
    assert report.ok
    path = os.path.join(tmp, "reduced_tile.adm")
    with open(path, "wb") as stream:
        stream.write(data)
    expected_triangles = sum(len(poly.vertices) - 2 for poly in tiles[0].data.polygons)
    expected_boundary = _terrain_boundary(tiles[0].data)[1]
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(bpy.context, path, ImportOptions())
    reduced = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    assert len(reduced.data.polygons) == expected_triangles
    assert _terrain_boundary(reduced.data)[1] == expected_boundary
    assert reduced.data.uv_layers.get("UVMap") is not None
    assert reduced.data.color_attributes.get("COLOR_1") is not None

    wide = bpy.data.images.new("Native 1009", width=1009, height=3, float_buffer=True)
    wide.colorspace_settings.name = "Non-Color"
    pixels = np.zeros((3, 1009, 4), dtype=np.float32)
    pixels[:, :, 0] = np.linspace(0, 1, 1009)
    pixels[:, :, 3] = 1
    wide.pixels.foreach_set(pixels.ravel())
    assert bpy.ops.adm.create_terrain_heightmap(
        image_name=wide.name, width_m=1008, depth_m=2) == {"FINISHED"}
    wide_grid = bpy.context.active_object
    assert len(wide_grid.data.vertices) == 1009 * 3
    assert np.allclose([vertex.co.z for vertex in wide_grid.data.vertices], pixels[:, :, 0].ravel())
    for samples, message in ((1, "at least 2"), (4096, "4,194,304 vertices")):
        before = len(bpy.data.objects)
        try:
            bpy.ops.adm.create_terrain_heightmap(
                image_name=wide.name, width_m=1008, depth_m=2, samples_x=samples, samples_y=samples)
        except RuntimeError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid or oversized terrain samples must be rejected")
        assert len(bpy.data.objects) == before

    from adm_blender.blender.operators import MAX_TERRAIN_VERTICES, _terrain_effective_samples

    assert _terrain_effective_samples(8192, 8192, 0, 0) == (2048, 2048)
    assert _terrain_effective_samples(1009, 1009, 0, 0) == (1009, 1009)
    dense_w, dense_h = 8193, 2049
    huge = bpy.data.images.new("Too Dense", width=dense_w, height=dense_h, float_buffer=True)
    huge.colorspace_settings.name = "Non-Color"
    huge_pixels = np.zeros((dense_h, dense_w, 4), dtype=np.float32)
    huge_pixels[:, :, 0] = (0.5 * np.linspace(0, 1, dense_w)[None, :]
                            + 0.25 * (np.arange(dense_h) % 2)[:, None])
    huge_pixels[:, :, 3] = 1
    huge.pixels.foreach_set(huge_pixels.ravel())
    del huge_pixels
    assert bpy.ops.adm.create_terrain_heightmap(
        image_name=huge.name, width_m=8192, depth_m=2048, origin="CORNER") == {"FINISHED"}
    auto = bpy.context.active_object
    ax, ay = auto["adm_terrain_samples_x"], auto["adm_terrain_samples_y"]
    assert 0.99 * MAX_TERRAIN_VERTICES < ax * ay <= MAX_TERRAIN_VERTICES, (ax, ay)
    assert abs(ax / ay - 4) < 0.01, (ax, ay)
    auto_coords = np.empty(ax * ay * 3)
    auto.data.vertices.foreach_get("co", auto_coords)
    auto_coords = auto_coords.reshape(ay, ax, 3)[2:-2, 2:-2]
    # box averaging must damp the one-pixel row stripes instead of aliasing them to 0 or 0.25
    detail = auto_coords[:, :, 2] - 0.5 * auto_coords[:, :, 0] / 8192
    assert np.abs(detail - 0.125).max() < 0.05, np.abs(detail - 0.125).max()
    bpy.data.images.remove(huge)

    from adm_blender.blender.operators import _terrain_tiling_check

    dense = {"adm_terrain_samples_x": 2048, "adm_terrain_samples_y": 2048,
             "adm_terrain_width_m": 2047 * 0.71, "adm_terrain_depth_m": 2047 * 0.71}
    tiling = dict(mode="ADAPTIVE", tile_width_m=100, tile_length_m=100, target_area_m2=10000,
                  min_area_m2=2500, max_area_m2=20000, max_cells_per_tile=4096,
                  sector_width_m=500, sector_length_m=500)
    _info, problems = _terrain_tiling_check(dense, tiling)
    assert "Minimum Area needs 4,960 cells" in problems["max_cells_per_tile"], problems
    _info, problems = _terrain_tiling_check(dense, dict(tiling, max_cells_per_tile=40000))
    assert not problems, problems
    _info, problems = _terrain_tiling_check(dense, dict(tiling, mode="FIXED", tile_width_m=10, tile_length_m=10))
    assert "maximum is 4,096" in problems["tile_width_m"], problems
    try:
        bpy.ops.adm.terrain_preview_fixed_grid(mode="ADAPTIVE", min_area_m2=2500, max_cells_per_tile=100)
    except RuntimeError as exc:
        assert "Minimum Area needs" in str(exc), exc
    else:
        raise AssertionError("infeasible tiling limits must be rejected before partitioning")
    assert "adm_terrain_preview_settings" not in auto

    invalid = bpy.data.images.new("Invalid Heightmap", width=2, height=2, float_buffer=True)
    invalid.colorspace_settings.name = "Non-Color"
    invalid.pixels.foreach_set(np.array([np.nan, 0, 0, 1] * 4, np.float32))
    before = len(bpy.data.objects)
    try:
        bpy.ops.adm.create_terrain_heightmap(image_name=invalid.name, width_m=10, depth_m=10)
    except RuntimeError as exc:
        assert "NaN or infinite" in str(exc)
    else:
        raise AssertionError("non-finite heights must be rejected")
    assert len(bpy.data.objects) == before

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
