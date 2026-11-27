# Mission decisions

Record evidence, consequences, compatibility, and tests for each accepted
decision. Items below are pending investigation unless explicitly marked
confirmed.

## Confirmed constraints
- Work on the actual current checkout; never reset to the external audit
  baseline or discard newer changes.
- Preserve the previous mission history at `.ai/archive/1f5c763/`.
- Do not create a standalone ADM Editor. Extend the existing Blender and World
  Tile authoring applications.
- Keep frozen shader/profile identities and meanings unchanged. New behavior
  must be opt-in and versioned.
- Do not claim renderer support from metadata, reference math, or a skipped
  test. Verify rendered output where the request requires actual rendering.
- Treat the pasted attachment as a read-only source; `.ai/MISSION.md` is its
  working copy.

## Pending audit and design decisions
- Compare boundary refinement, Control Maps, wider profiles and texture arrays
  against actual seam/render fixtures. A reference-only spatial region palette
  experiment now provides a preliminary comparison; choose only after measuring
  representability, compatibility, cost and error.
- Audit existing physical material/collider schemas before adding fields or
  registries; avoid duplicate friction/restitution semantics.
- Compare versioned BC5 fallback designs and prove primary-byte preservation,
  sampler/UV retention, core-PBR behavior and layered-shader compatibility.
- Derive parameter ranges, equations, sampling order, fallbacks and capabilities
  from explicit contracts and reference tests, not renderer assumptions.
- Verify VTK/Blender shader-hook behavior and budgets against actual supported
  runtimes before claiming combinations are supported.

## Evidence log

### Palette export policy (implemented; provisional within M2)
- Keep the existing four-layer shader profile unchanged. New AWTP projects use
  strict export; legacy AWTP projects without a policy load as approximate to
  preserve their previous export behavior.
- Approximate reduction retains each triangle corner's dominant surface, then
  reconciles the effective weights for shared vertices within each tile LOD.
  Report total-variation weight error; do not describe the result as exact or
  claim general cross-tile/LOD continuity without evidence. The rebuilt
  reference's decoded output does meet a 1% total-variation threshold at
  matching world positions across all tiles and LODs.
- Store identity on each source surface, not in its local material or shader
  slot. Missing legacy IDs derive deterministically from the original name;
  serialized IDs survive renames. `ADM_terrain_surface_v1` carries the
  ordered local-slot-to-global-ID mapping as optional, non-rendering metadata.
- Show a bounded deterministic sample of affected triangles, dropped surface
  IDs and raw per-corner weights. Keep the complete conflict count and
  aggregate total-variation measurements, and direct manual repair to the
  existing Surface paint tool. Do not overload the optional metadata extension
  with weights or physical properties.
- Evidence: `appartus_world_tile/awt/adm_export.py`,
  `appartus_world_tile/awt/project.py`, `appartus_world_tile/awt/material.py`,
  `adm-standard/extensions/ADM_terrain_surface_v1.md`, and the World Tile and
  Blender identity round-trip tests.
- Rebuilding `reference_project/advanced_reference.awtp` produces 54 conflicts
  in `x000_y001` (18 per LOD). Strict mode rejects before tile writes.
  Approximate mode affects 100 vertex instances at 1.243% mean and 3.922%
  maximum total-variation error; decoded shared positions agree across
  primitives. The checked-in prebuilt PLYs showed zero conflicts because they
  are stale relative to the AWTP rebuild, not because the historical conflict
  report was stale.
- Preliminary strategy comparison: on the rebuilt reference, the implemented
  face-mask selection plus deterministic palette packing uses 9 material
  palettes across tile files, with 1.243% mean and 3.922% maximum error on
  affected vertices and 100% dominant-surface retention. A competing spatial
  region strategy that picks four surfaces by aggregate corner weight in
  4 m, 8 m and 16 m centroid bins uses 27, 26 and 22 palettes, respectively,
  with about 2.21% mean and 9.80% maximum error; it also retains all dominant
  surfaces on this fixture. This supports the implemented strategy for this
  asset only. It does not compare boundary refinement, Control Maps, wider
  shader profiles or texture arrays, and the region variant was not rendered.
- Remaining decision: compare this reduction with tile/LOD boundary refinement,
  control maps and wider palettes before choosing a final cross-boundary
  contract.

### Physical surface type metadata (implemented; M3 complete)
- Preserve `ADM_physical_surfaces_v1` unchanged for its registered reaction
  profiles, collider defaults, and per-triangle stable references. Add
  `ADM_physical_surface_types_v1` as an additive contract for descriptive type,
  subtype, tag, and author description fields on existing `physicalMaterials`.
- Keep friction and restitution as the only serialized physical coefficients.
  Physical type classification is independent of visual materials and does not
  cause gameplay or simulation behavior.
- Use a machine-readable registry for built-in `adm.physical.*.v1` types,
  subtypes and tags. Accept custom `org.<reverse-domain>.<name>.vN` IDs;
  preserve unknown IDs and resolve unknown types to the registered unknown
  fallback rather than rewriting the serialized ID.
- Require the additive extension in both `extensionsUsed` and
  `extensionsRequired` whenever semantic fields are present.
- Evidence: `adm_blender/core/physical_surface_registry.json`,
  `adm-standard/extensions/ADM_physical_surface_types_v1.md`,
  `adm_blender/core/validate.py`, Blender properties/import/export, focused
  validator tests, and Blender save/reload round-trip tests.
- `query_physical_material` resolves a collider's default record or a
  triangle-specific override in primitive index order; visual slots never
  participate. The validator suite covers override precedence and invalid
  triangle indices.
- World Tile's physical-material library and independent paint map are now
  implemented. Paint is sampled at collision-triangle centroids and exported
  as stable per-face IDs, independently of visual terrain painting. The
  physical map does not affect the visual rules digest.

### Automatic terrain physical classification (implemented; M3 complete)
- Store an optional physical-material ID on each stable terrain surface. The
  collision PLY carries the same quantized authored surface weights used by the
  terrain build; export sums the three vertex weights per collision triangle and
  selects the largest total, with `argmax`'s stable lowest-index tie break.
- The selected surface's physical-material link supplies the automatic
  assignment. A missing link leaves the triangle unassigned. Manual paint
  overrides automatic classification; paint value `255` means use the automatic
  mapping. No final color, camera, lighting, LOD shader output, parallax, or
  other view-dependent effect participates.
- Record each tile's dominant collision surfaces in manifest v4 so physical
  fingerprints include only mappings and material records that can affect that
  tile. Keep visual fingerprints independent of physical links and continue to
  invalidate only relevant tiles. AWTP v12 and preset v6 preserve the links.
- Evidence: focused World Tile tests verify dominant-weight assignment, manual
  override, unlinked-surface behavior, persistence, presets, and selective
  invalidation. A generated tile with automatic, manual, and unassigned faces
  passes Blender import/save/reload/re-export.
- The 3D viewer switches between render and collision meshes rather than
  overlaying them. Collision faces use deterministic ID-derived colors and
  report material identity on hover. Cap inspection at 250,000 triangles and
  256 MiB per mesh; resolve collision files under the build directory.

### Independent World Tile collision meshes (implemented; M3 complete)
- Generate collision geometry independently from visual LODs and surface
  weights using the heightmap's RTIN error hierarchy. A collision error of
  `0` disables the optional path; positive values impose a measured vertical
  error bound.
- Preflight the extracted collision geometry against a hard per-tile triangle
  cap and fail explicitly when the bound and cap cannot both be met; do not
  silently relax either constraint. Collect boundary vertices from each tile,
  union them on the shared global grid, and propagate the required splits
  before generating the final per-tile meshes.
- Store collision PLYs separately from render LODs and export them as ADM
  `MESH` colliders. Automatic classification uses stable authored collision
  surface weights and explicit surface-to-physical-material links, not
  view-dependent rendered output. Manual paint overrides those assignments;
  triangles without a linked surface remain unassigned.
- Persist settings, physical paint, surface links, and the physical-boundary
  split-edge target in AWTP v12, preserving formats 2–11. Manifest v5 adds the
  physical-boundary edge target while retaining the v4 dominant-surface
  metadata and loading compatibility for prior manifests.
  Include collision and tile-local physical digests in export fingerprints so
  Export Changed responds only to relevant changes.
- Evidence: `appartus_world_tile/awt/pipeline.py`,
  `appartus_world_tile/awt/adm_export.py`, `appartus_world_tile/awt/project.py`,
  World Tile GUI/CLI, and the focused pipeline/export/project tests recorded
  in `.ai/TESTS.md`. Blender import, save/reload and re-export are covered by
  `adm_blender/tests/test_world_tile_collision_blender.py`.
- Physical-boundary refinement classifies automatic faces from the summed
  authored triangle weights and manual paint at triangle centroids; it refines
  mixed assignments until the configured RTIN split-edge size is met. The
  existing per-tile triangle cap and RTIN depth provide hard resource limits;
  deterministic tests cover automatic/manual boundaries and shared tile seams.
