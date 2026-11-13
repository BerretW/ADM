# ADM Tools for Blender (5.2+)

Blender extension for the ADM 1.0 format (spec: `adm-standard/ADM-1.0-SPEC.md`, Draft 0.4).
The workflow and layout follow Sollumz: object types, create/convert tools, a sidebar tab,
validation and import/export.

## Installation

- **Simplest:** zip the `adm_blender` folder (e.g. right-click › *Send to › Compressed folder*) and install
  the zip via *Edit › Preferences › Get Extensions › ⌄ › Install from Disk…*. You can also drag the zip into Blender.
- **Alternative:** `blender --command extension build --source-dir adm_blender` builds a smaller package
  without `tests/` and `__pycache__`.
- The sidebar tab name is set in the extension preferences (default `ADM`).

## Workflow

1. **Tools tab (N-panel › ADM)**: create a Model Root, Scene, LOD, Collider or Attachment, or convert
   the selection to an ADM type. This is the Sollumz-style "Create / Convert" approach.
2. **Object**: set the ADM type of the active object, plus its LOD, collider and attachment properties.
3. **Skeleton**: pick the profile (`humanoid.vrm1`, `generic.v1` or custom) and run *Auto Map Roles*. This
   recognises Mixamo, VRM, Unreal and Blender naming. It also covers *Compute rigId* and IK chains.
4. **Face & Expressions**: facial bindings to shape keys and expressions.
5. **Shaders**: shader definitions (`shaderDefinitions`) with parameters, and custom-shader assignment.
6. **Animation**: clip libraries (Actions → clips). You can choose:
   - the binding: `SEMANTIC` (by role) or `EXACT` (one rig, `rigId`);
   - the target: armature or `model.any`.
7. **Validation**: container and model/animation schema validation, with a report.

On the **Model Root**, the Object panel also edits **Physical Materials**, **Model Components** and
**Hitboxes**. Components reference an object or armature bone and an optional attachment socket.
Hitboxes reference an exported collider and an optional collider node/ancestor; physical material IDs
are assigned on colliders. These are asset descriptors, not physics simulation or damage behavior.
Vehicle and firearm profiles remain provisional, not certified built-ins.

**Import and export:** use *File › Import/Export › ADM Model (.adm)* and *ADM Animation Library*.
Drag & drop of `.adm` files also works.

### ADM Skeleton & Animation panel

The N-panel *ADM › ADM Skeleton & Animation* is shown for an active armature. It contains:

- **Profile:** choose the skeleton profile.
  - `humanoid.vrm1`: VRM 1.0 roles.
  - `generic.v1`: exact rig binding only.
  - `animal.generic_quadruped.v1`, `animal.canine.v1`, `animal.feline.v1`, `animal.equine.v1`: **PROVISIONAL**, not certifiable.
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
- **Sockets:** create attachment sockets from profile templates (hands, head, back…).
- **Skinning check:** unweighted vertices, weights that don't sum to 1, and non-skin bone groups.
- **Animation libraries:**
  - import a library and run a compatibility test against the rig (`EXACT`, `SEMANTIC`, `PROVISIONAL_SEMANTIC`, `INCOMPATIBLE`);
  - no automatic retarget between different profiles (e.g. canine→equine).

Export writes `skeletonProfiles` with roles, `referencePose`, `targetHeight`, `referenceCorrection` and `rigId`. It is blocked only by structural errors (missing or duplicate roles, wrong hierarchy). Pose deviations only warn. Open spec questions are listed in [SPEC_GAPS.md](../adm-standard/SPEC_GAPS.md).

### Material textures (Sollumz-style)

The material panel (Properties › Material › ADM, and the sidebar Shaders tab) has a **Texture Parameters**
box with one slot per PBR texture: Base Color, Metallic-Roughness, Normal, Occlusion and Emissive.

- Empty slot: pick an existing image, create a **New** one or **Open** a file. The colour space is set
  automatically (sRGB for colour, Non-Color for data maps).
- Filled slot: swap or reload the image, choose **UV0/UV1**, interpolation and extension, and edit
  slot extras (Alpha From Texture, normal Scale, occlusion strength, emission strength).
  **X** removes the texture and keeps the factor values.
- The slots edit the same node chain the exporter traces, so nothing new is stored in the file.
  Hand-built node setups are shown as *custom node setup* and are never overwritten.
- For custom shaders, the box is the portable PBR fallback. Shader parameters of type `TEXTURE` are
  listed separately under **Shader Texture Parameters**. Picking a custom shader syncs its parameters
  automatically; **Sync Parameters** is highlighted when they are out of date.

### Material animation

1. In the material panel, set the **Animation ID** (or *Auto*).
2. Run **Link Material To Clip**, which adds a MATERIAL/NODETREE slot to the clip's Action.
3. Key `layer_factor`, PBR values or shader parameters with the key button next to each parameter.

The export writes `pbrParameter` and `shaderParameter` channels:
- PBR channels only when their values change over the clip.
- Shader parameters only when they have keyframes. Values are clamped to the parameter's min/max.

### `model.any` libraries

These libraries are not bound to a rig. They contain only morph and material channels; bones are not
exported, and `EXTRACT` is forbidden. You can import them without an armature (rig = *None*).

## Draft 0.4 container and fallback

- Both file types use the native **64-byte header**, **80-byte directory entries**, 16-byte alignment,
  per-chunk SHA-256 and chunk-addressed buffer views. Draft 0.3 containers are rejected.
- Writers generate independent **RAW** chunks for accessor views (`GEOM` / `ANIM`) and images (`IMAG`).
  Chunks exceeding the interoperable 256 MiB cap are rejected, not written as invalid assets.
- The core reader exposes metadata-only bootstrap and on-demand chunk retrieval with dependency closure.
  Manifest size, chunk sizes, nesting, dependencies, references, padding and hashes are checked.
  Blender's full import/validation reads the supported payloads it uses; it is not a streaming viewport.
- **ZSTD is not implemented**: required/requested compressed chunks produce
  `ADM_ERR_UNSUPPORTED_CODEC`. Unused optional chunks need not be decoded.
- Every non-core material exports explicit `baseColorFactor`, `metallicFactor`, `roughnessFactor`,
  `emissiveFactor` and `alphaMode`. Missing fields are rejected as `ADM_ERR_MISSING_PBR_FALLBACK`.
- The viewport uses **core PBR fallback** for non-core shaders and reports `SHADER_FALLBACK`.
  Shader/layer definitions and their animation data remain editable and exportable; arbitrary custom
  shader rendering and certified layered rendering are not claimed. PBR tracks animate the fallback
  independently of custom shader parameters.
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

This is Draft 0.4 authoring support, **not full ADM conformance certification**. The draft's numerical
renderer, retargeting, IK and advanced interoperability acceptance corpus is not yet complete.

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
blender -b --factory-startup --python tests/test_skeleton_blender.py
blender -b --factory-startup --python tests/test_material_slots.py
blender -b --factory-startup --python tests/test_texture_formats.py
```

From the workspace root: `python -m unittest adm_blender.tests.test_skeleton_profiles adm_blender.tests.test_container adm_blender.tests.test_draft4 adm_blender.tests.test_gputex` runs without Blender (`test_gputex` needs NumPy).

**Standalone validator (without Blender):** `python -m adm_blender.core.validate file.adm`

## License

[MIT](LICENSE). The specification is separately licensed CC0-1.0 and is not included in the extension ZIP.
