# `adm.animal.feather@1.0.0`

## 1. Identity and version
ID `adm.animal.feather`, SemVer `1.0.0`.
## 2. Purpose and scope
Mesh feather and feather-card shading.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
| `sheen_strength` | F32 | `0.3` | `[0,1]` |
| `sheen_tint` | VEC3 | `[0.8,0.85,1]` | `[0,1]` |
## 4. Mathematical contract
`F=(1-clamp(abs(dot(N,V)),0,1))^5`; `C=baseColor+sheen_strength*F*sheen_tint`, componentwise clamped to HDR nonnegative.
## 5. Color spaces, units and texture channels
Colors are linear RGB; sheen strength is dimensionless.
## 6. Input textures
Core base color and optional detail normal texture; alpha uses base-color alpha.
## 7. Normal and tangent conventions
Detail normal follows §8 tangent-space +Y convention.
## 8. Alpha and double-sided behavior
Alpha and double-sided behavior follow §8; hair cards may use `MASK`.
## 9. PBR fallback
Top-level PBR fields are required; fallback omits sheen.
## 10. Animation
No shader parameters animatable.
## 11. Allowed Blender Shader Nodes
Geometry, Vector Math, Math, Mix, Normal Map, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
f = (1 - clamp(abs(dot(N,V)),0,1))^5
color = max(0, baseColor + sheen_strength * f * sheen_tint)
shade_core_pbr(color)
```
## 13. Conformance tests
Test normal/grazing angles, strength endpoints, detail normal and fallback.
## 14. Unsupported effects
Blade geometry, tessellation, spectral iridescence and renderer-dependent thin-film interference.
