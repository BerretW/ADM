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
  - The built Blender extension decodes BC7 on Windows without an external wheel;
    other platforms and the final packaged extension remain unverified. Blender
    and World Tile targeted tests preserve supported source bytes and R16 values.

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
- [ ] Extend existing sphere/plane/relief preview for actual supported maps and
      transparent preview limitations.
- [ ] Add a true multi-surface height blend preview, distinct from single-surface
      preview and fast terrain inspection.
  - Single-surface and final-material multi-surface views implement parallax and
    POM. Multi-surface weight diagnostics remain unshifted CPU estimates;
    broader map and renderer compatibility needs verification.
- [x] Add safe, deterministic directory import for texture sets, with explicit
      conflict/missing-map handling; never infer unknown or packed maps.

## M7 - World Tile export
- [x] Export advanced material profiles and maps, rejecting or disclosing
      unsupported features rather than silently dropping them.
- [x] Generate tangents for parallax even without normal maps.
- [ ] Preserve shared textures, passthrough, content hashes, atomic writes,
      validation, Export Changed, and tile seams/LOD behavior.
  - Two-surface height-blend output at interpolated edge points agrees across
    irregular tiles and mixed LODs in a reference-math test. A VTK pixel test
    also compares two planar preview tiles with permuted layer slots and mixed
    mesh density against a continuous POM reference. Another VTK test renders
    exported sloped irregular tiles with mixed LODs, varying biome-noise weights,
    a shared-surface biome transition, texture fallbacks, and permuted slots.
    Curved terrain and disjoint-surface biome transitions remain open. A separate
    rendered five-surface example
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
- [x] Preserve legacy profile editing and make upgrades explicit.
- [ ] Round-trip unsupported parameters without silent loss.
  - Blender project data retains parameters excluded by an intermediate
    profile; those inactive values are not exported with the legacy schema.
  - No standalone ADM Editor application is required or permitted. Transfer
    these authoring requirements to existing tools.

## M9 - Blender plugin
- [x] Integrate profiles, nodes, properties, UI, math, import/export, codecs,
      validation, and vertex painting.
- [ ] Preserve COLOR_0/COLOR_1, precision, and unsupported POM metadata.
  - POM parameter and supported GPU-source round trips are tested. Packaged BC7
    decoding is verified on Windows; other platforms remain unverified.
- [x] Test real node generation and a bake/render of height blending.

## M10 - Remaining ecosystem
- [ ] Audit every shader consumer (editors, viewers, SDK, CLI, validators,
      generators, importers, exporters, and reference renderers).
- [ ] Record full/partial/fallback/not-applicable support per consumer.
- [ ] Prevent unsupported fields from being silently discarded.

## M11 - Fixtures and documentation
- [x] Create original procedural Rock, Sand, Dirt, Grass, and Cobblestone maps.
- [ ] Create an Advanced Terrain ADM scene and a functional multi-tile AWTP sample.
  - The AWTP builds and exports four validated tiles with three LODs and
    referenced R8/R16/BC4/BC5/BC7 textures. Its project folder can be copied
    independently, including its textures. The generated
    ADM comparison scene round-trips four advanced profiles with AO, height,
    parallax/POM metadata and R8/R16/BC4/BC5/BC7 source bytes. Its
    fixture-specific VTK visualization renders actual parallax/POM and can
    disable POM for comparison; Blender's native preview does not render it.
- [ ] Update specification, registries, profiles, docs, changelog, gaps,
      conformance, and fixture catalog with exact implemented contracts.

## M12 - Full verification
- [ ] Run targeted and full tests, build, and CI-equivalent checks.
- [ ] Run package audits and review new input/file parsing boundaries.
- [ ] Re-read MISSION.md and audit each checkbox against implementation.
- [ ] Report actual implementation, assets, test evidence, performance, and
      remaining limitations or external blockers.
