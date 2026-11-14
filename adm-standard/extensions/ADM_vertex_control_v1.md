# `ADM_vertex_control_v1`

Version 1.1.0, incorporated by ADM Draft 0.4 P10.

Version 1.1.0 allows tint palettes 1–5 texels high (1.0.0 required exactly one row). Only the first
row is read, so every valid 1.0.0 file keeps its meaning; a 1.0.0 reader rejects taller palettes.

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

The extension's optional material `parameters` object MAY contain these controls:

| Name | Default | Bounds |
|---|---:|---:|
| `tintOffset` | `0` | `[-1024,1024]` |
| `normalMultiplier` | `1` | `[0,4]` |
| `reflectionMultiplier` | `1` | `[0,4]` |
| `wetnessOffset` | `0` | `[-1,1]` |

An omitted value uses its default. These names are extension-level parameters; they are not members
of each shader's `shaderParameters` schema. They MAY be targeted by ADM_ANIM `shaderParameter`
channels using the material's exact `shaderId` and `shaderVersion` as the binding identity. Such an
animation library MUST list `ADM_vertex_control_v1` in both `extensionsUsed` and `extensionsRequired`.
The channels use scalar values and the bounds in this table. They animate the material parameter and
MUST NOT rewrite `COLOR_0`.

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

`tintPalette` is optional and MUST reference a texture whose resolved image is an RGBA image `N`
texels wide (`N >= 1`) and 1 to 5 texels high. Only the **first row** — the top row, i.e. the first
row stored in the image file, at texture coordinate `v = 0.5 / height` — defines the palette; other
rows carry no ADM meaning, MUST be ignored by readers and MUST NOT be sampled. Readers MUST reject a
palette higher than 5 texels. `tintMode` is `MULTIPLY` or `REPLACE` and defaults to `MULTIPLY`. Palette
RGB is sRGB-encoded in the image and is decoded to linear RGB before use. Alpha is linear. Palette
entries are unassociated (straight-alpha) colors. The red control channel selects a discrete texel:

```text
position = clamp(COLOR_0.R, 0, 1) * N + tintOffset
index = clamp(floor(position), 0, N - 1)
palette = decode_sRGB(texel[index].rgb), texel[index].a
```

The sample is at the center of the selected texel in the first row with nearest filtering;
interpolation between entries or rows is
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

For every profile in the Core 20 table below, all four channels are reserved and MUST NOT affect
shading. The missing-attribute default is `(0,0,0,0)`. Writers and readers MAY preserve explicit
channel values for round-trip editing, but renderers MUST ignore them for these profile versions.
This intentionally reserves future per-profile behavior for a new profile version; readers MUST NOT
infer effects from textures, similarly named parameters, or another shader's `COLOR_1` contract.

| Registered shader profile | R | G | B | A | Missing default | Rendering effect |
|---|---|---|---|---|---|---|
| `adm.pbr.metallic_roughness@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.pbr.layered@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.cutout@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.emissive@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.decal@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.glass@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.foliage@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.terrain.four_layer@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.vehicle.paint@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.character.skin@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.animal.fur@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.animal.feather@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.animal.scales@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.building.concrete@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.building.brick@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.building.roof@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.nature.bark@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.nature.rock@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.nature.water@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |
| `adm.surface.fabric@1.0.0` | reserved | reserved | reserved | reserved | `(0,0,0,0)` | none |

These neutral contracts close the Core 20 channel mapping without inventing behavior from existing
shader parameters. A profile not listed above has no defined `COLOR_1` behavior; a reader MUST report
that unsupported behavior rather than guess.

## Blender reference implementation status

The Blender add-on transports `COLOR_0`/`COLOR_1`, the tint palette reference and the four
extension-level parameter values through export/import. Its authoring tools initialize missing
layers to the documented defaults, reset all or selected face corners, and write individual linear
channels. The tint swatch picker writes a normalized, offset-aware palette position to `COLOR_0.R`,
preserving G/B/A. Import materializes omitted optional controls; vertex-control export writes
their documented defaults without changing the Blender source mesh. Ordinary color assets without
this extension retain their original semantics. It supports ADM_ANIM binding and playback
for these parameters by extension-defined name and exact shader identity. Vertex-control preview
nodes apply the tint palette, normal-strength, wetness-color, wetness-roughness and F0 rules. For F0,
the preview mixes dielectric and metallic Principled lobes at the material metallic factor: the
dielectric lobe receives an IOR derived from the exact effective scalar F0, while the metallic lobe
uses the exact effective RGB F0 as its base color. Blender Cycles bake tests verify both node paths.
`COLOR_1` remains transport-only, and the bake tests do not establish interoperability with an
independent renderer. These limitations are not full renderer or extension conformance.
