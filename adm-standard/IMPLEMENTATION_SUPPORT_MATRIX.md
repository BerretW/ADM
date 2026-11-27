# Implementation support matrix

This matrix distinguishes reference implementation support from independent certification.
`Partial` and `Fallback` entries retain the exact ADM data when possible and must not be
represented as complete renderer conformance.

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
  unknown material-level extension JSON without remapping its internal
  references. It does not generally preserve unknown extensions elsewhere.
- Blender retains inactive profile parameters in the project when you switch
  profiles, restoring values whose shader and type match. An ADM export includes
  only parameters supported by the selected profile and warns about inactive
  overrides. Loading older projects initializes cache metadata for registered
  profiles; unknown or conflicting custom definitions remain unverified.
- Blender's ADM importer uses the PNG fallback for editable GPU images and
  retains a compatible primary for unchanged-image export. For BC5 normal
  maps, it reconstructs Z using the format and the fallback X and Y channels.
  If the external primary is missing or fails integrity checks, Blender reports
  that the normal fallback might not render correctly.
- World Tile's CPU multi-surface composition approximates AO by darkening the
  final color and supplies blended normal, metallic, roughness, and emission
  maps to its preview renderer. Its parallax and POM material previews sample
  each layer separately in the VTK fragment shader. Shader weight diagnostics
  use shifted coordinates; CPU weight views and reported mean weights use
  unshifted coordinates. These previews have been tested with
  VTK 9.7.2; other versions remain unverified. Separate offscreen tests render
  selected exported-terrain seams. The opt-in detailed terrain mode uses the
  same per-layer shader and exported four-layer palette policy; its fast
  material mode remains an albedo bake. The detailed mode has a separate
  triangle budget and warns when a palette exceeds four surfaces.
  The renderer reports insufficient texture units instead of dropping maps.
- World Tile retains unknown terrain shader settings in its project and rejects
  validation, build, and export. It does not interpret or remap references
  inside those settings. Unsupported profile versions and parallax modes
  remain visible in the material editor.
- Portable PBR fallback textures preserve only data representable in portable PBR and must
  be labeled as a fallback, never as layered shader conformance.
- DDS/KTX2 primary bytes are preserved only when the source role and color space match.
- Blender's automatic GPU conversion uses R16 for eligible scalar data and retains a
  16-bit PNG for other 16-bit images. Explicit 8-bit GPU compression is lossy and warns.
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
