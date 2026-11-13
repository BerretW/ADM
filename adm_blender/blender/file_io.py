"""File > Import / Export operators, drag & drop file handlers."""

import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .export_adm import ExportError, ExportOptions, export_model, find_model_root
from .import_adm import ImportError_, ImportOptions, import_model
from .operators import active_armature, show_report


def _prefs(context):
    from .. import __package__ as pkg
    addon = context.preferences.addons.get(pkg)
    return addon.preferences if addon else None


class ADM_OT_import(bpy.types.Operator, ImportHelper):
    """Import ADM 1.0 model(s) (.adm)"""
    bl_idname = "import_scene.adm"
    bl_label = "Import ADM"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filename_ext = ".adm"
    filter_glob: StringProperty(default="*.adm", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    import_normals: BoolProperty(name="Custom Normals", default=True,
                                 description="Apply the stored vertex normals as custom split normals")
    weld: BoolProperty(name="Weld Vertices", default=True,
                       description="Merge vertices split only by UV/normal seams into one Blender vertex")
    collection: BoolProperty(name="New Collection", default=True, description="Put each model in its own collection")

    def draw(self, context):
        col = self.layout.column(heading="Geometry")
        col.prop(self, "import_normals")
        col.prop(self, "weld")
        self.layout.prop(self, "collection")

    def execute(self, context):
        paths = [os.path.join(self.directory, f.name) for f in self.files if f.name] or [self.filepath]
        opts = ImportOptions(import_normals=self.import_normals, weld=self.weld, collection=self.collection)
        ok = 0
        for path in paths:
            try:
                imp, root = import_model(context, path, opts)
            except ImportError_ as exc:
                show_report(context, os.path.basename(path), exc.report, [exc])
                self.report({"ERROR"}, f"{os.path.basename(path)}: {exc}")
                continue
            ok += 1
            for w in imp.warnings:
                self.report({"WARNING"}, w)
            show_report(context, os.path.basename(path), None, (), imp.warnings)
        if not ok:
            return {"CANCELLED"}
        self.report({"INFO"}, f"imported {ok} ADM model(s)")
        return {"FINISHED"}


class ADM_OT_export(bpy.types.Operator, ExportHelper):
    """Export an ADM 1.0 model (.adm). Uses the Model Root of the active object when there is one"""
    bl_idname = "export_scene.adm"
    bl_label = "Export ADM"
    bl_options = {"REGISTER", "PRESET"}

    filename_ext = ".adm"
    filter_glob: StringProperty(default="*.adm", options={"HIDDEN"})

    scope: EnumProperty(name="Export", default="ROOT", items=[
        ("ROOT", "Active Model Root", "The Model Root containing the active object"),
        ("ALL_ROOTS", "All Model Roots", "Every Model Root in the view layer, one file per root (named after it)"),
        ("SELECTED", "Selected Objects", "Selection as one scene (no Model Root needed)"),
        ("SCENE", "Visible Scene", "Whole view layer as one scene")])
    apply_modifiers: BoolProperty(name="Apply Modifiers", default=True)
    export_normals: BoolProperty(name="Normals", default=True)
    export_tangents: EnumProperty(name="Tangents", default="AUTO", items=[
        ("AUTO", "Auto", "Only for meshes with a normal map"), ("ALWAYS", "Always", ""), ("NEVER", "Never", "")])
    export_uv1: BoolProperty(name="Second UV Map", default=True)
    export_colors: BoolProperty(name="Vertex Colors", default=True)
    export_morph_normals: BoolProperty(name="Shape Key Normals", default=True)
    export_materials: BoolProperty(name="Materials", default=True)
    embed_textures: BoolProperty(name="Embed Textures", default=True,
                                 description="Store images inside the ADM. When disabled, write safe relative "
                                             "references and copy images under textures/")
    vertex_controls: BoolProperty(name="ADM Vertex Controls", default=False,
                                  description="Interpret color attributes named COLOR_0/COLOR_1 using "
                                              "ADM_vertex_control_v1 semantics")
    image_format: EnumProperty(name="Images", default="PNG", items=[
        ("PNG", "PNG", "Embed every texture as PNG; JPEG, DDS, KTX2, TGA, EXR… sources are converted. "
                       "Readable by every ADM reader"),
        ("AUTO", "Keep PNG/JPEG", "Keep PNG/JPEG source bytes unchanged, convert everything else to PNG"),
        ("KTX2", "KTX2 + PNG fallback", "GPU-ready KTX2 (optional capability ADM-TEX-KTX2-1) plus the "
                                        "mandatory PNG fallback for readers without KTX2"),
        ("DDS", "DDS + PNG fallback", "GPU-ready DDS/DX10 (optional capability ADM-TEX-DDS-1) plus the "
                                      "mandatory PNG fallback for readers without DDS")])
    gpu_compression: EnumProperty(name="GPU Format", default="AUTO", items=[
        ("AUTO", "Auto (BC1/BC3)", "BC1 for opaque textures, BC3 when the texture has alpha"),
        ("BC1", "BC1 / DXT1", "4 bpp, no alpha"),
        ("BC3", "BC3 / DXT5", "8 bpp with alpha"),
        ("RGBA8", "RGBA8 (uncompressed)", "Lossless, 32 bpp")])
    gpu_mipmaps: BoolProperty(name="Mipmaps", default=True,
                              description="Store a full mip chain in the KTX2/DDS image")

    def invoke(self, context, event):
        root = find_model_root(context.active_object) if context.active_object else None
        if root is not None:
            self.filepath = bpy.path.clean_name(root.name) + self.filename_ext
        elif not any(o.adm.adm_type == "MODEL" for o in context.view_layer.objects):
            self.scope = "SELECTED" if context.selected_objects else "SCENE"
        return super().invoke(context, event)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.prop(self, "scope")
        col = lay.column(heading="Mesh")
        for p in ("apply_modifiers", "export_normals", "export_tangents", "export_uv1", "export_colors",
                  "export_morph_normals"):
            col.prop(self, p)
        col = lay.column(heading="Material")
        col.prop(self, "export_materials")
        col.prop(self, "embed_textures")
        col.prop(self, "vertex_controls")
        col.prop(self, "image_format")
        if self.image_format in ("KTX2", "DDS"):
            sub = col.column()
            sub.prop(self, "gpu_compression")
            sub.prop(self, "gpu_mipmaps")

    def _options(self, selected):
        return ExportOptions(selected_only=selected, apply_modifiers=self.apply_modifiers,
                             export_normals=self.export_normals, export_tangents=self.export_tangents,
                             export_uv1=self.export_uv1, export_colors=self.export_colors,
                             export_morph_normals=self.export_morph_normals,
                             export_materials=self.export_materials, embed_textures=self.embed_textures,
                             vertex_controls=self.vertex_controls,
                             image_format=self.image_format,
                             gpu_compression=self.gpu_compression, gpu_mipmaps=self.gpu_mipmaps)

    def _one(self, context, path, root, selected):
        try:
            exp, report = export_model(context, path, root, self._options(selected))
        except ExportError as exc:
            show_report(context, os.path.basename(path), exc.report, [exc])
            self.report({"ERROR"}, f"{exc} - see ADM > Validation")
            return False
        for w in exp.warnings:
            self.report({"WARNING"}, w)
        show_report(context, os.path.basename(path), report, (), exp.warnings)
        return True

    def execute(self, context):
        if self.scope == "ROOT":
            root = find_model_root(context.active_object) if context.active_object else None
            if root is None:
                self.report({"ERROR"}, "The active object is not inside an ADM Model Root "
                                       "(create one in the ADM sidebar or choose another export scope)")
                return {"CANCELLED"}
            ok = self._one(context, self.filepath, root, False)
        elif self.scope == "ALL_ROOTS":
            roots = sorted((o for o in context.view_layer.objects if o.adm.adm_type == "MODEL"), key=lambda o: o.name)
            folder = os.path.dirname(self.filepath)
            ok = bool(roots)
            for r in roots:
                ok &= self._one(context, os.path.join(folder, bpy.path.clean_name(r.name) + ".adm"), r, False)
        else:
            ok = self._one(context, self.filepath, None, self.scope == "SELECTED")
        if ok:
            self.report({"INFO"}, f"exported {os.path.basename(self.filepath)}")
        return {"FINISHED"} if ok else {"CANCELLED"}


def _armature_items(self, context):
    items = [(o.name, o.name, "", "ARMATURE_DATA", i + 1)
             for i, o in enumerate(sorted((o for o in bpy.data.objects if o.type == "ARMATURE"),
                                          key=lambda o: o.name))]
    return items + [("__NONE__", "(none - model.any.v1 only)", "Material / morph animation without a rig",
                     "BLANK1", 0)]


class ADM_OT_import_anim(bpy.types.Operator, ImportHelper):
    """Import an ADM animation library (.adm_anim) onto an armature"""
    bl_idname = "import_anim.adm_anim"
    bl_label = "Import ADM Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".adm_anim"
    filter_glob: StringProperty(default="*.adm_anim", options={"HIDDEN"})
    armature: EnumProperty(name="Rig", items=_armature_items)
    strict: BoolProperty(name="Strict Compatibility", default=True,
                         description="Refuse libraries whose profile or rigId does not match the rig")
    allow_provisional: BoolProperty(name="Allow Provisional Profiles", default=True,
                                    description="Bind SEMANTIC libraries of PROVISIONAL (animal) profiles to a rig "
                                                "declaring the same profile (not certified interoperable)")
    frame_start: IntProperty(name="Start Frame", default=1)

    def invoke(self, context, event):
        arm = active_armature(context)
        if arm is not None:
            self.armature = arm.name
        return super().invoke(context, event)

    def execute(self, context):
        from .import_anim import AnimImportOptions, import_library
        arm = bpy.data.objects.get(self.armature) if self.armature != "__NONE__" else None
        if self.armature != "__NONE__" and (arm is None or arm.type != "ARMATURE"):
            arm = active_armature(context)
        try:
            imp, lib = import_library(context, self.filepath,
                                      AnimImportOptions(armature=arm, strict=self.strict,
                                                        allow_provisional=self.allow_provisional,
                                                        frame_start=self.frame_start))
        except ImportError_ as exc:
            show_report(context, os.path.basename(self.filepath), exc.report, [exc])
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for w in imp.warnings:
            self.report({"WARNING"}, w)
        show_report(context, os.path.basename(self.filepath), None, (), imp.warnings)
        self.report({"INFO"}, f"imported {len(lib.clips)} clip(s) from {lib.lib_id}")
        return {"FINISHED"}


class ADM_OT_export_anim(bpy.types.Operator, ExportHelper):
    """Export the active ADM animation library (.adm_anim)"""
    bl_idname = "export_anim.adm_anim"
    bl_label = "Export ADM Animation"
    bl_options = {"REGISTER"}

    filename_ext = ".adm_anim"
    filter_glob: StringProperty(default="*.adm_anim", options={"HIDDEN"})
    all_libraries: BoolProperty(name="All Libraries", default=False,
                                description="Export every library of the scene into the chosen folder")
    sample_step: IntProperty(name="Sample Step", default=1, min=1, max=10)
    optimize: BoolProperty(name="Optimize Keys", default=True,
                           description="Drop constant tracks and keys reproducible by linear interpolation")

    @classmethod
    def poll(cls, context):
        return len(context.scene.adm_anim.libraries) > 0

    def invoke(self, context, event):
        s = context.scene.adm_anim
        if 0 <= s.active_library < len(s.libraries):
            self.filepath = s.libraries[s.active_library].lib_id.replace("@", "_") + self.filename_ext
        return super().invoke(context, event)

    def execute(self, context):
        from .export_anim import AnimExportOptions, export_library
        s = context.scene.adm_anim
        libs = list(s.libraries) if self.all_libraries else \
            ([s.libraries[s.active_library]] if 0 <= s.active_library < len(s.libraries) else [])
        opts = AnimExportOptions(sample_step=self.sample_step, optimize=self.optimize)
        ok = bool(libs)
        for lib in libs:
            path = self.filepath if not self.all_libraries else \
                os.path.join(os.path.dirname(self.filepath), lib.lib_id.replace("@", "_") + ".adm_anim")
            try:
                exp, report = export_library(context, lib, path, opts)
            except ExportError as exc:
                show_report(context, lib.lib_id, exc.report, [exc])
                self.report({"ERROR"}, f"{lib.lib_id}: {exc}")
                ok = False
                continue
            for w in exp.warnings:
                self.report({"WARNING"}, w)
            show_report(context, os.path.basename(path), report, (), exp.warnings)
        return {"FINISHED"} if ok else {"CANCELLED"}


class ADM_FH_model(bpy.types.FileHandler):
    bl_idname = "ADM_FH_model"
    bl_label = "ADM Model"
    bl_import_operator = "import_scene.adm"
    bl_export_operator = "export_scene.adm"
    bl_file_extensions = ".adm"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type in {"VIEW_3D", "OUTLINER"}


class ADM_FH_anim(bpy.types.FileHandler):
    bl_idname = "ADM_FH_anim"
    bl_label = "ADM Animation Library"
    bl_import_operator = "import_anim.adm_anim"
    bl_file_extensions = ".adm_anim"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type in {"VIEW_3D", "OUTLINER", "DOPESHEET_EDITOR"}


def menu_import(self, context):
    self.layout.operator(ADM_OT_import.bl_idname, text="ADM Model (.adm)")
    self.layout.operator(ADM_OT_import_anim.bl_idname, text="ADM Animation (.adm_anim)")


def menu_export(self, context):
    self.layout.operator(ADM_OT_export.bl_idname, text="ADM Model (.adm)")
    self.layout.operator(ADM_OT_export_anim.bl_idname, text="ADM Animation (.adm_anim)")


CLASSES = (ADM_OT_import, ADM_OT_export, ADM_OT_import_anim, ADM_OT_export_anim, ADM_FH_model, ADM_FH_anim)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
