# `ADM_interactive_surfaces_v1`

This normative extension identifies dynamic display surfaces on ordinary renderable geometry.
Its exact schema version is `1.0.0`; its associated optional runtime capability is
`ADM-INTERACTIVE-SURFACES-1`. It does not define an entity, collider, UI, camera, input system,
GPU resource or executable shader.

## Manifest schema and identity

The extension occurs once, at the model manifest's top level:

```json
{
  "extensionsUsed": ["ADM_interactive_surfaces_v1"],
  "extensions": {
    "ADM_interactive_surfaces_v1": {
      "version": "1.0.0",
      "surfaces": [
        {
          "surfaceId": "main_display",
          "aspectRatio": 1.7777778,
          "bindings": [{"node": 0, "primitive": 1, "texCoord": 0}]
        }
      ]
    }
  }
}
```

This is a manifest fragment; its node and primitive indices must resolve in the containing model.
`surfaces` and each `bindings` are non-empty arrays. A surface has required `surfaceId` and
`bindings` and optional `aspectRatio`. An ID is 1..64 ASCII characters matching
`[a-z][a-z0-9_]*`; IDs are unique across all surfaces in the model, including all scenes. Comparison
is byte-for-byte, case-sensitive. `aspectRatio`, if present, is a finite width/height ratio in
`(0,1000]`. It is rounded to IEEE-754 binary32 using round-to-nearest, ties-to-even and MUST remain
greater than zero after rounding. It is advisory, never a request to crop or rescale UVs. Absence
means unspecified.
Each binding has exactly the required members `node`, `primitive`, and `texCoord`. As elsewhere in
ADM, objects MAY contain `extras` and declared `extensions`; no other members are allowed.

`node` indexes `nodes`. That node MUST reference a mesh. `primitive` indexes that mesh's
`primitives`; the pair `(node, primitive)` occurs in exactly one binding in the entire model.
The primitive MUST have a material with the exact shader identity
`adm.surface.interactive@1.0.0`, and MUST provide the `F32 VEC2` attribute `TEXCOORD_0` or
`TEXCOORD_1` selected by integer `texCoord` 0 or 1. Every primitive using this exact shader on a
mesh-bearing node MUST have exactly one binding. Invalid references and missing UVs MUST be rejected;
readers MUST NOT infer them. A surface MAY have several bindings, and each primitive MAY contain any
number of triangles. This permits a screen to span materials, nodes, and triangle groups while
giving it one unique ID. Two nodes may reference the same mesh and bind its primitives to different
IDs. Index values are file-local references and may change on re-export; the `surfaceId` is the
stable authored identity. Node names and Blender material-slot positions have no identity semantics.

Identity on the material alone is insufficient: a material and its shader may be shared by multiple
independently addressed screens. The node/primitive binding also distinguishes two nodes sharing one
mesh. At runtime the key is `(model instance, surfaceId)`, so separate instances of one asset may
show different content. Neither model-instance identity nor runtime content is serialized by ADM.

`extensionsUsed` MUST declare this extension when its data is present. It MAY be listed in
`extensionsRequired` when discarding the binding metadata is unacceptable. A core reader MAY ignore
an unknown optional extension and display the portable PBR fallback; it MUST reject an unknown
required extension. A reader implementing this extension validates and exposes the bindings even if
it does not render runtime content. A reader MUST NOT interpret this v1 binding as another shader
version. An otherwise unbound unknown optional shader version follows the ordinary PBR fallback
rules, not an assumed v1 implementation.

## UV, projection and hit testing

The selected UV is per vertex, interpolated over each triangle; ADM's image origin is top-left,
`U` increases right and `V` increases down. `[0,1]` spans the full image edges. Runtime sampling uses
the base image level and bilinear filtering of decoded scene-linear RGB and linear alpha, with
`CLAMP_TO_EDGE` on both axes, independently of any authored fallback texture's sampler. For an image
of width `W` and height `H`, texel `(i,j)` has center `((i+0.5)/W,(j+0.5)/H)`. Clamp the input UV,
let `x=u*W-0.5`, `y=v*H-0.5`, and linearly interpolate the four texels at the floor/next integer
indices using the fractional parts of `x` and `y`; clamp each texel index to the image edge.
Values outside `[0,1]` are permitted and clamp to the nearest edge. No implicit UV flip, rotation,
aspect correction or screen-space projection is performed: intentionally reversed UVs mirror the
image. Overlapping UV islands sample the same content; the author is responsible for avoiding
ambiguity when that is not desired. Curved and multi-triangle geometry use the same rules.

For a ray hit, the engine chooses the actual hit triangle and uses its node/primitive binding.
Given barycentric weights `(w0,w1,w2)` on that deformed triangle, interpolate
`uv = w0*uv0 + w1*uv1 + w2*uv2`, then clamp each component to `[0,1]` for content coordinates.
For a content image of integer width `W>0`, height `H>0`, top-left integer pixel coordinates are
`x=min(floor(u*W),W-1)` and `y=min(floor(v*H),H-1)`. Rasterization uses perspective-correct UV
interpolation. Overlapping geometry is resolved by the host's ray-hit selection; ADM does not
specify a raycaster or events. Node, skin and morph transforms affect geometry and the hit triangle,
not the stored UV coordinates. `doubleSided` and face orientation retain their core meanings.

## Conformance

`ADM-INTERACTIVE-SURFACES-1` means the implementation validates and exposes this exact schema and
applies the runtime-content contract in
[`adm.surface.interactive@1.0.0`](../shaders/adm.surface.interactive.v1.md), including animation,
UV, alpha, color and fallback behavior. Supplying a runtime image, UI, camera, raycast or interaction
logic is an application decision, not an ADM requirement. Advertising ordinary `ADM-CORE-1` or
`ADM-SHADER-CORE-1` alone does not claim this capability.
