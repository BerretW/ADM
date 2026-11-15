# Apparatus World Tile

Desktop tool that turns a large heightmap (tested at 16 385 × 16 385) into crack-free
terrain tiles with several levels of detail and a TERRAIN_4 blend mask per tile, textures
them, and writes finished **ADM tiles** that open directly with **File → Import → ADM Model** in
Blender. The heavy work (meshing, simplification, masks, export) happens here, in parallel
native code. A project file (`.awtp`) keeps everything, so a world can be reopened, edited
and re-exported later; only tiles that changed are written again.

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

## GUI

* **File menu:** New / Open / Save / Save as project (`.awtp`), Open heightmap, Open built
  tiles. The title shows `*` while the project has unsaved changes; closing asks to save.
* **Terrain tab:** heightmap, scale, tile size with tile count and memory estimate, LOD
  errors, material zones with a height histogram (water and snow thresholds drawn into it),
  build folder, **Build tiles**.
* **Material tab:** the TERRAIN_4 material shared by all tiles. Per layer (ground, rock,
  snow, water = mask R, G, B, A): tint, albedo, texture repeat in metres (rounded to a whole
  number of repeats per tile, so textures continue across tiles), metallic and roughness as
  a factor plus an optional texture with channel and invert (packed maps such as RDR2 `_ma`
  work by picking the channel), and a normal map.
* **Export tab:** ADM folder, LOD switch distance, embed or share textures, validation,
  **Export changed / Export selected / Export all**. Tiles that are new or changed since the
  last export get a red corner on the map.
* **Map tab:** relief, zones (live, recomputed as you move the thresholds) or mesh density
  per tile. Click or drag to select tiles, Shift adds, double-click opens one tile in 3D.
* **3D tab:** the built tiles, coloured by height, by the blend masks exactly as TERRAIN_4
  will mix them, by tile, or by **Material** (layer albedos × tint blended by the masks,
  without normal maps). LOD switch, vertical exaggeration, wireframe. The preview keeps
  under 8 M triangles and automatically picks the finest LOD that fits.

## Project file (`.awtp`)

JSON with the build parameters (heightmap, scale, tiles, LOD errors, zone rules, build
folder), the material, the export settings and the tile selection. Paths are stored
relative to the project file, so the folder can be moved together with its heightmap and
textures. Reopening a project loads the heightmap and the built tiles from the build folder.

## ADM export

```
adm/
  x000_y000.adm           one model per tile: all LODs, TERRAIN_4 material, embedded mask
  textures/<name>_<hash>.png   layer textures, written once (unless they are embedded)
  world.json              what was exported: per-tile digest, origin, size; settings; material
```

* Each tile's root node sits at the tile centre in world space (ADM: Y up, −Z north), so
  imported tiles line up without any manual placement. Several LODs become an ADM
  `lodGroup`; LOD 1 starts at *LOD 1 from* (default: one tile size) and every further LOD
  doubles that distance. A single LOD is written as a plain mesh.
* Material: `adm.terrain.four_layer` with `layer{i}_texture`, `_base_color`, `_metallic`,
  `_roughness`, `_metallic_texture` / `_roughness_texture` with `_channel` and `_invert`,
  `_normal`, `uv_scale` and `blend_mask` on UV1. Tangents are written only when a layer has
  a normal map.
* Layer textures are shared through `ADM_external_images_v1` by default (content hash in the
  file name and in the tile, checked on import). **Embed** puts them into every tile
  instead, which is simpler to move around but repeats the data per tile. PNG and baseline
  JPEG pass through untouched; other formats (TGA, TIFF, DDS readable by Pillow…) are
  converted to PNG.
* **Export changed** compares a digest of every tile's meshes, mask, material (including the
  texture contents), placement and export settings with `world.json`. Rebuilding with other
  LOD errors, retexturing a layer or changing the LOD distance marks the affected tiles;
  a missing `.adm` file is always exported again.
* Every written tile is validated with the ADM validator before it replaces the old file
  (atomic write). Validation is the slowest step (see Performance); turn it off for quick
  iterations.

## Build folder

```
out/
  manifest.json           tiles, LOD statistics and digests, parameters, zone rules, mask layer order
  preview.png             hillshade (≤ 1024 px)
  zones.png               zone map (≤ 1024 px)
  tiles/x000_y000_lod0.ply
  masks/x000_y000_mask.png
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

### Layer masks and UVs (TERRAIN_4)

| Mask channel | TERRAIN_4 layer | Zone | Rule |
|---|---|---|---|
| R | 0 | ground | everything not claimed below |
| G | 1 | rock | slope between *rock start* and *rock full* |
| B | 2 | snow | height between *snow start* and *snow full*, fades out on slopes steeper than *snow up to slope* |
| A | 3 | water / shore | at or below *water level*, fading out over the *shore* band |

Priority is water > snow > rock > ground, and the four weights always sum to 255, which is
what `blend_mask` expects. **Suggest from heights** proposes thresholds: water at 2 % of the
height range, snow between the 85th and 95th height percentile. Only the thresholds are
guesses; check the zone map and adjust.

* `UVMap` (UV0) runs 0..1 across each full tile. Set the layer textures' `uv_scale` to an
  integer (tile size ÷ texture repeat in metres) and they continue seamlessly into the next
  tile.
* `UVMap_1` (UV1) addresses the tile's own mask with a half-texel inset. Neighbouring masks
  contain identical edge pixels, so blends meet without seams. In the material,
  `blend_mask` uses `tex_coord = 1` (UVMap_1) and the four layer textures `tex_coord = 0`.
* Mask size defaults to the tile cell count (one mask pixel per heightmap cell, max 2048);
  smaller masks smooth the transitions and save memory.

## Finishing the world in Blender

**Direct (recommended):** export ADM tiles here and import them with **File → Import → ADM Model**
(several files at once). Tiles arrive in place with their LODs, UV maps, mask and TERRAIN_4
material; edit the material in AWT and use **Export changed** to update only what differs.

**From the build folder:** if you prefer to texture in Blender instead,

1. Build the tiles here and check the zones in 2D and 3D.
2. In Blender: **ADM Tools → Terrain → Import World Tiles**, choose `manifest.json` and the
   LODs to import. Every tile becomes an ADM model with its mesh, both UV maps and its own
   material with the tile's mask already assigned. Positions match the heightmap exactly.
3. Set up the shared template material **ADM World Terrain** once: four layer textures
   (ground, rock, snow, water), `uv_scale`, normals and so on.
4. **Sync World Terrain Materials** copies the template into every tile material and keeps
   each tile's own mask. Repeat after every template change.
5. Hand-paint corrections into individual masks (Texture Paint on `UVMap_1`) where needed.

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
non-power-of-two sizes, masks (sum, seamless edges, zone rules), UVs, ADM export (world
placement, validation, tangents, changed-tile detection, embedded textures), the project
round trip and the material preview bake.
