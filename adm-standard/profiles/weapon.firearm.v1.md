# ADM Profile: `weapon.firearm.v1`

**Status:** normative proposal for ADM Draft 0.4; not yet independently certified. **Applies to:** visual modular representations of firearms (including different feed designs). **Excludes:** ballistics, ammunition properties, firing mechanisms, damage, procedural instructions, recoil forces, and gameplay operation. The profile does not describe manufacturing.

## W1. Coordinates and declaration

Model root: right-handed ADM coordinates +X to visual RIGHT, +Y UP, -Z toward forward-looking muzzle direction. A model claiming this profile MUST declare `modelProfiles:[{"id":"weapon.firearm.v1","schemaVersion":1,"metadata":{...}}]` and `componentRoles` entries bound to scene nodes with `profile:"weapon.firearm.v1"`. All bound pivot/marker nodes MUST have finite TRS and positive unit scale, and use local axes aligned with root axes in rest pose; their mesh children may have arbitrary transforms. No negative-scale mirroring. All named roles and sockets are exact ASCII strings, case-sensitive.

A component role is a semantic mechanical/articulation marker, not an anatomical bone or game action. Required roles: `weapon.receiver` and `weapon.muzzle`. `weapon.receiver` MUST be an ancestor of `weapon.muzzle` and of every declared moving component role. Muzzle node local origin is the author-supplied visual forward reference point. The muzzle's local forward axis MUST be -Z, global rest -Z as well. The metadata MUST provide `feedType` enum `DETACHABLE_MAGAZINE` | `INTERNAL` | `OTHER` | `NONE`. This describes visual feed arrangement only, never ammunition specifications. If `feedType=DETACHABLE_MAGAZINE`, roles `weapon.magazine` and socket attachment `mount.magazine` are REQUIRED. If feedType is another enum, `weapon.magazine` is OPTIONAL and no inference about gameplay ammunition is made.

Optional standardized roles: `weapon.bolt`, `weapon.slide`, `weapon.trigger`, `weapon.safety`, `weapon.stock`, `weapon.grip`, `weapon.handguard`, `weapon.charging_handle`, `weapon.ejection_port`, `weapon.sight.front`, `weapon.sight.rear`, `weapon.magazine`, `weapon.attachment.optic`, `weapon.attachment.muzzle`, `weapon.attachment.underbarrel`, `weapon.attachment.side.left`, `weapon.attachment.side.right`. A file MUST NOT bind both `weapon.bolt` and `weapon.slide` to the same scene node. Every role MUST resolve to exactly one unique node; any nonstandard role MUST use a reverse-DNS qualified identifier, e.g. `org.example.weapon.fold_stock`.

## W2. Socket classes and assembly frames

Sockets are §24 attachments (world frames of scene nodes). The profile registers these optional mount names and their **socket class**:

| Host socket | Class | Conventional purpose |
| --- | --- | --- |
| `mount.optic.primary` | `optic.v1` | optical accessory |
| `mount.muzzle` | `muzzle.v1` | visual muzzle accessory |
| `mount.underbarrel` | `underbarrel.v1` | underbody accessory |
| `mount.side.left` / `mount.side.right` | `side.v1` | side accessory |
| `mount.stock` | `stock.v1` | stock replacement |
| `mount.magazine` | `magazine.v1` | removable magazine |
| `mount.handguard` | `handguard.v1` | detachable fore-end |
| `mount.grip` | `grip.v1` | visual grip module |

Role names and socket names serve different purposes and are not interchangeable. For every provided registered socket, its local axes at rest MUST be +Y UP, -Z FORWARD, +X RIGHT; the socket origin is the intended assembly reference point. The author's chosen position along an attachment interface is an artistic anchor, not a physical interoperability guarantee. `metadata.mounts` optional array includes exactly one entry for every present registered mount: `{ "socket":str, "class":str, "interface":str }`. `class` MUST match table, `interface` MUST be a nonempty versioned ASCII identifier (`[a-z][a-z0-9_.]*\.v[1-9][0-9]*`), and is used for **exact compatibility**; same class but different interface is NOT automatically compatible. Other mount types require namespaced extensions.

An independent accessory ADM describes its connection by an attachment `mount.root` and the optional registered profile `weapon.attachment.v1` with metadata `class`, `interface`; the receiver MUST match class/interface against host metadata before auto-assembly. `mount.root` local transform is the asset's connection frame and has the same +Y/-Z/+X axis convention. Given the host socket world matrix W_host and accessory mount local-to-asset-root matrix L_attach, set the accessory root world matrix to `W_accessory = W_host × inverse(L_attach)`. Do not apply arbitrary scale correction or estimate bounds for fitting. Any explicit application-space alignment override is outside the standard and MUST NOT be treated as profile-compatible automatic assembly.

`weapon.attachment.v1` accessory declaration is `{ "id":"weapon.attachment.v1", "schemaVersion":1, "metadata":{"class":str,"interface":str} }`; it MUST include an `attachments` entry `mount.root`, and MUST NOT declare a `weapon.firearm.v1` receiver role unless the asset is itself a complete firearm. Same exact `interface` ID means compatible declared mounting geometry but not a promise of physical clearance; collision checks and placement policy remain the application responsibility.

## W3. Pivot, motion and animation

Each moving role pivot origin MUST be its intended local articulation origin. The following role kinematics are defined:

- `weapon.bolt`, `weapon.slide`, `weapon.charging_handle`: local -Z direction is positive *forward visual coordinate*; authored translation is an **explicit parent-space delta**; no assumed real mechanism direction or stroke length.
- `weapon.trigger`, `weapon.safety`: rotation about local +X for a standard visual preview. A nonstandard hinge MAY use a custom versioned profile rather than claiming this contract.
- `weapon.magazine`: detachable transform lives at the magazine role; author-specified visual animation may translate or rotate it. Detachment and item state are host decisions, not file actions.
- `weapon.sight.*` and `weapon.ejection_port`: locator/marker roles, not implicit animations or effects.

All standard moving roles MUST have TRS rest transforms, positive unit scale and local axis-aligned pivot frames; mesh offsets belong in descendants. `metadata.articulations` optional list of `{ "role":str, "allowed":"TRANSLATION"|"ROTATION"|"BOTH", "translationAxis"?:"X"|"Y"|"Z", "rotationAxis"?:"X"|"Y"|"Z", "translationMin"?:f32, "translationMax"?:f32, "rotationMinRad"?:f32, "rotationMaxRad"?:f32 }`. Every entry references an existing moving role. Allowed field requirements: for TRANSLATION the translationAxis and both min/max are required and no rotation parameters permitted; for ROTATION equivalent rotation fields required and translation parameters forbidden; BOTH requires both complete groups. Ranges MUST be finite, min≤0≤max, and may be zero to denote no movement. Translations are in meters relative to rest; rotations are signed radians relative to rest. No implied physical constraints or real-world technical specifications.

A compatible `.adm_anim` library uses `targetProfile:"weapon.firearm.v1"`, `binding:"SEMANTIC"` and `component` channels (§15) to animate role deltas; it may simultaneously animate compatible skeleton/humanoid poses only via a separately bound library. A clip may describe `weapon@inspection@visual:inspect1` or `weapon@handling@visual:magazine_remove`; a name or event MUST NOT automatically fire the weapon, spawn objects or affect inventory. Material emissive and morph channels retain their general ADM semantics.

A standard host MAY attach a firearm to a humanoid `hand` attachment as an independent model through §24 world-frame composition. Aim alignment is application-defined and MUST NOT be inferred from the model's muzzle axis alone; profile v1 declares no humanoid animation rig mapping. The player/character controller remains outside ADM.

## W4. LoD, collision, validation and interoperability

LOD swaps MUST preserve component role nodes and mount frames. A profile-valid weapon may consist of one or many visual meshes; separate accessories are separate `.adm` models, not embedded game entities. Mesh skins/morphs/shaders use normal ADM rules. Hitboxes and colliders MAY be present; they express asset geometry only. No ballistic or gameplay collision semantics are inferred.

- `WPN-001`: required receiver/muzzle roles, muzzle as receiver descendant, unique node mapping, correct -Z reference orientation.
- `WPN-002`: DETACHABLE_MAGAZINE requires magazine role and `mount.magazine` with matching mount metadata; other feed types need not have either.
- `WPN-003`: reject a mount without a `mounts` metadata entry, mismatched class/interface or absent socket.
- `WPN-004`: accessory `mount.root` compose test: for a host socket at translation (1,2,3), accessory mount at local (0,0,-0.25), identity rotations, result accessory root translation is (1,2,3.25), tolerance ≤1e-5m.
- `WPN-005`: mechanical track delta at rest gives identity; translation [0,0,-0.02] moves a component precisely 2cm in -Z in parent space, irrespective of model mesh data.
- `WPN-006`: loading/LOD swap does not change socket world transforms; export-import preserves mount IDs and frames within §25 tolerance.

These tests define the contract; a container-only validator does **not** certify them. An implementation advertising `ADM-WEAPON-FIREARM-1` MUST validate all profile constraints and pass the dedicated fixture set.
