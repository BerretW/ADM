# `ADM_material_height_v1`

This optional ADM 1.0 extension defines material-space height and parallax data.
Its schema version is `1.0.0`. It does not change vertex positions, collisions,
bounding boxes, terrain heightmaps, or level-of-detail geometry.

## Material data

Attach the extension to a material and declare it in `extensionsUsed`:

```json
{
  "extensionsUsed": ["ADM_material_height_v1"],
  "materials": [{
    "baseColorTexture": {"index": 0},
    "extensions": {
      "ADM_material_height_v1": {
        "version": "1.0.0",
        "heightTexture": {"index": 1, "texCoord": 0},
        "channel": "R",
        "invert": false,
        "scale": 1.0,
        "bias": 0.0,
        "referenceHeight": 0.5,
        "parallaxMode": "NONE",
        "parallaxScale": 0.0,
        "pomMinSteps": 8,
        "pomMaxSteps": 32
      }
    }
  }]
}
```

The extension object requires `version` and `heightTexture`. `version` MUST be
`"1.0.0"`. `heightTexture` uses the ordinary ADM texture index and an optional
`texCoord` of 0 or 1; its default is 0. The optional `channel` is `R`, `G`, `B`,
or `A` and defaults to `R`. `invert` defaults to `false`. `scale` defaults to
1 and MUST be in [0,1000]. `bias` defaults to 0 and MUST be in [-1,1].
`referenceHeight` defaults to 0.5 and MUST be in [0,1].

The optional `parallaxMode` is `NONE`, `PARALLAX`, or `PARALLAX_OCCLUSION` and
defaults to `NONE`. `parallaxScale` defaults to 0 and MUST be in [0,1] model
units. `pomMinSteps` and `pomMaxSteps` default to 8 and 32; when present they
MUST satisfy `1 <= pomMinSteps <= pomMaxSteps <= 256`.

## Height and parallax semantics

Height samples are linear data. A reader selects the named channel, applies
inversion when requested, then computes:

```text
sample = selected_channel(texture, uv)
if invert:
    sample = 1 - sample
effectiveHeight = clamp(sample * scale + bias, 0, 1)
```

The texture's UV set is selected by `heightTexture.texCoord`. No assumption is
made that the height texture has the same dimensions as any other material
texture. If the texture cannot be decoded, the extension's material effect is
unavailable; the reader uses the core PBR material and reports the limitation.

`referenceHeight` is the height at which parallax produces no UV offset.
`parallaxScale` bounds the apparent depth in model units. `NONE` does not offset
UV coordinates. `PARALLAX` applies a single bounded height-based offset.
`PARALLAX_OCCLUSION` traces through the height field between the view ray and
surface and refines the first crossing; its step count is bounded by the two
POM settings. The offset MUST remain finite and MUST NOT sample outside the
height texture's ordinary sampler addressing behavior.

Height and parallax are material-space effects only. A reader MUST NOT use them
to displace geometry or change collision, bounds, terrain height, or LOD data.
This extension does not redefine the core `occlusionTexture`.

## Fallback and conformance

The core material fields remain the portable PBR fallback. A reader that does
not implement this optional extension may ignore it and render the core
material. A producer MUST preserve the extension object through import/export,
including fields the tool does not edit. A producer that requires a reader to
apply parallax MUST list the extension in `extensionsRequired`; readers that do
not support a required extension MUST reject the asset.

- `HEIGHT-001`: validate the extension version, texture reference, channel,
  UV set, numeric bounds, mode, and POM step ordering.
- `HEIGHT-002`: verify height sampling, inversion, scale, bias, and reference
  height use linear channel values.
- `HEIGHT-003`: verify parallax offsets remain finite and respect the selected
  texture's UV set and sampler behavior.
- `HEIGHT-004`: verify the effect does not alter mesh data, collisions, bounds,
  terrain geometry, or LOD data.
- `HEIGHT-005`: preserve unknown optional parameters and use the core PBR
  fallback when the effect is unsupported.
