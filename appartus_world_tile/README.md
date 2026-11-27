# Apparatus World Tile

Desktop tool that turns a large heightmap (tested at 16 385 × 16 385) into crack-free
terrain tiles with several levels of detail, automatically textured vertex layers and finished
**ADM tiles** that open directly with **File → Import → ADM Model** in Blender. The heavy work
(meshing, simplification, texture weights and export) happens here, in parallel native code. A
project file (`.awtp`) keeps everything, so a world can be reopened, edited and re-exported
later; only tiles that changed are written again.

## Start

```bat
run_gui.bat                    :: first run creates .venv and installs everything
```

or by hand (Python 3.11+):

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[gui]"
.venv\Scripts\python -m awt gui [project.awtp, heightmap or manifest.json]
.venv\Scripts\python -m awt build source\switz3.png -o out --spacing 2 --height-range 0 2500 --max-error 0.25 1 4 --save-project world.awtp
.venv\Scripts\python -m awt build source\switz3.png -o out --collision-error 1.0 --collision-boundary-max-edge 4 --collision-max-triangles 262144
.venv\Scripts\python -m awt export world.awtp                   :: only changed tiles
.venv\Scripts\python -m awt export world.awtp --tiles x003_y001 x004_y001
.venv\Scripts\python -m awt export world.awtp --all --build     :: rebuild, then write everything
.venv\Scripts\python -m awt export world.awtp --control-map-resolution 512
```

Control Maps are opt-in. The GUI's **ADM tiles** tab and
`--control-map-resolution` generate four-channel RGBA weights from the source
heightmap and current surface rules; valid resolutions range from 2 to 4096
pixels per side. The source heightmap must match the build manifest, so rebuild
after changing its samples. Resolution changes do not rebuild terrain geometry.
Control Map exports require a four-layer shader profile and mark the extension
as required. Blender imports and preserves Control Map references, exposes
four-layer authoring settings, and previews supported modes before per-layer
height blending. Its filtering, tiled seams, and full mode conformance remain
unverified. The **Detailed material** preview samples the same source-rule
weights before per-layer parallax and height blending. Collision assignments
continue to use authored physical surface data, not Control Map or shader
output. Select **Control Map channel** in the 3D viewer to inspect a local
palette channel; set a nonzero resolution first.

For an existing `.venv`, rerun `.venv\Scripts\python -m pip install -e ".[gui]"`
to update dependencies. The launcher installs them only when it creates `.venv`.

The first run compiles the Numba kernels (a few seconds); the compiled code is cached.
ADM export uses `adm_blender/core` from this repository (no Blender needed), so keep the tool
inside the ADM checkout.
The standalone World Tile ZIP includes the required ADM core but not the example heightmaps
under `source`; use your own heightmap with the command-line examples.

To build a standalone ZIP from a repository checkout, run this command from the
repository root:

```bat
python tools\build_world_tile.py dist\appartus-world-tile-VERSION.zip
```

Replace `VERSION` with the World Tile version. The destination must not already
exist. The script packages tracked runtime and reference files and the generated
`advanced_material_reference.adm`; add other required files to Git before
building. It does not run tests or change versions.

The repository includes `reference_project/advanced_reference.awtp`, a four-tile project with
three LODs, five surfaces, biome noise, and a road. Its textures are in
`reference_project/textures`; copy the `reference_project` folder to move the project.
The project includes R8, R16, BC4, BC5, and BC7 GPU texture sources and prebuilt tiles.
Open the project to inspect or export those tiles without rebuilding. Rebuild them after
changing the heightmap, biome rules, or paint.

For a BC5 normal, World Tile retains the GPU source and its two-channel fallback
for the terrain shader. It exports a separate reconstructed RGB PNG for the
core PBR normal fallback.

### Render the advanced ADM reference

With the GUI dependencies installed, run these commands from `appartus_world_tile`
to render the bundled ADM scene with and without POM:

```bat
.venv\Scripts\python tools\render_advanced_reference.py reference_project\advanced_material_reference.adm pom.png
.venv\Scripts\python tools\render_advanced_reference.py reference_project\advanced_material_reference.adm no-pom.png --disable-pom
```

To regenerate the scene in an ADM repository checkout, run:

```bat
blender -b --factory-startup --python ..\adm_blender\tests\build_advanced_material_test_scene.py -- reference.blend
```

Compare `pom.png` and `no-pom.png` to see the POM UV offsets. This VTK
visualization reads the ADM's embedded texture fallbacks and is limited to the
generated fixture's constant weights, unit UV scales, opaque layers, and neutral
vertex controls. It approximates the material tint at 8-bit precision; it is
not a general ADM renderer or an independent conformance test. The Blender
material preview itself retains POM settings but does not render their offsets.

## Inputs

| Format | Notes |
|---|---|
| PNG / TIFF 16-bit | black..white = `--height-range MIN MAX` |
| 8-bit PNG | same, 256 steps only (visible terraces) |
| R16 / RAW | little-endian uint16; square size is detected, otherwise `--raw-size W H` |
| NPY, float TIFF | values are metres; `--remap-float` stretches min..max to the range |

`--spacing` is metres between neighbouring samples (or `--size` for the full width).

### Texturing options from the command line

`build` accepts the same height-based biome fitting and texture-refinement settings as the GUI:

```bat
.venv\Scripts\python -m awt build heightmap.png -o out --water-level 10 --shore 4 --snow 900 1100 --texture-error 0.15 --texture-detail 4 --save-project world.awtp
.venv\Scripts\python -m awt build heightmap.png -o out --project world.awtp --fit --save-project world.awtp
```

`--project` reuses its surface/biome setup and paint; `--fit` recalculates the default biome
height ranges for the loaded heightmap. `--water-level`, `--shore` and `--snow START FULL`
override those automatic levels. `--texture-error 0` disables transition refinement;
`--texture-detail` is the minimum new triangle edge length in metres.
`--collision-error` builds a separate collision mesh with the requested maximum
vertical error in metres; `0` disables collision output. The build rejects any tile
that exceeds `--collision-max-triangles` rather than silently relaxing the error
bound. Collision meshes use a separately measured RTIN and share refined tile-edge
vertices, so render LODs do not affect collision geometry. Their stable authored surface
weights support automatic physical classification; view-dependent shader effects do not.
ADM export writes each collision mesh as a `MESH` collider. Physical painting is independent
of visual terrain painting and overrides automatic assignments on collision triangles.
Automatic classification requires a physical-material link on the dominant surface; triangles
without a linked surface remain unassigned. Triangles that cross different physical assignments
are refined until their RTIN split edge is at most `--collision-boundary-max-edge` metres; the
per-tile triangle limit remains a hard cap and causes an explicit build error rather than a
silent reduction in boundary detail.

## GUI

* **File menu:** New / Open / Save / Save as project (`.awtp`), Open heightmap, Open built
  tiles. The title shows `*` while the project has unsaved changes; closing asks to save.
* **Terrain tab:** heightmap, scale, tile size with tile count and memory estimate, LOD
  errors, independent collision error, physical-boundary edge target and per-tile triangle cap, build folder,
  **Build tiles**. A collision error of `0` disables collision generation. Builds
  report the measured maximum error and reject a tile that exceeds its triangle cap.
* **Material tab:** a surface library (albedo, tint, texture repeat in metres, metallic,
  roughness, AO and height maps with channel and invert, plus normal and emission maps) and
  optional height-blend/parallax settings, plus biomes that select and blend those surfaces.
  Profile 2.1.0 is required to export AO, height, emission, height blending, or parallax.
  Select it explicitly or enable **Automatically upgrade the legacy profile for advanced
  settings**. The checkbox applies only to the material open in the editor and resets when
  you load another material. The editor announces an upgrade; choosing the legacy profile
  disables automatic upgrade. The selected profile is saved with the project.
  Unrecognized terrain shader settings are retained
  in the project but cannot be used for validation, build, or ADM export. Their values are
  opaque, so any references inside them aren't collected or remapped. Unsupported profile
  versions and parallax modes remain visible until you explicitly select a supported value.
  The six starter biomes are lowland, forest, shore,
  water, mountains and rocky terrain. Each biome can be placed automatically by height/slope
  bands or painted manually; its surface list can also limit individual surfaces by height and
  slope. Use **Surface noise** on each biome to vary its surfaces spatially.
  **Import sets…** scans a directory tree for split material maps and previews found, missing,
  conflicting, packed, and unknown files before you apply the selected sets.
  **Terrain setup wizard** starts from current rules or a temperate, alpine, coastal/island or
  arid profile, then lets you edit each biome's height/slope limits and choose albedo images
  for its shared surfaces. **Save preset** copies the material setup and its textures into the
  AWT user-data folder; **Load preset** restores it. Presets do not include map-specific paint.
  Texture pickers show source dimensions, format, bit depth, color-space metadata, mip count,
  and whether the file is external. GPU sources show the mip payload size; authoring images
  show an uncompressed RGBA base-level estimate rather than a promised export allocation.
  New presets use version 6 to retain stable surface IDs and physical-material links; the loader
  also accepts preset versions 1–5.
  Neighbouring biomes should share at least one surface so the transition uses a common
  texture rather than changing abruptly. Texture repeat is rounded to a whole number per tile,
  so textures continue across tiles. The **Surface** tab on the right shows the selected
  surface on an interactive **Sphere**, **Plane**, or **Terrain relief**. Drag to rotate,
  middle-drag to pan, and use the mouse wheel to zoom. **Material** mode applies albedo,
  normal, AO, metallic, roughness, and emission maps where VTK supports them. Select a map
  from the preview menu to inspect it directly; **Height** shows the selected channel as
  grayscale. With a height map and a nonzero scale, **Material** mode renders the selected
  parallax or parallax occlusion mode. It does not show multi-surface height blending.
  The sphere is 1 m in diameter; the plane and relief are 15 × 15 m. **Repeat** controls the
  preview texture scale in metres. The spherical mapping uses the equator and a pole-to-pole
  arc for horizontal and vertical scale, so its texture is distorted near the poles. The
  preview uses the exact repeat; built tiles round repeats to align their boundaries.
  **Show blended terrain** opens the detailed 3D material view using built biome weights.
  Rebuild the tiles after changing biome rules or paint.
  **Compare surface blending** opens a separate two-to-four-layer preview. Set base weights,
  toggle height blending, adjust transition and strength, and select a layer to inspect its
  final weight. Drag to rotate, pan, or zoom; choose a studio, grazing, or soft light.
  When parallax is enabled, the final-material view samples each layer's maps independently
  using its own offset, then applies height blending. Shader diagnostic views show base or
  final per-fragment weight, or encode signed U/V parallax offsets in red and green relative
  to the layer's parallax scale. Neutral offset is 0.5 in linear color. CPU weight views and
  displayed mean weights use unshifted coordinates. When parallax is disabled, the CPU-composited preview
  approximates AO by darkening the final color. The renderer reports when the available
  texture units cannot accommodate the selected maps. Scalar maps with matching dimensions
  share a floating-point texture without resampling; maps with different dimensions retain
  separate textures. The preview does not modify the source files.
* **Export tab:** ADM folder, LOD switch distance, embed or share textures, validation,
  **Export changed / Export selected / Export all**. Tiles that are new or changed since the
  last export get a red corner on the map.
* **Map tab:** relief, biome weights, surface weights, physical assignments or mesh density per tile. Click or drag
  to select tiles, Shift adds, double-click opens one tile in 3D. Zoom with the mouse wheel and
  pan with the middle mouse button. Choose **Biome** or
  **Surface**, or **Physical**, enable **Paint**, and drag to paint; right-drag removes that
  type of paint. On the **Material** tab, link each visual surface to an optional physical
  material for automatic classification by stable dominant surface weights. Manual physical paint
  takes precedence. **Physical library…** creates records with explicit friction, restitution
  and optional ADM profile. Manual paint is sampled at collision-triangle centroids; the export
  report counts assigned triangles and warns when a painted tile receives none.
  **Paint softness** affects visual biome/surface borders, not physical assignments.
* **3D tab:** the built tiles, coloured by height, surface weights, tile, or **Material**
  (a fast albedo bake without normal maps). Select **Detailed material** to sample layer
  maps, height blending, parallax, and POM in the VTK shader. It uses the same four-layer
  selection as ADM export and warns when dropped surfaces can cause seams. It requires a
  compatible VTK shader pipeline and enough texture units. Select fewer tiles or a coarser
  LOD if it exceeds the detailed-preview budget of 250,000 triangles or 128 material palettes.
  The detailed view also limits unique decoded texture base levels to 512 MiB per redraw;
  select fewer tiles or smaller textures if it exceeds that limit. This estimate excludes
  GPU mipmaps, renderer overhead, and temporary decoding allocations.
  Select **COLOR_1 palette channel**, then R, G, B, or A, to inspect the quantized
  vertex weights exported for each primitive. Channels name local palette slots, so the
  same channel can represent different surfaces in different primitives. This view uses
  the detailed triangle and palette budgets but does not load material textures.
  **Collision mesh** displays selected collision geometry instead of render geometry, colours
  faces by physical-material assignment, and reports triangle counts and measured error. Hover
  over a face to inspect its dominant surface, physical-material name, and stable ID. Unassigned
  faces are gray; unknown IDs are magenta. Collision inspection is limited to 250,000 triangles
  and 256 MiB per collision file.
  The other modes retain the 8 M triangle budget. LOD, vertical exaggeration, and wireframe
  remain available.

## Import material sets

Use **Import sets…** in the **Surface library** to scan a folder and its subfolders. The importer
groups files by the name before a recognized map suffix. It identifies file formats by their
contents, not their filename extensions; supported inputs are DDS, KTX2, PNG, TIFF, and TGA.

The default suffixes are:

| Map | Suffixes |
|---|---|
| Albedo | `_abte`, `_albedo`, `_basecolor`, `_diffuse` |
| Normal | `_nm`, `_normal` |
| Ambient occlusion | `_ao`, `_occlusion` |
| Roughness | `_roughness` |
| Metallic | `_metallic` |
| Height | `_height`, `_displacement` |
| Emission | `_emission`, `_emissive` |

For example, `rock_01_abte.dds`, `rock_01_nm.ktx2`, and `rock_01_ao.png` form the `rock_01`
surface. Edit suffixes in the import dialog when your files use different names, then select
**Scan again**.

Review the **Found maps** and **Missing maps** columns before you import. If several files match
one map, choose the intended file for that conflict. The importer never assigns packed `_ma` or
unknown maps. Select the surface sets to import; existing surfaces stay unchanged unless you
enable **Update matching existing surfaces**. Updates replace only maps that were found, so
missing maps keep their current values. New surfaces are added to the library but are not
automatically assigned to biomes.

## Adjust biome heights visually

1. Open a heightmap and select a **Biome** in the **Terrain** tab's **Texturing** section.
2. Enable **Automatic** for a paint-only biome if you want to place it by height.
3. Enable **From** or **To** to set a bounded edge. Drag **FROM** or **TO** in the graph, or
   enter the heights in metres. You can also drag another biome's dashed boundary to select it.
4. Drag **FADE** to set the transition, or enter its width in metres. This is the total transition
   width centred on each limit; both edges share the same width.
5. Save the project. Rebuild and export the tiles to apply the updated vertex weights.

Unchecked limits remain open. Limits outside the heightmap are editable numerically but have no
handle on the histogram. The first biome fills the remaining area and has no automatic height
controls. The graph's coloured bars show the dominant automatic biome on flat ground; the
selected curve shows its height rule alone. Slope, painted areas, and later biomes taking
priority can change the final result. Surface-specific rules remain on the **Material** tab.

## Project file (`.awtp`)

JSON with build parameters (heightmap, scale, tiles, LOD errors, collision settings, biome
rules, paint and build folder), roads, visual and physical material data, export settings and
tile selection. Physical paint is stored separately from biome and visual-surface paint.
Paths are stored relative to the project file, so the folder can be moved together with its
heightmap and textures. Reopening a project loads the heightmap and the built tiles from the
build folder.
Project formats 2–10 can be opened. New saves use format version 11 and persist stable IDs for
terrain surfaces and physical materials, surface-to-physical-material links, and the independent
physical-paint map. Legacy projects derive a terrain-surface ID from its original name; renaming
a surface does not change its ID.
Older tool versions cannot open files saved with a newer format version.

## Create a road

1. On the **Map** tab, click **New road**.
2. Click the map to add at least two control points. Their initial heights come from the source
   heightmap.
3. Click a control point and change **Point height** to set its elevation in metres.
4. Choose the road **Surface**, **Width**, and **Shoulder**. The shoulder blends the road grade
   and surface into the surrounding terrain.
5. Rebuild the tiles and export them. The 3D view shows the road after the rebuild.

Select an existing road in the list to edit its points or delete it. **Delete point** removes the
selected control point. The curved centre line has a smooth elevation profile through the point
heights. Roads are applied in list order, after surface paint; later roads take priority where
they overlap. The original heightmap is never modified. The editable terrain remains a heightmap,
so overhangs and separate bridge geometry need other tools. Surface paint and roads use a paint
grid of at most 4096 cells per side; a road must be at least one paint cell wide.

## ADM export

```
adm/
  x000_y000.adm           one model per tile: all LODs, selected layered profile and COLOR_1
  textures/<name>_<hash>.*     primary layer textures and GPU texture PNG fallbacks
  world.json              what was exported: per-tile digest, origin, size; settings; material
```

* Each tile's root node sits at the tile centre in world space (ADM: Y up, −Z north), so
  imported tiles line up without any manual placement. Several LODs become an ADM
  `lodGroup`; LOD 1 starts at *LOD 1 from* (default: one tile size) and every further LOD
  doubles that distance. A single LOD is written as a plain mesh.
* Material profile defaults to `adm.terrain.four_layer@2.0.0`. Choose
  `adm.terrain.four_layer@2.1.0` in **Terrain shader settings** to export AO, height, emission,
  height blending, or parallax, or enable automatic upgrade in the material editor.
  Profile 2.0.0 remains unchanged; if you author advanced settings without selecting or
  upgrading to 2.1.0, export stops with an explicit error. Surface weights are per-vertex
  `COLOR_1`; each primitive uses up to four surfaces. A tile using more than four surfaces is
  split across multiple primitives/materials. Each material includes layer albedo, base color,
  metallic and roughness factors and maps, normal, and UV scale. Profile 2.1.0 also includes
  per-layer AO and height maps, channel/invert controls, height scale/bias, emission maps,
  height-blend settings, and parallax/POM settings. Tangents are written when a used surface has
  a normal map or active parallax with a height map and non-zero scale.
  The portable PBR fallback represents only the first layer's textures and factors. It does not
  reproduce vertex-weighted layers, metallic/roughness maps, AO maps, height blending, or
  parallax; the export result reports these limitations.
* Layer textures are shared through `ADM_external_images_v1` by default (content hash in the
  file name and in the tile, checked on import). GPU textures have a DDS or KTX2 primary image
  and a same-size PNG fallback. **Embed** puts the images into every tile, instead, repeating the
  data per tile. ADM-compatible DDS and KTX2 files are preserved byte-for-byte when their color
  space matches the texture role. If an ADM-compatible GPU source has a mismatched color space,
  export stops; convert the source explicitly or choose a compatible map. Other inputs are
  generally converted to DDS: albedo uses automatic BC1/BC3
  selection, normal maps use uncompressed RGBA8, and data maps use BC3 or keep a compatible
  scalar format. Albedo and emission use sRGB; normal, AO, height, metallic, and roughness maps
  use linear UNORM. PNG is used as the importer-friendly fallback. DDS textures using BC1, BC3,
  BC4, BC5, BC6 or BC7 are decoded by AWT; supported
  BC2/DXT3 files are read through Pillow.
  BC5 normal maps reconstruct their Z component in the surface and blend previews.
  Scalar GPU fallbacks retain red values and use zero for green and blue.
  16-bit grayscale TIFF inputs retain their samples in the R16 primary and PNG
  fallback. Multichannel 16-bit data PNGs remain byte-identical PNG primaries; RGB and RGBA
  16-bit TIFF data maps become 16-bit PNG primaries without reducing channel precision. They
  have no separate fallback, and export reports the choice. Other multichannel 16-bit TIFF
  layouts are rejected rather than quantized. The height preview also retains the selected
  channel's 16-bit TIFF samples. When a 16-bit grayscale PNG or TIFF uses a green or blue map channel, export remaps
  that selection to red in ADM and reports the change. The project keeps the
  original selection. Scalar GPU input channels are not remapped.
  Single 2D textures are supported (not texture arrays, cubemaps or volumes).
* **GPU container** selects DDS or KTX2 for converted images. **GPU encoding** selects the
  role-based default, BC7, or uncompressed RGBA8 for converted 8-bit images. Compatible GPU
  sources remain byte-identical, even when they use another container or encoding, unless you
  enable **Re-encode compatible GPU sources**. That option rebuilds mipmaps and can lose
  quality. Scalar 16-bit data uses R16,
  and multichannel 16-bit data stays in PNG rather than being quantized to the selected 8-bit
  encoding. The export report identifies textures that retain a different format.
  Each surface map can override the export encoding. Data maps also offer R8, R16, and BC4:
  export copies the selected channel to red, updates the ADM channel selection, and retains
  inversion. The source and project selection stay unchanged. Normal maps offer BC5 with a
  reconstructed RGB normal for portable PBR. Compatible GPU sources and 16-bit data still
  follow the preservation rules; enable GPU source conversion to re-encode compatible GPU files.
* **Export changed** compares a digest of every tile's meshes, vertex weights, material
  (including the complete source texture bytes and mip levels), placement and export settings
  with `world.json`. Shader-only
  material edits do not rebuild terrain geometry or vertex weights. For newly built tiles, a
  surface edit marks only tiles that use that surface in at least one LOD. Global shader and
  export settings can affect every tile. A global GPU encoding change does not mark a tile
  when every texture it uses has a per-map encoding override. Older manifests without surface-use metadata conservatively
  mark all tiles for a material edit. The first export with the per-tile fingerprints also
  refreshes tiles recorded with older fingerprints. A missing `.adm` file is always exported again.
  GPU export setting changes mark textured tiles as changed; tiles that use no textures remain
  unchanged. Textured tiles with only preserved sources are conservatively marked as changed.
  Collision mesh digests are part of the same tile fingerprint.
* Each terrain primitive supports at most four surfaces. Weights at or below 2/255 are omitted
  when the exporter determines a triangle's surface set. New projects use **Strict** palette
  handling: export checks the selected tile LODs before writing and refuses a tile set if any
  triangle needs more than four surfaces. Choose **Approximate (seam-aware reduction)** only
  when losing some weight is acceptable. It keeps each vertex's dominant surface, reconciles
  vertex weights across the primitive palettes that use that vertex, and reports the affected
  triangles, up to 20 examples of dropped surfaces with raw U8 corner weights
  (0 to 255), and mean and maximum total-variation error. The report suggests
  reducing overlapping weights or painting fewer active surfaces with
  **Surface** on the **Map** tab. This guarantees matching effective
  weights at shared vertices within each tile LOD; it does not claim exact representation of
  omitted surfaces or continuity across independently sampled tile/LOD boundaries. Projects
  from versions 2–6 that do not store a palette policy load as **Approximate** to preserve their
  previous export behavior. Saving writes project format version 11 with the selected policy.
  Exported terrain materials use `ADM_terrain_surface_v1` to map local layer slots to those stable
  IDs. The extension adds identity metadata and does not change rendering or physical assignments.
* Every written tile is validated with the ADM validator before it replaces the old file
  (atomic write). Validation is the slowest step (see Performance); turn it off for quick
  iterations.

## Build folder

```
out/
  manifest.json           tiles, LOD and collision statistics, biome/surface rules, and weights
  preview.png             hillshade (≤ 1024 px)
  biomes.png               biome preview (≤ 1024 px)
  surfaces.png             dominant-surface preview (≤ 1024 px)
  tiles/x000_y000_lod0.ply
  collision/x000_y000_collision.ply  optional independent collision mesh
```

* Tile `x{ix}_y{iy}`: `ix` grows east, `iy` grows **north** (y000 is the southern row).
* Units are metres, Z up. Vertices are relative to the tile's `origin_m` (its south-west
  corner), Z is absolute height. `--origin center` puts the terrain centre at 0, 0.
* All LODs retain matching tile boundaries, so adjacent tiles can use different LODs without
  cracks. Rebuild the tiles and re-export them to apply this to an existing project.
* When collision generation is enabled, each tile has a separate `collision/*.ply` mesh. The
  manifest records its measured height error, triangle count, refined boundary-vertex count and
  stable dominant surfaces used for automatic physical classification. Collision vertices also
  store stable authored surface weights; these weights do not change collision geometry.
  ADM export references the mesh from a `MESH` collider. Manual paint overrides automatic
  physical-material links; a triangle with no applicable link remains unassigned. Older collision
  manifests remain loadable, but automatic classification requires rebuilding with manifest
  version 4, which records the weights' dominant surfaces.
* PLY vertices: position, normal (from the full-resolution heightmap, so shading is seamless
  across tiles and LODs), `UVMap` (s, t) and `UVMap_1` (s1, t1).

### Mesh guarantee

Simplification is a global RTIN (right-triangulated irregular network) over the whole map.
For every LOD the vertical distance between the mesh and **every** edited heightmap sample is at
most the LOD's maximum error, measured exactly (not estimated) and reported as
`measured_error_m`. Neighbouring tiles share identical edge vertices, so there are no cracks
between tiles even when their LODs differ. Tile size must be a power of two cells; maps that are not a
multiple of it get smaller tiles on the east and south edges.

### Biomes, surfaces and transitions

Each biome blends its own one-to-four surfaces using height and slope rules; biome rules are
evaluated in list order, with later biomes taking priority. The starter biomes have shared
surfaces where they meet. At a border, AWT fades biome-specific surfaces into the surfaces
shared by the two biomes, then into the neighbouring biome. For the smoothest result, keep at
least one surface in common between every pair of biomes that can touch. The GUI warns about
pairs without a shared surface; these pairs fall back to a direct blend and can show a hard
texture change.

Set **Surface noise** for an individual biome to blend its assigned surfaces into a smooth
spatial pattern with a 20 m scale. At 0% its original rules are unchanged; higher values
increase the variation and can introduce biome surfaces outside their height and slope bands.
The effect requires at least two surfaces in the biome. It also works for painted biomes but
does not alter direct surface paint or roads. The pattern uses world-scale coordinates, so it
matches at tile and LOD boundaries. The 2D surface view updates from the rules; rebuild the tiles
to update the 3D terrain and exported vertex weights.

Automatic placement, hand-painted biome areas, and hand-painted surfaces are combined in the same
weight field. Surface paint overrides biome paint, and roads override both. Softening blurs paint shares
to create a gradual boundary. The 2D biome and surface views and the 3D material preview show
the generated result before export.

Optional **Texture error** refinement subdivides triangles where interpolated vertex weights
would differ from the texture field by more than the chosen threshold. **Texture detail**
limits how short a new triangle edge may be. Set Texture error to 0 to disable refinement.
This can add geometry around texture transitions without changing the configured terrain LOD
height-error bound. Fine surface noise can be missed on coarse meshes or low-resolution
heightmaps. To capture more of it, lower **Texture error** and **Texture detail** or increase
the heightmap resolution. At three-biome junctions, the pairwise blend rule can leave small
discontinuities; inspect these areas in the previews.

* `UVMap` (UV0) runs 0..1 across each full tile. Set the layer textures' `uv_scale` to an
  integer (tile size ÷ texture repeat in metres) and they continue seamlessly into the next
  tile.
* Surface weights are stored on vertices, not in a separate blend-mask texture. `COLOR_1`
  carries the four weights for the current primitive's surface slots; neighbouring tiles
  calculate matching edge weights from the same world-space terrain field.

## Finishing the world in Blender

Export from the **Export** tab, then import the resulting `.adm` files with **File → Import →
ADM Model** (multi-select works). Tiles arrive at their world positions with their LODs,
`COLOR_1` weights and materials. Make texturing changes in AWT and use **Export changed** to
update only affected tiles.

## Performance

Measured on 12 threads (Python 3.14, Numba 0.68):

| Input | Tiles | LODs | Time | Triangles LOD0 / LOD1 / LOD2 |
|---|---|---|---|---|
| 2048², 0.71 m | 8 × 8 of 256 | 0.1 / 0.5 / 2 m | 0.7 s | 5.9 M / 2.0 M / 0.39 M |
| 4033², 2 m | 16 × 16 of 256 | 0.25 / 1 / 4 m | 6.1 s | 10.1 M / 3.0 M / 0.73 M |
| 16385², 1 m | 32 × 32 of 512 | 0.25 / 1 / 4 m | 19.6 s | 141.5 M / 2.2 M / 0.45 M |

Working memory is about 2 bytes (uint16 heights) + 4 bytes (error grid) per sample:
≈ 1.6 GB for 16k × 16k. The GUI shows the estimate before building.

ADM export of 4097², 16 × 16 tiles of 256, 3 LODs, four 1024² layers with normal maps
(357 MiB): 7.4 s with validation, 0.9 s without; checking which tiles changed takes 10 ms.

## Tests

```bat
.venv\Scripts\python -m unittest discover -s tests -t .
```

They check the error bound against every sample, watertightness across tiles, winding,
non-power-of-two sizes, biome/surface weights and seamless edges, paint blending, UVs,
ADM export (world placement, validation, tangents, changed-tile detection, embedded textures),
advanced profile maps and parallax tangents, project round trips, and material preview bakes.
