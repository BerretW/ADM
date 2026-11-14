# Draft 0.4 executed test report

## Blender 1.13.0 automatic LOD generator — local verification

- Blender 5.2.3 `test_lod_generator.py`: **PASS**. Four levels at 0/15/40/100 m inside the model
  root; non-screen triangles follow 0.5/0.25/0.1 (3200 → 1699/949/499); interactive screen triangles,
  surface IDs, both materials, `COLOR_0`, skin weights are preserved on every level; shape keys with
  a relative chain are transferred to LOD1–LOD2 (cone morph error < 0.03, relative delta exact) and
  dropped on LOD3; the exported model validates with one LOD group and one `surfaceId` bound on four
  nodes; regeneration replaces generated levels; non-decreasing ratios are rejected.
- All other Blender integration tests and the Python unittest suite (94 tests, 1 skip): **PASS**.
- `adm_tools-1.13.0.zip`: extension validation and an isolated install that runs Generate LODs: **PASS**.

## Blender 1.12.0 / `ADM_vertex_control_v1` 1.1.0 multi-row tint palettes — local verification

- Python unittest suite: **PASS**, 94 tests (1 skip). `test_tint_palette_height_one_to_five` accepts
  heights 1 and 5 and rejects 6 with `VERTEX_CONTROL_PALETTE_SIZE`. Reference validators, shader
  registry and fixture reproducibility checks: **PASS**.
- Blender 5.2.3 `test_workflow.py`: **PASS**. A 4×3 palette yields top-row swatches, exports as valid
  ADM and re-imports with the same top-row swatches; 5 px palettes read only the top row; 6 px
  palettes are rejected.
- Blender 5.2.3 `test_shader_preview.py`: **PASS**. Cycles bake of a 2×3 palette samples only the
  top row. `test_interactive_blender.py`, `test_material_slots.py`, `test_fixtures.py`: **PASS**.
- `adm_tools-1.12.0.zip`: **PASS** for CRC, manifest version, byte identity with source and an
  installation into an isolated temporary Blender user directory (22 shader entries, top-row
  swatches, 6 px palette rejected). The temporary directory was removed.

## Blender 1.11.0 vertex-color authoring — local verification

- Blender 5.2.3 `test_workflow.py`: **PASS**. Checks that meshes outside an ADM Model Root stay
  untouched even with an enabled material, ADM-model and explicit-conversion initialization, neutral
  layer initialization, preservation of
  authored and ordinary colors, live Edit Mode channel/face selection, default reset, material-slot
  filtering, offset-aware R-only palette selection, invalid palettes, BYTE_COLOR/POINT conversion,
  missing-attribute import/export defaults, conflicting attribute diagnostics and round-trip values.
- Blender 5.2.3 `test_shader_preview.py`: **PASS**. Cycles verifies the selected palette entry on
  actual geometry, wetness, normal strength, dielectric/metallic F0 and ignored reserved `COLOR_1`.
- Blender 5.2.3 `test_interactive_blender.py`, `test_material_slots.py` and `test_fixtures.py`: **PASS**.
- `adm_tools-1.11.0.zip`: **PASS** for CRC, manifest version, byte identity with source and a real
  installation into an isolated temporary extension repository. All 22 shader entries, layer
  initialization, tint selection, reset and export worked from the installed package. No user
  preferences were saved; the temporary repository was removed.
- `git diff --check`: **PASS**. Blender still emits the previously reported dependency-cycle
  warnings. No schema or capability versions changed; these are reference implementation tests,
  not independent renderer certification.

## P13 interactive surfaces — local verification

- CI-equivalent Python unittest command (`test_container`, `test_draft4`, `test_skeleton_profiles`,
  `test_gputex`, `test_shader_math`): **93 tests, 92 passed, 1 skipped**. Windows denied permission
  to create the symlink for the existing external-image escape test.
- `python adm-standard/tools/run_tests.py`: **25 passed, 0 failed**;
  `test_profiles.py`: **12 passed**. The interactive reference test verifies two stable IDs, shared
  geometry, UV/hit mapping, bilinear sRGB-to-linear sampling, alpha, runtime equations and fallback.
- Shader registry generation and tests: **PASS**, 21 exact-version profiles.
  `build_interactive_fixture.py --check` and the self-contained fixture generator's byte comparison:
  **PASS**, including all 11 malformed interactive fixtures.
- Blender 5.2.3 `test_interactive_blender.py`: **42 checks passed**. These include embedded and
  external fallback round trips, shared materials and meshes, per-face IDs, curved/multi-triangle
  screens, geometry edits, material-slot reordering, triangulation, animation, HDR `COLOR_0`,
  `COLOR_1`, palette controls, UV 1-only import, binary32 aspect-ratio limits, and explicit rejection
  of missing or incompatible fallback UVs. Mirrored-UV normal tangents and handedness are checked.
- Blender 5.2.3 `test_shader_preview.py`, `test_shader_profiles.py`, `test_workflow.py`,
  `test_fixtures.py`, `test_material_slots.py`, `test_texture_formats.py`, and
  `test_skeleton_blender.py`: **PASS**. The Cycles bake checks that the disabled interactive screen
  still displays its authored static fallback RGB `(0.2, 0.4, 0.6)` on the object.
- Blender 5.2.3 `build_material_test_scene.py`: **PASS**; the generated scene was non-empty and the
  temporary file was removed. Blender emitted dependency-cycle warnings, but all scripts exited 0.
- Blender 5.2.3 installed `adm_tools-1.10.0.zip` into an isolated temporary extension repository:
  **PASS**. The addon was enabled, the interactive material shader was selectable, and the surface
  assignment operator was registered. The temporary repository was removed without saving preferences.
- The initial [GitHub Actions run](https://github.com/BerretW/ADM/actions/runs/43574909424) failed
  fixture reproduction on Linux because the generated PNG depended on zlib's DEFLATE implementation.
  The generator now uses a fixed, validated PNG payload. The reproduction check passes with both
  zlib-ng and Blender's standard zlib, and a regression test simulates a different encoder.

These are local reference-implementation checks, not independent engine-renderer certification.
The Blender preview is static; runtime content and input remain the engine's responsibility. The pull
request checks report the latest remote GitHub Actions results.

## P12 vertex-control materials — local verification

- CI-equivalent Python unittest command (`test_container`, `test_draft4`, `test_skeleton_profiles`,
  `test_gputex`, `test_shader_math`): **85 passed, 1 skipped**. The skip is the Windows symlink
  permission case described below.
- Blender 5.2.3 `adm_blender/tests/test_shader_preview.py`: **PASS**. Cycles bakes verify palette
  sampling, wetness albedo/roughness, live driver updates, and exact dielectric/metallic F0 node
  outputs. It also verifies that changing reserved `COLOR_1` values does not affect the preview.
  The F0 sample produced metallic RGB `(0.10817, 0.20615, 0.30414)` and dielectric F0 `0.02586`.
- Blender 5.2.3 `adm_blender/tests/test_workflow.py`: **PASS**. Model and animation validation,
  extension binding, COLOR_0/COLOR_1/material-setting export/import, ADM_ANIM wetness values
  round-trip, and imported material STEP/LINEAR/CUBICSPLINE interpolation endpoints/midpoints.
- Blender 5.2.3 `test_fixtures.py`, `test_material_slots.py`, `test_texture_formats.py`, and
  `test_skeleton_blender.py`: **PASS**. The CI workflow now runs these with the shader-preview and
  workflow tests under Blender 5.2.4 after verifying the downloaded archive checksum; remote Actions
  execution has not yet been observed.
- Blender 5.2.3 `build_material_test_scene.py`: **PASS**, generated and saved a 20-swatch Core shader
  preview scene; the temporary `.blend` was verified non-empty and removed after the check.
- `python adm-standard/tools/run_tests.py`: **13 passed, 0 failed**.
- `python adm-standard/tools/build_shader_registry.py --check`: **PASS**, all 20 profiles.
- `py_compile` passed for all changed Python modules and tests.

These are reference implementation tests. Core 20 `COLOR_1` semantics are explicitly reserved with no
shading effect; independent-reader renderer conformance is not claimed. A new GitHub Actions run on
the updated branch has not yet been observed.

## 2026-11-14 CI fixture-generator failure and local verification

The failed GitHub Actions run [43532271476](https://github.com/BerretW/ADM/actions/runs/43532271476)
at commit `d1748684ab` failed in all four Windows/Ubuntu × Python 3.11/3.14 jobs at
`test_fixture_generator_is_self_contained`. The actual cause was
`adm-standard/tools/build_fixtures.py` opening a developer-local `/mnt/data/ADM-1.0-shadery-a-animace.zip`
that is not part of the repository; the script also ignored the test's `--output-dir`.

The generator now rebuilds valid and profile containers from their checked-in JSON manifests and
verified RAW chunk payloads, emits deterministic LF-terminated JSON, recreates the negative
container fixtures, and honors `--output-dir`. It no longer needs the external ZIP.

**Local verification (Windows, Python 3.14.7):**

- `python -m unittest adm_blender.tests.test_container.ContainerTests.test_fixture_generator_is_self_contained -v`: 1 passed.
- `python -m unittest adm_blender.tests.test_container -v`: 24 passed.
- CI-equivalent core command (`test_container`, `test_draft4`, `test_skeleton_profiles`, `test_gputex`,
  `test_shader_math`): 81 passed, 1 skipped. The skip is the symlink-escape test because this Windows
  environment denied symlink creation; the test reports that permission reason. Linux CI is expected
  to exercise the symlink case.
- `python adm-standard/tools/run_tests.py`: 13 passed, 0 failed.
- `python adm-standard/tools/build_shader_registry.py --check` and
  `python adm-standard/tools/test_shader_registry.py`: passed (20 profiles).
- `python adm-standard/tools/build_fixtures.py` followed by
  `git diff --exit-code -- adm-standard/fixtures`: passed; regenerated fixture bytes are unchanged.
- Python 3.11 was not installed locally. A post-fix GitHub Actions run across all four matrix entries
  is still required; no green remote run is claimed here.

**Command:** `python3 tools/run_tests.py`  
**Environment:** Python 3, standard library; run on 2026-11-13.

**Passed: 13/13 checks**

- 5 valid `.adm`/`.adm_anim` samples pass the container validator: `triangle.adm`, `triangle_split.adm`, `shader_layered.adm`, `catalog-only.adm_anim`, `shader_parameter_tracks.adm_anim`.
- 6 invalid samples are rejected: wrong header size, incorrect file size, invalid chunk offset, SHA-256 tampering, cyclic dependencies, missing explicit advanced-shader PBR fallback.
- Catalog metadata read by header+JSON access without loading chunk data.
- Split geometry example has two payload chunks; targeted retrieval reads only the requested 6-byte chunk, not the other payload chunk.

This 13-check standard-library suite covers only the container/reference fixtures. Feature-specific reference toolkit tests are listed below.

## Draft 0.4 P4 skeleton, animation and IK tests

Executed by the reference Blender toolkit, not by an independent implementation:

- `python -m unittest adm_blender.tests.test_skeleton_profiles adm_blender.tests.test_draft4 adm_blender.tests.test_gputex`: 45 tests, all passing.
  - Registry consistency with VRM 1.0, auto-mapping, missing/duplicate roles, extra bones, wrong parents, mirrored and non-T poses.
  - ADM-IK-1 validation and solver math, including exact reach bounds and the equal-length zero-distance singularity.
  - Compatibility levels, including canine→equine, canine→feline and humanoid→canine = INCOMPATIBLE.
- `blender -b --factory-startup --python adm_blender/tests/test_skeleton_blender.py`: all checks passing.
  - Retargeting the same `.adm_anim` onto two humanoids with different proportions and bone rolls: role world-rotation delta 0.0000°, hand position ≤ 7e-7 m relative to the scaled source.
  - Skeleton and skin round trip: bind matrices / IBMs within 5e-7, vertex weights exact.
  - IK preview: end effector within 2e-7 m of the target.
  - Combined skeletal + ARKit `jawOpen` animation.
  - Unsupported Blender constraints reported.
- Core validator requires every mapped humanoid role's correction to match the inverse serialized rest rotation and rejects humanoid reference-pose violations.
- `test_workflow.py`, `test_material_slots.py`, `test_texture_formats.py`, and `test_fixtures.py`: all passed under Blender 5.2.
- `python adm-standard/tools/run_tests.py`: 13/13 passed; `python adm-standard/tools/test_profiles.py`: 12/12 passed.

**Not covered:** independent semantic retarget/IK implementation, calibrated external T-pose corpus, animal anatomy approval, and GPU upload/rendering. Reference implementation tests are not certification.

## Draft 0.4 P3 GPU texture container tests

Executed by the reference Blender toolkit, not by an independent implementation:

- `python -m unittest adm_blender.tests.test_gputex`: 11 tests (NumPy).
  - KTX2 and DDS round trip for RGBA8/BC1/BC3 × sRGB/UNORM with mip sizes; exact BC1/BC3 block bit packing; sRGB-correct mip filtering.
  - Header fields (vkFormat, level index order and alignment, DFD, DX10 header).
  - Rejection of supercompression, cubemaps, arrays, BC7, trailing and truncated data; legacy DDS accepted only as authoring input.
  - Validator codes `IMAGE_FALLBACK_REQUIRED`, `IMAGE_FALLBACK_SIZE`, `IMAGE_COLORSPACE`.
- `blender -b --factory-startup --python adm_blender/tests/test_texture_formats.py`: all checks passing.
  - Blender's own DDS reader (OpenImageIO) decodes the toolkit's DDS output identically to the toolkit (RGBA8 exact, BC1/BC3 within 1 LSB). This is the only cross-implementation check.
  - The PNG default converts JPEG, DDS and KTX2 sources to PNG with identical pixels; *Keep PNG/JPEG* keeps the JPEG bytes.
  - KTX2/DDS export: the correct sRGB/UNORM variant per role, mips, primary vs PNG fallback (RGBA8 exact, BC mean error ≤ 12/255), validator clean, import resolves the fallback.

**Not covered:** validation by the official KTX-Software `ktx validate` tool and GPU upload tests.

## Draft 0.4 P1 mechanical profile tests

Added separate profile structural validator, example vehicle, firearm and accessory files, and example mechanical component animation libraries. `tools/test_profiles.py` checks role constraints, frame axes and basic math, and `tools/container.py` checks container validity/hashes. **This does not constitute full certification**: independent Blender round-trip, full skeletal/mechanical retargeting, kinematic endpoint golden files and renderer/LOD semantics remain to be tested.
