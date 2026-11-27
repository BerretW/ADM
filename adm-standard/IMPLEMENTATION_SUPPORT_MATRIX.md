# Implementation support matrix

This matrix distinguishes reference implementation support from independent certification.
`Partial` and `Fallback` entries retain the exact ADM data when possible and must not be
represented as complete renderer conformance.
For extension-by-extension status across the advanced terrain material mission, see the
[material feature compatibility matrix](MATERIAL_FEATURE_COMPATIBILITY.md).

| Consumer | AO | Height | Height Blend | Parallax | POM | GPU Formats | Round-trip |
|---|---|---|---|---|---|---|---|
| ADM Blender material preview | Fallback | Partial | Partial | Unsupported | Unsupported | Partial | Not applicable |
| ADM Blender import/export | Partial | Partial | Partial | Partial | Partial | Partial | Partial |
| World Tile single-surface preview | Partial | Partial | Not applicable | Partial | Partial | Partial | Not applicable |
| World Tile multi-surface preview | Partial | Partial | Partial | Partial | Partial | Partial | Not applicable |
| World Tile 3D detailed material mode | Partial | Partial | Partial | Partial | Partial | Partial | Not applicable |
| World Tile 3D fast material mode | Fallback | Unsupported | Unsupported | Unsupported | Unsupported | Partial | Not applicable |
| World Tile ADM export | Partial | Partial | Partial | Partial | Partial | Partial | Partial |
| ADM validators | Partial | Partial | Partial | Partial | Partial | Partial | Not applicable |
| Shared ADM GPU codec | Not applicable | Partial | Not applicable | Not applicable | Not applicable | Partial | Partial |
| World Tile CLI | Partial | Partial | Partial | Partial | Partial | Partial | Partial |
| Independent container CLI | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable |
| Reference math | Partial | Partial | Partial | Partial | Partial | Not applicable | Not applicable |
| Registry and fixture generators | Partial | Partial | Partial | Partial | Partial | Partial | Not applicable |
| Advanced ADM fixture VTK visualization | Partial | Partial | Partial | Partial | Partial | Fallback | Not applicable |

## Explicit limitations

- Blender approximates layer AO by darkening the preview color. It retains parallax
  and POM parameters, but does not preview their UV offsets.
- Blender preserves optional `ADM_material_height_v1` data, its height texture
  and sampler on import and export, but uses the core material preview and
  warns that the effect is unavailable. It rejects the extension when required.
  When normal and height textures use different UV sets, the exported tangent
  frame follows the normal map; readers must derive a separate height frame.
  Unknown optional height fields and nested extension data are retained, but
  their internal references are not remapped.
- Blender warns on import and export when optional extensions are not
  recognized, including after saving and reopening a project. It retains
  unknown root-, scene-, imported node-, mesh-, material-, and primitive-level extension JSON
  without remapping internal references. Primitive data follows imported faces;
  export rejects missing face tracking, lost primitives, and splits across output
  primitives. It rejects ambiguous scene merges and conflicting root-extension values when exporting
  multiple models. It does not generally preserve unknown
  extensions elsewhere or on nodes that were not imported.
- Blender retains inactive profile parameters in the project when you switch
  profiles, restoring values whose shader and type match. An ADM export includes
  only parameters supported by the selected profile and warns about inactive
  overrides. Loading older projects initializes cache metadata for registered
  profiles; unknown schemas cannot be validated.
- Blender retains parameters of unknown `adm.*` shader versions through project
  save and ADM export. It remaps recognized texture references and preserves
  their samplers and compatible GPU sources, but cannot validate the unknown
  schema or remap references inside opaque parameter objects.
- Blender's ADM importer uses the PNG fallback for editable GPU images and
  retains a compatible primary for unchanged-image export. For BC5 normal
  maps, it reconstructs Z using the format and the fallback X and Y channels.
  If the external primary is missing or fails integrity checks, Blender reports
  that the normal fallback might not render correctly.
- World Tile's CPU multi-surface composition approximates AO by darkening the
  final color and supplies blended normal, metallic, roughness, and emission
  maps to its preview renderer. The multi-surface final-material view uses this
  CPU composition when parallax mode is `NONE`. Its parallax and POM material
  previews sample each layer separately in the VTK fragment shader. Shader
  weight diagnostics use shifted coordinates; CPU weight views and reported mean weights use
  unshifted coordinates. These previews have been tested with
  VTK 9.7.2; other versions remain unverified. Separate offscreen tests render
  selected exported-terrain seams. The opt-in detailed terrain mode uses the
  same per-layer shader and exported four-layer palette policy; its fast
  material mode remains an albedo bake. The detailed mode has a separate
  triangle budget and warns when a palette exceeds four surfaces.
  The renderer reports insufficient texture units instead of dropping maps.
  Equal-size scalar maps share a float texture without resampling. The 3D view
  also exposes each exported `COLOR_1` palette channel.
- World Tile retains unknown terrain shader settings in its project and rejects
  validation, build, and export. It does not interpret or remap references
  inside those settings. Unsupported profile versions and parallax modes
  remain visible in the material editor.
- Portable PBR fallback textures preserve only data representable in portable PBR and must
  be labeled as a fallback, never as layered shader conformance.
- DDS/KTX2 primary bytes are preserved only when the source role and color space match.
- Blender's automatic GPU conversion uses R16 for eligible scalar data and retains a
  16-bit PNG for other 16-bit images. Explicit 8-bit GPU compression is lossy and warns.
- World Tile preserves multichannel 16-bit data PNG bytes as the primary, and converts
  supported 16-bit RGB/RGBA TIFF data to 16-bit PNG without quantization. It rejects
  other multichannel 16-bit TIFF layouts. The TIFF height preview retains 16-bit samples.
- World Tile's export settings select DDS or KTX2 and automatic, BC7, or RGBA8 encoding
  for converted 8-bit images. Compatible GPU inputs remain unchanged unless re-encoding
  is explicitly enabled. 16-bit data retains its precision, and the export report
  identifies retained formats and re-encoded sources.
- Individual World Tile maps can override their encoding. Data maps support R8, R16,
  and BC4 by exporting the selected channel as red; normal maps support BC5 with a
  separate reconstructed RGB PBR normal. Unconverted GPU inputs and 16-bit data can
  retain a different format to preserve their bytes or precision.
- For a BC5 terrain normal, World Tile retains the BC5 source and its
  two-channel fallback for the shader, and emits a separate reconstructed RGB
  PNG for the top-level PBR normal. Blender also emits a separate RGB PNG
  when an exported shader parameter retains the same BC5 bytes. Blender's
  standalone core-PBR BC5 export
  does not yet provide both a preserved BC5 primary and an RGB fallback under
  the current two-channel fallback rule. Blender warns when exporting a BC5
  core normal because portable readers might display that fallback incorrectly.
- The standalone shared BC7 decoder requires `texture2ddecoder`. Blender's texture
  loader repackages BC7 KTX2 blocks as DDS and uses Blender's native DDS reader;
  this path has been verified in a built extension on Windows with Blender 5.2.3.
  Other platforms have not been verified.
- Validators check contracts and references; they do not render or prove visual
  conformance. The reference math is not a renderer.
- The World Tile CLI uses the same project and export implementation as the
  GUI and reports triangles exceeding four surfaces. The independent container
  CLI checks container structure and selected contracts, not full shader
  semantics or rendering. It rejects required extensions outside its explicit
  allowlist. Fixture and registry generators are not general ADM editors.
- The fixture-specific VTK visualization reads the generated advanced ADM and
  renders parallax and POM with embedded PNG fallbacks. It rejects layouts
  outside its limited assumptions and is not an independent renderer or a
  general ADM viewer.
- No separate web editor, standalone ADM editor, general-purpose viewer, or
  independent runtime renderer was found in the repository. Blender's custom
  shader editor uses the PBR fallback; its custom ENUM definitions and values
  are preserved. Imports reject incompatible parameter names, types, ENUM
  values, numeric, boolean or texture defaults, and metadata for an existing
  definition.
- Independent implementation certification requires separate render/reference comparisons.
