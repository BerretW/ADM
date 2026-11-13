# `adm.surface.cutout@1.0.0`

## 1. Identity and version

Shader ID is `adm.surface.cutout`; exact SemVer is `1.0.0`.

## 2. Purpose and scope

This profile defines a portable hard alpha cutout for fences, grilles, leaves and similar surfaces.
It adds no proprietary rendering behavior.

## 3. Parameter table

There are no `shaderParameters`. The profile uses ordinary ADM §8 PBR fields:

| Field | Type | Range/default | Meaning |
|---|---|---|---|
| `alphaMode` | enum | MUST be `MASK` | Enables hard alpha discard |
| `alphaCutoff` | F32 | `[0,1]`, default `0.5` | Inclusive surviving threshold |
| `baseColorFactor.a` | F32 | `[0,1]`, default `1` | Scalar alpha multiplier |

`baseColorTexture` and `doubleSided` use the ordinary §8 definitions.

## 4. Mathematical contract

Let `A = baseColorFactor.a × T.a`, where `T.a` is sampled base-color texture alpha, or `1` when
the texture is absent. Discard iff `A < alphaCutoff`; equality is retained. The material MUST set
`alphaMode` to `MASK`.

## 5. Color spaces, units and texture channels

Base-color RGB follows ADM §8 sRGB decoding and linear factor multiplication. Alpha has no unit,
is linear, and is not gamma-decoded. The texture alpha channel is used as stored by the decoded image.

## 6. Input textures

`baseColorTexture` is the only texture input added to the cutout calculation. Its UV selection,
sampling and sRGB behavior follow §8. Other standard PBR textures remain available for shading.

## 7. Normal and tangent conventions

Normals, tangent space, normal textures and tangent handedness follow ADM §8. This profile does not
add or alter a normal convention.

## 8. Alpha and double-sided behavior

Alpha behavior is exactly the formula in §4. `doubleSided` follows ADM §8: false culls back faces;
true disables culling and reverses back-face normals for lighting. MSAA and alpha-to-coverage are
not required.

## 9. PBR fallback

The ordinary ADM §8 PBR fields are the rendering contract. As a non-core profile, a material MUST
serialize every explicit portable fallback field required by §8, including `alphaMode: "MASK"`.
Readers without this profile use core PBR fallback and report `SHADER_FALLBACK`.

## 10. Animation

This profile declares no shader parameters. Standard `pbrParameter` animation of supported fallback
fields remains governed by ADM §15. Animation of `alphaMode` is not defined.

## 11. Allowed Blender Shader Nodes

The reference graph uses standard Image Texture, Math comparison, Principled BSDF and Material
Output nodes. The alpha comparison implements discard iff alpha is strictly less than the cutoff.
The node graph itself is not serialized into ADM.

## 12. Reference pseudocode

```text
alpha = baseColorFactor.a
if baseColorTexture exists:
    alpha = alpha * sample(baseColorTexture, uv).a
if alpha < alphaCutoff:
    discard
shade_core_pbr()
```

## 13. Conformance tests

An implementation MUST verify `alphaMode = MASK`, that alpha equal to the cutoff passes, alpha
below it is discarded, and absent texture alpha behaves as 1. It MUST preserve shader ID/version
and fallback PBR values through export and import.

## 14. Unsupported effects

Soft transparency, alpha-to-coverage, stochastic coverage, screen-door dithering and renderer-specific
transparency are not part of this profile.
