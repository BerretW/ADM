# `ADM_terrain_macro_color_v1`

Version 1.0.0 defines a shared or local terrain color overlay. It changes
rendered albedo only; it does not change terrain weights, surface identity,
geometry, or physical collision assignments.

## Declaration and profile compatibility

Version 1.0.0 applies to the registered four-layer terrain profiles:
`adm.terrain.four_layer@1.0.0`, `adm.terrain.four_layer@2.0.0`,
`adm.terrain.four_layer@1.1.0`, `adm.terrain.four_layer@2.1.0`, and
`adm.pbr.layered@2.1.0`. Custom profiles and profiles with a different layer
count are not valid for this extension version. The material MUST map its four
local layers to four stable IDs in `ADM_terrain_surface_v1.surfaceIds`.

The extension MUST be listed in both `extensionsUsed` and `extensionsRequired`.
Add this object to the material:

```json
{
  "extensions": {
    "ADM_terrain_macro_color_v1": {
      "version": "1.0.0",
      "texture": {"index": 3, "texCoord": 0},
      "projection": "LOCAL_UV",
      "blendMode": "MULTIPLY",
      "strength": 1.0,
      "layerInfluence": [1.0, 1.0, 1.0, 1.0],
      "scale": [1.0, 1.0],
      "offset": [0.0, 0.0]
    }
  }
}
```

The object MUST contain `version`, `texture`, `projection`, and `blendMode`.
It MAY contain `origin`, `scale`, `offset`, `strength`, and `layerInfluence`.
No other fields are defined in version 1.0.0. `version` MUST be `"1.0.0"`.
Readers that do not support this extension MUST reject assets that require it.

## Projection and sampling

`projection` MUST be `LOCAL_UV` or `SHARED_WORLD_XZ`.

- `LOCAL_UV` samples the selected `TEXCOORD_0` or `TEXCOORD_1`. The texture
  reference's `texCoord` defaults to 0. `origin` is not valid.
- `SHARED_WORLD_XZ` samples asset-space position after node transforms and
  before renderer floating-origin subtraction. The texture reference MUST omit
  `texCoord`. `origin` is an optional two-component XZ position in meters and
  defaults to `[0,0]`.

Both projections transform coordinates as follows:

```text
uv = source * scale + offset
```

For `LOCAL_UV`, `source` is the selected UV. For `SHARED_WORLD_XZ`,
`source = ([position.x, position.z] - origin)`. `scale` defaults to `[1,1]`;
its components MUST be finite and bounded by `1e6`, and it MUST NOT be
`[0,0]`. `offset` defaults to `[0,0]`; its components MUST be finite and
bounded by `1e9`. `origin` components MUST be finite and bounded by `1e9`.
Floating-origin shifts MUST NOT change sampled coordinates. Adjacent tiles
using a shared map MUST use the same coordinate phase and agree at shared
borders.

The referenced image MUST provide at least three decoded color channels. RGB
is sRGB-encoded and MUST be decoded to linear light before evaluation. Alpha,
when present, is linear; a three-channel image has implicit alpha `1`. GPU
texture sources MUST use an sRGB format, and their portable fallbacks MUST
provide at least three channels. Samplers MUST use `LINEAR` minification and
magnification filters. Readers MUST select mip levels from coordinate
derivatives and linearly interpolate between available levels. Separately
tiled images MUST have matching border texels and mip gutters over the full
filter footprint.

## Blend modes

The input layer albedos and output are linear RGB. `strength` defaults to `1`
and MUST be in `[0,1]`. `layerInfluence` defaults to `[1,1,1,1]` and MUST be a
four-component vector in `[0,1]`. Its order matches the four local layers and
stable IDs. Let `B_i` be the linear base albedo of layer `i`, `M` the sampled
linear macro RGB, `A` the sampled linear alpha (or `1` when absent), and:

```text
f_i = clamp(strength * layerInfluence[i], 0, 1)
```

The equations below apply independently to each layer. Combine the results
using the material's final normalized terrain weights `w_i`:

```text
output = sum(w_i * layerResult_i)
```

| `blendMode` | `layerResult_i` |
|---|---|
| `MULTIPLY` | `B_i * (1 - f_i + f_i * M)`; alpha is ignored |
| `TINT` | `B_i * (1 - f_i*A + f_i*A*M)` |
| `LERP` | `(1 - f_i*A) * B_i + f_i*A*M` |

`MULTIPLY` and `TINT` use component-wise RGB multiplication. A white map is
neutral for both. Alpha zero is neutral for `TINT` and `LERP`. Zero strength,
zero per-layer influence, or a missing/unavailable map leaves the base albedo
unchanged. A reader that cannot decode the map MUST report that it is
unavailable and use the base albedo without the macro effect.

## Evaluation and physical-surface independence

Sample the macro map in its declared projection, independently of per-layer
parallax. Apply its blend mode to each layer's linear base albedo, then combine
the results using the final weights after Control Map evaluation and the
shader profile's height blending. Do not shift Macro Color coordinates by
view-dependent parallax.

Macro Color MUST NOT affect collision generation or physical-material
classification. Physical classification MUST use stable authored,
camera-independent weights and physical-material references; it MUST NOT use
macro color, final color, lighting, or view-dependent shader output.

## Conformance

- `TMC-001`: validate declaration, version, four-layer profile, stable IDs,
  texture reference, image channels, color space, sampler, projection, and
  numeric bounds.
- `TMC-002`: verify sRGB-to-linear decoding and the `MULTIPLY`, `TINT`, and
  `LERP` equations with independent vectors.
- `TMC-003`: verify neutral strength/influence, alpha behavior, missing-map
  fallback, layer ordering, and weighted combination.
- `TMC-004`: verify local UV and shared world coordinates, including
  floating-origin invariance and shared-edge samples.
- `TMC-005`: verify derivative-based filtering, mip selection, border
  continuity, and independence from per-layer parallax in renderers.
- `TMC-006`: verify physical assignments remain unchanged when Macro Color,
  camera, lighting, or parallax changes.
