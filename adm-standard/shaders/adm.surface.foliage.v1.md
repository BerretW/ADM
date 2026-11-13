# `adm.surface.foliage@1.0.0`

## 1. Identity and version
ID `adm.surface.foliage`, SemVer `1.0.0`.
## 2. Purpose and scope
Two-sided leaf, grass and foliage cards using mesh geometry and a hard alpha mask.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `backface_tint` | VEC3 | `[0.75,0.9,0.65]` | `[0,1]` |
| `transmission` | F32 | `0.2` | `[0,1]` |
## 4. Mathematical contract
Let `b=1` for back-facing fragments and `0` otherwise. `C=mix(baseColor,baseColor*backface_tint,b*transmission)`.
This is a deterministic orientation tint, not a light-transport simulation.
## 5. Color spaces, units and texture channels
Base color and tint use linear RGB after §8 texture decoding. `transmission` is dimensionless.
## 6. Input textures
Base-color alpha is the cutout mask; other textures follow §8.
## 7. Normal and tangent conventions
Normal maps use the §8 tangent-space +Y convention.
## 8. Alpha and double-sided behavior
Requires `alphaMode=MASK` and `doubleSided=true`. The inclusive threshold follows §8.
## 9. PBR fallback
Explicit §8 fallback fields are mandatory; fallback remains ordinary PBR.
## 10. Animation
No shader parameters are animatable; PBR fields may use standard animation.
## 11. Allowed Blender Shader Nodes
Geometry Backfacing, Math, Mix, Image Texture, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
back = 1 if fragment_is_back_facing else 0
color = mix(base_color, base_color * backface_tint, back * transmission)
discard_if(base_alpha < alphaCutoff)
```
## 13. Conformance tests
Test front/back outputs, mask cutoff boundaries, two-sided mode and fallback round-trip.
## 14. Unsupported effects
Light-direction transmission, leaf-volume scattering, wind deformation and subsurface scattering.
