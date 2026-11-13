# ADM 1.0 — Draft 0.4 Standard Kit

**Status:** working draft, NOT a ratified standard. **Prepared:** 2026-11-13.

This kit contains a rewritten integrated specification for the proposed **native, chunk-streamable** game-model format `.adm` and the independent animation-library format `.adm_anim`. Models are **asset descriptions**, not game entities. The draft is **not binary compatible with Draft 0.3**. No existing implementations are required to preserve Draft 0.3 compatibility.

## Contents

- `ADM-1.0-SPEC.md`: normative *proposal*, including exact 64-byte header, 80-byte chunk directory entries, chunk-addressed bufferViews, safety rules, model data, animation libraries, morphs, two-bone IK, shaders and PBR fallback.
- `fixtures/valid/`: 5 small binary reference examples and their readable JSON manifests.
- `fixtures/invalid/`: 6 intentionally corrupted/invalid files.
- `tools/container.py`: standalone Python standard-library-only writer, container checker and minimal seek/range reader.
- `tools/build_fixtures.py`: regenerates valid test data from earlier Draft 0.3 fixtures **only when the older ZIP is available at the development path**; the packaged fixtures are already generated and no older files are needed to run tests.
- `tools/run_tests.py`: reproducible tests for the supplied files.
- `TEST-RESULTS.md`: executed tests and known gaps.
- `CHANGELOG.md`: changes since Draft 0.3.

## Run tests

```bash
python3 tools/run_tests.py
python3 tools/container.py fixtures/valid/triangle.adm
```

`tools/run_tests.py` uses Python 3.9+ standard library. It is the container-kit test only; it does not test renderer equivalence, full animation evaluation, complete semantic/IK conformance, ARKit52 or full Blender round-trip. Additional reference toolkit tests are recorded in `TEST-RESULTS.md`.

## Major design decisions

- A file starts with an indexable, noncompressed JSON manifest and a directory of independently accessible chunks.
- Small viewers can implement basic PBR and skip optional shader technology.
- Every advanced material contains explicitly serialized portable PBR fallback fields.
- The machine-readable shader registry contains all 20 requested profile IDs and their typed parameter schemas.
  Blender renders a viewport preview for every official profile (skin, fur and fabric are approximations); custom shaders report PBR fallback. See `SPEC_GAPS.md`.
- `AMA0` animation libraries store searchable clip descriptions and may animate bones, morph targets, expressions and numeric shader/PBR fields.
- Humanoid bone roles follow VRM 1.0; ADM-REF-NORM-1 and the ADM-IK-1 two-bone solver are now specified, but independent conformance work remains.
- Vehicle/weapon roles are now defined in **normative annexes** `profiles/vehicle.car.v1.md` and `profiles/weapon.firearm.v1.md`. The profiles are specified but **not yet independently certified**. No gameplay behavior is encoded.

## Open issues preventing certification

1. Approve normative animal profiles (currently PROVISIONAL proposals, see `profiles/animal.quadruped.v1.md`) and publish independent semantic certification fixtures for the vehicle/weapon profiles.
2. Full shader-registry publication and shader-reference rendering tests.
3. Independent KTX2/DDS fixtures for the §8.6 subset, checked by a second implementation (Basis Universal remains outside 1.0).
4. Fully independent reader/writer and per-feature semantic conformance fixtures.
5. Production streaming/caching stress tests, decompressor resource-limit tests.

The specification governs the data format; engine scheduling, gameplay behavior, renderer backend and network replication stay outside its scope.

## Vehicle and firearm profile annexes (P1)

- `profiles/vehicle.car.v1.md` — normative role, axle, wheel, steering and hinge contracts.
- `profiles/weapon.firearm.v1.md` — receiver, muzzle, modular accessory mounts and visual component animation.
- `fixtures/profiles/*.adm` — structural/metadata example assets; intentionally may contain no renderable mesh.
- `fixtures/profiles/*.adm_anim` — mechanical component animation examples with real F32 samples.
- `tools/test_profiles.py` — structural validation and numerical smoke checks (not a full reference renderer/evaluator).

Run `python3 tools/test_profiles.py` alongside the existing `python3 tools/run_tests.py`.

## Skeleton profile registry (P4)

- `profiles/skeleton-profiles.json`: machine-readable registry of roles, parents, required flags, pose checks, and IK/socket templates, with each profile's `status`.
- `profiles/humanoid.vrm1.md`: VRM 1.0 humanoid. Role data, ADM-REF-NORM-1 corrections and reference-pose rules are normative. Tests `HUM-001..006`.
- `profiles/animal.quadruped.v1.md`: generic quadruped, canine, feline and equine. **PROVISIONAL, not registered, not certifiable.** Tests `QDR-001..004`.
- `SPEC_GAPS.md`: resolved ambiguity dispositions plus the deliberately retained approval and certification blockers.

These tests are executed by the reference Blender toolkit (`adm_blender/tests/test_skeleton_profiles.py`, `test_skeleton_blender.py`). An independent second implementation does not exist yet.

## Shader registry (P8)

- `shaders/registry.json` contains the 20 requested versioned shader IDs and typed parameter schemas.
- `shaders/*.v1.md` contains a contract annex for each non-core profile; §8 retains the existing core and layered semantics.
- `tools/build_shader_registry.py --check` detects drift between Blender's normative parameter tables and the generated registry.
- `tools/test_shader_registry.py` validates IDs, parameter defaults and annex presence. `adm_blender/tests/test_shader_math.py` checks independent scalar/vector reference values.
- Blender round-trip tests preserve all 20 identities and schemas, but most specialist viewport node builders remain unimplemented and fall back explicitly to PBR. This is not full Core 20 renderer conformance; see `SPEC_GAPS.md`.
