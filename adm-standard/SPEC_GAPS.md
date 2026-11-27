# ADM 1.0 Development / Experimental: Coverage and Open Work

ADM 1.0 is an open, implementation-independent standard in development. Its current normative text
defines exact, testable requirements, but the project may make incompatible changes before declaring
a stable public release. This register distinguishes implemented, partial and unverified
capabilities; it does not claim that reference-implementation tests prove interoperability.

## Shader development-change control

On 2026-11-15 the shader registry and referenced contracts were reissued after development
definitions had changed under the same identities. This history explains the retained
`shaders/freeze-2026-11-15.json`; that file records the published state at that date and is no longer
a rule that blocks development changes. Earlier development assets are not automatically migrated.

The former freeze mechanism prevented intentional edits to every existing `(shader.id, version)` and
its contract text. It also required new shader identities and contract text to be added to an
append-only hash baseline, even during experimental development. Those compatibility constraints
are removed. Registry generation, ID/schema/default validation, and CI checks against the pull
request or push base remain in place.

For every shader registry or referenced-contract change, CI compares the change with the base
revision. `shaders/revisions.json` must identify each changed profile and contract, state why it
changed, and link to a changelog heading. CI fails if a changed item is missing from the new record,
if a record claims an unchanged item, or if an earlier record is edited or removed. Reviewers
approve the change through the normal Git review process. The comparison is skipped when no base
revision is available; local registry integrity and revision-record checks still run.

The shader contract version still identifies compatibility-relevant meaning. Increment its major
version for an incompatible contract change; the experimental process does not require the project
to preserve or implement superseded versions. A reader uses the exact declared version, or reports
the normative fallback where the contract permits one.

## Current design decisions

| ID | Area | Normative disposition |
|---|---|---|
| `SPEC_GAP-SKEL-SCHEMA` | §11 profile schema | The schema lists `targetHeight`, `referenceCorrection` and `rigId`, and defines their types and use. |
| `SPEC_GAP-ANIM-LIB-SCHEMA` | §13 / §16 library fields | The exact allowed and required library keys now include `revision`, `namespace`, `motionScale`, `sourceHeight` and `rootMotionSource`, with validation dependencies and units. Unknown fields are invalid. |
| `SPEC_GAP-REFPOSE-TOL` | §11 / HUM-002..004 | Humanoid directed-pose checks use a 25° inclusive maximum; exceeding it invalidates SEMANTIC binding. Left/right facing is a categorical check. The threshold is normative; empirical calibration remains a certification task. |
| `SPEC_GAP-CORRECTION` | §11.2 / §16 | `ADM-REF-NORM-1` defines each mapped humanoid correction as the inverse of the parent-to-child product of serialized local rest rotations. Corrections are required for every mapped role in SEMANTIC humanoid binding; no identity fallback is allowed. |
| `SPEC_GAP-LOCAL-AXES` | §11.2 | Local axes remain unconstrained; the normalized correction algorithm defines how semantic rotation deltas are applied independently of bone roll. |
| `SPEC_GAP-FORWARD` | §2 / §11 | ADM model space is +Y up, +X anatomical right, −Z forward. Source formats with a different basis are converted consistently across geometry, transforms, skinning, animation, IK and attachments before validation. |
| `SPEC_GAP-ROOT-ROLE` | §11 / §14 / §16 | `root` is not a VRM role. Humanoid translation and v1 root-motion extraction use semantic `hips`; v1 EXTRACT requires `library.rootMotionSource:"hips"`. No root role is synthesized. |
| `SPEC_GAP-IK-MULTI` | §20 | ADM-IK-1 is explicitly two-bone. Longer chains and distal hoof/toe contact require a separately registered future capability. |
| `SPEC_GAP-IK-LIMITS` | §20 | Joint limits, stretch, twist distribution, pole-angle controls, FABRIK/CCD and longer chains are outside ADM-IK-1. The core schema does not accept such fields; authoring tools must report unsupported DCC settings rather than silently export them. |
| `SPEC_GAP-IK-ZERO-FOLD` | §20.1 | The solver clamps to the exact physical reach interval. At the equal-length zero-distance singularity it preserves the neutral mid position and places the endpoint at the root. The reference solver and boundary test use this rule. |
| `SPEC_GAP-PROFILE-TEMPLATES` | §11 registry | The root/profile/role/reference-pose/IK-template/socket-template schema for `profiles/skeleton-profiles.json` is specified. Templates are authoring defaults only; ADM files store explicit resolved roles, IK chains and attachments. |
| `SPEC_GAP-RETARGET-MAP` | §11 registry | ADM 1.0 registers no cross-profile map format or mapping. `retargetMaps` must be empty; different profile IDs are INCOMPATIBLE. A future mapping requires a reviewed versioned profile-pair annex with explicit role transforms and fixtures. |
| `SPEC_GAP-CUSTOM-PROFILE` | §11 / §28 | Unregistered reverse-DNS versioned IDs are EXACT_ONLY. Semantic use requires a complete published annex and machine-readable registry entry with role, hierarchy, pose, correction, retarget, IK/socket and fixture rules. |
| `SPEC_GAP-KTX2-SUBSET` | §8.6–§8.7 | Version 1 remains RGBA8/BC1/BC3; version 2 capabilities add R8/R16/BC4/BC5/BC7 with explicit channel and precision rules. Tests cover selected independent BC7 vectors and R16 and GPU-source round trips, including a packaged Blender candidate on Windows. Official KTX validation, GPU uploads, other platforms, and full independent v2 conformance remain unverified. |
| `SPEC_GAP-BC5-CORE-FALLBACK` | §8 / §8.7 normal fallback | A standalone core PBR normal cannot retain a BC5 primary and also supply reconstructed RGB in its single fallback while §8.7 requires the two-channel fallback. Blender reports the limitation. World Tile uses separate shader and core PBR textures where a layered shader provides both references. |
| `SPEC_GAP-TERRAIN-PALETTE` | Layered terrain export | The four-layer primitive cannot represent five simultaneously nonzero surfaces. Per-triangle trimming can cause visible seams, including at tile or LOD boundaries; World Tile reports the conflict. |
| `SPEC_GAP-TERRAIN-CONTROL-MAP` | `ADM_terrain_control_map_v1@1.0.0` | The contract, reference weight/coordinate evaluation, validation, and independent vectors are present. World Tile authoring/rendering and Blender rendering are not implemented; Blender rejects required Control Map data. Filtered mip/border continuity and actual renderer seams remain unverified. Control Maps retain the four-local-slot limit and do not provide exact five-plus-surface representation. |
| `SPEC_GAP-TERRAIN-MACRO-COLOR` | `ADM_terrain_macro_color_v1@1.0.0` | The contract, reference color/coordinate evaluation, structural and image validation, and independent vectors are present. World Tile authoring/rendering and Blender rendering are not implemented; Blender rejects required Macro Color data. Filtered mip/border continuity and actual renderer output remain unverified. |
| `SPEC_GAP-TERRAIN-MACRO-NORMAL` | `ADM_terrain_macro_normal_v1@1.0.0` | The contract, BC5/RNM/frame reference math, profile/image/sampler validation, and independent vectors are present. World Tile and Blender rendering/authoring are not implemented; Blender rejects required Macro Normal data. Filtered mip/border continuity, cross-frame rendered output, and portable-fallback equivalence remain unverified. |
| `SPEC_GAP-SHADER-CORE20` | Shader registry and renderer | The registry has the registered shader IDs, schemas and contracts. Blender preview graphs apply vertex-control tint, normal strength, wetness color/roughness, and exact dielectric/metallic F0 using separate Principled lobes; Cycles bake tests verify the F0 node outputs. Extension-level animation bindings, Core 20 `@1.0.0` reserved/no-effect `COLOR_1` contracts, separately versioned `@2.0.0` mask contracts, and model/material round-trip tests are present. Not every shader has an independently bake-tested renderer, Skin/Fur/Fabric remain approximations, and independent renderer interoperability is unverified. Add focused renderer bakes and validate with an independent implementation before claiming full conformance. See the shader development-change control above. |
| `SPEC_GAP-INTERACTIVE-BINDING` | Interactive display identity, UV and appearance | `ADM_interactive_surfaces_v1@1.0.0` defines unique surface IDs, node/primitive/UV references, hit coordinates and optional aspect metadata. `adm.surface.interactive@1.0.0` defines runtime color/alpha, lit/unlit, off state and portable fallback. Blender and both manifest validators exercise the data; independent runtime rendering remains unverified. |
| `SPEC_GAP-HUMANOID-SOCKETS` | Equipment attachment semantics | `ADM_humanoid_sockets_v1@1.0.0` defines 20 stable humanoid mount names, role ancestry, model-space frame axes, asset-authored positions and `mount.root` composition. The reference validator and Blender export/import tests cover the contract. Independent engine interoperability and equipment-fit guarantees remain unverified. |

## Capability status

- **Implemented:** a specific behavior has a runnable reference test and recorded fixture evidence.
  This does not imply full feature coverage or independent interoperability.
- **Partial:** the repository implements or tests part of a capability, but its catalog lists
  required fixture data or expected results that are still missing.
- **Proposed:** the data is non-normative and not accepted as an ADM 1.0 profile until a documented
  development change adopts it.

The [reference-test catalog](fixtures/reference-catalog.json) applies these statuses per test
category. It records only real fixture files and runnable tests; entries under `requiredFixtureData`
and `requiredExpectationFields` describe work that has not been supplied.

## Excluded proposals (not part of ADM 1.0)

The quadruped profile proposal and its machine-readable records are retained under `proposals/`.
They are not entries in the current ADM 1.0 profile registry and MUST NOT be used for semantic
binding. Adoption requires a reviewed change to the specification, registry, validator and fixtures.

| Proposal | ADM 1.0 disposition | Work required for possible future adoption |
|---|---|---|
| `animal.*.v1` registry | Excluded; not registered | Review anatomy and role hierarchies per species; publish versioned profiles and positive/negative fixtures. |
| Quadruped `STAND` pose | Excluded; diagnostics only in the proposal | Approve a reference pose and calibrated direction/side tolerances for each adopted profile. |
| Cross-species retargeting | Not defined or permitted | Publish explicit profile-pair mappings, transforms, scaling rules and numerical fixtures. |

## Independent conformance and certification work

- Blender preserves `modelProfiles` and `componentRoles`, and its core validator covers the registered
  vehicle/firearm metadata and role-frame checks. Blender animation libraries now author and import
  `target.kind=component` tracks using rest-relative deltas, resolve profile roles against the chosen
  Model Root, and reject sampled values outside profile axes or declared limits. A Blender round-trip
  test covers export/import evaluation and profile-limit rejection. This remains reference-implementation
  coverage; independent mechanical-profile evaluation and engine interoperability are not certified.
- No independent second implementation currently verifies ADM semantic humanoid retargeting or the full ADM-IK-1 solver. The Blender tests are reference-implementation tests only.
- Canonical `rigId`, humanoid semantic retarget and IK need versioned byte/numerical fixtures consumed by an independent validator before certification.
- The KTX2 subset has not been checked by the official KTX-Software validator or by GPU upload tests; Blender/OpenImageIO independently reads the emitted DDS subset only.
- The bundled tests alone do not establish independently verified full ADM 1.0 conformance.
- The external-image and physical-surface extensions have structural and Blender workflow coverage, including external texture resolution and per-triangle FACE-attribute round-trip. Security-edge fixtures (including symlink escape, failure cleanup, and all external image encodings) and independent-reader interoperability remain certification gates.
- Interactive screens have numerical reference values and Blender metadata round trips, but no second
  independent runtime renderer or engine-level hit-test certification. Blender previews the authored
  static fallback only; runtime content and input remain the engine's responsibility.
- Humanoid socket IDs and frames are normative, but positions are authored per model. The registry does
  not guarantee cross-body fit or define inventory compatibility, equipment animation, or engine-side
  attachment policy; no independent reader has yet verified the extension.
