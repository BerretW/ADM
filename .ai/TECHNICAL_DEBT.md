# Technical debt

This file tracks issues confirmed during the current mission. Verify each
starting observation before treating it as current debt. Every entry must state
severity, cause, workaround, proposed fix, and source/test evidence.

## Open issues

### Four-layer palette conflicts
- **Severity:** High for exact representation; approximate mode has measured
  low weight error on the current reference but is not exact.
- **Cause:** A four-layer primitive cannot represent arbitrary five-plus
  simultaneous weights. Per-triangle truncation also gives inconsistent values
  at shared vertices when neighboring primitives use different palettes.
- **Workaround:** New projects default to strict rejection. Users can opt into
  approximate reduction, which preserves each corner's dominant surface and
  reconciles shared-vertex weights within one tile LOD. It reports mean and
  maximum total-variation error, plus up to 20 affected triangles with dropped
  per-corner weights and stable surface IDs. Users can repair the source
  weights with the existing Map-tab Surface paint tool.
- **Next step:** Compare palette reduction with boundary refinement, Control
  Maps, wider profiles and texture arrays. A spatial-region candidate measured
  worse on the current reference (more palettes and greater affected-vertex
  error) but has not been rendered. Broaden the decoded-weight and rendered
  checks to additional source assets and independent tile/LOD boundaries. The current
  reference export passes a 1% decoded-weight total-variation bound across
  matching world positions, but this fixture does not establish a general
  guarantee.
- **Evidence:** `appartus_world_tile/awt/adm_export.py` and
  `appartus_world_tile/tests/test_export.py`,
  `adm-standard/extensions/ADM_terrain_surface_v1.md`, and Blender material
  round-trip tests. Rebuilding the reference AWTP
  reproduces 54 conflicts; strict mode writes no tile files; approximate mode
  measures 1.243% mean / 3.922% maximum error and passes duplicate-position
  comparisons within primitives and a <=1% total-variation comparison across
  tiles and LODs. See `.ai/TESTS.md`.

### Blender standalone core-PBR BC5 fallback
- **Severity:** High for portable normal-map use.
- **Cause:** The primary BC5 data and current RGB fallback contract have
  incompatible channel requirements in the standalone path.
- **Workaround:** No general workaround is accepted until verified against the
  exact current exporter and reader behavior.
- **Next step:** Design and test a versioned, unambiguous representation that
  retains original BC5 bytes.
- **Evidence:** Previous mission `.ai/TECHNICAL_DEBT.md` (archived).

### Preview and renderer limitations
- **Severity:** Medium; CPU composition and missing Blender POM rendering are
  not equivalent to shader execution.
- **Cause:** Existing renderer paths differ in sampling and effect support.
- **Workaround:** Clearly label approximations and rely only on tested actual
  shader previews for effects they implement.
- **Next step:** Extend existing renderers where feasible; verify pixels and
  report remaining backend limits.
- **Evidence:** Previous mission closeout and World Tile tests (archived).

### Opaque extension references
- **Severity:** High when editing/re-exporting data with unknown references.
- **Cause:** Unknown schemas do not identify which values reference ADM objects.
- **Workaround:** Preserve opaque JSON only where supported and reject unsafe
  transformations; never guess references from numeric values.
- **Next step:** Add explicit reference declarations only if justified by
  current formats and tested consumers.
- **Evidence:** Previous mission `.ai/TECHNICAL_DEBT.md` (archived).

### Multiplatform codecs and Blender cycle diagnostics
- **Severity:** Medium to high depending on release target.
- **Cause:** Historical verification was Windows-focused; Blender dependency
  cycles were observed without a confirmed minimal reproducer.
- **Workaround:** State the tested platform/runtime and preserve diagnostics.
- **Next step:** Test supported platforms where available; isolate cycle sources
  before attempting targeted fixes.
- **Evidence:** Previous mission closeout and test records (archived).

### Independent terrain collision authoring
- **Severity:** High for terrain collision workflows.
- **Cause:** Independent RTIN collision geometry, a measured vertical-error
  bound, a hard per-tile triangle cap, shared-edge refinement, manifest
  diagnostics, and ADM MESH-collider export now exist. The physical-material
  library, independent manual paint map, stable per-face assignment, automatic
  classification from dominant authored surface weights, selective fingerprints,
  Blender save/reload round trip, collision inspection, and deterministic
  physical-boundary refinement are also implemented. Refinement uses the
  configured RTIN split-edge limit, per-tile triangle cap, and maximum RTIN
  depth. No unresolved defect is currently confirmed in this workflow; broader
  large-world performance and consumer validation remain unverified.
- **Workaround:** Manual paint overrides automatic surface links. A dominant
  surface without a physical link remains unassigned; view-dependent shader
  output is never used for classification.
- **Next step:** Continue broadening tests for independent export, persistence,
  invalid references, selective invalidation, collision inspection, and Blender
  round trips; the broader material and texture mission remains open.
- **Evidence:** `appartus_world_tile/awt/pipeline.py`,
  `appartus_world_tile/awt/adm_export.py`,
  `appartus_world_tile/awt/material.py`, and focused tests in
  `appartus_world_tile/tests/test_pipeline.py`, `test_export.py`, and
  `adm_blender/tests/test_world_tile_collision_blender.py`. See `.ai/TESTS.md`.
