# ADM 1.0 — Draft 0.4 Standard Kit

**Status:** working draft, NOT a ratified standard. **Prepared:** 2026-11-13.

This kit contains a rewritten integrated specification for the proposed **native, chunk-streamable** game-model format `.adm` and the independent animation-library format `.adm_anim`. Models are **asset descriptions**, not game entities. The draft is **not binary compatible with Draft 0.3**. No existing implementations are required to preserve Draft 0.3 compatibility.

## Contents

- `ADM-1.0-SPEC.md`: normative *proposal*, including exact 64-byte header, 80-byte chunk directory entries, chunk-addressed bufferViews, safety rules, model data, animation libraries, morphs, two-bone IK, shaders and PBR fallback.
- `fixtures/valid/`: 5 small binary reference examples and their readable JSON manifests.
- `fixtures/invalid/`: 6 intentionally corrupted/invalid files.
- `tools/container.py`: standalone Python standard-library-only writer, container checker and minimal seek/range reader.
- `tools/build_fixtures.py`: regenerates all valid/invalid binaries from the checked-in JSON manifests and explicit sample payloads; no external archive or private development paths are needed.
- `tools/run_tests.py`: reproducible tests for the supplied files.
- `TEST-RESULTS.md`: executed tests and known gaps.
- `CHANGELOG.md`: changes since Draft 0.3.

## Run tests

```bash
python3 tools/run_tests.py
python3 tools/container.py fixtures/valid/triangle.adm
```

To regenerate the reference corpus, run `python3 tools/build_fixtures.py`.
Use `--output-dir PATH` to generate a separate copy instead of rewriting the checked-in binaries.

Uses Python 3.9+ standard library. **Does not test renderer equivalence, ZSTD, semantic animation evaluation, retargeting, complete IK, ARKit52, KTX2 codec variants, or full Blender round-trip**. Those cases remain mandatory before 1.0 can be ratified.

## Major design decisions

- A file starts with an indexable, noncompressed JSON manifest and a directory of independently accessible chunks.
- Small viewers can implement basic PBR and skip optional shader technology.
- Every advanced material contains explicitly serialized portable PBR fallback fields.
- `AMA0` animation libraries store searchable clip descriptions and may animate bones, morph targets, expressions and numeric shader/PBR fields.
- Humanoid bone roles follow VRM 1.0 concepts; exact solver/test vectors require further conformance work.
- Optional semantic vehicle/weapon profile names are reserved, not yet certified. No gameplay behavior is encoded.

## Open issues preventing certification

1. Complete normative profile tables for car/weapon/animal assets.
2. Full shader-registry publication and shader-reference rendering tests.
3. A frozen supported KTX2/Basis Universal subset with actual fixtures.
4. Fully independent reader/writer and per-feature semantic conformance fixtures.
5. Production streaming/caching stress tests, decompressor resource-limit tests.

The specification governs the data format; engine scheduling, gameplay behavior, renderer backend and network replication stay outside its scope.

## License

The specification, documentation in this directory and reference fixtures are dedicated under
[CC0-1.0](LICENSE). The Python reference tools are separately licensed under [MIT](tools/LICENSE).
