# `adm.nature.water@1.0.0`

## 1. Identity and version
ID `adm.nature.water`, SemVer `1.0.0`.
## 2. Purpose and scope
Thin water surface with Fresnel and optional deterministic UV offset animation.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `water_tint` | VEC3 | `[0.05,0.25,0.35]` | `[0,1]` |
| `transparency` | F32 | `0.8` | `[0,1]` |
| `ior` | F32 | `1.333` | `[1,2.5]` |
| `uv_velocity` | VEC2 | `[0,0]` | `[-10,10]` |
## 4. Mathematical contract
Schlick `F` uses `ior`; `alpha=1-transparency*(1-F)` and color is `mix(water_tint,white,F)`.
UV offset is `fract(uv + uv_velocity*time)` where time is seconds from clip start.
## 5. Color spaces, units and texture channels
Tint is linear RGB; velocity is UV units/second; IOR dimensionless.
## 6. Input textures
Optional core normal texture; no depth or scene-color input.
## 7. Normal and tangent conventions
Mapped tangent normal follows §8.
## 8. Alpha and double-sided behavior
Requires `alphaMode=BLEND`; straight alpha follows §8. No scene refraction.
## 9. PBR fallback
Required top-level PBR fallback; fallback uses static PBR factors.
## 10. Animation
`transparency` and `uv_velocity` may be animated. UV animation is evaluated against clip time.
## 11. Allowed Blender Shader Nodes
Texture Coordinate, Vector Math, Math, Fresnel/Layer Weight, Mix, Principled BSDF and Output.
## 12. Reference pseudocode
```text
uv2 = fract(uv + uv_velocity*time)
F = schlick(abs(dot(N,V)), ior)
alpha = 1 - transparency*(1-F)
blend_straight(mix(water_tint, white, F), alpha)
```
## 13. Conformance tests
Test normal/grazing Fresnel, UV wrap, alpha compositing and zero velocity.
## 14. Unsupported effects
Depth absorption, foam, displacement waves, SSR, ray tracing and scene refraction.
