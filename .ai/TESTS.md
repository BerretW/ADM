# Mission verification record

## Completed so far
- The latest complete World Tile run with isolated Pillow 13 passed 89 tests,
  including the rendered planar POM seam regression.
- A limited `pip-audit` of the installed World Tile dependency versions found
  76 advisory entries for Pillow 11.3.0. The dependency now requires Pillow
  13.0.0, and all 88 World Tile tests passed with Pillow 13 installed in an
  isolated session directory. The audited version list, including an isolated
  tifffile installation, then had no known advisories. This is not a complete
  lockfile audit: the project does not provide a dependency lockfile, and the
  shared system Python still has Pillow 11.3.0 installed.
- Current `build.bat -CheckOnly`: all 33 listed steps passed on Blender 5.2.3.
  External-asset cases were skipped where files, rights, or a binding target
  were unavailable. The report records a dirty worktree and is not a release.
  Shader-profile and ENUM logs contain no enum mismatch or recursion warnings.
- World Tile's full suite passed 88 tests. Shared GPU codec and material math
  tests passed 35 tests. `git diff --check` passed with a CRLF notice.
- The first current check-only build exposed a stale fallback image identity
  assertion. The corrected fixture checks equal decoded pixels, per-texture
  identity, and original primary bytes; it passed before the successful build.
- A subsequent check-only build also passed after adding custom shader
  parameter-name/type conflict rejection. The World Tile suite is run
  separately from that build.
- A later check-only build passed after adding matching and conflicting numeric,
  boolean and texture-default checks, including altered texture pixels.
- Blender `test_shader_enums_blender.py`: isolated run passed with a custom
  ENUM exported, saved, reopened, imported into a scene without its definition,
  and re-exported after reordering. An incompatible existing definition is
  rejected explicitly. The regression also checks an invalid definition.
- Ten targeted World Tile multi-surface and parallax tests passed, including
  a CPU height-blend regression that distinguishes R16 values 32768 and
  32769 and rendered VTK parallax/POM comparisons.
- The complete World Tile suite passed 87 tests before the four-layer test was
  added. A separate offscreen perspective-camera test then rendered four layers
  with all seven map types, differing resolutions, inversion, scale and bias;
  it verified visible POM and explicit rejection at a 16-unit texture budget.
  The local VTK context reported at least 32 units.
- Blender's complete shader-profile test passed after the custom ENUM UI fix,
  exercising the legacy and advanced profiles in a bounded process.
- The advanced reference ADM scene passed a bounded Blender round trip with
  all five procedural GPU formats. Complete source blobs match before and after
  import/export. POM is retained as metadata, not rendered in Blender.
- An exported two-surface fixture compares interpolated UVs and height-adjusted
  weights at three positions on overlapping tile edges, including mixed LODs.
  This is a reference-math check, not a rendered-fragment seam test.
- A separate offscreen VTK test compares POM pixels at an irregular planar
  preview-tile seam against an unbroken plane. The adjacent meshes have different
  density and reversed layer slots, with distinct repeats and height maps. It
  also confirms a measurable POM difference when scales are disabled. The test
  uses constant weights; it does not render exported terrain or cover >4 layers.
- An exploratory VTK render loaded the generated ADM scene and compared its
  material preview with authored versus zero parallax scales. It changed 48,493
  8-bit color-channel samples by more than five levels, but hard-coded this
  fixture's layer weights and defaults and produced a dark image. It does not
  establish a complete reference renderer or a shippable visual fixture.
- A later bounded end-to-end test generates the ADM scene in Blender, runs the
  fixture-specific VTK visualization with and without POM in separate processes,
  and checks that more than 500 color-channel samples change by over five
  8-bit levels. The test passed. The tool uses fixture-specific assumptions and
  PNG fallbacks, not an independent or general-purpose ADM renderer.
- Offscreen VTK 9.7.2 tests compare two independent layer offsets and height
  blending with the shared reference math, and render parallax-shifted normal
  and emission maps in a lit PBR pass. Both lit and unlit passes cover the
  view-space matrix declaration. 16-bit RGBA PNG fallbacks retain scalar
  precision in the preview path.
- Blender `test_texture_formats.py` and `test_bc5_normal_import_blender.py`:
  isolated, bounded runs pass for unmodified R8/R16/BC4/BC5/BC7 DDS and KTX2
  source bytes, mip chains, color/data roles, R16 and BC5 save/reload, and
  edited-then-repacked images. `test_material_slots.py` and
  `test_import_transaction_blender.py` also pass. Test logs still contain
  existing Blender dependency-cycle and KTX2 decoder diagnostics.
- World Tile full unittest discovery: **84 passed**. A separate offscreen VTK
  plane test compares single-step and POM rendered gradient offsets with the
  shared reference math at an oblique angle, checks a frontal angle and inverted
  height, and verifies R16 DDS/KTX2 height samples. The relocated AWTP test
  copies only its project directory, builds four tiles and exports all five
  referenced GPU formats. This does not verify multi-layer POM or fragment
  continuity across terrain seams.
- `adm_blender.tests.test_material_math`: eight tests cover channel selection,
  AO, height-blend invariants and order, invalid inputs, and parallax/POM math.
- `adm_blender.tests.test_gputex` covers version-2 KTX2/DDS headers and odd-size
  payloads; lossless R8/R16 and scalar mips; BC4/BC5 encoding, decoding and
  normal mips; format-derived solid-block vectors; and an optional independent
  `texture2ddecoder` comparison.
- Focused World Tile tests cover material round-trip, fingerprint separation,
  AWTP v5/legacy defaults, preset v3 copying, explicit advanced-profile export,
  and non-silent rejection when the legacy target is selected.
- Earlier `appartus_world_tile` full `unittest` discovery ran 54 tests, including
  advanced controls, PBR-map preview, multi-layer height blending, diagnostics,
  seam/LOD, and render tests.
- `adm_blender.tests.test_gputex` plus `adm_blender.tests.test_material_math`:
  30 tests pass with `texture2ddecoder` available; without it, 28 pass and the
  two independent-decoder tests skip explicitly.
- KTX-Software `ktx validate --warnings-as-errors` accepts generated R8, R16,
  BC4, and BC5 KTX2 files. Its CLI cannot decode the tested BC4/BC5 files for
  image extraction; `texture2ddecoder` independently matched our BC4/BC5
  decoder exactly on a 53x37 fixture and matched BC7 decoding on DDS and KTX2
  blocks.
- KTX2 parsing rejects overlapping mip payloads; the targeted regression test
  passes.
- Earlier combined core codec, renderer-neutral material-math, and World Tile
  export suites passed: **48 passed**. Coverage includes byte-preserving R8/R16/BC4
  DDS/KTX2 inputs, exact R16 PNG fallback values, and 16-bit PNG-to-R16 DDS
  conversion.
- Advanced World Tile export coverage verifies explicit 2.1.0 selection,
  AO/height/emission map references and settings, PBR fallback diagnostics,
  and tangent generation for parallax without normal maps. The World Tile suite
  runs 57 tests (40 pass, 17 skip); GPU texture/shader validation runs 23 tests;
  shared material math runs 8 tests.
- Earlier `adm-standard/tools/build_shader_registry.py --check`,
  `adm-standard/tools/test_shader_registry.py`, and shader governance comparison
  against base commit `84ea70eae8b5b48f02d1ef41e66c8719a5259de9` passed with 47
  registered shader profiles.
- Current registry generation and tests pass with 47 profiles. The governance
  tool reports that the base revision is unavailable in this checkout, so its
  development-change comparison is skipped; integrity and historical freeze
  checks pass.
- Latest complete World Tile run after installing the declared GUI dependencies:
  `python -m unittest discover -s tests` from `appartus_world_tile` — **66
  tests passed**. This includes the material-set importer, GUI controls, and
  preview tests. The material profile selector regression test verifies that
  selecting profile 2.1.0 updates the exported material model.
- Latest core run: `python -m unittest adm_blender.tests.test_gputex
  adm_blender.tests.test_material_math` — **31 tests passed**.
- Latest shader checks: registry generation check and the 47-profile registry
  and governance tests passed. Development comparison was skipped because the
  base commit is unavailable in this checkout.
- Latest changed-module `py_compile` and `git diff --check` passed. The
  registry check emitted a CRLF-to-LF warning for `registry.json`.
- The material-set dialog acceptance smoke test passes with a unique, new
  surface name; existing material surfaces are intentionally unchecked by
  default.
- M8 source discovery found no standalone ADM Editor project in the workspace.
  The approved implementation target is the existing ADM Blender plugin and
  Apparatus World Tile editor, not a new application.
- Full `adm_blender/tests` discovery cannot run under the system Python because
  18 Blender-only modules import `bpy`/`bmesh`; non-Blender unit tests in that
  discovery passed before those import failures.
- The World Tile export tests run under Python 3.14.7 after installing the
  project's declared `numba` and `texture2ddecoder` dependencies. Other Blender
  modules still require Blender's embedded `bpy`/`bmesh` runtime.

## Planned verification
- BC7 encoding, broader R16 fallback/export precision, and DDS external
  validation.
- Renderer-neutral shader-math tests for invariants and edge cases.
- World Tile unit, persistence, GUI, preview, export, and seam/LOD regressions.
- ADM editor serialization and preview/export integration.
- Blender node, round-trip, codec, and rendered/baked shader tests.
- Consumer-by-consumer compatibility checks and repository CI/build matrix.
- Dependency audit and validation of untrusted texture inputs.

## ENUM and build investigation, 2026-11-26
- Baseline `adm.terrain.four_layer@2.1.0` isolated test: stopped after the
  45-second bound; repeated recursion and RNA enum warnings occurred during
  configuration. The Blender process consumed CPU and did not reach export.
- Blender 5.2.3: 47 isolated profile scenarios completed; 46 passed initially.
  The remaining `adm.surface.two_layer@1.1.0` exposed an advanced-profile
  data-texture color-space bug. After repair, all four advanced profiles passed
  isolated import/export tests, including enum and texture color-space checks.
- Complete shader-profile test: passed in 30 seconds; enum save/load and repeated
  version-switch regression: passed; Cycles preview test: passed in 100 seconds.
  The bake measured `(0.01798621, 0, 0.98201376)` against the reference
  `(0.01798621, 0, 0.98201379)`. The tests emitted no enum mismatch or recursion
  warnings. Existing Blender dependency-cycle warnings remain.
- First check-only build: Python tests failed because the separate procedural
  reference generator was not included in the original fixture rebuild check.
  Both generators now have separate passing tests.
- Second check-only build was interrupted while printing preview dependency-cycle
  diagnostics. It passed Python, standard, shader registry, fixture, and Blender
  profile checks before interruption; it did not produce a final report.
- A subsequent `build.bat -CheckOnly` completed with exit 0: 30 steps passed,
  2,070 cases passed, 10 cases skipped, and none failed. The skipped external
  asset cases lacked local files or rights/binding approval. The shader profile
  and preview processes exited 0 in 31.2 and 122.6 seconds, respectively.
  Full dependency-cycle diagnostics remain in `dist/blender-test-logs/`.
- World Tile: 67 tests passed, including a reference project build producing four
  neighbouring tiles with three LODs and existing material texture paths.
  Core GPU-texture and material-math tests: 31 passed.
- The reference project also exported four ADM tiles with export validation
  enabled. A relocated copy of the project and its repository-relative
  advanced-material fixture tree also built and exported four validated tiles.
  The project folder alone is not self-contained.
- The advanced Blender scene generator saved a `.blend` successfully in a
  separate process (36.9 seconds, exit 0). Its first render was too dark to
  demonstrate the intended comparisons. Its packed procedural images contained
  black pixels because setting their color space after writing pixels reset the
  image. Setting color space first preserved test pixels across save/reload.
  The corrected scene regenerated (30.1 seconds), reopened, and rendered
  successfully (2.8 seconds). Creating vertex colors before the shader nodes
  made the classic/height comparison visible for all four profiles. The
  complete required reference ADM scene remains unverified.
- `test_advanced_scene_images_blender.py` passed in 2.4 seconds and is included
  in subsequent builds; it was added after the reported check-only build.
- The bounded runner terminated a test Blender child at a 0.1-second timeout,
  captured separate logs, and returned the expected exit code 124.
- Three targeted World Tile multi-surface preview tests passed, including AO
  channel, inversion, strength, missing-map and zero-weight behavior.
- After that change, the complete World Tile suite passed: 68 tests, no skips.
- Two focused single-surface material-preview tests passed after correcting the
  neutral ORM channels. The renderer's shader multiplies its ORM channels by
  the corresponding roughness and metallic uniforms.
- Blender texture-format tests passed with R16 DDS/KTX2 loading, project
  save/reload, 16-bit PNG ADM export/import, edited PNG export, R16 GPU
  primary/fallback round-trips, R16 mip values, repeated export after importing
  the PNG fallback, and a warning for 8-bit GPU conversion. Edited non-scalar
  channels do not get discarded by R16 conversion.
- World Tile normal-map regression passed: all three preview shapes have
  tangents, and a lit plane renders differently for flat and sideways normals.
- Layered PBR tests passed for weighted maps, inversion, zero-weight layers, and
  actual normal and emission rendering through the multi-surface preview.
- The complete World Tile suite passed 73 tests after the preview changes.
  Single-surface tests also verify linear-space albedo tint and neutral AO at
  zero strength.
- A later `build.bat -CheckOnly` completed with exit 0: 31 steps, 2,090
  reported passing cases and 10 external-asset skips. It ran while additional
  edits were being made, so the resulting report is not a frozen-worktree
  final build. Profile and enum logs contained no enum mismatch or recursion
  warnings; the shader profile log still reported dependency cycles.
- The generated advanced ADM scene passed a bounded Blender test (40.7 s):
  eight meshes and materials cover all four advanced profiles with classic
  and height blend, layer AO/height/normal, and parallax/POM metadata; import
  and validated re-export preserve the checked profile and parameter values.
  The test is included in subsequent builds. The scene does not yet exercise
  the required GPU formats or render parallax/POM.
- BC7 UNORM and sRGB KTX2 loads, odd dimensions, an unloaded file reference,
  and save/reload passed in Blender. DDS repackaging preserved every tested
  mip payload. One generated block in each of the eight BC7 modes decoded
  identically to `texture2ddecoder` on Blender 5.2.3 for Windows. An isolated
  extension ZIP built from the worktree also decoded BC7 without an external
  Python wheel; other platforms were not tested.
- World Tile's selective export regression checks per-LOD usage against PLY
  weights, tile-local material and AO texture changes, unused surfaces, global
  height settings, legacy manifests, and rejection of incorrect usage metadata.
  On the four-tile test fixture, a validated full export took 0.276 s; ten
  changed-only checks took a median 0.667 ms and a maximum 6.43 ms.
- Focused texture regressions verify KTX2 R16/BC7 preview decoding, exact
  R16 export and scalar fallback channels, mip-only Export Changed detection,
  16-bit preview normalization, grayscale source channel remapping, and BC5
  normal reconstruction for DDS/KTX2.
  Blender BC5 normal reconstruction is covered separately below.
- The World Tile suite passed 81 tests, including the relocated reference project,
  which built and exported four validated ADM tiles whose referenced
  primary images include R8, R16, BC4, BC5, and BC7. Two generator runs
  produced identical hashes for the five GPU source textures.
- A synthetic shared-edge diagnostic with five equally weighted surfaces and
  different third-corner weights produced slot sets `[0,1,2,3]` and `[1,2,3,4]`.
  The reference height-blend output assigns surface 0 weight 0.9479 on the
  first side and zero on the second. Both triangles report a surface conflict;
  final cross-primitive visual continuity is therefore not verified.
- A focused regression checks that two primitive slot layouts produce identical
  reference height-blend weights for the same two nonzero surface weights.
- A bounded Blender process passed BC5 DDS embedded and BC5 KTX2 external
  import, shared data/normal texture use, Cycles layered-normal bake, ADM
  re-export/import and `.blend` save/reload. An external primary with a
  mismatched SHA-256 produced the expected warning. Existing dependency-cycle
  diagnostics were still emitted.
- Another check-only build returned exit 0 while World Tile changes were in
  progress; it is not final frozen-worktree evidence.
- Real-texture diagnostic: `big_road_mud_01` from local `test_files` produced
  four validated World Tile ADM exports. Blender imported the textures and baked
  the layered normal. A 16-by-16 bake was spatially constant at 16 repeats per
  tile; after evaluating the UV drivers and increasing the bake to 64-by-64,
  RGB peak-to-peak ranges were approximately `(0.244, 0.501, 0.105)`.
  This diagnoses sampling aliasing in the small bake, not POM rendering.
- The Blender BC5 regression passed in a bounded process after adding PBR and
  shader-parameter DDS/KTX2 opening, custom raw-channel behavior, missing-file
  reporting, input size limits, save/reload and ADM import/export checks.
  Dependency-cycle diagnostics remain. The Blender texture-format suite and
  material-slot suite also passed in separate bounded processes.
- GPU codec and material-math tests: 34 passed, including rejection of an
  impossible DDS mip count. The complete World Tile suite passed 82 tests.
  The new seam check compares reference height-blend output and UV phase at
  shared vertices for two surfaces, biome noise, partial edge tiles and mixed
  LODs; it does not prove interpolated-fragment or over-four-surface continuity.
