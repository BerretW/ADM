# Mission verification record

## Completed so far
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
