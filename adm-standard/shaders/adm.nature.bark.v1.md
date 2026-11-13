# `adm.nature.bark@1.0.0`

## 1. Identity and version
ID `adm.nature.bark`, SemVer `1.0.0`.
## 2. Purpose and scope
Tiled tree-bark material for ordinary mesh trunks and branches.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
| `moss_mask` | TEXTURE | `null` | valid §8 texture ref |
| `uv_scale` | VEC2 | `[1,1]` | `[0.001,1000]` |
| `moss_amount` | F32 | `0` | `[0,1]` |
## 4. Mathematical contract
`m=clamp(moss_mask.r*moss_amount,0,1)` or zero; color is `mix(baseColor,baseColor*0.45,m)`.
## 5. Color spaces, units and texture channels
Base RGB follows §8 sRGB; moss R is linear; UV scale is dimensionless.
## 6. Input textures
Core base/normal textures and optional detail normal and moss mask.
## 7. Normal and tangent conventions
Detail normal is combined with core tangent normal using normalized vector addition.
## 8. Alpha and double-sided behavior
Top-level §8 rules apply.
## 9. PBR fallback
Top-level PBR fields are required; moss/detail are optional.
## 10. Animation
`moss_amount` is animatable.
## 11. Allowed Blender Shader Nodes
Image Texture, UV Map, Normal Map, Vector Math, Separate Color, Math, Mix and Principled BSDF.
## 12. Reference pseudocode
```text
m = clamp(mask.r*moss_amount,0,1) if mask exists else 0
color = mix(baseColor, baseColor*0.45, m)
normal = normalize(coreNormal + detailNormal) if detail exists else coreNormal
```
## 13. Conformance tests
Test UV tiling, moss endpoints, normal combination and fallback.
## 14. Unsupported effects
Displacement, procedural bark generation and world-space moss growth.
