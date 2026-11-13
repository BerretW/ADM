# Draft 0.4 executed test report

**Command:** `python3 tools/run_tests.py`  
**Environment:** Python 3, standard library; run on 2026-11-13.

**Passed: 13/13 checks**

- 5 valid `.adm`/`.adm_anim` samples pass the container validator: `triangle.adm`, `triangle_split.adm`, `shader_layered.adm`, `catalog-only.adm_anim`, `shader_parameter_tracks.adm_anim`.
- 6 invalid samples are rejected: wrong header size, incorrect file size, invalid chunk offset, SHA-256 tampering, cyclic dependencies, missing explicit advanced-shader PBR fallback.
- Catalog metadata read by header+JSON access without loading chunk data.
- Split geometry example has two payload chunks; targeted retrieval reads only the requested 6-byte chunk, not the other payload chunk.

**Not covered:** real rendering, visual comparison, full shader semantics, runtime IK solving, morph/skin numerical output, asset-loading concurrency, ZSTD, KTX2, alpha rendering, advanced semantic validation, malformed JSON depth/security fuzzing and interoperability between independent toolchains. The bundled validator is an illustrative **subset validator**, not a certification harness.

## Draft 0.4 P2 skeleton profile tests

Executed by the reference Blender toolkit, not by an independent implementation:

- `python -m unittest adm_blender.tests.test_skeleton_profiles`: 25 pure-Python tests.
  - Registry consistency with VRM 1.0, auto-mapping, missing/duplicate roles, extra bones, wrong parents, mirrored and non-T poses.
  - ADM-IK-1 validation and solver math.
  - Compatibility levels, including canine→equine, canine→feline and humanoid→canine = INCOMPATIBLE.
- `blender -b --factory-startup --python adm_blender/tests/test_skeleton_blender.py`: 109 checks, all passing.
  - Retargeting the same `.adm_anim` onto two humanoids with different proportions and bone rolls: role world-rotation delta 0.0000°, hand position ≤ 7e-7 m relative to the scaled source.
  - Skeleton and skin round trip: bind matrices / IBMs within 5e-7, vertex weights exact.
  - IK preview: end effector within 2e-7 m of the target.
  - Combined skeletal + ARKit `jawOpen` animation.
  - Unsupported Blender constraints reported.

**Not covered:** independent interoperability, calibrated T-pose fixtures, animal anatomy review, and UI interaction.

## Draft 0.4 P1 mechanical profile tests

Added separate profile structural validator, example vehicle, firearm and accessory files, and example mechanical component animation libraries. `tools/test_profiles.py` checks role constraints, frame axes and basic math, and `tools/container.py` checks container validity/hashes. **This does not constitute full certification**: independent Blender round-trip, full skeletal/mechanical retargeting, kinematic endpoint golden files and renderer/LOD semantics remain to be tested.
