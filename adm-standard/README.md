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

Uses Python 3.9+ standard library. **Does not test renderer equivalence, ZSTD, semantic animation evaluation, retargeting, complete IK, ARKit52, KTX2 codec variants, or full Blender round-trip**. Those cases remain mandatory before 1.0 can be ratified.

## Major design decisions

- A file starts with an indexable, noncompressed JSON manifest and a directory of independently accessible chunks.
- Small viewers can implement basic PBR and skip optional shader technology.
- Every advanced material contains explicitly serialized portable PBR fallback fields.
- `AMA0` animation libraries store searchable clip descriptions and may animate bones, morph targets, expressions and numeric shader/PBR fields.
- Humanoid bone roles follow VRM 1.0 concepts; exact solver/test vectors require further conformance work.
- Vehicle/weapon roles are now defined in **normative annexes** `profiles/vehicle.car.v1.md` and `profiles/weapon.firearm.v1.md`. The profiles are specified but **not yet independently certified**. No gameplay behavior is encoded.

## Open issues preventing certification

1. Complete normative animal profiles (currently PROVISIONAL proposals, see `profiles/animal.quadruped.v1.md`), the open points in `SPEC_GAPS.md`, plus independent semantic certification fixtures for the newly specified vehicle/weapon profiles.
2. Full shader-registry publication and shader-reference rendering tests.
3. A frozen supported KTX2/Basis Universal subset with actual fixtures.
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

## Skeleton profile registry (P2)

- `profiles/skeleton-profiles.json`: machine-readable registry of roles, parents, required flags, pose checks, and IK/socket templates, with each profile's `status`.
- `profiles/humanoid.vrm1.md`: VRM 1.0 humanoid. Role data is normative; the ADM-REF-NORM, IK, socket and facial conventions are PROPOSED. Tests `HUM-001..006`.
- `profiles/animal.quadruped.v1.md`: generic quadruped, canine, feline and equine. **PROVISIONAL, not registered, not certifiable.** Tests `QDR-001..004`.
- `SPEC_GAPS.md`: unresolved specification points and the reference toolkit's interim behaviour.

These tests are executed by the reference Blender toolkit (`adm_blender/tests/test_skeleton_profiles.py`, `test_skeleton_blender.py`). An independent second implementation does not exist yet.
