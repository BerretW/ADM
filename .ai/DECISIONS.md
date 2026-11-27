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
  against actual seam/render fixtures. The Control Map boundary is accepted as
  an architectural constraint, not as proof that Control Maps are the best
  general palette strategy. A reference-only spatial-region experiment is
  preliminary; compare representability, compatibility, cost and error before
  changing the four-slot export policy.
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

### Control Map boundary and contract (M2 decision confirmed; M4 started)
- Keep four local layer slots mapped in stable order to global surface IDs.
  Texture-driven Control Maps remove dependence on mesh vertex density, but
  they do not increase the representable layer count or exactly encode five or
  more simultaneously active surfaces.
- Define Control Map weights before per-layer projection, parallax, and height
  blending. The extension requires stable four-ID mappings in every mode,
  accepts only registered four-layer terrain shader profiles, and requires
  linear sampled data, bounded coordinate transforms, normalized weights,
  deterministic fallbacks, and shared border/mip behavior.
- Control Map v1 accepts only registered `adm.terrain.four_layer` 1.0.0,
  2.0.0, 1.1.0, and 2.1.0 profiles and `adm.pbr.layered@2.1.0`.
  Every mode, including `VERTEX_ONLY`, requires all four stable IDs.
- Keep collision classification separate. Any future Control Map-based
  authoring classifier must consume raw camera-independent weights and bake
  stable collision assignments; it must not read final color or view-dependent
  shader output.
- Evidence: `adm-standard/extensions/ADM_terrain_control_map_v1.md`,
  `adm_blender/core/material_math.py`, `adm_blender/core/validate.py`, and
  `adm-standard/fixtures/expectations/terrain_control_maps_v1.json`.
- Consequences: unsupported readers must reject required extension data.
  Blender preserves and previews this extension for supported settings, while
  unsupported axis-specific wrap modes fall back to vertex weights with a
  warning. World Tile exports opt-in maps from the
  original height samples, road-graded height field, and current surface rules.
  The build manifest fingerprints source samples; changing them requires a
  rebuild before map export, while changing map resolution does not rebuild
  geometry. Exported maps use local four-slot ordering with unused IDs padded
  deterministically and zero-weight channels; each tile is bounded to
  16,777,216 aggregate palette texels.
- Keep collider classification unchanged by visual Control Maps. Collision
  assignments continue to use stable surface links and manual physical paint;
  they do not consume generated texture weights, rendered colors, camera data,
  or view-dependent shader effects.
- Consequences: World Tile now has source-rule export and external RGBA mask
  import with four stable-ID channel assignments, AWTP v14 path persistence,
  export, and an opt-in Detailed preview that samples maps before per-layer
  parallax and height blending. External image bytes remain external to the
  project file. Manual map painting, combined/final diagnostics,
  filtering/mip/border conformance, and rendered seam evidence remain open.
  Blender imports/exports required Control Maps, exposes authoring settings and
  stable layer IDs, and has Cycles pixel tests for all six modes with UV
  sampling, UV0/UV1 selection, coordinate offsets, and a world-planar
  XZ/origin sample. Transformed model coordinates, mip/filter, border/seam, and
  floating-origin conformance remain open.
  The wider M2 comparison of palette reduction, boundary refinement, Control
  Maps, wider profiles, and arrays remains open.

### Terrain Macro Color contract (M4 contract adopted; consumers pending)
- Apply the map after per-layer linear albedo sampling and final Control Map/
  height weights, before weighted layer combination. Support local UV and
  shared world-XZ projection; parallax must not shift macro coordinates.
- Decode RGB from sRGB to linear. `MULTIPLY` ignores alpha; `TINT` uses alpha
  as multiply coverage; `LERP` interpolates base albedo toward macro color using
  alpha coverage. `strength * layerInfluence[i]` gates each layer.
- A missing map, zero strength, or zero layer influence leaves albedo unchanged.
  White is neutral for `MULTIPLY` and `TINT`; zero alpha is neutral for `TINT`
  and `LERP`.
- Only registered four-layer terrain profiles and four stable surface IDs are
  valid. Macro Color changes rendered albedo only and never participates in
  collision classification or collider generation.
- Evidence: `adm-standard/extensions/ADM_terrain_macro_color_v1.md`,
  `adm_blender/core/material_math.py`, the validator, and independent vectors
  in `adm-standard/fixtures/expectations/terrain_macro_color_v1.json`.
- Consequences: Blender rejects required Macro Color data; World Tile and
  Blender render/authoring support remain incomplete. Filtering, mip/border
  continuity, and actual renderer output remain unverified.

### M2 palette policy with future Control Maps (architectural decision confirmed)
- Preserve four local visual slots and their stable global surface-ID mapping
  for existing profiles. Keep strict/approximate face-mask reduction as the
  export strategy when more than four surfaces compete for a primitive; report
  measured loss rather than claiming exact representation.
- Use Control Maps to remove dependence on vertex density and improve
  within-palette interpolation only. Their four channels map to the same four
  stable IDs; Control Maps do not solve five-plus simultaneous surface weights.
- Keep boundary refinement for independent physical collider assignments and
  geometry. It cannot replace visual material blending or increase the
  representable visual palette.
- Treat texture arrays as resource packing, not a semantic expansion of
  surface slots. Do not select wider profiles until compatibility and runtime
  costs are measured against the actual multi-tile fixtures.
- Maintain physical classification from stable authored, camera-independent
  weights and explicit physical references. Macro color/normal, lighting,
  parallax, and other view-dependent shader outputs never participate.
- Evidence: the rebuilt reference measures 9 palettes, 1.243% mean and 3.922%
  maximum affected-vertex total-variation error for the current face-mask
  strategy; preliminary spatial bins require 22–27 palettes and about 2.21%
  mean / 9.80% maximum error. Control Map v1, boundary-refinement behavior,
  and existing physical-classification tests establish their distinct roles.
- Consequence: the architecture is selected, but the M2 comparative benchmark
  remains open until palette count, visual error, identity preservation, and
  export cost are recorded across shared edges, tiles/LODs, irregular edges,
  noise, and biome transitions. Do not expand the four-slot profile based on
  one reference asset.

### Terrain Macro Normal contract (M4 contract adopted; consumers pending)
- Sample local UV or shared world-XZ, always in linear data. GPU sources are
  BC5 UNORM; portable normal images are lossless PNG.
- Reconstruct tangent-space Z from clamped BC5 XY, apply bounded strength and
  four stable per-layer influences, transform each layer normal into the
  common projection frame, compose with RNM, then combine with final terrain
  weights after Control Map and height blending.
- Define deterministic derivative frame fallback, handedness, RNM singularity,
  zero-result, and unavailable-map behavior. Macro Normal affects rendered
  normals only.
- Physical classification and collision generation remain independent of
  Macro Normal, final color, lighting, camera, parallax, and other view effects.
- Evidence: `adm-standard/extensions/ADM_terrain_macro_normal_v1.md`,
  `adm_blender/core/material_math.py`, validator tests, and independent
  vectors in `adm-standard/fixtures/expectations/terrain_macro_normal_v1.json`.
- Consequences: Blender rejects required Macro Normal data before scene
  mutation. World Tile and Blender authoring/render integration, filtered
  border/mip behavior, and portable fallback equivalence remain open.
