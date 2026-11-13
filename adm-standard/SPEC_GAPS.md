# ADM 1.0 Draft 0.4 — specification gap disposition

This register records ambiguities discovered while implementing the reference Blender toolkit and the normative disposition added in revision P4. A closed gap means the current Draft 0.4 behavior is explicit; it does not imply independent conformance certification. Items retained below are deliberately not filled with unapproved binary or semantic conventions.

## Resolved in the specification

| ID | Area | Normative disposition |
|---|---|---|
| `SPEC_GAP-SKEL-SCHEMA` | §11 profile schema | The schema lists `targetHeight`, `referenceCorrection` and `rigId`, and defines their types and use. |
| `SPEC_GAP-ANIM-LIB-SCHEMA` | §13 / §16 library fields | The exact allowed and required library keys now include `revision`, `namespace`, `motionScale`, `sourceHeight` and `rootMotionSource`, with validation dependencies and units. Unknown fields are invalid. |
| `SPEC_GAP-REFPOSE-TOL` | §11 / HUM-002..004 | Humanoid directed-pose checks use a 25° inclusive maximum; exceeding it invalidates SEMANTIC binding. Left/right facing is a categorical check. The threshold is normative; empirical calibration remains a certification task. |
| `SPEC_GAP-CORRECTION` | §11.2 / §16 | `ADM-REF-NORM-1` defines each mapped humanoid correction as the inverse of the parent-to-child product of serialized local rest rotations. Corrections are required for every mapped role in SEMANTIC humanoid binding; no identity fallback is allowed. |
| `SPEC_GAP-LOCAL-AXES` | §11.2 | Local axes remain unconstrained; the normalized correction algorithm defines how semantic rotation deltas are applied independently of bone roll. |
| `SPEC_GAP-FORWARD` | §2 / §11 | ADM model space is +Y up, +X anatomical right, −Z forward. Source formats with a different basis are converted consistently across geometry, transforms, skinning, animation, IK and attachments before validation. |
| `SPEC_GAP-ROOT-ROLE` | §11 / §14 / §16 | `root` is not a VRM role. Humanoid translation and v1 root-motion extraction use semantic `hips`; v1 EXTRACT requires `library.rootMotionSource:"hips"`. No root role is synthesized. |
| `SPEC_GAP-IK-MULTI` | §20 / animal annex | ADM-IK-1 is explicitly two-bone. Quadruped templates solve only the first two segments; distal joints remain FK and are not represented as full hoof/toe contact IK. More segments need a separate registered capability. |
| `SPEC_GAP-IK-LIMITS` | §20 | Joint limits, stretch, twist distribution, pole-angle controls, FABRIK/CCD and longer chains are outside ADM-IK-1. The core schema does not accept such fields; authoring tools must report unsupported DCC settings rather than silently export them. |
| `SPEC_GAP-IK-ZERO-FOLD` | §20.1 | The solver clamps to the exact physical reach interval. At the equal-length zero-distance singularity it preserves the neutral mid position and places the endpoint at the root. The reference solver and boundary test use this rule. |
| `SPEC_GAP-PROFILE-TEMPLATES` | §11 registry | The root/profile/role/reference-pose/IK-template/socket-template schema for `profiles/skeleton-profiles.json` is specified. Templates are authoring defaults only; ADM files store explicit resolved roles, IK chains and attachments. |
| `SPEC_GAP-RETARGET-MAP` | §11 registry | ADM 1.0 registers no cross-profile map format or mapping. `retargetMaps` must be empty; different profile IDs are INCOMPATIBLE. A future mapping requires a reviewed versioned profile-pair annex with explicit role transforms and fixtures. |
| `SPEC_GAP-CUSTOM-PROFILE` | §11 / §28 | Unregistered reverse-DNS versioned IDs are EXACT_ONLY. Semantic use requires a complete published annex and machine-readable registry entry with role, hierarchy, pose, correction, retarget, IK/socket and fixture rules. |
| `SPEC_GAP-KTX2-SUBSET` | §8.6 | Resolved in P3: optional KTX2/DDS subsets, RGBA8/BC1/BC3, sRGB/UNORM role rules, mips and mandatory same-size PNG/JPEG fallback are specified. Unsupported encodings and layouts are rejected. |
| `SPEC_GAP-SHADER-CORE20` | Shader registry | The proposed Core 20 list is not yet a complete normative registry. Only core PBR, layered PBR and cutout have registered contracts in P5; the remaining profiles need exact parameter tables, deterministic rendering math, fallback behavior, independent tests and per-profile documentation. | Specify and implement each profile in a versioned annex, add reference and negative fixtures, Blender node and round-trip tests, then publish the complete registry. |

## Deliberately retained: approval and certification blockers

| ID | Area | Why it remains open | Required to close |
|---|---|---|---|
| `SPEC_GAP-ANIMAL-REGISTRY` | `animal.*.v1` | The identifiers and role sets are design proposals only. The user requirement explicitly says not to call them official without an approved normative profile; the current proposal has not had independent anatomical review. | Approve a versioned profile per species with role hierarchy, mandatory/optional roles, reference pose, limb topology, IK semantics, sockets and positive/negative example rigs; then mark the registry entry NORMATIVE. |
| `SPEC_GAP-STAND` | Animal reference pose | The proposed quadruped `STAND` posture and 45° checks are editor diagnostics, not calibrated cross-tool semantics. Making them normative without approved animal profiles would imply unsupported compatibility. | Approve the pose per animal profile and publish calibrated direction/side fixtures. |
| `SPEC_GAP-RETARGET-ANIMAL` | Cross-species animation | No canine/feline/equine map has been reviewed or registered. Similar limb names/topology do not establish compatible motion. | Publish an explicit profile-pair mapping, transform and scaling rules, and numerical acceptance fixtures. Until then every cross-profile binding is INCOMPATIBLE. |

## Release/certification limitations (not specification ambiguities)

- No independent second implementation currently verifies ADM semantic humanoid retargeting or the full ADM-IK-1 solver. The Blender tests are reference-implementation tests only.
- Canonical `rigId`, humanoid semantic retarget and IK need versioned byte/numerical fixtures consumed by an independent validator before certification.
- The KTX2 subset has not been checked by the official KTX-Software validator or by GPU upload tests; Blender/OpenImageIO independently reads the emitted DDS subset only.
- No animal profile may be advertised as normative, and no implementation may claim full ADM 1.0 conformance from the bundled tests alone.
