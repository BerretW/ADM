# `adm.surface.two_layer@1.0.0`

Two independently textured PBR layers blended by a linear grayscale mask. This profile is suitable
for effects such as worn walls or moss on stone; it does not require vertex colors.

The parameter definitions are in `registry.json`. The `layer0_*` and `layer1_*` parameters,
including metallic and roughness texture channel selection and inversion, follow
[`adm.terrain.four_layer@1.0.0`](adm.terrain.four_layer.v1.md). Each layer uses its own `uv_scale`
component. The unused third and fourth components are retained for the shared parameter shape.

`blend_mask` uses its own unscaled `texCoord`. Its linear red channel is clamped to `[0,1]` and
gives the layer 1 weight; the layer 0 weight is `1 - mask`. An absent mask selects layer 0. Black
therefore shows layer 0, white shows layer 1, and gray interpolates between them. The same weights
apply to albedo, alpha, metallic, roughness, emission and decoded tangent-space normals. Normalize
the weighted normal; a zero vector is invalid. The mask is not a two-channel terrain weight map.

The top-level PBR material fields remain the portable fallback. No shader parameters are animatable.
Readers without this profile use the fallback; independent renderer support is not implied.
