# Draft 0.4 executed test report

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
