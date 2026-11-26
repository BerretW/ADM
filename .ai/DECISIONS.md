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
