# ADM Skeleton Profiles: quadruped family (`animal.*.v1`) — PROPOSAL

**Status: PROVISIONAL — not registered for normative semantic interoperability in ADM 1.0 Draft 0.4.** This document and the matching entries in [`skeleton-profiles.json`](skeleton-profiles.json) are a design proposal for review. Tools MAY author, map and validate against these identifiers. They MUST NOT advertise `SEMANTIC` interoperability for them; the plugin reports `PROVISIONAL_SEMANTIC` instead. Role names, required roles, joint topology, gait labels and orientations below are proposals and MUST NOT be emitted as normative compatibility claims until an anatomy review, approved registry entry and independent fixtures are published.

| id | extends | gait | limb segments (front / hind) | required extras |
|---|---|---|---|---|
| `animal.generic_quadruped.v1` | — | GENERIC | UpperLeg, LowerLeg, Foot, [Toes] / same | none |
| `animal.canine.v1` | generic | DIGITIGRADE | UpperLeg, LowerLeg, Foot, Toes / same | `*FrontShoulder` (scapula), `*Toes` |
| `animal.feline.v1` | generic | DIGITIGRADE | as canine | as canine |
| `animal.equine.v1` | generic | UNGULIGRADE | UpperLeg, LowerLeg, Foot (cannon), Pastern, Hoof / same | `*FrontShoulder`, `*Pastern`, `*Hoof` |

## Q1. Roles

Common: `hips` (pelvis, semantic root, required), `spine`, `chest`, `neck`, `head` (required), and the optional `jaw`, `leftEye`, `rightEye`, `leftEar`, `rightEar`, `tailBase`, `tailMid` (needs `tailBase`), `tailTip` (needs `tailMid`).

Limbs per side (`left`/`right`):
- Front: `{side}FrontShoulder` (parent `chest`), then `{side}Front<Segment>` in the order of the table, each the parent of the next.
- Hind: `{side}Hind<Segment>`, with the first segment parented to `hips`.

`Toes`, `Pastern` and `Hoof` need their parent segment. Left/right follows the animal's own anatomy, not the viewer's.

Canine and feline share one topology. A separate identifier still matters, because profile identity rather than topology decides compatibility.

## Q2. Proposed authoring pose `STAND` (non-normative)

The proposal uses the ADM model frame (+Y up, forward −Z, +X the animal's right), places the trunk roughly forward and the limbs in a neutral standing pose. The 45-degree limb direction checks and left/right facing checks in the machine-readable registry are editor diagnostics only. ADM 1.0 does not define a normative animal reference pose, a calibrated tolerance or a required rest stance; a validator MUST report these as provisional diagnostics and MUST NOT reject or certify cross-asset semantic compatibility from them.

## Q3. IK

ADM-IK-1 is two-bone only. A provisional editor template may create one chain on the first three segments:
- `leftFrontLeg`, `rightFrontLeg`: UpperLeg→LowerLeg→Foot, pole `[0,0,1]` (elbow back).
- `leftHindLeg`, `rightHindLeg`: same segments, pole `[0,0,-1]` (stifle forward).

Distal segments such as Toes, Pastern and Hoof keep their FK rotation; hoof/toe contact is not solved by that template. Multi-segment limb IK and joint limits are outside ADM-IK-1 and require a separately registered future capability. Templates MUST NOT be presented as complete animal-limb IK.

## Q4. Sockets

- generic, canine and feline: `head`→`head`, `back`→`chest`, `collar`→`neck`
- equine: `head`, `back`, `saddle`→`spine`

## Q5. Compatibility and retargeting rules

1. A library binds SEMANTICally only to a rig declaring the **same** profile id (`semanticCompatibleWith = [self]`).
2. `extends` documents shared structure only and does **not** grant compatibility. A canine clip is never applied to an equine or feline rig automatically.
3. ADM 1.0 defines no cross-profile map format or registered map. All `retargetMaps` are empty and every cross-profile binding is `INCOMPATIBLE`. A future mapping requires the reviewed, versioned profile-pair annex described in §11; similar topology or gait labels do not imply compatibility.
4. While the profiles are PROVISIONAL, a same-profile binding is reported as `PROVISIONAL_SEMANTIC`. Importers MAY allow it behind an explicit opt-in (plugin option *Allow Provisional*) and MUST warn.

## Q6. Planned conformance tests (design)

- `QDR-001`: required roles per specialization; digit roles (`*Toes`) are unknown on equine, and Pastern/Hoof are unknown on canine/feline.
- `QDR-002`: tail and limb needs-parent rules.
- `QDR-003`: canine→equine, canine→feline and humanoid→canine bindings are INCOMPATIBLE.
- `QDR-004`: same-profile binding is PROVISIONAL_SEMANTIC and is refused when provisional binding is disabled.

`QDR-001`, `QDR-003` and `QDR-004` are executed by the plugin tests (`QDR-002` partially, through the generic needs-parent rule). Registration still requires anatomical review, representative example rigs per specialization, approved pose and IK semantics, and an independent implementation. Until then these checks only test the toolkit's provisional behavior.
