# `ADM_terrain_control_map_v1`

Version 1.0.0 defines texture-based material weights for four-layer terrain
materials. A Control Map is linear weight data, not a color map. It replaces
or combines with the material's existing `COLOR_1` weights before per-layer
projection, parallax, and height blending.

## Declaration and material data

The extension applies only to a registered four-layer terrain shader profile.
Version 1.0.0 supports `adm.terrain.four_layer` versions `1.0.0`, `2.0.0`,
`1.1.0`, and `2.1.0`, plus the four-layer `adm.pbr.layered@2.1.0` profile.
Custom profiles and profiles with fewer or more layers are not valid for this
extension version. The material maps exactly four local layers to stable IDs
through `ADM_terrain_surface_v1`. Add this object to the material:

```json
{
  "extensions": {
    "ADM_terrain_control_map_v1": {
      "version": "1.0.0",
      "mode": "VERTEX_MULTIPLY",
      "texture": {"index": 2, "texCoord": 0},
      "mapping": "UV",
      "scale": [1.0, 1.0],
      "offset": [0.0, 0.0],
      "strength": 1.0,
      "channelOrder": [0, 1, 2, 3]
    }
  }
}
```

The extension MUST be listed in both `extensionsUsed` and
``extensionsRequired`. The object MUST contain `version` and `mode`; it MAY
contain `texture`, `mapping`, `origin`, `scale`, `offset`, `strength`,
`channelOrder`, and `overrideMask`. No other keys are defined in version
1.0.0. `version` MUST be `"1.0.0"`. `mode` MUST be one of the modes below. A
reader that does not support this extension MUST reject an asset that requires
it.

`ADM_terrain_surface_v1.surfaceIds` MUST contain exactly four IDs on the same
material. Local surface order is the order of those IDs and the order of the
shader's four layer slots. `channelOrder` maps each local layer slot to one
canonical sampled weight. Its default is `[0, 1, 2, 3]`; an explicit value
MUST be a permutation of those four integers.

## Modes and weight evaluation

The source vertex weights are the material profile's four `COLOR_1` channels,
or that profile's documented missing-attribute default. The `texture` field is
required except for `VERTEX_ONLY`. `TEXTURE_RGB_IMPLICIT` requires a texture
that decodes to at least three channels. Every other texture-driven mode
requires at least four channels. GPU texture sources and their portable
fallbacks MUST both meet the channel requirement. Texture samples are linear,
clamped to `[0,1]`, and reordered by `channelOrder` before combination.
Normalize a weight vector `x` as follows:

```text
normalize(x):
    x[i] = max(0, x[i])
    total = sum(x)
    if total > 0: return x / total
    return [1, 0, 0, 0]
```

The zero-total fallback selects local layer zero. It applies independently to
a zero-total vertex vector, a zero-total sampled vector, and a zero-total final
result. If the texture is missing or undecodable, the reader MUST report that
the Control Map is unavailable and use the normalized vertex weights without
sampling or combining a Control Map value.

`strength` defaults to `1` and MUST be in `[0,1]`. Let `v` be normalized
vertex weights and `c` be normalized, reordered Control Map weights. The
following equations define the modes:

| Mode | Result before final normalization |
|---|---|
| `VERTEX_ONLY` | `v`; no texture is sampled |
| `TEXTURE_RGBA` | `(1-strength) * v + strength * c`, where `c` comes from RGBA |
| `TEXTURE_RGB_IMPLICIT` | `(1-strength) * v + strength * c`, where `c` is formed from RGB as defined below |
| `VERTEX_MULTIPLY` | `(1-strength) * v + strength * normalize(v * c)` |
| `VERTEX_OVERRIDE` | `v[i] * (1-strength*mask[i]) + c[i] * strength*mask[i]` |
| `VERTEX_MODULATE` | `v[i] * (1-strength + strength * 4 * c[i])` for each layer |

Normalize each result. A `TEXTURE_RGB_IMPLICIT` sample forms its canonical
four weights before `channelOrder` is applied:

```text
w0 = max(0, 1 - R - G - B)
w1 = R
w2 = G
w3 = B
c = normalize([w0, w1, w2, w3])
```

Alpha is ignored in `TEXTURE_RGB_IMPLICIT`. For `TEXTURE_RGBA`, all four
sampled channels are explicit. `VERTEX_MODULATE` has a neutral control value
of `0.25` per channel: at any strength, a uniform neutral map preserves the
normalized vertex weights. `overrideMask` is valid only for
`VERTEX_OVERRIDE`; it is a four-component vector in `[0,1]`, defaults to
`[1,1,1,1]`, and independently gates replacement for each local layer.
Readers MUST reject it when another mode is selected.

## Coordinates and filtering

`mapping` defaults to `UV` and MUST be `UV` or `WORLD_PLANAR_XZ`.
`scale` defaults to `[1,1]`; `offset` defaults to `[0,0]`. Both are finite
two-component vectors with absolute components at most `1e6` and `1e9`,
respectively. `scale` MUST NOT be `[0,0]`.

For `UV`, `texture` MAY include `texCoord` 0 or 1, defaulting to 0. Sample at:

```text
uv = selectedTexCoord * scale + offset
```

For `WORLD_PLANAR_XZ`, `texture.texCoord` MUST be absent. `origin` is an
optional finite two-component vector in meters, defaulting to `[0,0]`; each
component MUST have an absolute value at most `1e9`. Use asset-space positions
after node transforms, before any renderer floating-origin subtraction:

```text
uv = ([position.x, position.z] - origin) * scale + offset
```

Implementations that use a floating origin MUST compensate for that origin so
the sampled coordinates do not change when the render origin moves. Tiles that
share a Control Map MUST use the same coordinate phase and sample values at
shared borders.

Control Map images MUST be treated as linear data, never sRGB. Their sampler
MUST use `LINEAR` minification and magnification filters. Addressing follows
the referenced texture's existing wrap modes. Implementations MUST select
mip levels from texture-coordinate derivatives and linearly interpolate
between available mip levels. When separately tiled images are used, their
border texels and mip gutters MUST agree across shared edges for the full
filter footprint. Normalize the filtered weights after sampling; do not
normalize each texel before filtering.

## Evaluation order and physical surfaces

Apply the extension in this order:

1. Read base vertex weights.
2. Sample Control Map data in the selected coordinate system.
3. Reorder channels and combine according to `mode`.
4. Normalize, using the local-layer-zero fallback.
5. Apply per-layer texture projection and parallax.
6. Sample layer heights and apply the selected shader profile's height blend.
7. Evaluate the final material.

Control Map UVs MUST NOT be offset by per-layer, view-dependent parallax.
This extension does not assign physical materials or change colliders. Any
authoring-time physical classification that consumes Control Map data MUST use
the unshifted, camera-independent weights and MUST store the result as stable
collision assignments; it MUST NOT depend on lighting, final color, or
view-dependent shader output.

## Conformance

- `TCM-001`: validate declaration, version, mode, layer identity, texture
  reference, decoded channel count, coordinates, ranges, and sampler filtering.
- `TCM-002`: verify RGBA and implicit-RGB decoding, channel reordering, and
  normalization.
- `TCM-003`: verify all six modes, strength endpoints, zero totals, and the
  layer-zero fallback.
- `TCM-004`: verify UV and world-planar coordinates remain stable across a
  floating-origin shift.
- `TCM-005`: verify filtered weights are normalized after sampling and that
  separately tiled border/mip samples agree.
- `TCM-006`: verify Control Map coordinates are evaluated before and are not
  shifted by per-layer parallax; physical assignments remain camera-independent.
