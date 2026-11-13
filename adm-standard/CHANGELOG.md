# Changelog

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
