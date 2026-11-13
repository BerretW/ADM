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
- New validation codes `IMAGE_FALLBACK_SIZE` and `IMAGE_COLORSPACE`; conformance tests `MAT-005` (now certifiable) and `TEX-001..003`. Closes `SPEC_GAP-KTX2-SUBSET`.
- No binary container change.
