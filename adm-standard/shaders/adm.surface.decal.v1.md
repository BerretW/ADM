# `adm.surface.decal@1.0.0`

## 1. Identity and version

Shader ID is `adm.surface.decal`; exact SemVer is `1.0.0`.

## 2. Purpose and scope

This profile describes alpha-blended decal geometry such as signs, markings and grime overlays.
It is a mesh material and does not project onto other geometry.

## 3. Parameter table

There are no `shaderParameters`. The profile uses ordinary ADM §8 PBR fields and requires
`alphaMode = BLEND`.

## 4. Mathematical contract

Let source color `Cs` be the material's linear PBR surface color and source alpha `As` be the
effective base-color alpha. Let destination color `Cd` be the already composited linear color.
The output is `Cout = Cs × As + Cd × (1 − As)`. The decal is the source layer.

## 5. Color spaces, units and texture channels

Color factors are linear. Base-color texture RGB is decoded from sRGB before multiplication;
texture alpha is linear, as defined in §8. All values are dimensionless normalized color/coverage
except emissive radiance.

## 6. Input textures

All standard PBR textures are optional and follow ADM §8 for sampling, channels and UV selection.
No screen-space or projected texture input exists.

## 7. Normal and tangent conventions

Normal maps use the ADM §8 tangent-space +Y convention and normal/tangent requirements.

## 8. Alpha and double-sided behavior

The profile requires `alphaMode = BLEND` and uses straight, unpremultiplied alpha exactly as §8.
`doubleSided` follows §8. Sorting, depth testing and intersecting transparent surfaces are outside
the material contract.

## 9. PBR fallback

The ordinary PBR fields completely define this profile's shading. Non-core explicit fallback fields
are required by §8. Readers without this profile render the same core PBR and report
`SHADER_FALLBACK`.

## 10. Animation

There are no shader parameters. Standard `pbrParameter` animation remains available for supported
numeric PBR fields; `alphaMode` is not animated.

## 11. Allowed Blender Shader Nodes

Standard Image Texture, Principled BSDF and Material Output nodes are sufficient. Blender's
transparent render configuration must use straight-alpha blending. The graph is not serialized.

## 12. Reference pseudocode

```text
source = evaluate_core_pbr(material, uv)
assert material.alphaMode == BLEND
output = source.rgb * source.alpha + destination.rgb * (1 - source.alpha)
```

## 13. Conformance tests

An implementation MUST reject this profile unless `alphaMode` is `BLEND`, evaluate the specified
straight-alpha equation in linear space, and preserve the profile ID/version and fallback PBR
fields through export and import.

## 14. Unsupported effects

Screen-space projection, G-buffer/deferred decals, automatic depth bias, order-independent
transparency, alpha-to-coverage and guaranteed ordering of overlapping decal meshes are not defined.
