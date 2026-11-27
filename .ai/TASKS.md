# Mission checklist

Source: [MISSION.md](MISSION.md). Check an item only after implementation and
its required verification are recorded in [TESTS.md](TESTS.md). A planned
design, metadata-only support, or skipped test does not count as completion.

## M1 - Baseline and persistent state
- [ ] Record current baseline, preserve worktree changes, and verify dependencies.
- [ ] Archive the previous `.ai` mission history without losing its records.
- [ ] Establish the regression baseline and maintain mission state.

## M2 - Terrain palette consistency (P0)
- [ ] Separate global surface identity from local palette/material slots.
- [ ] Compare seam-safe palette strategies for shared vertices/edges, tiles,
      LOD, irregular boundaries, noise, and biome transitions.
- [ ] Implement deterministic palette assignment/reduction and quantify error.
- [ ] Add editor diagnostics, affected-triangle details, suggestions/manual
      repair, and strict versus explicitly approximate export.
- [ ] Render and test two-to-four and five-plus surfaces, height blending, POM,
      slot permutations, mixed LOD, curved terrain, and disjoint biomes.

## M3 - Physical Surface System and colliders (P0)
- [ ] Define a versioned machine-readable registry, stable/custom IDs, subtypes,
      tags, unknown-type fallback, and physical-versus-visual independence.
- [ ] Extend existing physical-material contracts without duplicating physics
      properties or adding gameplay behavior.
- [ ] Assign stable physical material references to whole colliders and
      triangles; preserve them through triangulation and round trips.
- [ ] Implement and test reference surface queries.
- [ ] Add independent terrain collision generation, bounded simplification,
      boundary refinement, manual physical paint, and diagnostics.

## M4 - Versioned material and texture contracts
- [ ] Define versioned Control Map modes, channel order, sampling, filtering,
      neutral values, combination, normalization, fallback, and seam behavior.
- [ ] Define Macro Color/Normal, anti-tiling/stochastic sampling, triplanar,
      Detail Maps, per-layer controls, porosity, self-shadowing, displacement,
      and Material Distance LOD contracts.
- [ ] Resolve the core-PBR BC5 primary/fallback conflict without changing
      historical meanings or silently recompressing source data.
- [ ] Define capability negotiation, serialization, validation, compatibility,
      and conformance fixtures for each new normative contract.
- [ ] Preserve R16 precision, mip payloads, GPU source bytes and existing
      profile behavior; establish explicit resource budgets.

## M5 - Shared reference mathematics and registries
- [ ] Update ADM specification, extension/capability/shader registries, profiles,
      revision governance, validators, reference math, and fixtures.
- [ ] Keep historical shader profiles frozen; version all changed behavior.
- [ ] Add deterministic golden vectors and invariants for the new contracts.

## M6 - World Tile authoring and renderer
- [ ] Add Control Map generation/import/painting, resolution and channel
      diagnostics without unnecessary geometry rebuilds.
- [ ] Add Macro Maps, anti-tiling, triplanar, detail controls, per-layer
      parameters, displacement, self-shadowing, and quality controls.
- [ ] Integrate composable shader components with existing preview
      infrastructure; preserve fast paths and report unsupported combinations.
- [ ] Add palette conflict UI and strict/approximate export behavior.
- [ ] Add physical surface library, automatic/manual classification,
      independent collision authoring, refinement, and inspection.
- [ ] Version AWTP/presets, preserve supported old versions, unknown data,
      relative paths, and non-destructive failure behavior.
- [ ] Verify Export Changed, fingerprints, selective invalidation, atomic
      publication, source-byte preservation, and unchanged repeat exports.

## M7 - Blender and remaining consumers
- [ ] Integrate profiles/extensions, authoring, previews, collider assignments,
      validation, import/export, save/reload and round-trip in Blender.
- [ ] Preserve unsupported/unknown data safely and disclose actual renderer
      support; do not describe approximations as conformant effects.
- [ ] Audit and update relevant SDK, CLI, validators, viewers, math, importers,
      exporters and reference renderers; update the support matrix.

## M8 - Reference content
- [ ] Generate original deterministic material maps and an advanced material
      comparison scene covering all required effects.
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
