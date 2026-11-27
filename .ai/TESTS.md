# Mission verification record

## Completed so far
- The World Tile suite passed 114 tests with five PyVista future warnings
  after adding opaque terrain-shader setting preservation and independent
  global and surface control updates. Regressions save and reopen the project, verify that
  unknown settings affect material fingerprints but not geometry rules, check
  that export fails before creating output, and verify unsupported selections
  and precise or out-of-range values survive unrelated GUI edits.
- World Tile candidate 9 passed ZIP integrity and byte comparisons for the
  changed material model, panel, and README. Its relocated project exported
  four tiles, and its extracted GUI preserved and rejected opaque settings.
  An initial GUI check failed because the test omitted the project base path
  while reconstructing relative texture paths; the corrected check passed.
  This candidate predates the granular surface-edit fix and is not a release.
- World Tile candidate 10 includes the granular surface-edit fix. ZIP
  integrity and byte comparisons passed; from an unrelated extracted folder,
  it exported four reference tiles and its GUI preserved precise surface and
  opaque shader values. It rejected validation of the opaque setting.
  This is not a release.
- A bounded Blender 5.2.3 regression passed for optional material-height
  import, GPU source bytes, sampler and unknown extension fields, height UV 1
  tangent direction, ADM export, project save/reload, mixed normal and height
  UV warnings, and side-effect-free rejection of the required extension.
  The interactive-material and BC5 bounded regressions also passed after the
  tangent change, with existing Blender dependency-cycle warnings.
- The same regression reproduced and then verified the fix for missing layered
  parallax tangents without a core normal map. It checks mirrored UV 1, a
  conflicting second height UV, and disabled parallax.
- The same mirrored-UV test reproduced and verified a core normal-map tangent
  fix: a non-interactive material using UV 1 now exports tangents for UV 1.
  The interactive-material regression also passed after this change.
- After the tangent fix, `build.bat -CheckOnly` passed all 34 steps: 2,145
  reported cases passed and 10 external-asset cases were skipped. This predates
  the later change allowing unknown optional height fields. It did not package
  or bump a version and does not verify a final distribution.
- After the unknown-field change, the height Blender regression and five
  GPU/material-height validator tests passed. A fresh check-only build passed
  34 steps, with 2,145 reported passing cases and 10 external-asset skips.
  The World Tile suite also passed 111 tests with five PyVista future warnings.
  The shader ENUM and profile logs contained no enum mismatch or recursion
  errors. Blender dependency-cycle warnings remain.
- The height regression confirms the unknown-extension warning and documents
  that an arbitrary unknown material extension is not preserved on export.
  The warning persists through project reload and selected-object export.
  Import-transaction and interactive-material Blender regressions also passed.
- After the persistent-warning changes, a fresh check-only build passed 34
  steps, with 2,145 reported passing cases and 10 external-asset skips.
- After the core-normal UV 1 tangent fix, another `build.bat -CheckOnly`
  passed 34 steps, with 2,145 reported passing cases and 10 external-asset
  skips. The report is `dist/qa-report-1.24.33.json`; this was not a release
  build.
- World Tile candidate 8 passed ZIP integrity, includes the updated shared
  validator and constants byte-for-byte, and exported all four prebuilt tiles
  from an unrelated extracted directory. Its POM on/off renders differ in
  82,594 color-channel samples by more than 5/255. Its offscreen GUI loaded
  four tiles and closed cleanly with an active change checker. It is not a
  release package.
- A Blender 1.24.33 candidate ZIP built from the current source passed integrity
  and byte comparisons for the modified implementation files. Bounded Blender
  5.2.3 tests loaded the extracted candidate and passed material-height,
  BC5, and texture-format regressions, including BC7 independent vectors and
  R16/GPU source-byte round trips. Test-only helpers were loaded from the
  checkout because the extension ZIP excludes tests. A subsequent candidate
  including the core normal UV 1 tangent fix passed the same packaged tests
  and byte comparisons. Neither candidate is a release.
- A `pip-audit` check of the installed World Tile GUI runtime dependency graph
  found advisories in `certifi` 2026.7.22 and `urllib3` 2.7.0. No direct
  World Tile HTTP use was found. The GUI dependency constraints now require
  `certifi` 2026.10.19 or later and `urllib3` 2.8.0 or later. An isolated
  overlay with 2026.11.20 and 2.8.0 passed the same audit. This checks one
  installed graph, not every allowed version: there is no committed Python
  dependency lockfile.
- On the extracted candidate, an offscreen Qt single-surface preview of the
  reference Rock surface took 871.9 ms for the first `set_surface` and event
  processing, then a median 110.2 ms and maximum 128.7 ms over five redraws.
  These are one Windows run with warm repeated inputs, not GPU timings or
  comparisons across workloads.
- Instrumenting that Rock preview counted 983,040 bytes in four NumPy texture
  base levels submitted to VTK, including its parallax height. This is a
  base-level footprint estimate, not a GPU allocation measurement; driver
  format expansion, mipmaps, intermediate copies, and renderer overhead are
  excluded.
- On the extracted World Tile candidate, a single Windows Python process
  measured the portable four-tile reference with one export thread. The three
  LODs contain 5,171, 4,547, and 3,091 triangles across all tiles. Five
  preparations of the 256x256, nine-mip Rock R16 DDS took 80.32, 66.33,
  66.57, 72.40, and 66.81 ms (median 66.81 ms). The first all-tile export
  took 2,216.81 ms; this includes first-use initialization and followed the
  texture preparation. Five unchanged checks took 14.02, 7.50, 7.53, 7.43,
  and 7.31 ms (median 7.50 ms) and found no changes. Three repeated
  selected-one-tile exports took 810.84, 748.98, and 748.15 ms (median
  748.98 ms); three repeated all-four-tile exports took 798.33, 790.70, and
  788.01 ms (median 790.70 ms). Each export prepares the material textures;
  timings use warm filesystem inputs and do not compare different scenes.
  Windows `GetProcessMemoryInfo` reported a 44,138,496-byte final working set
  and a 586,678,272-byte peak working set for the entire process, not per
  operation or GPU memory. Results are one machine and are not performance
  guarantees.
- The complete World Tile suite passed 111 tests with five PyVista future
  warnings using the isolated patched GUI dependencies. This includes the GUI
  shutdown, packaging, and bounded reference-normal decoding regressions.
- Blender 5.2.3 passed a bounded BC5 regression for direct DDS/KTX2 opening,
  source-byte preservation, raw fallback channels, explicit BC4/BC5 conversions,
  core-PBR compatibility warnings, Cycles bake, and ADM and Blender-project
  round trips. Existing dependency-cycle warnings remain.
- The regenerated reference ADM passed a fallback-channel check and a POM
  on/off render comparison. Before regeneration, the same channel check failed
  because the previous fallback stored reconstructed blue values.
- A complete World Tile run passed 108 tests with five PyVista future warnings
  after the reference correction. A subsequent standalone-package regression
  passed: two archives are byte-identical, required runtime and reference files
  match the checkout, and an existing destination is not overwritten.
- A ZIP made with the new packaging script passed integrity checks. From an
  unrelated extracted directory, the CLI exported four prebuilt tiles and the
  POM/no-POM renders differed in 82,594 color-channel samples by more than five
  8-bit levels. This is a candidate, not a release.
- The refreshed candidate with corrected GUI shutdown and dependency constraints
  passed ZIP integrity, exported four tiles from an unrelated extracted folder,
  rendered a POM comparison with 82,594 channel differences above 5/255, and
  exited cleanly after immediate GUI close with an active change checker.
  The candidate was rebuilt after adding the reference-normal decode limit and
  passed those same extracted CLI, rendering, and GUI checks.
- In an offscreen Windows GUI subprocess, the extracted candidate loaded the
  reference heightmap and four tiles with three LODs. Closing immediately
  afterward returned Windows status `0xC0000409` even though the recorded main
  worker, change checker, viewer loader, and viewer baker were not running.
  Waiting one second while processing Qt events before closing returned exit 0.
  At immediate close the material update timer was active; stopping all three
  main-window timers before closing did not prevent the native failure.
  The failure also occurred when the window was shown and closed through the
  Qt event loop. An empty window without the project exited normally.
  Diagnostic subprocesses that separately omitted the viewer shutdown, the
  surface-preview shutdown, or both still failed; this does not establish
  which component owns the native failure.
  Disabling the asynchronous export change check avoided the failure, whereas
  running the same calculation synchronously did not reproduce it. The window
  now defers closure until the checker's Qt `finished` signal is processed.
  A regression holds that checker open and confirms the event loop remains
  responsive until it finishes. An extracted corrected candidate loaded the
  four-tile project and closed immediately with the checker pending; exit 0.
- A later `build.bat -CheckOnly` returned exit 0: 33 test steps passed, with
  2,145 reported passing cases and 10 external-asset skips. It did not create
  release packages. The build ran while World Tile packaging and documentation
  were being edited, so it is not a frozen-worktree final release verification.
- Generated the bundled advanced ADM scene in a bounded Blender 5.2.3 process
  (exit 0, 34.5 s). A separate regression rendered the bundled file with POM on
  and off without Blender and verified a visible pixel difference.
- A refreshed 102-file candidate ZIP includes that ADM scene. From its
  extracted folder, the fixture renderer produced both comparison images;
  82,596 color-channel samples differed by more than five 8-bit levels.
  The reference catalog check passed. The archive is not a final release.
- World Tile BC5 normal regression: both embedded and external exports retain
  exact primary bytes and the specified two-channel PNG, while core PBR points
  to a separate reconstructed RGB PNG. The export and pipeline suites passed
  46 tests after this change.
- A bounded Blender 5.2.3 process imported and re-exported a World Tile ADM
  with BC5 in each layer. It retained the BC5 primary bytes and separate core
  RGB PNG bytes; exit 0 in 2.8 s. Blender reported 14 dependency cycles.
- A gated GUI regression changes the selected tiles, LOD, and preview mode
  while the initial load is in flight. The detailed view discards the stale
  result and loads the two requested tiles at LOD 2. In the headless Qt test
  context VTK reports zero texture units, so the preview uses its conservative
  16-unit limit; the test removes three map types to fit within that limit.
  The full reference material needs 24 units for one observed palette and
  reports a configuration error under the conservative limit.
- Four detailed-terrain and layered POM tests passed after texture sharing was added. The
  multi-tile test confirms repeated height maps are decoded once per redraw and
  the same VTK texture is bound to multiple palette actors. A lowered test
  budget produces an explicit error and removes partial actors. Python emitted
  PyVista object-finalization errors during interpreter shutdown after the run;
  the test process exited successfully.
- A non-release World Tile candidate ZIP contained 101 files including the
  shared ADM core, renderer and complete reference project. Its ZIP integrity
  check passed; the extracted CLI exported four prebuilt tiles from an unrelated
  directory without rebuilding. After BC5 and preview changes, a refreshed
  candidate also exported four tiles, and its GUI loaded the heightmap, four
  tiles and three LODs in an isolated offscreen process. This does not verify
  the final packages.
- On the relocated reference project, separate candidate CLI processes took
  2.473 s for one selected tile and 2.471 s for four tiles, including process
  startup and texture preparation. Their sampled Windows peak working sets were
  555.9 MiB and 556.0 MiB respectively. These are single runs with warm file and
  compilation caches, not a scalability comparison or GPU-memory measurement.
- Preparing the reference project's five GPU sources in a separate candidate
  process took 0.424 s. Their combined encoded mip payload was 480,663 bytes;
  that number excludes decoded copies, GPU allocation overhead, and textures
  outside those five sources.
- A focused cache regression verifies that the same file with different
  selected channels or inversion creates distinct textures, while identical
  sampling settings share one texture.
- Full World Tile suite: 107 passed, five PyVista future warnings, 76.36 s
  (Python 3.14.7, isolated Pillow 13, VTK 9.7.2). A subsequent independent
  BC5 reconstruction-formula assertion passed in a focused run.
- Relocated AWTP regression: copied the entire reference project to an unrelated
  directory, confirmed both manifest heightmap paths resolve to the copied file,
  exported four prebuilt tiles without rebuilding, then rebuilt and exported
  four tiles. `test_pipeline.py -k advanced_reference_project`: passed.
- Focused GUI tests use built terrain tiles to render a one-layer POM change
  and a two-layer height-blend change. They exercise asynchronous detailed-mode
  loading, fast-mode switching, and a missing-surface error. Seven related
  terrain, POM, and layered-render regressions passed with VTK 9.7.2.
- The complete World Tile suite passed 99 tests after terrain preview
  integration. A separate texture-picker test verifies R16 DDS dimensions,
  format, mip count and byte estimate, 16-bit TIFF metadata, and malformed
  file reporting.
- A rendered shader diagnostic test checks base and height-adjusted weights,
  confirms that POM changes the displayed final weight and offset, and checks
  that a configuration failure hides the diagnostic and reports the error.
- A GPU color-space regression verifies that ADM-compatible DDS and KTX2
  inputs with incompatible albedo, normal or data roles fail explicitly rather
  than being silently re-encoded. The full suite exposed an old test expecting
  silent BC7 UNORM-to-sRGB transcoding; it now verifies byte-preserving BC7
  sRGB export and the separate mismatch test checks rejection. Eight related GPU
  and R16 tests passed.
- The full World Tile suite passed 97 tests with isolated Pillow 13 and VTK
  9.7.2; five PyVista future warnings
  remain. Rendered tests passed for planar and curved terrain and for a curved
  transition between disjoint biomes. The
  latter confirms four nonzero surface weights at a shared edge, mixed LODs,
  measurable POM, pixel continuity and invariance under reversed layer slots.
- A bounded Blender ENUM regression verifies explicit null texture overrides
  against a non-null custom default across import, project reload and export.
  It also checks whitespace-preserving shader metadata and rejection of
  conflicting descriptions and authors. Before the fix, the metadata
  whitespace assertion failed; the updated regression passes.
- A 16-bit grayscale TIFF previously became an 8-bit BC3 primary. A focused
  regression now verifies its exact R16 DDS samples and 16-bit PNG fallback;
  another verifies the preview's normalized samples.
- A check-only build failed because an existing import-transaction fixture used
  conflicting shader metadata. Its fixture now matches the retained definition,
  and the bounded transaction test passes, including injected rollback failures.
  The subsequent complete check-only matrix also passed. It did not build a ZIP.
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
  8-bit levels. It also checks that a non-unit UV scale is explicitly rejected.
  The test passed. The tool uses fixture-specific assumptions and PNG fallbacks,
  not an independent or general-purpose ADM renderer.
- The complete World Tile test suite passed: 90 tests with Pillow 13 and VTK
  9.7.2 on Windows. Five PyVista future warnings remain.
- An offscreen VTK regression renders two exported sloped, irregular tiles at
  different LODs, using exported UVs, per-vertex `COLOR_1`, shader settings,
  and PNG fallbacks. Along the visible edge it checks varying biome-noise
  weights and a shared-surface biome transition, absence of black gaps, a
  maximum adjacent-channel difference of 18/255, measurable POM changes, and
  slot-permutation invariance. It passed with VTK 9.7.2. The later curved and
  disjoint-biome variants use the same test and empirical threshold.
- A separate synthetic two-triangle test uses the exporter's actual
  `triangle_masks` and `color1` packing on five equal edge weights. The POM
  shader renders a visible discontinuity when each triangle drops a different
  surface. Both conflicts are reported by the packing function. This is a
  known limit, not a passing seam guarantee for over-four-surface input. GUI and
  CLI regressions check that export reports warn about the seam risk.
- The shader enum switch regression saves a project while a legacy profile is
  selected, reopens it, and checks restoration of advanced ENUM, numeric and
  image values when the advanced profile is selected again. It checks the export
  warning and distinguishes custom parameters with different types. It also
  reloads an official profile with cache metadata removed to test migration.
- `build.bat -CheckOnly` passed all steps after the shader-cache and migration
  changes, with documented external-asset skips. The affected enum and all 47
  Blender shader profile scenarios also passed in bounded individual runs.
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
