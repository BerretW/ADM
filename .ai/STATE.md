# Mission state

## Current status
Mission intake and the first P0 palette remediation are complete. The user-
provided request is preserved verbatim in `MISSION.md`; the broader mission
remains in progress.

## Baseline
- Intake HEAD: `1f5c7638bd014bbe7d24e347d5600fdcdedffe46`
  (`Document controlled mission closeout`), branch `main`.
- Worktree was clean before this mission started.
- During intake, the user/environment committed the archived prior records and
  new mission setup as `b39da3da5d766c081f8dc84873fe25a7b0685e35`; do not amend
  that commit. The active branch now points to this commit.
- The user-provided external audit baseline is
  `cd3c9b9d1bfe1e0a0d7f8a1718a899f0371b0969`.
- `git diff --stat cd3c9b9..HEAD` showed only mission-closeout documentation
  changes; implementation files at intake match the cited audit baseline.
- Previous `.ai` mission records were copied to `.ai/archive/1f5c763/` before
  starting this mission. The archival copies must remain unchanged.
- Previous local report records Blender Tools 1.24.45 and World Tile 0.7.17.
  Treat these as historical evidence, not proof of this mission's completion.

## Current milestone
M1 and M3 are complete. M2 and M4–M9 remain in progress. Global terrain
surface identity is separate from local material slots through persistent World Tile surface IDs
and optional `ADM_terrain_surface_v1` mappings. Strict and approximate palette
policies include bounded conflict details and repair suggestions. M2 remains
open pending broader palette-strategy comparisons. M3 now has an additive,
machine-readable physical type/subtype/tag registry and Blender authoring,
validation, fallback lookup, and import/export/save-reload support. Existing
collider defaults, per-triangle references, friction and restitution retain
their meanings. Validator, query, and Blender round-trip tests pass. World Tile
now generates an optional independent terrain collision mesh with a measured
height-error bound, hard per-tile triangle cap, shared-edge refinement, and ADM
MESH-collider export. Its physical-material library supports stable
surface-to-physical links and automatic classification from dominant authored
collision weights; manual physical paint overrides those links. AWTP v12,
preset v6, manifest v5, selective export invalidation, and Blender save/reload
coverage are verified. Physical-boundary refinement now classifies face
assignments from authored weights and centroid paint, applies a deterministic
RTIN split-edge target, and respects the per-tile triangle cap and RTIN depth;
v11 projects load with the default edge target. The 3D viewer can display collision geometry
separately, colour physical assignments, report counts and measured error, and
show surface/material identity under the cursor. No release version bump or
package was made.
Follow the dependency order in `TASKS.md`; do not mark pre-existing or
historical work complete without re-verifying it against this mission's exact
requirements.

## Known starting limitations
The previous closeout and technical-debt report identifies the following items
for fresh verification:

- Four-layer palettes cannot precisely represent five simultaneous surface
  weights. Rebuilding the reference AWTP reproduces 54 conflicts (18 in each
  LOD of one tile); strict export rejects before writing, while approximation
  preserves shared-vertex weights within each tile LOD with measured mean
  total-variation error 1.243% and maximum 3.922%. This does not yet prove
  general continuity across independently sampled tile or LOD boundaries.
  The rebuilt reference export passes a separate cross-tile/LOD comparison at
  a 1% total-variation threshold. Export diagnostics show up to 20 affected
  triangles and their dropped corner weights. Alternate strategies and
  broader render fixtures remain open.
- Core-PBR BC5 primary bytes and reconstructed RGB fallback are unresolved in
  Blender's standalone core-PBR path.
- World Tile's multi-surface final view uses CPU composition when parallax is
  disabled; its weight diagnostics are unshifted estimates.
- Blender does not natively render POM; supported unknown extensions cannot
  generally have opaque references remapped.
- GPU codec/render-hook verification is Windows-specific; Blender dependency
  cycle warnings remain unexplained.

These are starting observations, not accepted final blockers. Reproduce and
update them as implementation evidence becomes available.

## Work log
- 2026-11-27: Read the full user-provided mission and previous `.ai` records.
  Verified clean `main` at `1f5c763`; the only diff from the stated
  `cd3c9b9` reference was mission-closeout documentation.
- 2026-11-27: Archived previous mission records under `.ai/archive/1f5c763/`
  and copied the read-only user-provided mission snapshot verbatim to
  `.ai/MISSION.md`.
- 2026-11-27: Recreated the mission checklist and initial state, decisions,
  test and debt records. Baseline tests and dependency availability still need
  verification.
- 2026-11-27: Root `build.bat -CheckOnly` passed on intake commit
  `1f5c7638bd014bbe7d24e347d5600fdcdedffe46`: Blender 5.2.3 LTS, 35 steps
  passed, 2,150 reported cases passed, 10 externally blocked cases skipped,
  zero failures. Blender was available at the build script's documented
  fallback path. The Python/standard/Blender matrix does not run the World Tile
  suite; that baseline remains pending.
- 2026-11-27: Python 3.14.7 is available. The project declares Python >=3.11.
  `tifffile` is absent from the current environment; all other checked World
  Tile runtime dependencies (NumPy, Pillow, Numba, texture2ddecoder, PySide6,
  PyVista, PyVistaQt) are importable. Do not install unless a selected test
  fails because the declared dependency is missing.
- 2026-11-27: World Tile suite first reported 4 errors and 1 failure: the
  declared `tifffile` dependency was missing, and a subprocess test could not
  import `awt` because the repository root was its working directory. Installed
  the already-declared package after the missing-import failure and reran with
  the app directory added to `PYTHONPATH`, which also resolves the subprocess
  import. `python -m unittest discover -s tests` then passed all 131 tests in
  108.461 seconds. One existing PyVista future warning remains.
- 2026-11-27: Rebuilt `reference_project/advanced_reference.awtp` into a
  temporary directory rather than relying on its checked-in prebuilt tiles.
  The rebuild reproduced 54 palette-conflict triangles, all in `x000_y001`
  (18 per LOD); strict export rejected them before creating tile files.
  Approximate export affected 100 vertex instances, with 1.243% mean and
  3.922% maximum total-variation error. A regression test compares decoded
  per-surface weights at duplicate emitted positions across primitives.
- 2026-11-27: World Tile `python -m unittest discover -s tests` passed all 134
  tests in 115.035 seconds, including the rebuilt-reference integration test.
  One existing PyVista future warning remains.
- 2026-11-27: `.\build.bat -CheckOnly` passed all 35 steps and 2,150 cases,
  with zero failures and 10 reported skips. Blender 5.2.3 LTS; report:
  `dist/check-report-1.24.45.txt`; QA JSON:
  `dist/qa-report-1.24.45.json`. Skips include unavailable external assets,
  unavailable symlink permissions, and an animation binding without a
  compatible target. No version bump or package was made.
- 2026-11-27: `git diff --check` passed.
- 2026-11-27: Extended the rebuilt-reference regression to compare decoded
  surface weights at matching world positions across all tiles and LODs. The
  exact ADM output passes the 1% total-variation bound; targeted test passed in
  5.087 seconds.
- 2026-11-27: Added persistent deterministic surface IDs to AWTP format 8 and
  terrain presets version 5. Added optional `ADM_terrain_surface_v1` to map
  local material slots to those IDs, with ADM validation and Blender
  import/export preservation tests.
- 2026-11-27: Added bounded affected-triangle diagnostics with dropped
  per-corner weights and stable surface IDs. Strict errors, the GUI report and
  CLI output include repair suggestions that direct users to reduce overlap
  or edit weights with the existing Map-tab Surface paint tool.
- 2026-11-27: World Tile `python -m unittest discover -s tests` passed all 135
  tests in 115.481 seconds after adding CLI details. One existing PyVista
  future warning remains. Rendered regressions cover two/four/five surfaces,
  height blending and POM, local-slot permutation, mixed LOD, curved irregular
  tiles and disjoint biomes.
- 2026-11-27: `.\build.bat -CheckOnly` passed all 35 steps, 2,151 cases, zero
  failures and 10 skips on Blender 5.2.3 LTS. The report and QA JSON remain
  `dist/check-report-1.24.45.txt` and `dist/qa-report-1.24.45.json`. No version
  bump or package was made.
- 2026-11-27: The terrain surface identity extension passed the Blender
  material-height import/export/save/reload integration test and all 33 ADM
  draft-4 validator tests (one skipped).
- 2026-11-27: `git diff --check` passed after the M2 identity and diagnostics
  changes.
- 2026-11-27: After adding the 128-byte UTF-8 surface-ID bound, the focused
  project migration, ID stability/validation and ADM export tests passed
  (3 tests); Python compile and `git diff --check` also passed.
- 2026-11-27: After bounding the aggregate detail sample across parallel tile
  exports, the rebuilt-reference diagnostics and decoded-weight regression
  passed again (1 test); output remains sorted by tile, LOD and triangle index.
- 2026-11-27: Compared the current face-mask palette strategy with spatial
  region palettes on a fresh reference rebuild. The current strategy uses 9
  tile-file palettes at 1.243% mean / 3.922% max affected-vertex error.
  Region bins of 4, 8 and 16 m use 27, 26 and 22 palettes at about 2.21% mean /
  9.80% max error. All retained dominant surfaces on this fixture; region
  candidates were not rendered, and other alternatives remain unmeasured.

- 2026-11-27: Added `ADM_physical_surface_types_v1` and
  `adm_blender/core/physical_surface_registry.json` for built-in types,
  subtypes, semantic tags, and the unknown-type fallback. Custom
  `org.<reverse-domain>.<name>.vN` IDs remain preservable; existing physical
  profiles, friction/restitution fields, collider defaults, and per-face
  references keep their prior meanings. Physical classification is independent
  of visual materials and adds no gameplay behavior.
- 2026-11-27: Blender physical type metadata now has authoring fields and
  import/export/save-reload preservation. Validator tests cover built-in and
  custom IDs, subtype/tag constraints, extension requirements, description
  bounds, and fallback lookup.
- 2026-11-27: Added `query_physical_material` as a reference resolver for
  collider defaults and per-triangle overrides. The focused validator suite
  passes 37 tests with 1 existing skip, including default precedence and
  invalid triangle-index cases.
- 2026-11-27: `python -m unittest adm_blender.tests.test_draft4` passed 36
  tests with 1 existing skip. Blender 5.2.3 `test_material_height_blender.py`
  passed, including round trips for known and unknown custom physical types.
  Blender 5.2.3 `test_workflow.py` passed stable collider and per-triangle
  physical-reference import/export checks. `git diff --check` passed.
- 2026-11-27: `.\build.bat -CheckOnly` passed all 35 steps and 2,154 cases,
  with 0 failures and 10 skips on Blender 5.2.3 LTS. The QA report confirms
  that `test_workflow.py` and `test_material_height_blender.py` passed.
  Reports: `dist/check-report-1.24.45.txt`,
  `dist/qa-report-1.24.45.json`, and `dist/qa-report-1.24.45.md`. No version
  bump or package was made.
- 2026-11-27: After adding reference surface queries, `.\build.bat -CheckOnly`
  passed all 35 steps and 2,165 cases (2,155 passed, 10 skipped, 0 failed) on
  Blender 5.2.3 LTS. The report remains at the same `dist/` paths. Check-only
  left version 1.24.45 unchanged and skipped packaging.
- 2026-11-27: Added optional independent collision meshes to World Tile.
  Collision geometry uses its own height-error RTIN, preflights a hard
  per-tile triangle limit, unions and propagates boundary vertices, and records
  measured error and boundary diagnostics. ADM export writes a separate MESH
  collider and includes its digest in Export Changed fingerprints. AWTP
  format 9 preserves collision settings; manifest format 3 adds collision
  records while the loader continues to accept format 2. Manual physical paint
  and per-triangle assignment are still outstanding.
- 2026-11-27: World Tile pipeline tests passed 22/22, covering error bounds,
  triangle caps, render-mesh independence, horizontal/vertical shared-edge
  vertex sets, invalid limits, and legacy manifest loading. ADM export tests
  passed 42/42, including validated collider serialization, collision-path
  traversal rejection and incomplete-manifest rejection. GUI/project workflow
  tests passed 59/59 with the app path in `PYTHONPATH`; one existing PyVista
  future warning remains. `awt build --help` exposes both collision options.
- 2026-11-27: An initial GUI test invocation without `PYTHONPATH` had one
  subprocess import failure because it runs from the repository root. Rerunning
  with `C:\Users\adolf\GitHub\ADM\appartus_world_tile` in `PYTHONPATH` passed
  all 59 tests. This is a test invocation environment requirement, not a
  collision failure.
- 2026-11-27: Added the independent World Tile physical-material library and
  paint map, persisted in AWTP v10. Export samples collision-triangle
  centroids and emits stable per-face physical IDs only for painted triangles,
  reports assigned
  and unassigned counts, and fingerprints only affected tiles. Physical paint
  does not alter visual surface rules or borrow visual weights. README,
  persistence/preset tests, export tests, and a Blender
  import/save/reload/re-export integration test cover the workflow. Automatic
  classification, physical-boundary refinement, and collision inspection
  remain open.

- 2026-11-27: Added optional physical-material links on stable terrain surfaces.
  Collision PLYs now retain the authored surface-weight channels, and ADM export
  classifies each collision triangle by its deterministic dominant weight; manual
  paint overrides the automatic mapping and unlinked surfaces remain unassigned.
  The manifest records dominant surfaces per collision tile for selective
  physical fingerprinting. AWTP is v11, presets are v6, the collision manifest is
  v4, and the Export Changed index is v8.
- 2026-11-27: World Tile focused regression suites passed 139 tests with five
  existing PyVista future warnings. A generated tile containing automatic,
  manual-override, and unassigned collision faces passed Blender 5.2.3 import,
  save/reload, and ADM re-export. An initial project-fingerprint test failed
  because its referenced height image did not exist; the fixture now creates the
  image in its temporary directory, and the focused suites pass.
- 2026-11-27: Tightened legacy collision-manifest handling. Versions before 4
  remain manual-only because they lack dominant-surface metadata; v4 manifests
  with missing or empty metadata now fail explicitly instead of silently
  skipping automatic-classification fingerprints. The final focused suites
  passed 140 tests with five existing PyVista future warnings. A regenerated
  automatic/manual/unassigned collider passed Blender 5.2.3 save/reload and
  re-export again.
- 2026-11-27: `.\build.bat -CheckOnly` passed the ADM matrix: 35 steps, 2,155
  passed cases, 10 skipped, and 0 failed on Python 3.14.7 and Blender 5.2.3 LTS.
  Skips concern unavailable or unapproved external assets and a binding without
  a compatible target. Reports are recorded in `dist/`; the check-only run did
  not bump versions or package.
- 2026-11-27: Added a separate collision inspection mode to the World Tile 3D
  viewer. It renders physical assignments and wireframe, reports collision
  triangle counts and measured error, and shows the dominant surface plus
  physical-material name/ID on hover. The loader bounds inspection to 250,000
  triangles and 256 MiB per mesh, and rejects collision paths that escape the
  build directory. Focused World Tile tests passed 141 cases with five existing
  PyVista future warnings; the test covers assigned, unassigned, hover, and
  path-traversal behavior.
- 2026-11-27: Added deterministic physical-boundary RTIN refinement. Mixed
  vertex and face-centroid assignments split while the RTIN edge exceeds the
  configured 4 m default; a hard per-tile triangle cap and maximum RTIN depth
  prevent unbounded subdivision. The setting is exposed in the GUI and CLI,
  persisted in AWTP v12, and older v11 projects retain the 4 m default.
  Regression tests cover automatic links, manual paint, triangle limits,
  measured split-edge size, deterministic output, and shared tile seams.
- 2026-11-27: `C:\Python314\python.exe -m pytest appartus_world_tile\tests -q`
  passed all 152 World Tile tests with five existing PyVista future warnings.
  A generated collider with automatic, manual, and unassigned faces passed
  Blender 5.2.3 import, `.blend` save/reload, and ADM re-export; Blender emitted
  the existing dependency-cycle warnings. CLI help exposes the new edge-limit
  option. The root check-only matrix was not rerun for this World Tile change.

## Blockers
None established. Do not treat unavailable platforms or unrun tests as passes.
