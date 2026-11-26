# Implementation support matrix

This matrix distinguishes reference implementation support from independent certification.
`Partial` and `Fallback` entries retain the exact ADM data when possible and must not be
represented as complete renderer conformance.

| Consumer | AO | Height | Height Blend | Parallax | POM | GPU Formats | Round-trip |
|---|---|---|---|---|---|---|---|
| ADM Blender material preview | Full | Partial | Full | Fallback | Fallback | Partial | Full |
| ADM Blender import/export | Full metadata | Full metadata | Full node math | Partial preview | Partial preview | Full codecs | Full typed parameters |
| Apparatus World Tile material preview | Full | Full | Unsupported | Unsupported | Unsupported | Partial | Full |
| Apparatus World Tile multi-surface preview | Fallback | Full | Full weight result | Unsupported | Unsupported | Partial | Full weight controls |
| Apparatus World Tile 3D terrain material mode | Fallback | Fallback | Unsupported | Unsupported | Unsupported | Partial | Full export data |
| Apparatus World Tile ADM export | Full | Full | Full metadata | Full metadata | Full metadata | Full primary/fallback | Full where profile 2.1 accepts data |
| ADM independent validator | Full contract | Full contract | Full invariant math | Full contract | Full contract | Full header/payload validation | Full serialization validation |
| Shared ADM GPU codec | Not applicable | Full R8/R16/BC4 | Not applicable | Not applicable | Not applicable | Full R8/R16/BC4/BC5/BC7 primary | Byte-preserving supported inputs |
| ADM CLI/reference tools | Full data validation | Full data validation | Full reference math tests | Contract validation | Contract validation | Partial independent CLI decoding | Full document validation |

## Explicit limitations

- Blender preview AO is implemented in the preview node graph where supported; POM is
  represented as metadata plus a conservative preview approximation.
- World Tile still cannot claim AO, normal, emission, parallax or POM in its CPU
  multi-surface composition unless the corresponding real renderer path is implemented.
- Portable PBR fallback textures preserve only data representable in portable PBR and must
  be labeled as a fallback, never as layered shader conformance.
- DDS/KTX2 primary bytes are preserved only when the source role and color space match.
- Independent implementation certification requires separate render/reference comparisons.
