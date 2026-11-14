"""Automatic LOD generation into an ADM LOD group (Decimate/Collapse from LOD0)."""

import bpy
import numpy as np
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty
from mathutils import Matrix

from ..core import constants as K
from .operators import link_to_active_collection, make_active, parent_keep_transform

MAX_LEVELS = 6
PROTECT_GROUP = "_adm_lod_decimate"
MORPH_ATTR = "_adm_lod_morph_{}"


class LodError(ValueError):
    pass


def triangle_count(mesh):
    return sum(len(poly.vertices) - 2 for poly in mesh.polygons)


def _is_screen_material(mat):
    return mat is not None and mat.adm.shader_key() == K.SHADER_INTERACTIVE


def lod_source_of(obj):
    """LOD0 mesh for the active object, LOD group or previously generated level."""
    if obj is None:
        return None
    if obj.adm.adm_type == "LOD_GROUP":
        levels = sorted((lv for lv in obj.adm.lod_levels if lv.object is not None), key=lambda lv: lv.min_distance)
        obj = levels[0].object if levels else None
    elif obj.adm.lod_source is not None:
        obj = obj.adm.lod_source
    if obj is None or obj.type != "MESH" or obj.adm.adm_type in {"COLLIDER", "LOD_GROUP"}:
        return None
    return obj


def _morph_keys(source):
    key = source.data.shape_keys
    if key is None or len(key.key_blocks) < 2:
        return None, []
    return key.reference_key, [kb for kb in key.key_blocks if kb != key.reference_key]


def _coords(data, count):
    out = np.empty(count * 3, dtype=np.float32)
    data.foreach_get("co", out)
    return out.reshape(-1, 3)


def _decimated_mesh(context, source, ratio, protect, morphs):
    """Decimate a copy of the LOD0 basis; morph deltas ride along as interpolated point attributes."""
    mesh = source.data.copy()
    tmp = bpy.data.objects.new("_adm_lod_tmp", mesh)
    context.scene.collection.objects.link(tmp)
    try:
        reference, keys = _morph_keys(source)
        if reference is not None:
            count = len(mesh.vertices)
            basis = _coords(reference.data, count)
            mesh.vertices.foreach_set("co", basis.ravel())
            for i, kb in enumerate(keys if morphs else ()):
                attr = mesh.attributes.new(MORPH_ATTR.format(i), "FLOAT_VECTOR", "POINT")
                attr.data.foreach_set("vector", (_coords(kb.data, count) - basis).ravel())
        if mesh.shape_keys is not None:
            tmp.shape_key_clear()
        total = triangle_count(mesh)
        kept = set()
        if protect:
            for poly in mesh.polygons:
                if poly.material_index < len(source.material_slots) \
                        and _is_screen_material(source.material_slots[poly.material_index].material):
                    kept.update(poly.vertices)
        locked = sum(len(poly.vertices) - 2 for poly in mesh.polygons if kept.issuperset(poly.vertices))
        mod = tmp.modifiers.new("ADM LOD", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        # protected triangles are excluded from the reduction target so the rest still reaches `ratio`
        mod.ratio = 1.0 if total == 0 else (locked + ratio * (total - locked)) / total
        if kept:
            group = tmp.vertex_groups.new(name=PROTECT_GROUP)
            group.add([v.index for v in mesh.vertices if v.index not in kept], 1.0, "REPLACE")
            mod.vertex_group = PROTECT_GROUP
        depsgraph = context.evaluated_depsgraph_get()
        result = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                                 depsgraph=depsgraph)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(mesh)
    return result, locked


def _apply_morphs(lod, source):
    reference, keys = _morph_keys(source)
    mesh = lod.data
    count = len(mesh.vertices)
    base = _coords(mesh.vertices, count)
    lod.shape_key_add(name=reference.name, from_mix=False)
    blocks = {}
    for i, kb in enumerate(keys):
        attr = mesh.attributes[MORPH_ATTR.format(i)]
        delta = np.empty(count * 3, dtype=np.float32)
        attr.data.foreach_get("vector", delta)
        new = lod.shape_key_add(name=kb.name, from_mix=False)
        new.data.foreach_set("co", (base + delta.reshape(-1, 3)).ravel())
        new.slider_min, new.slider_max = kb.slider_min, kb.slider_max
        new.value, new.mute, new.interpolation = kb.value, kb.mute, kb.interpolation
        new.vertex_group = kb.vertex_group
        blocks[kb.name] = new
    for kb in keys:
        if kb.relative_key is not None and kb.relative_key.name in blocks:
            blocks[kb.name].relative_key = blocks[kb.relative_key.name]


def _strip_temporary(lod):
    group = lod.vertex_groups.get(PROTECT_GROUP)
    if group is not None:
        lod.vertex_groups.remove(group)
    mesh = lod.data
    for attr in [a.name for a in mesh.attributes if a.name.startswith("_adm_lod_morph_")]:
        mesh.attributes.remove(mesh.attributes[attr])


def _remove_generated(group, source):
    for i in reversed(range(len(group.adm.lod_levels))):
        obj = group.adm.lod_levels[i].object
        if obj is not None and obj.adm.lod_source == source:
            group.adm.lod_levels.remove(i)
    for obj in [c for c in group.children if c.adm.lod_source == source]:
        mesh = obj.data
        bpy.data.objects.remove(obj)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _group_for(context, source):
    parent = source.parent
    if parent is not None and parent.adm.adm_type == "LOD_GROUP":
        return parent
    group = bpy.data.objects.new(f"{source.name}_LODs", None)
    group.empty_display_type = "SPHERE"
    group.empty_display_size = 0.3
    group.adm.adm_type = "LOD_GROUP"
    for coll in source.users_collection:
        coll.objects.link(group)
    if not group.users_collection:
        link_to_active_collection(context, group)
    group.matrix_world = Matrix.Translation(source.matrix_world.to_translation())
    if parent is not None:
        parent_keep_transform(group, parent)
    context.view_layer.update()
    parent_keep_transform(source, group)
    return group


def generate_lods(context, source, levels, ratios, distances, morph_max_lod, protect_screens):
    """Return (group, [(level, triangles, morphs)]); replaces levels generated earlier from ``source``."""
    if not 2 <= levels <= MAX_LEVELS:
        raise LodError(f"levels must be 2..{MAX_LEVELS}")
    ratios, distances = list(ratios[:levels - 1]), list(distances[:levels - 1])
    if any(not 0.0 < r < 1.0 for r in ratios) or any(a <= b for a, b in zip(ratios, ratios[1:])):
        raise LodError("ratios must be in (0,1) and strictly decreasing")
    if distances[0] <= 0.0 or any(a >= b for a, b in zip(distances, distances[1:])):
        raise LodError("switch distances must be > 0 and strictly increasing")
    if source.data.shape_keys is not None and not source.data.shape_keys.use_relative:
        raise LodError(f"'{source.name}': absolute shape keys are not supported")
    group = _group_for(context, source)
    _remove_generated(group, source)
    level0 = next((lv for lv in group.adm.lod_levels if lv.object == source), None)
    if level0 is None:
        level0 = group.adm.lod_levels.add()
        level0.object = source
    level0.min_distance = 0.0
    taken = {round(lv.min_distance, 6) for lv in group.adm.lod_levels if lv.object not in {None, source}}
    if taken & {round(d, 6) for d in distances}:
        raise LodError(f"'{group.name}': a manual level already uses one of the switch distances")
    base_name = source.name[:-5] if source.name.endswith("_LOD0") else source.name
    out = []
    has_morphs = _morph_keys(source)[0] is not None
    for i, (ratio, distance) in enumerate(zip(ratios, distances), start=1):
        morphs = has_morphs and i <= morph_max_lod
        mesh, _ = _decimated_mesh(context, source, ratio, protect_screens, morphs)
        mesh.name = f"{source.data.name}_LOD{i}"
        lod = source.copy()
        lod.data = mesh
        lod.name = f"{base_name}_LOD{i}"
        lod.adm.lod_source = source
        lod.animation_data_clear()
        for coll in group.users_collection:
            coll.objects.link(lod)
        lod.parent = group
        lod.matrix_world = source.matrix_world.copy()
        if morphs:
            _apply_morphs(lod, source)
        _strip_temporary(lod)
        lod.hide_set(True)
        level = group.adm.lod_levels.add()
        level.object, level.min_distance = lod, distance
        out.append((i, triangle_count(mesh), morphs))
    return group, out


class ADM_OT_generate_lods(bpy.types.Operator):
    """Generate decimated LOD1..n of the active mesh into an ADM LOD group (regenerates earlier output)"""
    bl_idname = "adm.generate_lods"
    bl_label = "Generate LODs"
    bl_options = {"REGISTER", "UNDO"}

    levels: IntProperty(name="Levels", default=4, min=2, max=MAX_LEVELS,
                        description="Total level count including the original LOD0")
    ratios: FloatVectorProperty(name="Triangle Ratio", size=MAX_LEVELS - 1, min=0.001, max=0.999,
                                default=(0.5, 0.25, 0.1, 0.05, 0.02),
                                description="Fraction of LOD0 triangles kept by LOD1, LOD2, ...")
    distances: FloatVectorProperty(name="Switch Distance", size=MAX_LEVELS - 1, min=0.001, unit="LENGTH",
                                   default=(15.0, 40.0, 100.0, 200.0, 400.0),
                                   description="Camera distance in meters where LOD1, LOD2, ... starts")
    morph_max_lod: IntProperty(name="Shape Keys Up To LOD", default=2, min=0, max=MAX_LEVELS - 1,
                               description="Transfer shape keys to LOD1..this level; farther levels drop them")
    protect_screens: BoolProperty(name="Keep Interactive Screens", default=True,
                                  description="Never decimate faces using the interactive surface shader")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and lod_source_of(context.active_object) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.prop(self, "levels")
        col = lay.column(align=True)
        for i in range(self.levels - 1):
            row = col.row(align=True)
            row.label(text=f"LOD{i + 1}")
            row.prop(self, "ratios", index=i, text="")
            row.prop(self, "distances", index=i, text="")
        lay.prop(self, "morph_max_lod")
        lay.prop(self, "protect_screens")

    def execute(self, context):
        source = lod_source_of(context.active_object)
        try:
            group, out = generate_lods(context, source, self.levels, self.ratios, self.distances,
                                       self.morph_max_lod, self.protect_screens)
        except LodError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        make_active(context, group)
        base = triangle_count(source.data)
        summary = ", ".join(f"LOD{i} {tris}" + (" +morphs" if morphs else "") for i, tris, morphs in out)
        self.report({"INFO"}, f"LOD0 {base} tris; {summary}")
        return {"FINISHED"}


CLASSES = (ADM_OT_generate_lods,)
