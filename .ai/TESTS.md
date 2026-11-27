# Mission verification record

Record exact commands, environment, outcomes, skips and artifact paths. A skip
is not evidence that a requirement passed.

## Baseline and environment
- Intake checkout: Windows, `main`, `1f5c7638bd014bbe7d24e347d5600fdcdedffe46`.
- The prior `.ai/FINAL_REPORT.md` records historical checks for Blender 5.2.3
  and World Tile with VTK 9.7.2; those checks precede this mission and do not
  establish current mission conformance.
- Current branch subsequently received mission setup commit
  `b39da3da5d766c081f8dc84873fe25a7b0685e35`; no source-code changes were
  present in that commit.
- Python 3.14.7 and Blender 5.2.3 LTS are available. World Tile declared
  dependencies except `tifffile` were importable at intake.
- `.\build.bat -CheckOnly`: **PASS**, 35 steps, 2,150 cases passed, 0 failed,
  10 skipped because optional external files, permissions, or a binding target
  were unavailable. Report: `dist/check-report-1.24.45.txt`; QA JSON:
  `dist/qa-report-1.24.45.json`. The build did not bump versions or package.
- The check-only matrix does not cover World Tile; its baseline remains
  separate.
- From `appartus_world_tile`, with its absolute path in `PYTHONPATH`,
  `python -m unittest discover -s tests`: **131 passed**, 0 failed, 0 skipped
  (108.461 s). `tifffile` was installed because two test errors exercised its
  declared project dependency. One existing PyVista `extract_surface`
  future-warning was emitted. Initial run without `tifffile` and `PYTHONPATH`
  failed (4 errors, 1 failure); this is diagnostic context, not the final
  baseline result.

## New mission runs

| Date | Command / artifact | Environment | Result | Notes |
|---|---|---|---|---|
| 2026-11-27 | Rebuild `reference_project/advanced_reference.awtp` to a temporary output; run strict and approximate export | Windows, Python 3.14.7 | **PASS** | Rebuilt geometry reports 54 conflicts in `x000_y001` (18 per LOD). Strict mode rejects before writing tile files. Approximate mode affects 100 vertex instances; mean total-variation error is 1.243%, maximum 3.922%. Decoded weights at matching world positions across all tiles and LODs stay within 1% total-variation error. The checked-in prebuilt PLYs do not reproduce the current AWTP rules and are not valid conflict evidence. |
| 2026-11-27 | `python -m unittest tests.test_export.ExportTest.test_reference_project_palette_conflicts_and_measured_reduction` | From `appartus_world_tile`, app path in `PYTHONPATH` | **PASS**, 1 test (5.087 s) | Exercises rebuild, strict preflight, approximate metrics, and cross-tile/LOD decoded weights. |
| 2026-11-27 | `python -m unittest discover -s tests` | From `appartus_world_tile`, app path in `PYTHONPATH`; Python 3.14.7 | **PASS**, 135 tests (115.481 s) | Covers stable surface IDs, preset/project migration, conflict details and the rebuilt reference. Render regressions cover two/four/five surfaces, height blending, POM, slot permutations, mixed LOD, curved irregular tiles and disjoint biomes. One existing PyVista `extract_surface` future warning. |
| 2026-11-27 | Blender `test_material_height_blender.py` | Blender 5.2.3 LTS, headless | **PASS** | Includes optional terrain surface identity preservation through import, export, save and reload. |
| 2026-11-27 | `python -m unittest adm_blender.tests.test_draft4` | Python 3.14.7 | **PASS**, 33 tests; 1 skipped | Includes terrain surface extension validation and scope checks. |
| 2026-11-27 | Focused World Tile identity/export tests | From `appartus_world_tile`, app path in `PYTHONPATH` | **PASS**, 3 tests | Rechecked surface-ID stability and UTF-8 byte limit, legacy project migration, and ADM material-slot identity export after the final ID validation edit. |
| 2026-11-27 | Rebuilt-reference conflict diagnostics | From `appartus_world_tile`, app path in `PYTHONPATH` | **PASS**, 1 test | Rechecked strict preflight details and the deterministic, bounded 20-triangle sample after parallel aggregation. |
| 2026-11-27 | One-off palette strategy experiment | Windows, Python 3.14.7; rebuilt `reference_project/advanced_reference.awtp` | **MEASURED** | Compared face-mask packing with spatial regions binned at 4/8/16 m. Current: 9 material palettes, 1.243% mean and 3.922% max affected-vertex error. Region: 27/26/22 palettes, about 2.21% mean and 9.80% max; all retained dominant surfaces on this fixture. Region variants were not rendered and are not shipped. |
| 2026-11-27 | `C:\Python314\python.exe -m pytest -q appartus_world_tile\tests\test_terrain_wizard.py::TerrainWizardTest::test_over_four_surface_approximation_preserves_rendered_shared_edge` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 1 test (1.98 s) | Renders adjacent conflicting five-surface palettes with height blending and POM. Seam-consistent weights keep the measured median shared-edge jump at or below 10; reversing each primitive's local slot order keeps pixels within 3 intensity levels. Disabling POM changes more than 100 pixel components by over 5 levels. |
| 2026-11-27 | `python -m unittest adm_blender.tests.test_draft4` | Python 3.14.7 | **PASS**, 36 tests; 1 skipped | Covers the physical type registry, built-in/custom IDs, subtype/tag constraints, extension declaration, bounded descriptions and unknown-type fallback. |
| 2026-11-27 | `python -m unittest adm_blender.tests.test_draft4` | Python 3.14.7 | **PASS**, 37 tests; 1 skipped | Adds reference-query coverage for per-triangle override, collider default fallback, and out-of-range triangle handling. |
| 2026-11-27 | `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_material_height_blender.py' 240` | Windows, Blender 5.2.3 LTS | **PASS** | Verifies known and custom unknown physical type/subtype/tag metadata through ADM import/export and Blender save/reload; rejects a non-array tag value. Blender reported existing dependency-cycle warnings and a `Material.use_nodes` deprecation warning. |
| 2026-11-27 | `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_workflow.py' 240` | Windows, Blender 5.2.3 LTS | **PASS** | Verifies collider-level physical material defaults and stable per-triangle IDs through triangulation, export, import and re-export. Existing Blender dependency-cycle and `Material.use_nodes` warnings remain. |
| 2026-11-27 | `.\build.bat -CheckOnly` | Windows, Blender 5.2.3 LTS | **PASS**, 35 steps; 2,154 cases; 0 failed; 10 skipped | Includes ADM validator tests and Blender workflow/material-height tests. Reports: `dist/check-report-1.24.45.txt`, `dist/qa-report-1.24.45.json`, and `dist/qa-report-1.24.45.md`. Check-only left the version unchanged and skipped packaging. |
| 2026-11-27 | `.\build.bat -CheckOnly` | Windows, Blender 5.2.3 LTS | **PASS**, 35 steps; 2,165 cases; 2,155 passed; 10 skipped; 0 failed | Includes the physical query tests and Blender integration checks. Reports: `dist/check-report-1.24.45.txt`, `dist/qa-report-1.24.45.json`, and `dist/qa-report-1.24.45.md`. Check-only left the version unchanged and skipped packaging. |
| 2026-11-27 | `.\build.bat -CheckOnly` | Windows, Blender 5.2.3 LTS | **PASS**, 35 steps; 2,151 cases; 0 failed; 10 skipped | Report: `dist/check-report-1.24.45.txt`; QA JSON: `dist/qa-report-1.24.45.json`. Skips include unavailable external assets, symlink permissions, and a binding test without a compatible target. Check-only left the version unchanged and did not package. |
| 2026-11-27 | `git diff --check` | Windows | **PASS** | No whitespace errors. |
| 2026-11-27 | `python -m unittest discover -s tests -p 'test_pipeline.py'` | From `appartus_world_tile`; Python 3.14.7 | **PASS**, 22 tests | Covers independent collision error bounds, per-tile triangle caps, render LOD invariance, shared horizontal/vertical boundary vertices, invalid limits, and v2 manifest loading. |
| 2026-11-27 | `python -m unittest discover -s tests -p 'test_export.py'` | From `appartus_world_tile`; Python 3.14.7 | **PASS**, 42 tests | Validates separate ADM MESH collider export, collider mesh accessors, collision fingerprint inclusion, malicious path rejection, and incomplete collision-record rejection. |
| 2026-11-27 | `python -m unittest discover -s tests -p 'test_terrain_wizard.py'` | From `appartus_world_tile`, app path in `PYTHONPATH`; Python 3.14.7 | **PASS**, 59 tests | Verifies AWTP v9 collision controls persist and restore. One existing PyVista future warning. Without `PYTHONPATH`, one subprocess import test fails from repository-root cwd; the exact rerun with the app path passes. |
| 2026-11-27 | `python -m awt build --help` | From `appartus_world_tile` | **PASS** | Confirms `--collision-error` and `--collision-max-triangles` are exposed. |
| 2026-11-27 | `git diff --check` | Windows | **PASS** | Final check after collision implementation and mission-record updates. |
| 2026-11-27 | `python -m pytest appartus_world_tile\tests\test_export.py appartus_world_tile\tests\test_pipeline.py appartus_world_tile\tests\test_terrain_setup.py appartus_world_tile\tests\test_terrain_wizard.py -q` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 136 tests | Covers AWTP v10 physical materials/paint, preset persistence, independent collision export, tile-local physical invalidation, GUI painting and the physical-material dialog. Five existing PyVista future warnings. |
| 2026-11-27 | `python -m unittest adm_blender.tests.test_draft4 -q` | Windows, Python 3.14.7 | **PASS**, 37 tests; 1 skipped | Physical registry, reference queries and ADM validation. |
| 2026-11-27 | `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_workflow.py' 240` | Windows, Blender 5.2.3 LTS | **PASS** | Rechecks existing collider defaults and per-triangle assignment round trips after exporter grouping changes. Existing Blender dependency-cycle and `Material.use_nodes` deprecation warnings remain. |
| 2026-11-27 | Generate a temporary painted World Tile ADM with system Python; run `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_world_tile_collision_blender.py' 240` | Windows, Python 3.14.7 and Blender 5.2.3 LTS | **PASS** | Assigned and unassigned collision faces survive import, `.blend` save/reload and ADM re-export; stable physical IDs and material references are preserved. Existing Blender dependency-cycle warnings remain. Temporary fixture was removed. |
| 2026-11-27 | `C:\Python314\python.exe -m pytest appartus_world_tile\tests\test_export.py appartus_world_tile\tests\test_pipeline.py appartus_world_tile\tests\test_terrain_setup.py appartus_world_tile\tests\test_terrain_wizard.py -q` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 139 tests | Covers AWTP v11 physical links and paint, automatic dominant-weight classification, manual override precedence, manifest v4 dominant surfaces, preset v6 persistence, selective invalidation, and GUI linking. Five existing PyVista future warnings. |
| 2026-11-27 | `C:\Python314\python.exe -m unittest tests.test_export.ExportTest.test_project_v11_physical_material_links_and_legacy_load_defaults -v` | From `appartus_world_tile`; Python 3.14.7 | **PASS**, 1 test | The initial run caught a nonexistent test texture referenced by the fingerprint assertion. The fixture now creates the texture in its managed temporary directory. |
| 2026-11-27 | Generate a one-tile World Tile ADM with an automatic grass link, manual physical paint, and unlinked dominant surfaces; run `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_world_tile_collision_blender.py' 240` | Windows, Python 3.14.7 and Blender 5.2.3 LTS | **PASS** | Automatic, manual, and unassigned faces survive Blender import, `.blend` save/reload, and ADM re-export. Existing Blender dependency-cycle warnings remain; the generated fixture was temporary. |
| 2026-11-27 | Final focused World Tile pytest command (above) | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 140 tests | Adds regression coverage for v2/v3 collision manifests without dominant-surface metadata: manual assignment remains available, automatic classification stays disabled, and malformed v4 metadata fails explicitly. Five existing PyVista future warnings. |
| 2026-11-27 | Regenerate a one-tile World Tile ADM with automatic, manual-override, and unassigned faces; rerun `test_world_tile_collision_blender.py` | Windows, Python 3.14.7 and Blender 5.2.3 LTS | **PASS** | Rechecked the Blender import/save/reload/re-export after legacy-manifest validation changes. Existing 95 Blender dependency cycles remain; the fixture was temporary. |
| 2026-11-27 | `.\build.bat -CheckOnly` | Windows, Python 3.14.7 and Blender 5.2.3 LTS | **PASS**, 35 steps; 2,155 passed; 10 skipped; 0 failed | Reports: `dist/check-report-1.24.45.txt`, `dist/qa-report-1.24.45.json`, and `dist/qa-report-1.24.45.md`. Skips are external assets not present or approved, plus an animation binding without a compatible target. Check-only left versions unchanged and skipped packaging. |
| 2026-11-27 | `C:\Python314\python.exe -m pytest appartus_world_tile\tests\test_export.py appartus_world_tile\tests\test_pipeline.py appartus_world_tile\tests\test_terrain_setup.py appartus_world_tile\tests\test_terrain_wizard.py -q` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 141 tests | Final focused run after adding the collision-inspector test for separate geometry display, physical assignment colours, counts/error, hover identity, and rejection of a path that escapes the build directory. Five existing PyVista future warnings. |
| 2026-11-27 | `C:\Python314\python.exe -m pytest appartus_world_tile\tests -q` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS**, 152 tests | Covers deterministic physical-boundary refinement from automatic links and manual paint, maximum split-edge size, tile seams, hard per-tile triangle cap, AWTP v12 persistence/legacy v11 defaults, and manifest v5 generation. Five existing PyVista future warnings. |
| 2026-11-27 | Generate a temporary World Tile ADM with automatic, manual-override and unassigned collision faces; run `python .\tools\run_blender_test.py 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' '.\adm_blender\tests\test_world_tile_collision_blender.py' 240` | Windows, Python 3.14.7 and Blender 5.2.3 LTS | **PASS** | Assigned/unassigned faces, physical IDs and material references survive collider import, `.blend` save/reload and ADM re-export after boundary refinement. Existing 38 dependency-cycle warnings across save and reload. |
| 2026-11-27 | `python -m awt build --help` and `git diff --check` | Windows, Python 3.14.7; World Tile path in `PYTHONPATH` | **PASS** | Confirms `--collision-boundary-max-edge` is exposed; no whitespace errors. |

## Required evidence before closeout
- Normative contract fixtures and deterministic reference math.
- Palette conflict, strict/approximate export, pixel/seam, slot permutation,
  mixed LOD and irregular/curved terrain render tests.
- Control/Macro Map, anti-tiling, triplanar, detail, self-shadowing and
  displacement vectors including edge cases and bounded resource use.
- Physical registry, collider assignment/query, independent collision,
  boundary refinement and round-trip tests.
- BC5 fallback/source-byte preservation plus R16, mipmap and embedded/external
  GPU texture cases.
- World Tile old/new persistence, GUI binding, generation, selective
  invalidation, portability and atomic export.
- Blender runtime registration, node/render tests, import/export, save/reload,
  collider and texture cases.
- Consumer support audit and actual rendered artifacts.
- Package integrity and isolated installation checks.
