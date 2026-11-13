# ADM Skeleton Profile: `humanoid.vrm1`

**Status:** role registry and semantic reference-pose/retarget rules are normative (ADM 1.0 Draft 0.4 §§11, 11.2 and 16). Role names and hierarchy are taken unchanged from VRM 1.0; ADM-specific coordinate and normalized-correction rules are defined by the ADM specification. Machine-readable data: [`skeleton-profiles.json`](skeleton-profiles.json) (`profiles[id=humanoid.vrm1]`). Remaining approval and certification blockers are tracked in [`../SPEC_GAPS.md`](../SPEC_GAPS.md).

## H1. Source and role set

Role names, parent roles, required/optional classification and the "needs parent" rules come from the VRM 1.0 humanoid specification (`https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md`). ADM does not add, rename or remove roles.

- 55 roles in total: torso (`hips spine chest upperChest neck head`), face (`leftEye rightEye jaw`), legs (`*UpperLeg *LowerLeg *Foot *Toes`), arms (`*Shoulder *UpperArm *LowerArm *Hand`) and 30 finger roles (`*Thumb{Metacarpal,Proximal,Distal}`, `*{Index,Middle,Ring,Little}{Proximal,Intermediate,Distal}`).
- **Required (15):** `hips spine head leftUpperLeg leftLowerLeg leftFoot rightUpperLeg rightLowerLeg rightFoot leftUpperArm leftLowerArm leftHand rightUpperArm rightLowerArm rightHand`.
- **Needs parent:** `upperChest` requires `chest`; `*ThumbProximal`/`*ThumbDistal` and finger `*Intermediate`/`*Distal` require their VRM parent role.
- A role is mapped to exactly one skin joint and a joint carries at most one role (§11). The plugin and validator reject duplicate roles (`ROLE_DUPLICATE`), unknown names (`ROLE_UNKNOWN`), missing required roles (`ROLE_MISSING`) and broken "needs parent" rules (`ROLE_NEEDS_PARENT`).

**Hierarchy rule (semantic parent chain):** the nearest *mapped* ancestor of a role joint MUST be the nearest mapped role in the VRM parent chain (`ROLE_HIERARCHY`). Unmapped helper/twist/costume joints may sit between mapped joints. Compatibility is decided by roles, never by joint count (`EXTRA_BONES` is informational).

## H2. Reference pose `T`

Directions are in ADM model space (+Y up, +X character's right, forward −Z):

| Check | Expected direction |
|---|---|
| `leftUpperArm→leftLowerArm`, `leftLowerArm→leftHand` | −X |
| `rightUpperArm→rightLowerArm`, `rightLowerArm→rightHand` | +X |
| `*UpperLeg→*LowerLeg`, `*LowerLeg→*Foot` | −Y |
| `hips→head` | +Y |
| `rightUpperLeg.x > leftUpperLeg.x` and `rightUpperArm.x > leftUpperArm.x` | facing (`REFERENCE_FACING`) |

The facing test is categorical: a rig whose left joints lie on +X is mirrored for ADM and MUST be basis-converted before semantic export. Each directed check has a maximum angular deviation of **25 degrees inclusive**. Exceeding it invalidates SEMANTIC compatibility and is reported as `REFERENCE_POSE`. This threshold is normative; calibration against independent real-world rigs remains a certification task.

## H3. Local joint axes

ADM 1.0 does not constrain local joint axes (bone roll); the registry declares `localAxes: "UNCONSTRAINED"`. Semantic portability is provided by the normative correction algorithm in §11.2/H4, not by requiring identical local axes.

## H4. Normalized reference correction (`ADM-REF-NORM-1`)

For every mapped role in a humanoid profile used for SEMANTIC binding, §11.2 requires:

```
C_role = inverse(q_rest(role))     # parent-to-child product of local rest rotations
```

With this choice δ is an ADM-model-axis rotation delta: the joint's model-space rotation becomes `δ × q_rest`. δ is independent of bone roll and joint count, so two humanoids with different proportions and rolls receive the same model-space rotation delta. A writer MUST store the correction for every mapped role; missing corrections invalidate semantic binding. A reader applies the target model's corrections. Identity is correct only when `q_rest` is identity and MUST NOT be substituted when a correction is missing.

Verification (reference toolkit test `test_skeleton_blender.py`): source rig at scale 1.0 and roll 0°, target rig at scale 1.25 and roll 30° with different joint names. The per-role model-space rotation deltas agree within 1e-4°, and the hand position scaled by 1/1.25 agrees within 1e-6 m. This is not an independent conformance test.

## H5. IK templates (PROPOSED defaults for ADM-IK-1)

| id | root | mid | end | pole (model) |
|---|---|---|---|---|
| `leftArm` | `leftUpperArm` | `leftLowerArm` | `leftHand` | `[0,0,1]` (elbow back) |
| `leftLeg` | `leftUpperLeg` | `leftLowerLeg` | `leftFoot` | `[0,0,-1]` (knee forward) |
| `rightArm` | `rightUpperArm` | `rightLowerArm` | `rightHand` | `[0,0,1]` |
| `rightLeg` | `rightUpperLeg` | `rightLowerLeg` | `rightFoot` | `[0,0,-1]` |

The templates only pre-fill §20 `ikChains`; the file always stores explicit node indices and a model-space pole. ADM-IK-1 requires direct parent→child links. If a twist helper sits between `leftUpperArm` and `leftLowerArm`, the template does not apply, and the tool reports `IK_NOT_DIRECT`. Joint limits, stretch, pole angle and chains of three or more segments are outside ADM-IK-1 (§20). Tools MUST report such DCC constraint settings as unsupported and MUST NOT export them as ADM IK.

## H6. Socket templates (PROPOSED names)

`hand.left`→`leftHand`, `hand.right`→`rightHand`, `head`→`head`, `spine.back`→`chest` (fallback `spine`). Sockets are ordinary §24 attachments parented to the role joint. They have their origin at the joint and their rotation equal to the model frame in the reference pose (identity in ADM model space), so a prop held at `hand.right` has the same orientation on any compliant humanoid regardless of bone roll.

## H7. Facial channels

ARKit 52 (`facialProfiles[id=arkit52]`) and VRM-style `expressions` are **independent, explicitly declared** capabilities (§9, §19). `humanoid.vrm1` does not imply either. A SEMANTIC library may combine `bone` channels with `morph` channels. A morph channel named after an ARKit coefficient binds through the target's `facialProfiles` bindings when present, otherwise through an equally named morph target.

## H8. Conformance tests

- `HUM-001`: reject a missing required role, a duplicate role, an unknown role, and a violated needs-parent rule.
- `HUM-002`: accept helper joints between mapped roles; reject a mapped joint whose nearest mapped ancestor is not its VRM parent role.
- `HUM-003`: facing detection (left on +X ⇒ invalid for semantic retarget); a 180° rotation restores validity.
- `HUM-004`: ADM-REF-NORM-1 retarget between rigs of different scale and roll yields equal model-space deltas (≤0.05°).
- `HUM-005`: IK templates pass §20 validation and the ADM-IK-1 solver places `end` on a reachable target (≤1e-4 m).
- `HUM-006`: export→import preserves bind matrices (≤1e-5), roles, corrections, IK chains and skin weights.

Executable implementation: `adm_blender/tests/test_skeleton_profiles.py` (pure Python) and `adm_blender/tests/test_skeleton_blender.py` (Blender). An independent second implementation is still required before certification.
