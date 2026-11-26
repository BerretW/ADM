# ADM Tools for Blender (5.2+)

Blender extension for **ADM 1.0 – Development / Experimental**
(`adm-standard/ADM-1.0-SPEC.md`).
The workflow and layout follow Sollumz: object types, create/convert tools, a sidebar tab,
validation and import/export. This is a reference implementation; its tests do not constitute
independent ADM conformance certification or proof of interoperability. ADM is an
implementation-independent open standard. Incompatible changes are allowed during development;
historical files may not be supported or migrated. A stable public version will be declared only
by a separate decision.

The ADM edition, binary file-format, extensions, shader contracts and Blender add-on have
independent version identifiers. See the [version policy](../adm-standard/ADM-1.0-SPEC.md#28-development-version-policy-extension-registry-and-governance)
and [development-change controls](../adm-standard/SPEC_GAPS.md#shader-development-change-control).

## Installation

- **Simplest:** zip the `adm_blender` folder (e.g. right-click › *Send to › Compressed folder*) and install
  the zip via *Edit › Preferences › Get Extensions › ⌄ › Install from Disk…*. You can also drag the zip into Blender.
- **Alternative:** `blender --command extension build --source-dir adm_blender` builds a smaller package
  without `tests/` and `__pycache__`.
- The sidebar tab name is set in the extension preferences (default `ADM`).
- After updating from 1.18.0 or earlier, save your work and restart Blender once. Those versions
  could keep old material properties in memory after an update, causing `shader_version` errors
  during **Convert Materials To ADM**. New versions reload the extension's modules together.

## Workflow

1. **Tools tab (N-panel › ADM)**: create a Model Root, Scene, LOD, Collider or Attachment, or convert
   the selection to an ADM type. This is the Sollumz-style "Create / Convert" approach.
2. **Object**: set the ADM type of the active object, plus its LOD, collider and attachment properties.
   **Generate LODs** (Tools › Create, or *Regenerate LODs* on a LOD group) builds LOD1…LODn of the
   active mesh with Blender's Decimate (Collapse) and wires them into an ADM LOD group. Defaults are
   four levels: LOD0 (original, 0 m), LOD1 50 % triangles at 15 m, LOD2 25 % at 40 m, LOD3 10 % at
   100 m. Every level is decimated from LOD0, keeps materials, UVs, `COLOR_0`/`COLOR_1`, skin vertex
   groups, the modifier stack and interactive surface IDs. Interactive screen faces are never
   decimated (the reduction target excludes them), so one `surfaceId` binds the screen on every
   level. Shape keys follow common game practice: they are transferred to near levels (default
   LOD1–LOD2, *Shape Keys Up To LOD*) and dropped on far levels. The morph deltas are carried through
   the decimation as interpolated vertex attributes, so close surfaces such as lips do not mix; keys
   keep their names, relative keys, ranges and vertex groups, so `.adm_anim` morph channels drive all
   levels by name. Running it again replaces the levels it generated earlier; manual levels stay.
   Limits: shape-key drivers and Facial Profile/expression bindings are not copied to generated levels,
   absolute shape keys are rejected, and colliders are not affected by LOD.
3. **Skeleton**: pick the profile (`humanoid.vrm1`, `generic.v1` or custom) and run *Auto Map Roles*. This
   recognises Mixamo, VRM, Unreal and Blender naming. It also covers *Compute rigId* and IK chains.
4. **Face & Expressions**: facial bindings to shape keys and expressions.
5. **Shaders**: shader definitions (`shaderDefinitions`) with parameters, and custom-shader assignment.
6. **Animation**: clip libraries (Actions → clips). You can choose:
   - for rig libraries, the binding: `SEMANTIC` (by role) or `EXACT` (one rig, `rigId`);
   - the target: armature, `model.any`, or vehicle/firearm mechanical components.
   `SEMANTIC` rotation tracks are expressed in model-root space and converted through the target
   armature object's transform on import. They animate mapped roles only; use `EXACT` to preserve
   custom/helper bone tracks on the identical rig.
   Mechanical libraries are always `SEMANTIC`: choose their Model Root and matching profile, then animate
   objects marked with unique component roles. Import/export uses rest-relative translation and rotation
   deltas, and checks sampled tracks against the profile's axes and declared steering, hinge, or
   articulation ranges.
7. **Validation**: container and model/animation schema validation, with a report.

On the **Model Root**, the Object panel also edits **Physical Materials**, **Model Components** and
**Hitboxes**. Components reference an object or armature bone and an optional attachment socket.
Hitboxes reference an exported collider and an optional collider node/ancestor; physical material IDs
are assigned on colliders. For a MESH collider, select faces in Edit Mode, choose the physical ID on
the collider, return to Object Mode, and click **Assign Surface To Selected Faces**. Unassigned faces
use the collider's default ID. These are asset descriptors, not physics simulation or damage behavior.
Vehicle and firearm profiles are normative ADM 1.0 annexes; independent profile certification is
separate. Physics and game behavior are not defined by the format.

**Import and export:** use *File › Import/Export › ADM Model (.adm)* and *ADM Animation Library*.
Drag & drop of `.adm` files also works.
Exporting a mesh in Edit Mode uses its current edits and UVs without leaving Edit Mode.
ADM exports retain Blender bone display tails and roll through the required `ADM_joint_display_v1`
extension. `ADM_animation_timing_v1` version 1.1.0 records the project FPS plus each clip's FPS and
frame range. Changing a clip's FPS while keeping its frame range changes its playback speed and
duration. **Play Clip** applies that clip's rate to Blender's scene, which has one active frame rate.
Animation import preserves per-clip rates by default and reports project-rate changes. The earlier
1.0.0 timing payload is rejected and is not migrated automatically. Import rejects skeleton files
missing required display data rather than guessing bone tails or roll.

**Mixamo FBX:** use *File › Import › Mixamo Animation (.fbx)* or the button in **Animation Libraries**.
Choose the target armature (it must use `humanoid.vrm1`), then create a library or append to one for that
rig, and enter the required library/clip names and descriptions. The importer requires exactly one FBX
armature and one action, maps Mixamo bone names, normalizes both rigs, and retargets through ADM's
`SEMANTIC` animation pipeline. If the source faces +Z, it is rotated 180 degrees to match ADM's -Z
humanoid forward direction. Hips translation is extracted by default; the dialog can switch to
in-place or ignored root motion. Animation frame rate and frame range are preserved by the ADM timing
extension. Imported FBX objects are removed after success by default; enable **Keep Imported FBX Objects**
to retain the source rig and meshes for inspection.

**BVH animation:** click **Import BVH Animation** in **Animation Libraries**, or choose
*File › Import › BVH Animation (.bvh)*. The active rig is selected by default; if the scene has one
armature and no active rig, the wizard selects it. Otherwise, search for the rig by name under
**Target Rig** at the top of the import options. This field keeps the selected object name while
the preview is refreshed or removed. The target must use `humanoid.vrm1`. Select one or more BVH
files. The wizard checks the hierarchy and frame data before import, shows frame count,
frame rate, duration and joint-mapping totals, and asks you to confirm. It suggests roles from joint
names; if a required role is missing, add overrides in `JointName=humanoidRole` form, separated by
semicolons or newlines. The mapping must cover every required humanoid role. Blender operator presets
can save reusable mapping overrides.

Create a library or append the clips to a library for the selected rig. A batch uses each filename
as its clip ID and title, and each clip keeps its parsed FPS by default. Change the per-file FPS in
the confirmation dialog to change that clip's playback speed without resampling its frames. The
dialog shows a live armature preview for the first file. Change **Forward** and **Up** to adjust the
BVH axis conversion; **Align lowest bone to ground** and **Preview Translation** adjust the displayed
preview and any retained source armature. These placement controls do not move the retargeted target
rig. The Blender importer supports source and clip rates from 0.001 through 1000 FPS and reports
rates outside that range. The wizard preserves library author, license, revision, namespace and tags.
It records each source filename in the clip description. Hips translation is extracted by default; you can choose
in-place or ignored root motion. The source armature is removed after retargeting by default; enable
**Keep Imported BVH Rig** to retain it.

The wizard uses Blender's BVH importer after ADM Tools validates the file and proposes a complete
humanoid role map. A complete name-based map is not proof that the source has a compatible reference
pose or facing direction; the retargeter reports adjustments and warnings. Files without a complete
humanoid role map are rejected unless you supply the missing role overrides. BVH import does not claim
support for non-humanoid retargeting or independent interoperability.

### Vertex color layers and tint swatches

**ADM > Object > Vertex Colors** (also in the material's **ADM Vertex Control** box) manages
the actual Blender color attributes, not a separate color system.

- Enabling **Enable Vertex Controls** on a material initializes the active object and meshes
  inside an ADM Model Root that use it. A new mesh added to an ADM model with that enabled material
  is initialized on the next UI tick. **Convert Materials To ADM** initializes the selected objects
  by default; its redo option can disable initialization. Meshes outside an ADM model are never
  changed automatically, and ordinary ADM imports without vertex controls are not changed.
- **Initialize Layers** creates missing `COLOR_0` and `COLOR_1` without overwriting authored values.
  Control attributes use **FLOAT_COLOR / CORNER**: existing POINT or BYTE_COLOR controls are
  converted with their linear values preserved. Unrelated color attributes are left alone.
- **Reset Defaults** writes `COLOR_0=(0,1,1,0)` and `COLOR_1=(0,0,0,0)`. These mean tint entry 0,
  full normal strength, full base reflectivity and a dry surface. Zero `COLOR_1` disables every
  `2.0.0` mask; `COLOR_1` remains reserved with no effect for `1.0.0` profiles and Interactive Surface.
- Select **Profile Version 2.0.0 (COLOR_1)** on an official shader to activate its four registered
  channel effects. In an ADM Model Root, **Initialize Shader Masks** creates a missing `COLOR_1`
  without overwriting authored values. The panel names each channel, supports Fill/Clear/Invert and
  channel painting, and **Preview Mask** displays the selected layer/channel directly. Per-channel
  strengths and the profile's other mask parameters are edited in the material's shader parameters.
- Choose **All Faces**, **Selected Faces** or **This Material Faces** (every face using the active
  material, regardless of selection), then edit one R/G/B/A channel or all four and click
  **Apply Channels**. Edit Mode uses its live face selection without switching modes. A single-channel
  write preserves the other channels. **Make Active** selects the layer for Blender vertex painting.
- Choose an RGBA **Tint Palette** image 1–5 px high on the active material (only its **top row** is
  the palette; lower rows are ignored), select its swatch and click
  **Apply Palette to R**. Only matching faces using that material are affected. R stores the normalized
  palette position, **not the swatch's RGB or an integer index**. The position accounts for the current
  `tintOffset`; unreachable entries produce an error instead of selecting a different color.
  G/B/A remain unchanged. **Refresh Palette** reloads swatches after image edits.
- Layer edits affect all objects sharing the mesh datablock. Use Blender's single-user mesh command
  first if you need independent colors. Reset/apply actions support Undo.
- With **ADM Vertex Controls** enabled for export, both layers are serialized, using their exact
  standard defaults if missing on the evaluated mesh; exporting never modifies the source mesh.
  Import preserves explicit values and initializes omitted optional controls to their standard defaults.
  The export dialog preselects vertex controls when its scope contains enabled materials or a
  `COLOR_1` attribute unless an explicit setting/preset overrides it. Exporting an authored v2
  `COLOR_1` with that option disabled is rejected rather than silently dropping or reinterpreting it.
  **Validate Model** uses the same automatic default and object scope as the default export: the
  active model root, or selected objects when no root is active, otherwise the visible scene.
  Changing the export scope updates the automatic choice until the checkbox is explicitly edited.
  Scripted exports must pass `vertex_controls=True` to include the masks.

### ADM Skeleton & Animation panel

The N-panel *ADM › ADM Skeleton & Animation* is shown for an active armature. It contains:

- **Profile:** choose the skeleton profile.
  - `humanoid.vrm1`: VRM 1.0 roles.
  - `generic.v1`: exact rig binding only.
  - `animal.generic_quadruped.v1`, `animal.canine.v1`, `animal.feline.v1`, `animal.equine.v1`: **PROVISIONAL authoring proposals outside ADM 1.0**, not certifiable.
  - custom.
- **Detection:** *Detect Skeleton* auto-maps bones to roles (Mixamo, VRM, Unreal, Blender naming).
  Mixamo names support both `mixamorig:` and numbered namespaces such as `mixamorig1:`.
  After importing a rig, run role mapping before validation; you don't need to rename its bones.
- **Role editor:** fix mappings by hand, one bone per role. Duplicates are rejected.
- **Missing required roles:** listed per role.
- **Validate ADM Rig:** each issue shows the code, role, bone and reason. Safe fixes are offered only when the result is unambiguous:
  - auto-map missing roles;
  - rotate a +Z-facing (VRM/glTF) rig by 180°;
  - normalize `referenceCorrection` (ADM-REF-NORM);
  - clear unknown roles;
  - normalize IK poles;
  - limit and normalize skin weights.
  Rig validation does not replace **Validate Model**, which also checks the serialized IK,
  socket frames, materials, and other model data. The wizard's final step includes
  **Validate Complete Model** for this full export check without writing a file.
- **Reference corrections:** if animation compatibility reports `REFERENCE_CORRECTION`, select the
  target armature and click **Normalize Corrections** in this panel, then retry the test or import.
  The diagnostic includes these steps. Disabling **Strict** bypasses validation; it doesn't repair the rig.
- **IK chains (ADM-IK-1, two-bone):**
  - create chains from profile templates and edit them;
  - preview the pose with Blender IK constraints, then remove the preview;
  - validate pole, length and bone-hierarchy rules.

  Blender IK limits, stretch, rotation targets and other constraints are reported as unsupported and are not exported.
- **Sockets:** create attachment placeholders from the humanoid profile. `ADM-HUMANOID-SOCKETS-1`
  includes right-hand grip and left support-hand grip, back/sling/holster/knife points, helmet/NVG/
  face/ear mounts, plate carrier, chest rig, backpack and belt. Markers start at role joint origins:
  move them to the actual mount points before export. The standard frame is +X right, +Y up, -Z
  forward; export/import preserves the authored transform. Older generic anchors (`hand.left`,
  `hand.right`, `head`, `spine.back`) remain supported but do not claim the capability.
  Socket creation uses the rest pose even while you preview animation. If export reports
  `HUMANOID_SOCKET_FRAME`, select the armature in Object Mode and click **Align Socket Frames**
  in **Sockets**, then export again. This resets standard socket rotation and scale in model space
  without moving their rest-pose mount positions or changing custom/legacy sockets.
- **Skinning check:** unweighted vertices, weights that don't sum to 1, and non-skin bone groups.
- **Animation libraries:**
  - import a library and run a compatibility test against the rig (`EXACT`, `SEMANTIC`, `PROVISIONAL_SEMANTIC`, `INCOMPATIBLE`);
  - no automatic retarget between different profiles (e.g. canine→equine).

Export writes `skeletonProfiles` with roles, `referencePose`, `targetHeight`, `referenceCorrection` and `rigId`. It is blocked only by structural errors (missing or duplicate roles, wrong hierarchy). Pose deviations only warn. Conformance limitations and excluded proposals are listed in [SPEC_GAPS.md](../adm-standard/SPEC_GAPS.md).

The Model Root panel preserves `modelProfiles` as strict JSON, and node properties assign
`componentRoles`. The core validator checks the registered vehicle and firearm profile metadata and
their role-frame constraints. Blender can author, export and import `target.kind=component` tracks
using rest-relative translation and rotation deltas, with profile-axis and limit checks. Independent
engine evaluation and interoperability remain unverified.

The `ADM_humanoid_sockets_v1` extension declares standardized humanoid attachment names and their
role ancestry; it does not add bones or affect existing animation libraries. A gear/weapon asset can
provide an ordinary `mount.root` attachment for frame composition. Slot compatibility, inventory,
weapon animation and equipment fit remain engine responsibilities. See the
[socket contract](../adm-standard/extensions/ADM_humanoid_sockets_v1.md).

### Material textures (Sollumz-style)

The machine-readable registry contains the original Core 20 profiles, the interactive surface and
two-layer surface profiles, each with a typed parameter schema.
Blender preserves their IDs, parameter values and portable PBR fallback through import/export.
Cutout, emissive and decal have profile-specific validation; glass, water and foliage also enforce
their alpha/two-sided requirements. Interactive surfaces show the authored PBR fallback, not a live
runtime image. Specialist rendering is not claimed as certified.

The material panel (Properties › Material › ADM, and the sidebar Shaders tab) has a **Texture Parameters**
box with one slot per PBR texture: Base Color, Metallic-Roughness, Normal, Occlusion and Emissive.

- Empty slot: pick an existing image, create a **New** one or **Open** a file. The colour space is set
  automatically (sRGB for colour, Non-Color for data maps).
- Filled slot: the current image is shown above the picker. Pick a replacement, choose
  **UV0/UV1**, interpolation and extension, and edit
  slot extras (Alpha From Texture, normal Scale, occlusion strength, emission strength).
  **X** removes the texture and keeps the factor values. Texture and UV changes through ADM
  refresh an existing preview automatically; after manually changing nodes or sampler settings,
  use **Refresh Shader Preview**.
- The slots edit the same node chain the exporter traces, so nothing new is stored in the file.
  Imported or hand-built node setups are shown as *custom node setup*. The slot lists the best
  textures found in that setup (**Use Albedo: …**, ranked by node label/image name and colour space;
  palettes are skipped) and a picker. Either one replaces the setup with the simple exportable chain;
  the original nodes are only disconnected, never deleted.
- The shared PBR Metallic-Roughness slot supports selecting R/G/B/A and inversion independently
  for roughness and metallic on traceable image chains. Export repacks the results into the ADM PBR
  G/B channels; reimport preserves the appearance, not the original channel choices. Profile-specific
  shader operations may override those PBR inputs. The controls are disabled for unsupported node
  chains; use the existing texture picker to replace such a chain.
- Switching **Shader** updates the viewport like Sollumz: *PBR Metallic-Roughness* shows the
  material's own Principled BSDF chain (created if missing), *PBR Layered* builds an `ADM Preview`
  node group (base/overlay mix driven by `layer_factor` and the mask's red channel) as the active
  output, and *Custom Shader* shows the portable PBR fallback. Preview nodes are never exported.
- For custom shaders, the box is the portable PBR fallback. Shader parameters of type `TEXTURE` are
  listed separately under **Shader Texture Parameters**. Picking a custom shader syncs its parameters
  automatically; **Sync Parameters** is highlighted when they are out of date.
- Two-layer, terrain and PBR Layered 2.0 shader parameters are grouped into collapsible sections by
  layer, with albedo, normal, metallic and roughness maps beside their corresponding factors.
  Version 2.0 profiles also group their effects by **COLOR_1** channel and effect name. Expand a
  section to edit it; other profile parameters remain in the texture and value sections below.
  Each checkbox still controls its individual override, and metallic/roughness channel and inversion
  controls belong to the texture directly above them.
- Terrain Four Layer and PBR Two Layer put their blend mask, its UV set and per-layer tiling above
  the layers in **Blend & Tiling**. Terrain uses R/G/B/A for layers 0/1/2/3; Two Layer uses red
  (black = layer 0, white = layer 1). Without a mask, layer 0 is selected except in Terrain 2.0,
  which uses the `COLOR_1` weights; a mask multiplies those weights and a zero total selects layer 0.
  Assigning a terrain mask
  sets its image datablock to **Non-Color** and **Channel Packed**; this affects all uses of that image.
  An enabled metallic or roughness map with a zero effective factor displays a warning and
  **Set Factor to 1**. The button changes the factor only when clicked.

### Terrain from a heightmap

1. Load a heightmap in Blender's Image Editor and set its color space to **Non-Color**. The operator
   samples the red channel as linear values from 0 to 1; 16-bit grayscale images are supported.
2. In Object Mode choose **ADM Tools › Create › Create Terrain from Heightmap**. Select the loaded
   image, enter its real-world width and depth in metres, and set the minimum and maximum elevations
   in metres. The source image does not supply these dimensions.
3. Leave **Samples X/Y at 0 (Source)** to preserve the original sampling density: a 1009 x 1009
   heightmap creates a 1009 x 1009 grid, without downsampling. Enter at least 2 on either axis to
   resample it manually. For loaded images, the dialog shows the resolved grid and triangle count.
   The mesh is an editable grid with UVs and a Terrain Four Layer material; heights are baked into
   its vertices. Large grids take more memory and time.
4. Assign the four layer textures and a painted or generated RGBA weight mask under **Blend & Tiling**.
   The operator does not infer a blend mask from height or slope. For an existing mesh, create a grid
   and UV map, apply a height displacement to its geometry, then assign the same shader and mask.

The heightmap dialog can also load a file directly, interpret the red channel as absolute metres,
flip either axis, apply a height scale and offset, and place the center or lower-left corner at the
3D cursor. Alternatively, enter metres per source pixel: the physical dimensions use the number of
intervals (`samples - 1`), not the number of samples. Non-finite pixels and a configured NoData
value are rejected. The generated object stores its source image name and settings as custom
properties. Source images are limited to 8193 x 8193 pixels (67,125,249) and generated grids to
4,194,304 vertices (native 2017 x 2017 maps fit). With both Samples at 0, a denser source is reduced
automatically to the largest grid within that limit, keeping the aspect ratio (8192 x 8192 becomes
2048 x 2048); neighbouring source pixels are box-averaged so detail does not alias. The dialog and
the completion message show the resulting vertex spacing in metres. Explicit Samples that exceed
the limit are rejected. Manual Samples inputs allow up to 4096 per axis within that total.
Direct file loading uses Blender's image decoder; a format Blender cannot decode is reported as an
error. The importer does not read GeoTIFF georeferencing or infer NoData metadata: enter dimensions
and any NoData value explicitly. It creates a working mesh only; use the separate terrain-tiling
workflow below to preview and apply tile boundaries.

### Terrain tiling and tile export

Select the generated working terrain and open **N-panel › ADM › Terrain Tools**. **Preview Tiling**
offers three modes. Each displays proposed boundaries as a non-destructive curve following the
working mesh; **Regenerate Preview** replaces the preview and **Cancel** removes it.

- **Fixed Grid** uses the requested tile width and length in metres. Boundaries snap to the nearest
  source-grid interval, so no triangle is split and the terrain dimensions are not stretched.
- **Adaptive** grows connected, irregular regions across the grid. Target, minimum and maximum tile
  areas are in square metres; terrain sensitivity and natural-boundary preference bias the growth
  toward slope and elevation changes. The maximum cell count also bounds each tile's complexity.
- **Hybrid** first divides the grid into regular sectors, then applies the same connected adaptive
  partitioning inside each sector. Sector width and length are in metres.

Adaptive and Hybrid tiling only decide where tile borders run over existing grid cells; geometry
density is controlled separately by **Tile Geometry** below. Slope and elevation are averaged over
roughly one eighth of the target tile width, so sensor noise on dense heightmaps does not strand
single cells as separate tiles.
Their area limits are quantized to the working grid. The preview dialog shows the grid size, cell
spacing, the tile area allowed by **Maximum Cells per Tile** and the expected tile count while you
edit; settings that cannot work (for example a Minimum Area needing more cells than a tile may hold,
or more than 4,096 tiles) mark the offending field red with a suggested fix and are refused before
any partitioning runs. On dense grids raise **Maximum Cells per Tile**: at 0.71 m spacing a cell is
about 0.5 m2, so the default 4,096 cells caps tiles at about 2,065 m2. Preview and Apply show progress;
Apply reuses the partition computed by Preview. A preview
stores the source geometry signature and parameters; applying after editing the working mesh is
rejected until the preview is regenerated. One apply operation is limited to 4,096 tiles to prevent
accidental creation of an unresponsive Blender scene.

**Tile Geometry** selects how each tile is simplified after tiling:

- **Adaptive** (default) keeps detail where the terrain needs it. For every tile it searches for the
  lowest Decimate/Collapse ratio whose vertical deviation from every source sample of that tile stays
  within **Max Height Error** (default 0.1 m). Flat tiles therefore drop to very few triangles while
  rough tiles keep more. The completion message reports the largest measured error; each tile stores
  it as `adm_terrain_measured_error_m`. The bound is checked at the source samples, not between them.
- **Decimate** keeps a fixed share of triangles: **15% / 30% / 70%** (retained, not removed). This is
  not Un-Subdivide, which uses integer iterations rather than a ratio. Small or narrow tiles can retain
  more than the requested percentage because borders are protected.
- **Full Resolution** keeps all source grid cells.

In both reduced modes boundary vertices and edges are protected and verified unchanged, so
neighbouring tiles still meet exactly. The completion message reports the actual triangle counts.
The reduction is baked into editable output meshes, not left as a modifier, and never modifies the
full-resolution working grid. Adaptive search costs several Collapse passes per tile and is slower
than Decimate on large terrains.

**Apply Tiling** creates a collection of separate ADM Model Roots and uniquely editable mesh
datablocks. Each tile retains source materials, UV maps, `COLOR_0`/`COLOR_1` and supported point
attributes; interior attribute values are interpolated during reduction. The original working mesh
is retained, hidden and excluded from export. The first tile becomes active.
Use Blender's existing **Generate LODs** on a tile to add
an ADM LOD Group, **Sync Terrain Borders** after editing coincident border samples, and **Export Tile**
for an individual model. To export a set, use the standard ADM export dialog's **All Model Roots**
scope.

Border synchronization averages matching XY samples shared by generated tiles; it does not add
vertices, reconcile differently transformed roots or repair mismatched edge topology. Tiling requires
the regular-grid topology of the working mesh; manually changing its topology is unsupported.
Polygon-aware manual split/merge editing, LOD seam stitching/skirts,
synchronization of simplified LOD borders, and export manifests are not implemented.

### World tiles from Apparatus World Tile

Very large heightmaps (up to 16k × 16k) are tiled and textured outside Blender by the
[Apparatus World Tile](../appartus_world_tile/README.md) tool. It exports finished ADM tiles: one
`.adm` per tile with its LODs and `adm.terrain.four_layer@2.0.0` materials whose surfaces are
blended per vertex by `COLOR_1`. Import them with **File → Import → ADM Model** (multi-select
works): each tile lands at its world position with no extra steps. Textures and biomes are edited
in the tool, which re-exports only changed tiles.

### Shader profile previews

- Selecting an official profile (Brick, Concrete, Roof, Bark, Rock, Terrain 4, Glass, Water, Vehicle
  Paint, Skin, Fur, Fabric, Feather, Scales, Foliage…) builds `ADM Preview` nodes. They implement the
  profile contract on top of the material's own PBR chain and are shown on the object in Material
  Preview/Rendered mode. They are never exported.
- A parameter is used only when its **Override** checkbox is enabled; otherwise the contract
  default applies. Editing a value enables Override automatically. Overridden numbers are connected
  through drivers, so they update live. Only parameters marked `animatable` in the shader schema
  support exported shader animation; the panel shows a key button for those parameters.
  **Refresh Preview** rebuilds the nodes.
- Terrain Four Layer uses its own `layer0_texture` through `layer3_texture` parameters, not the
  portable PBR Base Color texture. In version 1.0, layer 0 is visible without a blend mask. Assign `layer0_texture`
  under **Layer 0**, or click **Use PBR Base Color for Layer 0** to copy the
  existing PBR image and UV set. This changes layer 0 only and preserves the PBR fallback. When a
  material is shared, use the same second UV map name on its meshes for a consistent preview.
- Each terrain layer also has `layer{i}_metallic_texture` and `layer{i}_roughness_texture` slots.
  Choose R, G, B or A and optional inversion separately for each map; defaults are R without
  inversion. The selected Non-Color channel multiplies its factor and uses the map's own UV
  selection and the layer's `uv_scale`. Set the metallic factor to 1 to use the full map (default 0).
  Existing terrain materials may need **Sync Parameters (out of date)** to expose the new slots.
- PBR Layered 2.0 has the same maps and channel/inversion controls for each layer. The surface
  overlays of all 2.0 profiles also provide independent metallic and roughness maps for each
  `COLOR_1` surface channel. Maps multiply the corresponding factors; set a factor to 1 to use its
  full range. Non-surface mask effects keep their original scalar, color or normal-only behavior.
  Existing materials may need **Sync Parameters (out of date)** to show the added slots.
- **PBR Two Layer** blends two independent textured PBR layers using the red channel of a Non-Color
  `blend_mask`: black selects layer 0 and white selects layer 1. Without a mask it shows layer 0.
  Each layer provides albedo, normal, metallic and roughness textures, plus independent channel and
  inversion controls for metallic and roughness. The profile uses a portable PBR fallback in readers
  that do not support it; it does not require vertex colors.
- Profile-specific grayscale masks use Non-Color images and read the red channel. Example for Brick: in `mortar_mask`,
  white = mortar joint and black = brick face. It is sampled at UV × `uv_scale`, like the base texture.
  `dirt_mask` darkens the color to 35 % where it is white. **Generate Mortar Mask** creates a packed
  running-bond mask (rows, columns, joint width, offset).
- Skin, Fur and Fabric are Principled BSDF approximations (subsurface, anisotropy), and the panel says so.
- **ADM Vertex Control** can be enabled per material. It interprets `COLOR_0`, samples the optional
  top row of the 1–5 px high tint palette, and previews tint/normal/wetness. Dielectric and metallic F0 are represented
  by separate Principled lobes mixed at the material metallic factor; the effective dielectric F0 is
  encoded as IOR and metallic F0 as the lobe base color. Cycles tests bake both node outputs.
  Core 20 `1.0.0` profiles preserve but ignore `COLOR_1`; their separately versioned `2.0.0` profiles use the
  registered shader-specific mask effects described above.

### Interactive display surfaces

1. Assign an ADM material with **Shader > Interactive Surface** to the display polygons. A frame or
   other part may keep its own normal material; the same interactive material may be shared by displays.
2. Create and unwrap the required UV maps. UV 0 is the render-active Blender UV map; UV 1 is the next
   exported map. Enable **Second UV Map** during export when a surface uses UV 1.
3. In Edit Mode select the screen faces, return to Object Mode, and open **N-panel > ADM > Object >
   Interactive Surface** (also in Object Properties > ADM). Enter a model-wide **Surface ID** such as
   `main_display`, choose **UV Set**, set an optional width/height **Aspect Ratio** (`0` means
   unspecified), and click **Assign Selected**. Repeat with another ID for another screen.
4. **Read Selected Faces** loads an existing assignment into the controls; **Clear** removes it.
   One ID intentionally shared by several face groups denotes one logical surface. Assignments live
   on mesh faces: linked objects share them. Make the mesh single-user before assigning different IDs
   to linked objects. Import separates shared source meshes when their per-node IDs differ.
5. In Material Properties > ADM, edit the normal PBR fallback and optionally use its Base Color or
   Emissive texture as a static test image. In **Material Preview** the actual object displays this
   fallback. The `brightness`, `emissive_strength`, `enabled`, and `unlit` parameters affect engine
   runtime content, not this static preview; `enabled=false` selects the authored fallback. Brightness
   and emissive strength can be animated using the ordinary material Animation ID workflow.
   Explicit fallback UV maps must be exported, and a shared material must use the same UV set index on
   every mesh. Unsupported transformed texture coordinates are rejected rather than silently changed.
6. Export and re-import `.adm`. The add-on preserves the IDs, UV bindings, ratio, parameters and
   fallback. It rejects missing IDs, unavailable UVs or disabled material export instead of guessing.
   When using ADM vertex controls, enable **ADM Vertex Controls** and **Vertex Colors** during export;
   disabling those options changes or omits control data, and the exporter warns for affected screens.

The extension is `ADM_interactive_surfaces_v1` version `1.0.0`; its runtime capability is
`ADM-INTERACTIVE-SURFACES-1`. The engine supplies any camera, UI, render target and interaction.
Blender's preview is not a camera or live UI implementation. See the
[surface binding contract](../adm-standard/extensions/ADM_interactive_surfaces_v1.md) and
[shader contract](../adm-standard/shaders/adm.surface.interactive.v1.md).

### Material animation

1. In the material panel, set the **Animation ID** (or *Auto*).
2. Run **Link Material To Clip**, which adds a MATERIAL/NODETREE slot to the clip's Action.
3. Key `layer_factor`, PBR values, animatable shader parameters or enabled ADM Vertex Control
   parameters with the key button next to each parameter.

The export writes `pbrParameter` and `shaderParameter` channels:
- PBR channels only when their values change over the clip.
- Shader parameters only when marked `animatable` and keyed. Values are clamped to the parameter's
  min/max. Keyed shader parameters not marked `animatable` are skipped with an export warning.
- ADM Vertex Control targets use the extension's parameter names and the material's exact shader
  identity. The `.adm_anim` file declares `ADM_vertex_control_v1` required.

### `model.any` libraries

These libraries are not bound to a rig. They contain only morph and material channels; bones are not
exported, and `EXTRACT` is forbidden. You can import them without an armature (rig = *None*).

## ADM 1.0 container and fallback

- Both file types use the native **64-byte header**, **80-byte directory entries**, 16-byte alignment,
  per-chunk SHA-256 and chunk-addressed buffer views. Legacy Draft 0.3 containers are rejected.
- Writers generate independent **RAW** chunks for accessor views (`GEOM` / `ANIM`) and images (`IMAG`).
  Chunks exceeding the interoperable 256 MiB cap are rejected, not written as invalid assets.
- The core reader exposes metadata-only bootstrap and on-demand chunk retrieval with dependency closure.
  Manifest size, chunk sizes, nesting, dependencies, references, padding and hashes are checked.
  Blender's full import/validation reads the supported payloads it uses; it is not a streaming viewport.
- **ZSTD is not implemented**: required/requested compressed chunks produce
  `ADM_ERR_UNSUPPORTED_CODEC`. Unused optional chunks need not be decoded.
- Every non-core material exports explicit `baseColorFactor`, `metallicFactor`, `roughnessFactor`,
  `emissiveFactor` and `alphaMode`. Missing fields are rejected as `ADM_ERR_MISSING_PBR_FALLBACK`.
- The viewport shows a **layered preview** for `adm.pbr.layered@1.0.0`, profile previews for the
  original Core 20 set, and the authored **core PBR fallback** for interactive and custom shaders
  (unsupported custom shaders report `SHADER_FALLBACK`).
  Shader/layer definitions and their animation data remain editable and exportable; arbitrary custom
  shader rendering and certified layered rendering are not claimed. PBR tracks animate the fallback
  independently of custom shader parameters.
- Export's **Embed Textures** option is enabled by default. When disabled, external images are written
  under a deterministic relative `textures/` path and validated against the ADM file's directory on
  import.
- `ADM_vertex_control_v1` can serialize `COLOR_0`/`COLOR_1`, palette references and material control
  values. Enable **Enable Vertex Controls** on a material to preview and animate the four universal
  controls. The export option must also enable **Vertex Controls** for the model. Tint, normal strength,
  wetness color, roughness and dielectric/metallic F0 are previewed. Core 20 `1.0.0` profiles keep
  `COLOR_1` reserved; the additive `2.0.0` profiles apply the registered `COLOR_1` masks.
  `adm.pbr.metallic_roughness@2.1.0` derives chipped edge wear from geometry and normal-map
  transitions. `COLOR_1.B` permits wear and `COLOR_1.G` permits dirt; the engine supplies their
  amounts per instance, and those amounts are not stored in ADM.
  To inspect it in Blender, open the 3D View sidebar with `N`, select **ADM**, and click
  **Create Edge Wear Test Scene (2.1.0)** in **ADM Tools**. The add-on creates a separate Cycles scene
  with textured convex geometry, a flat-mask control, a normal-map edge sample, and two dirt
  instances. Select a wear sample and adjust **Engine Wear Preview** in **ADM Tools › Shader Test**.
  For another mesh using the profile, select it and click **Enable Wear Preview** to show the
  control. The slider is per object, simulates the engine, and is not exported. The test uses Cycles
  rendered view for geometric pointiness; the source texture and mesh remain unchanged.
  The F0 preview has Blender bake coverage but no independent renderer interoperability test. See
  `adm-standard/SPEC_GAPS.md`.
- Image export (the **Images** option in File > Export > ADM):
  - **Keep GPU / PNG** (default) preserves compatible, unedited DDS/KTX2 bytes and their mip
    levels, with a portable fallback. Other images are converted to PNG, except PNG sources.
    If you edit an image, export uses the edited pixels instead and reports the conversion.
  - **PNG** writes only PNG. JPEG, DDS, KTX2 and other sources are converted, so any
    engine can read the file. R16 DDS/KTX2 sources loaded through a texture slot and edited
    16-bit PNG sources retain 16-bit samples in PNG export.
  - **Keep GPU / PNG / JPEG** also passes JPEG source bytes through unchanged.
  - **KTX2 + PNG fallback** and **DDS + PNG fallback** write a GPU image (§8.6: RGBA8, BC1, BC3 or R16,
    sRGB for colour and UNORM for data textures, optional mipmaps) together with the mandatory
    same-size PNG `fallbackSource`. *Compression* `AUTO` picks BC1 for opaque and BC3 for
    transparent images. For 16-bit data images, `AUTO` uses R16 when the green and blue channels
    are zero and alpha is one, including an imported R16 PNG fallback. Other 16-bit sources are
    quantized in the GPU image with a warning; the PNG fallback retains 16-bit samples. The
    encoder is built in (NumPy), so no external tools are needed.
- On import, KTX2/DDS primaries resolve to their PNG/JPEG `fallbackSource` (`KTX2_FALLBACK` /
  `DDS_FALLBACK`). BC5 normal maps reconstruct their Z component for core PBR and official shader
  parameters. If an external primary is missing or fails integrity checks, import warns that the
  normal fallback might render incorrectly and the original cannot be preserved.
  Use the folder button on a PBR slot or shader texture parameter to open `.ktx2` and `.dds`
  files through the add-on's loader. Official BC5 normal parameters reconstruct Z;
  custom shader parameters have no declared normal role and retain their raw channels.
  BC7 KTX2 blocks are repackaged as DDS and decoded by
  Blender's DDS reader; this path has been verified on Windows with Blender 5.2.3.

This is ADM 1.0 authoring support, **not full ADM conformance certification**. The numerical
renderer, retargeting, IK and advanced interoperability evidence described in §25 is a separate
conformance activity and is not supplied by the Blender reference tests.

## Interpretations of the draft

The draft leaves some points open. This add-on resolves them as follows:

- **rigId:** a descriptor of `jointOrder` + rest TRS (f32 hex) + raw IBM bytes + `roles → node`, hashed
  with SHA-256 (`core/rigid.py`).
  - When a model is imported, its original rigId and a tolerant rest-pose fingerprint are stored.
  - Until the rest pose changes, `EXACT` libraries made for the source file are accepted. Re-export
    produces a new, correct rigId.
- **Profile extras:** `targetHeight` and `referenceCorrection`.
- **Library extras:** `revision`, `namespace`, `motionScale`, `sourceHeight` and `rootMotionSource`.
- **Positions and timing:** the hips offset is measured in model-root space. Clip duration is f32.
- **materialId:** a channel's `materialId` is the material's `animationId`.

## Tests

```
blender -b --factory-startup --python tests/test_fixtures.py
blender -b --factory-startup --python tests/test_workflow.py
blender -b --factory-startup --python tests/test_lod_generator.py
blender -b --factory-startup --python tests/test_interactive_blender.py
blender -b --factory-startup --python tests/test_skeleton_blender.py
blender -b --factory-startup --python tests/test_material_slots.py
blender -b --factory-startup --python tests/test_texture_formats.py
```

From the workspace root: `python -m unittest adm_blender.tests.test_skeleton_profiles adm_blender.tests.test_container adm_blender.tests.test_draft4 adm_blender.tests.test_gputex` runs without Blender (`test_gputex` needs NumPy).

For optional private FBX, BLEND, ADM, and ADM_ANIM smoke tests, see the
[external asset catalog instructions](tests/EXTERNAL_ASSETS.md).

**Standalone validator (without Blender):** `python -m adm_blender.core.validate file.adm`

## License

[MIT](LICENSE). The specification is separately licensed CC0-1.0 and is not included in the extension ZIP.
