# `ADM_external_images_v1`

Version 1.0.0, incorporated by ADM Draft 0.4 P10.

## Declaration and image schema

Any file containing an external image MUST list `ADM_external_images_v1` in both `extensionsUsed`
and `extensionsRequired`. Each image has exactly one source:

```json
{"uri":"textures/wall.png","mimeType":"image/png","sha256":"<optional lowercase SHA-256>"}
```

or the existing embedded form:

```json
{"bufferView":0,"mimeType":"image/png"}
```

`bufferView` and `uri` MUST NOT coexist or both be absent. An external image MAY have `name` and
MAY have `sha256`, a 64-character lowercase hexadecimal digest of the complete file bytes. A
present digest MUST be checked by the resolver. The MIME allowlist is the ADM 1.0 image subset:
PNG, baseline JPEG, the registered KTX2 subset and the registered DDS subset.

An external URI is a normalized, portable, relative path. It MUST use `/`, ASCII letters/digits,
underscore, hyphen or dot in each segment; empty, `.` and `..` segments; trailing dots; Windows
device names; drive/scheme prefixes; absolute paths; percent escapes; backslashes; and control
characters are forbidden. Network URLs and automatic downloads are forbidden.

External KTX2/DDS images obey the same `fallbackSource` requirement as embedded GPU images. The
fallback MAY itself be embedded or external; when external, it is resolved against the same asset
root. The primary and fallback MUST have equal dimensions. A reader without GPU texture support MUST
use the fallback. If the primary is unavailable but the fallback is available, a reader MAY use the
fallback and MUST report that it did so. If the fallback is unavailable, the texture is incomplete.

## Resolution and validation

Structural validation checks the URI syntax, MIME, source exclusivity, image/texture references and
extension declaration without touching the filesystem. Resolved validation uses a host resolver and
checks availability, regular-file status, declared MIME, supported texture subset, dimensions and
the optional SHA-256. Missing external files are resource-resolution errors, not ADM-container
corruption.

The default Blender resolver joins the URI to the directory containing the imported `.adm`. The
canonical resolved path MUST remain beneath that root after symlink resolution. Resolvers MUST NOT
fetch remote data or follow a reference outside the configured asset root. Engines MAY instead
implement `resolveTexture(assetContext, relativeURI)` over a virtual filesystem, pack, bundle or
cache; ADM does not serialize a machine-specific root.

## Export behavior

`Embed Textures` defaults to enabled. Embedded export is unchanged. With embedding disabled, the
writer copies each referenced encoded image to a deterministic path under `textures/`, writes only
its relative URI (and SHA-256) in the ADM, and MUST finish all required copies before reporting a
successful export. Identical bytes are shared. Existing files are never overwritten unless their
bytes are identical. A failed sidecar write MUST fail the export; it MUST NOT leave an ADM that
claims success with missing resources.

## Status

The extension does not alter material color-space, sampler, fallback or shader semantics. Embedded
and external sources containing identical image bytes are semantically identical. Blender
round-trip, resolver-security and image-format fixtures are required before conformance can be
claimed.
