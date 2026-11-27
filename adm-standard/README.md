# ADM 1.0 Development / Experimental

**Status:** Open standard, development edition. ADM 1.0 defines exact, normative rules for the current revision, but those rules are not publicly stable. Breaking changes are allowed until a separate decision declares a stable release.

This kit contains the normative specification for the **native, chunk-streamable** game-model
format `.adm` and independent animation-library format `.adm_anim`. ADM is implementation- and
engine-independent. Models are **asset descriptions**, not game entities. Historical development
files may be incompatible and are not automatically migrated.

The file header identifies the current binary format as `1.0`; extension contracts, shader
contracts and the Blender add-on have independent versions. See [§28](ADM-1.0-SPEC.md#28-development-version-policy-extension-registry-and-governance)
for when to change each version. The historic shader hash snapshot records its 2026-11-15
publication state; CI now checks current changes against Git and requires a linked development
record instead of freezing published entries.

## Contents

- `ADM-1.0-SPEC.md`: current normative specification, including the exact 64-byte header, 80-byte chunk directory entries, chunk-addressed bufferViews, safety rules, model data, animation libraries, morphs, two-bone IK, shaders and PBR fallback.
- `fixtures/valid/`: binary reference examples and their readable JSON manifests, including the
  two-display `interactive_terminal.adm`.
- `fixtures/invalid/`: intentionally corrupted/invalid container and interactive-surface files.
- `fixtures/semantic_invalid/`: container-valid shader-mask assets that violate the required
  vertex-control extension, strength bounds or normalized channel range.
- `fixtures/expectations/shader_masks_v2.json`: independent `COLOR_1` vectors and channel maps for
  the 20 versioned shader profiles.
- `fixtures/expectations/interactive_terminal.expected.json`: explicit surface, hit-test and runtime
  color/alpha reference values.
- `tools/container.py`: standalone Python standard-library-only writer, container checker and minimal seek/range reader.
- `tools/build_fixtures.py`: regenerates fixtures from checked-in manifests and verified chunk payloads.
- `tools/build_interactive_fixture.py --check`: rebuilds the interactive fixture from explicit source
  geometry and image data and compares its bytes.
- `tools/test_interactive_surfaces.py`: independent fixture and numerical UV/color/alpha checks.
- `tools/test_independent_conformance.py`: bounded-input, strict-JSON and cross-reader checks for
  published fixtures; it does not certify full semantic conformance.
- `tools/test_shader_vertex_masks.py`: independent numerical vectors and v2 profile-channel checks;
  it does not import Blender's implementation.
- `shaders/freeze-2026-11-15.json`: historical hash record of the shader publication on 2026-11-15.
- `shaders/revisions.json` and `tools/check_shader_registry_changes.py`: records intentional
  contract edits; CI detects changed but unrecorded profiles and contracts.
- `fixtures/reference-catalog.json`: machine-readable coverage, existing reference assets, and
  missing fixture data and expectations for eight test categories.
- `tools/run_tests.py`: reproducible tests for the supplied files.
- `TEST-RESULTS.md`: executed tests and known gaps.
- `CHANGELOG.md`: development and publication history.

## Run tests

```bash
python3 tools/run_tests.py
python3 tools/test_profiles.py
python3 tools/test_independent_conformance.py
python3 tools/test_shader_vertex_masks.py
python3 tools/test_shader_registry.py
python3 tools/check_shader_registry_changes.py
python3 tools/test_reference_catalog.py
python3 tools/container.py fixtures/valid/triangle.adm
```

`tools/run_tests.py` uses Python 3.9+ standard library. It is the container-kit test only; it does not test renderer equivalence, full animation evaluation, complete semantic/IK conformance, ARKit52 or full Blender round-trip. Additional reference toolkit tests are recorded in `TEST-RESULTS.md`.

## Versioning and development policy

The current edition is **ADM 1.0 – Development / Experimental**. The requirements remain
normative for this revision, but future changes may be incompatible. The project does not promise
support for historical development files or automatic migration. A stable public version will be
announced only by a separate decision.

The standard edition, file-format header, each extension, each shader contract, and the Blender
add-on use separate version identifiers. Raise a version only when it communicates an actual
compatibility boundary; do not retain obsolete implementations only to support an earlier
development asset. See [the version policy](ADM-1.0-SPEC.md#28-development-version-policy-extension-registry-and-governance).

## Major design decisions

- A file starts with an indexable, noncompressed JSON manifest and a directory of independently accessible chunks.
- Small viewers can implement basic PBR and skip optional shader technology.
- Every advanced material contains explicitly serialized portable PBR fallback fields.
- The machine-readable shader registry preserves Core 20 `1.0.0` profiles, adds 20 compatible
  `2.0.0` `COLOR_1` profiles, the interactive surface and a two-layer surface profile. Blender previews
  the registered mask operations; skin, fur and fabric remain approximations. Interactive surfaces
  preview their authored static PBR fallback; custom shaders report PBR fallback. See `SPEC_GAPS.md`.
- `AMA0` animation libraries store searchable clip descriptions and may animate bones, morph targets, expressions and numeric shader/PBR fields.
- Humanoid bone roles follow VRM 1.0; ADM-REF-NORM-1 and the ADM-IK-1 two-bone solver are now specified, but independent conformance work remains.
- Vehicle/weapon roles are defined in the **normative annexes** `profiles/vehicle.car.v1.md` and `profiles/weapon.firearm.v1.md`. Independent profile certification is a separate activity. No gameplay behavior is encoded.
- The quadruped profile proposal is kept under `proposals/` and is **outside ADM 1.0**; it is not present in the normative skeleton registry.

## Conformance status

The repository's fixtures and validators cover only a subset of §25/§30. The reference
implementation is not evidence of interoperability, and no independent second implementation has
verified these fixtures. The numerical conformance corpus, renderer/IK interoperability evidence
and production stress tests remain incomplete. See [`SPEC_GAPS.md`](SPEC_GAPS.md) and the
[reference-test catalog](fixtures/reference-catalog.json) for implemented checks, partial
coverage, untested behavior and required fixture data. The expected values are engine-independent;
the catalog adds no engine-specific ADM metadata. A stable public version will be declared only by
a separate decision.

The specification governs the data format; engine scheduling, gameplay behavior, renderer backend and network replication stay outside its scope.

## Vehicle and firearm profile annexes

- `profiles/vehicle.car.v1.md` — normative role, axle, wheel, steering and hinge contracts.
- `profiles/weapon.firearm.v1.md` — receiver, muzzle, modular accessory mounts and visual component animation.
- `fixtures/profiles/*.adm` — structural/metadata example assets, including a renderable mesh that
  samples all five `COLOR_1` mask levels; mechanical examples may contain no renderable mesh.
- `fixtures/profiles/*.adm_anim` — mechanical component animation examples with real F32 samples.
- `tools/test_profiles.py` — structural validation and numerical smoke checks (not a full reference renderer/evaluator).

Run `python3 tools/test_profiles.py` alongside the existing `python3 tools/run_tests.py`.

## Skeleton profile registry and sockets

- `profiles/skeleton-profiles.json`: current ADM 1.0 registry of the normative humanoid profile and exact-only generic profile.
- `profiles/humanoid.vrm1.md`: VRM 1.0 humanoid. Role data, ADM-REF-NORM-1 corrections and reference-pose rules are normative. Tests `HUM-001..006`.
- `extensions/ADM_humanoid_sockets_v1.md`: normative equipment socket names, role ancestry,
  model-space frames and `mount.root` composition for `ADM-HUMANOID-SOCKETS-1`.
- `extensions/ADM_joint_display_v1.md`: normative joint display frames and bone endpoints for
  exact cross-tool skeleton editing under `ADM-JOINT-DISPLAY-1`.
- `extensions/ADM_animation_timing_v1.md`: normative project and per-clip frame-rate and clip-range
  metadata for exact authoring-timeline round trips under `ADM-ANIMATION-TIMING-1`.
- `fixtures/expectations/humanoid_sockets.expected.json`: exact registry-to-socket-name expectation used
  by the reference tests.
- `proposals/animal.quadruped.v1.md` and `proposals/skeleton-profile-proposals.json`: non-normative animal profile proposals, outside ADM 1.0.
- `SPEC_GAPS.md`: current decisions, excluded proposals and implementation/certification limitations.

These tests are executed by the reference Blender toolkit (`adm_blender/tests/test_skeleton_profiles.py`, `test_skeleton_blender.py`). They are not independent certification.

## Shader registry

- `shaders/registry.json` contains the Core 20, interactive and two-layer shader profiles and typed schemas.
- `shaders/adm.surface.two_layer.v1.md` defines the grayscale-mask two-layer PBR profile.
- `shaders/ADM_shader_vertex_masks_v2.md` defines the `COLOR_1` contracts for profile 2.0.0.
- `shaders/ADM_shader_vertex_masks_v2_1.md` defines PBR metallic-roughness 2.1.0 edge wear and dirt.
- `shaders/ADM_layered_height_profiles_v1.md` defines the advanced layered AO, height,
  height-blend, parallax, and POM contracts and their exact sampling algorithms.
- `shaders/*.v1.md` contains a contract annex for each non-core profile; §8 retains the existing core and layered semantics.
- `tools/build_shader_registry.py --check` detects drift between Blender's normative parameter tables and the generated registry.
- `tools/test_shader_registry.py` validates IDs, parameter defaults and annex presence. `adm_blender/tests/test_shader_math.py` checks independent scalar/vector reference values.
- Blender round-trip tests preserve the registered identities and schemas. The interactive shader uses
  static fallback preview rather than runtime rendering. This is not independent renderer conformance;
  see `SPEC_GAPS.md`.

## Terrain material techniques

These techniques operate at different stages and are not interchangeable:

- **Surface Noise** is a World Tile authoring operation that varies generated
  surface weights in world space. It is not a runtime ADM shader requirement.
- **`COLOR_1` blending** stores layer weights in vertex channels. A primitive's
  material identifies the surface assigned to each channel.
- **Height Based Blending** adjusts the base layer weights using the sampled
  height of each active layer. It does not move terrain vertices.
- **Parallax** offsets material texture coordinates according to the view direction
  and sampled height. **POM** traces multiple height samples to estimate an
  intersection and may cost more than a single parallax sample.
- **Geometric terrain heightmap** changes terrain vertex positions and silhouettes;
  it is separate from the material height textures used by blending and parallax.

For exact inputs, algorithms, bounds, and fallback rules, see the
[layered material contracts](shaders/ADM_layered_height_profiles_v1.md).
