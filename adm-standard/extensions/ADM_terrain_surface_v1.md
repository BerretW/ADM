# `ADM_terrain_surface_v1`

Version 1.0.0 maps a terrain material's local layer slots to stable surface
identifiers. The extension adds identity metadata; it does not change shader
behavior, surface weights, or physical-material assignments.

## Material data

Add the extension to a material's `extensions` object:

```json
{
  "extensions": {
    "ADM_terrain_surface_v1": {
      "version": "1.0.0",
      "surfaceIds": [
        "awt.surface.0123456789abcdef01234567",
        "awt.surface.89abcdef0123456701234567"
      ]
    }
  }
}
```

The following requirements apply:

- The extension object MUST contain only `version` and `surfaceIds`.
- `version` MUST be `"1.0.0"`.
- `surfaceIds` MUST contain one to four non-empty strings. Each string MUST
  contain no more than 128 UTF-8 bytes.
- An ID MUST identify the same source terrain surface across materials, tiles,
  levels of detail (LODs), and exports of that source. Different source
  surfaces MUST have different IDs within the terrain asset.
- The array order maps local layer index `i` to the material's `layer{i}_*`
  shader parameters and to channel `i` of `COLOR_1` on primitives using the
  material. IDs MAY repeat in other materials to refer to the same source
  surface.
- The extension MUST be listed in `extensionsUsed`. It MUST NOT be listed in
  `extensionsRequired`, because it does not change how a reader renders the
  material.

IDs are opaque references. Readers MUST NOT derive an ID from a material name,
texture, shader parameter, or local layer index. An unregistered ID remains
valid and identifies an application-defined surface; readers that do not
understand it can ignore this optional metadata while rendering the material
normally.

This extension does not define physical properties, surface tags, collision
assignments, or material behavior.
