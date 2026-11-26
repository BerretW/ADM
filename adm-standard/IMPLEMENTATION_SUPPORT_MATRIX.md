# Implementation support matrix

This matrix distinguishes reference implementation support from independent certification.
`Partial` and `Fallback` entries retain the exact ADM data when possible and must not be
represented as complete renderer conformance.

| Consumer | AO | Height | Height Blend | Parallax | POM | GPU Formats | Round-trip |
|---|---|---|---|---|---|---|---|
| ADM Blender material preview | Fallback | Partial | Partial | Unsupported | Unsupported | Partial | Not applicable |
| ADM Blender import/export | Partial | Partial | Partial | Partial | Partial | Partial | Partial |
| World Tile single-surface preview | Partial | Partial | Not applicable | Unsupported | Unsupported | Partial | Not applicable |
| World Tile multi-surface preview | Partial | Partial | Partial | Unsupported | Unsupported | Partial | Not applicable |
| World Tile 3D terrain material mode | Unsupported | Unsupported | Unsupported | Unsupported | Unsupported | Partial | Not applicable |
| World Tile ADM export | Partial | Partial | Partial | Partial | Partial | Partial | Partial |
| ADM validators | Partial | Partial | Partial | Partial | Partial | Partial | Not applicable |
| Shared ADM GPU codec | Not applicable | Partial | Not applicable | Not applicable | Not applicable | Partial | Partial |
| ADM CLI/reference tools | Partial | Partial | Partial | Partial | Partial | Partial | Partial |

## Explicit limitations

- Blender approximates layer AO by darkening the preview color. It retains parallax
  and POM parameters, but does not preview their UV offsets.
- Blender's ADM importer uses the PNG fallback for GPU images. For BC5 normal
  maps, it reconstructs Z from the primary format and the fallback X and Y
  channels. If the external primary is missing or fails integrity checks,
  Blender reports that the normal fallback might not render correctly.
- World Tile's CPU multi-surface composition approximates AO by darkening the
  final color and supplies blended normal, metallic, roughness, and emission
  maps to its preview renderer. It does not render parallax or POM effects.
- Portable PBR fallback textures preserve only data representable in portable PBR and must
  be labeled as a fallback, never as layered shader conformance.
- DDS/KTX2 primary bytes are preserved only when the source role and color space match.
- The standalone shared BC7 decoder requires `texture2ddecoder`. Blender's texture
  loader repackages BC7 KTX2 blocks as DDS and uses Blender's native DDS reader;
  this path has been verified in a built extension on Windows with Blender 5.2.3.
  Other platforms have not been verified.
- Validators check contracts and references; they do not render or prove visual
  conformance. The reference math is not a renderer.
- Independent implementation certification requires separate render/reference comparisons.
