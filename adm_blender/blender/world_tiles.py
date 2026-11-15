"""Import terrain tiles built by Apparatus World Tile and keep their materials in sync.

The external tool (``appartus_world_tile``) writes ``manifest.json``, one binary PLY per tile
and LOD, and one TERRAIN_4 blend mask per tile.  Every tile becomes an ADM model whose material
is a copy of a shared template material with the tile's own ``blend_mask``.
"""

import json
import math
import os

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, IntVectorProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

MANIFEST_FORMAT = "apparatus-world-tile"
MANIFEST_VERSION = 1
TEMPLATE_NAME = "ADM World Terrain"
TEMPLATE_FLAG = "adm_world_terrain_template"
TILE_TEMPLATE_KEY = "adm_world_terrain_template_name"
TILE_KEY = "adm_world_tile_id"
LAYER_ROUGHNESS = {"ground": 0.9, "rock": 0.8, "snow": 0.55, "water": 0.08}

_PLY_TYPES = {"char": "i1", "uchar": "u1", "int8": "i1", "uint8": "u1", "short": "<i2", "ushort": "<u2",
              "int16": "<i2", "uint16": "<u2", "int": "<i4", "uint": "<u4", "int32": "<i4", "uint32": "<u4",
              "float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8"}


class WorldTileError(Exception):
    pass


def read_ply(path):
    """Binary little-endian triangle PLY -> (structured vertex array, (n, 3) int faces)."""
    with open(path, "rb") as handle:
        if handle.readline().strip() != b"ply":
            raise WorldTileError(f"{path}: not a PLY file")
        elements = []
        while True:
            line = handle.readline()
            if not line:
                raise WorldTileError(f"{path}: header has no end_header")
            words = line.decode("ascii", "replace").split()
            if not words or words[0] in ("comment", "obj_info"):
                continue
            if words[0] == "end_header":
                break
            if words[0] == "format" and words[1:2] != ["binary_little_endian"]:
                raise WorldTileError(f"{path}: only binary_little_endian PLY is supported")
            if words[0] == "element":
                elements.append([words[1], int(words[2]), []])
            elif words[0] == "property" and elements:
                elements[-1][2].append(words[1:])
        vertices = faces = None
        for name, count, props in elements:
            if name == "vertex":
                if any(p[0] == "list" for p in props):
                    raise WorldTileError(f"{path}: list properties on vertices are not supported")
                dtype = np.dtype([(p[1], _PLY_TYPES[p[0]]) for p in props])
                vertices = np.fromfile(handle, dtype=dtype, count=count)
                if len(vertices) != count:
                    raise WorldTileError(f"{path}: file is truncated")
            elif name == "face":
                if len(props) != 1 or props[0][0] != "list":
                    raise WorldTileError(f"{path}: faces must be a single vertex index list")
                dtype = np.dtype([("n", _PLY_TYPES[props[0][1]]), ("i", _PLY_TYPES[props[0][2]], (3,))])
                data = np.fromfile(handle, dtype=dtype, count=count)
                if len(data) != count or np.any(data["n"] != 3):
                    raise WorldTileError(f"{path}: only complete triangle lists are supported")
                faces = data["i"].astype(np.int32)
            else:
                raise WorldTileError(f"{path}: unexpected element '{name}'")
    if vertices is None or faces is None or len(vertices) == 0:
        raise WorldTileError(f"{path}: no vertices or faces")
    if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
        raise WorldTileError(f"{path}: face index out of range")
    for field in ("x", "y", "z", "nx", "ny", "nz", "s", "t", "s1", "t1"):
        if field not in vertices.dtype.names:
            raise WorldTileError(f"{path}: vertex property '{field}' missing")
    return vertices, faces


def load_manifest(path):
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("format") != MANIFEST_FORMAT:
        raise WorldTileError("Not an Apparatus World Tile manifest")
    if int(manifest.get("format_version", 0)) > MANIFEST_VERSION:
        raise WorldTileError("The manifest is newer than this add-on; update ADM Tools")
    return manifest


def _inside(root, relative):
    """Resolve a manifest-relative path and refuse anything outside the manifest folder."""
    path = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([path, os.path.realpath(root)]) != os.path.realpath(root):
        raise WorldTileError(f"'{relative}' points outside the tile folder")
    return path


def _build_mesh(name, verts, faces, unit):
    from .materials import UV_NAMES

    mesh = bpy.data.meshes.new(name)
    co = np.column_stack((verts["x"], verts["y"], verts["z"])).astype(np.float64) / unit
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", co.astype(np.float32).ravel())
    loops = faces.ravel()
    mesh.loops.add(len(loops))
    mesh.loops.foreach_set("vertex_index", loops)
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(len(faces), dtype=np.int32) * 3)
    mesh.polygons.foreach_set("loop_total", np.full(len(faces), 3, dtype=np.int32))
    mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=bool))
    mesh.update(calc_edges=True)
    for uv_name, (u, v) in zip(UV_NAMES, (("s", "t"), ("s1", "t1"))):
        layer = mesh.uv_layers.new(name=uv_name)
        layer.uv.foreach_set("vector", np.column_stack((verts[u], verts[v]))[loops].astype(np.float32).ravel())
    normals = np.column_stack((verts["nx"], verts["ny"], verts["nz"])).astype(np.float32)
    mesh.normals_split_custom_set_from_vertices(normals)
    mesh.validate(clean_customdata=False)
    mesh.update()
    return mesh


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def ensure_template(manifest, repeat_m):
    """Shared TERRAIN_4 template; created once, never overwritten."""
    from .materials import quiet_param_updates, refresh_shader_preview, sync_official_shader_params, \
        unique_animation_id

    template = bpy.data.materials.get(TEMPLATE_NAME)
    if template is not None:
        return template, False
    template = bpy.data.materials.new(TEMPLATE_NAME)
    template.use_nodes = True
    template.use_fake_user = True
    template[TEMPLATE_FLAG] = True
    template.adm.shader = "TERRAIN_4"
    sync_official_shader_params(template)
    taken = {m.adm.animation_id.strip() for m in bpy.data.materials if m != template} - {""}
    template.adm.animation_id = unique_animation_id(template.name, taken)
    tile_m = float(manifest.get("tile_size_m", 0.0))
    scale = min(1000.0, max(1.0, round(tile_m / repeat_m))) if tile_m > 0 and repeat_m > 0 else 1.0
    params = template.adm.params
    with quiet_param_updates():
        if params.get("uv_scale") is not None:
            params["uv_scale"].value_vec = (scale,) * 4
            params["uv_scale"].use = True
        for layer in manifest.get("mask_layers", []):
            i = int(layer["layer"])
            color = params.get(f"layer{i}_base_color")
            if color is not None:
                color.value_vec = tuple(_srgb_to_linear(c) for c in layer["color"]) + (1.0,)
                color.use = True
            rough = params.get(f"layer{i}_roughness")
            if rough is not None and layer.get("name") in LAYER_ROUGHNESS:
                rough.value_f = LAYER_ROUGHNESS[layer["name"]]
                rough.use = True
    refresh_shader_preview(template)
    return template, True


def _mask_image(path):
    image = bpy.data.images.load(path, check_existing=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    return image


def tile_material(template, name, mask_image, taken):
    """Copy ``template`` for one tile and give it the tile's blend mask on UVMap_1."""
    from .materials import quiet_param_updates, sync_official_shader_params, unique_animation_id

    mat = template.copy()
    mat.name = name
    mat.use_fake_user = False
    if TEMPLATE_FLAG in mat:
        del mat[TEMPLATE_FLAG]
    mat[TILE_TEMPLATE_KEY] = template.name
    aid = unique_animation_id(name, taken)
    taken.add(aid)
    mat.adm.animation_id = aid
    sync_official_shader_params(mat)
    param = mat.adm.params.get("blend_mask")
    if param is not None:
        with quiet_param_updates():
            param.image = mask_image
            param.tex_coord = 1
            param.use = mask_image is not None
    return mat


class ADM_OT_import_world_tiles(bpy.types.Operator, ImportHelper):
    """Import terrain tiles, LODs and blend masks built by Apparatus World Tile (manifest.json)"""
    bl_idname = "adm.import_world_tiles"
    bl_label = "Import World Tiles"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="manifest.json;*.json", options={"HIDDEN"})
    lod_mode: EnumProperty(
        name="Levels of Detail",
        items=[("ALL", "All as LOD Groups", "Import every LOD into an ADM LOD group per tile"),
               ("ONE", "Single LOD", "Import only one LOD per tile")],
        default="ALL")
    lod: IntProperty(name="LOD", min=0, default=0, description="LOD index to import in Single LOD mode")
    switch_distance_m: FloatProperty(
        name="First Switch Distance", min=0.0, default=0.0, unit="LENGTH",
        description="Distance at which LOD 1 starts; each further LOD doubles it. 0 = tile size")
    use_region: BoolProperty(name="Only a Region", default=False,
                             description="Import only tiles inside the given tile index range")
    region_min: IntVectorProperty(name="From Tile", size=2, min=0, default=(0, 0),
                                  description="Lowest tile index x, y (y counts from the south)")
    region_max: IntVectorProperty(name="To Tile", size=2, min=0, default=(3, 3),
                                  description="Highest tile index x, y, inclusive")
    texture_repeat_m: FloatProperty(
        name="Texture Repeat", min=0.01, default=4.0, unit="LENGTH",
        description="Size of one layer texture repeat, used for uv_scale when the template is created")
    max_triangles: IntProperty(name="Triangle Limit", min=1000, default=30_000_000,
                               description="Refuse imports above this many triangles")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "lod_mode")
        if self.lod_mode == "ONE":
            layout.prop(self, "lod")
        else:
            layout.prop(self, "switch_distance_m")
        layout.prop(self, "use_region")
        if self.use_region:
            layout.prop(self, "region_min")
            layout.prop(self, "region_max")
        layout.prop(self, "texture_repeat_m")
        layout.prop(self, "max_triangles")

    def execute(self, context):
        unit = context.scene.unit_settings.scale_length
        if not math.isfinite(unit) or unit <= 0:
            self.report({"ERROR"}, "Scene unit scale must be finite and positive")
            return {"CANCELLED"}
        try:
            manifest = load_manifest(self.filepath)
        except (OSError, ValueError, WorldTileError) as exc:
            self.report({"ERROR"}, f"Cannot read manifest: {exc}")
            return {"CANCELLED"}
        root_dir = os.path.dirname(os.path.abspath(self.filepath))
        lod_count = len(manifest.get("lods", []))
        if lod_count == 0:
            self.report({"ERROR"}, "Manifest has no LODs")
            return {"CANCELLED"}
        if self.lod_mode == "ONE" and self.lod >= lod_count:
            self.report({"ERROR"}, f"LOD {self.lod} does not exist; the tiles have LOD 0 to {lod_count - 1}")
            return {"CANCELLED"}
        lods = [self.lod] if self.lod_mode == "ONE" else list(range(lod_count))
        tiles = manifest.get("tiles", [])
        if self.use_region:
            x0, y0 = self.region_min
            x1, y1 = self.region_max
            tiles = [t for t in tiles if x0 <= t["ix"] <= x1 and y0 <= t["iy"] <= y1]
        if not tiles:
            self.report({"ERROR"}, "No tiles to import")
            return {"CANCELLED"}
        triangles = sum(t["lods"][lod]["triangles"] for t in tiles for lod in lods)
        if triangles > self.max_triangles:
            self.report({"ERROR"}, f"{len(tiles)} tiles would add {triangles:,} triangles (limit "
                        f"{self.max_triangles:,}). Import a coarser single LOD or a region.")
            return {"CANCELLED"}

        template, created = ensure_template(manifest, self.texture_repeat_m)
        stem = os.path.basename(root_dir) or "World"
        collection = bpy.data.collections.new(f"World Tiles {stem}")
        context.scene.collection.children.link(collection)
        collection["adm_world_tiles_manifest"] = os.path.abspath(self.filepath)
        tile_m = float(manifest.get("tile_size_m", 0.0)) or 100.0
        first = self.switch_distance_m or tile_m
        taken = {m.adm.animation_id.strip() for m in bpy.data.materials} - {""}
        created_objects, materials = [], []
        progress = context.window_manager
        progress.progress_begin(0, len(tiles))
        try:
            for index, tile in enumerate(tiles, 1):
                tile_id = tile["id"]
                ox, oy, oz = tile["origin_m"]
                root = bpy.data.objects.new(f"{stem}_{tile_id}", None)
                root.empty_display_type = "PLAIN_AXES"
                collection.objects.link(root)
                created_objects.append(root)
                root.adm.adm_type = "MODEL"
                root.matrix_world = Matrix.Translation((ox / unit, oy / unit, oz / unit))
                root[TILE_KEY] = tile_id
                root["adm_world_tile_ix"] = int(tile["ix"])
                root["adm_world_tile_iy"] = int(tile["iy"])
                root["adm_world_tile_size_m"] = list(tile["size_m"])
                mask = tile.get("mask")
                image = _mask_image(_inside(root_dir, mask)) if mask else None
                mat = tile_material(template, f"{template.name} {tile_id}", image, taken)
                materials.append(mat)
                parent = root
                if len(lods) > 1:
                    parent = bpy.data.objects.new(f"{stem}_{tile_id}_LODs", None)
                    parent.empty_display_type = "SPHERE"
                    parent.empty_display_size = 0.3
                    collection.objects.link(parent)
                    created_objects.append(parent)
                    parent.adm.adm_type = "LOD_GROUP"
                    parent.parent = root
                for lod in lods:
                    record = tile["lods"][lod]
                    verts, faces = read_ply(_inside(root_dir, record["file"]))
                    mesh = _build_mesh(f"{stem}_{tile_id}_LOD{lod}", verts, faces, unit)
                    mesh.materials.append(mat)
                    obj = bpy.data.objects.new(mesh.name, mesh)
                    collection.objects.link(obj)
                    created_objects.append(obj)
                    obj.parent = parent
                    obj[TILE_KEY] = tile_id
                    obj["adm_world_tile_lod"] = lod
                    obj["adm_world_tile_max_error_m"] = float(manifest["lods"][lod]["max_error_m"])
                    obj["adm_world_tile_measured_error_m"] = float(record["measured_error_m"])
                    if len(lods) > 1:
                        level = parent.adm.lod_levels.add()
                        level.object = obj
                        level.min_distance = 0.0 if lod == 0 else first * 2 ** (lod - 1) / unit
                        if lod:
                            obj.hide_set(True)
                progress.progress_update(index)
        except (OSError, ValueError, KeyError, IndexError, RuntimeError, WorldTileError) as exc:
            progress.progress_end()
            for obj in reversed(created_objects):
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and data.users == 0:
                    bpy.data.meshes.remove(data)
            for mat in materials:
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
            bpy.data.collections.remove(collection)
            self.report({"ERROR"}, f"World tile import failed; nothing was kept: {exc}")
            return {"CANCELLED"}
        progress.progress_end()
        from .materials import refresh_shader_preview
        for mat in materials:
            refresh_shader_preview(mat)
        ensure_template_swatch(context, template, collection, manifest, unit)
        note = f"template '{template.name}' created" if created else f"using existing '{template.name}'"
        self.report({"INFO"}, f"Imported {len(tiles)} tiles × {len(lods)} LOD(s), {triangles:,} triangles; "
                    f"{note}. Select '{TEMPLATE_NAME} Swatch', edit its material, then run "
                    "Sync World Terrain Materials.")
        return {"FINISHED"}


def ensure_template_swatch(context, template, collection, manifest, unit):
    """Small plane carrying the template so it can be selected and edited; never exported."""
    for obj in bpy.data.objects:
        if obj.get(TEMPLATE_FLAG) and obj.type == "MESH" and template.name in [m.name for m in obj.data.materials if m]:
            return obj
    size = float(manifest.get("tile_size_m", 100.0)) / unit
    x0, y0 = (float(v) / unit for v in manifest.get("bounds_m", [0.0, 0.0])[:2])
    z = float(manifest.get("source", {}).get("height_range_m", [0.0, 0.0])[1]) / unit
    mesh = bpy.data.meshes.new(TEMPLATE_NAME + " Swatch")
    mesh.from_pydata([(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0)], [], [(0, 1, 2, 3)])
    from .materials import UV_NAMES
    for name in UV_NAMES:
        mesh.uv_layers.new(name=name).uv.foreach_set("vector", (0, 0, 1, 0, 1, 1, 0, 1))
    mesh.materials.append(template)
    obj = bpy.data.objects.new(TEMPLATE_NAME + " Swatch", mesh)
    obj[TEMPLATE_FLAG] = True
    obj.adm.export_exclude = True
    obj.location = (x0 - size * 1.25, y0, z)
    collection.objects.link(obj)
    return obj


def tile_materials(template_name=None):
    return [m for m in bpy.data.materials if TILE_TEMPLATE_KEY in m
            and (template_name is None or m[TILE_TEMPLATE_KEY] == template_name)]


def sync_tile_materials(template):
    """Rebuild every tile material from ``template`` and keep each tile's mask and identity."""
    from .materials import refresh_shader_preview

    count = 0
    taken = set()
    for old in tile_materials(template.name):
        param = old.adm.params.get("blend_mask")
        image = param.image if param is not None else None
        name, aid = old.name, old.adm.animation_id
        old.name = name + ".sync"
        new = tile_material(template, name, image, taken)
        new.adm.animation_id = aid
        old.user_remap(new)
        bpy.data.materials.remove(old)
        new.name = name
        refresh_shader_preview(new)
        count += 1
    return count


def _template_from_context(context):
    mat = getattr(context, "material", None)
    obj = context.active_object
    if mat is None and obj is not None:
        mat = obj.active_material
    if mat is not None and mat.get(TEMPLATE_FLAG):
        return mat
    if mat is not None and TILE_TEMPLATE_KEY in mat:
        return bpy.data.materials.get(mat[TILE_TEMPLATE_KEY])
    return bpy.data.materials.get(TEMPLATE_NAME)


class ADM_OT_sync_world_terrain_materials(bpy.types.Operator):
    """Copy the world terrain template material to every tile material, keeping each tile's blend mask"""
    bl_idname = "adm.sync_world_terrain_materials"
    bl_label = "Sync World Terrain Materials"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        template = _template_from_context(context)
        return template is not None and any(True for _ in tile_materials(template.name))

    def execute(self, context):
        template = _template_from_context(context)
        count = sync_tile_materials(template)
        self.report({"INFO"}, f"Updated {count} tile materials from '{template.name}'")
        return {"FINISHED"}


CLASSES = (ADM_OT_import_world_tiles, ADM_OT_sync_world_terrain_materials)
