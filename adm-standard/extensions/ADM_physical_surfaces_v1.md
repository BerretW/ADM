# `ADM_physical_surfaces_v1`

Version 1.0.0, incorporated by ADM Draft 0.4 P10.

## Physical surface profiles

The optional `profile` field on a `physicalMaterials` record is one of:

| ID | Surface |
|---|---|
| `adm.phys.wood.v1` | Wood |
| `adm.phys.metal.v1` | Metal |
| `adm.phys.stone.v1` | Stone, concrete or masonry |
| `adm.phys.ground.v1` | Soil, sand or natural ground |
| `adm.phys.glass.v1` | Glass |

These are identities for application-side surface reactions (for example footsteps, impacts or
scraping). They do not define coefficients beyond the existing record's `friction` and
`restitution`, and MUST NOT imply penetration, ignition, breakage or gameplay behavior. An omitted
profile retains legacy behavior. Unknown profiles are invalid in this extension revision.

## Per-face assignment on collision meshes

A collider's existing `physicalMaterial` is the default for all of its mesh triangles. A collision
mesh primitive MAY override that default with:

```json
{
  "extensions": {
    "ADM_physical_surfaces_v1": {
      "faceMaterials": ["wood", "stone"]
    }
  }
}
```

`faceMaterials` MUST contain exactly one existing `physicalMaterials[*].id` for each triangle in
the primitive's index accessor, in index order. IDs are stable references; Blender material-slot
indices are not serialized or interpreted as physical surface identifiers. The extension MUST be
listed in both `extensionsUsed` and `extensionsRequired` when any per-face assignment is present.
Readers without support MUST reject the asset rather than silently collapsing the assignments.

## Blender mapping

Blender collision meshes store the stable IDs in a string FACE attribute named
`adm_physical_material_id`. The collider-level `physicalMaterial` remains the default. Exporters
MUST apply the face IDs after triangulation so each emitted triangle has one stable ID. Importers
MUST restore the FACE attribute without depending on visual material slots.
