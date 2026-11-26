# Mission state

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
  Normal, emission, parallax and POM remain unsupported in this preview.
