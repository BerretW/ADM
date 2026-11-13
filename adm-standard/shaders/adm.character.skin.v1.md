# `adm.character.skin@1.0.0`

## 1. Identity and version
ID `adm.character.skin`, SemVer `1.0.0`.
## 2. Purpose and scope
Portable skin material with a bounded diffuse-wrap approximation, not screen-space subsurface scattering.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `subsurface_strength` | F32 | `0.1` | `[0,1]` |
| `subsurface_color` | VEC3 | `[1,0.5,0.35]` | `[0,1]` |
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
## 4. Mathematical contract
For each direct light `L`, `wrap=max(0,(dot(N,L)+subsurface_strength)/(1+subsurface_strength))`.
Diffuse response is `mix(baseColor*max(0,dot(N,L)), subsurface_color*wrap, subsurface_strength)`.
## 5. Color spaces, units and texture channels
Colors are linear RGB; strength is dimensionless. Texture roles follow §8.
## 6. Input textures
Standard base/normal/PBR textures plus optional `detail_normal`.
## 7. Normal and tangent conventions
Both normal maps use tangent-space +Y and are applied in order: base normal then detail normal.
## 8. Alpha and double-sided behavior
Alpha and culling follow §8.
## 9. PBR fallback
Top-level PBR fields are mandatory; fallback drops the wrap term.
## 10. Animation
No shader-specific animation; PBR fields remain animatable.
## 11. Allowed Blender Shader Nodes
Normal Map, Vector Math, Diffuse BSDF, Mix, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
ndotl = max(0, dot(N,L))
wrap = max(0, (dot(N,L)+s)/(1+s))
diffuse = mix(baseColor*ndotl, subsurface_color*wrap, s)
```
## 13. Conformance tests
Test front/back light response, strength endpoints, detail normal combination and PBR fallback.
## 14. Unsupported effects
Screen-space SSS, path-traced diffusion, thickness-dependent scattering and skin-specific BRDFs.
