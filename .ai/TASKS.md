# Mission checklist

Source: [MISSION.md](MISSION.md). Check an item only after implementation and
its required verification are recorded in [TESTS.md](TESTS.md). A planned
design, metadata-only support, or skipped test does not count as completion.

## M1 - Baseline and persistent state
- [x] Record current baseline, preserve worktree changes, and verify dependencies.
- [x] Archive the previous `.ai` mission history without losing its records.
- [x] Establish the World Tile regression baseline and maintain mission state.

## M2 - Terrain palette consistency (P0)
- [x] Separate global surface identity from local palette/material slots.
- [ ] Compare face-mask reduction with shared-edge, tile/LOD, irregular-edge,
      noise, and biome-transition fixtures; record palette count, visual error,
      identity preservation, and export cost.
- [x] Implement deterministic palette assignment/reduction and quantify error.
- [x] Add editor diagnostics, affected-triangle details, suggestions/manual
      repair, and strict versus explicitly approximate export.
- [x] Render and test two-to-four and five-plus surfaces, height blending, POM,
      slot permutations, mixed LOD, curved terrain, and disjoint biomes.
- [x] Adopt the Control Map boundary: preserve four local slots and stable
      global IDs; Control Maps remove vertex-density dependence but do not
      claim exact representation of five-plus active surfaces.
- [x] Confirm the architectural split for future Control Maps: retain
      four-slot face-mask reduction for over-capacity export, use Control Maps
      to remove vertex-density dependence within four slots, and keep physical
      boundary refinement separate from visual blending. Broader fixture and
      export-cost comparisons remain open.

## M3 - Physical Surface System and colliders (P0)
- [x] Define a versioned machine-readable registry, stable/custom IDs, subtypes,
      tags, unknown-type fallback, and physical-versus-visual independence.
- [x] Extend existing physical-material contracts without duplicating physics
      properties or adding gameplay behavior.
- [x] Assign stable physical material references to whole colliders and
      triangles; preserve them through triangulation and round trips.
- [x] Implement and test reference surface queries.
- [x] Generate bounded independent collision geometry with shared-tile
      boundary refinement, physical-material assignments, and Blender
      round-trip support.
- [x] Classify collision faces automatically from stable dominant surface
      weights, support manual overrides, and inspect collision geometry,
      physical boundaries, error, counts, and under-cursor material identity.
- [x] Refine collision geometry around physical-material boundaries under
      explicit deterministic subdivision and resource limits.

## M4 - Versioned material and texture contracts
- [x] Control Maps: define the extension schema, stable channel-to-surface
      mapping, modes, linear sampling, filtering, normalization, fallback,
      coordinate transforms, borders, and mip behavior.
- [x] Control Maps: verify exact unfiltered shared edges across local palette
      order and Blender world-planar sampling under object translation and a
      compensating floating-origin shift.
- [x] World Tile VTK: render a high-frequency Control Map at magnified and
      minified scales to verify mip-level selection.
- [x] World Tile VTK: verify sampled Control Map weights stay fixed before
      view-dependent per-layer parallax while parallax offsets change with view.
- [ ] Control Maps: verify cross-reader filtering parity, tile/border seams,
      and per-layer parallax ordering in Blender.
- [x] Control Maps: validate four-layer profile compatibility, stable IDs,
      texture references, decoded channel counts, and required-capability
      behavior.
- [x] Macro Color: define shared/local projection, color space, Multiply/Tint/
      Lerp equations, neutral defaults, per-layer influence, validation, and
      independent golden vectors. Renderer and authoring integration remain open.
- [x] Macro Normal: define coordinate space, strength, BC5 reconstruction,
      RNM composition, degeneracy handling, and missing-map behavior.
- [ ] Anti-tiling: define deterministic cell/hash transforms, seeds, derivatives,
      mip selection, tangent-normal transforms, and seam/floating-origin rules.
- [ ] Stochastic sampling: define deterministic blend samples, bounded tap
      counts, derivative behavior, and parity across material maps.
- [ ] Triplanar: define axis weights, projection frames, normal transforms,
      degenerate cases, map sampling, and combination limits.
- [ ] Detail maps: define albedo/normal/roughness contracts, neutral values,
      blending, mip/filter rules, and distance fade.
- [ ] Per-layer controls: define Normal Strength, Blend Softness, and descriptive
      Porosity independently, preserving frozen profile behavior.
- [ ] Parallax Self-shadowing: specify a bounded light-ray reference algorithm,
      direct-light scope, bias, missing-height fallback, and vectors.
- [ ] True Displacement: define physical units, direction, clamping, bounds,
      LOD/tile continuity, baking, and separation from collider generation.
- [ ] Material Distance LOD: define ordered distance bands, transitions,
      availability preferences, and renderer quality-policy behavior.
- [ ] BC5 core PBR: define a versioned role-specific fallback retaining source
      BC5 bytes, sampler, UV set, and normal strength.
- [ ] GPU resources: specify R16/mip/source-byte preservation, packing rules,
      texture-array tradeoffs, budgets, and explicit exhaustion behavior.
- [ ] For every contract, add capability/version rules, invalid-input checks,
      cross-reader fixtures, and compatibility/fallback evidence.

## M5 - Shared reference mathematics and registries
- [x] Add renderer-independent Control Map weight and coordinate reference math
      with independent vectors for all six modes and coordinate transforms.
- [x] Add Macro Color reference math for sRGB decoding, three blend modes,
      four-layer influence, and local/shared coordinates with golden vectors.
- [x] Add Macro Normal and RNM reference math with golden vectors.
- [ ] Add deterministic anti-tiling, stochastic, and triplanar reference math.
- [ ] Add Detail Map, per-layer control, self-shadow, displacement, and distance
      LOD reference evaluators and bounded numerical tests.
- [ ] Update ADM specification, extension/capability/shader registries, profiles,
      revision governance, validators, and fixtures for each adopted contract.
- [ ] Keep historical shader profiles frozen; version all changed behavior.
- [ ] Add deterministic golden vectors and invariants for the new contracts.

## M6 - World Tile authoring and renderer
- [x] Add bounded four-channel Control Map rasterization directly from compiled
      source rules, independent of mesh vertices and geometry LOD.
- [x] Integrate current biome/height/slope/noise/paint rules and road grades,
      configurable export resolution, AWTP v13 persistence, and source-sample
      identity checks; changing map resolution does not rebuild geometry.
- [x] Export required Control Map data with four stable IDs per palette,
      bounded RGBA textures, selective invalidation, and unchanged physical
      collider assignments.
- [x] Sample source-rule Control Maps in the Detailed material preview before
      per-layer parallax and height blending.
- [x] Render a Control Map plus view-dependent parallax and verify weight
      samples remain unshifted while per-layer offsets change with view.
- [x] Enable linear mipmapped textures in the World Tile material preview and
      count full mip chains against its decoded-texture budget.
- [x] Export generated per-tile Control Maps with `CLAMP_TO_EDGE` samplers and
      use clamped addressing in the World Tile preview.
- [x] Expose a local-palette Control Map channel diagnostic in the 3D viewer.
- [x] Verify adjacent source-rule Control Map raster edges match exactly when
      their local channel order differs.
- [x] Add a bounded RGBA external-mask decoder with format, byte, pixel,
      dimension, and malformed-input checks.
- [x] Persist external mask paths and four stable surface IDs in AWTP v14;
      add GUI channel assignment, export/preview integration, and source
      fingerprinting without changing physical classification.
- [x] Report palette-conflict counts by tile and LOD in strict rejection and
      approximate export results.
- [x] Aggregate the exported `COLOR_1` vertex-input means by stable surface ID,
      tile, and LOD; label them as input data, not shader-composed results.
- [x] Render adjacent external-mask Control Map tiles at magnified and
      minified scales and measure the shared-edge pixel difference.
- [ ] Diagnose shader-composed final weights and verify source-rule seams,
      mip/border continuity, parallax, and cross-reader output.
- [ ] Macro Color: author/import color maps and preserve image/source bytes.
- [ ] Macro Color: render neutral/enabled previews and verify collision geometry
      remains unchanged.
- [ ] Macro Normal: author/import BC5 and portable fallback data and preserve
      source bytes.
- [ ] Macro Normal: render neutral/enabled previews and verify collision
      geometry remains unchanged.
- [ ] Anti-tiling: expose bounded controls and render camera-, LOD-, and
      tile-seam regressions.
- [ ] Stochastic sampling: expose bounded tap/sample controls and render
      determinism, camera-, LOD-, and tile-seam regressions.
- [ ] Triplanar: author per-layer projection settings and report unsupported
      combinations.
- [ ] Triplanar: render projection-axis and normal-frame regressions.
- [ ] Detail Maps: author per-layer albedo/normal/roughness maps and neutral
      defaults.
- [ ] Detail Maps: render blend, mip, and distance-fade regressions.
- [ ] Per-layer Normal Strength: author and render independent surface tests.
- [ ] Per-layer Blend Softness: author and render boundary-transition tests.
- [ ] Per-layer Porosity: author descriptive metadata without physics behavior.
- [ ] Parallax self-shadowing: preview bounded direct-light effects and test
      missing-height fallback.
- [ ] True displacement: preview bounded geometry changes and measure
      silhouette, LOD/tile continuity, and collider independence.
- [ ] Material Distance LOD: author ordered bands and verify cross-fade behavior.
- [ ] Preview quality: expose quality policy without changing exported ADM data.
- [ ] Integrate composable shader components with existing preview
      infrastructure; preserve fast paths and report unsupported combinations.
- [ ] Add palette conflict UI and strict/approximate export behavior.
- [x] Add the physical-material library, automatic/manual classification, and
      independent collision authoring with physical assignment inspection.
- [x] Refine collision geometry around physical-material boundaries under
      explicit deterministic subdivision and resource limits.
- [ ] Version AWTP/presets, preserve supported old versions, unknown data,
      relative paths, and non-destructive failure behavior.
- [ ] Verify Export Changed, fingerprints, selective invalidation, atomic
      publication, source-byte preservation, and unchanged repeat exports.

## M7 - Blender and remaining consumers
- [x] Blender Control Maps: preserve references, author data, and validate
      imported/exported extension data.
- [x] Blender Control Maps: render all supported modes and verify UV selection,
      coordinate offsets, transformed world positions, and floating-origin
      stability.
- [ ] Blender Control Maps: verify sampler filtering, mip selection, tile seams,
      and per-layer parallax ordering.
- [ ] Blender Macro Color: preserve metadata and implement nodes.
- [ ] Blender Macro Color: verify rendered output and import/export/save/reload.
- [ ] Blender Macro Normal: preserve BC5/fallback metadata and implement nodes.
- [ ] Blender Macro Normal: verify rendered output and import/export/save/reload.
- [ ] Blender anti-tiling: implement nodes or report unsupported behavior.
- [ ] Blender stochastic sampling: implement bounded nodes or report unsupported
      behavior.
- [ ] Blender triplanar: implement projection/normal nodes or report unsupported
      behavior.
- [ ] Blender Detail Maps: author/preserve albedo, normal, and roughness maps;
      verify preview and round trips.
- [ ] Blender Normal Strength: author/preserve and verify preview/round trips.
- [ ] Blender Blend Softness: author/preserve and verify preview/round trips.
- [ ] Blender Porosity: author/preserve descriptive metadata only.
- [ ] Blender self-shadowing: render only supported direct-light behavior and
      test fallback.
- [ ] Blender displacement: render true silhouette changes or report unsupported.
- [ ] Blender Material Distance LOD: author and render supported distance bands.
- [ ] Integrate physical assignments, validation, import/export, save/reload,
      and collider round-trip in Blender.
- [ ] Preserve unsupported/unknown data safely and disclose actual renderer
      support; do not describe approximations as conformant effects.
- [ ] Audit and update relevant SDK, CLI, validators, viewers, math, importers,
      exporters and reference renderers; update the support matrix.

## M8 - Reference content
- [ ] Generate original deterministic Control Maps with source parameters.
- [ ] Generate original deterministic Macro Color maps with source parameters.
- [ ] Generate original deterministic Macro Normal maps with source parameters.
- [ ] Generate original deterministic Detail Maps with source parameters.
- [ ] Generate original deterministic height and physical surface maps with
      source parameters.
- [ ] Create comparison scenes for Control Maps and Macro Color.
- [ ] Create comparison scenes for Macro Normal.
- [ ] Create comparison scenes for anti-tiling and stochastic sampling.
- [ ] Create comparison scenes for triplanar and Detail Maps.
- [ ] Create comparison scenes for self-shadowing and displacement.
- [ ] Create a portable multi-tile AWTP reference world with irregular edges,
      multiple LODs, more than four world surfaces, new maps/effects, and
      separate colliders with automatic and manual physical assignments.
- [ ] Create physical-surface query fixtures and a brick sphere/plane showcase.
- [ ] Produce actual renders from multiple camera/light angles, including
      silhouette evidence for true displacement.

## M9 - Verification, documentation, and distribution
- [ ] Test contracts, invalid inputs, numerical/resource bounds, path safety,
      preservation, atomic export and cleanup.
- [ ] Run World Tile, Blender-runtime, standard, consumer, rendered-pixel,
      seam/LOD/collision and relevant build/package tests. Record every skip.
- [ ] Measure performance with methodology and environment; do not infer
      scalability from a single small sample.
- [ ] Update README, specification, registries, profiles, tool guides,
      migration guide, changelog, gaps, fixtures and conformance docs.
- [ ] Verify distributable archives outside the workspace and Blender in
      isolated preferences/repositories; avoid replacing user installations.
- [ ] Re-read the complete mission, audit every requirement, document blockers
      and create final report and technical-debt report.
