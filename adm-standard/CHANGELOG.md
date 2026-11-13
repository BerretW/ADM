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
