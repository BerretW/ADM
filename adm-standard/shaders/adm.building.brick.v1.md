# `adm.building.brick@1.0.0`

## 1. Identity and version
ID `adm.building.brick`, SemVer `1.0.0`.
## 2. Purpose and scope
Brick wall with a deterministic mortar mask.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `mortar_mask` | TEXTURE | `null` | valid §8 texture ref |
| `dirt_mask` | TEXTURE | `null` | valid §8 texture ref |
| `mortar_roughness` | F32 | `0.9` | `[0,1]` |
| `brick_roughness` | F32 | `0.75` | `[0,1]` |
| `uv_scale` | VEC2 | `[1,1]` | `[0.001,1000]` |
## 4. Mathematical contract
`m=clamp(mortar_mask.r,0,1)` (or 0 when absent); base color and roughness are `mix(brick,mortar,m)`.
Dirt uses `dirt_mask.r` and multiplies color by `mix(1,0.35,d)`.
## 5. Color spaces, units and texture channels
Albedo is linear after sRGB decode; masks are linear; UV scale is dimensionless.
## 6. Input textures
Base texture contains brick color; mortar and dirt masks use their red channels.
## 7. Normal and tangent conventions
Base normal follows §8 and is shared by brick and mortar.
## 8. Alpha and double-sided behavior
Top-level §8 rules apply.
## 9. PBR fallback
Ordinary PBR fields are required; mortar/dirt detail may be omitted by fallback readers.
## 10. Animation
No shader parameters animatable.
## 11. Allowed Blender Shader Nodes
Image Texture, UV Map, Separate Color, Math, Mix and Principled BSDF.
## 12. Reference pseudocode
```text
m = mortar_mask.r if present else 0
color = mix(brick_rgb, mortar_rgb, clamp(m,0,1))
roughness = mix(brick_roughness, mortar_roughness, clamp(m,0,1))
```
## 13. Conformance tests
Test mask endpoints, roughness interpolation, dirt endpoints and fallback.
## 14. Unsupported effects
Procedural brick layout, parallax mortar depth and displacement.
