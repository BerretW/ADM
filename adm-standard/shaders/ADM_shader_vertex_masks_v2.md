# ADM Core shader profiles 2.0.0: `COLOR_1`

Status: normative shader profile contracts for ADM 1.0.

These are additive, versioned shader profiles carried by the existing ADM 1.0 material schema.
They do not change the ADM container version, the `ADM_vertex_control_v1` `COLOR_0` contract, or
the meaning of any profile at `1.0.0`. A reader resolves a shader by the exact `(id, version)` pair.
`adm.surface.interactive@1.0.0` is intentionally unchanged and has no `COLOR_1` semantics.

`COLOR_1` is available only when `ADM_vertex_control_v1` is listed in both `extensionsUsed` and
`extensionsRequired`. It is an optional normalized `U8 VEC4` or `F32 VEC4` attribute, linearly
interpolated over each triangle. Values MUST be finite and in `[0,1]`. An absent attribute is
`(0,0,0,0)`. Vertex data is linear; readers MUST NOT apply sRGB conversion to masks.

## Shared operations

For channel `c` and its profile parameter `color1_<c>_strength`:

```text
mask_c = clamp(COLOR_1.c, 0, 1)
effective_c = clamp(mask_c * clamp(strength_c, 0, 1), 0, 1)
blend(a, b, t) = a * (1 - t) + b * t
```

All v2 strength parameters default to `1`. Channel effects are evaluated in R, G, B, A order.
Surface overlays operate on the result of earlier channels. The profile's ordinary shader
operations are evaluated first; `COLOR_1` is applied next; the existing `COLOR_0` tint, normal,
reflectivity and wetness operations are applied last. Neither operation modifies the vertex data.

### Surface overlay

An overlay channel has `color1_<c>_color` (linear `VEC3`), `color1_<c>_metallic`,
`color1_<c>_roughness`, and optional `color1_<c>_texture` and `color1_<c>_normal` texture
parameters. The factors default to the profile-specific values in the registry. Texture defaults
are absent.

If an albedo texture is present, its RGB is decoded from sRGB to linear and multiplied by the
linear color factor. If absent, the color factor is the complete overlay albedo. Metallic and
roughness targets are linear scalars in `[0,1]`. For the current base color `C`, metallic `M`,
roughness `R`, and alpha `A`:

```text
C' = blend(C, overlayAlbedo, effective_c)
M' = blend(M, overlayMetallic, effective_c)
R' = blend(R, overlayRoughness, effective_c)
A' = A                                  when the albedo texture is absent
A' = blend(A, A * textureAlpha, effective_c) otherwise
```

Texture alpha is linear and is not premultiplied. An optional normal texture is linear tangent
space: decode `n = 2 * RGB - 1`, transform it to the surface frame, then set
`N' = normalize(blend(N, n, effective_c))`. If the normal texture is absent, the normal is
unchanged. Overlay effects do not change emission.

### Scalar, color and coverage operations

`factor` channels have `color1_<c>_value` and set their named material input with
`blend(current, value, effective_c)`. Values follow the target input bounds in the registry:
normalized surface inputs use `[0,1]`; emission strength uses `[0,4]`.

`multiply` channels have `color1_<c>_value` in `[0,4]` and compute
`current * blend(1, value, effective_c)`. `color` channels have a linear `VEC3`
`color1_<c>_color` and blend it into the named color input. `coverage` channels multiply their
named output by `effective_c`. A missing `COLOR_1` therefore disables a coverage-only effect.

`contrast` channels have `color1_<c>_value` in `[0,4]` and compute:

```text
target = clamp(0.5 + (baseColor - 0.5) * value, 0, 1)
baseColor' = blend(baseColor, target, effective_c)
```

`normal` channels have an optional linear tangent-space `color1_<c>_normal`. When absent they
have no effect; when present they use the normal operation defined above.

### Four-layer weights

`adm.pbr.layered@2.0.0` and `adm.terrain.four_layer@2.0.0` use R/G/B/A as layer 0/1/2/3 weights.
Each raw weight is `clamp(COLOR_1.channel * color1_<channel>_strength, 0, 1)`. For terrain,
an optional linear `blend_mask` multiplies the corresponding RGBA weight. For layered PBR there
is no `blend_mask` texture. The four results are normalized by their sum. If their sum is zero,
the weights are exactly `(1,0,0,0)`.

Each layer has a linear `VEC4` base-color factor, scalar metallic and roughness factors, a linear
`VEC3` emissive factor, and optional sRGB albedo and linear tangent-space normal textures. Missing
textures use the factors; a missing normal is `(0,0,1)`. Texture RGB multiplies the base-color RGB;
texture alpha multiplies the base-color alpha. The renderer computes weighted sums of base color,
alpha, metallic, roughness and emission. It computes the weighted sum of decoded normals and
normalizes that result; if the result has zero length it uses `(0,0,1)`. Thus all layers use the
same weights and no layer is implicitly overlaid after another.

For terrain, each layer also has optional linear `layer{i}_metallic_texture` and
`layer{i}_roughness_texture` maps. Their red channels multiply the respective factors before
weighting; absent maps leave the factors unchanged. Each uses its own `texCoord` and the layer's
`uv_scale`. These additional maps do not apply to `adm.pbr.layered@2.0.0`.

`adm.pbr.layered@1.0.0` retains its existing `ADM_material_layers_v1` two-layer contract and does
not use `COLOR_1`.

## Profile contracts

`surface` means the complete PBR overlay above. Its default linear color, metallic and roughness
are encoded by the correspondingly named profile parameters in `registry.json`. `factor`,
`multiply`, `color`, `coverage`, `contrast`, `normal`, and `layer` use the shared operations above.

| Exact profile | R | G | B | A |
|---|---|---|---|---|
| `adm.pbr.metallic_roughness@2.0.0` | Detail blend (`surface`) | Dirt mask (`surface`) | Edge wear (`surface`) | Clearcoat (`factor`, Coat Weight) |
| `adm.pbr.layered@2.0.0` | Layer 1 (`layer 0`) | Layer 2 (`layer 1`) | Layer 3 (`layer 2`) | Layer 4 (`layer 3`) |
| `adm.surface.cutout@2.0.0` | Cutout variation (`factor`, Alpha) | Edge fade (`factor`, Alpha) | Detail mask (`surface`) | Damage (`surface`) |
| `adm.surface.emissive@2.0.0` | Emission intensity (`factor`, Emission Strength) | Color blend (`color`, Emission Color) | Flicker influence (`multiply`, Emission Strength) | Emissive coverage (`coverage`, Emission Strength) |
| `adm.surface.decal@2.0.0` | Opacity (`factor`, Alpha) | Dirt blend (`surface`) | Wear (`surface`) | Detail blend (`surface`) |
| `adm.surface.glass@2.0.0` | Local opacity (`factor`, Alpha) | Frosting (`factor`, Roughness) | Dirt (`surface`) | Tint variation (`color`, Base Color) |
| `adm.surface.foliage@2.0.0` | Translucency (`factor`, Subsurface Weight) | Color variation (`surface`) | Dryness (`factor`, Roughness) | Detail mask (`surface`) |
| `adm.terrain.four_layer@2.0.0` | Layer 1 (`layer 0`) | Layer 2 (`layer 1`) | Layer 3 (`layer 2`) | Layer 4 (`layer 3`) |
| `adm.vehicle.paint@2.0.0` | Metallic flakes (`factor`, Metallic) | Dirt (`surface`) | Scratches (`surface`) | Clearcoat (`factor`, Coat Weight) |
| `adm.character.skin@2.0.0` | Subsurface (`factor`, Subsurface Weight) | Detail normals (`normal`) | Roughness variation (`factor`, Roughness) | Scar/detail (`surface`) |
| `adm.animal.fur@2.0.0` | Fur density (`factor`, Anisotropic) | Color variation (`surface`) | Roughness variation (`factor`, Roughness) | Detail (`normal`) |
| `adm.animal.feather@2.0.0` | Color variation (`surface`) | Iridescence (`color`, Emission Color) | Detail (`normal`) | Wear (`factor`, Roughness) |
| `adm.animal.scales@2.0.0` | Scale contrast (`contrast`, Base Color) | Reflectivity variation (`factor`, Specular IOR Level) | Roughness variation (`factor`, Roughness) | Detail (`surface`) |
| `adm.building.concrete@2.0.0` | Dirt (`surface`) | Damage (`surface`) | Moisture stains (`surface`) | Secondary texture (`surface`) |
| `adm.building.brick@2.0.0` | Mortar variation (`surface`) | Dirt (`surface`) | Wear (`surface`) | Moss (`surface`) |
| `adm.building.roof@2.0.0` | Dirt (`surface`) | Wear (`surface`) | Moss (`surface`) | Secondary texture (`surface`) |
| `adm.nature.bark@2.0.0` | Moss (`surface`) | Cracks/detail (`normal`) | Color variation (`surface`) | Secondary texture (`surface`) |
| `adm.nature.rock@2.0.0` | Moss (`surface`) | Dirt (`surface`) | Snow (`surface`) | Secondary texture (`surface`) |
| `adm.nature.water@2.0.0` | Foam (`surface`) | Depth tint influence (`color`, Base Color) | Surface variation (`factor`, Roughness) | Shoreline (`factor`, Alpha) |
| `adm.surface.fabric@2.0.0` | Fiber detail (`normal`) | Dirt (`surface`) | Wear (`surface`) | Secondary texture (`surface`) |

The glass, skin, foliage, fur, feather, scale and fiber results are portable surface approximations.
Fur density changes the Principled anisotropic response; it does not create geometry or require a
hair renderer. Feather iridescence is represented by the registered emission-color blend
approximation and does not require ray tracing. A renderer MUST implement the operations above for
a profile it declares supported; it MUST NOT infer a channel meaning from another version or profile.
