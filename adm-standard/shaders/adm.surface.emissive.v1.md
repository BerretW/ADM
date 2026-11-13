# `adm.surface.emissive@1.0.0`

## 1. Identity and version

Shader ID is `adm.surface.emissive`; exact SemVer is `1.0.0`.

## 2. Purpose and scope

This profile identifies surfaces whose portable material output contains emissive radiance, such as
signs, LEDs and displays. It uses ADM core PBR fields rather than introducing a duplicate intensity.

## 3. Parameter table

There are no `shaderParameters`. `emissiveFactor` and `emissiveTexture` are the ordinary ADM §8
PBR emissive fields. `emissiveFactor` has type VEC3, finite components `>= 0`, and defaults to zero.

## 4. Mathematical contract

The emissive output is `E = emissiveFactor × T`, componentwise, where `T = linear(texture.rgb)` if
an emissive texture exists, otherwise `[1,1,1]`. At least one component of `emissiveFactor` MUST be
positive. The profile does not change the core BRDF or alpha behavior.

## 5. Color spaces, units and texture channels

`emissiveFactor` is linear RGB. Emissive texture RGB is decoded from sRGB before multiplication as
specified in §8. The texture alpha channel is ignored by emission.

## 6. Input textures

`emissiveTexture` is optional and uses the ADM §8 `textureRef` and UV rules. No other profile-specific
textures are defined.

## 7. Normal and tangent conventions

Normal maps and tangent basis follow ADM §8. Emission is independent of normal and tangent inputs.

## 8. Alpha and double-sided behavior

Alpha mode, alpha cutoff and double-sided behavior are exactly the ADM §8 material rules. Emission
does not override culling or transparency.

## 9. PBR fallback

The ordinary `emissiveFactor` and `emissiveTexture` are both the profile payload and its PBR
fallback. A non-core material MUST still serialize all fallback fields required by §8. Readers
without this profile render core PBR and report `SHADER_FALLBACK`.

## 10. Animation

The profile has no `shaderParameters`. `emissiveFactor` may be animated using the standard
`pbrParameter` channel. Time-dependent effects, including flicker, are not defined by this profile.

## 11. Allowed Blender Shader Nodes

The reference graph uses standard Image Texture, Principled BSDF and Material Output nodes. The
emission color and strength inputs realize the PBR fields. No custom GPU shader or Blender node
serialization is used.

## 12. Reference pseudocode

```text
texture_rgb = [1, 1, 1] if emissiveTexture is absent
              else srgb_to_linear(sample(emissiveTexture, uv).rgb)
emission = emissiveFactor * texture_rgb
shade_core_pbr_with_emission(emission)
```

## 13. Conformance tests

An implementation MUST reject a profile material with no positive `emissiveFactor` component,
verify texture sRGB decoding and componentwise multiplication, and preserve shader ID/version and
PBR fallback values through export and import.

## 14. Unsupported effects

Emission is not required to illuminate other geometry. Bloom, global illumination, exposure,
animated emission and renderer-specific glare are not part of this profile.
