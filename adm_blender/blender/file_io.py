"""File > Import / Export operators, drag & drop file handlers."""

import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .export_adm import ExportError, ExportOptions, default_export_options, export_model, find_model_root
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


def _update_export_scope(self, context):
    if self.vertex_controls_manual:
        return
    root = find_model_root(context.active_object) if context.active_object else None
    if self.scope == "ALL_ROOTS":
        enabled = any(default_export_options(context, obj).vertex_controls
                      for obj in context.view_layer.objects if obj.adm.adm_type == "MODEL")
    else:
        enabled = default_export_options(context, root if self.scope == "ROOT" else None,
                                         self.scope == "SELECTED").vertex_controls
    self.vertex_controls_auto = True
    try:
        self.vertex_controls = enabled
    finally:
        self.vertex_controls_auto = False


def _update_export_vertex_controls(self, context):
    if not self.vertex_controls_auto:
        self.vertex_controls_manual = True


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
        ("SCENE", "Visible Scene", "Whole view layer as one scene")], update=_update_export_scope)
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
    vertex_controls: BoolProperty(name="ADM Vertex Controls", default=False, update=_update_export_vertex_controls,
                                  description="Use ADM_vertex_control_v1 semantics for COLOR_0 and COLOR_1; "
                                              "required to export authored COLOR_1 masks for 2.0.0 profiles")
    vertex_controls_manual: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    vertex_controls_auto: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
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
        explicit_vertex_controls = self.properties.is_property_set("vertex_controls")
        root = find_model_root(context.active_object) if context.active_object else None
        if root is not None:
            self.filepath = bpy.path.clean_name(root.name) + self.filename_ext
        elif not self.properties.is_property_set("scope"):
            self.scope = "SELECTED" if context.selected_objects else "SCENE"
        if not explicit_vertex_controls:
            _update_export_scope(self, context)
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
    return items + [("__NONE__", "(none)", "No armature for model.any.v1 or mechanical component libraries",
                     "BLANK1", 0)]


def _model_root_items(self, context):
    items = [(o.name, o.name, "", "OUTLINER_OB_EMPTY", i + 1)
             for i, o in enumerate(sorted((o for o in bpy.data.objects if o.adm.adm_type == "MODEL"),
                                          key=lambda o: o.name))]
    return items + [("__NONE__", "(none)", "Only mechanical component libraries need a model root",
                     "BLANK1", 0)]


def _mixamo_armature_items(self, context):
    objects = sorted((o for o in context.view_layer.objects if o.type == "ARMATURE"), key=lambda o: o.name)
    return [(o.name, o.name, "", "ARMATURE_DATA", i + 1) for i, o in enumerate(objects)] or [
        ("__NONE__", "(no armatures in this scene)", "", "BLANK1", 0)]


def _mixamo_library_items(self, context):
    target = bpy.data.objects.get(self.target_armature)
    items = []
    for i, lib in enumerate(context.scene.adm_anim.libraries):
        if lib.target == "RIG" and (target is None or lib.armature == target):
            items.append((str(i), f"{lib.title or lib.lib_id} ({lib.lib_id})",
                          "Append the imported clip to this animation library", "ACTION", i + 1))
    return items or [("__NONE__", "(no libraries for this rig)", "", "BLANK1", 0)]


def _fbx_data_ids():
    names = ("actions", "armatures", "cameras", "collections", "curves", "images", "lights",
             "materials", "meshes")
    return {name: set(getattr(bpy.data, name)) for name in names}


def _remove_fbx_import(new_objects, new_data):
    for obj in list(new_objects):
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
    for name in ("actions", "meshes", "armatures", "curves", "cameras", "lights", "materials", "images"):
        collection = getattr(bpy.data, name)
        for datablock in list(new_data.get(name, ())):
            if datablock.name not in collection:
                continue
            if getattr(datablock, "use_fake_user", False):
                datablock.use_fake_user = False
            if datablock.users == 0:
                collection.remove(datablock)
    remaining = list(new_data.get("collections", ()))
    while remaining:
        removable = [collection for collection in remaining
                     if (collection.name in bpy.data.collections and not collection.objects
                         and not collection.children)]
        if not removable:
            break
        for collection in removable:
            bpy.data.collections.remove(collection)
            remaining.remove(collection)


class ADM_OT_import_anim(bpy.types.Operator, ImportHelper):
    """Import an ADM animation library (.adm_anim) onto a rig or model root"""
    bl_idname = "import_anim.adm_anim"
    bl_label = "Import ADM Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".adm_anim"
    filter_glob: StringProperty(default="*.adm_anim", options={"HIDDEN"})
    armature: EnumProperty(name="Rig", items=_armature_items)
    model_root: EnumProperty(name="Model Root", items=_model_root_items)
    strict: BoolProperty(name="Strict Compatibility", default=True,
                         description="Refuse libraries whose profile or rigId does not match the rig")
    allow_provisional: BoolProperty(name="Allow Provisional Profiles", default=True,
                                    description="Bind SEMANTIC libraries of PROVISIONAL (animal) profiles to a rig "
                                                "declaring the same profile (not certified interoperable)")
    frame_start: IntProperty(name="Start Frame", default=1)
    match_source_frame_rate: BoolProperty(
        name="Match Source Frame Rate", default=True,
        description="Set the scene frame rate from the animation file to preserve its frame range")

    def invoke(self, context, event):
        arm = active_armature(context)
        if arm is not None:
            self.armature = arm.name
        root = find_model_root(context.active_object) if context.active_object else None
        if root is not None:
            self.model_root = root.name
        return super().invoke(context, event)

    def draw(self, context):
        self.layout.prop(self, "armature")
        self.layout.prop(self, "model_root")
        self.layout.prop(self, "strict")
        self.layout.prop(self, "allow_provisional")
        self.layout.prop(self, "frame_start")
        self.layout.prop(self, "match_source_frame_rate")

    def execute(self, context):
        from .import_anim import AnimImportOptions, import_library
        arm = bpy.data.objects.get(self.armature) if self.armature != "__NONE__" else None
        root = bpy.data.objects.get(self.model_root) if self.model_root != "__NONE__" else None
        if self.armature != "__NONE__" and (arm is None or arm.type != "ARMATURE"):
            arm = active_armature(context)
        if self.model_root != "__NONE__" and (root is None or root.adm.adm_type != "MODEL"):
            root = find_model_root(context.active_object) if context.active_object else None
        try:
            imp, lib = import_library(context, self.filepath,
                                      AnimImportOptions(armature=arm, model_root=root, strict=self.strict,
                                                        allow_provisional=self.allow_provisional,
                                                        frame_start=self.frame_start,
                                                        match_source_frame_rate=self.match_source_frame_rate))
        except ImportError_ as exc:
            show_report(context, os.path.basename(self.filepath), exc.report, [exc])
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for w in imp.warnings:
            self.report({"WARNING"}, w)
        show_report(context, os.path.basename(self.filepath), None, (), imp.warnings)
        self.report({"INFO"}, f"imported {len(lib.clips)} clip(s) from {lib.lib_id}")
        return {"FINISHED"}


class ADM_OT_import_mixamo_animation(bpy.types.Operator, ImportHelper):
    """Import a Mixamo FBX action and retarget it onto a humanoid ADM rig"""
    bl_idname = "import_anim.mixamo_fbx"
    bl_label = "Import Mixamo Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})
    target_armature: EnumProperty(name="Target Rig", items=_mixamo_armature_items)
    library_mode: EnumProperty(name="Library", default="NEW", items=[
        ("NEW", "Create New", "Create a new animation library"),
        ("EXISTING", "Append to Existing", "Add the clip to a library for the chosen rig"),
    ])
    existing_library: EnumProperty(name="Destination", items=_mixamo_library_items)
    library_id: StringProperty(name="Library ID", default="mixamo@animations")
    library_title: StringProperty(name="Library Title", default="Mixamo Animations")
    library_description: StringProperty(name="Library Description")
    clip_id: StringProperty(name="Clip ID", default="mixamo_clip")
    clip_title: StringProperty(name="Clip Title", default="Mixamo Animation")
    clip_description: StringProperty(name="Clip Description")
    root_motion: EnumProperty(name="Root Motion", default="EXTRACT", items=[
        ("EXTRACT", "Extract Hips Translation", "Preserve the animated hips translation"),
        ("IN_PLACE", "In Place", "Do not export hips translation"),
        ("IGNORE", "Ignore", "Ignore extracted root motion on import"),
    ])
    keep_source: BoolProperty(
        name="Keep Imported FBX Objects", default=False,
        description="Keep the imported Mixamo armature and meshes in the scene after retargeting")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def invoke(self, context, event):
        arm = active_armature(context)
        if arm is not None and arm.name in context.view_layer.objects:
            self.target_armature = arm.name
        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_armature")
        layout.prop(self, "library_mode")
        if self.library_mode == "NEW":
            col = layout.column()
            col.use_property_split = True
            col.prop(self, "library_id")
            col.prop(self, "library_title")
            col.prop(self, "library_description")
        else:
            layout.prop(self, "existing_library")
        col = layout.column()
        col.use_property_split = True
        col.prop(self, "clip_id")
        col.prop(self, "clip_title")
        col.prop(self, "clip_description")
        layout.prop(self, "root_motion")
        layout.prop(self, "keep_source")

    def execute(self, context):
        target = bpy.data.objects.get(self.target_armature)
        if target is None or target.type != "ARMATURE" or target.name not in context.view_layer.objects:
            self.report({"ERROR"}, "Choose an armature in the current scene as the target rig")
            return {"CANCELLED"}
        if target.data.adm.profile_id.strip() != "humanoid.vrm1":
            self.report({"ERROR"}, "The target rig must use the humanoid.vrm1 profile")
            return {"CANCELLED"}
        if not self.filepath or not os.path.isfile(self.filepath) or not self.filepath.lower().endswith(".fbx"):
            self.report({"ERROR"}, "Choose an existing .fbx file")
            return {"CANCELLED"}
        if not hasattr(bpy.ops.import_scene, "fbx"):
            self.report({"ERROR"}, "Blender's FBX importer is unavailable")
            return {"CANCELLED"}

        library_index = None
        if self.library_mode == "EXISTING":
            if self.existing_library == "__NONE__":
                self.report({"ERROR"}, "Choose an existing animation library for the target rig")
                return {"CANCELLED"}
            try:
                library_index = int(self.existing_library)
            except ValueError:
                self.report({"ERROR"}, "The selected animation library is invalid")
                return {"CANCELLED"}

        objects_before = set(bpy.data.objects)
        data_before = _fbx_data_ids()
        selected_before = set(context.selected_objects)
        active_before = context.view_layer.objects.active
        scene = context.scene
        scene_state = (scene.render.fps, scene.render.fps_base, scene.frame_current,
                       scene.frame_start, scene.frame_end)
        source_objects = set()
        source_data = {}
        source_armature = None
        source_action = None
        importer = None
        result_library = None
        result_clip = None
        export_warnings = ()
        succeeded = False
        try:
            imported = bpy.ops.import_scene.fbx(
                filepath=self.filepath,
                use_anim=True,
                global_scale=1.0,
                automatic_bone_orientation=False,
                use_custom_props=False,
                axis_forward="-Z",
                axis_up="Y",
            )
            source_objects = set(bpy.data.objects) - objects_before
            source_data = {name: set(getattr(bpy.data, name)) - values
                           for name, values in data_before.items()}
            if "FINISHED" not in imported:
                raise RuntimeError("Blender cancelled the FBX import")

            armatures = [obj for obj in source_objects if obj.type == "ARMATURE"]
            if len(armatures) != 1:
                raise ValueError(f"FBX must contain exactly one armature; found {len(armatures)}")
            source_armature = armatures[0]
            new_actions = source_data.get("actions", set())
            if len(new_actions) != 1:
                raise ValueError(f"FBX must contain exactly one animation action; found {len(new_actions)}")
            imported_action = next(iter(new_actions))
            assigned_action = (source_armature.animation_data.action
                               if source_armature.animation_data else None)
            if assigned_action is None:
                assigned_action = imported_action
                from .export_anim import pick_slot
                animation_data = source_armature.animation_data_create()
                animation_data.action = assigned_action
                slot = pick_slot(assigned_action, "OBJECT", (source_armature.name,))
                if slot is not None:
                    animation_data.action_slot = slot
            if assigned_action != imported_action:
                raise ValueError("the imported armature is not assigned the FBX animation action")
            source_action = assigned_action

            from .mixamo_import import retarget_mixamo_action
            importer, result_library, result_clip, export_warnings = retarget_mixamo_action(
                context, source_armature, source_action, target,
                library_index=library_index,
                library_id=self.library_id,
                library_title=self.library_title,
                library_description=self.library_description,
                clip_id=self.clip_id,
                clip_title=self.clip_title,
                clip_description=self.clip_description,
                root_motion=self.root_motion,
            )
            succeeded = True
        except (ExportError, ImportError_, OSError, RuntimeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
        finally:
            if not succeeded and not source_objects:
                source_objects = set(bpy.data.objects) - objects_before
                source_data = {name: set(getattr(bpy.data, name)) - values
                               for name, values in data_before.items()}
            if not succeeded or not self.keep_source:
                _remove_fbx_import(source_objects, source_data)
            if succeeded:
                for obj in context.view_layer.objects:
                    obj.select_set(False)
                target.select_set(True)
                context.view_layer.objects.active = target
            else:
                scene.render.fps, scene.render.fps_base = scene_state[:2]
                scene.frame_start, scene.frame_end = scene_state[3:5]
                scene.frame_set(scene_state[2])
                for obj in context.view_layer.objects:
                    obj.select_set(obj in selected_before)
                if active_before is not None and active_before.name in context.view_layer.objects:
                    context.view_layer.objects.active = active_before

        if not succeeded:
            return {"CANCELLED"}
        warnings = list(export_warnings) + list(importer.warnings)
        for warning in warnings:
            self.report({"WARNING"}, warning)
        show_report(context, os.path.basename(self.filepath), None, (), warnings)
        self.report({"INFO"}, f"imported {result_clip.clip_id} into {result_library.lib_id} "
                              f"(frames {result_clip.action.frame_range[0]:g}-"
                              f"{result_clip.action.frame_range[1]:g})")
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
    self.layout.operator(ADM_OT_import_mixamo_animation.bl_idname, text="Mixamo Animation (.fbx)")


def menu_export(self, context):
    self.layout.operator(ADM_OT_export.bl_idname, text="ADM Model (.adm)")
    self.layout.operator(ADM_OT_export_anim.bl_idname, text="ADM Animation (.adm_anim)")


CLASSES = (ADM_OT_import, ADM_OT_export, ADM_OT_import_anim, ADM_OT_import_mixamo_animation,
           ADM_OT_export_anim, ADM_FH_model, ADM_FH_anim)


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
