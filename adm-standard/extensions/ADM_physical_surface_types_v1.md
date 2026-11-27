# `ADM_physical_surface_types_v1`

Version 1.0.0. This extension adds descriptive physical-surface classification to the existing
`physicalMaterials` records. It does not change `ADM_physical_surfaces_v1` profile meanings,
friction, restitution, collider defaults, or per-face references.

## Add a physical-surface type

The extension adds these fields to a `physicalMaterials` record. Every record that uses any of
these fields MUST include a nonempty `type`; the other fields are optional:

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Versioned physical-surface type ID |
| `subtype` | string | More specific type ID |
| `tags` | array of strings | Descriptive semantic tags |
| `description` | string | Optional author-provided description |

Use the machine-readable [physical surface registry](../../adm_blender/core/physical_surface_registry.json)
for built-in types, subtypes, and tags. A custom type, subtype, or tag ID MUST use the
`org.<reverse-domain>.<name>.vN` form. IDs are case-sensitive and limited to 160 UTF-8 bytes.
A registered subtype MUST belong to the selected type. A custom subtype MAY use a custom ID; readers
preserve it and treat it as unspecified unless they recognize it. `tags` MUST contain unique IDs
and MUST contain no more than 32 entries. `description` MUST be no more than 512 UTF-8 bytes.

For example:

```json
{
  "physicalMaterials": [
    {
      "id": "meadow",
      "friction": 0.6,
      "restitution": 0.1,
      "type": "adm.physical.grass.v1",
      "subtype": "adm.physical.grass.tall.v1",
      "tags": ["adm.physical.tag.organic.v1", "adm.physical.tag.vegetated.v1"]
    }
  ],
  "extensionsUsed": ["ADM_physical_surface_types_v1"],
  "extensionsRequired": ["ADM_physical_surface_types_v1"]
}
```

When any type metadata is present, list this extension in both `extensionsUsed` and
`extensionsRequired`. Type IDs not present in the registry remain valid when they use the custom
ID form. Readers preserve unknown IDs and use `adm.physical.unknown.v1` for classification fallback.
Readers preserve unknown tags but do not assign them known meaning. A subtype that is not in the
selected type's registry is preserved and treated as unspecified.

## Keep physical and visual data independent

Physical type metadata applies only to physical materials and colliders. It MUST NOT be inferred
from visual material names, shader IDs, texture content, or visual surface identifiers. Visual
surface data MUST NOT determine collision behavior. The type, subtype, tags, and description do not
add friction or restitution values and MUST NOT imply gameplay behavior such as damage, ignition,
penetration, or breakage.
