# Mission decisions

Record only decisions verified from repository policy or required to resolve
implementation ambiguity. Link each decision to its source and tests.

## Pending audit
- Shader/profile and capability versioning must follow the existing registry,
  freeze manifest, and development-change governance; inspect those sources
  before choosing identifiers or versions.
- New material effects must be opt-in and preserve frozen legacy profiles.
- Do not claim a renderer supports an effect unless its implementation and tests
  demonstrate that support; retain unknown metadata through round trips.

## Confirmed implementation decisions
- Keep `ADM-TEX-KTX2-1` and `ADM-TEX-DDS-1` meanings unchanged. Use separate
  `-2` capabilities for additional formats and select portable fallbacks when
  a reader only implements v1.
- Keep shader-only AO/height/parallax settings out of `rules_digest`; include
  their serialized fields and referenced image content in material fingerprints.
- Until advanced profile export is implemented, reject an advanced World Tile
  export with an explicit error rather than emitting a legacy material that
  silently loses its settings.
- Expose R8/R16 through a separate scalar codec API instead of routing R16
  through the uint8 RGBA interface; reject R16 RGBA decoding to avoid silent
  precision loss.
- Keep BC7 encoding distinct from parsing and decoding. The decoder uses
  `texture2ddecoder` when installed; never interpret BC7 blocks as another
  format, and report a missing decoder dependency explicitly.
- Add layered AO/height features under the exact additive profile identities
  `adm.terrain.four_layer@1.1.0/@2.1.0`,
  `adm.surface.two_layer@1.1.0`, and `adm.pbr.layered@2.1.0`; do not redefine
  the existing 1.0.0 or 2.0.0 profile schemas.
- Keep each layer's AO, height, normal, and PBR texture references on the
  albedo's UV set. A per-layer height map's parallax offset affects that layer's
  samples, but never changes the already-computed base weights.
- Implement all ADM Editor requirements in existing authoring tools rather than
  creating a separate application. The primary targets are the ADM Blender
  Plugin and Apparatus World Tile Editor; apply relevant work to other existing
  material and shader consumers.

## World Tile preview renderer audit

- The surface preview uses PyVista's VTK PBR actor, with generated tangents
  for normal maps and separately bound albedo, ORM, normal, and emission
  textures. The multi-surface preview precomposes maps on the CPU and sends a
  single material to VTK. The terrain inspection view is a separate path.
- VTK 9.7.2 on Windows exposes fragment and vertex shader replacements,
  named texture bindings and custom uniforms. An offscreen experiment sampled
  a separately bound height texture in a custom fragment replacement. Another
  experiment ray-marched that texture with explicit gradients and observed
  different UV offsets at frontal and oblique camera angles. This establishes
  technical feasibility, not application integration or shader conformance.
- Built-in PBR code samples albedo, ORM, normals and emission separately. Any
  per-layer POM implementation must shift each of those map samples consistently,
  retain stable derivatives for ray samples, and handle missing or degenerate
  tangent frames. The existing CPU-composited multi-surface maps cannot represent
  independently view-dependent offsets for multiple layers; implementing that
  path requires per-layer GPU sampling rather than shifting a single composite.
- VTK shader replacements depend on generated shader hooks and names; guard
  against version differences with actual render tests and visible failure
  diagnostics. Keep effect code and texture/uniform binding separate from UI
  controls so later effects can extend the pipeline. Retain the existing
  renderer unless concrete evidence proves it unsuitable; the experiment does
  not justify replacing the backend.
- The single-surface preview passes its own view-space position through a vertex
  varying because VTK omits `vertexVC` in some render passes. A derivative-based
  tangent frame drives the bounded offset, and the same shifted coordinates are
  substituted into VTK's albedo, ORM, normal, and emission samples. This is
  tested on VTK 9.7.2; shader-hook compatibility on other versions remains
  unverified. The UI reports configuration rather
  than claiming shader compilation succeeded.
- The multi-surface final view binds each layer's original-resolution maps
  separately and computes each parallax ray, map sample and height-adjusted
  weight in the fragment shader. Weight inspection and displayed mean weights
  remain CPU estimates at unshifted UVs. Texture-unit exhaustion is reported
  rather than silently dropping maps; when a Qt context is not yet available,
  the OpenGL minimum of 16 units is used conservatively.
