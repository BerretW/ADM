# Changelog

## Unreleased

### Changed

- Upgraded `ADM_animation_timing_v1` to schema `1.1.0` with per-clip frame rates. The prior
  `1.0.0` timing payload is no longer accepted; history remains in Git and older development
  animation files are not automatically migrated.
- Marked ADM 1.0 as **Development / Experimental**: normative requirements remain exact for the
  current revision, but incompatible changes are allowed before a separate stable-release decision.
- Replaced the shader-definition freeze check with registry integrity checks and CI comparison
  against the base revision. Changed shader identities and contract references now require a
  `shaders/revisions.json` record linked to this changelog.
- Removed the unused top-level shader-registry version; exact shader contract versions remain on
  each `(shader.id, shader.version)` identity.
- Clarified the independent roles of the ADM edition, binary file-format, extension, shader-contract
  and Blender add-on versions.

### Added

- Added opt-in `ADM-TEX-KTX2-2` and `ADM-TEX-DDS-2` format contracts for R8, R16, BC4, BC5, and
  BC7 while retaining the original version 1 capability meanings and portable fallback rules.
- Added renderer-independent layer AO, effective-height, height-blend, and tangent-space
  parallax reference math helpers with focused numerical tests.
- Specified `ADM_material_height_v1` for material-space height and parallax data and added
  validator checks for its version, texture reference, UV set, ranges, and POM settings.
- Added four versioned layered-material profiles with per-layer AO, height-based blending,
  parallax/POM bounds, texture-role validation, explicit PBR fallback, and generated capability
  metadata.
- World Tile exports the selected `@2.1.0` profile and its AO, height, emission, blend, and
  parallax data. Its export diagnostics describe the limitations of portable PBR fallbacks.
- Added typed enum shader parameters for closed, case-sensitive mode selections.
- Added a machine-readable reference-test catalog that records existing fixture evidence and
  explicitly lists missing fixtures and expectations for all eight test categories.
- Added deterministic procedural Rock, Cobblestone, Sand, Dirt, and Grass material references,
  a Blender advanced layered-material scene generator, and a loadable Advanced World Tile project.
- Added an implementation support matrix that separates real consumer support from
  metadata preservation and portable PBR fallback behavior.
- Added explanatory rejection diagnostics for unsupported container versions and layouts.

## ADM 1.0 optional animation-timing extension — 2026-11-18

- Added the normative `ADM_animation_timing_v1@1.0.0` contract for source frame rates and exact
  per-clip frame ranges while keeping core sample times and durations in seconds.
- Blender animation imports can match the source frame rate to preserve the original frame range;
  the scene-rate change is reported and can be disabled explicitly.

## ADM 1.0 optional joint-display extension — 2026-11-17

- Added the normative `ADM_joint_display_v1@1.0.0` contract for exact display frames, bone heads,
  tails and roll without changing core node, skinning or animation semantics.
- Blender exports declare the extension required and provide data for every exported bone node;
  importers reject missing data instead of estimating bone geometry.

## ADM 1.0 shader registry republication — 2026-11-15

- Reissued the current 42 shader definitions and their referenced contracts as the authoritative
  baseline, retaining their current IDs and versions. This explicitly supersedes earlier development
  definitions, including the 20 changed identities recorded below; compatibility with those
  definitions is not supported. The ADM container version is unchanged.
- Froze the reissued entries and contract text in `shaders/freeze-2026-11-15.json`. CI checks the
  baseline separately from the generated registry and rejects changes to published identities.
- Released Blender Tools 1.18.9 with the republication notice; shader behavior is unchanged.

## Documentation audit — 2026-11-15

- Documented that 20 published shader identities acquired metallic/roughness texture parameters
  or channel/inversion controls without a version change after the 1.0 publication. The later
  republication above resolves the versioning decision, without supporting the earlier schemas.
- Documented the current Blender terrain workflow, animatable-parameter export restriction and
  the manual terrain regression test's absence from CI.

## ADM 1.0 — Final specification publication — 2026-11-14

- Froze the ADM 1.0 normative text and established a versioned conformance/certification process
  separate from specification publication. This does not claim independent implementation
  certification or external standards-body ratification.
- Kept the ADM 1.0 wire format and finalized semantics unchanged from the last working revision.
  Legacy ADM, ADS and `.ads_anim` formats remain incompatible.
- Excluded all `animal.*.v1` quadruped profiles from ADM 1.0. Their proposals and machine-readable
  data are retained under `proposals/`; they are not in the normative skeleton registry and cannot
  be used for ADM 1.0 semantic binding.
- Froze `profiles/skeleton-profiles.json` at registry version 1.0.0 with `humanoid.vrm1` and
  `generic.v1`.
- Recorded independent conformance testing, numerical corpus completion and certification as
  separate outstanding implementation activities in `SPEC_GAPS.md`.

## Blender Tools 1.18.0 — `COLOR_1` v2 — 2026-11-14

- Added 20 additive `@2.0.0` mask-enabled shader profiles while preserving every `@1.0.0` profile
  and the interactive surface contract.
- Finalized the normative `COLOR_1` operations and profile channel maps, with independent golden
  vectors and valid/semantic-invalid fixtures.
- Added Blender mask authoring/preview, version-aware round trips, and export protection against
  silently dropping or reinterpreting authored v2 masks.
- Added verified Blender download mirrors to CI and fixed export of `COLOR_1` when vertex controls
  are disabled.
- Local Python and Blender reference-implementation test evidence is recorded above; remote CI and
  independent renderer certification remain outstanding.

## Blender Tools 1.15.0 — 2026-11-14

- Publishes the frozen ADM 1.0 skeleton registry separately from non-normative animal profile
  proposals. The add-on may still author those profiles as explicitly provisional data.
- Aligns the extension version and exported asset generator marker with the final specification.

## Draft 0.4 revision P14 — humanoid equipment sockets

- Added the normative `ADM_humanoid_sockets_v1@1.0.0` extension and `ADM-HUMANOID-SOCKETS-1`
  capability with 20 named weapon and gear mount points on `humanoid.vrm1`; retained the four earlier
  generic anchors for compatibility.
- Defined role ancestry, model-space mount-frame axes, authored per-model socket positions and
  accessory `mount.root` composition. The capability does not add bones or change animation
  compatibility, and does not define inventory or gameplay behavior.
- Updated the skeleton-profile registry to `0.4-P14`.

## Blender Tools 1.14.0 — 2026-11-14

- Blender creates editable socket placeholders from the profile template and preserves names and
  transforms through ADM export/import. The validator rejects undeclared, incompatible-version,
  mis-parented or misoriented standardized sockets.

## Blender Tools 1.13.0 — 2026-11-14

- Added **Generate LODs**: Decimate (Collapse) LOD1…LODn of the active mesh into an ADM LOD group,
  default four levels (100/50/25/10 % triangles at 0/15/40/100 m). Interactive screen faces are kept
  intact and stay bound to the same `surfaceId` on every level. Shape keys are transferred to near
  levels (default up to LOD2) through attribute-interpolated deltas and dropped on far levels.
  Regeneration replaces only generated levels. No ADM schema, shader or capability version changes.

## Blender Tools 1.12.0 / `ADM_vertex_control_v1` 1.1.0 — 2026-11-14

- Tint palettes may be 1–5 texels high. Only the first (top) row is the palette; other rows are
  ignored and never sampled. Taller palettes are rejected (`VERTEX_CONTROL_PALETTE_SIZE`).
- Every valid 1.0.0 asset keeps its exact meaning. A 1.0.0 reader rejects palettes taller than one row.
- Blender swatches, preview sampling, export and the validator follow the new rule.
- Added the **This Material Faces** vertex-color scope: Reset, Apply Channels and Apply Palette to R
  write every face of the active material, independent of the face selection.

## Blender Tools 1.11.0 — 2026-11-14

- Added `COLOR_0`/`COLOR_1` initialization, selected-face/channel editing and neutral-default reset.
- Enabling vertex controls or converting materials to ADM initializes control layers of the active
  or selected objects and of ADM model meshes using the material; meshes outside an ADM Model Root
  and unrelated color layers are never changed automatically.
- Added one-row tint-palette swatches with offset-aware R-only palette selection.
- Vertex-control import/export materializes omitted optional channel defaults and preserves authored
  values and palettes. No ADM schema, shader version or capability version changes.

## Draft 0.4 — 2026-11-13

**Breaking (no backward compatibility promised):**
- Replaced the previous 32-byte header + monolithic BIN with a native 64-byte header, an 80-byte-per-entry chunk directory, individually addressable/verified chunks and a metadata-only bootstrap.
- All model and animation `bufferViews` now address a `chunkId` and uncompressed byte range.
- RAW chunks required; ZSTD optional codec profile. SHA-256 per chunk; offset checks; bounded chunk sizes; dependency DAG; optional stream priority metadata.
- PNG and JPEG remain mandatory; KTX2 permitted only with portable PNG/JPEG image fallback (exact KTX2 profile still pending).
- Explicit portable PBR fields required on all non-core shaders; portable numeric PBR animation survives shader fallback.
- Added optional semantic records for components, physical materials, and hitboxes; reserved vehicle/weapon role profiles clearly labeled provisional.
- Added container-negative fixtures, split-stream example and standard-library validator tests.

**Retained from Draft 0.3:**
- `.adm_anim` animation library catalogs with mandatory clip descriptions.
- Humanoid semantic roles / retargeting concept, two-bone IK, root motion metadata, layers, ARKit52 and morph target rules.
- Typed shader registry, two-layer material model, PBR fallback and material/shader animation.

**Limitations:** no complete semantic/render/IK conformance suite; this is a working draft.

## Draft 0.4 revision P1 — vehicle/weapon profile definitions

- Added mandatory `modelProfiles` schema and normative annexes for `vehicle.car.v1`, `weapon.firearm.v1` and modular `weapon.attachment.v1`.
- Added `component` animation target with rest-relative translation/rotation semantics for mechanical, non-skin nodes.
- Defined wheel/steering and hinge axes, ordered axle metadata, attachment mount classes/interfaces, and deterministic accessory frame composition.
- Added profile validation fixtures and executable structural and mathematical smoke tests; profile conformance is not yet independently certified.

## Draft 0.4 revision P2 — skeleton profile registry

- Added the machine-readable skeleton profile registry `profiles/skeleton-profiles.json` (`humanoid.vrm1` NORMATIVE role data from VRM 1.0, `generic.v1` EXACT_ONLY, `animal.*.v1` PROVISIONAL).
- Added the annex `profiles/humanoid.vrm1.md`: VRM 1.0 roles, required set, parent rules, T pose, conformance tests `HUM-001..006`, and the proposed `ADM-REF-NORM` correction convention, IK and socket templates and facial-profile rules.
- Added the PROVISIONAL, non-normative annex `profiles/animal.quadruped.v1.md` (generic quadruped, canine, feline, equine) with tests `QDR-001..004`. Quadruped profiles remain unregistered and are never `SEMANTIC`-compatible.
- §11 schema consistency fix: lists the optional `targetHeight`, `referenceCorrection` and `rigId` members that §11.1/§16 already used. Clarified the VRM +Z vs ADM −Z facing and the mirrored-rig rule.
- Added `SPEC_GAPS.md`, the register of unresolved points (pose tolerance, correction convention, multi-segment IK, joint limits, retarget maps, …).
- No binary container change.

## Draft 0.4 revision P3 — GPU texture containers

- Added §8.6, the GPU texture container registry: optional capabilities `ADM-TEX-KTX2-1` and the new `ADM-TEX-DDS-1` (`image/vnd-ms.dds`, DX10 header only).
- Registered formats RGBA8, BC1 and BC3 in sRGB and UNORM variants, with optional precomputed mip levels. Supercompression, Basis Universal, BC4–BC7, arrays and cubemaps are excluded.
- A KTX2/DDS source always requires a PNG/JPEG `fallbackSource` of identical pixel size. Colour textures must use sRGB and data textures UNORM.
- New validation codes `IMAGE_FALLBACK_SIZE` and `IMAGE_COLORSPACE`; specified conformance tests `MAT-005` and `TEX-001..003`. Independent conformance testing remains outstanding. Closes the format-definition gap `SPEC_GAP-KTX2-SUBSET`.
- No binary container change.

## Draft 0.4 revision P4 — semantic skeleton, animation and IK gap resolution

- Made the `.adm_anim` library key set normative and aligned it with the already implemented `revision`, `namespace`, `motionScale`, `sourceHeight` and `rootMotionSource` fields.
- Defined the 25° humanoid reference-pose tolerance, coordinate-basis conversion rule, and `ADM-REF-NORM-1` rest-rotation correction algorithm. Humanoid semantic files now require and validate corrections for every mapped role.
- Clarified that VRM humanoid root motion uses `hips`, never a synthesized `root` role; v1 EXTRACT is limited to semantic humanoid hips tracks.
- Defined the skeleton registry/template file schema, custom profile publication requirements, and the explicit v1 prohibition on cross-profile retarget maps.
- Specified exact two-bone reach clamping and the equal-length zero-distance singularity rule; documented that joint limits and multi-segment IK are outside ADM-IK-1.
- Animal profiles, their STAND pose, and cross-species retarget remain provisional pending explicit anatomical approval and independent fixtures.
- Updated the reference solver and validator to match the clarified humanoid reference-pose, correction and IK rules.

## Draft 0.4 revision P5 — shader registry foundation

- Added the machine-readable shader registry and registered the existing core PBR and layered profiles without changing their parameter semantics.
- Added `adm.surface.cutout@1.0.0`, requiring masked alpha with the exact ADM §8 cutoff rule; Blender selection, validation and export/import preserve that contract.
- Added a profile contract and a registry consistency test. The requested Core 20 set is not complete; only profiles with a concrete contract are listed as official.
- No binary container change.

## Draft 0.4 revision P6 — portable emissive profile

- Added `adm.surface.emissive@1.0.0` to the official registry, using the existing linear PBR emissive factor/texture contract.
- Blender export/import preserves the profile identity and rejects materials with no effective emissive factor.
- Added the profile annex and material round-trip/negative tests. No proprietary glow, bloom or indirect-light behavior is implied.
- No binary container change.

## Draft 0.4 revision P7 — mesh decal profile

- Added `adm.surface.decal@1.0.0` with mandatory straight-alpha `BLEND` and no screen-space or deferred-renderer behavior.
- Blender selection, validation and export/import preserve the decal profile and alpha mode.
- Added profile documentation and valid/invalid round-trip coverage. No binary container change.

## Draft 0.4 revision P8 — Core 20 shader registry and contracts

- Added all 20 requested shader IDs, exact `1.0.0` versions and typed parameter schemas to the generated registry.
- Added per-profile contract annexes and deterministic reference evaluators/tests for cutout, alpha blend, glass Fresnel, foliage orientation tint, terrain weights, wrapped diffuse and triplanar weights.
- Extended Blender profile selection, schema synchronization and generic typed parameter import/export; added round-trip checks for all registered IDs.
- Profiles without dedicated Blender node builders preserve data and explicitly report/use PBR fallback. Full renderer conformance is not claimed; see `SPEC_GAPS.md`.
- No binary container change.

## Draft 0.4 revision P9 — Blender viewport previews for the Core 20 profiles

- Added Blender node-preview builders for brick, concrete, roof, bark, rock (triplanar), terrain 4-layer, glass, water, vehicle paint, skin, fur, fabric, feather, scales and foliage. Previews are separate `ADM Preview` nodes and are never exported; the portable PBR fallback is unchanged.
- Overridden numeric parameters drive the preview through live drivers (animatable); editing a value enables its override automatically.
- `adm.building.brick@1.0.0`: added the `mortar_color` parameter that the contract already referenced (`mortar_rgb`), and specified which textures `uv_scale` applies to.
- Skin, fur and fabric previews are approximations with Principled BSDF and are labeled as such in the UI.
- Added a reference mortar-mask generator and Cycles-bake tests that check preview colors and roughness against the contract math.
- No binary container change.

## Draft 0.4 revision P10 — vertex controls, external images and physical surfaces

- Added versioned extension contracts for `ADM_vertex_control_v1`, `ADM_external_images_v1`, and `ADM_physical_surfaces_v1`.
- Registered `COLOR_0` control semantics only when the required vertex-control extension is declared; retained ordinary linear RGBA semantics otherwise. `COLOR_1` transport is defined, but per-profile meanings remain a SPEC_GAP.
- Added structural and resolved validation for safe relative external-image URIs, MIME, size, dimensions, hashes and fallback references. Blender export defaults to embedded textures; external export writes deterministic sidecars and import resolves them relative to the ADM asset.
- Added physical surface profile IDs and per-triangle collision-mesh references. Blender stores IDs in the `adm_physical_material_id` FACE string attribute; the UI can assign the collider's selected stable ID to selected faces.
- Added Blender workflow tests for external sidecar resolution and physical surface export/import round-trip.
- Vertex-control values and palette settings currently serialize and import, but universal tint/normal/reflection/wetness preview application, verified animation binding, full `COLOR_1` rules, external failure-cleanup/security edge coverage, and independent-reader interoperability remain open in `SPEC_GAPS.md`. These extensions are not yet certified for full renderer interoperability.
- Reworked `tools/build_fixtures.py` to use checked-in manifests and verified chunk payloads instead of a developer-local ZIP; `--output-dir` now works and fixture regeneration is byte-reproducible.

## Draft 0.4 revision P11 — vertex-control preview and animation

- Added Blender viewport application of `COLOR_0` tint-palette sampling, normal strength, wetness color and roughness for Core, layered, custom-fallback and profile preview materials when enabled.
- Added exact-name extension-level `shaderParameter` animation targets for `tintOffset`, `normalMultiplier`, `reflectionMultiplier` and `wetnessOffset`; `.adm_anim` requires the extension when those channels are present, and model/material binding is validated.
- Added round-trip workflow assertions for exported `COLOR_0`, material control settings, animation bindings and sampled wetness values.
- Added Cycles bake tests for wetness albedo/roughness, live driver updates, and exact dielectric/metallic F0 node outputs.
- Blender's Principled BSDF cannot match the exact metallic F0 equation; reflectivity remains approximate for metallic materials. Per-profile `COLOR_1` semantics and independent renderer conformance remain open.
- No binary container change.

## Draft 0.4 revision P12 — exact F0 preview and Core 20 COLOR_1 contract

- Vertex-control preview now mixes dielectric and metallic Principled lobes at the material metallic factor, encoding effective dielectric F0 as IOR and metallic F0 as the lobe base color.
- Added Blender Cycles bake checks for the effective dielectric and metallic F0 node outputs.
- Defined `COLOR_1` as reserved/no-effect with `(0,0,0,0)` missing default for each of the 20 registered Core profiles. Blender preserves explicit values through export/import and tests that changing them does not affect the preview.
- Added Blender F-Curve checks for material animation interpolation at endpoints and midpoints for STEP, LINEAR and CUBICSPLINE.
- Added a Blender 5.2.4 headless CI job that verifies the official Linux archive against a pinned SHA-256 before running the integration tests.
- Added a deterministic scene generator for all 20 official shader previews; Blender CI verifies it saves a non-empty `.blend`.
- Independent-renderer interoperability and full shader-preview certification remain open; Skin, Fur and Fabric previews remain approximations.

## Draft 0.4 revision P13 — interactive surfaces

- Registered `adm.surface.interactive@1.0.0` and `ADM-INTERACTIVE-SURFACES-1` with typed runtime
  brightness/emission, off and unlit controls, color/alpha rules and the mandatory portable PBR fallback.
- Defined `ADM_interactive_surfaces_v1@1.0.0` with stable model-wide IDs and explicit node/primitive/UV
  bindings, per-instance runtime identity, barycentric hit coordinates and advisory aspect ratios.
- Added Blender selected-face authoring, static fallback preview, strict UV/reference validation and
  import/export preservation, including shared material and shared-mesh node cases.
- Preserved ordinary HDR `COLOR_0` on mixed-material screens; defined deterministic linear-space
  bilinear sampling and clamped straight alpha. Fallback normal tangents use the appropriate UV set
  and ADM handedness; unsupported or inconsistent texture UV mappings are reported, not guessed.
- Added a two-screen binary fixture with a readable manifest, numerical expectations, malformed
  fixtures and Blender/reference tests. Independent engine-renderer certification remains outstanding.
- No binary container change; existing assets and shader meanings are unchanged.
