# ADM PBR metallic-roughness 2.1.0: edge wear and dirt

Status: normative shader profile contract for ADM 1.0.

This contract applies only to `adm.pbr.metallic_roughness@2.1.0`. It uses the existing ADM 1.0
material schema and `ADM_vertex_control_v1` `COLOR_1` attribute. It does not change the container
format or the meaning of `adm.pbr.metallic_roughness@2.0.0`. Readers resolve the exact shader
identity and version.

The shared `COLOR_1` encoding, interpolation, and surface-overlay operations from
[`ADM_shader_vertex_masks_v2.md`](ADM_shader_vertex_masks_v2.md) apply except where this contract
defines different behavior for channels G and B.

## Dirt mask

`COLOR_1.G` identifies where the renderer may add dirt. Its value is a linear coverage weight;
zero disables dirt and intermediate values feather the allowed area. The renderer supplies a
`dirt_amount` value in `[0,1]` for each model instance. This runtime value is not an ADM material
parameter and is not serialized.

```text
dirt_coverage = clamp(COLOR_1.G, 0, 1)
effective_g = clamp(dirt_coverage * dirt_amount, 0, 1)
```

The renderer or viewer may choose a different `dirt_amount` for each instance. It may derive the
values from a repeatable per-instance seed. A renderer MUST NOT treat `COLOR_1.G` as the complete
dirt amount or apply dirt where the channel is zero.

The G surface overlay uses the shared surface-overlay operation with `effective_g`. The profile
does not define `color1_g_strength`; `dirt_amount` is the only runtime intensity control.

## Edge wear

`COLOR_1.B` identifies where the renderer may add wear. Its value is a linear coverage weight;
zero disables wear and intermediate values feather the allowed area. The renderer supplies a
`wear_amount` value in `[0,1]` for each model instance. This runtime value is not an ADM material
parameter and is not serialized.

The shader derives an edge signal from convex geometric curvature and sharp transitions in the base
PBR normal map. A missing normal map contributes zero. Flat and concave geometric regions contribute
zero to the geometric signal. The renderer also generates an irregular procedural `wear_pattern`
in `[0,1]` to break up the worn surface into chipped or damaged patches. The pattern is independent
of `wear_amount` and requires no additional texture in the ADM model.

Each signal is normalized to `[0,1]`. For the base PBR normal map, decode the sampled tangent-space
normal, apply the normal map's strength, and normalize the result as `n(u,v)`. Compare it with
samples one texel away in the positive and negative U and V directions:

```text
normal_map_edge = clamp(
    max(length(n(u,v) - n(u + du,v)),
        length(n(u,v) - n(u - du,v)),
        length(n(u,v) - n(u,v + dv)),
        length(n(u,v) - n(u,v - dv))) / 2,
    0, 1)
edge_signal = max(convex_geometry_signal, normal_map_edge)
wear_coverage = clamp(COLOR_1.B, 0, 1)
effective_b = clamp(wear_coverage * edge_signal * wear_pattern * wear_amount, 0, 1)
```

`du` and `dv` are one texel in the normal map's UV space. The geometric signal MUST increase with
convex curvature and MUST be zero on flat or concave regions. A renderer MUST evaluate wear only
where `edge_signal` is nonzero; it MUST NOT apply wear over a flat surface solely because
`COLOR_1.B` is nonzero. A renderer MUST NOT apply wear where `COLOR_1.B` or `wear_amount` is zero.
With the same instance and pattern, increasing `wear_amount` MUST NOT decrease `effective_b`.
The renderer chooses the pattern implementation and scale; renderers need not produce identical
chip shapes.

The B surface overlay uses the shared surface-overlay operation with `effective_b`. The profile
does not define `color1_b_strength`; the runtime wear amount, vertex mask, edge signal and
procedural pattern determine the overlay. The overlay changes the rendered base color, metallic,
roughness and optional normal response, including when the base color comes from a texture. It does
not modify the source texture or the mesh.

## Blender preview

The ADM Blender add-on approximates the geometric signal using Blender's Cycles pointiness and
local bevel outputs, the normal-map signal with neighboring texture samples, and chipped wear with
procedural noise. Its per-object wear control simulates `wear_amount`; it is not exported to ADM.
The preview does not change the portable PBR fallback or write runtime `dirt_amount` into ADM.
