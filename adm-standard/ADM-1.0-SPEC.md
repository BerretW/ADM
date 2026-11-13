# ADM 1.0 — Apparatus Drawable Model & Animation Standard

**Status:** Draft 0.4 revision P4 — normative humanoid retarget/IK rules and specification-gap dispositions; **NOT ratified**  
**Date:** 2026-11-13  
**Formats:** `.adm` (drawable model), `.adm_anim` (standalone animation library)  
**Version:** 1.0 (`major=1, minor=0`) for each independent file format  
**Compatibility:** intentionally incompatible with all legacy ADM / ADS / `.ads_anim` variants  
**Intended license:** specification CC0-1.0; reference implementations preferably MIT or Apache-2.0  
**Conformance:** this draft is not certified; §25 and §30 define the required tests, including streaming/security tests. The published example validator checks a subset only.

> **Normative rule:** ADM describes reusable *model assets*, NOT game entities. It standardizes appearance, standardized shader bindings and shader-parameter animation, rest transforms, articulation, visual animation, morph shapes, attachment markers, LOD, geometric collision descriptors, and metadata. It does not define NPC AI, inventory, network replication, vehicle drivetrain, damage logic, scripts, character controllers, game physics, or audio playback. An application supplies these systems.
>
> **Draft restriction:** This document supersedes the earlier 1.0 draft completely. The last section identifies remaining profile/testing work that MUST be closed before a final 1.0 release. No old files are grandfathered in.

## 1. Document scope and interpretation

The terms **MUST**, **MUST NOT**, **SHOULD**, **MAY** express requirements. Field names are case-sensitive. JSON arrays preserve order and are zero-indexed. Data not explicitly permitted by a structure is invalid, except namespaced `extensions` and non-normative `extras`. A reader MUST reject malformed data rather than silently repairing it. Implementations MAY provide a separately labelled import-repair mode.

**Interoperability objective:** independently written Blender exporter, C++/Rust loader, and viewer MUST agree on byte decoding, node topology and matrices, sampled animation channels, retarget results, morph weights, and IK target positions within the numerical tolerances in §25. Engines may choose different rasterizers, physics solvers, and character controllers; these are not file conformance criteria.

**Self-contained model by default:** `.adm` is self-contained for its geometry, skeleton, morph targets, materials and images. It may contain multiple mesh primitives and nodes. Models of a building, animal or car can be complete in one file. The generic model/asset layer does NOT require references to other `.adm` files. Animations are explicitly in separate `.adm_anim` libraries and may be shared by models. Loading libraries is an application responsibility.

**Mandatory reader capabilities:** `ADM-CONTAINER-1` validates/streams the chunk container and `ADM-CORE-1` validates model semantics; `ADM-ANIM-1` parses/evaluates animation libraries; `ADM-HUMANOID-1` supports standardized humanoid retarget; `ADM-IK-1` supports two-segment IK; `ADM-FACE-ARKIT52-1` supports the facial channel profile; `ADM-SHADER-CORE-1` supports standard PBR shader binding and portable PBR parameter animation; `ADM-SHADER-LAYERED-1` supports deterministic multilayer material evaluation; `ADM-TEX-KTX2-1` and `ADM-TEX-DDS-1` decode the GPU texture container subsets of §8.6. Readers MUST advertise the profile(s) they implement, not claim support for data that they silently drop. Writers need not generate every optional model feature, but generated data MUST conform.

**References adopted, not embedded wholesale:** glTF 2.0 mathematics / texture conventions, VRM 1.0 humanoid bone roles and T-pose semantics, Apple ARKit facial coefficient identifiers. Their foreign container formats do **not** replace ADM's on-disk layout.


## 2. Primitive types and math

| Type | Wire representation | Notes |
|---|---|---|
| `u8` | 1 octet | 0–255 |
| `u16` | 2 octets, little endian | unsigned |
| `u32` | 4 octets, little endian | unsigned |
| `u64` | 8 octets, little endian | unsigned |
| `i16` | 2 octets, little endian | two's complement |
| `f32` | IEEE-754 binary32, little endian | NaN and ±Infinity forbidden |
| JSON integer | base-10 integer lexical form | no fractional/exponent notation for integer-valued fields; range 0..2^32-1 unless otherwise specified |
| JSON number | finite JSON number | converted to binary64 for semantics; no NaN/Infinity |
| string | JSON UTF-8 string | valid Unicode scalar values only; unpaired surrogate forbidden |
| `vec2` | JSON `[x,y]` | finite numbers |
| `vec3` | JSON `[x,y,z]` | finite numbers |
| `vec4` | JSON `[x,y,z,w]` | finite numbers |
| `quat` | JSON `[x,y,z,w]` | normalized, right-handed rotation |
| `mat4` | 16-element JSON array | column-major: `m[col*4+row]` |

**Coordinates:** right-handed; +X right, +Y up, +Z toward viewer / backward; forward direction is **−Z**. Units: **meters**, **seconds**, **radians** (where angles occur). `POSITION`, `NORMAL`, tangent xyz and translations use this coordinate system. Front faces are **counter-clockwise as viewed from the front**. A triangle `[a,b,c]` is front-facing when its normal follows `(b-a) × (c-a)`. Texture coordinates: `(0,0)` is the **top-left** of an image, U grows rightward, V downward. Importers/exporters MUST transform their native coordinates, winding and UVs; they MUST NOT silently relabel their native convention as ADM.

**Matrices and hierarchy:** column vectors, post-multiplication. Local-to-world transform of child `C` is `W(C) = W(parent) × L(C)`; root parent world is identity. If node specifies TRS, `L = T × R × S`. A node MAY specify **either** `matrix` **or** any of `translation`, `rotation`, `scale`, never both. Defaults: translation `[0,0,0]`, rotation `[0,0,0,1]`, scale `[1,1,1]`. Every quaternion MUST have length between `1−1e-4` and `1+1e-4`; readers MUST normalize before use. Rotations use the Hamilton quaternion convention and act on column vectors. Normals transform with the inverse transpose of the upper-left 3×3; if non-invertible, usage requiring normals is invalid. Animation targets MUST use TRS nodes; a matrix node MUST NOT be targeted by animation. For skinning, node world matrices and inverse bind matrices MUST be invertible. Negative scale is permitted on unskinned nodes, with front-face orientation adjusted by determinant sign; skinned joints MUST have positive scales to avoid nonunique decomposition in 1.0.

## 3. Native chunked binary container (byte-exact, replaces Draft 0.3)

**BREAKING CHANGE:** The earlier 32-byte header and contiguous BIN region are REMOVED. A Draft 0.4 `.adm` or `.adm_anim` MUST use the header and chunk directory below. This draft is intentionally not compatible with Draft 0.3. Integer fields are unsigned little-endian. The manifest is plain UTF-8 JSON, independently readable. All offsets refer to byte positions from the start of the file. The file MUST NOT include unaddressed bytes except zero padding for 16-byte alignment between regions.

### 3.1 Fixed header (64 bytes)

| Offset | Size | Type | Meaning |
|---:|---:|---|---|
| 0 | 4 | ASCII | `ADM0` (model) OR `AMA0` (animation library) |
| 4 | 2 | u16 | major = 1 |
| 6 | 2 | u16 | minor = 0 |
| 8 | 4 | u32 | headerSize = 64 |
| 12 | 4 | u32 | flags = 0 |
| 16 | 8 | u64 | fileSize = exact physical length |
| 24 | 8 | u64 | manifestOffset = 64 |
| 32 | 8 | u64 | manifestLength = UTF-8 JSON byte length, at least 2 |
| 40 | 8 | u64 | directoryOffset = `align16(64+manifestLength)` |
| 48 | 4 | u32 | chunkCount (0..65535) |
| 52 | 4 | u32 | directoryEntrySize = 80 |
| 56 | 8 | u64 | reserved = 0 |

`align16(x) = (x+15) & ~15` evaluated with checked 64-bit arithmetic. The directory occupies exactly `80*chunkCount` bytes. It begins immediately after the aligned manifest; all intervening bytes MUST be zero. Data begins at or after `align16(directoryOffset + 80*chunkCount)`. Empty (metadata-only) animation libraries MAY contain no data chunks. A reader MUST reject unknown major/minor versions, flags, reserved values, noncanonical region offsets, overlapped regions and lengths extending beyond fileSize. Maximum interoperable manifest length is 16 MiB. Producers MUST write JSON object text without BOM, duplicate keys or non-finite numbers. JSON order is not normative. JSON metadata MUST be parseable without fetching any chunk payload.

### 3.2 Fixed directory entry (80 bytes each)

| Entry offset | Size | Type | Meaning |
|---:|---:|---|---|
| 0 | 8 | u64 | chunkId; nonzero, unique, strictly increasing |
| 8 | 4 | ASCII | chunkType (`GEOM`, `ANIM`, `IMAG`, `DATA` or future FourCC) |
| 12 | 4 | u32 | entryFlags: bit0 = required; other bits = 0 |
| 16 | 4 | u32 | codec: 0 = RAW; 1 = ZSTD frame |
| 20 | 4 | u32 | reserved = 0 |
| 24 | 8 | u64 | fileOffset of stored bytes; 16-byte aligned |
| 32 | 8 | u64 | storedLength, encoded bytes |
| 40 | 8 | u64 | rawLength, bytes after decoding |
| 48 | 32 | octets | SHA-256 of uncompressed payload, canonical byte order |

Chunk IDs MUST be in `[1, 4294967295]` (u32-compatible for exact JSON integer references). RAW requires `storedLength == rawLength`. ZSTD uses one independent, complete standard Zstandard frame per chunk, without dictionaries, skippable frames or trailing bytes; this codec is optional capability `ADM-CODEC-ZSTD-1`. An unsupported codec on a **required** chunk or on any chunk needed for selected output causes `ADM_ERR_UNSUPPORTED_CODEC`; unused optional chunks may be skipped. Readers MUST verify SHA-256 after decoding a requested chunk, before consuming it; an unrequested chunk MAY remain unverified until used. The hard interoperable `rawLength` cap is 256 MiB per chunk, requiring larger assets to be split. Zero-byte chunks are forbidden. Directory entries MUST be ordered by chunkId; payload byte ranges MUST NOT overlap and MUST be ordered by `fileOffset` ascending, although chunkId need not match physical order. Padding between payloads MUST be zero. `fileSize` MUST match actual file size. Bytes after the final payload (except zero alignment padding to fileSize) are forbidden. Unknown FourCC entries may be ignored only if optional and unreferenced; unknown required FourCC entries cause `ADM_ERR_UNSUPPORTED_CHUNK`.

A valid reader MUST enforce checked addition/multiplication before allocating, decompressing or seeking. Producer SHOULD place lower-LOD geometry and PBR fallback textures before high-detail chunks, but data ordering never changes semantics. SHAs provide integrity, **not authentication or publisher trust**.

## 4. JSON manifest: top-level schema

Required top-level members: `asset`, `nodes`, `scenes`, `scene`, `meshes`, `accessors`, `bufferViews`. The `chunkDependencies` member is optional as defined in §5. Optional members (default empty arrays where an array is expected): `materials`, `samplers`, `images`, `textures`, `shaderDefinitions`, `skins`, `colliders`, `lodGroups`, `attachments`, `skeletonProfiles`, `facialProfiles`, `expressions`, `ikChains`, `componentRoles`, `chunkDependencies`, `streamHints`, `physicalMaterials`, `hitboxes`, `modelComponents`, `modelProfiles`, `extensionsUsed`, `extensionsRequired`, `extensions`, `extras`. Embedded animation clips are NOT allowed in `.adm`; animations reside in `.adm_anim`. `asset` is `{ "generator"?: string, "copyright"?: string }` with an optional string `generator` and `copyright`. File version comes **only from binary header**; `asset` MUST NOT duplicate a version.

A missing optional array is equivalent to `[]`. Unknown top-level fields are invalid except namespaced members within `extensions` and arbitrary JSON inside `extras`. `extras` MUST be a JSON object and MUST NOT change normative behavior. `extensionsUsed` and `extensionsRequired` are arrays of unique strings matching `[A-Za-z][A-Za-z0-9_]*`; `extensionsRequired` MUST be a subset of `extensionsUsed`. An implementation MUST reject a file containing an unknown required extension, and MAY ignore an unknown optional extension. Extension data is held in `extensions` objects keyed by those names and MUST have a separately published, versioned specification. An extension MUST NOT reinterpret core fields. A writer MUST NOT use `extras` as an undocumented substitute for required core semantics.

All cross-references by index MUST refer to an existing element of the named array. Strings representing logical names are UTF-8; names MAY repeat unless uniqueness is explicitly required. All absent optional object fields take the defaults stated below, never guessed defaults.

## 5. Chunk-addressed buffer views, accessors and dependencies

The Draft 0.3 single BIN region no longer exists. `bufferViews` is an array of `{ "chunkId":u32, "byteOffset":u32, "byteLength":u32 }` (all required), with `chunkId` identifying a directory entry. Views index the **decompressed** chunk payload. `byteOffset + byteLength <= rawLength` must be checked with widened arithmetic. A view MUST reference a known `GEOM`, `ANIM`, `DATA`, or `IMAG` directory chunk; image-only views MUST reference `IMAG`, geometry accessor views SHOULD reference `GEOM`, and animation time/key views MUST reference `ANIM`. Two buffer views MAY refer to one chunk; they MAY overlap if they intentionally share identical data. No implicit allocation across chunks is allowed. If a referenced chunk codec is unavailable, the view is unavailable and the consuming feature MUST report the unsupported capability rather than guess.

`accessors` is an array of:

```
{ "bufferView":u32, "byteOffset"?:u32, "componentType":"F32"|"U32"|"U16"|"U8",
  "type":"SCALAR"|"VEC2"|"VEC3"|"VEC4"|"MAT4", "count":u32,
  "normalized"?:bool }
```

Accessor byteOffset defaults to 0, component sizes are F32/U32=4, U16=2, U8=1; element component counts 1/2/3/4/16. Packed, noninterleaved storage only. Normalized unsigned components divide by max representable value. The accessor spans exactly `count*componentCount*componentSize` bytes within its view; start offset must meet component-size alignment. Readers MUST reject overflows, unaligned accessors, wrong types and non-finite F32 values. Matrices are column-major. An image view is consumed as encoded bytes directly, not through an accessor.

`chunkDependencies` is an optional array of `{ "chunkId":u32, "requires":[u32,...] }`. Each chunkId may appear at most once, with all requires unique, nonzero, present, and not equal to chunkId; cycles are invalid. Missing entry means no dependencies. Dependency edges indicate prerequisite data for correct interpretation and imply prefetch-before-use, not automatic entity loading. To satisfy a request for chunk C, a loader computes its transitive dependency closure, then may fetch/decode chunks in any topological order. Reference metadata in the manifest remains authoritative; `chunkDependencies` MUST NOT hide references. **A required geometry chunk may depend on other required chunks but MUST NOT require unsupported optional feature chunks to decode.** Optional higher-detail chunks MUST NOT be necessary to interpret mandatory lower-detail fallbacks.

`streamHints`, optional, is an array of `{ "chunkId":u32, "priority":u32 }` with unique chunk IDs and priorities 0..255, where 0 is highest priority. It is advisory only and MUST NOT affect rendered meaning. A producer SHOULD use it for LOD0/LOD1 and fallback material resources, but an application controls scheduling. Chunk IDs are stable **within the asset version**, not globally stable across repacking; durable cross-asset binding uses semantic IDs (e.g. attachment names, library IDs and material animation IDs), never file offsets or chunk IDs.

**Lazy loading contract:** Reading the header, directory and manifest MUST NOT require reading any chunk payload. Resolving a requested accessor, texture or animation sampler may fetch only the associated chunk and the transitive chunk dependency closure. Reader MUST detect integrity errors on used chunks and return `ADM_ERR_HASH_MISMATCH` rather than silently substitute data. It MUST report `ADM_ERR_RESOURCE_LIMIT` for configured limits. A browser/viewer MAY preload extra chunks for convenience; an ADM implementation claiming `ADM-STREAM-1` MUST expose partial-loading APIs and pass §25 streaming tests.

## 6. Scenes and node tree

`scenes`: non-empty array of `{ "name"?: string, "nodes": [u32...] }`; `scene`: required u32 index of default scene. `nodes` is an array of:

```
{ "name"?: string, "children"?: [u32...], "translation"?: vec3,
  "rotation"?: quat, "scale"?: vec3, "matrix"?: mat4,
  "mesh"?: u32, "skin"?: u32, "extras"?: object, "extensions"?: object }
```

A node is a transform and may refer to a mesh and skin. A node with morphable mesh MAY additionally contain `weights:[number...]` whose length equals the mesh target count; weights MUST be finite within [0,1]. If `skin` is set, `mesh` MUST also be set. All nodes MUST be reachable from exactly one scene root in the file; scene root sets MUST be disjoint in v1.0. Every node MUST have at most one parent. No cycles, duplicate child indices, or roots that also occur as children. A node MAY have children and a mesh simultaneously. A scene root MUST NOT have a parent. Node names are display labels, not identity: indices are authoritative. A writer SHOULD provide stable human-readable names.

## 7. Meshes and primitive vertex attributes

`meshes`: array of `{ "name"?: string, "primitives": [primitive, ...], "targetNames"?: [string...], "weights"?: [number...] }` with at least one primitive. A primitive:

```
{ "attributes": { "POSITION": accessorIndex, "NORMAL"?: accessorIndex,
                  "TANGENT"?: accessorIndex, "TEXCOORD_0"?: accessorIndex,
                  "TEXCOORD_1"?: accessorIndex, "COLOR_0"?: accessorIndex,
                  "JOINTS_0"?: accessorIndex, "WEIGHTS_0"?: accessorIndex },
  "indices": accessorIndex, "material"?: u32, "targets"?: [targetObject...] }
```

`POSITION` and `indices` are required. There is exactly one topology in ADM 1.0: **triangles**. Non-indexed triangles, lines, points, triangle strips/fans, quads and n-gons MUST be triangulated by the exporter. Index accessor MUST be SCALAR U16 or U32, non-normalized, `count>=3` and divisible by 3. Indices MUST each be `< vertexCount`. A primitive MUST have `POSITION` as F32 VEC3 and `count>=3`. All present vertex attributes MUST have the same count as POSITION. Allowed types:

| Semantic | Accessor type | Meaning |
|---|---|---|
| POSITION | F32 VEC3 | local-space meters |
| NORMAL | F32 VEC3 | unit normal, local space |
| TANGENT | F32 VEC4 | normalized xyz tangent, w = +1 or −1 |
| TEXCOORD_0, TEXCOORD_1 | F32 VEC2 | UV coordinates, top-left convention |
| COLOR_0 | U8 normalized VEC4 **or** F32 VEC4 | linear RGBA vertex color |
| JOINTS_0 | U8/U16 non-normalized VEC4 | indices into associated skin's `joints` array |
| WEIGHTS_0 | F32 VEC4 **or** U8/U16 normalized VEC4 | 4 skin influences |

Unknown attribute semantics are invalid in CORE 1.0. JOINTS_0 and WEIGHTS_0 MUST occur together. Their weights MUST be nonnegative and finite, with sum within `1±1e-3`; readers MUST renormalize. Every nonzero-weight joint index MUST be `< skin.joints.length` for each node using that mesh. A mesh containing JOINTS/WEIGHTS MUST be used only by nodes providing `skin`; an unskinned mesh MUST NOT be used by nodes providing `skin`. Each triangle's three position indices MAY repeat, yielding a zero-area triangle; exporters SHOULD avoid this and a validator SHOULD warn. NORMAL and TANGENT vectors MUST have length `1±1e-3`; readers MUST renormalize. If NORMAL is absent, reader MUST generate **per-face flat normals** from winding; if TANGENT is absent and material needs a normal map, reader MUST generate per-triangle tangents or report normal-map shading unsupported (no silent arbitrary tangent frame). For consistency, a writer SHOULD always export normals/tangents when normal mapping is used. Degenerate UVs MAY prevent tangent derivation.

Optional `material` references `materials`; absent means fallback opaque neutral gray linear RGBA `[0.5,0.5,0.5,1]`, metallic 0, roughness 1, doubleSided false.

## 8. Materials, samplers, images and textures

**Shader binding rule:** A material is data, not executable code. It MUST NOT contain embedded GLSL/HLSL/SPIR-V, platform-specific bytecode, Blender nodes, implicit engine shader names or script code. Every material MAY select a published shader definition by ID and exact SemVer version using `shader`. If omitted, its shader is `adm.pbr.metallic_roughness@1.0.0`. The PBR fields defined below are the always-valid **fallback material**, and remain mandatory to interpret even when the chosen shader is unknown. **Any material selecting a shader other than `adm.pbr.metallic_roughness@1.0.0` MUST explicitly serialize `baseColorFactor`, `metallicFactor`, `roughnessFactor`, `emissiveFactor`, and `alphaMode` as its portable fallback; omitting one is `ADM_ERR_MISSING_PBR_FALLBACK`.** Ordinary core PBR materials retain the defaults below. For a layered/custom shader, these fields MUST be valid irrespective of whether the renderer supports its advanced shader. Material objects MAY add `shader`, `shaderParameters`, and `animationId` only as specified in §8.1–§8.5. A viewer MUST implement `adm.pbr.metallic_roughness@1.0.0`; it MAY implement other registered shaders. Custom shaders never imply installation, download, compilation or execution of arbitrary code.

`materials`: array of objects:

```
{ "name"?: string,
  "baseColorFactor"?: [r,g,b,a], "baseColorTexture"?: textureRef,
  "metallicFactor"?: number, "roughnessFactor"?: number,
  "metallicRoughnessTexture"?: textureRef,
  "normalTexture"?: {"index":u32,"texCoord"?:0|1,"scale"?:number},
  "occlusionTexture"?: {"index":u32,"texCoord"?:0|1,"strength"?:number},
  "emissiveTexture"?: textureRef, "emissiveFactor"?: [r,g,b],
  "alphaMode"?: "OPAQUE"|"MASK"|"BLEND", "alphaCutoff"?: number,
  "doubleSided"?: bool }
```

`textureRef` is `{ "index": u32, "texCoord"?: 0|1 }`, default texCoord 0. Defaults: baseColorFactor `[1,1,1,1]`, metallicFactor `1`, roughnessFactor `1`, emissiveFactor `[0,0,0]`, alphaMode `OPAQUE`, alphaCutoff `0.5`, doubleSided `false`, normal scale `1`, occlusion strength `1`. All color factors represent **linear RGB**, not sRGB. Color factors, metallic, roughness, occlusion strength and alphaCutoff must be in `[0,1]`; emissiveFactor components must be `>=0` finite; normal scale must be finite and `>=0`. BaseColorTexture RGB and emissiveTexture RGB MUST be decoded from sRGB to linear before multiplication by factors; alpha and data textures MUST remain linear. Metallic-roughness image channels: **G = roughness, B = metallic; R/A ignored**. Normal map: RGB encodes tangent-space xyz via `2*RGB-1`, OpenGL-style **+Y** green channel; normal scale multiplies tangent x/y then vector normalizes. Occlusion image R scales ambient/indirect occlusion by strength. Texture contributions multiply corresponding factors. Alpha modes: OPAQUE ignores alpha; MASK discards fragments with alpha `< alphaCutoff`; BLEND uses standard straight (unpremultiplied) alpha compositing, `Cout = Cs*As + Cd*(1-As)` in linear space. Double-sided false means back faces are culled; double-sided true disables face culling, and back-face normals SHOULD be reversed for lighting.

`images`: array of `{ "bufferView": u32, "mimeType": "image/png"|"image/jpeg"|"image/ktx2"|"image/vnd-ms.dds", "name"?: string }`. All image buffer views MUST point to IMAG chunks. **Only embedded images** are allowed in 1.0, so a complete ADM does not depend on filesystem paths, relative URL resolution or external resource availability. Each image view's *entire* byte range MUST contain one decodable PNG, JPEG, or KTX2/DDS file of the §8.6 subset matching mimeType. PNG and baseline JPEG decoding are mandatory for a full viewer (PNG transparency supported). KTX2 (optional capability `ADM-TEX-KTX2-1`) and DDS (optional capability `ADM-TEX-DDS-1`) are **GPU texture containers**: they MUST only be used as a texture `source` whose texture declares a PNG/JPEG `fallbackSource`, as specified below. APNG, animated WebP, HDR, EXR, and KTX2/DDS outside the §8.6 subset are outside 1.0. Images MUST contain one 2D image; cubemaps/arrays are outside 1.0.

`samplers`: array of `{ "magFilter"?: "NEAREST"|"LINEAR", "minFilter"?: "NEAREST"|"LINEAR", "wrapS"?: "REPEAT"|"CLAMP_TO_EDGE"|"MIRRORED_REPEAT", "wrapT"?: ... }`; defaults LINEAR, LINEAR, REPEAT, REPEAT. Mipmaps MAY be generated by runtime; sampler mip-filter settings are not encoded in 1.0. A KTX2/DDS image MAY carry precomputed mip levels (§8.6); a reader MAY use them or regenerate mips.

`textures`: array of `{ "source": u32, "fallbackSource"?: u32, "sampler"?: u32 }` where source indexes images and sampler indexes samplers; no sampler means defaults. When source is KTX2 or DDS, fallbackSource is REQUIRED and MUST reference a PNG/JPEG image with the same pixel width and height; a reader without the matching capability MUST choose fallbackSource. A PNG/JPEG source MUST NOT declare fallbackSource. KTX2/DDS support means decoding the subset published in §8.6; neither container is uniformly supported by all readers or engines. Every material texture reference MUST point to an existing texture. If texCoord=1, the mesh primitive MUST have TEXCOORD_1 (same for 0); missing required UV is invalid. `normalTexture` requires NORMAL and TANGENT attributes for guaranteed cross-implementation visual conformity (a reader MAY still offer fallback-generated tangents, but a conforming writer MUST include them).

### 8.1 Shader registry, binding identity and discovery

A shader is identified by an exact pair `(shader.id, shader.version)`, serialized as `"shader":{"id":"adm.pbr.metallic_roughness","version":"1.0.0"}`. `id` is a nonempty ASCII dot-qualified identifier (regex `[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+`, length 3..160 bytes), compared byte-for-byte. The `adm.` prefix is reserved for the official registry; external publishers SHOULD use reverse-DNS prefixes they control (for example `org.example.hologram`). `version` MUST be an exact SemVer 2.0.0 version without build metadata or ranges; a reader MUST NOT silently substitute another version. Official registry entries are immutable after publication; a semantic change requires a new version. `shader` defaults to the core PBR shader. A material's `animationId`, when present, MUST match `[a-z][a-z0-9_]*` and be unique across all `materials` in one model. It is a portable animation binding key, NOT an array index or user-visible material title. Animatable shader materials MUST provide `animationId`.

`shaderDefinitions`, optional on the `.adm` top-level, is an array of **embedded descriptive schemas** (no executable code). Each entry MUST have `{ "id":string, "version":string, "parameters":[...] }` and MAY have `"description"` and `"author"` strings. No two entries may have the same `(id,version)`. Its parameter entries MUST satisfy §8.2. An embedded definition is required for each *non-official custom shader referenced by a material*, so parsers can validate names/types and editors can expose an inspector without internet access. Official `adm.*` shader definitions MUST NOT be redefined in the file: the published registry takes precedence. An embedded custom definition describes the interface, not an interoperable rendering algorithm; custom implementations require a separately published shader contract, and otherwise conform only by rendering the PBR fallback. Missing embedded custom definition is invalid even if an application has an implementation installed.

The format does not define shader lookup paths, downloads, shader binaries, shader compilers, rendering APIs, caching or resource-pack installation. The external shader registry is a public collection of versioned *specifications* defining parameter meanings and their rendering behavior. An implementation MUST either implement the exact declared shader contract or use the PBR fallback and report status `SHADER_FALLBACK`; it MUST NOT pretend that arbitrary same-named parameters give equivalent rendering. Unknown official **optional** shaders also fall back. The standard core shader is not optional. An application MUST expose a query/report interface identifying supported `(id,version)` pairs and fallback decisions.

### 8.2 Typed shader parameters and material encoding

A shader definition's `parameters` array contains unique entries:

```json
{"name":"dirt_amount", "type":"F32", "default":0.0,
 "minimum":0.0, "maximum":1.0, "animatable":true,
 "description":"Linear dirt coverage fraction"}
```

Parameter name syntax `[a-z][a-z0-9_]*` (1..64 characters). Permitted types: `F32` (finite JSON number), `VEC2` (2 finite JSON numbers), `VEC3` (3), `VEC4` (4), `BOOL` (JSON true/false), `TEXTURE` (`textureRef` as defined in §8). Only `F32`, `VEC2`, `VEC3`, `VEC4` can be animatable, and `animatable:true` on BOOL/TEXTURE is invalid. `minimum` and `maximum` are optional **only** for numeric types, either a scalar for F32 or same-length vector for VECn. Bounds MUST be finite and componentwise `minimum <= maximum`; all parameter defaults and material values MUST lie within the declared bounds. If bounds are omitted the value is any finite value of the matching type. `description` is mandatory non-whitespace UTF-8 text (at most 2048 Unicode code points). `animatable` defaults to false. `default` is required for all parameters; for `TEXTURE` it is either `null` (no texture) or valid textureRef. `shaderParameters` is a JSON object from parameter name to value. A material `extensions` object, when present, is an ordinary JSON object keyed only by registered extension IDs that are listed in the file-level `extensionsUsed`; unknown extension data is validated and ignored only according to §4. A material without any layer or custom extension MAY omit `extensions`. A material MAY omit any parameter, in which case the declared default is used. Unknown names, wrong types, nonfinite components and out-of-range values MUST be rejected. Duplicate parameter names in a definition are invalid. A reader MUST validate the parameter object even if it will render fallback.

Core PBR fallback fields (`baseColorFactor`, `metallicFactor`, etc. in §8) are **independent** of custom shader parameters. They MUST NOT be silently overridden by similarly named custom keys, nor are they inherently animated when a custom shader parameter changes. For intentional fallback animation, an animation channel MAY explicitly target a PBR fallback field using `target.kind="pbrParameter"` (§15 and §18.1). This makes cross-viewer behavior predictable.

### 8.3 Required core shader and reference parameter table

The registry MUST contain `adm.pbr.metallic_roughness@1.0.0` and its PBR semantics are exactly the rules in §8. Its shader parameter table is **empty**: this shader is controlled entirely by the ordinary PBR fallback fields. Its material may omit `shader` and MUST omit nonempty `shaderParameters`. Conforming renderers SHOULD expose all PBR fields to their material editor. Animation of supported numeric fallback fields uses `pbrParameter` (§15), not `shaderParameter`.

The `ADM-SHADER-CORE-1` capability means: parse and validate shader references and custom schemas; correctly render core PBR; animate standard numeric PBR fields using the specified playback algorithm; render a PBR fallback when a non-core shader is unavailable; report the fallback. It does **not** mean the application implements every registered or vendor shader.

The official shader `adm.surface.cutout@1.0.0` is a masked-alpha semantic profile using the core PBR inputs and no additional shader parameters. A material selecting this profile MUST set `alphaMode` to `MASK`; omitted `alphaMode` therefore does not satisfy this profile. Its sampled alpha is `baseColorFactor.a × baseColorTexture.a`, with the texture term equal to 1 when no base-color texture is present. A fragment is discarded exactly when the resulting alpha is `< alphaCutoff`; equality passes. `alphaCutoff` defaults to 0.5 and uses the ordinary §8 range. `doubleSided` retains its §8 culling and back-face-normal semantics. The profile does not require MSAA or alpha-to-coverage and remains renderable with the standard PBR fallback. It has no shader parameters; all material values are ordinary PBR fields.

### 8.4 Standard optional layered shader (`ADM-SHADER-LAYERED-1`)

The official shader `adm.pbr.layered@1.0.0` is defined as a separate optional **semantic profile**, not a free-form Blender node graph. To avoid dependence on engine-specific blend algorithms, its shader binding MUST use exactly one numeric `layer_factor` parameter of type F32, finite in `[0,1]`, default `0`, animatable; the material MUST also include `extensions.ADM_material_layers_v1` containing exactly two *complete* numeric PBR layer records (`base` and `overlay`) and an optional `maskTexture` textureRef. A layer record has `baseColorFactor` (linear RGBA), `metallicFactor`, `roughnessFactor`, `emissiveFactor`, and optional `normalFactor` (tangent-frame vec3, default `[0,0,1]`, length >0). The `extensionsUsed` list MUST include `ADM_material_layers_v1`; `extensionsRequired` MUST include it if layered rendering is necessary rather than optional. If an implementation does not support layered rendering, it MUST use top-level PBR fallback; ignoring a **required** extension still makes file unsupported. This extension identifier is registered by this document; its structural definition here is normative.

At a fragment, `a = clamp(layer_factor × mask,0,1)`, where `mask` is 1 if `maskTexture` absent, else the sampled **linear red channel** of the mask texture. Both layer numeric PBR properties are combined componentwise by `mix(base,overlay,a)` (`mix(x,y,a) = x(1-a)+ya`) in linear space. `normalFactor` is interpolated componentwise then normalized; zero resulting vector is invalid. This interpolated tangent normal is transformed by the same tangent basis as §8. Layered rendering is **two-layer only** in v1.0; composing additional layers, height blending, packed material graphs, per-layer textures/UVs, clearcoat and damage/paint shader semantics remain separately specified future registry entries. A producer MUST NOT claim those effects are interoperably defined by this two-layer profile.

The `layer_factor` may be animated via a `shaderParameter` channel, causing the layer blend to vary over time without any runtime shader source code in ADM. Rendering an unsupported layered shader uses the ordinary material's base PBR fallback properties, NOT an implementation-chosen interpretation of the layers. This deliberate v1.0 restriction is preferred to an underspecified multilayer pipeline.

### 8.5 Example material with named shader and fallback

```json
{
  "name":"muddy_panel", "animationId":"body_paint",
  "shader":{"id":"adm.pbr.layered","version":"1.0.0"},
  "shaderParameters":{"layer_factor":0.2},
  "baseColorFactor":[0.4,0.05,0.03,1.0],
  "metallicFactor":0.5, "roughnessFactor":0.45,
  "extensions":{"ADM_material_layers_v1":{
    "base":{"baseColorFactor":[0.4,0.05,0.03,1],"metallicFactor":0.5,"roughnessFactor":0.45,"emissiveFactor":[0,0,0]},
    "overlay":{"baseColorFactor":[0.14,0.1,0.06,1],"metallicFactor":0,"roughnessFactor":0.95,"emissiveFactor":[0,0,0]}
  }}
}
```

The example is a **material fragment**, not a complete `.adm` manifest. A containing file MUST list the extension under `extensionsUsed`; it MUST list it under `extensionsRequired` only if exact layered rendering is essential. The top-level PBR values remain the intended fallback.

### 8.6 GPU texture container registry (`ADM-TEX-KTX2-1`, `ADM-TEX-DDS-1`)

KTX2 and DDS images exist so engines that upload block-compressed data directly can skip decoding. They never replace the portable path: every texture whose source is KTX2/DDS carries a PNG/JPEG `fallbackSource` (§8), and a writer's default output SHOULD be PNG/JPEG only. The fallback and the GPU image MUST encode the same picture; lossy block compression differences are allowed.

**Common rules (both containers):** exactly one 2D image (no depth, no array layers, one face); width and height ≥ 1; `levelCount` ≥ 1 where level *i* has size `max(1, w >> i) × max(1, h >> i)` and level 0 equals the fallback size; at most `floor(log2(max(w,h))) + 1` levels; no supercompression; the byte range ends exactly at the end of the last stored level. Registered formats:

| Format | KTX2 `vkFormat` (UNORM / sRGB) | DXGI (UNORM / sRGB) | Block |
|---|---|---|---|
| RGBA8 | 37 / 43 | 28 / 29 | 1×1, 4 bytes |
| BC1 (RGB, or RGBA with 1-bit alpha) | 131 or 133 / 132 or 134 | 71 / 72 | 4×4, 8 bytes |
| BC3 (RGBA) | 137 / 138 | 77 / 78 | 4×4, 16 bytes |

**Colour space:** the sRGB variant MUST be used for `baseColorTexture` and `emissiveTexture`; the UNORM variant MUST be used for `metallicRoughnessTexture`, `normalTexture` and `occlusionTexture` (data textures). A writer that shares one image between colour and data roles MUST emit separate images. Violation is `IMAGE_COLORSPACE`.

**KTX2 profile:** KTX 2.0 identifier; `typeSize` = 1; `pixelDepth` = 0; `layerCount` = 0; `faceCount` = 1; `supercompressionScheme` = 0; a Basic Data Format Descriptor whose colour model (RGBSDA = 1, BC1A = 128, BC3 = 130) and transfer function (sRGB = 2, linear = 1) agree with `vkFormat`; level data aligned to `lcm(blockBytes, 4)`, stored smallest mip first as required by KTX 2.0. Key/value data is optional and ignored by ADM.

**DDS profile:** magic `DDS `, 124-byte header with `ddspf.dwFourCC = "DX10"` followed by the 20-byte `DDS_HEADER_DXT10` (`resourceDimension` = 3 (TEXTURE2D), `miscFlag` = 0, `arraySize` = 1); mip levels stored contiguously, level 0 first. Legacy (non-DX10) headers are outside the subset; tools MAY still read them as authoring *input*.

**Outside 1.0:** Basis Universal / UASTC / ETC1S, ZSTD or zlib supercompression, BC4–BC7, ASTC, ETC2, HDR formats, cubemaps, arrays and 3D textures. Readers MUST reject such GPU images (`IMAGE_DECODE`) and use the fallback.

**Reader behaviour:** a reader advertising the capability MAY use the GPU image, its stored mips, or the fallback; a reader without it MUST use the fallback and SHOULD report a non-fatal diagnostic. Validation codes: `IMAGE_DECODE` (container violates the subset), `IMAGE_FALLBACK_REQUIRED`, `IMAGE_FALLBACK_SIZE`, `IMAGE_COLORSPACE`.

## 9. Morph targets / blend shapes (CORE, required support)

A **morph target** is additive per-vertex displacement, applied *before* skeletal skinning. Every `meshes[k]` MAY declare `targetNames: [string...]` and `weights: [number...]`; both arrays MUST have length **N**, where N is the number of morph targets shared by all primitives of that mesh. Every primitive MUST contain `targets: [target,...]` of exactly the same length N (an omitted target has no displacement and is encoded `{}`). Each target object MAY contain `POSITION`, `NORMAL`, `TANGENT` accessors: all must be F32 VEC3, count equal to primitive vertex count, with **deltas** (not absolute coordinates). Each delta semantic may be omitted and then equals zero. Target `TANGENT` xyz changes base tangent xyz, while tangent `w` is unchanged. `targetNames` are unique, case-sensitive, nonempty UTF-8 strings. Mesh defaults (`weights`) MUST be finite numbers in [0,1], defaulting to all zeros if omitted. A mesh with N=0 MUST NOT have `targetNames`, `weights` or primitive `targets`.

A node referencing a morphed mesh MAY have `weights` with N numbers, overriding mesh defaults. Unspecified node weights use mesh defaults. Where multiple nodes instantiate the same mesh, weights are **per node instance**, not shared runtime state. For each vertex, before skinning:

`p' = p_base + Σ(k=0..N-1) w[k] * deltaP[k]`  
`n' = normalize(n_base + Σ w[k] * deltaN[k])` (only if explicit normal exists)  
`t' = normalize(t_base.xyz + Σ w[k] * deltaT[k])`, `t.w` unchanged.

If the normal/tangent accumulator has length <1e-8, the corresponding authored base normal/tangent MUST be used; the authored base attribute must itself be valid. Morph weights MUST be clamped to [0,1] when driven at runtime, except that a future named extension could define extrapolation. Skinning is then applied to morphed positions and normals. Morph deltas are local model coordinates; targets MUST NOT change vertex count, index topology, materials, or joint indices. All mesh nodes using the same target name refer to their own geometries. `targetNames` are not global IDs.

**Facial profile** `face.arkit52.v1`: model `facialProfiles` array entries have `{ "id":"face.arkit52.v1", "bindings":[{"channel":str,"node":u32,"target":str,"scale"?:number},...] }`. Each binding references a morph-capable node and a target name on that node's mesh. `scale` defaults to 1 and MUST be in [0,1]. Duplicate `(channel,node,target)` forbidden. Input channel coefficients are in [0,1], and each target's accumulated value is `clamp01(Σ incoming[channel]*scale)` unless a higher-priority expression layer takes ownership as defined in §19. A channel MAY bind to multiple targets or nodes. A model claiming **complete ARKit52** support MUST bind each of the 52 channels at least once; incomplete models MAY use the profile but MUST declare `coverage:"partial"` (complete models: `coverage:"complete"`). A binding not found or targeting a nonexistent morph is invalid. ARKit stream sources are outside the format.

**Frozen 52 channel names, exact capitalization** (based on Apple `ARFaceAnchor.BlendShapeLocation`):

```text
browDownLeft browDownRight browInnerUp browOuterUpLeft browOuterUpRight
cheekPuff cheekSquintLeft cheekSquintRight eyeBlinkLeft eyeBlinkRight
eyeLookDownLeft eyeLookDownRight eyeLookInLeft eyeLookInRight
 eyeLookOutLeft eyeLookOutRight eyeLookUpLeft eyeLookUpRight
 eyeSquintLeft eyeSquintRight eyeWideLeft eyeWideRight
jawForward jawLeft jawOpen jawRight
mouthClose mouthDimpleLeft mouthDimpleRight mouthFrownLeft mouthFrownRight
mouthFunnel mouthLeft mouthLowerDownLeft mouthLowerDownRight
mouthPressLeft mouthPressRight mouthPucker mouthRight mouthRollLower
mouthRollUpper mouthShrugLower mouthShrugUpper mouthSmileLeft mouthSmileRight
mouthStretchLeft mouthStretchRight mouthUpperUpLeft mouthUpperUpRight
noseSneerLeft noseSneerRight tongueOut
```

Spaces/newlines in this printed list delimit individual identifiers and are NOT part of them. For a sample with `jawOpen=0.7` bound to target `jawOpen` with scale=1, the target receives 0.7. Left and right are **subject/anatomical** sides, not viewer sides. Unlike source Apple APIs, ADM does not require Apple software or specific capture hardware.

A generic custom shape uses a unique non-ARKit target name, optionally prefixed `custom.`. Any geometry morph (including muscles, animal muzzles, damage) uses the same mechanism. ARKit channels do not imply that all 52 targets must be geometrically separate; mapping can be 1-to-many.


## 10. Skins, joints, rest pose

The `skins` structure is `{ "name"?:string,"joints":[u32...],"inverseBindMatrices":u32,"skeletonProfile"?:u32 }`. `joints` MUST be a nonempty array of unique node indices. `inverseBindMatrices` is mandatory: an F32 MAT4 accessor with `count == len(joints)`. Nodes may have arbitrary extra helper joints. A skin's `skeletonProfile` references the file's `skeletonProfiles` table (§11), if provided. A mesh with `JOINTS_0` and `WEIGHTS_0` MUST be instantiated by a node with skin. All nonzero joint indices MUST refer to entries in the associated skin joint array. Per-vertex influence count is 4 max in v1; weights sum to 1±0.001 and readers renormalize; zero-total weights invalid.

At bind time `IBM[j] = inverse(W_joint_bind[j]) × W_mesh_bind`. At time `t`, `D[j] = inverse(W_mesh(t)) × W_joint(t) × IBM[j]`. Object-local skinned vertex: `p_s = Σ(weight[j] × D[j] × morph(p))`. World vertex `W_mesh(t) × p_s`. All matrices are column-major and transform column vectors. **Normals:** apply each joint's inverse-transpose 3×3 to morphed normal, weighted sum, normalize. A zero-length sum is invalid for a posed frame; runtimes MAY use original normal as explicitly reported fallback. No dual-quaternion skinning in v1.

`rest pose` is the default local TRS stored by the nodes when no animation applies. All skin joints MUST use TRS, be invertible, have positive component scales, and be in the same scene as the skinned mesh. An exporter MUST NOT include already deformed (posed) geometry while simultaneously recording a different bind pose. The `joints` array order defines skin-local influence indices and is independent of semantic bone names. Standard vehicle and weapon articulation nodes are **not** required to be skin joints; use `componentRoles` and `target.kind=component` for these (§15, §29).


## 11. Skeleton Profiles and cross-model identity

`skeletonProfiles` is an optional top-level array of `{ "id":string,"skin":u32,"roles":object,"referencePose"?:string,"targetHeight"?:f32,"referenceCorrection"?:object,"rigId"?:string,"extensions"?:object }`. `targetHeight` (finite >0 meters) is the target height used by §16 `motionScale`; `referenceCorrection` maps role names (each a key of `roles`) to unit quaternions `[x,y,z,w]` used by §11.2/§16; `rigId` is the §11.1 fingerprint. `id` MUST be a registered profile ID or a versioned custom ID of §11. `roles` maps **semantic role** to a node index; no role may occur twice; a node MUST NOT be mapped to two roles in the same profile. Role nodes must belong to referenced `skin.joints`. Generic profiles MAY have empty roles and only support exact-rig binding. All roles, including optional ones, use the exact normative spelling for the registered profile.

**Skeleton profile registry:** `profiles/skeleton-profiles.json` is the machine-readable registry. Its root is `{ "registryVersion":string, "specification":string, "coordinateSystem":{ "up":unitVec3, "forward":unitVec3, "right":unitVec3 }, "profiles":[...] }`; for ADM 1.0 these vectors MUST be exactly up `[0,1,0]`, forward `[0,0,-1]`, right `[1,0,0]`. Each profile has `id`, positive integer `version`, `status` (`NORMATIVE`, `EXACT_ONLY`, `PROVISIONAL`), `family`, `title`, `roles`, `referencePose` (object or null), `localAxes`, `ikTemplates`, `socketTemplates`, `semanticCompatibleWith`, `retargetMaps` and `translationRoles`; `source` is optional citation metadata. A role value is `{ "parent":role|null, "required":boolean, "needsParent"?:boolean }`; `parent` names the immediate semantic parent, and unmapped helper joints may intervene in the actual node tree. A non-null `referencePose` is `{ "name":string, "up":unitVec3, "forward":unitVec3, "right":unitVec3, "sides":[{"left":role,"right":role},...], "checks":[{"from":role,"to":role,"direction":unitVec3},...], "toleranceDeg":finiteNumber, "toleranceStatus":"NORMATIVE"|"PROVISIONAL_DIAGNOSTIC" }`. A provisional profile MUST use `PROVISIONAL_DIAGNOSTIC`; its pose checks cannot establish compatibility. Each IK template is `{ "id":string,"root":role,"mid":role,"end":role,"pole":unitVec3 }`; the solver is TWO_BONE in ADM-IK-1. Each socket template is `{ "name":string,"role":role,"fallback"?:[role,...] }`, where fallback order is preference order. `localAxes` is `"UNCONSTRAINED"` in this revision. Empty `retargetMaps` means no cross-profile retarget mapping is registered. Unknown registry fields are invalid. This registry is authoring/validation metadata, not serialized inside `.adm`; each file stores the resolved `roles`, `ikChains` and `attachments` explicitly.

Registry status controls claims: `NORMATIVE` may be advertised as semantic-compatible when all profile validation passes; `EXACT_ONLY` never supports semantic binding; `PROVISIONAL` may be authored and validated for diagnostics but MUST NOT be claimed as ADM semantic interoperability. Templates are editor defaults, not hidden runtime behavior.

**`humanoid.vrm1`** uses the semantic bone names, required/optional classification, and parent hierarchy of the normative VRM 1.0 humanoid specification (pinned reference: `https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md`, reference snapshot date 2026-11-13). The required 15 roles are `hips spine head leftUpperLeg leftLowerLeg leftFoot rightUpperLeg rightLowerLeg rightFoot leftUpperArm leftLowerArm leftHand rightUpperArm rightLowerArm rightHand`. Other VRM-defined roles are optional. VRM's ancestor rules apply to the **semantic parent chain**: unmapped helper joints MAY occur between mapped semantic bones if they do not alter the unique mapped ancestry. A role map missing any required role is invalid for `humanoid.vrm1`. A model can include hundreds of facial, hair or costume joints without breaking semantic compatibility.

**Canonical reference pose** for retargeting: a humanoid model MUST declare `referencePose:"T"`. In the final ADM model frame +Y is up, +X is the character's anatomical right, and forward is −Z. For each profile direction check in the registry, compute the normalized vector from the source role joint's rest-pose origin to the destination role joint's rest-pose origin in model space and its angle to the declared unit direction. Every humanoid check MUST be within **25 degrees**, inclusive; any check outside tolerance invalidates semantic binding (`REFERENCE_POSE`). Left/right facing checks are categorical and have no angular tolerance: a humanoid with its left-side roles on +X is mirrored and invalid (`REFERENCE_FACING`). A numeric check is a validity threshold, not a claim that the resulting pose is anatomically ideal. **No fixed number of mesh bones is required**, and semantic compatibility does not imply exact bone count or identical bone lengths.

Coordinates in an imported source format MUST be converted as one consistent basis transform before ADM validation. For a VRM/glTF source facing +Z, the source-to-ADM conversion includes a 180-degree rotation about +Y; apply it consistently to geometry, node/rest transforms, inverse bind matrices, animation, IK poles and attachment frames. Do not repair only the armature or semantic role positions.

**Compatibility** is explicit:

- `EXACT`: same rig identity and identical ordered mapped joints, default local TRS and skin bind matrices (within declared tolerance). To avoid ambiguous identity across tools, `rigId` is a required lowercase 64-digit hexadecimal SHA-256 over the canonical rig descriptor produced by §11.1 when a model declares an exact-compatible rig. An animation may demand the same rigId.
- `SEMANTIC`: required semantic roles supplied and matching profile identifier; the profile's published reference-correction and retarget rules apply. Extra unmapped bones keep target rest/default pose. A profile marked `PROVISIONAL` cannot produce this compatibility level.
- `INCOMPATIBLE`: missing required roles, different declared profile IDs, or failed validation; loader MUST NOT play as if compatible.

### 11.1 Exact rig fingerprint

Canonical descriptor is UTF-8 JSON with sorted keys, no whitespace, integers as decimal, float32 values serialized as **8 lowercase hex digits of their IEEE-754 little-endian byte sequence**, and fields `roles` (sorted role names with integer node indices), `jointOrder` (ordered node indices), `restTRS` (all joint local TRS array entries in `jointOrder` order), `inverseBindMatrices` (16 f32 per joint). Encode as canonical UTF-8 JSON and compute SHA-256 hex digest. `rigId` MUST exactly equal the calculated digest. Negative zero is canonicalized to +0 before bytes encoding. JSON sorting uses Unicode scalar code point order. Exact matching DOES NOT replace validation of actual profile semantics. [**Normative fixture required before final ratification**: §25.]

### 11.2 Local axes and normalized humanoid retargeting

ADM does not prescribe Blender/bone-local axis or roll conventions. For `humanoid.vrm1`, interoperable semantic rotation tracks therefore use the following mandatory normalized convention (profile algorithm `ADM-REF-NORM-1`). Let `q_rest(role)` be the unit quaternion formed by multiplying the role joint's local rest rotations from the scene root through that joint, in parent-to-child order; scale is not included. `referenceCorrection[role]` MUST equal its conjugate, normalized, i.e. `inverse(q_rest(role))`, up to quaternion sign and a maximum component error of `1e-4`. A `humanoid.vrm1` profile MUST provide a correction for every mapped role; missing or inconsistent corrections invalidate semantic binding and MUST NOT silently default to identity. Exact binding does not require corrections.

For a semantic rotation delta `δ` sampled in the ADM reference frame, evaluate the target role's model-space rotation as `q_target = q_rest × C × δ × inverse(C)`, where `C=referenceCorrection[role]`. With a valid normalized correction this is `δ × q_rest`: the delta is applied in the ADM model frame independent of local bone roll. Quaternions are xyzw Hamilton products; normalize the result. Writers MUST calculate corrections from the serialized rest transforms, not from posed/deformed transforms. The reference pose check is performed before applying correction. The optional profile field MUST contain exactly the mapped role names for a semantic humanoid profile; unmapped helper joints are not entries.

**Mechanical profiles:** `vehicle.car.v1` and `weapon.firearm.v1` are non-skeleton model profiles defined in normative Draft 0.4 annexes. Quadruped identifiers `animal.generic_quadruped.v1`, `animal.canine.v1`, `animal.feline.v1` and `animal.equine.v1` remain PROVISIONAL proposals pending explicit profile approval and independent anatomical review. A tool MUST NOT report `SEMANTIC` compatibility for them. `extends` records shared draft structure only and grants no compatibility.

**Custom profiles:** an unregistered identifier MUST use `org.<reverse-domain>.<profile-name>.vN` (lowercase ASCII labels matching `[a-z][a-z0-9-]*`, final version label `v[1-9][0-9]*`). An unregistered profile is `EXACT_ONLY`; it MUST NOT define semantic roles or claim semantic compatibility. To register semantic behavior, publish a versioned annex and machine-readable registry entry defining the complete role set, required/optional rules, parent graph, reference-pose checks and tolerance, translation roles, retarget algorithm/corrections, IK/socket templates and positive/negative fixtures. Until that is approved and listed with `NORMATIVE` status, consumers MUST treat the ID as unknown for semantic binding.

**Cross-profile retarget maps:** ADM 1.0 defines no serialized map format and registers no cross-profile map. The registry's `retargetMaps` MUST therefore be empty in this revision. A differing source/target profile ID is `INCOMPATIBLE`, even when the roles appear similar or the profiles share a draft `extends` relationship. A future mapping requires a versioned, reviewed profile-pair annex with an explicit role mapping, transform/correction rules, compatibility tests and an exact registry entry; tools MUST NOT infer or synthesize one. This explicit prohibition is the ADM 1.0 behavior, not an invitation to guess.


## 12. Model metadata for mechanical parts and attachments

Existing ADM `attachments` attach named coordinate frames to nodes (§23). Optional top-level `componentRoles` is an array of `{ "role": string,"node":u32,"profile":string }`, with unique role names within a profile; the data expresses **mechanical visual semantics**, not physics. Names SHOULD be qualified, e.g. `wheel.axle0.left`, `wheel.axle0.right`, `door.front.left`, `steering.wheel`, `seat.driver`, `muzzle`, `prop.socket.right_hand`. No role may imply engine-specific control code. A generic viewer MUST expose node transforms even if it doesn't interpret roles.

Normative role and pivot conventions for `vehicle.car.v1` and `weapon.firearm.v1` are defined in §29 and their incorporated profile annexes. `modelProfiles` is optional top-level array of `{ "id": string, "schemaVersion":u32, "metadata":object }` with unique `id` values; the two published profile annexes require schemaVersion=1. Other profile IDs require a separately published versioned contract. Unregistered `componentRoles` are descriptive annotations only. Profiles are not a requirement for generic ADM-CORE-1 assets.


## 13. `.adm_anim` container (byte-exact)

`.adm_anim` is a separate **complete** animation library containing no mesh geometry. It shares the exact 64-byte chunk container, directory, JSON encoding, chunk-addressed bufferViews, accessors, and type definitions from §§2–5, except for this format's 4-byte magic: ASCII `AMA0` = hex `41 4D 41 30`. `major=1`, `minor=0`, flags=reserved=0. Physical length and all offsets MUST satisfy §3. A `.adm` parser MUST NOT accept this magic as `.adm`, and vice versa. No legacy `ADS\0` support.

Top-level `.adm_anim` manifest **required**: `asset` object, `library` object, `clips` array, `bufferViews` array, `accessors` array. **Optional**: `eventsSchema`, `chunkDependencies`, `streamHints`, `extensionsUsed`, `extensionsRequired`, `extensions`, `extras`. Unknown top-level fields forbidden. `library` has required fields `{ "id":library_id, "title":string, "description":string, "language":string, "targetProfile":string, "binding":"SEMANTIC"|"EXACT" }` and only these optional fields: `rigId`, `tags`, `author`, `license`, `revision`, `namespace`, `motionScale`, `sourceHeight`, `rootMotionSource`. Unknown library fields are invalid. `title` and `description` MUST contain non-whitespace Unicode text, max 256 and 2048 Unicode code points respectively. `language` MUST match a valid BCP-47 language tag (case-insensitive comparison; writer SHOULD use canonical casing). `targetProfile` MUST identify a registered skeleton profile, a registered mechanical model profile (`vehicle.car.v1`, `weapon.firearm.v1`), `model.any.v1`, or a versioned published custom profile. A SEMANTIC `component` channel requires a matching mechanical `modelProfiles` entry on the target model; mechanical roles are not skin joints. `model.any.v1` is registered by ADM 1.0 for material/morph/expression-only libraries, requires `binding=SEMANTIC`, and forbids `bone` and `component` targets and `rootMotion=EXTRACT`; its tracks can bind any ADM model possessing their explicitly identified target roles. `binding=EXACT` requires `rigId`; SEMANTIC MUST NOT include it. `tags`, when present, MUST be an array of unique lowercase segments matching the clip tag syntax in §14. `author` and `license`, when present, MUST be strings. `revision`, when present, MUST be SemVer 2.0.0. `namespace`, when present, MUST be a lowercase reverse-DNS name with at least two labels; it qualifies the library identity but does not change `library.id`. `motionScale` MAY be `"SOURCE_HEIGHT"` only; it requires finite `sourceHeight > 0` meters. `sourceHeight` without `motionScale` is invalid. With `SOURCE_HEIGHT`, a semantic humanoid target MUST provide finite `targetHeight > 0` meters; missing target height makes the binding incompatible, not an unscaled fallback. `rootMotionSource`, when present, MUST be `"hips"` and is valid only for `targetProfile:"humanoid.vrm1"` in this revision. It identifies the semantic track used by EXTRACT clips, not a new skeleton role. If author/license is absent no authorship or licensing conclusion is implied. Catalog indexers MUST be able to extract `library` and `clips[*]` metadata without reading ANIM chunks.

`library.id` is the **authoritative** ID, never derived from the filename. Full clip identifiers are `library.id + ':' + clip.id`. Library ID syntax `segment ('@' segment)*`, clip id `segment`, segment regex `[a-z][a-z0-9_]*`. Full IDs are lowercase ASCII and case-sensitive. `human@walking@wounded:walk1` is valid; whitespace, uppercase, slash, colon in segment, empty segment or duplicate clip id are invalid. Library IDs SHOULD have ≥2 segments; if not, still syntactically valid. An application MUST NOT choose between two simultaneously loaded identical full IDs without an explicit namespace/version override from its asset manager; this file format does not define resource search paths or override precedence.

**Versioning:** container major/minor is binary specification version, independent of semantic library version. Optional `library.revision` is a SemVer 2.0.0 string; resource systems that use revision MUST specify their dependency resolution policy. `library.id` alone is not globally collision-resistant across creators; for distribution `library.namespace` MAY specify reverse-DNS name (e.g. `org.example`) and the disambiguated asset key is `(namespace, id, revision)`; absent namespace denotes a project-local name. Namespaces MUST NOT be silently merged.


## 14. Animation clips and mandatory descriptions

Every `.adm_anim` `clips` entry MUST provide:

```json
{ "id":"walk1", "title":"Wounded walk 1", "description":"Slow limping walk favoring the right leg.",
  "language":"en", "tags":["locomotion","wounded","limping"],
  "duration":1.6, "loop":"REPEAT", "rootMotion":"IN_PLACE", "channels":[], "events":[] }
```

Required fields: `id`, `title`, `description`, `language`, `duration`, `loop`, `rootMotion`, `channels`, `samplers`. `tags`, `events`, `extras` are optional (default empty). Title, description and language follow the library's field constraints. A whitespace-only description is INVALID: exporters MUST prompt authors rather than synthesize text from clip names. `duration` finite float ≥0 seconds. `loop` = `ONCE` or `REPEAT` or `PINGPONG`. `rootMotion` = `IN_PLACE` or `EXTRACT` or `IGNORE`. `tags` unique lowercase segments, sorted lexically on write for deterministic indexing. Clip names are unique inside their library. `clip.id` is NOT a human-readable label.

For t input: ONCE uses clamp(t,0,duration); REPEAT with duration>0 uses t - duration*floor(t/duration), otherwise time0; PINGPONG with duration>0 let r=t - 2duration*floor(t/(2duration)), use `duration-abs(r-duration)`; duration0 always time0. **Events** fire on crossings in advancing time including wrap boundaries according to §17; a viewer seeking to time without playback does not implicitly fire events.

`rootMotion=IN_PLACE` means hips is animated only by non-locomotive offsets; no world displacement is implied. `EXTRACT` declares a dedicated root-motion transform track which the evaluator MUST expose to its host as per-sample displacement; it MUST NOT itself move a game entity. In v1, extraction is supported only for semantic `humanoid.vrm1` libraries with `library.rootMotionSource:"hips"`; EXACT extraction and other root roles are unsupported. If any clip uses `EXTRACT`, the library MUST declare that source. The clip MUST supply exactly one hips translation channel; a rotation channel on hips is optional and, if present, contributes orientation to extracted motion. For `EXTRACT`, the selected channel is removed from the evaluated pose (the hips component uses its neutral value) and emitted separately, preventing double application. `IGNORE` treats ordinary skeletal channels normally but does not emit a root-motion result. A clip without `EXTRACT` MUST NOT be interpreted as root-motion extraction, whether or not its library declares a source. A host may choose to integrate emitted deltas into its scene/object transform, which is not part of ADM.

All numerical metadata must be finite. Search by title, description and tags is an indexer's choice; the source strings are guaranteed available and stable for indexing. Keywords/synonyms and translations MAY be added via separately versioned extension, without changing the primary required description.


## 15. Animation channels: exact data schema

`clip.channels` is an ordered array of objects:

```json
{ "target":{"kind":"bone","role":"leftUpperArm"}, "path":"rotation", "sampler":0 }
{ "target":{"kind":"morph","name":"jawOpen"}, "path":"weight", "sampler":1 }
{ "target":{"kind":"expression","name":"happy"}, "path":"weight", "sampler":2 }
```

`clip.samplers` is required (may be `[]`) and is an array of `{ "input":accessorIndex,"output":accessorIndex,"interpolation":"STEP"|"LINEAR"|"CUBICSPLINE" }`. An `input` accessor MUST be F32 SCALAR with count>=1, strictly increasing finite times ≥0, ending ≤ duration; times are seconds. Values are F32; `translation`/`scale` output VEC3, `rotation` output VEC4 xyzw unit quaternion, `weight` output SCALAR. For STEP or LINEAR, output count=input count. For CUBICSPLINE, output count=3×input count, stored `[inTangent,value,outTangent]` for each key, tangents measured per second and not subject to weight clamps before evaluating the segment. For quaternion CUBICSPLINE the interpolated vector must be normalized; a zero interpolated vector is invalid. All sampler time types are F32, no quantized time in v1. Input/accessor indices reference `.adm_anim` chunk-addressed buffer views, never model `.adm` chunks.

`target.kind=shaderParameter` MUST provide `materialId` (string matching a model material's unique `animationId`) and `parameter` (registered shader-parameter name); its `path` MUST be `value`. The material MUST reference the shader/version specified by `target.shaderId` and `target.shaderVersion` (both required), and that parameter MUST exist, be numeric and have `animatable:true`. Sampler output type MUST match parameter type: F32→SCALAR, VEC2→VEC2, VEC3→VEC3, VEC4→VEC4. Exact shader version mismatch rejects binding; no implicit migration. `target.kind=pbrParameter` MUST provide `materialId`, `parameter` and `path:"value"`; `parameter` MUST be one of `baseColorFactor` (VEC4), `metallicFactor` (F32), `roughnessFactor` (F32), `emissiveFactor` (VEC3), `alphaCutoff` (F32) or `normalScale` (F32). `normalScale` animates the existing `normalTexture.scale`; the material MUST have `normalTexture`. All other PBR field defaults follow §8. Sampler output type MUST match field dimensions. Texture indices, alphaMode, doubleSided, shaders and BOOL/TEXTURE parameters are never animatable in v1.0. A shader animation channel MUST NOT switch shader identities, swap textures or change topology.

`target.kind=component` is defined for mechanical model profiles, **not** skeleton joints. It MUST provide `role` (string, exactly one `componentRoles.role` mapping for the declared profile) and a `path` of `translation` (F32 VEC3) or `rotation` (F32 VEC4 quaternion); it MUST NOT use `scale`. Its samples are **rest-relative deltas**: translation resulting local T = T_rest + sampled deltaT in parent axes; rotation resulting local Q = normalize(Q_rest × sampled deltaQ), with xyzw Hamilton multiplication. Initial deltaT = zero and deltaQ = identity. A semantic component animation library MUST specify the identical `targetProfile` ID as the model's `modelProfiles` entry, set `binding=SEMANTIC`, and resolve each target role uniquely. `optional:true` allows an absent role (with a reported diagnostic). Component tracks MAY use existing interpolation and blending rules §18; for OVERRIDE blend the **delta** against the zero/identity default, while ADDITIVE is composed as defined in §18. Profile-specific range and axis constraints are defined in the annex and checked after sampling. `component` channels operate on model nodes even if they do not have a skin; they MUST be evaluated before final scene matrices and attachment world frames are calculated. A model node targeted simultaneously by `bone` and `component` channels is invalid for that evaluation; a role node MUST NOT be one of the `skin.joints` in any skin. `model.any.v1` MUST NOT bind component targets because it lacks declared mechanical role semantics. 

`target.kind=bone` uses `role` (SEMANTIC), or `nodeName` (EXACT, must be unique within the rig descriptor). For SEMANTIC a role MUST exist in the target profile registry, otherwise invalid. `target.kind=morph` uses `name` of a morph target or a bound semantic face channel (`face.arkit52.v1` channel); `target.kind=expression` uses named `expressions` defined on the model (§19). A morph clip may target a shared semantic ARKit channel even if the model uses multiple meshes. Any target (including shader/material targets) not present in a particular model is an error unless the channel object includes `optional:true`; optional channels may be omitted with their defaults and MUST be reported by a diagnostic API. A target `(kind,identity,path)` MUST NOT repeat inside a clip. One sampler MAY be reused across multiple channels of matching output types.

**Interpolation:** STEP holds previous key. LINEAR interpolates scalar/vector components and SLERP quaternion shortest arc. If dot<0, negate second quaternion; if dot>0.9995 use normalized lerp, else use `sin((1-u)θ)/sin θ*q0 + sin(uθ)/sin θ*q1` with θ=acos(clamp(dot,-1,1)). CUBICSPLINE uses cubic Hermite `h00=2u³−3u²+1`, `h10=u³−2u²+u`, `h01=−2u³+3u²`, `h11=u³−u²`; result `h00*v0 + h10*Δt*outTan0 + h01*v1 + h11*Δt*inTan1`. Weight channels clamp to [0,1] only after sampling. Key times outside authored range clamp to the first/last sample value (independent of clip loop handling). For CUBICSPLINE quaternions no shortest-path sign correction during Hermite; writers MUST author sign-consistent keys/tangents, avoiding nonzero-length ambiguities.


## 16. Animation semantic transforms and retarget

For `binding:"EXACT"` channels contain absolute **target-local TRS** (except weight channels). Missing paths use rig rest values. For `binding:"SEMANTIC"`, rotation channels represent a **unit quaternion delta in the ADM model reference frame**, not an absolute local rotation. An authored identity quaternion means *keep the reference rest rotation*. The target evaluator MUST apply the profile correction algorithm (for `humanoid.vrm1`, §11.2) and derive local rotations from the resulting model-space transforms and the animated parent transforms; it MUST NOT multiply the delta directly into an arbitrary target-local bone axis. Target translation is forbidden for semantic bone roles except roles explicitly listed in the profile's `translationRoles` (for humanoid, only `hips`). `scale` tracks are forbidden for SEMANTIC. Extra target bones not addressed by channels retain default local TRS.

**Root/hips motion:** semantic translation channels may target only roles listed in the profile's `translationRoles`; for `humanoid.vrm1`, this is `hips`, not `root`. Samples specify offsets in meters relative to the neutral role origin. A library MAY declare `motionScale:"SOURCE_HEIGHT"` and `sourceHeight` finite >0 meters; then target offset is source offset × (`targetHeight/sourceHeight`), using the target model's declared `targetHeight`. Without `motionScale`, translation uses literal meters and is never automatically scaled. `rootMotionSource:"hips"` explicitly identifies the hips track for clips with `rootMotion:"EXTRACT"`; it does not create a `root` role. For time `t`, extracted translation is the sampled source offset at `t` minus the sampled source offset at the clip's reference time 0, after motion scaling. With a rotation track, extracted orientation is `inverse(q(0)) × q(t)`; without one it is identity. Loop-boundary displacement is evaluated according to the clip loop rule in §14 and reported as a delta between successive samples; file evaluation does not move the model root or an engine entity.

**Rest alignment prerequisite:** A semantic humanoid target MUST pass the §11 reference-pose checks and provide the complete `ADM-REF-NORM-1` per-role corrections. The evaluator MUST use the profile's semantic roles and the algorithm in §11.2; it MUST NOT assume that differing local rest axes align. A profile that does not define a normative correction/retarget algorithm cannot be used for semantic binding. An unknown or provisional profile's retarget rules are undefined, and a reader MUST NOT claim semantic compatibility for it.

**Quality caveat:** Identical semantic roles guarantee deterministic pose mapping, not identical contact, reach or animation aesthetics across differently proportioned bodies. IK is used for reach/feet correction. Bone names alone do not imply avatar proportions.


## 17. Animation events and root-motion output

An event is `{ "time":float, "name":string,"payload"?:object }`, where time is finite in `[0,duration]`, name follows `[a-z][a-z0-9_.]*` and payload is arbitrary JSON no more than 4096 UTF-8 bytes after canonical serialization; payload does not control core animation. Events MUST be sorted by time ascending; ties sorted by name then payload canonical JSON byte order. On a continuous forward playback interval `(t0,t1]`, emit all event occurrences whose loop-mapped absolute times fall in it, ordered by occurrence time and file order. On reverse playback `(t1,t0]` emit in reverse occurrence order; a host application may opt not to dispatch reverse events but must report that behavior. At EXACT ONCE t=0 events are emitted only when playback is explicitly started (not when seeking). For REPEAT an event authored at duration MUST be considered at wrap boundary; an event at time0 at wrap is considered a *separate event*, so both may fire if both exist. PINGPONG events are emitted at each directional pass including endpoints once per turnaround, without duplicate reporting at the same absolute instant.

For `rootMotion=EXTRACT`, the evaluator exposes `Δroot = inverse(R(t0))×R(t1)` computed from the root track in reference space, with loop wrap broken into consecutive segments. Root motion is **data**, not a request to move networked entities. Rotation/translation samples are communicated as double-precision host results derived from f32 source values; on-disk storage remains f32.


## 18. Animation layering and blending

The file DOES NOT prescribe game state machines or when to play animations. However a compliant **ADM animation evaluator** that combines clips MUST implement a deterministic evaluation API:

`Evaluate(model, [(clip, localTime, weight, layer, mode, mask)...], externalMorphCoefficients, ikTargets) → pose, morphWeights, shaderParameterValues, pbrParameterValues, events, rootDeltas`.

Weights are finite in [0,1]; layers are nonnegative integers; mode=`OVERRIDE` or `ADDITIVE`; masks list explicit bone roles/names, mechanical component roles and/or morph channels, default all. Layers are evaluated in ascending layer, with items in the same layer sorted lexicographically by full clip identifier; duplicates within one layer are rejected. **OVERRIDE** on a channel: for all clips on layer with channel weights wi, let total S=Σwi. If S=0 preserve previous value; otherwise calculate normalized weighted blend B from contributions `wi/S` (scalar/vector weighted mean, quaternion via sign-corrected normalized weighted sum using lexicographically first contributing quaternion as sign reference), then apply `lerp(previous,B,min(1,S))` for scalars/vectors and shortest-arc SLERP for rotation. **ADDITIVE** on a channel (after overrides in that layer): translation adds `wi × deltaPosition`; rotation applies `slerp(identity, deltaQuaternion, wi)` in lexicographic order; scale additive is forbidden for semantic skeletons; morph weight adds `wi×deltaWeight` and clamps after layer. Each animated channel missing from a clip contributes no weight and leaves its previous value unchanged.

External ARKit face values, if supplied, are inserted as an explicit synthetic `OVERRIDE` layer with configured layer index; no implicit precedence. Default external layer is 1000. Per-channel expressions (next section) use deterministic masks and override. Hosts not exposing the blending API MAY support individual-clip playback only, but MUST NOT claim the `ADM-ANIM-BLEND-1` profile. Internal arithmetic SHOULD use f64; outputs are compared within §25 tolerance, not bitwise identical.


### 18.1 Deterministic shader-parameter animation and evaluation

The `.adm_anim` file stores animated **numeric values**, not shader code. Shader tracks use the same strictly increasing seconds, STEPs, LINEAR interpolation and cubic Hermite samples defined in §15. `shaderParameter` and `pbrParameter` are independent target namespaces. Full target identity is `(kind, materialId, shaderId?, shaderVersion?, parameter)`; a parameter cannot appear more than once per clip under the same full identity. `materialId` targets a reusable model role, never the source `.adm` material array index. A library MAY contain bone, morph, expression, shader and fallback PBR channels in the same clip; standard track catalog metadata remains mandatory.

For every evaluation call, initialize shader parameters from the material values with their schema defaults, and initialize PBR parameters from §8. Layer order, channel masks and clip weights follow §18 **without exception**. A shader/material channel contributes only if its full identity matches; masks addressing shader fields use the exact identity string `shaderParameter:<materialId>:<parameter>` or `pbrParameter:<materialId>:<parameter>`. Invalid mask tokens are rejected. A shader track absent from an active clip leaves the current value untouched. For OVERRIDE, compute componentwise weighted mean among matching clips, then `mix(previous, mean, min(1,totalWeight))`. For ADDITIVE, add `weight × sampledDelta` componentwise; for shader/PBR tracks the keyframe samples in an ADDITIVE clip represent **deltas** around zero, not absolute values. In a single layer, OVERRIDE contributions are applied first; ADDITIVE contributions then accumulate in lexicographic full clip ID order. After **each layer**, clamp to declared parameter minimum/maximum where present, otherwise retain finite numbers. Core PBR parameters follow their §8 bounds. Sampling results MUST be finite; overflow is invalid. Shader parameter evaluation happens **after pose/expression sample blending and before material shading**; it does not change skeleton/IK calculations.

An unrecognized optional shader MUST use PBR fallback. `shaderParameter` channels on that shader may still be validated and sampled for diagnostics, but they MUST NOT be interpreted as, or automatically mapped onto, PBR fields. Independent `pbrParameter` channels remain active, so authors can explicitly animate a visible portable fallback. A required unknown `shader` is **not** inferred from its name: use an explicitly registered required extension/capability to prohibit fallback where fidelity is indispensable. A renderer MUST report both `shaderSupported` and `shaderFallbackActive` per material.

A decoder that only parses libraries MUST retain shader channel data and MUST report unsupported evaluation separately. An evaluator advertising `ADM-SHADER-CORE-1` MUST support `pbrParameter` tracks; one advertising `ADM-SHADER-LAYERED-1` MUST additionally support `adm.pbr.layered@1.0.0` and its `layer_factor` track.

**Example animation clip fragment:**

```json
{
  "id":"mud_build_up", "title":"Mud gradually accumulates", 
  "description":"Increases the mud layer factor on the body paint over two seconds.",
  "language":"en", "duration":2.0, "loop":"ONCE", "rootMotion":"IGNORE",
  "samplers":[{"input":0,"output":1,"interpolation":"LINEAR"}],
  "channels":[{
    "target":{"kind":"shaderParameter","materialId":"body_paint",
      "shaderId":"adm.pbr.layered","shaderVersion":"1.0.0",
      "parameter":"layer_factor"},
    "path":"value", "sampler":0
  }],"events":[]
}
```

Its input accessor contains F32 `[0.0,2.0]`; output F32 `[0.0,1.0]`. At playback t=1.0 and layer weight 1, sampled `layer_factor=0.5`. If a viewer lacks `ADM-SHADER-LAYERED-1`, it draws the unchanged portable PBR fallback (or animates it if separate `pbrParameter` channels exist). The fragment requires valid `.adm_anim` chunk-addressed bufferViews/accessors and a matching `.adm` model; it is not a standalone valid file.

## 19. Expressions and face-driven animation

A model MAY declare top-level `expressions` as an array `{ "name":str,"bindings":[{"node":u32,"target":str,"weight":f32}...],"priority"?:u32,"group"?:"face"|"blink"|"mouth"|"look"|"custom" }`. Names MUST be unique, nonempty. Each binding target MUST be an existing morph target on the specified node; `weight` ∈ [0,1]. An expression input E in [0,1] proposes target contribution `E×binding.weight`.

Expressions operate in a **face expression layer** after clip morph sampling and before IK. Expressions are processed by ascending priority (default 0), then name ascending. At each expression, for every target it binds, set weight to `clamp01(current*(1-E) + E*binding.weight)`; this is an OVERRIDE, not sum, guaranteeing deterministic conflict behavior. The `group` field is descriptive for cataloging only; no implied suppression of blink or mouth occurs. If artists want exclusive combinations they MUST specify actual layer/blend masks or priorities; VRM's expression vocabulary may be used, but no VRM runtime conflict rules are silently assumed. Useful preset names: `neutral`, `happy`, `sad`, `angry`, `relaxed`, `surprised`, plus lip/eye expressions; custom names allowed.

`face.arkit52.v1` input is a stream of coefficients; a recorded face clip uses `target.kind="morph"` with the same 52 semantic channel names. An ARKit-specific clip need NOT contain all 52 channels; omitted channel values remain zero unless supplied by other layers. Morph weights and expression results have no dependency on Apple hardware.


## 20. IK definitions and runtime parameter contract

IK is standard **model metadata** plus an optional external runtime target input, not a stored scripted behavior. Top-level `ikChains` array contains:

```json
{ "id":"leftLeg", "solver":"TWO_BONE", "root":4, "mid":5, "end":6,
  "effectorOffset":[0,0,0], "pole":[0,0,1], "weight":1.0,
  "stretch":false, "targetSpace":"MODEL" }
```

Fields `id`, `solver`, `root`, `mid`, `end`, `pole` are required. Root/mid/end are unique joint node indices, with mid a descendant of root and end a descendant of mid; in 1.0 the chain MUST consist of **direct parent-child** links, so segment lengths are well-defined. Each root-to-mid and mid-to-effector rest distance MUST be greater than `1e-6` meters; all chain bones MUST have positive uniform scale, and their parent transforms MUST NOT introduce shear. `effectorOffset` defaults to `[0,0,0]` in end local coordinates; the solved end point is the offset transformed by the end node's model matrix, not necessarily the end node origin. `pole` is a unit vector in **model** space. `weight` is in [0,1] and defaults to 1. `stretch` MUST be false in v1. `targetSpace` MUST be `"MODEL"` in v1. A chain is defined in neutral pose; an arbitrary runtime target is an input `(position, optional orientation, optional poleOverride)` supplied in model space. A supplied `poleOverride` MUST be a finite nonzero model-space direction and is normalized before use. A host MUST NOT silently invent a target; if absent, the IK chain is inactive and the FK pose is unchanged.

`ADM-IK-1` standardizes TWO_BONE position-solving only. FABRIK, CCD, gaze constraints, angular joint limits, twist distribution, stretch and chains with more than two segments are **not part of ADM-IK-1**. The core `ikChains` schema has no joint-limit fields; such fields are invalid, not silently ignored. DCC constraints outside this exact subset MUST be reported as unsupported and MUST NOT be exported as ADM IK. Support requires a separately registered, versioned capability and MUST NOT alter ADM-IK-1 results.

### 20.1 Two-bone numerical solver

All vector calculations below are in **model space after animation, retarget and blend but before skinning**, and use f64. Let A be the root origin, B the mid origin, C the end-effector point (`end` node origin transformed by `effectorOffset`), and P the target; `l1=|B−A|`, `l2=|C−B|`, `d=|P−A|`. If either segment length is <=1e-6, the chain is invalid. The physically reachable endpoint interval is `[dmin,dmax]`, where `dmin=abs(l1-l2)` and `dmax=l1+l2`. Set `d_solved=clamp(d,dmin,dmax)`; status is `SOLVED` iff `dmin <= d <= dmax`, otherwise `CLAMPED`. There is no epsilon inset from the reachable interval.

For `d>1e-8`, set `u=(P−A)/d`; otherwise use `normalize(C−A)` if nonzero, else `normalize(B−A)`. Let Q be `poleOverride` when supplied, otherwise the chain's `pole`. Set `v=normalize(Q−u*dot(Q,u))`. If this projected vector has length `<1e-8`, choose the least-aligned model unit axis X, Y, Z (ties in that order), project it onto the plane perpendicular to u, and normalize. Normally set `a=(l1²−l2²+d_solved²)/(2*d_solved)`, `h=sqrt(max(0,l1²−a²))`, `B*=A+a*u+h*v`, and `C*=A+d_solved*u`.

**Zero-fold singularity rule:** if `d_solved <= 1e-8` (the equal-length, zero-distance case), set `B*=B` and `C*=A`. This preserves the neutral fold direction and avoids division by zero; `SOLVED`/`CLAMPED` status still follows the interval test above. A target outside the interval is clamped to the nearer endpoint by the clamp operation. If `weight=0`, return the input FK pose exactly. Report the final end-effector error, solved target and status.

### 20.2 Applying joint rotations without hidden twist

For root joint, find minimal quaternion `swingRoot = FromTo(B−A, B*−A)`; for mid joint after updating root transform, `swingMid = FromTo(C_afterRoot−B*, C*−B*)`. `FromTo(x,y)` is the unique shortest-arc rotation for nonantipodal directions. For antipodal (dot <=−1+1e-8), choose an axis orthogonal to x by selecting least-aligned of X,Y,Z and normalizing cross(x,axis), rotate π. Multiply world rotation on the **left**: `R_root_new=swingRoot×R_root_old`, `R_mid_new=swingMid×R_mid_afterRoot`. Convert back to local rotations via inverse parent world rotations. Apply IK chain weight by shortest-arc SLERP between pre-IK and solved local rotations for **both joints**. End bone's authored local rotation remains unchanged; any requested effector orientation is **not solved** in v1 and MUST be returned as `UNSUPPORTED_ORIENTATION` unless separately authored as FK.

The solver MUST report the final endpoint error, model-space solved target, and `SOLVED` or `CLAMPED` status. Different applications may add terrain queries, but those cannot change the declared solver algorithm. Evaluate chains in ascending lexical `id`; overlapping chain bone sets are invalid in ADM-IK-1, avoiding order-dependent conflict. The chain never changes model root/world entity transform.

**Important offset note:** for v1 the solver places the `end` joint origin, not an arbitrary offset effector. `effectorOffset` MUST equal `[0,0,0]` for the TWO_BONE profile; a nonzero value is reserved for a later IK profile. The field is present to permit future extension but MUST be validated now.


## 21. Normative runtime evaluation order

1. Decode and validate the model's rest pose, skeleton profile, morph targets and external animation library metadata.
2. Resolve `EXACT` or `SEMANTIC` binding before playing a clip; on failure reject playback with a typed error, never bind by similarly spelled bone names.
3. Sample keyframes in each active clip at its mapped time; compute target normalized transforms and scalar channels.
4. Retarget semantic rotation deltas; evaluate layer overrides and additive passes by §18.
5. Evaluate expression bindings and external ARKit coefficient layer with explicit layer precedence; clamp final morph weights to [0,1]. Evaluate shader/PBR parameter tracks per §18.1; supply the resulting values to the material pipeline before rendering.
6. Build animated global FK joint transforms, then run enabled IK chains in lexical `id` order according to §20.
7. Apply morph target deltas to base mesh vertices, then apply skinning using the corrected joint transforms; compute final attachment transforms from corrected world joints.
8. Emit events and root-motion data; never automatically alter gameplay entity state.

An implementation that offers only asset decoding MAY omit the runtime evaluator, but MUST say so. The **reference evaluator** MUST implement all steps to obtain conformance with `ADM-ANIM-BLEND-1` and `ADM-IK-1`.


## 22. Colliders

`colliders`: array of descriptions with exactly one of the following shapes, each attached to a node:

```
{ "name"?: string, "node": u32, "shape": "BOX", "size": [x,y,z], "trigger"?: bool }
{ "name"?: string, "node": u32, "shape": "SPHERE", "radius": number, "trigger"?: bool }
{ "name"?: string, "node": u32, "shape": "CAPSULE", "radius": number, "height": number, "trigger"?: bool }
{ "name"?: string, "node": u32, "shape": "MESH", "mesh": u32, "trigger"?: bool }
```

All collider shapes are centered at their node local origin, oriented with node local axes and follow its world transform. BOX size is full side lengths with all components `>0`; SPHERE radius `>0`; CAPSULE is Y-aligned, total height including caps MUST be `>= 2*radius`. MESH references a mesh whose primitives are triangle lists and defines a triangle-soup collision surface in mesh-local coordinates; node transform locates the collider. `trigger` defaults false and denotes semantic overlap-only behavior, **not** an engine-defined event contract. Colliders MUST NOT imply mass, friction, restitution, rigid bodies, continuous collision detection, convex decomposition, or navigation semantics. Runtimes MUST expose shape descriptors faithfully; collision simulation behavior is implementation-specific and outside ADM-CORE.

## 23. LOD selection

`lodGroups`: array of `{ "name"?:string, "levels": [ { "node":u32, "minDistance":number }, ... ] }`. At least two levels. Node indices in a group MUST be distinct; each node MUST be a scene node. `minDistance` MUST be finite `>=0`, sorted strictly increasing, and level 0's minDistance MUST be 0. For an object instance, compute Euclidean distance in meters from world-space camera position to **world-space transform origin of the first group's level node**. Select level with the greatest minDistance `<= distance`. One group is a set of alternative **whole subtrees**: the selected node and descendants are visible; all other level nodes and descendants are hidden. Nodes and descendants in different LOD groups MUST NOT overlap, and no LOD level node may be ancestor/descendant of another level in the same group. Camera frustum culling and screen coverage are orthogonal. No implied crossfade/hysteresis: a renderer MAY add cosmetic transitions, but must select the same discrete level at thresholds. LOD selection affects only visibility; colliders are independent and remain active unless an application chooses otherwise.

## 24. Attachment points

`attachments`: array of `{ "name": string, "node": u32 }`. Names MUST be unique across the file, case-sensitive, and nonempty. An attachment is the transform of its referenced node in world space, with no additional offset: `W_attachment = W(node)`. The node may be under an animated joint, so the attachment follows that joint. Names are semantic contracts chosen by the asset author (e.g. `weapon_right`, `seat_driver`, `wheel_fl`); ADM does not assign gameplay meanings or spawn behavior. External engines MAY bind objects to attachments, but ADM 1.0 does not define external asset references.

## 25. Validation and interoperability acceptance suite

A final ADM 1.0 release MUST contain a versioned test corpus, independent conformance validator, and a formally separate collection of **positive and negative** tests. Minimum required cases:

| Fixture | Purpose / expected outcome |
|---|---|
| `triangle.adm` | basic 64-byte header, chunk directory, triangle, material defaults, exact vertex coordinates |
| `skinned_humanoid.adm` | 15 required humanoid semantic roles, 4-weight skinning, correct bind and neutral pose |
| `face_arkit52.adm` | complete mapping of 52 semantic face channels, expected vertex samples for `jawOpen=0,0.5,1` |
| `morph_and_skin.adm` | identical result applying morph **before** skinning |
| `walk_wounded.adm_anim` | library id `human@walking@wounded`, descriptions, clip timing and lookup |
| `walk_semantic.adm_anim` | retarget identity rotation to two humanoids with differing limb lengths |
| `two_bone_ik.adm` | reachable, unreachable, antipodal, weight=0, collinear-pole cases |
| `override_additive.adm_anim` | exact layering order, event crossings, quaternion shortest path |
| `shader_parameter_tracks.adm_anim` | animated `layer_factor` and portable PBR fallback, t=0/1/2 results and masking |
| `shader_layered.adm` | exact shader/version, binding IDs, deterministic two-layer linear blend, unsupported renderer fallback |
| `shader_custom_fallback.adm` | custom embedded schema, unknown shader fallback, unknown/mistyped parameter rejection |
| `bad_*.adm*` | truncation, overlapping chunks, decompression bombs, wrong SHA-256, dependency cycles, overflow, duplicate JSON key/name, NaN, nonexistent joint, external URI, missing description, invalid morph count, unknown version |

**Numerical comparison:** position and IK endpoint error ≤ 1e-4 meter or relative 1e-5 whichever larger; quaternion angular error ≤0.05 degrees; weights ≤1e-5 absolute. File parsing, references, lengths, magic, names and flags MUST match exactly. Readers MUST validate without opening Blender/Unity. All reference samples MUST specify times, inputs, expected world joint matrices, expected morph deformation and solver status. A vendor MUST pass all tests corresponding to its advertised profile; failing tests prevent a conformance claim.

**Deterministic metadata:** JSON member order does not matter; canonicalization is only required for exact-rig hash (§11.1), event payload ordering and test vectors. Runtimes MUST impose configurable input resource limits (prevent huge allocations, overflow, deeply nested JSON and decompression bombs) and report resource-limit errors distinctly from invalid encoding.

**Current state:** Draft 0.4 bundles newly regenerated 64-byte-header fixtures and negative container tests. The advanced fixtures above are mandatory acceptance criteria for release, **not claimed to exist yet**. Independent exporter/reader interoperability testing has **not** been performed for this revised specification.


## 26. Authoring rules for Blender and other DCC exporters

A Blender exporter MUST: convert from Blender Z-up to ADM Y-up (rotation `x,z,-y`), match triangle winding after conversion, convert UV to top-left V convention, export geometric data in mesh-local coordinates, freeze rest/bind and morph shape keys consistently, preserve named semantic role maps (not infer role solely from arbitrary bone names), check inverse bind matrices, write each morph target in identical vertex topology, export required clip descriptions and BCP-47 languages, expose shader registry and typed parameter controls, preserve `animationId` material bindings, validate shader-track channels and bounds, bake unsupported Blender node graphs to an explicit portable PBR fallback, avoid path-dependent external textures, and hard-fail on invalid semantic profiles.

When baking animation, the exporter MUST choose either `EXACT` absolute local TRS or `SEMANTIC` reference-rest delta rotations with correct metadata. It MUST NOT put raw source absolute rotations into a SEMANTIC library. For each clip, properties assigned to bones and face morphs MUST use §15 schema and §16 basis convention. Exporters MUST validate their own generated file with an independent file-level validator before declaring success.

A conforming viewer MUST: read the correct magic, parse and validate metadata and addressed chunk data without Blender dependency, render model without animation, display supported shader IDs and explicit fallback status, expose clip catalog and descriptions, bind semantic clip by profile, support morph target updates and ARKit 52 channels (for declared profile), optionally evaluate IK according to advertised profile, report unsupported optional advanced features explicitly. A preview application MAY display a simple neutral material when PBR shading is not supported but cannot claim exact PBR visual conformance.


## 27. Examples — independent files and library lookup

**Model manifest excerpt** (supplemental fields; merge with §§4–8 required core members; the node numbers below are placeholders and must resolve):

```json
{
  "skeletonProfiles": [{
    "id":"humanoid.vrm1","skin":0,"referencePose":"T",
    "roles":{"hips":0,"spine":1,"head":2,"leftUpperLeg":3,"leftLowerLeg":4,"leftFoot":5,
             "rightUpperLeg":6,"rightLowerLeg":7,"rightFoot":8,"leftUpperArm":9,
             "leftLowerArm":10,"leftHand":11,"rightUpperArm":12,"rightLowerArm":13,"rightHand":14}
  }],
  "facialProfiles":[{"id":"face.arkit52.v1","coverage":"partial",
     "bindings":[{"channel":"jawOpen","node":20,"target":"jawOpen"}]}],
  "ikChains":[{"id":"leftLeg","solver":"TWO_BONE","root":3,"mid":4,"end":5,"pole":[0,0,1]}]
}
```

**Animation manifest excerpt** (clip samplers omitted because chunk-addressed animation data must be supplied by actual exporter):

```json
{
  "asset":{"generator":"ADM example"},
  "library":{"id":"human@walking@wounded","title":"Wounded walk set",
    "description":"Locomotion clips for wounded human characters.","language":"en",
    "targetProfile":"humanoid.vrm1","binding":"SEMANTIC"},
  "clips":[{"id":"walk1","title":"Limp left","description":"Slow walk favoring right leg.",
    "language":"en","duration":1.6,"loop":"REPEAT","rootMotion":"IN_PLACE",
    "channels":[],"samplers":[],"tags":["limping","locomotion","wounded"]}],
  "bufferViews":[],"accessors":[]
}
```

The full identifier is `human@walking@wounded:walk1`. The application may show the text description for catalog search without loading animation keyframes. An empty `channels` array is a valid *metadata-only/no-op clip*, useful for testing the catalog; a real movement clip MUST contain data-bearing channels.

**Model instantiation:** a single `.adm` may have hundreds of nodes and many meshes. The `.adm_anim` library does not reference the model filename, uses the target profile, and may animate any model validating against that profile. Nothing in this example causes an NPC to move automatically; a host chooses when/where it evaluates the clip.


## 28. Version policy, extension registry, and open standard governance

Any change to binary header, semantics, required fields, or published interpolation/IK math is a MAJOR revision. A MINOR revision may add **explicitly optional** fields that 1.0 readers can safely ignore only when declared via a recognized extension; files with minor>0 require a reader that explicitly supports that minor version. Unknown required extensions MUST be rejected; optional extensions may be ignored only when doing so preserves core meaning. `extensionsRequired` MUST be subset of `extensionsUsed`, and extension IDs MUST be versioned in registry documents. Custom skeleton profile IDs MUST be versioned and published with validation rules and example rigs before advertised interoperable.

Suggested repository layout:

```text
spec/
  ADM-1.0-SPEC.md           # this normative master document
  schemas/                 # JSON Schema for both manifest kinds
  profiles/                # pinned humanoid/face and normative vehicle/weapon annexes; future animal profiles
  registry/                # namespace/extension ID registry and immutable shader profiles
  fixtures/valid/          # byte-perfect samples and expected evaluator output
  fixtures/invalid/        # validation failures with codes
  reference/               # engine-independent reader and animation evaluator
  CHANGELOG.md
```

Recommended source citation references:

- glTF 2.0: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
- VRM 1.0 humanoid roles: https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md
- VRM Animation 1.0: https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm_animation-1.0/README.md
- Apple ARKit named coefficients: https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation/

**Release blockers (not optional):** freeze the full VRM role registry snapshot including all optional bones; publish numerical calibrated T-pose fixtures and canonical rig fingerprint example; publish fully valid anim/morph/IK/shader-animation fixture bytes with expected samples; freeze shader registry schemas and material-layer extension; implement independent parsers/evaluators; test branch/error paths, out-of-bounds handling, right/left anatomy and morphology. Until then this text is a **serious engineering draft**, not a verified final international standard.



## 29. Native runtime profiles for vehicles, weapons, modular models and physical metadata

This section defines **asset descriptors**, not runtime game behavior. Every ordinary ADM-CORE-1 reader MUST parse or safely reject unsupported optional profile features; it need not implement vehicle dynamics, weapon firing, damage, inventory, networking or simulation.

### 29.1 Model components and semantic sockets

`modelComponents` optional list: `{ "id":string, "role":string, "node":u32, "socket"?:string }` with unique IDs matching `[a-z][a-z0-9_.]*`; `role` is a published profile role or qualified custom role. `node` resolves an existing node. If `socket` appears, it MUST match an attachment in §24. Two component records MUST NOT have the same `id`. This permits identifying detachable parts without prescribing how they detach. An assembly system SHOULD use attachments with explicit stable local transforms; per-entity attachment decisions are outside ADM. External model asset dependencies are not mandatory for core: engines MAY assemble separate `.adm` files via these semantic sockets. No external file URI is implied by a component record.

### 29.2 Vehicle model profile — status provisional

`vehicle.car.v1` is **defined by incorporated normative annex `profiles/vehicle.car.v1.md`**, with its role list, +X wheel roll axes, +Y steering, hinge metadata, multiple consecutive axle records, socket alignment, role-preserving LODs and semantic animation. The annex defines `ADM-VEHICLE-CAR-1` and `VEH-001..006`. It describes visual and collision asset data only: vehicle dynamics, drivetrains, steering controller and damage logic are not part of ADM. **Profile design is now complete; independent certification fixtures remain pending.**

### 29.3 Weapon modularity — status provisional

`weapon.firearm.v1` is **defined by incorporated normative annex `profiles/weapon.firearm.v1.md`**, with required receiver/muzzle roles, optional moving visual mechanisms, normalized attachment frames, exact versioned mount interfaces, visual animation and `weapon.attachment.v1` for modular accessories. The annex defines `ADM-WEAPON-FIREARM-1` and `WPN-001..006`. Ballistics, damage, firing mechanisms, inventory, aiming controllers and other gameplay systems are not represented. **Profile design is now complete; independent certification fixtures remain pending.**

### 29.4 Physical metadata and bone hitboxes

`physicalMaterials` optional: `{ "id": string, "friction": number, "restitution": number }` with unique IDs and coefficients in [0,1]. These represent suggested static coefficients; runtime contact solver semantics are outside ADM. Each collider from §22 MAY declare `physicalMaterial` (string ref). `hitboxes` optional: `{ "id": string, "collider":u32, "boneNode"?:u32, "role"?:string }` with unique IDs and valid references; the hitbox attaches to its collider's transform, `boneNode` when present MUST be the collider's node or ancestor. The `role` is semantic only (e.g. `head`, `torso`), not damage calculation. These fields never trigger gameplay or physical simulation.

### 29.5 Production readiness gates

For a high-speed racing-game model pipeline: chunk streaming, independently readable LODs, standalone portable PBR materials, mechanical sockets, physical collision descriptors and robust invalid-file handling MUST be tested. For a detailed extraction-shooter model pipeline: attachment round-trips, morph/skin fidelity, shared animation library retargeting, weapon modularity fixtures, low-latency material fallback and asset caching MUST be tested. Profile certification requires `VEH-001..006` or `WPN-001..006` test success; ordinary `ADM-CORE-1` asset support does not require either mechanical profile.

## 30. Draft 0.4 mandatory conformance additions

`CONT-001`: header 64 bytes, exact field offsets, magic and region bounds. `CONT-002`: sorted unique chunk IDs, aligned nonoverlapping payloads and zero padding. `CONT-003`: SHA-256 mismatch detected when chunk is consumed. `CONT-004`: RAW and optional ZSTD decoding; unsupported codec must raise exact capability error. `CONT-005`: dependency closure deterministic and acyclic. `CONT-006`: parser can inspect manifest and list clips/materials **with zero payload reads**. `CONT-007`: fetch one mesh/texture/clip without loading all other chunks. `CONT-008`: malicious length/offset/overflow, truncated and zip-bomb-like content rejected without unsafe allocation. `CONT-009`: requested LOD can load independently of higher LOD when manifest dependencies permit it.

`MAT-001`: fully registered layered material produces normative material parameters at sample UV. `MAT-002`: unsupported advanced shader uses core PBR fallback textures without requiring advanced code or data. `MAT-003`: any non-core shader lacking one of the explicit fallback properties required in §8 MUST be rejected with `ADM_ERR_MISSING_PBR_FALLBACK`. `MAT-004`: PBR animation continues on fallback when advanced shader parameters are unsupported; unsupported **optional** specialized tracks are skipped with diagnostics. `MAT-005`: KTX2 or DDS primary with PNG/JPEG alternate resolves correctly in a core reader (fallback chosen) and in a reader advertising `ADM-TEX-KTX2-1`/`ADM-TEX-DDS-1` (primary decoded per §8.6 with matching dimensions and colour space). `TEX-001`: GPU image outside the §8.6 subset (supercompressed, array, cubemap, unregistered format, wrong level size, trailing bytes, legacy DDS header) is `IMAGE_DECODE`. `TEX-002`: missing fallback or fallback with different size is rejected. `TEX-003`: sRGB/UNORM variant mismatching the texture role is `IMAGE_COLORSPACE`.

`ANIM-001`: clip metadata retrievable without loading ANIM chunks. `ANIM-002`: semantic humanoid rotations on distinct proportions conform to §16. `ANIM-003`: morph + skin evaluation order and ARKit52 channel mapping. `ANIM-004`: reachability, pole and twist cases for two-bone IK. `ANIM-005`: shader material ID binding and fallback animation results with exact times. `MOD-001`: attachment IDs and node transforms preserved through re-export. `PHYS-001`: collider/hitbox metadata round-trips without engine-specific behavior assumptions.

**Profile conformance:** `VEH-001..006` and `WPN-001..006` are defined in the normative annexes, with a structural fixture set and a separate baseline validator. These are NOT yet a complete numerical animation or Blender round-trip certification suite. Skeleton profile tests `HUM-001..006` (annex `profiles/humanoid.vrm1.md`) and the provisional `QDR-001..004` (annex `profiles/animal.quadruped.v1.md`) are executed by the reference Blender toolkit; an independent second implementation is still required.

**Status:** This kit includes a working **container-only** validator and lightweight examples covering `CONT-001..003`, `CONT-005` and initial manifest decoding. It does NOT include complete numerical animation solvers, renderer golden images or a full semantic validator; KTX2/DDS subset checks (§8.6) exist only in the Blender add-on's validator. Consequently this document is **Draft 0.4, not a ratified/certified release**. No vendor may claim full ADM 1.0 conformance from the included scripts alone.


## 31. Incorporated normative mechanical profile annexes

The following files are normative components of this Draft 0.4 revision, not external optional commentary. A tool claiming the named profile MUST implement both §29 and its corresponding annex. `profiles/vehicle.car.v1.md` defines `ADM-VEHICLE-CAR-1`; `profiles/weapon.firearm.v1.md` defines `ADM-WEAPON-FIREARM-1` and modular `weapon.attachment.v1`. Ambiguities are errors, not permission to guess: discrepancy between the core document and an annex MUST be reported and resolved before profile certification. Per §28 the final registry is version-pinned at publication.

**Skeleton profile annexes (revision P4):** `profiles/skeleton-profiles.json` (machine-readable registry), `profiles/humanoid.vrm1.md` (normative humanoid role, reference-pose and retarget rules) and `profiles/animal.quadruped.v1.md` (PROVISIONAL, non-normative). Approval and certification blockers are listed in `SPEC_GAPS.md`.
