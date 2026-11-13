# `adm.surface.fabric@1.0.0`

## 1. Identity and version
ID `adm.surface.fabric`, SemVer `1.0.0`.
## 2. Purpose and scope
Portable fabric and upholstery with tangent-aligned fiber response.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `fiber_detail` | TEXTURE | `null` | valid §8 texture ref |
| `detail_normal` | TEXTURE | `null` | valid §8 texture ref |
| `fiber_tint` | VEC3 | `[0.9,0.85,0.8]` | `[0,1]` |
| `fiber_strength` | F32 | `0.25` | `[0,1]` |
| `anisotropy` | F32 | `0.4` | `[0,1]` |
## 4. Mathematical contract
Base is core PBR. Add tangent GGX lobe with `weight=fiber_strength*anisotropy`; color is `fiber_tint*detail.r` or `fiber_tint`.
## 5. Color spaces, units and texture channels
Fiber detail R is linear; tint is linear RGB; weights dimensionless.
## 6. Input textures
Optional linear fiber detail and tangent-space detail normal; base textures follow §8.
## 7. Normal and tangent conventions
Detail normal uses §8; anisotropy direction is the normalized tangent attribute.
## 8. Alpha and double-sided behavior
Alpha and culling follow §8; alpha mask is optional.
## 9. PBR fallback
Top-level PBR fallback is required; fallback omits the fiber lobe.
## 10. Animation
No shader-specific parameters animatable.
## 11. Allowed Blender Shader Nodes
Anisotropic BSDF/Principled anisotropy, Tangent, Image Texture, Normal Map and Material Output.
## 12. Reference pseudocode
```text
fiberColor = fiber_tint * (fiber_detail.r if present else 1)
shade = core_pbr + fiber_strength*anisotropy*tangent_ggx(T, fiberColor)
```
## 13. Conformance tests
Test tangent orientation, lobe endpoints, optional texture and fallback.
## 14. Unsupported effects
Thread simulation, displacement weave, procedural fiber generation and vendor-specific cloth BRDFs.
