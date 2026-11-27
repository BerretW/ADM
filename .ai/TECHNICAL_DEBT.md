# Technical debt

This file tracks issues confirmed during the current mission. Verify each
starting observation before treating it as current debt. Every entry must state
severity, cause, workaround, proposed fix, and source/test evidence.

## Open issues

### Terrain Control Map consumer support
- **Severity:** High for assets that require texture-driven terrain weights.
- **Cause:** `ADM_terrain_control_map_v1@1.0.0` has a normative contract,
  reference weight/coordinate math, and structural validation, including a
  gate for registered four-layer profiles and four stable IDs in every mode,
  and World Tile can export opt-in, source-sampled RGBA maps and sample them in
  the Detailed material preview. Blender now imports and exports the extension,
  exposes authoring properties, and previews supported modes. World Tile has
  VTK evidence for minification, mip selection, and rendered seams. Blender
  Cycles verifies minified filtered weights and a shared world-XZ edge across
  adjacent meshes; explicit mip selection, cross-reader parity, and per-layer
  parallax ordering remain unverified. Blender's current terrain preview does
  not implement POM, so it cannot render-verify the ordering against an active
  parallax effect. Blender falls back to vertex weights when
  sampler wrap modes differ by axis, because its Image Texture node applies one
  wrap mode to both axes.
- **Workaround:** Blender emits an import warning for axis-specific wrap modes
  and shows normalized vertex weights in that case. Do not label the available
  preview paths as fully conformant.
- **Next step:** Complete shader-composed final-weight diagnostics and verify
  source-rule tile borders and cross-reader filtering parity. Export diagnostics
  now report palette conflicts by LOD and tile/LOD, plus exact emitted
  `COLOR_1` input means by stable ID across tiles/LODs; they do not yet
  aggregate final rendered weights. VTK render regressions now verify external-
  mask and source-rule seam pixels at magnified and minified scales; parallax-
  at-border and cross-reader seam parity remain unverified. World Tile now imports
  bounded external RGBA masks, persists their paths and stable-ID channel
  mapping in AWTP v14, and uses them in export and the Detailed preview.
  External image bytes remain external to the project file.
  Generated tile maps now use clamp-to-edge
  samplers, and VTK tests exact source-grid edges and mip selection, but these
  tests do not establish final cross-tile rendered seams. Blender now has
  rendered evidence for translated object positions and a matching
  floating-origin shift; sampler filtering, mip behavior, and pre-parallax
  ordering remain unverified there. Keep physical classification based on
  Blender now has rendered evidence for translated world positions, a
  compensating floating-origin shift, minified weight averaging, and an
  adjacent-mesh world-XZ seam. Explicit mip selection, cross-reader
  sampler/filter parity, and per-layer parallax ordering remain open; the
  preview does not implement POM. Keep physical classification based on stable
  authored surface links and manual paint, never rendered Control Map output.
- **Evidence:** `adm-standard/extensions/ADM_terrain_control_map_v1.md`,
  `adm_blender/core/material_math.py`, `adm_blender/core/validate.py`,
  `adm_blender/blender/import_adm.py`, and the focused tests recorded in
  `.ai/TESTS.md`.

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
  Maps, wider profiles and texture arrays. The Control Map boundary is
  architectural guidance, not a resolution of five-plus-surface representation.
  A spatial-region candidate measured worse on the current reference (more palettes and greater affected-vertex
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

### Terrain Macro Color consumer support
- **Severity:** High for assets that require the macro effect.
- **Cause:** `ADM_terrain_macro_color_v1@1.0.0` has a normative contract,
  reference color/coordinate math, profile/image/color-space/sampler
  validation, and independent vectors. World Tile and Blender now author,
import/export, and render the feature; Blender also verifies output against
the reference math and preserves editable settings through save/reload.
World Tile now measures a shared-world map across adjacent tile actors at
magnified and minified views. Exact mip selection, separate-image gutter
handling, parallax ordering, and cross-reader conformance remain unverified.
- **Workaround:** Use Macro Color only with registered four-layer profiles and
  the tested projection and blend modes. Current consumer support is not
  cross-reader certification.
- **Next step:** Verify exact mip/gutter continuity for separately tiled
  images and cross-reader output. World Tile now has rendered evidence for
  adjacent tile continuity and independence from per-layer Parallax/POM;
  Blender's terrain preview still does not implement POM.
- **Evidence:** `adm-standard/extensions/ADM_terrain_macro_color_v1.md`,
  `adm_blender/core/material_math.py`, `adm_blender/core/validate.py`,
  `adm_blender/blender/import_adm.py`, the focused tests, and the compatibility
  matrix.

### Terrain Macro Normal consumer support
- **Severity:** High for assets that require the macro normal effect.
- **Cause:** `ADM_terrain_macro_normal_v1@1.0.0` has a normative BC5/RNM/frame
  contract, reference math, profile/image/format/sampler validation, and
  independent vectors. World Tile authoring/export/presets and local/shared
  previews are implemented, including BC5 source preservation, reconstructed
  RGB fallback, parallax independence, and unchanged collider assignments.
  Blender authoring/export/save-reload and local/shared RNM previews work for
  rotated surfaces and a fixture with a layer normal on a different UV set.
  Mirrored/degenerate UV tangent-frame behavior is not verified; filtered
  mip/border continuity, broader cross-frame fixtures, adjacent-tile
  continuity, and portable fallback equivalence are also unverified.
- **Workaround:** Blender rejects required Macro Normal data before scene
  mutation. Keep this guard until the renderer verifies mirrored/degenerate
  tangent frames and BC5/fallback handling; current preview evidence does not
  establish complete required-extension support.
- **Next step:** Verify mirrored/degenerate tangent-frame handling and BC5/RGB
  fallback equivalence, then enable required-data import only after round-trip,
  shared-tile seam, mip, parallax-independence, and collider tests pass.
- **Evidence:** `adm-standard/extensions/ADM_terrain_macro_normal_v1.md`,
  `adm_blender/core/material_math.py`, `adm_blender/core/validate.py`,
  `adm_blender/blender/import_adm.py`, the focused tests, and the compatibility
  matrix.

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
- **Cause:** Historical verification was Windows-focused. Blender 5.2.3
  reports dependency cycles when preview drivers target shader-node output
  `default_value` properties and feed back through the node-tree output.
  `_Graph._driver()` and `source()` in
  `adm_blender/blender/shader_preview.py` construct these live preview links.
- **Workaround:** Keep the live drivers and report the warnings; disabling them
  would break preview updates. Do not suppress the diagnostics.
- **Next step:** Find a cycle-free live-update path and verify it against the
  material preview suite before replacing the current driver mechanism. Test
  supported platforms and codecs where available.
- **Evidence:** `adm_blender/blender/shader_preview.py`,
  `adm_blender/tests/test_shader_preview.py`,
  `adm_blender/tests/test_material_height_blender.py`, and `.ai/TESTS.md`.

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
