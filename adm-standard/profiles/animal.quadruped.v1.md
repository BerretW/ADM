# ADM Skeleton Profiles: quadruped family (`animal.*.v1`) — PROPOSAL

**Status: PROVISIONAL — not registered in ADM 1.0 Draft 0.4.** This document and the matching entries in [`skeleton-profiles.json`](skeleton-profiles.json) are a design proposal for review. Tools MAY author, map and validate against these identifiers. They MUST NOT advertise `SEMANTIC` interoperability for them; the plugin reports the compatibility level `PROVISIONAL_SEMANTIC` instead. Role names, joint counts and orientations below may still change before registration (`SPEC_GAP-ANIMAL-REGISTRY`).

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

## Q2. Reference pose `STAND`

Same model frame as humanoids: +Y up, forward −Z, +X the animal's right.
- `hips→chest` points forward (−Z).
- `<limb>UpperLeg→<limb>Foot` points down (−Y), with an advisory tolerance of 45°.
- Facing is detected from the x order of the left/right `FrontUpperLeg` and `HindUpperLeg` joints.

The STAND pose itself is not defined by ADM 1.0 (`SPEC_GAP-STAND`).

## Q3. IK

ADM-IK-1 is two-bone only. Each limb gets one chain on its first three segments:
- `leftFrontLeg`, `rightFrontLeg`: UpperLeg→LowerLeg→Foot, pole `[0,0,1]` (elbow back).
- `leftHindLeg`, `rightHindLeg`: same segments, pole `[0,0,-1]` (stifle forward).

Distal segments such as Toes, Pastern and Hoof keep their FK rotation. Multi-segment (3+ bone) limb IK and joint limits need a future registered IK profile (`SPEC_GAP-IK-MULTI`, `SPEC_GAP-IK-LIMITS`).

## Q4. Sockets

- generic, canine and feline: `head`→`head`, `back`→`chest`, `collar`→`neck`
- equine: `head`, `back`, `saddle`→`spine`

## Q5. Compatibility and retargeting rules

1. A library binds SEMANTICally only to a rig declaring the **same** profile id (`semanticCompatibleWith = [self]`).
2. `extends` documents shared structure only and does **not** grant compatibility. A canine clip is never applied to an equine or feline rig automatically.
3. Cross-profile retargeting requires an explicit, published `retargetMaps` entry. Its format is undefined (`SPEC_GAP-RETARGET-MAP`), so all maps are empty and every cross-profile binding is `INCOMPATIBLE`.
4. While the profiles are PROVISIONAL, a same-profile binding is reported as `PROVISIONAL_SEMANTIC`. Importers MAY allow it behind an explicit opt-in (plugin option *Allow Provisional*) and MUST warn.

## Q6. Planned conformance tests (design)

- `QDR-001`: required roles per specialization; digit roles (`*Toes`) are unknown on equine, and Pastern/Hoof are unknown on canine/feline.
- `QDR-002`: tail and limb needs-parent rules.
- `QDR-003`: canine→equine, canine→feline and humanoid→canine bindings are INCOMPATIBLE.
- `QDR-004`: same-profile binding is PROVISIONAL_SEMANTIC and is refused when provisional binding is disabled.

`QDR-001`, `QDR-003` and `QDR-004` are executed by the plugin tests (`QDR-002` partially, through the generic needs-parent rule). Registration needs anatomical review, example rigs per specialization and an independent implementation.
