# `ADM_terrain_macro_normal_v1`

Version 1.0.0 defines a tangent-space normal overlay for four-layer terrain.
It changes the rendered surface normal only; it does not change terrain
weights, surface identity, geometry, or physical collision assignments.

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
    "ADM_terrain_macro_normal_v1": {
      "version": "1.0.0",
      "texture": {"index": 4, "texCoord": 0},
      "projection": "LOCAL_UV",
      "strength": 1.0,
      "layerInfluence": [1.0, 1.0, 1.0, 1.0],
      "scale": [1.0, 1.0],
      "offset": [0.0, 0.0]
    }
  }
}
```

The object MUST contain `version`, `texture`, and `projection`. It MAY contain
`origin`, `scale`, `offset`, `strength`, and `layerInfluence`. No other fields
are defined in version 1.0.0. `version` MUST be `"1.0.0"`. Readers that do not
support this extension MUST reject assets that require it.

## Projection and tangent frame

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

The macro tangent frame uses the geometric surface normal `N` and the
asset-space derivatives `dPdu` and `dPdv` of the transformed map coordinates,
including `scale`:

```text
T = normalize(dPdu - N * dot(dPdu, N))
V = dPdv - N * dot(dPdv, N)
h = -1 if dot(cross(T, V), N) < 0, otherwise +1
B = h * normalize(cross(N, T))
frame = (T, B, N)
```

If the projected `dPdu` length is `<= 1e-12`, choose world `+X` unless it is
within 0.1 of parallel to `N`, then choose world `+Z`; project that axis onto
the surface and set `h = +1`. If the projected `V` length is `<= 1e-12`, also
set `h = +1`. A zero handedness dot product selects `h = +1`. Readers MUST
use these fallbacks rather than producing a non-finite frame.

For a layer tangent normal `n_i=(x,y,z)` and layer frame
`(T_i,B_i,N_i)`, its world normal is
`normalize(x*T_i + y*B_i + z*N_i)`. Transform that world normal into `frame`
using dot products with `T`, `B`, and `N`. Apply the Macro Normal overlay in
this common frame. Transform the final result back to world space using
`frame`. This makes the overlay composable with layers that use different UV
sets or texture projections.

## Texture data and strength

The image MUST provide at least two decoded channels. R and G store tangent
normal X and Y in `[0,1]`, decoded as:

```text
x = 2*R - 1
y = 2*G - 1
if x*x + y*y > 1:
    (x, y) = normalize((x, y))
z = sqrt(max(0, 1 - x*x - y*y))
```

Readers MUST treat all channels as linear data regardless of embedded image
color metadata; alpha is ignored. A portable normal image MUST be PNG. For a
portable RGB fallback, B MUST contain the reconstructed Z in `[0,1]`. A GPU
source MUST be BC5 UNORM and its PNG fallback MUST provide at least three
channels and preserve the reconstructed normal. Other GPU formats, JPEG normal
images, and sRGB variants are invalid.

`strength` defaults to `1` and MUST be in `[0,1]`. `layerInfluence` defaults
to `[1,1,1,1]` and MUST be a four-component vector in `[0,1]`. Its order
matches the four local layers and stable IDs. For layer `i`, let:

```text
f_i = clamp(strength * layerInfluence[i], 0, 1)
x_i = f_i * x
y_i = f_i * y
D_i = normalize((x_i, y_i, sqrt(max(0, 1 - x_i*x_i - y_i*y_i))))
```

Zero strength or zero layer influence yields the flat tangent normal
`(0,0,1)`.

The texture sampler MUST use `LINEAR` minification and magnification filters.
Readers MUST select mip levels from coordinate derivatives and linearly
interpolate between available levels. Separately tiled images MUST have
matching border texels and mip gutters over the full filter footprint.

## Reoriented normal mapping

Let `B_i` be the normalized base layer normal transformed into the macro
tangent frame. Combine it with `D_i` using reoriented normal mapping:

```text
t = B_i + (0,0,1)
u = D_i * (-1,-1,1)
R_i = normalize(t * dot(t,u) - u * t.z)
```

If `length(t) <= 1e-8`, or the candidate result has length `<= 1e-8`, use
`B_i` unchanged. A missing layer normal map contributes the geometric surface
normal; in the macro tangent frame this is `(0,0,1)`. Blend per-layer results
with the final normalized terrain
weights `w_i` after Control Map evaluation and height blending:

```text
R = normalize(sum(w_i * R_i))
```

If the weighted sum has length `<= 1e-8`, use `(0,0,1)` in the macro tangent
frame. If the Macro Normal image is missing or undecodable, the reader MUST
report that it is unavailable and use the weighted base layer normals without
the overlay.

Sample Macro Normal coordinates independently of per-layer parallax. Do not
shift the projection by a view-dependent offset.

## Physical-surface independence

Macro Normal MUST NOT affect collision generation or physical-material
classification. Physical classification MUST use stable authored,
camera-independent weights and physical-material references; it MUST NOT use
normal samples, final color, lighting, or view-dependent shader output.

## Conformance

- `TMN-001`: validate declaration, version, four-layer profile, stable IDs,
  texture reference, BC5 format, fallback channels, color space, sampler,
  projection, and numeric bounds.
- `TMN-002`: verify BC5 reconstruction, over-disk clamping, strength endpoints,
  and portable-fallback equivalence.
- `TMN-003`: verify RNM composition, flat/missing normals, degenerate base and
  output vectors, layer influence, and weighted combination.
- `TMN-004`: verify local UV and shared-world tangent frames, including
  degenerate derivative fallback and floating-origin invariance.
- `TMN-005`: verify filtered mip/border continuity and independence from
  per-layer parallax in rendered output.
- `TMN-006`: verify physical assignments remain unchanged when Macro Normal,
  camera, lighting, or parallax changes.
