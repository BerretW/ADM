# Material feature compatibility matrix

Use this matrix to check whether a material feature has a normative contract,
reference implementation, authoring path, and renderer support in this
repository. It covers the advanced terrain material mission; it does not certify
independent interoperability. Reference math and validation do not prove that a
renderer samples or displays an effect correctly.

The status labels describe repository evidence:

- **Specified** means a versioned contract defines the feature.
- **Reference only** means reference math or validation exists, but the
  consumer does not render the effect.
- **Partial** means the consumer preserves or implements some behavior but
  lacks required conformance evidence or complete support.
- **Unsupported** means the consumer explicitly rejects required data or does
  not implement the effect.
- **Implemented (M3)** means the physical-surface workflow has mission test
  coverage; it does not imply third-party certification.

| Feature | ADM contract | Reference math and validation | World Tile | Blender | Collision classification |
|---|---|---|---|---|---|
| Terrain Control Maps | `ADM_terrain_control_map_v1@1.0.0` specified for registered four-layer profiles | Six weight modes, coordinate transforms, profile/channel/reference validation, and golden vectors; no filtered-sampling conformance renderer | Partial: bounded source-rule export and external RGBA mask import, stable-ID channel assignment, AWTP v14 persistence, export, and Detailed preview; external-mask and source-rule seam pixels are tested in VTK at magnified/minified scales, while shader-composed weights remain open | Partial: import/export and save/reload, authoring controls, Cycles tests for all six modes, UV0/UV1, offsets, translated world positions, minified filtered weights, and an adjacent-mesh world-XZ seam; explicit mip selection, cross-reader parity, and per-layer POM ordering remain open | External masks affect visual weights only; export continues to assign collision materials from authored physical data and manual paint |
| Terrain Macro Color | `ADM_terrain_macro_color_v1@1.0.0` specified for registered four-layer profiles | sRGB color/coordinate reference math, profile/image/color-space/sampler validation, and independent vectors; renderer conformance remains incomplete | Partial: AWTP v15 path/settings, image authoring, sRGB validation, required export with four stable local IDs and portable fallback, and local/shared VTK preview for all blend modes; a shared-world map renders across adjacent tile actors at magnified/minified views with measured edge thresholds, and Macro Color stays fixed when per-layer Parallax/POM visibly changes the base albedo; exact mip selection, separate-image gutters, and cross-reader parity remain open | Partial: required import/export, authoring controls, sRGB channel-packed preview image, Cycles tests for all blend modes and local/shared projections, plus save/reload; sampler, tile-edge mip/gutter and cross-reader conformance remain open | Changes rendered albedo only; stable authored weights and physical collider assignments remain independent |
| Terrain Macro Normal | `ADM_terrain_macro_normal_v1@1.0.0` specified for registered four-layer profiles | BC5 reconstruction, RNM, tangent-frame and coordinate reference math; profile/image/format/sampler validation and independent vectors | Partial: AWTP v16 authoring, BC5 UNORM export plus reconstructed RGB fallback, compatible source-byte preservation, preset v7 packaging, and local/shared RNM preview; parallax independence and unchanged collider assignments are tested, while filtered mip/gutter, adjacent-tile continuity, and fallback equivalence remain open | Partial: authoring/export and `.blend` save/reload; Cycles verifies local/shared sampling, rotated-surface RNM, a layer normal on a different UV set, neutral strength, and unchanged weights. Mirrored/degenerate tangent-frame handling, BC5/fallback round trips, mip/filter parity, and required-extension import remain open | Independent of physical classification |
| Anti-tiling and stochastic sampling | Not defined | Not implemented | Not implemented | Not implemented | Independent of visual effects |
| General layered-terrain triplanar projection | No terrain-wide contract; `adm.nature.rock.v1` defines profile-specific object-space triplanar mapping | Profile-specific weight math exists; no general terrain evaluator | Not implemented for terrain | Partial: the rock profile has a Blender preview, but layered terrain has no general triplanar authoring path | Independent of visual effects |
| Generic terrain detail maps and per-layer controls | No cross-profile terrain contract; existing shader profiles have separate `detail_*` parameters | No generic layered-terrain evaluator | Not implemented for terrain | Partial: profile-specific detail controls exist; no general layered-terrain authoring path | Independent of visual effects |
| Parallax self-shadowing | Not defined | Not implemented | Not implemented | Not implemented | Must not affect physical assignments |
| True displacement | Not defined | Not implemented | Not implemented | Not implemented | Separate from collider generation |
| Material distance LOD | Not defined | Not implemented | Not implemented | Not implemented | Must not affect physical assignments |
| Core-PBR BC5 fallback | Existing texture contract; standalone fallback remains unresolved | Partial validation and byte-preservation paths | Layered terrain exports preserve BC5 plus reconstructed PBR normal | Standalone core-PBR export cannot provide both the BC5 primary and reconstructed RGB fallback | Not applicable |
| GPU texture resource architecture | Existing GPU formats; arrays and mission-wide budgets are not defined | Partial codec and texture validation | Supports selected R8/R16/BC formats and source preservation | Supports selected GPU formats; platform coverage is incomplete | Not applicable |
| Physical surfaces and independent terrain colliders | Versioned physical surface and type extensions | Reference query, validation, and assignment tests | Implemented (M3), including automatic/manual assignments and independent collision geometry | Implemented (M3) import/export and save/reload coverage | Based on stable authored weights and explicit overrides, never final color, lighting, camera, parallax, or POM |
| Existing layered height and parallax effects | Versioned shader and height contracts | Partial reference math and validation | Partial; renderer paths differ | Height metadata is preserved; POM is unsupported in preview | Independent of physical assignments |

## Control Map limitations

The Control Map extension removes dependence on vertex density for material
weights, but it does not increase the four-layer primitive limit. It does not
make five or more simultaneous surfaces exactly representable. Stable global
surface IDs still map to exactly four local layer slots for texture-driven
modes.

The Control Map contract specifies derivative-based mip selection and shared
border behavior. The reference math evaluates weights and coordinates at a
sample; it does not establish texture-filtering, mip-selection, border, or
rendered-seam conformance. World Tile's opt-in exporter samples the original
heightmap and current surface rules into bounded per-palette RGBA maps. Its
detailed preview samples those maps before per-layer parallax and height
blending. World Tile also imports bounded external RGBA masks, stores their
path and four stable channel IDs in AWTP v14, and uses the resampled weights in
export and its Detailed preview. The image covers the heightmap grid; R, G, B,
and A map to distinct stable surface IDs. VTK render tests measure external-
mask and source-rule seam pixels at magnified and minified scales. Shader-
composed final weights, seam behavior with per-layer parallax/mip selection,
and cross-reader seam/mip parity remain open.
Blender imports and preserves required Control Maps,
exposes authoring properties, and previews supported modes. Its render and
sampler conformance remains incomplete; unsupported axis-specific wrap settings
fall back to vertex weights with an import warning.

The matrix distinguishes terrain-wide contracts from profile-specific
features. For example, `adm.nature.rock.v1` already defines object-space
triplanar mapping and Blender previews that profile. That support does not
provide a general triplanar contract or World Tile integration for layered
terrain.

Physical collider assignments remain independent of view-dependent shader
output. Any future Control Map-based authoring classification must consume raw,
camera-independent weights and bake stable collision assignments.

For the broader consumer and GPU texture limits, see the
[implementation support matrix](IMPLEMENTATION_SUPPORT_MATRIX.md). For
measured mission test results and open work, see the repository's `.ai`
mission records.
