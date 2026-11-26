# Layered material AO and height profiles

Status: normative shader profile contracts for ADM 1.0.

These additive profiles preserve every existing 1.0.0 and 2.0.0 contract:

| Profile | Base mask | Layers |
|---|---|---:|
| `adm.terrain.four_layer@1.1.0` | Linear RGBA `blend_mask` | 4 |
| `adm.terrain.four_layer@2.1.0` | `COLOR_1` weights, optionally multiplied by linear RGBA `blend_mask` | 4 |
| `adm.surface.two_layer@1.1.0` | Linear red `blend_mask` | 2 |
| `adm.pbr.layered@2.1.0` | `COLOR_1` weights | 4 |

The corresponding `1.0.0` and `2.0.0` profiles keep their original parameter
schemas and rendering behavior. The `2.x` profiles use the `COLOR_1` rules in
[`ADM_shader_vertex_masks_v2.md`](ADM_shader_vertex_masks_v2.md). Base weights
are clamped and normalized; an all-zero set selects layer 0. For the two-layer
profile, the mask's red channel is the layer 1 weight and layer 0 receives its
complement.

## Additional parameters

Each layer `i` adds the following fields to the corresponding base profile:

| Parameter | Type | Default | Bounds |
|---|---|---:|---:|
| `layer{i}_ao_texture` | TEXTURE | `null` | Linear data |
| `layer{i}_ao_channel` | F32 | `0` (R) | `[0,3]`, rounded by `floor(value + 0.5)` |
| `layer{i}_ao_invert` | BOOL | `false` | — |
| `layer{i}_ao_strength` | F32 | `1` | `[0,1]` |
| `layer{i}_height_texture` | TEXTURE | `null` | Linear data |
| `layer{i}_height_channel` | F32 | `0` (R) | `[0,3]`, rounded by `floor(value + 0.5)` |
| `layer{i}_height_invert` | BOOL | `false` | — |
| `layer{i}_height_scale` | F32 | `1` | `[0,1000]` |
| `layer{i}_height_bias` | F32 | `0` | `[-1,1]` |
| `layer{i}_parallax_scale` | F32 | `0` | `[0,1]` scaled UV units |
| `layer{i}_emissive_texture` | TEXTURE | `null` | sRGB color |

The emission map is multiplied by the existing linear `layer{i}_emissive` factor.

The profile also adds:

| Parameter | Type | Default | Bounds |
|---|---|---:|---:|
| `height_blend_enabled` | BOOL | `false` | — |
| `height_blend_transition` | F32 | `0.2` | `[0.001,1]` |
| `height_blend_strength` | F32 | `1` | `[0,1]` |
| `parallax_mode` | ENUM | `NONE` | `NONE`, `PARALLAX`, `PARALLAX_OCCLUSION` |
| `parallax_reference_height` | F32 | `0.5` | `[0,1]` |
| `parallax_min_steps` | F32 | `8` | Integer `[1,256]` |
| `parallax_max_steps` | F32 | `32` | Integer `[1,256]`, at least the minimum |

`ENUM` parameters declare a non-empty `values` string array. Their values are
case-sensitive strings from that array and are not animatable.

Each non-null texture reference for a layer MUST use the same `texCoord` as
`layer{i}_texture`; if that albedo reference is absent, the other layer maps
MUST use `TEXCOORD_0`. `texCoord` defaults to 0. `uv_scale[i]` applies to every
texture in layer `i`, including AO and height. Texture dimensions need not match.
The blend masks are not scaled. Readers MUST sample each texture with its own
sampler and MUST NOT resample all maps to a shared resolution.

## Height sampling and blending

Select the named linear channel and apply inversion before scale and bias:

```text
sample = selected_channel(height_texture, uv)
if invert:
    sample = 1 - sample
height = clamp(sample * height_scale + height_bias, 0, 1)
```

Height 0 is the lowest surface point and 1 is the highest. A missing height
texture contributes neutral height 0.5. If every layer height texture is
missing, height blending returns the original normalized weights. Height maps
do not change geometry, collision, bounds, terrain elevation, or LOD data.

When `height_blend_enabled` is false or `height_blend_strength` is zero, final
weights equal the base weights. Otherwise, among layers with positive base
weight, let `h_max` be the largest sampled height. For each layer:

```text
q[i] = w[i] * exp(clamp((height[i] - h_max) / transition, -80, 0))
heightWeight[i] = q[i] / sum(q)
finalWeight[i] = mix(w[i], heightWeight[i], strength)
```

The implementation MUST normalize the final weights after mixing to account
for floating-point error. It MUST preserve zero base weights, one-hot weights,
and permutation invariance; weights MUST remain finite and nonnegative and sum
to 1. Equal heights reproduce the base weights. If every base weight is zero,
layer 0 is selected before height blending.

## Per-layer ambient occlusion

AO samples are linear data. Select and optionally invert the requested channel,
then compute:

```text
layerAO[i] = mix(1, sample, ao_strength)
```

An absent AO texture contributes 1. The layered result is
`sum(finalWeight[i] * layerAO[i])`. Combine it multiplicatively with the
ordinary top-level occlusion result, after applying that result's ordinary
strength: `finalAO = topLevelAO * layeredAO`. A missing top-level occlusion
texture contributes 1.

AO attenuates indirect diffuse lighting only. It MUST NOT darken direct
lighting, emission, or base-color samples. A preview renderer that cannot
separate indirect lighting MAY use an approximation, but MUST identify that
approximation in its UI or export diagnostics.

## Parallax and parallax occlusion

`NONE` applies no UV offset. `PARALLAX` computes one height-based offset.
`PARALLAX_OCCLUSION` marches a view ray through the selected layer's height
field and linearly refines the first intersection. Both modes are optional
material-space effects and MUST NOT displace geometry.

For each active layer, transform the view direction into its tangent frame and
normalize it. A back-facing direction (`view.z <= 0`), a zero parallax scale,
or a missing height texture produces a zero offset. Clamp the denominator to
`max(view.z, 0.1)` at grazing angles. The single-step depth is
`height - parallax_reference_height`; its raw offset is
`-view.xy / max(view.z, 0.1) * depth * layer{i}_parallax_scale`. Clamp the
offset vector length to `layer{i}_parallax_scale`.

For occlusion mode, select
`round(min_steps + (max_steps - min_steps) * (1 - clamp(view.z,0,1)))` steps.
March from depth 0 through 1 along the same bounded ray. The intersection is
the first point where `rayDepth >= 1 - sampledHeight`; interpolate between the
previous and current signed distances to refine it. Stop at `max_steps`. This
defines a bounded linear approximation, not a geometry or silhouette change.

Compute base weights once at the original UVs. Parallax samples only each
active layer's own height map and MUST NOT recalculate or feed back into base
weights. Apply each layer's offset to all that layer's maps, including its
height and AO maps, then compute optional height-blend weights from the
offset height samples. Each layer's sampler wrap mode controls out-of-range UVs.
The same texture LOD rule applies to each ray sample; implementations SHOULD
use a stable gradient or explicitly selected mip to avoid divergent mip choice
during a ray march.

Parallax requires a valid tangent frame. If a reader lacks tangents, it MUST
disable parallax for the affected primitive and report the limitation; it
continues with unshifted samples. A renderer that does not implement the
selected parallax mode retains the material's other profile behavior and
reports the fallback. POM steps are integers satisfying
`1 <= parallax_min_steps <= parallax_max_steps <= 256`.

## PBR output, fallback, and capability

Use the same final weights for albedo, alpha, normal, metallic, roughness,
emission, and AO. Decode albedo and emission RGB from sRGB before multiplying
their linear factors. Scalar maps and normal maps are linear. Blend
tangent-space normals with the final weights and normalize; a zero-length
result becomes `(0,0,1)`. A missing layer normal is `(0,0,1)`. Preserve the
existing top-level PBR fields as the portable fallback.

`ADM-SHADER-LAYERED-HEIGHT-1` is an optional reader capability. It means the
reader validates and renders all four profiles in this document, including
their AO, height blending, parallax, and POM behavior, and reports unsupported
features. It is separate from `ADM-SHADER-LAYERED-1`; a reader MUST NOT claim
this capability when it only implements the older layer blend.

## Conformance cases

Implementations claiming `ADM-SHADER-LAYERED-HEIGHT-1` MUST pass positive and
negative tests for:

- all four exact profile identities and preservation of old profile behavior;
- default values, bounds, enum values, texture references, and integer POM
  step ordering;
- linear channel selection, inversion, scale, bias, clipping, and missing maps;
- AO strength, neutral missing maps, and top-level AO combination;
- normalized weights, zero-weight preservation, one-hot inputs, equal heights,
  all-missing heights, zero-strength behavior, and layer-order permutation;
- finite single-step offsets, grazing-angle clamping, back-face behavior,
  bounded POM steps, and first-intersection refinement;
- consistent per-layer UV sets and texture sampling, with mismatched map sizes;
- PBR fallback preservation and no changes to mesh geometry, collision, bounds,
  or terrain LOD data.
