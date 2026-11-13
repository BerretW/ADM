# `adm.animal.fur@1.0.0`

## 1. Identity and version
ID `adm.animal.fur`, SemVer `1.0.0`.
## 2. Purpose and scope
Mesh-based fur and hair cards; individual strands remain geometry.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `fur_detail` | TEXTURE | `null` | valid §8 texture ref |
| `fiber_tint` | VEC3 | `[0.8,0.7,0.6]` | `[0,1]` |
| `fiber_roughness` | F32 | `0.35` | `[0,1]` |
| `anisotropy` | F32 | `0.35` | `[0,1]` |
## 4. Mathematical contract
Base lobe is core PBR. Fiber lobe is `weight=anisotropy*(1-roughness)` and uses the tangent-aligned GGX distribution;
its linear color is `fiber_tint * detail.r` when detail exists, else `fiber_tint`.
## 5. Color spaces, units and texture channels
Base RGB follows §8 sRGB decoding; detail R is linear; all weights are dimensionless.
## 6. Input textures
`fur_detail` is optional and its red channel modulates fiber lobe energy. Alpha cards use core base alpha.
## 7. Normal and tangent conventions
Use ADM tangent and bitangent; strand direction is the normalized tangent attribute.
## 8. Alpha and double-sided behavior
Alpha/culling follow §8; hair-card cutout uses `MASK`.
## 9. PBR fallback
Top-level PBR fallback is required; unsupported readers omit only the fiber lobe.
## 10. Animation
No shader parameters animatable.
## 11. Allowed Blender Shader Nodes
Anisotropic BSDF/Principled anisotropy, Tangent, Image Texture, Math and Material Output.
## 12. Reference pseudocode
```text
fiberColor = fiber_tint * (fur_detail.r if present else 1)
fiberWeight = anisotropy * (1 - fiber_roughness)
shade = core_pbr + fiberWeight * tangent_ggx(T, fiber_roughness, fiberColor)
```
## 13. Conformance tests
Test tangent rotation, anisotropy endpoints, detail modulation and fallback.
## 14. Unsupported effects
Hair tessellation, strand generation, grooming, wind simulation and vendor-specific hair BRDFs.
