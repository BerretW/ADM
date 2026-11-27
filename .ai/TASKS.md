# Mission checklist

Source: [MISSION.md](MISSION.md). The source is the complete user-provided request;
checkboxes track verification and delivery, not merely code changes.

## M1 - Audit and persistent state
- [x] Audit repository consumers, registries, governance, and current tests.
- [x] Compare World Tile changes from the referenced baseline commits.
- [x] Record existing behavior, changes, decisions, and verification in `.ai/`.

## M2 - GPU formats
- [x] Normatively specify R8, R16, BC4, BC5, BC7 UNORM/SRGB in DDS and KTX2.
- [x] Specify channels, block and mip sizes, color space, roles, fallbacks,
      missing channels, validation, and capability negotiation.
- [x] Enforce KTX2 `typeSize` 2 for R16 and 1 for the other registered formats.
- [ ] Preserve source precision and supported GPU texture bytes; validate codecs
      with independent test vectors, including R16 and mip chains.
  - The packaged Blender extension decodes BC7 on Windows without an external
    wheel; other platforms remain unverified. Blender and World Tile targeted
    tests preserve supported source bytes and R16 values.
  - World Tile now exports a separate reconstructed RGB normal for core PBR,
    while retaining the BC5 primary and its specified `(R,G,0,1)` shader fallback.
    Blender does the same when a shader parameter retains the matching BC5.
    Blender's standalone core-PBR BC5 path still needs resolution: a single
    texture cannot both retain the BC5 primary and offer an RGB fallback under
    the current two-channel fallback rule.

## M3 - Material and shader contracts
- [x] Define a versioned material-height extension without conflicting with
      top-level occlusion or geometric terrain displacement.
- [x] Add versioned terrain, two-layer surface, and layered PBR shader profiles
      while preserving frozen legacy behavior.
- [x] Specify per-layer AO, height, height blending, parallax, POM, bounds,
      fallback, capability, and PBR behavior.

## M4 - Shared reference implementation
- [x] Use registry-driven shared parameter/capability metadata and renderer-neutral
      reference mathematics.
- [x] Test AO, height/channel math, blend invariants/permutation, POM, numerical
      stability, and backward compatibility.

## M5 - World Tile data model
- [x] Extend existing MapSlot/Surface/TerrainMaterial contracts for AO, height,
      emission, shader settings, and explicit profile versions.
- [x] Preserve AWTP 2/3/4 loads; serialize a new version without mislabeling data.
- [x] Preserve presets, relative paths, texture collection, and all current paint,
      road, noise, project, and wizard behavior.
- [x] Keep shader-only edits out of rules_digest and geometry rebuild; include
      shader properties and texture bytes in material fingerprints.

## M6 - World Tile GUI and preview
- [x] Add AO/height and shader controls within existing material editor patterns.
- [x] Preserve biome graph and noise controls, naming, repeat, and edit workflow.
- [x] Extend existing sphere/plane/relief preview for actual supported maps and
      transparent preview limitations.
- [x] Add a true multi-surface height blend preview, distinct from single-surface
      preview and fast terrain inspection.
  - Single-surface, multi-surface and detailed terrain views implement parallax
    and POM. Per-fragment shader weight and offset diagnostics are available;
    CPU weight views and reported mean weights remain unshifted estimates.
    Supported maps and preview shapes have focused tests. VTK versions beyond
    the tested Windows 9.7.2 remain unverified.
- [x] Add safe, deterministic directory import for texture sets, with explicit
      conflict/missing-map handling; never infer unknown or packed maps.

## M7 - World Tile export
- [x] Export advanced material profiles and maps, rejecting or disclosing
      unsupported features rather than silently dropping them.
- [x] Generate tangents for parallax even without normal maps.
- [x] Provide explicit terrain shader selection and opt-in automatic upgrade
      when advanced settings are used, with visible notification.
- [ ] Preserve shared textures, passthrough, content hashes, atomic writes,
      validation, Export Changed, and tile seams/LOD behavior.
  - Two-surface height-blend output at interpolated edge points agrees across
    irregular tiles and mixed LODs in a reference-math test. A VTK pixel test
    also compares two planar preview tiles with permuted layer slots and mixed
    mesh density against a continuous POM reference. Another VTK test renders
    exported sloped irregular tiles with mixed LODs, varying biome-noise weights,
    a shared-surface biome transition, texture fallbacks, and permuted slots.
    The same test also covers curved terrain and a transition between disjoint
    two-surface biomes with four nonzero weights on the edge; it permutes the
    right-hand layer slots. A separate rendered five-surface example
    demonstrates an actual discontinuity when neighboring triangles drop
    different layers; the four-layer contract cannot represent all five
    simultaneous weights, and export reports the conflict count.
- [x] Ensure material-only edits do not rebuild geometry or vertex weights.

## M8 - ADM Editor
- [ ] Integrate the ADM Editor requirements into existing authoring tools:
      `adm_blender` and `appartus_world_tile`, including layer maps, height/AO
      controls, GPU formats, profile versions, validation, import/export, and
      real material preview.
- [ ] Integrate layer maps, height/AO controls, GPU formats, profile versions,
      validation, import/export, and real material preview.
  - World Tile exposes export-level DDS/KTX2 and automatic/BC7/RGBA8 settings
    for converted 8-bit images. It preserves compatible GPU inputs and 16-bit
    data by default; re-encoding GPU sources is opt-in. Per-map overrides add
    R8/R16/BC4 for selected data channels and BC5 for normals, along with
    automatic/BC7/RGBA8.
- [x] Preserve legacy profile editing and make upgrades explicit.
- [ ] Round-trip unsupported parameters without silent loss.
  - Blender project data retains parameters excluded by an intermediate
    profile; those inactive values are not exported with the legacy schema.
    Unknown official shader versions retain their parameter JSON, recognized
    texture references, samplers, and compatible source bytes on export. Their
    schemas and opaque nested references cannot be validated or remapped.
    World Tile retains unknown terrain shader settings in AWTP and rejects
    validation, build, and export. Their opaque references are not remapped.
  - No standalone ADM Editor application is required or permitted. Transfer
    these authoring requirements to existing tools.

## M9 - Blender plugin
- [x] Integrate profiles, nodes, properties, UI, math, import/export, codecs,
      validation, and vertex painting.
- [ ] Preserve COLOR_0/COLOR_1, precision, and unsupported POM metadata.
  - POM parameter and supported GPU-source round trips are tested. Packaged BC7
    decoding is verified on Windows; other platforms remain unverified.
    Optional material-height metadata, source bytes, sampler, and height UV
    tangents survive import/export and project reload. Required material height
    is rejected because Blender does not implement its effect. Unknown fields
    and nested extension references are retained without remapping and produce
    a warning.
- [x] Test real node generation and a bake/render of height blending.

## M10 - Remaining ecosystem
- [x] Audit every shader consumer (editors, viewers, SDK, CLI, validators,
      generators, importers, exporters, and reference renderers).
- [x] Record full/partial/fallback/not-applicable support per consumer.
- [ ] Prevent unsupported fields from being silently discarded.
  - Blender warns on import and export about unrecognized optional extensions,
    including after reload. Root-, scene-, imported node-, mesh-, material-, and primitive-level
    unknown extension JSON is retained without remapping opaque references;
    scene merges, primitive splits, and missing face tracking are rejected. Other
    locations and unimported nodes are not generally preserved through export.
    Conflicting root data is rejected.

## M11 - Fixtures and documentation
- [x] Create original procedural Rock, Sand, Dirt, Grass, and Cobblestone maps.
- [x] Create an Advanced Terrain ADM scene and a functional multi-tile AWTP sample.
  - The AWTP builds and exports four validated tiles with three LODs and
    referenced R8/R16/BC4/BC5/BC7 textures. Its project folder can be copied
    independently, including its textures. The generated
    ADM comparison scene round-trips four advanced profiles with AO, height,
    parallax/POM metadata and R8/R16/BC4/BC5/BC7 source bytes. Its
    fixture-specific VTK visualization renders actual parallax/POM and can
    disable POM for comparison; Blender's native preview does not render it.
    The ADM scene is bundled alongside the portable project.
- [ ] Update specification, registries, profiles, docs, changelog, gaps,
      conformance, and fixture catalog with exact implemented contracts.

## M12 - Full verification
- [x] Run targeted and full tests, build, and CI-equivalent checks.
- [x] Diagnose and fix the Windows offscreen packaged-GUI early-close failure.
- [x] Run package audits and review new input/file parsing boundaries.
  - The audited World Tile dependency graph has no known vulnerabilities, but
    no committed lockfile fixes every permitted dependency resolution.
- [ ] Re-read MISSION.md and audit each checkbox against implementation.
- [ ] Report actual implementation, assets, test evidence, performance, and
      remaining limitations or external blockers.
