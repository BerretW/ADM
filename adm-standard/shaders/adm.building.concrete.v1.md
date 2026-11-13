# `adm.building.concrete@1.0.0`

## 1. Identity and version
ID `adm.building.concrete`, SemVer `1.0.0`.
## 2. Purpose and scope
Concrete, plaster and facade material with tiled detail and dirt coverage.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_texture` | TEXTURE | `null` | valid §8 texture ref |
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
| `dirt_mask` | TEXTURE | `null` | valid §8 texture ref |
| `detail_scale` | F32 | `4` | `[0.01,100]` |
| `dirt_amount` | F32 | `0` | `[0,1]` |
## 4. Mathematical contract
`detailColor` multiplies base RGB; `d=clamp(dirt_mask.r*dirt_amount,0,1)`;
`color=mix(detailColor,detailColor*0.35,d)`. Roughness and metallic remain top-level PBR factors.
## 5. Color spaces, units and texture channels
Albedo textures are sRGB-decoded; mask R and normal data are linear; scale is a dimensionless UV multiplier.
## 6. Input textures
Optional detail albedo, detail normal and dirt mask.
## 7. Normal and tangent conventions
Both normal inputs follow §8; detail normal is combined after the core normal.
## 8. Alpha and double-sided behavior
Top-level §8 alpha and culling rules apply unchanged.
## 9. PBR fallback
Top-level fallback is mandatory; detail/dirt are optional enhancements.
## 10. Animation
`dirt_amount` is animatable.
## 11. Allowed Blender Shader Nodes
Image Texture, UV Map, Normal Map, Separate Color, Math, Mix and Principled BSDF.
## 12. Reference pseudocode
```text
detail = baseColor * srgb_to_linear(sample(detail_texture, uv*detail_scale).rgb)
d = clamp(sample(dirt_mask,uv).r*dirt_amount,0,1) if present else 0
shade_core_pbr(mix(detail, detail*0.35, d), roughnessFactor, metallicFactor)
```
## 13. Conformance tests
Test absent textures, scale, dirt endpoints and PBR fallback round-trip.
## 14. Unsupported effects
Parallax, displacement, screen-space dirt and procedural weathering.
