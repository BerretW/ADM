# `adm.surface.interactive@1.0.0`

## Identity and scope

This optional official shader profile marks ordinary mesh primitives as dynamic image surfaces;
[`ADM_interactive_surfaces_v1`](../extensions/ADM_interactive_surfaces_v1.md) supplies their stable
identities and UV bindings. The model contains no runtime resource handle, camera, program or UI.
The engine decides whether and what to display independently for each model instance and surface.
The full runtime capability is `ADM-INTERACTIVE-SURFACES-1`.

## Parameters

| Name | Type | Default | Bounds | Animatable |
|---|---|---:|---|---|
| `brightness` | F32 | `1` | `[0,16]` | yes |
| `emissive_strength` | F32 | `1` | `[0,16]` | yes |
| `enabled` | BOOL | `true` | boolean | no |
| `unlit` | BOOL | `true` | boolean | no |

These are material parameters, shared by every primitive using that material. The existing
`animationId` requirement and `shaderParameter` animation rules apply to the numeric parameters.
To animate the portable fallback independently, use existing `pbrParameter` tracks. As in §18.1,
animation samples are blended and clamped to the listed bounds after each layer; samples MUST be
finite. `enabled=false` selects the authored fallback, making a dark authored fallback suitable for
an off screen. `brightness=0` instead produces black runtime RGB.

## Fallback and runtime image

The explicit portable PBR fallback fields required for every non-core shader are mandatory and
retain their usual meanings. If `enabled` is false, no runtime content is supplied, or the renderer
does not support this exact profile, render the authored PBR fallback unmodified by these parameters
and report the relevant fallback status. Since materials and even a surface's bindings may be shared
or use different materials, an implementation MUST also expose `shaderSupported` and
`shaderFallbackActive` per model-instance/surface/binding, in addition to the existing per-material
status. Its textures may be embedded or, with the required external image extension, external.
Blender's static preview uses this fallback; it does not simulate a camera or runtime UI. A fallback
can itself contain an authored static image.

When enabled and a runtime image is supplied, sample it using the selected binding's UV and
sampling rules. The application supplies a straight-alpha RGBA image with finite RGB and finite alpha
in `[0,1]`, and identifies whether its RGB is sRGB-encoded or scene-linear. For sRGB components
`c` in `[0,1]`, decode each texel before filtering: `c/12.92` if `c<=0.04045`, otherwise
`((c+0.055)/1.055)^2.4`. Do not decode already-linear render targets. Alpha is always linear and
unpremultiplied. Let `C` and `A` be the filtered sample, and `R = brightness * C`. Values of `R` may
exceed 1 and MUST NOT be clamped before the host's ordinary output transform.

* With `unlit=true`, the surface output is linear RGB `R`, independent of ambient and direct light.
  `emissive_strength` is ignored in this mode. This output is not illumination of other geometry.
* With `unlit=false`, use the core PBR BRDF with base RGB `baseColorFactor.rgb * R`, base alpha
  `baseColorFactor.a * A`, and the ordinary fallback metallic, roughness, normal and occlusion
  inputs. Replace the ordinary fallback emission with linear emitted RGB
  `emissive_strength * R`. The authored base-color and emissive textures are not sampled as runtime
  content, and are not multiplied into this runtime result.

In both modes alpha starts as `baseColorFactor.a * A`. Ordinary vertex alpha or the tint-palette alpha
operation, when enabled, applies as described below. Clamp the resulting alpha to `[0,1]` before the
alpha-mode operation. `OPAQUE` ignores alpha, `MASK` discards alpha below `alphaCutoff`, and `BLEND`
uses §8 straight-alpha composition in linear space. `doubleSided`, face culling and back-face normal
handling are unchanged. Tone mapping, bloom and lighting other objects are host responsibilities.

## Vertex controls and other features

Without `ADM_vertex_control_v1`, ordinary `COLOR_0` multiplies the PBR base RGBA as in the core
standard; absent color has the neutral value `(1,1,1,1)`. In unlit mode only its alpha affects alpha,
not emitted RGB. With that required extension,
its palette operation applies to the runtime PBR base RGBA, including alpha, in its existing order.
The normal, reflectivity and wetness controls affect the lit BRDF only; they MUST NOT darken or
otherwise multiply emitted RGB or the final unlit pixel. In unlit mode they have no visible RGB
effect. In lit mode the palette, normal, reflection and wetness controls are applied exactly once
to the PBR terms, while emission remains `emissive_strength * R`. These rules do not reinterpret any
channel. `COLOR_1` R/G/B/A are reserved and ignored by this profile; the absent default is
`(0,0,0,0)`. Existing extension declaration, palette sampling and animation rules remain unchanged.

Node transforms, morphs, skinning, other material slots and external or embedded fallback textures
retain their existing ADM semantics. Renderers MUST NOT silently substitute another shader version;
an unsupported optional version uses its PBR fallback and reports `SHADER_FALLBACK`.
