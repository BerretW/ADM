# `ADM_vertex_control_v1`

Version 1.0.0, incorporated by ADM Draft 0.4 P10.

## Declaration and compatibility

A file using this capability MUST list `ADM_vertex_control_v1` in both `extensionsUsed` and
`extensionsRequired`. It applies to every mesh primitive. A reader that does not support it MUST
reject the asset; it MUST NOT interpret `COLOR_0` as ordinary vertex color. Without this extension,
Draft 0.4 `COLOR_0` retains its original linear RGBA color meaning.

This is the sole registered exception to the core rule that extensions do not redefine a core
semantic. The exception is explicit and versioned; files lacking the required declaration are never
interpreted as vertex-control files.

## `COLOR_0`

`COLOR_0` remains an optional `U8 normalized VEC4` or `F32 VEC4` vertex attribute. In this extension
its values are four independent linear control channels, each in `[0,1]`:

| Channel | Meaning |
|---|---|
| R | Tint-palette position |
| G | Normal-map strength |
| B | Base specular reflectivity scale |
| A | Surface wetness |

When `COLOR_0` is absent, its value is `(0,1,1,0)`. Values are linearly interpolated over each
triangle before material evaluation. Exporters MUST clamp values to `[0,1]`; readers MUST reject
out-of-range F32 values. U8 values are divided by 255.

The material's numeric `shaderParameters` MAY include the following standard animatable parameters;
all official Core 20 profiles define them with the listed defaults and bounds:

| Name | Default | Bounds |
|---|---:|---:|
| `tintOffset` | `0` | `[-1024,1024]` |
| `normalMultiplier` | `1` | `[0,4]` |
| `reflectionMultiplier` | `1` | `[0,4]` |
| `wetnessOffset` | `0` | `[-1,1]` |

An omitted value uses its default. They use the existing `shaderParameter` animation target and do
not animate or rewrite vertex buffers. A material needs `animationId` only when an animation
actually targets it.

## Tint palette

A material MAY declare:

```json
{
  "extensions": {
    "ADM_vertex_control_v1": {
      "tintPalette": {"index": 0, "texCoord": 0},
      "tintMode": "MULTIPLY",
      "parameters": {
        "tintOffset": 0,
        "normalMultiplier": 1,
        "reflectionMultiplier": 1,
        "wetnessOffset": 0
      }
    }
  }
}
```

`parameters` is optional; missing members use the defaults and bounds in the table above. No other
parameter names are allowed in this object. These parameters use the existing material-animation
`shaderParameter` channel kind with the corresponding exact shader identity. The animation file MUST
declare this extension as required if it contains one of these targets. `animationId` is required
when a channel actually targets the material; the mere availability of animatable parameters does
not require an ID.

`tintPalette` is optional and MUST reference a texture whose resolved image is a one-row RGBA image
with at least one texel. `tintMode` is `MULTIPLY` or `REPLACE` and defaults to `MULTIPLY`. Palette
RGB is sRGB-encoded in the image and is decoded to linear RGB before use. Alpha is linear. Palette
entries are unassociated (straight-alpha) colors. The red control channel selects a discrete texel:

```text
position = clamp(COLOR_0.R, 0, 1) * N + tintOffset
index = clamp(floor(position), 0, N - 1)
palette = decode_sRGB(texel[index].rgb), texel[index].a
```

The sample is at the selected texel center with nearest filtering; interpolation between entries is
forbidden. `MULTIPLY` multiplies base RGB and alpha by palette RGBA. `REPLACE` replaces base RGB with
palette RGB and leaves base alpha unchanged. The palette operation occurs after the base-color factor
and texture, and before wetness.

## Normal strength, reflectivity and wetness

For tangent-space normal sample `q = 2*RGB-1`, with base normal-texture scale `s0`:

```text
s = clamp(COLOR_0.G * normalMultiplier, 0, 1) * s0
n = normalize((q.x*s, q.y*s, q.z))
```

The renderer MUST apply this to the tangent-space normal before tangent-to-surface transformation.
The output is normalized. If there is no normal texture, this channel has no effect.

Let `F0` be the material's linear base reflectance at normal incidence after its metallic/roughness
model forms the dielectric/metal mixture. The reflectivity scale is
`r = clamp(COLOR_0.B * reflectionMultiplier, 0, 1)` and `F0r = r * F0`. It scales the specular
BRDF input, not the shaded pixel color or diffuse term.

Effective wetness is `w = clamp(COLOR_0.A + wetnessOffset, 0, 1)`. It MUST be applied once, after
the shader's base material parameters:

```text
baseColor.rgb *= 1 - 0.15*w
roughness = mix(baseRoughness, min(baseRoughness, 0.10), w)
F0water = ((1.333 - 1) / (1.333 + 1))^2
F0effective = mix(F0r, F0water + (1 - F0water)^2 * F0r, w)
```

This is a single thin-water coat approximation. Implementations MUST NOT also add a second wetness
reflectivity multiplier or multiply the final pixel color. Shader-specific wetness controls, if any,
MUST be explicitly specified by that shader's versioned contract and MUST be applied in addition to
these universal effects without reapplying them.

## `COLOR_1`

`COLOR_1`, when present, is an optional `U8 normalized VEC4` or `F32 VEC4` shader-specific attribute
with values in `[0,1]`. It is valid only with this extension. Its R/G/B/A meanings, defaults and
operations are defined by the exact registered shader profile. Missing `COLOR_1` uses that profile's
documented default. A reader MUST report unsupported `COLOR_1` behavior and MUST NOT guess a
cross-profile interpretation.

The initial Core 20 per-shader `COLOR_1` table and executable renderer conformance fixtures are
pending; the generic attribute transport does not claim shader-specific `COLOR_1` conformance.
