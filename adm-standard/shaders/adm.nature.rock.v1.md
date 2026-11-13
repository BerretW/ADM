# `adm.nature.rock@1.0.0`

## 1. Identity and version
ID `adm.nature.rock`, SemVer `1.0.0`.
## 2. Purpose and scope
Rock surface detail with explicit optional object-space triplanar projection.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_texture` | TEXTURE | `null` | valid §8 texture ref |
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
| `moss_mask` | TEXTURE | `null` | valid §8 texture ref |
| `detail_scale` | F32 | `4` | `[0.01,100]` |
| `triplanar_scale` | F32 | `1` | `[0.001,1000]` |
## 4. Mathematical contract
Triplanar weights are `abs(N)^4 / sum(abs(N)^4)`. Project normalized object position on YZ, XZ and XY; blend samples by those weights.
Detail RGB multiplies base color; moss mask R applies `mix(1,0.4,moss)`.
## 5. Color spaces, units and texture channels
Color textures are sRGB-decoded; masks and normals linear; scale is inverse object-space units.
## 6. Input textures
Detail color/normal and moss mask are optional.
## 7. Normal and tangent conventions
Each projected normal is reoriented to object space before weighted sum and normalization.
## 8. Alpha and double-sided behavior
Top-level §8 rules apply.
## 9. PBR fallback
Top-level PBR fallback is required; detail and triplanar effects may be omitted.
## 10. Animation
No parameters animatable.
## 11. Allowed Blender Shader Nodes
Geometry Position/Normal, Vector Math, Math, Image Texture, Mix and Principled BSDF.
## 12. Reference pseudocode
```text
w = normalize(abs(N)^4)
P = object_position * triplanar_scale
detail = w.x*sample_yz(P) + w.y*sample_xz(P) + w.z*sample_xy(P)
```
## 13. Conformance tests
Test axis-aligned normals, equal projection weights, scale invariance and fallback.
## 14. Unsupported effects
World-position anchoring, displacement, stochastic projection and geometry-dependent texture baking.
