# Mission state

- Blender 1.24.41 and 1.24.42 inadvertently include an ignored nested
  `adm_blender.zip` from the source directory. Do not distribute those
  packages. The manifest now excludes ZIP files and the build checks the
  resulting package for nested ZIPs.
- Blender 1.24.43 passes the 36-step build and its ZIP has no nested archives.
  The install check used isolated preferences but the default extension
  repository still pointed to the user's Blender 5.2 directory, replacing
  its installed `adm_tools` with 1.24.43. The previous installed version
  was not recorded.
- Blender 1.24.45 includes scene, mesh, and primitive metadata preservation.
  Its package passed source comparisons, packaged regressions, and installation
  and reactivation in an explicitly isolated extension repository.
- Blender retains unknown scene and mesh extension JSON and primitive extension JSON on imported faces, without
  interpreting its references. Export rejects missing tracking, lost primitives,
  and primitive splits; other unsupported extension locations remain incomplete.
- World Tile 0.7.17's 102-file ZIP matches source bytes; packaged export
  regressions and its relocated four-tile reference export passed.
- World Tile 0.7.16's 102-file ZIP matches source bytes; extracted tests cover
  per-map formats, channel mapping, sharing, UI and preset persistence. Its
  relocated reference project exports four validated tiles.
- World Tile 0.7.15's 102-file ZIP matches source bytes and passed extracted
  GPU-format, explicit-conversion, precision, input-limit, GUI, and per-tile
  invalidation tests. Its relocated reference exports four validated tiles.
- World Tile 0.7.13 preserves multichannel 16-bit data PNG primaries and
  converts supported RGB/RGBA 16-bit TIFF data maps to 16-bit PNG. The TIFF
  height preview preserves the selected channel; unsupported 16-bit TIFF
  layouts fail explicitly. Export revision 5 invalidates previous tile outputs.
- World Tile has export-level DDS/KTX2 and automatic/BC7/RGBA8 settings for
  converted 8-bit images. Compatible GPU inputs remain byte-identical unless
  re-encoding is enabled; 16-bit data keeps its precision. Export warns about
  re-encoding and formats that differ from the selection.
  Container and conversion changes invalidate textured tiles. A global encoding
  change invalidates only tiles with a texture using that default. Each map
  also offers an encoding override: R8/R16/BC4 for
  the selected data channel, BC5 for normals, and automatic/BC7/RGBA8.
  M8 remains open for its other authoring and round-trip limitations.
- World Tile's material editor offers a default-off, material-session-scoped
  automatic upgrade to terrain shader 2.1.0. It reports the upgrade, preserves
  unknown settings, and disables the opt-in when the legacy profile is chosen.
- World Tile 0.7.12 passed all 119 tests. Its 102-file ZIP matched the source
  bytes, passed extracted auto-upgrade and POM rendering tests, and exported
  four tiles from the relocated reference project.
- Mission completion is not claimed. A standalone core-PBR BC5 texture cannot
  retain its BC5 primary and also supply reconstructed RGB under the existing
  two-channel fallback contract; no standard expansion was authorized. Five
  simultaneous surfaces cannot be represented exactly by a four-layer primitive.
  Opaque extension references cannot be safely remapped without their schemas;
  unsupported extension locations remain incompletely preserved. Other platforms
  and dependency resolutions remain unverified. Open checklist items stay open.
- Blender retains unknown root-extension JSON across import, project reload,
  full-model and selected-object export, with a warning that opaque references
  cannot be remapped. Conflicting root data from multiple models is rejected.
- Imported object and bone nodes also retain unknown extension JSON. Unimported
  nodes cannot retain it; warnings disclose opaque references and data loss.
- Blender 1.24.41 passed all 36 build steps (2,149 reported cases, 10 skips).
  The ZIP matches all 49 packaged source files and passed extracted node, bone,
  and material regressions plus isolated installation and reactivation.
- Blender 1.24.40 was built after the root-extension change. All 36 build
  steps passed; the extracted package passed the new regression and an isolated
  install, disable, and re-enable check.
- Blender 1.24.39 passed all 36 build steps (2,148 reported cases, 10 skips).
  Its ZIP matches the implementation and passed packaged unknown-shader, ENUM,
  and R16 tests, plus isolated installation and reactivation.
- The World Tile suite passed 117 tests after the shared palette-grouping
  refactor. Version 0.7.11's extracted ZIP passed preview and relocated
  four-tile export tests. A pinned
  isolated runtime graph passed `pip-audit`; the repository does not lock every
  possible dependency resolution.
- The World Tile 3D view can inspect each quantized `COLOR_1` palette channel
  without loading textures. It uses the exporter's primitive palettes and
  warns that channel-to-surface assignments can differ between primitives.
- Blender imports unknown official shader versions using PBR fallback and
  retains their parameter values across project save, profile switches, and
  ADM export. Recognized texture references are remapped with their samplers
  and compatible GPU source bytes. Unknown schemas and opaque parameter
  references still cannot be validated or remapped; warnings disclose this.
  Custom shader versions no longer depend on the official-version enum.
- The World Tile layered preview packs equally sized scalar maps into float
  channels without resampling, keeping height in red for POM. Differently sized
  maps remain separate; the packed allocation is checked against the decoded
  texture budget before allocation. The portable reference's complete maps
  configure within a forced 16-unit budget, without dropping maps.
- World Tile version 0.7.7 candidate 12 passed ZIP integrity, packaged-code
  comparisons, packed and independent POM rendering, and full-map reference
  preview under a forced 16-unit budget. Its relocated project exported four
  validated ADM tiles. It remains a candidate while mission items are open.
- World Tile 0.7.8 candidate 13 also passed packaged `COLOR_1`, POM, and
  complete-reference preview regressions, and exported four relocated tiles.
  The packaged fixture renderer produced POM-on and POM-off images in `dist`.
- Blender `build.bat` produced version 1.24.38 after the 16-bit AUTO fix; all
  36 build steps passed. ZIP integrity and implementation comparisons passed;
  the extracted extension passed the bounded texture-format regression and an
  isolated installation could be enabled, disabled, and re-enabled.
- Blender add-on registration no longer reads materials inside Blender's
  restricted registration context. Existing shader parameter ownership is
  initialized on the first timer tick and on project load. Registration rolls
  back completed classes and handlers on failure.
- The Blender 1.24.35 ZIP passed the full build and an isolated installation
  and activation test. This fixes the registration incident; it does not close
  the remaining advanced-material mission items documented below.
- Blender retains unrecognized material-level extension JSON through ADM
  export and Blender project reload. Opaque references are not remapped;
  other unknown extension locations are not generally preserved.
- The subsequent Blender 1.24.36 build passed all 36 steps and its ZIP passed
  an isolated installation and activation test. This is not completion of the
  remaining advanced-material mission items.
- Blender exports a separate reconstructed RGB core-PBR normal if a shader
  parameter retains the same BC5 source bytes. The shader's BC5 primary and
  two-channel fallback remain intact. A core-only BC5 source still retains its
  original two-channel fallback and warns about portable-reader limitations.
- The Blender 1.24.37 build and isolated installation passed. Bounded BC5 and
  height regressions also passed against the packaged implementation.
- Blender's automatic DDS/KTX2 conversion now keeps 16-bit PNG data when R16
  cannot represent all source channels. Explicit 8-bit compression still
  converts with a warning and a 16-bit fallback.
- World Tile now retains unrecognized `terrain_shader` settings as opaque
  project data, includes them in the material fingerprint, and rejects
  validation, build, and export rather than silently dropping them. Opaque
  internal references are not interpreted or remapped. Unsupported profile
  and parallax values stay visible in the editor; changing an unrelated
  global or surface control no longer rounds or clamps other shader values.
- Blender preserves optional `ADM_material_height_v1` material data and its
  texture and sampler across ADM export and Blender project reload. It warns
  that its preview does not apply the effect and rejects the required extension.
  Height-only parallax exports tangents for the height UV set; conflicting
  normal and height UV sets require a separate reader-derived height frame.
  Unknown optional fields and nested extension data are retained without
  remapping their internal references, with an export warning. The bounded
  regression passed on Blender 5.2.3.
- Blender also exports tangents for active layered-shader parallax without a
  core normal map, using the height layer's UV set. Different active tangent
  UV sets produce a warning because one exported tangent frame cannot represent
  them all. A mirrored-UV regression verifies the tangent direction.
- A core normal map using UV 1 now also exports tangents from that UV set;
  the mirrored-UV regression reproduced the prior mismatch and passed after
  the fix.
- The post-fix check-only build passed all 34 steps, with 2,145 reported
  passing cases and 10 external-asset skips. The corrected Blender candidate
  passed packaged height, BC5, and texture-format regressions.
- The relocated four-tile World Tile candidate has measured texture
  preparation, unchanged detection, selected and all-tile exports, process
  working set, preview time, and an explicitly limited GPU base-level
  estimate. Workloads and results are recorded in `TESTS.md`.
- A subsequent check-only build passed all 34 steps, with 2,145 reported
  passing cases and 10 external-asset skips after the unknown-height-field
  change. The World Tile suite passed 111 tests. The build did not produce a
  release ZIP.
- Blender warns on import and export when a model declares unrecognized
  optional extensions. The warning survives project reload and selected-object
  export. Unknown extensions outside material-level data can still be lost;
  the warning does not claim general round-trip
  support.
- The check-only build also passed after the persistent-warning change:
  34 steps, 2,145 reported passing cases, and 10 external-asset skips.
- A non-release World Tile candidate rebuilt after the validator change passed
  ZIP integrity, exported all four relocated reference tiles, rendered the POM
  comparison, and loaded and closed the offscreen GUI with a checker active.
  Candidate 10 includes the opaque-settings and granular surface-edit fixes.
  Its relocated project exported four tiles and its GUI preserved precise
  values and opaque settings. The candidates are not releases.
- A non-release Blender 1.24.33 candidate including the core-normal tangent
  fix passed ZIP integrity and packaged material-height, BC5, and texture-format
  regressions on Windows. The final version bump, release ZIP, and
  other-platform verification remain open.
- Blender now retains a raw `(R,G,0,1)` fallback when directly opening a BC5
  normal, while its editable preview reconstructs Z. Explicit BC4/BC5 conversion
  also clears missing fallback channels. Core-only BC5 export warns that portable
  readers might display the two-channel fallback incorrectly; this warning does
  not resolve the single-texture fallback conflict described below.
- The standalone ADM reference was regenerated with the corrected fallback.
  Its fixture-specific VTK renderer reconstructs BC5 normals from that fallback
  for visualization. Regression checks inspect the fallback channels and render
  POM on and off.
- `tools/build_world_tile.py` builds a reproducible standalone ZIP from tracked
  runtime files and the generated reference ADM without overwriting an existing
  archive. It does not test or bump versions. An extracted non-release candidate
  exports all four prebuilt tiles and renders the corrected reference scene.
- An offscreen Windows GUI process failed during immediate close while an export
  change-check thread was active. Closing now defers until its Qt `finished`
  signal is processed, cancels pending checks, and stops window timers. A gated
  worker regression and immediate-close test of an extracted candidate both
  returned exit 0; the latter loaded four tiles with three LODs.
- The World Tile GUI dependency constraints exclude the audited vulnerable
  `certifi` and `urllib3` versions. A patched isolated runtime graph passed
  `pip-audit`; dependencies are not locked, so other resolutions remain
  unverified. The shared Python environment was not modified.
- Custom shader ENUM definitions and values now survive ADM import/export and
  Blender save/reload, including Unicode and reordering. Imports reject an
  existing conflicting parameter names, types, ENUM values, numeric or boolean
  defaults, texture defaults, and shader or parameter descriptions and author
  metadata instead of silently reinterpreting or discarding values. The
  exporter preserves whitespace in nonempty descriptions and author strings.
  Their editor accepts explicit string values and reports values outside the
  definition. An isolated Blender regression passed on Blender 5.2.3.
- Multi-surface CPU height blending and AO sampling now use the same
  precision-preserving scalar decoder as the VTK shader path. A focused R16
  test distinguishes adjacent 16-bit values in height-derived weights.
- World Tile converts 16-bit grayscale TIFF material maps to 16-bit PNG rather
  than truncating them to 8 bits. The preview and R16 DDS export retain their
  sample values; this fixes an authoring path distinct from R16 GPU passthrough.
- The generated ADM reference now embeds original procedural R8, R16, BC4,
  BC5 and BC7 textures; its Blender import/export regression compares their
  complete source bytes. A fixture-specific VTK visualization reads the ADM and
  renders actual POM; Blender's own material preview still does not render it.
- An exported-geometry test now evaluates interpolated two-surface height
  blend weights along shared irregular-tile edges at mixed LODs. This checks
  reference math, not actual terrain fragment rendering or >4-surface seams.
- An offscreen VTK test now renders two exported, sloped irregular tiles at
  different LODs using their exported UVs, per-vertex weights, shader settings,
  and texture fallbacks. At the sampled edge it detects POM offsets, checks
  pixel continuity and verifies invariance under a swapped layer palette.
  Weights vary along the edge due to biome noise and a shared-surface biome
  transition. Additional cases use curved terrain and a disjoint four-surface
  biome transition with nonzero weights for all four surfaces on the edge.
  A separate five-surface synthetic case demonstrates a visible seam.
- An exploratory VTK script loaded the generated ADM scene's geometry and
  texture fallbacks, then rendered its layers with the preview shader. Toggling
  parallax scales changed 48,493 color-channel samples by more than five
  8-bit levels. The script assumes this fixture's constant weights and other
  defaults, and its image is too dark for a useful comparison; it is not a
  complete or distributable reference renderer.
- The subsequent fixture-specific VTK tool validates its constant-weight,
  UV, mask and vertex-control assumptions and explicitly rejects unsupported
  shader parameters. A generated ADM scene rendered with POM on and off differs
  at more than 500 color-channel samples. The tool uses embedded PNG fallbacks
  and is not a general ADM or independent conformance renderer.
- Blender profile synchronization retains parameters excluded by the selected
  schema as inactive project data and restores them on a return to the same
  shader when their saved types match. ADM exports include only parameters
  supported by the selected profile and warn about inactive overrides.
  The regression switches through a legacy profile and saves/reopens the project
  before checking restored ENUM, numeric and image values. Registration and
  project loading infer metadata for existing official or unambiguous custom
  definitions; unknown or conflicting definitions remain unverified.

## Baseline
- Workspace HEAD at intake: `84ea70eae8b5b48f02d1ef41e66c8719a5259de9`.
- Workspace was clean at intake. No `.ai/` directory existed.
- The exact user-provided mission is persisted in `.ai/MISSION.md`.
- The request spans the ADM standard, shared texture codecs, shader profiles,
  World Tile, ADM authoring, Blender, other consumers, fixtures, and docs.
- Existing repository evidence includes frozen shader registry governance and
  working World Tile biome surface noise / terrain-material workflows.

## Current milestone
The mission remains incomplete. Blender shader ENUM recursion is fixed and its
focused tests pass. World Tile's material previews, opt-in detailed terrain
view, and fixture-specific ADM visualization render POM. The fast terrain
material mode remains a CPU bake. Open work includes the standalone BC5
core-PBR fallback conflict, distributed codec verification, and the final build.
A check-only build passed with documented external-asset skips;
final distribution packaging remains blocked by the open mission work.
See `TASKS.md` and `TESTS.md` for current evidence.
- The reference project's prebuilt tile manifest now uses relative heightmap
  paths. A relocation regression loads and exports all four prebuilt tiles
  before rebuilding, then rebuilds and exports them again.
- A non-release standalone World Tile candidate includes the shared ADM core,
  preview renderer and reference assets. The CLI exported its relocated
  prebuilt sample without rebuilding; final packaging remains outstanding.
- The reference folder now contains a generated standalone advanced ADM scene.
  The fixture-specific renderer displays measurable POM in that file without
  requiring Blender; the fixture catalog and instructions identify it.
- World Tile now uses a separate reconstructed RGB PNG as its core PBR normal
  for BC5 sources. Its layer shader retains the byte-identical BC5 primary and
  the specified two-channel PNG fallback. Export index version 4 invalidates
  prior tile digests. Embedded and external cases pass. Blender's standalone
  core-PBR BC5 case remains unresolved: its single normal texture must retain
  the primary, but the current fallback rule requires blue zero.
- An earlier complete World Tile run passed 107 tests with five PyVista future
  warnings; an independent BC5 reconstruction-formula assertion passed separately.
  The latest check-only build passed after its import-transaction fixture was
  updated for shader metadata conflict detection. No release ZIP was built.
- The detailed terrain view now groups built tile triangles using the exporter's
  four-layer palette policy and renders interpolated weights with the VTK shader.
  Focused GUI/offscreen tests demonstrate single-layer POM, two-layer height
  blending, asynchronous loading and explicit incompatible-material errors.
  Its 250,000-triangle limit preserves the fast large-terrain modes.
- Detailed terrain actors share decoded texture objects across palettes during
  each redraw. A subsequent redraw rebuilds the cache, so edits are not hidden.
  A gated multi-tile test confirms stale selection and LOD loads are discarded.
  Unique decoded texture base levels are limited to 512 MiB per redraw; the
  limit excludes transient allocations, renderer overhead and GPU mipmaps.
- World Tile texture pickers display verified source dimensions, format,
  depth, color-space metadata and mip count, plus a GPU payload size or a
  clearly labelled RGBA base-level estimate. Invalid files report a reason.
- The multi-surface preview exposes per-layer shader diagnostics for base
  weight, final weight and signed parallax offset. Its displayed mean weights
  remain unshifted CPU estimates.
- World Tile now rejects color-space mismatches for supported DDS primaries,
  as it already did for KTX2, rather than silently recompressing them. Inputs
  outside the ADM GPU subset still follow the documented conversion path.

## Work log
- 2026-11-26: Audited mission outline and repository status. Copied the supplied
  mission snapshot exactly and created the checklist, state, decisions, and test
  records. Inspected referenced World Tile history, GPU texture subset, shader
  registry generation/freeze governance, Blender consumer and test layout.
- 2026-11-26: Added version-2 KTX2/DDS format identifiers and parser coverage for
  R8, R16, BC4, BC5 and BC7 UNORM/sRGB; added a renderer-neutral AO/height/blend/
  parallax math module and tests.
- 2026-11-26: Added opt-in World Tile AO/height/emission/parallax data fields,
  AWTP v5 and preset v3 serialization, texture collection, advanced fingerprint
  handling, and an export guard that prevents silent data loss. Added project,
  preset, math and format parser tests.
- 2026-11-26: Updated normative texture format text and changelog. Full codecs,
  shader profiles, extension schema, authoring, rendering and supported export
  are still not implemented.
- 2026-11-26: Added the normative `ADM_material_height_v1` contract and
  validator checks for its texture/UV reference, version, channels, bounds,
  parallax mode and POM steps. Added World Tile UI controls for per-surface AO,
  height, emission and parallax plus global height-blend/POM settings. The
  World Tile UI now applies albedo, normal, ORM and emission maps in its VTK
  material preview and offers direct albedo/normal/AO/roughness/metallic/height/
  emission inspection. Parallax/POM and cross-layer height blending remain
  clearly unsupported in that preview. The World Tile suite passes (52 tests);
  ADM math/texture/validator tests pass (23 tests), including the R16 KTX2
  two-byte `typeSize` constraint. A broad Blender test
  discovery is unavailable outside Blender because 18 Blender-only modules
  require `bpy`/`bmesh`; core tests still run in regular Python.
- 2026-11-26: Added a separate interactive 2–4-layer World Tile preview with
  editable base weights, classic/height blending, transition and strength,
  per-layer final-weight views, trackball camera, and selectable light presets.
  Its CPU reference composition keeps base-zero layers at zero and reports
  mean final weights; AO, normal, emission, and parallax are explicitly not
  represented in this preview.
- 2026-11-26: Implemented lossless R8/R16 scalar KTX2/DDS encode/decode and
  16-bit-preserving scalar mip generation, plus BC4/BC5 encoding and decoding
  with vector-filtered BC5 normal mips. BC7 encoding uses valid mode-6 blocks;
  decoding uses the declared `texture2ddecoder` package when available.
  Added format-derived solid-block tests and optional independent decoder
  comparisons plus an overlapping-mip rejection check. 30 core math and texture
  tests pass when that declared dependency is available; KTX-Software
  independently validates generated R8/R16/BC4/BC5/BC7 KTX2 files and all
  version-2 format fixtures. AWT's declared
  decoder matched BC4/BC5 pixels exactly on an odd-size fixture and was used to
  verify BC7 decode results.
- 2026-11-26: World Tile now preserves compatible R8/R16/BC4 scalar DDS/KTX2
  bytes and writes value-preserving 8-bit or 16-bit PNG fallbacks. A 16-bit
  grayscale PNG exports as R16 DDS without precision loss. KTX2 inputs share
  the existing GPU texture size limit. Focused R16 tests pass; the combined
  codec, material-math, and World Tile export suites pass (48 tests).
- 2026-11-26: Added the exact layered-height profiles
  `adm.terrain.four_layer@1.1.0`, `adm.terrain.four_layer@2.1.0`,
  `adm.surface.two_layer@1.1.0`, and `adm.pbr.layered@2.1.0`. Their generated
  registry entries, typed ENUM parameters, parameter bounds, UV/color-space
  validation, AO/height/POM contract, PBR fallback, and development revision
  record pass the registry, governance, and validator tests. Existing
  1.0.0/2.0.0 profile schemas remain unchanged.
- 2026-11-26: The generated shader registry now carries the layered-height
  capability per exact profile identity, alongside the shared parameter
  defaults, types, bounds, and texture roles. The generator is deterministic
  and its check, registry tests, development governance check, and shared
  renderer-neutral math tests pass.
- 2026-11-26: World Tile now exports the explicitly selected
  `adm.terrain.four_layer@2.1.0` profile, including per-layer AO, height,
  emission, height blending, parallax/POM and portable PBR fallback fields.
  Advanced settings remain guarded when profile 2.0.0 is selected. Active
  parallax writes tangents even without normal maps; material-only changes
  remain separate from terrain-rule and vertex-weight rebuilds. The material
  editor exposes the explicit profile selection. Updated export documentation,
  layered emission color-space handling, and registry revision metadata. World
  Tile tests: 57 run, 40 passed, 17 skipped; GPU texture/shader validator tests:
  23 passed; material math tests: 8 passed; registry check and Python compile
  passed. The governance tool could not compare against the supplied base
  commit because that revision is unavailable in this checkout.
- 2026-11-26: Completed deterministic material-set import. The importer scans
  recursively with entry and byte limits, validates texture content and
  dimensions, skips symbolic links, makes conflicts explicit, and never assigns
  packed or unknown maps. The editor previews missing/conflicting maps, supports
  configurable suffixes and optional updates that preserve missing maps, and
  adds new surfaces without assigning them to biomes. Updated the World Tile
  guide and added coverage for entry caps, root containment, and TIFF/TGA files.
  The full World Tile suite passes 66 tests with GUI dependencies installed;
  core GPU texture and material math tests pass 31 tests. Shader registry
  integrity and governance tests pass, while development comparison against
  the unavailable base revision is skipped. Texture reads enforce the file
  size cap even if the file grows after its initial stat check.
- 2026-11-26: Confirmed that M8 cannot be implemented from this checkout:
  repository inspection found no standalone ADM Editor source or application.
  The documented ADM tools are the Blender add-on and World Tile editor.
  Recorded the blocker rather than creating an unrequested third editor, and
  continued with the independent Blender milestone.

## Blockers
- No external blocker has been established for the remaining mission work.
- Mission completion remains blocked by the open implementation and verification
  work in `TASKS.md`; a passing check-only build is not a release.

## 2026-11-26 ENUM diagnosis
- The `value_enum` items callback read `self.value_enum`, recursively invoking
  itself; repeated `RecursionError` and RNA warnings caused sustained CPU use
  and uncontrolled output. An isolated process was stopped after a timeout.
- Dynamic ENUM items now retain their strings and explicit stable numeric values.
  Unknown stored integers remain visibly invalid rather than being reinterpreted.
  Shader-switch callbacks guard nested rebuilds, and advanced texture imports
  restore linear data texture color spaces.
- Four advanced profile import/export scenarios, all 47 isolated profile
  scenarios, the full profile test, the Blender project save/load enum test,
  and a Cycles height-blending bake passed in targeted runs. See `TESTS.md`.
- The prior checklist incorrectly marked missing preview and reference work as
  complete; those items have been reopened.
- The subsequent bounded check-only build completed successfully (30 steps,
  2,070 reported passing cases, 10 skips, Blender 5.2.3 LTS). The preview
  test completed in 122.6 seconds. Blender still emitted dependency-cycle
  diagnostics, retained in the test logs; these are not claimed as resolved.
- World Tile's multi-surface preview now approximates weighted per-layer AO by
  darkening the composed color, honoring map channel, inversion and strength.
  At that point, normal, emission, parallax and POM were unsupported.
- Corrected single-surface ORM packing: absent roughness and metallic maps use
  neutral channels, so the renderer applies each scalar factor once instead of
  squaring it when another ORM map is present.
- Blender's texture-slot loader decodes R16 DDS and KTX2 into a packed float
  image. PNG export retains 16-bit samples for those sources and for edited
  16-bit PNGs. AUTO GPU export preserves unmodified scalar channel layouts as
  R16; other 16-bit GPU conversions warn and retain a 16-bit PNG fallback.
- World Tile's single-surface normal map now has generated mesh tangents for
  sphere, plane and relief. VTK requires those tangents to apply normal mapping.
- World Tile's multi-surface preview now blends color in linear space and
  composites normal, metallic, roughness, and emission maps into PBR textures.
  It uses the final height-adjusted weights; parallax and POM remain unsupported.
- Single-surface albedo tint now also uses linear-space multiplication; the AO
  inspection view applies the same neutral-at-zero strength as the PBR preview.
- A later check-only build passed 31 steps, but ran while further changes were
  being made. Repeat the final verification on a stable worktree after the
  remaining mission requirements are implemented.
- The advanced comparison-scene generator now emits a validated ADM alongside
  its Blender project. It includes classic and height blending, AO maps, and
  parallax/POM settings for all four advanced profiles. It is not the complete
  GPU-format or POM-rendering fixture required by the mission.
- Blender's BC7 KTX2 loader now repackages its validated blocks into a temporary
  DDS and uses Blender's native decoder. A built extension decoded a BC7 texture
  without an external wheel on Windows; other platforms remain unverified.
- World Tile builds now record per-LOD surface usage. Export Changed fingerprints
  only surfaces used by each tile, and validates usage metadata against geometry
  when exporting. Older manifests retain conservative whole-material detection.
- KTX2 inputs previously failed in World Tile's material fingerprint and preview,
  even though direct export accepted them. Compatible DDS/KTX2 sources now decode
  for preview; fingerprints hash complete source bytes, including mip levels.
  Scalar GPU PNG fallbacks now use `(R, 0, 0, 1)` with 16-bit R16 samples.
  World Tile reconstructs BC5 normal Z in both surface and blended previews.
- The relocated four-tile World Tile reference project now exports referenced
  R8, R16, BC4, BC5, and BC7 sources. Its generator reproduces the five GPU
  source files byte-for-byte. This does not complete the separate advanced
  Blender scene.
- A shared-edge numerical diagnostic confirms an existing >4-surface seam:
  neighbouring triangles select different four-surface sets. With equal shared
  weights and one high layer, reference height blending assigns that layer
  0.9479 on one side and omits it on the other. The exporter reports the
  affected-triangle count; the geometry and selection behavior are unchanged.
- Blender's ADM importer now reconstructs BC5 normal Z for core PBR and official
  shader normal parameters without changing data-role uses of the same texture.
  External GPU primaries are size-limited and integrity-checked; unreadable or
  invalid sources produce an explicit warning. Source GPU bytes are still not
  retained through Blender's fallback-based ADM re-export.
- Real DDS textures from the local, gitignored `test_files` library were scanned,
  exported by World Tile and imported into Blender. A 16-by-16 bake initially
  appeared spatially uniform: its 16 texture repeats aligned with the sample grid.
  At 64-by-64, the real normal map varies across pixels. These user-provided
  textures are not included in the repository fixtures or distribution.
- The Blender material panel now exposes the existing texture loader for PBR
  slots and shader texture parameters. Official BC5 normal parameters reconstruct
  Z; custom shader parameters retain raw channels because they have no declared
  normal role. GPU authoring input has byte and decoded-pixel limits, and DDS
  and KTX2 parsing rejects impossible mip counts before creating level lists.
- A new exported-geometry regression checks periodic UV phase and reference
  height-blended weights at shared vertices across different LODs and partial
  edge tiles, with two surfaces and biome noise. It does not establish continuity
  at every interpolated fragment or resolve the known over-four-surface case.
- The World Tile single-surface preview now configures per-fragment parallax and
  POM with a dedicated view-space varying, including render passes that omit
  VTK's `vertexVC`. A rendered gradient agrees with reference offsets in a
  controlled plane test; frontal views and inverted heights are covered.
  R16 DDS/KTX2 height samples retain 16-bit precision when sent to the shader.
  Multi-surface POM, other VTK versions, and all material-map combinations
  remain unverified or unimplemented.
- The reference AWTP project now contains local copies of its procedural PNG
  textures. A test copies only the project folder to an unrelated location,
  builds four tiles and exports them with all five GPU texture formats.
- Blender now packs validated GPU primaries alongside their preview images and
  retains them by default when pixels and texture role are unchanged. Edits
  invalidate the stored primary even after the image is repacked. Explicit PNG
  or GPU-format export still converts. Isolated tests cover R8, R16, BC4, BC5
  and BC7 in DDS/KTX2, BC7 sRGB, external-source integrity, mip bytes, and
  save/reload; they do not establish cross-platform BC7 decoding.
- The multi-surface final-material view now samples layer maps independently in
  VTK and computes per-layer parallax/POM and height blending. Offscreen tests
  compare rendered offsets and height-blend output against reference math and
  exercise lit emission and normal maps. Weight diagnostics remain unshifted
  CPU estimates, hardware texture-unit limits can prevent configuration, and
  terrain-tile fragment seams and VTK versions other than 9.7.2 remain open.
