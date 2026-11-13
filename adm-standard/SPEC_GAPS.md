# ADM 1.0 Draft 0.4 — open specification gaps (`SPEC_GAP`)

Areas found while implementing the skeleton profile registry (revision P2) that the Draft 0.4 text does not define unambiguously. Each gap lists the **interim behaviour** of the reference Blender toolkit. Interim behaviour is never a new binary structure: it only uses fields the specification already defines, or keeps data editor-side.

| ID | Area | Problem | Interim behaviour |
|---|---|---|---|
| `SPEC_GAP-SKEL-SCHEMA` | §11 vs §11/§16 | The §11 record schema listed only `id, skin, roles, referencePose, extensions`, but §16 uses `targetHeight` and `referenceCorrection`, and §11 compatibility requires `rigId`. | **Resolved in P2:** the §11 schema now lists the three optional members. |
| `SPEC_GAP-ANIM-LIB-SCHEMA` | §13 vs §16 | §16 uses `motionScale`, `sourceHeight` and `rootMotionSource` on `library`, but the §13 `library` schema does not list them (nor `revision` / `namespace`), and §13 forbids unknown fields. | Writers emit them only when used; the validator accepts them. Needs a §13 schema fix. |
| `SPEC_GAP-REFPOSE-TOL` | §11, §25 | No numeric tolerance for "arms horizontal / legs down"; T-pose fixtures are a release blocker (§28). | Advisory 25° (humanoid) / 45° (quadruped) direction checks. Facing (left/right on the wrong side) is always an error. Deviations warn on export/import and do not block. |
| `SPEC_GAP-CORRECTION` | §16 | `referenceCorrection` is defined as a formula, but no rule says which correction makes δ portable between rigs with different local axes. | `ADM-REF-NORM` proposal (`profiles/humanoid.vrm1.md` H4): `C = inverse(model-space rest rotation)`. Rigs without it get the warning `CORRECTION_NOT_NORMALIZED`. |
| `SPEC_GAP-LOCAL-AXES` | §10–§11 | Local joint axes (bone roll) are unconstrained. | `localAxes: "UNCONSTRAINED"` in the registry; portability comes from ADM-REF-NORM. |
| `SPEC_GAP-FORWARD` | §2, §11 | ADM forward is −Z; VRM/glTF characters face +Z. Rigs imported from VRM must be rotated 180° about +Y, and §11 does not mention this. | Facing check plus the safe `ROTATE_180` fix in the plugin. |
| `SPEC_GAP-ROOT-ROLE` | §11, §16 | The text mentions root/hips motion, but `root` is not a VRM 1.0 role. | Only `hips` carries translation (`translationRoles`). No `root` role is created. |
| `SPEC_GAP-IK-MULTI` | §20 | ADM-IK-1 is direct two-bone only. Digitigrade and unguligrade limbs have 3–4 functional segments. | Animal IK templates cover UpperLeg→LowerLeg→Foot. Distal segments stay FK. |
| `SPEC_GAP-IK-LIMITS` | §20 | Angular joint limits, stretch and pole angle are explicitly excluded, with no registered extension. | Blender IK limits, stretch, `use_rotation`, chain_count≠2 and non-IK constraints are reported as unsupported and are not exported. |
| `SPEC_GAP-IK-ZERO-FOLD` | §20.1 | "nearest representable endpoint using a documented zero-fold rule": the rule is not specified. | The core solver clamps `d` into `[|l1−l2|+eps, l1+l2−eps]` and uses the §20.1 fallback axes. |
| `SPEC_GAP-PROFILE-TEMPLATES` | §11, §20, §24 | No schema for profile IK templates or socket templates. | Registry JSON (`profiles/skeleton-profiles.json`) carries them as **editor defaults**. Files always store explicit `ikChains` and `attachments`. |
| `SPEC_GAP-ANIMAL-REGISTRY` | §11 | "Quadruped profiles remain unregistered." | `animal.*.v1` are PROVISIONAL proposals (`profiles/animal.quadruped.v1.md`). Compatibility is `PROVISIONAL_SEMANTIC`, never `SEMANTIC`. |
| `SPEC_GAP-STAND` | §11 | No reference pose is defined for non-humanoids. | Proposed `STAND`: forward −Z, limbs down, advisory 45°. |
| `SPEC_GAP-RETARGET-MAP` | §11, §16 | No format for approved cross-profile retarget maps. | `retargetMaps` is empty for every profile, so every cross-profile binding is INCOMPATIBLE. |
| `SPEC_GAP-CUSTOM-PROFILE` | §11, §28 | "Published with validation rules and example rigs": no machine-readable format is given. | Custom ids (`org.domain.name.vN`) are allowed. They have no semantic rules, so only EXACT binding is portable, and the tool warns. |
| `SPEC_GAP-KTX2-SUBSET` | §8 | "KTX2 support means decoding the explicitly published subset", but no subset was published; DDS was excluded outright. | **Resolved in P3:** §8.6 registers the KTX2 and DDS (DX10) subset: RGBA8 / BC1 / BC3, sRGB vs UNORM per role, embedded mips, mandatory same-size PNG/JPEG fallback. Basis Universal, BC4–BC7, ASTC/ETC2 and supercompression remain future work. |

## Retained Draft 0.4 limitations

Calibrated T-pose fixtures, canonical rig fingerprint example bytes and an independent second implementation of semantic retargeting are still missing. Until they exist, no tool may claim ADM 1.0 skeleton or retarget certification.
