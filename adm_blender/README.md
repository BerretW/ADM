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
- KTX2 primary textures select their mandatory embedded PNG/JPEG `fallbackSource`; the unsupported
  KTX2 payload is not decoded. Re-export embeds the portable image. KTX2 codec certification is pending
  in the specification itself.

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
```

From the workspace root: `python -m unittest discover -s adm_blender\tests -p "test_draft4.py"`
and `python -m unittest discover -s adm_blender\tests -p "test_container.py"` run without Blender.

**Standalone validator (without Blender):** `python -m adm_blender.core.validate file.adm`

## License

[MIT](LICENSE). The specification is separately licensed CC0-1.0 and is not included in the extension ZIP.
