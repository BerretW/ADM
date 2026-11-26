# Mission state

- Custom shader ENUM definitions and values now survive ADM import/export and
  Blender save/reload, including Unicode and reordering. Imports reject an
  existing conflicting parameter names, types, ENUM values, numeric or boolean
  defaults, and texture defaults instead of silently reinterpreting or
  discarding values.
  Their editor accepts explicit string values and reports values outside the
  definition. An isolated Blender regression passed on Blender 5.2.3.
- Multi-surface CPU height blending and AO sampling now use the same
  precision-preserving scalar decoder as the VTK shader path. A focused R16
  test distinguishes adjacent 16-bit values in height-derived weights.
- The generated ADM reference now embeds original procedural R8, R16, BC4,
  BC5 and BC7 textures; its Blender import/export regression compares their
  complete source bytes. A fixture-specific VTK visualization reads the ADM and
  renders actual POM; Blender's own material preview still does not render it.
- An exported-geometry test now evaluates interpolated two-surface height
  blend weights along shared irregular-tile edges at mixed LODs. This checks
  reference math, not actual terrain fragment rendering or >4-surface seams.
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
focused tests pass. World Tile material/POM previews, advanced reference assets,
seam shader evaluation, distributed codec verification, and the final full build
remain open. A check-only build passed with documented external-asset skips;
final distribution packaging remains blocked by the open mission work.
See `TASKS.md` and `TESTS.md` for current evidence.

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
