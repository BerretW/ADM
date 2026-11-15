# ADM Tools for Blender (5.2+)

Blender extension for the final ADM 1.0 specification (`adm-standard/ADM-1.0-SPEC.md`).
The workflow and layout follow Sollumz: object types, create/convert tools, a sidebar tab,
validation and import/export. This is a reference implementation; its tests do not constitute
independent ADM conformance certification.

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
  Scripted exports must pass `vertex_controls=True` to include the masks.

### ADM Skeleton & Animation panel

The N-panel *ADM › ADM Skeleton & Animation* is shown for an active armature. It contains:

- **Profile:** choose the skeleton profile.
  - `humanoid.vrm1`: VRM 1.0 roles.
  - `generic.v1`: exact rig binding only.
  - `animal.generic_quadruped.v1`, `animal.canine.v1`, `animal.feline.v1`, `animal.equine.v1`: **PROVISIONAL authoring proposals outside ADM 1.0**, not certifiable.
  - custom.
- **Detection:** *Detect Skeleton* auto-maps bones to roles (Mixamo, VRM, Unreal, Blender naming).
- **Role editor:** fix mappings by hand, one bone per role. Duplicates are rejected.
- **Missing required roles:** listed per role.
- **Validate ADM Rig:** each issue shows the code, role, bone and reason. Safe fixes are offered only when the result is unambiguous:
  - auto-map missing roles;
  - rotate a +Z-facing (VRM/glTF) rig by 180°;
  - normalize `referenceCorrection` (ADM-REF-NORM);
  - clear unknown roles;
  - normalize IK poles;
  - limit and normalize skin weights.
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
- **Skinning check:** unweighted vertices, weights that don't sum to 1, and non-skin bone groups.
- **Animation libraries:**
  - import a library and run a compatibility test against the rig (`EXACT`, `SEMANTIC`, `PROVISIONAL_SEMANTIC`, `INCOMPATIBLE`);
  - no automatic retarget between different profiles (e.g. canine→equine).

Export writes `skeletonProfiles` with roles, `referencePose`, `targetHeight`, `referenceCorrection` and `rigId`. It is blocked only by structural errors (missing or duplicate roles, wrong hierarchy). Pose deviations only warn. Conformance limitations and excluded proposals are listed in [SPEC_GAPS.md](../adm-standard/SPEC_GAPS.md).

The Model Root panel preserves `modelProfiles` as strict JSON, and node properties assign
`componentRoles`. The core validator checks the registered vehicle and firearm profile metadata and
their role-frame constraints. The Blender animation authoring/import workflow does not yet author or
evaluate `target.kind=component` tracks; use a compatible external tool/runtime for those tracks.

The `ADM_humanoid_sockets_v1` extension declares standardized humanoid attachment names and their
role ancestry; it does not add bones or affect existing animation libraries. A gear/weapon asset can
provide an ordinary `mount.root` attachment for frame composition. Slot compatibility, inventory,
weapon animation and equipment fit remain engine responsibilities. See the
[socket contract](../adm-standard/extensions/ADM_humanoid_sockets_v1.md).

### Material textures (Sollumz-style)

The machine-readable registry contains the original Core 20 profiles plus the interactive surface
profile, each with a typed parameter schema.
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
- Switching **Shader** updates the viewport like Sollumz: *PBR Metallic-Roughness* shows the
  material's own Principled BSDF chain (created if missing), *PBR Layered* builds an `ADM Preview`
  node group (base/overlay mix driven by `layer_factor` and the mask's red channel) as the active
  output, and *Custom Shader* shows the portable PBR fallback. Preview nodes are never exported.
- For custom shaders, the box is the portable PBR fallback. Shader parameters of type `TEXTURE` are
  listed separately under **Shader Texture Parameters**. Picking a custom shader syncs its parameters
  automatically; **Sync Parameters** is highlighted when they are out of date.

### Shader profile previews

- Selecting an official profile (Brick, Concrete, Roof, Bark, Rock, Terrain 4, Glass, Water, Vehicle
  Paint, Skin, Fur, Fabric, Feather, Scales, Foliage…) builds `ADM Preview` nodes. They implement the
  profile contract on top of the material's own PBR chain and are shown on the object in Material
  Preview/Rendered mode. They are never exported.
- A parameter is used only when its **Override** checkbox is enabled; otherwise the contract
  default applies. Editing a value enables Override automatically. Overridden numbers are connected
  through drivers, so they update live and can be keyframed. **Refresh Preview** rebuilds the nodes.
- Terrain Four Layer uses its own `layer0_texture` through `layer3_texture` parameters, not the
  portable PBR Base Color texture. Without a blend mask, layer 0 is visible. Assign `layer0_texture`
  under **Shader Texture Parameters**, or click **Use PBR Base Color for Layer 0** to copy the
  existing PBR image and UV set. This changes layer 0 only and preserves the PBR fallback. When a
  material is shared, use the same second UV map name on its meshes for a consistent preview.
- Each terrain layer also has `layer{i}_metallic_texture` and `layer{i}_roughness_texture` slots.
  Their Non-Color red channels multiply the corresponding factors and use their own UV selection
  and the layer's `uv_scale`. Set the metallic factor to 1 to use the full map (its default is 0).
  Existing terrain materials may need **Sync Parameters (out of date)** to expose the new slots.
- Masks are grayscale Non-Color images; the red channel is read. Example for Brick: in `mortar_mask`,
  white = mortar joint and black = brick face. It is sampled at UV × `uv_scale`, like the base texture.
  `dirt_mask` darkens the color to 35 % where it is white. **Generate Mortar Mask** creates a packed
  running-bond mask (rows, columns, joint width, offset).
- Skin, Fur and Fabric are Principled BSDF approximations (subsurface, anisotropy), and the panel says so.
- **ADM Vertex Control** can be enabled per material. It interprets `COLOR_0`, samples the optional
  top row of the 1–5 px high tint palette, and previews tint/normal/wetness. Dielectric and metallic F0 are represented
  by separate Principled lobes mixed at the material metallic factor; the effective dielectric F0 is
  encoded as IOR and metallic F0 as the lobe base color. Cycles tests bake both node outputs.
  Core 20 `1.0.0` profiles preserve but ignore `COLOR_1`; their compatible `2.0.0` versions use the
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
3. Key `layer_factor`, PBR values, shader parameters or enabled ADM Vertex Control parameters with
   the key button next to each parameter.

The export writes `pbrParameter` and `shaderParameter` channels:
- PBR channels only when their values change over the clip.
- Shader parameters only when they have keyframes. Values are clamped to the parameter's min/max.
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
  The F0 preview has Blender bake coverage but no independent renderer interoperability test. See
  `adm-standard/SPEC_GAPS.md`.
- Image export (the **Images** option in File > Export > ADM):
  - **PNG** (default) writes only PNG. JPEG, DDS, KTX2 and other sources are converted, so any
    engine can read the file.
  - **Keep PNG/JPEG** passes PNG and JPEG source bytes through unchanged and converts the rest to PNG.
  - **KTX2 + PNG fallback** and **DDS + PNG fallback** write a GPU image (§8.6: RGBA8, BC1 or BC3,
    sRGB for colour and UNORM for data textures, optional mipmaps) together with the mandatory
    same-size PNG `fallbackSource`. *Compression* `AUTO` picks BC1 for opaque and BC3 for
    transparent images. The encoder is built in (NumPy), so no external tools are needed.
- On import, KTX2/DDS primaries resolve to their PNG/JPEG `fallbackSource` (`KTX2_FALLBACK` /
  `DDS_FALLBACK`). *Open Image* on a texture slot also accepts `.ktx2` and `.dds` files; the add-on
  decodes them itself when Blender cannot.

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

**Standalone validator (without Blender):** `python -m adm_blender.core.validate file.adm`

## License

[MIT](LICENSE). The specification is separately licensed CC0-1.0 and is not included in the extension ZIP.
