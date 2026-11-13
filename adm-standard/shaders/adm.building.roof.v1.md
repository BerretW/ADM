# `adm.building.roof@1.0.0`

## 1. Identity and version
ID `adm.building.roof`, SemVer `1.0.0`.
## 2. Purpose and scope
Tiled roof coverings with a weathering tint; mesh only.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_mask` | TEXTURE | `null` | valid §8 texture ref |
| `weather_tint` | VEC3 | `[0.5,0.5,0.5]` | `[0,1]` |
| `weather_amount` | F32 | `0` | `[0,1]` |
## 4. Mathematical contract
`w=clamp(detail_mask.r*weather_amount,0,1)` or zero without mask; `color=mix(baseColor,weather_tint,w)`.
Roughness, metallic and normal are top-level PBR values.
## 5. Color spaces, units and texture channels
Tint/base RGB are linear after §8 conversion; mask R is linear data.
## 6. Input textures
Core base/normal textures and optional detail mask.
## 7. Normal and tangent conventions
Normal follows §8.
## 8. Alpha and double-sided behavior
Alpha/culling follow §8.
## 9. PBR fallback
Top-level PBR fields are mandatory; weathering is omitted in fallback.
## 10. Animation
`weather_amount` is animatable.
## 11. Allowed Blender Shader Nodes
Image Texture, Separate Color, Math, Mix, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
w = clamp(mask.r * weather_amount,0,1) if mask exists else 0
color = mix(baseColor, weather_tint, w)
shade_core_pbr(color, roughnessFactor, metallicFactor)
```
## 13. Conformance tests
Test mask absence, weight endpoints, tint interpolation and round-trip.
## 14. Unsupported effects
Displacement, tessellation, procedural tile placement and physical snow accumulation.
