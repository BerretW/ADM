# `ADM_humanoid_sockets_v1`

This extension defines stable attachment names and coordinate-frame semantics for equipment sockets
on `humanoid.vrm1` models. Its schema version is exactly `1.0.0`; its associated capability is
`ADM-HUMANOID-SOCKETS-1`. It uses the existing top-level `attachments` array and adds no node,
geometry, inventory or gameplay data.

## Declaration and frames

When one or more registered humanoid socket names are present in `attachments`, the model MUST:

- contain a `skeletonProfiles` entry with `id:"humanoid.vrm1"`;
- list `ADM_humanoid_sockets_v1` in both `extensionsUsed` and `extensionsRequired`;
- contain the top-level extension object `{ "version":"1.0.0" }`;
- declare each socket name at most once (the general §24 attachment uniqueness rule).

Each registered socket is an ordinary `{ "name":string, "node":u32 }` attachment. Its node MUST
be the node mapped to the required semantic role or a descendant of it. The required role and
permitted fallback role(s) are listed below. No relationship is inferred from a node's name.

The socket's world transform in the model's rest pose is the authored connection frame:
`W_socket = W(node)`. In ADM model space the frame MUST have unit scale and axes +X right, +Y up,
and −Z forward (equivalently, its matrix columns are +X, +Y, +Z). Orientation tolerance is
`1e-4` per axis component. Position is authored per character and is not standardized: proportions,
body shape and equipment fit differ between assets. Tools MAY create a marker at the role joint
origin as a starting point, but the author MUST place it at the intended contact/mount point.

An accessory model MAY expose its connection frame as a generic attachment named `mount.root`.
For host socket world matrix `W_socket` and accessory mount matrix `L_mount` relative to the
accessory model root, an application that chooses to assemble them computes:
`W_accessoryRoot = W_socket × inverse(L_mount)`.
The accessory does not need `ADM_humanoid_sockets_v1`; the extension is needed to interpret
humanoid host socket names. The convention does not promise collision-free fit.

## Registered humanoid socket names

All names are exact, lowercase ASCII and case-sensitive. Every listed name may appear once per
model. Fallbacks are ordered; use the first mapped role in that order. The node referenced by the
attachment MUST be the chosen role node or one of its descendants.

| Socket name | Required role | Fallback roles | Intended mount |
|---|---|---|---|
| `hand.right.grip` | `rightHand` | — | Primary hand-held item grip |
| `hand.left.support` | `leftHand` | — | Support-hand grip / two-handed item |
| `weapon.primary.back` | `chest` | `spine` | Primary long item on back |
| `weapon.secondary.back` | `chest` | `spine` | Secondary long item on back |
| `weapon.sling` | `chest` | `upperChest`, `spine` | Sling/retention anchor |
| `weapon.holster.hip.left` | `leftUpperLeg` | `hips` | Left hip holster |
| `weapon.holster.hip.right` | `rightUpperLeg` | `hips` | Right hip holster |
| `weapon.holster.thigh.left` | `leftUpperLeg` | — | Left thigh holster |
| `weapon.holster.thigh.right` | `rightUpperLeg` | — | Right thigh holster |
| `weapon.knife.chest.left` | `chest` | `spine` | Left chest knife mount |
| `weapon.knife.chest.right` | `chest` | `spine` | Right chest knife mount |
| `head.helmet` | `head` | — | Helmet |
| `head.nvg` | `head` | — | Night-vision device |
| `head.face` | `head` | — | Face covering |
| `head.ear.left` | `head` | — | Left ear protection |
| `head.ear.right` | `head` | — | Right ear protection |
| `torso.plate_carrier` | `chest` | `upperChest`, `spine` | Plate carrier |
| `torso.chest_rig` | `chest` | `upperChest`, `spine` | Chest rig |
| `back.backpack` | `chest` | `upperChest`, `spine` | Backpack |
| `waist.belt` | `hips` | — | Belt |

These are mount-point identifiers, not a required equipment set. A model may contain any subset.
The older generic template names `hand.left`, `hand.right`, `head` and `spine.back` remain ordinary
§24 attachments for compatibility; they do not claim this extension or substitute for the
registered names above.

The socket name identifies a host slot. It does not declare item compatibility, inventory rules,
weapon handling, animation selection, concealment, collision policy, or runtime attachment behavior.
Those are application responsibilities. Separate instances of one model may bind different content
to the same socket.

## Validation and conformance

An implementation claiming `ADM-HUMANOID-SOCKETS-1` MUST validate the declaration, exact version,
unique registered names, `humanoid.vrm1` role ancestry, and model-space frame axes above. It MUST
preserve socket attachment names and transforms through import/export. Unknown required extension
versions MUST be rejected; readers that do not implement this extension MUST reject it as required.
Generic readers MAY expose the attachments as ordinary named frames without applying equipment
semantics.

- `SOCK-001`: accept one hand-held socket on a valid humanoid role.
- `SOCK-002`: accept multiple distinct weapon, head and gear socket names in one humanoid model.
- `SOCK-003`: accept a role-node descendant as the attachment node and preserve its authored offset
  and orientation through export/import.
- `SOCK-004`: reject duplicate registered socket names, missing humanoid profile, invalid role
  ancestry, non-unit scale, or a frame outside the specified axis tolerance.
- `SOCK-005`: reject missing extension declaration, non-required capability, unknown extension
  version, and a required extension with no registered socket attachment.
- `SOCK-006`: verify accessory composition using host translation `(1,2,3)` and mount local
  translation `(0,0,-0.25)`; the accessory root translation is `(1,2,3.25)`.

The extension does not alter existing `humanoid.vrm1` roles or animation bindings. Socket position is
asset-authored; shared socket IDs make the mount discoverable but do not guarantee that equipment
fits every body type.
