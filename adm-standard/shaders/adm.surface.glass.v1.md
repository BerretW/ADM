# `adm.surface.glass@1.0.0`

## 1. Identity and version
ID `adm.surface.glass`, SemVer `1.0.0`.
## 2. Purpose and scope
Thin, alpha-blended glass without scene refraction. This is a mesh surface, not a screen-space effect.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `glass_tint` | VEC3 | `[0.8,0.9,1]` | `[0,1]` per component |
| `reflection_tint` | VEC3 | `[1,1,1]` | `[0,1]` per component |
| `transparency` | F32 | `0.9` | `[0,1]` |
| `ior` | F32 | `1.5` | `[1,2.5]` |
## 4. Mathematical contract
`c=clamp(abs(dot(N,V)),0,1)`, `F0=((ior-1)/(ior+1))^2`, `F=F0+(1-F0)(1-c)^5`.
`C=mix(glass_tint,reflection_tint,F)` and coverage `A=1-transparency*(1-F)`, multiplied by base alpha.
## 5. Color spaces, units and texture channels
Tints are linear RGB; IOR and transparency are dimensionless. Base-color texture follows §8.
## 6. Input textures
Ordinary §8 PBR textures are optional; no scene color or refraction texture is read.
## 7. Normal and tangent conventions
`N` uses the normalized geometric/shading normal after the §8 normal map; `V` points toward the viewer.
## 8. Alpha and double-sided behavior
Requires `alphaMode=BLEND`; straight-alpha compositing follows §8. Double-sided uses §8.
## 9. PBR fallback
All explicit §8 fallback fields are mandatory. Unsupported readers render PBR and report fallback.
## 10. Animation
`transparency` is animatable; other shader parameters are static. PBR animation remains independent.
## 11. Allowed Blender Shader Nodes
Image Texture, Geometry, Vector Math, Math, Mix, Principled BSDF and Material Output. No refraction nodes.
## 12. Reference pseudocode
```text
F = schlick(abs(dot(normalize(N), normalize(V))), ior)
color = mix(glass_tint, reflection_tint, F)
alpha = base_alpha * (1 - transparency * (1 - F))
blend_straight(color, alpha)
```
## 13. Conformance tests
Test normal incidence, grazing incidence, IOR bounds, alpha composition and fallback round-trip.
## 14. Unsupported effects
Scene refraction, thickness absorption, screen-space reflection, bloom and path-traced caustics.
