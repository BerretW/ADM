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
.venv\Scripts\python -m awt export world.awtp                   :: only changed tiles
.venv\Scripts\python -m awt export world.awtp --tiles x003_y001 x004_y001
.venv\Scripts\python -m awt export world.awtp --all --build     :: rebuild, then write everything
```

The first run compiles the Numba kernels (a few seconds); the compiled code is cached.
ADM export uses `adm_blender/core` from this repository (no Blender needed), so keep the tool
inside the ADM checkout.

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

## GUI

* **File menu:** New / Open / Save / Save as project (`.awtp`), Open heightmap, Open built
  tiles. The title shows `*` while the project has unsaved changes; closing asks to save.
* **Terrain tab:** heightmap, scale, tile size with tile count and memory estimate, LOD
  errors, build folder, **Build tiles**.
* **Material tab:** a surface library (albedo, tint, texture repeat in metres, metallic and
  roughness factors/maps with channel and invert, and normal map) plus biomes that select and
  blend those surfaces. The six starter biomes are lowland, forest, shore, water, mountains
  and rocky terrain. Each biome can be placed automatically by height/slope bands or painted
  manually; its surface list can also limit individual surfaces by height and slope.
  **Terrain setup wizard** starts from current rules or a temperate, alpine, coastal/island or
  arid profile, then lets you edit each biome's height/slope limits and choose albedo images
  for its shared surfaces. **Save preset** copies the material setup and its textures into the
  AWT user-data folder; **Load preset** restores it. Presets do not include map-specific paint.
  Neighbouring biomes should share at least one surface so the transition uses a common
  texture rather than changing abruptly. Texture repeat is rounded to a whole number per tile,
  so textures continue across tiles. The selected surface has a lit **Sphere** and tiled
  **Plane** preview; **Show blended terrain** opens the 3D terrain with all current biome
  rules applied.
* **Export tab:** ADM folder, LOD switch distance, embed or share textures, validation,
  **Export changed / Export selected / Export all**. Tiles that are new or changed since the
  last export get a red corner on the map.
* **Map tab:** relief, biome weights, surface weights or mesh density per tile. Click or drag
  to select tiles, Shift adds, double-click opens one tile in 3D. Enable **Paint biomes** to
  paint the selected biome; right-drag restores automatic placement. **Paint softness** sets
  how far painted borders fade.
* **3D tab:** the built tiles, coloured by height, by biome or surface weights, by tile, or by
  **Material** (surface albedos × tint blended by vertex weights,
  without normal maps). LOD switch, vertical exaggeration, wireframe. The preview keeps
  under 8 M triangles and automatically picks the finest LOD that fits.

## Project file (`.awtp`)

JSON with the build parameters (heightmap, scale, tiles, LOD errors, biome rules, paint and
build folder), the surface/biome material, the export settings and the tile selection. Paths are stored
relative to the project file, so the folder can be moved together with its heightmap and
textures. Reopening a project loads the heightmap and the built tiles from the build folder.

## ADM export

```
adm/
  x000_y000.adm           one model per tile: all LODs, four_layer@2.0.0 materials and COLOR_1
  textures/<name>_<hash>.dds   primary layer textures (unless they are embedded)
  textures/<name>_<hash>.png   PNG fallback for each primary texture
  world.json              what was exported: per-tile digest, origin, size; settings; material
```

* Each tile's root node sits at the tile centre in world space (ADM: Y up, −Z north), so
  imported tiles line up without any manual placement. Several LODs become an ADM
  `lodGroup`; LOD 1 starts at *LOD 1 from* (default: one tile size) and every further LOD
  doubles that distance. A single LOD is written as a plain mesh.
* Material: `adm.terrain.four_layer@2.0.0`. Surface weights are per-vertex `COLOR_1`; each
  primitive uses up to four surfaces. A tile using more than four surfaces is split across
  multiple primitives/materials. Each material includes `layer{i}_texture`, `_base_color`,
  `_metallic`, `_roughness`, `_metallic_texture` / `_roughness_texture` with `_channel` and
  `_invert`, `_normal`, and `uv_scale`. Tangents are written only when a used surface has a
  normal map.
* Layer textures are shared through `ADM_external_images_v1` by default (content hash in the
  file name and in the tile, checked on import). Each texture has a DDS primary image and
  same-size PNG fallback. **Embed** puts both images into every tile, instead, repeating the
  data per tile. ADM-compatible DDS files are preserved byte-for-byte when their color space
  matches the texture role. Other inputs are converted to DDS: albedo uses automatic BC1/BC3
  selection, normal maps use uncompressed RGBA8, and metallic/roughness maps use BC3; color
  textures use sRGB while data textures use linear UNORM. PNG is used as the importer-friendly
  fallback. DDS textures using BC1, BC3, BC4, BC5, BC6 or BC7 are decoded by AWT; supported
  BC2/DXT3 files are read through Pillow.
  Single 2D textures are supported (not texture arrays, cubemaps or volumes).
* **Export changed** compares a digest of every tile's meshes, vertex weights, material
  (including the texture contents), placement and export settings with `world.json`. Rebuilding with other
  LOD errors, retexturing a layer or changing the LOD distance marks the affected tiles;
  a missing `.adm` file is always exported again.
* Every written tile is validated with the ADM validator before it replaces the old file
  (atomic write). Validation is the slowest step (see Performance); turn it off for quick
  iterations.

## Build folder

```
out/
  manifest.json           tiles, LOD statistics, biome/surface rules, and weights metadata
  preview.png             hillshade (≤ 1024 px)
  biomes.png               biome preview (≤ 1024 px)
  surfaces.png             dominant-surface preview (≤ 1024 px)
  tiles/x000_y000_lod0.ply
```

* Tile `x{ix}_y{iy}`: `ix` grows east, `iy` grows **north** (y000 is the southern row).
* Units are metres, Z up. Vertices are relative to the tile's `origin_m` (its south-west
  corner), Z is absolute height. `--origin center` puts the terrain centre at 0, 0.
* PLY vertices: position, normal (from the full-resolution heightmap, so shading is seamless
  across tiles and LODs), `UVMap` (s, t) and `UVMap_1` (s1, t1).

### Mesh guarantee

Simplification is a global RTIN (right-triangulated irregular network) over the whole map.
For every LOD the vertical distance between the mesh and **every** heightmap sample is at
most the LOD's maximum error, measured exactly (not estimated) and reported as
`measured_error_m`. Neighbouring tiles share identical edge vertices, so there are no cracks
between tiles of the same LOD. Tile size must be a power of two cells; maps that are not a
multiple of it get smaller tiles on the east and south edges.

### Biomes, surfaces and transitions

Each biome blends its own one-to-four surfaces using height and slope rules; biome rules are
evaluated in list order, with later biomes taking priority. The starter biomes have shared
surfaces where they meet. At a border, AWT fades biome-specific surfaces into the surfaces
shared by the two biomes, then into the neighbouring biome. For the smoothest result, keep at
least one surface in common between every pair of biomes that can touch. The GUI warns about
pairs without a shared surface; these pairs fall back to a direct blend and can show a hard
texture change.

Automatic placement and hand-painted biome areas are combined in the same weight field.
Painting overrides automatic placement in the painted area; softening blurs the paint shares
to create a gradual boundary. The 2D biome and surface views and the 3D material preview show
the generated result before export.

Optional **Texture error** refinement subdivides triangles where interpolated vertex weights
would differ from the texture field by more than the chosen threshold. **Texture detail**
limits how short a new triangle edge may be. Set Texture error to 0 to disable refinement.
This can add geometry around texture transitions without changing the configured terrain LOD
height-error bound. At three-biome junctions, the pairwise blend rule can leave small
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
the project round trip and the material preview bake.
