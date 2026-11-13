# `adm.vehicle.paint@1.0.0`

## 1. Identity and version
ID `adm.vehicle.paint`, SemVer `1.0.0`.
## 2. Purpose and scope
Portable automotive paint with base PBR plus an analytic clearcoat and grazing tint.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `clearcoat` | F32 | `0.5` | `[0,1]` |
| `clearcoat_roughness` | F32 | `0.1` | `[0,1]` |
| `edge_tint` | VEC3 | `[1,0.8,0.5]` | `[0,1]` |
| `edge_tint_strength` | F32 | `0.15` | `[0,1]` |
## 4. Mathematical contract
Use Schlick `F` from the base dielectric `F0=0.04`. `C=mix(baseColor,edge_tint,F*edge_tint_strength)`.
Add a second GGX lobe with weight `clearcoat`, roughness `clearcoat_roughness`, and dielectric `F0=0.04`.
## 5. Color spaces, units and texture channels
Colors are linear RGB; weights and roughness are dimensionless normalized values.
## 6. Input textures
Standard §8 PBR textures; no proprietary carpaint maps.
## 7. Normal and tangent conventions
Normals follow §8. Clearcoat uses the same normal as the base lobe.
## 8. Alpha and double-sided behavior
Alpha and face culling follow §8.
## 9. PBR fallback
Required §8 top-level PBR fields are the fallback.
## 10. Animation
`clearcoat` and `clearcoat_roughness` are animatable numeric parameters.
## 11. Allowed Blender Shader Nodes
Principled BSDF clearcoat inputs, Layer Weight, Math, Mix and Material Output.
## 12. Reference pseudocode
```text
F = 0.04 + 0.96 * (1 - clamp(abs(dot(N,V)),0,1))^5
color = mix(baseColor, edge_tint, F * edge_tint_strength)
brdf = ggx_base + clearcoat * ggx_clearcoat(clearcoat_roughness, F0=0.04)
```
## 13. Conformance tests
Test zero/full clearcoat, normal/grazing angles and fallback export/import.
## 14. Unsupported effects
RAGE carpaint, flake maps, multi-coat stacks and renderer-specific environment reflections.
