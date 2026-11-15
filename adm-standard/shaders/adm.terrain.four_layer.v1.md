# `adm.terrain.four_layer@1.0.0`

## 1. Identity and version
ID `adm.terrain.four_layer`, SemVer `1.0.0`.
## 2. Purpose and scope
Four albedo layers on ordinary mesh geometry, weighted by one RGBA blend mask.
## 3. Parameter table
| Name | Type | Default | Bounds |
|---|---|---|---|
| `layer{i}_texture` | TEXTURE | `null` | valid §8 texture ref, `i=0..3` |
| `layer{i}_base_color` | VEC4 | `[1,1,1,1]` | `[0,1]`, `i=0..3` |
| `layer{i}_metallic` | F32 | `0` | `[0,1]`, `i=0..3` |
| `layer{i}_roughness` | F32 | `0.8` | `[0,1]`, `i=0..3` |
| `layer{i}_metallic_texture` | TEXTURE | `null` | valid §8 texture ref, `i=0..3` |
| `layer{i}_roughness_texture` | TEXTURE | `null` | valid §8 texture ref, `i=0..3` |
| `layer{i}_{metallic,roughness}_channel` | F32 | `0` | `[0,3]`, `i=0..3` |
| `layer{i}_{metallic,roughness}_invert` | BOOL | `false` | `i=0..3` |
| `layer{i}_emissive` | VEC3 | `[0,0,0]` | finite nonnegative, `i=0..3` |
| `layer{i}_normal` | TEXTURE | `null` | valid §8 texture ref, `i=0..3` |
| `blend_mask` | TEXTURE | `null` | valid §8 texture ref |
| `uv_scale` | VEC4 | `[1,1,1,1]` | `[0.001,1000]` |
## 4. Mathematical contract
Mask channels are clamped nonnegative; `w_i=m_i/sum(m)` when sum>0, otherwise `w=[1,0,0,0]`.
Each layer albedo is its texture's linear RGB times its `base_color` RGB; base alpha is similarly factored.
For each metallic or roughness texture, round its channel parameter to the nearest integer
(`floor(value + 0.5)`): 0=R, 1=G, 2=B, 3=A. If its invert parameter is true, replace the sampled
value `s` with `1-s`. The result multiplies the corresponding layer factor. Without the texture,
the factor is used unchanged, regardless of channel and inversion.
Albedo, metallic, roughness, emissive and normal are each combined componentwise by the same `w_i`;
the weighted normal is normalized and a zero result is invalid.
## 5. Color spaces, units and texture channels
Layer albedo RGB is sRGB decoded; metallic, roughness, normal and blend-mask textures are linear data.
Metallic and roughness default to the red channel without inversion. UV scales are dimensionless.
## 6. Input textures
Each texture uses its own `texCoord`; each layer texture uses the corresponding `uv_scale` component.
The blend mask is not scaled.
## 7. Normal and tangent conventions
Each optional layer normal follows §8 tangent-space +Y encoding; missing layer normals use `[0,0,1]`.
## 8. Alpha and double-sided behavior
Alpha and culling follow the top-level PBR material fields in §8.
## 9. PBR fallback
Top-level PBR fields are mandatory for fallback; a reader without this profile ignores the layer extension and reports fallback.
## 10. Animation
No shader parameters are animatable. PBR animation is independent.
## 11. Allowed Blender Shader Nodes
Image Texture, UV Map, Separate Color, Math, Vector Math, Mix, Principled BSDF and Material Output.
## 12. Reference pseudocode
```text
w = normalize_nonnegative(mask.rgba, fallback=[1,0,0,0])
for i in 0..3:
    albedo[i] = srgb_to_linear(sample(layer[i], uv*uv_scale[i]).rgb) * layer[i].base_color.rgb
albedo = sum(w[i] * albedo[i] for i in 0..3)
metallic = sum(w[i] * layer[i].metallic * sample_channel_or_one(layer[i].metallic_texture,
               layer[i].metallic_channel, layer[i].metallic_invert) for i in 0..3)
roughness = sum(w[i] * layer[i].roughness * sample_channel_or_one(layer[i].roughness_texture,
                layer[i].roughness_channel, layer[i].roughness_invert) for i in 0..3)
normal = normalize(sum(w[i] * layer_normal[i] for i in 0..3))
shade_pbr(albedo, metallic, roughness, normal)
```
## 13. Conformance tests
Test one-hot masks, all-zero fallback, normalization and each PBR property/normal round-trip.
## 14. Unsupported effects
Height blending, terrain clipmaps and tessellation.
