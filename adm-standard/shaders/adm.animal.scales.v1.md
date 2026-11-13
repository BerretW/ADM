# `adm.animal.scales@1.0.0`

## 1. Identity and version
ID `adm.animal.scales`, SemVer `1.0.0`.
## 2. Purpose and scope
Textured scale surfaces for reptiles, fish and similar models.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---:|---|
| `detail_texture` | TEXTURE | `null` | valid §8 texture ref |
| `scale_normal` | TEXTURE | `null` | valid §8 texture ref |
| `specular_strength` | F32 | `0.5` | `[0,1]` |
| `scale_metallic` | F32 | `0` | `[0,1]` |
## 4. Mathematical contract
Core PBR is evaluated with `metallic=scale_metallic`; optional detail RGB multiplies base color in linear space.
`specular_strength` scales dielectric F0 from 0.04 to 0.08.
## 5. Color spaces, units and texture channels
Detail RGB is sRGB-decoded. Strength and metallic are dimensionless.
## 6. Input textures
Optional detail color and normal parameters; normal channels follow §8.
## 7. Normal and tangent conventions
Scale normal uses tangent-space +Y and is normalized after applying normal scale.
## 8. Alpha and double-sided behavior
Alpha/culling follow §8.
## 9. PBR fallback
Ordinary PBR fields are required; unsupported readers ignore detail/specular adjustment.
## 10. Animation
No shader parameters animatable.
## 11. Allowed Blender Shader Nodes
Image Texture, Normal Map, Math, Mix, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
base = baseColor * srgb_to_linear(detail.rgb) if detail exists else baseColor
F0 = mix(0.04, 0.08, specular_strength)
shade_ggx(base, scale_metallic, F0, mapped_normal)
```
## 13. Conformance tests
Test detail multiplication, normal decoding, F0 endpoints and fallback.
## 14. Unsupported effects
Procedural scale generation, tessellation, displacement and microgeometry.
