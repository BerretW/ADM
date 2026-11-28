# Technical debt

This file tracks issues confirmed during the current mission. Verify each
starting observation before treating it as current debt. Every entry must state
severity, cause, workaround, proposed fix, and source/test evidence.

## Open issues

### Terrain Control Map consumer support
- **Severity:** High for assets that require texture-driven terrain weights.
- **Cause:** `ADM_terrain_control_map_v1@1.0.0` has a normative contract,
  reference weight/coordinate math, and structural validation for registered
  four-layer profiles and four stable IDs in every mode. World Tile exports
  source-rule maps and bounded external RGBA masks, stores external paths in
  AWTP v14, and previews maps before per-layer parallax. VTK tests cover
  minified filtering and source-rule/external-mask seams at magnified and
  minified scales. Blender imports and exports required maps, exposes
  authoring controls, and previews supported modes. Cycles tests cover all six
  weight modes, UV selection, coordinate offsets, translated world positions,
  floating-origin compensation, filtered minification, and an adjacent
  shared-world seam. Blender does not expose exact mip selection, and its
  preview does not implement POM, so per-layer parallax ordering is not
  render-verified. Its Image Texture node applies one wrap mode to both axes.
- **Workaround:** When an imported sampler uses different wrap modes by axis,
  Blender warns and previews normalized vertex weights instead. Treat current
  renderer support as partial.
- **Next step:** Directly compare raw renderer output arrays and verify
  separately tiled mip gutters. The Detailed viewer now shows selected final
  shader weights after Control Map sampling and height blending. World Tile VTK and Blender Cycles now
  consume the same 256-by-256 checker texture on a matched 32-by-32 plane/UV
  sample grid. Every pixel matches the shared 0.5/0.5 vector within 0.02;
  direct backend-array parity is not yet measured.
  The Blender preview has no POM implementation, so per-layer parallax ordering
  cannot yet be rendered there; do not claim parity until a supported path
  exists.
  Keep collider classification based on authored physical weights and stable
  links. A focused regression confirms that changing an external Control Map
  to assign every visual sample to one surface leaves independently painted
  collision assignments and decoded collider positions/indices unchanged.
- **Evidence:** `adm-standard/extensions/ADM_terrain_control_map_v1.md`,
  `adm_blender/core/material_math.py`, `adm_blender/core/validate.py`,
  `adm_blender/blender/import_adm.py`, and the focused tests recorded in
  `.ai/TESTS.md`.

### Four-layer palette conflicts
- **Severity:** High for exact representation; approximate mode has measured
  weight loss and does not provide exact five-plus-surface representation.
- **Cause:** A four-layer primitive cannot represent arbitrary five-plus
  simultaneous weights. Palette intersections now reconcile coincident
  positions across primitives, LODs, and tile edges, but can drop substantial
  non-dominant weight to maintain an identical decoded value at each shared
  position.
- **Workaround:** New projects default to strict rejection. Users can opt into
  approximate reduction, which preserves each corner's dominant surface and
  reconciles shared-vertex weights across matching tile/LOD positions. It
  reports mean and maximum total-variation error, plus up to 20 affected
  triangles with dropped per-corner weights and stable surface IDs. Users can
  repair source weights with the existing Map-tab Surface paint tool.
- **Next step:** Compare palette reduction with boundary refinement, Control
  Maps, wider profiles and texture arrays. The Control Map boundary is
  architectural guidance, not a resolution of five-plus-surface
  representation. Spatial-region candidates have been compared on the
  rebuilt reference and noisy 12-tile stress fixture. An albedo-only VTK
  vertex-RGB proxy render measures pixel error for both strategies on both
  assets, but does not exercise layered textures, height blending, normals, or
  parallax. Render both strategies through the layered terrain shader and
  measure export costs on larger assets before deciding whether any alternative
  should replace face-mask reduction. Three samples per asset now give median
  export times of 1.187 s (reference) and 1.203 s (stress), but do not establish
  scalability.
- **Evidence:** `appartus_world_tile/awt/adm_export.py` and
  `appartus_world_tile/tests/test_export.py`,
  `adm-standard/extensions/ADM_terrain_surface_v1.md`, and Blender material
  round-trip tests. Rebuilding the reference AWTP
  reproduces 54 conflicts; strict mode writes no tile files; approximate mode
  measures 1.243% mean / 3.922% maximum error and passes duplicate-position
  comparisons across tiles and LODs. The stress fixture records 2,870
  conflicts, 34 palettes, 100% dominant-ID preservation, and exact shared
  positions; export-index v9 fingerprints shared-edge palette inputs and
  selected exports include only adjacent tiles whose seam digest changed. See
  `.ai/TESTS.md`.

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
  Cycles verifies mirrored handedness, zero map-scale components, and
  degenerate UV fallback on aligned and rotated (-Y) surfaces. Blender's native
  tangent fallback diverges from the contract for a degenerate UV frame near
  world +X: it selects -Z where the deterministic contract requires +Z.
  Required `SHARED_WORLD_XZ` import/export now passes round-trip checks for exact
  BC5 primary bytes and reconstructed RGB fallback pixels. World Tile now
  renders a shared Macro Normal map across adjacent tile actors at magnified
  and minified views within the measured seam threshold. Filtered mip/border
  continuity and cross-reader parity remain open.
- **Workaround:** Use `SHARED_WORLD_XZ` for required Macro Normal in Blender.
  Required `LOCAL_UV` data is rejected before scene mutation; its preview is
  available but does not conform for the identified degenerate frame.
- **Next step:** Implement a deterministic local-frame fallback near world
  +X, or retain the import guard if Blender's shader nodes cannot express it.
  Then extend frame, mip/filter, seam, and cross-reader verification.
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
