"""GPU texture containers of the ADM texture registry (spec §8.6).

``ADM-TEX-KTX2-1`` and ``ADM-TEX-DDS-1`` share one payload subset: a single 2D image with one or more
mip levels in RGBA8, BC1 or BC3, each in an UNORM or sRGB variant. KTX2 must not be supercompressed;
DDS must carry the DX10 extended header. Header parsing is pure Python (used by the validator);
encoding/decoding needs numpy and is imported lazily.
"""

import struct

KTX2_MAGIC = b"\xabKTX 20\xbb\r\n\x1a\n"
DDS_MAGIC = b"DDS "
MIME_KTX2 = "image/ktx2"
MIME_DDS = "image/vnd-ms.dds"
KINDS = ("RGBA8", "BC1", "BC3")

# kind -> (bytes per block, block edge in texels)
_BLOCK = {"RGBA8": (4, 1), "BC1": (8, 4), "BC3": (16, 4)}

_VK = {37: ("RGBA8", False), 43: ("RGBA8", True), 131: ("BC1", False), 132: ("BC1", True),
       133: ("BC1", False), 134: ("BC1", True), 137: ("BC3", False), 138: ("BC3", True)}
_VK_WRITE = {("RGBA8", False): 37, ("RGBA8", True): 43, ("BC1", False): 131, ("BC1", True): 132,
             ("BC3", False): 137, ("BC3", True): 138}
_DFD_MODEL = {"RGBA8": 1, "BC1": 128, "BC3": 130}   # KHR_DF_MODEL_RGBSDA / BC1A / BC3
_DXGI = {28: ("RGBA8", False), 29: ("RGBA8", True), 71: ("BC1", False), 72: ("BC1", True),
         77: ("BC3", False), 78: ("BC3", True)}
_DXGI_WRITE = {v: k for k, v in _DXGI.items()}

_DDSD_CAPS, _DDSD_HEIGHT, _DDSD_WIDTH, _DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
_DDSD_PIXELFORMAT, _DDSD_MIPMAPCOUNT, _DDSD_LINEARSIZE, _DDSD_DEPTH = 0x1000, 0x20000, 0x80000, 0x800000
_DDPF_ALPHAPIXELS, _DDPF_FOURCC, _DDPF_RGB = 0x1, 0x4, 0x40
_DDSCAPS_COMPLEX, _DDSCAPS_TEXTURE, _DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000
_DDSCAPS2_CUBEMAP, _DDSCAPS2_VOLUME = 0x200, 0x200000


class GpuTextureError(ValueError):
    pass


def level_size(kind, w, h):
    nbytes, edge = _BLOCK[kind]
    return ((w + edge - 1) // edge) * ((h + edge - 1) // edge) * nbytes


def max_levels(w, h):
    return max(w, h).bit_length()


def _level_dims(w, h, n):
    return [(max(1, w >> i), max(1, h >> i)) for i in range(n)]


def mime_of(blob):
    if blob.startswith(KTX2_MAGIC):
        return MIME_KTX2
    if blob.startswith(DDS_MAGIC):
        return MIME_DDS
    return None


# ================================================================================================
# parsing (pure Python)
# ================================================================================================
def parse(blob, mime, strict=True):
    """Return ``{"kind", "srgb", "width", "height", "levels": [(offset, length, w, h), ...]}``.

    ``strict`` enforces the ADM registry subset; non-strict also accepts legacy DDS (DXT1/DXT5,
    32-bit RGB(A) masks) for converting source textures.
    """
    if mime == MIME_KTX2:
        return _parse_ktx2(bytes(blob))
    if mime == MIME_DDS:
        return _parse_dds(bytes(blob), strict)
    raise GpuTextureError(f"not a GPU texture mime type: {mime!r}")


def _check_levels(blob, kind, w, h, levels, align):
    if w < 1 or h < 1:
        raise GpuTextureError("width/height must be >= 1")
    if not 1 <= len(levels) <= max_levels(w, h):
        raise GpuTextureError(f"level count {len(levels)} outside 1..{max_levels(w, h)}")
    out = []
    for i, ((off, length), (lw, lh)) in enumerate(zip(levels, _level_dims(w, h, len(levels)))):
        want = level_size(kind, lw, lh)
        if length != want:
            raise GpuTextureError(f"level {i}: {length} bytes, expected {want}")
        if off < 0 or off + length > len(blob):
            raise GpuTextureError(f"level {i}: data outside the image")
        if align and off % align:
            raise GpuTextureError(f"level {i}: offset {off} not aligned to {align}")
        out.append((off, length, lw, lh))
    return out


def _parse_ktx2(blob):
    if len(blob) < 80 or not blob.startswith(KTX2_MAGIC):
        raise GpuTextureError("missing KTX2 identifier")
    vk, type_size, w, h, depth, layers, faces, nlevels, scheme = struct.unpack_from("<9I", blob, 12)
    dfd_off, dfd_len, kvd_off, kvd_len, sgd_off, sgd_len = struct.unpack_from("<4I2Q", blob, 48)
    if vk not in _VK:
        raise GpuTextureError(f"vkFormat {vk} is outside the ADM KTX2 subset")
    kind, srgb = _VK[vk]
    if type_size != 1:
        raise GpuTextureError("typeSize must be 1")
    if depth != 0 or layers != 0 or faces != 1:
        raise GpuTextureError("only a single 2D image is allowed (no depth, array or cubemap)")
    if scheme != 0 or sgd_len != 0:
        raise GpuTextureError("supercompression is outside the ADM KTX2 subset")
    if nlevels == 0:
        raise GpuTextureError("levelCount 0 (runtime-generated mips) is not allowed")
    if 80 + 24 * nlevels > len(blob):
        raise GpuTextureError("truncated level index")
    raw = [struct.unpack_from("<3Q", blob, 80 + 24 * i) for i in range(nlevels)]
    for i, (_, length, uncompressed) in enumerate(raw):
        if length != uncompressed:
            raise GpuTextureError(f"level {i}: compressed level data is not allowed")
    nbytes = _BLOCK[kind][0]
    align = nbytes * 4 // _gcd(nbytes, 4)
    levels = _check_levels(blob, kind, w, h, [(o, n) for o, n, _ in raw], align)
    if dfd_len < 28 or dfd_off + dfd_len > len(blob) or dfd_off % 4:
        raise GpuTextureError("invalid data format descriptor range")
    total, = struct.unpack_from("<I", blob, dfd_off)
    model, _, transfer = struct.unpack_from("<3B", blob, dfd_off + 12)
    if total != dfd_len:
        raise GpuTextureError("dfdTotalSize does not match dfdByteLength")
    if model != _DFD_MODEL[kind]:
        raise GpuTextureError(f"DFD color model {model} does not match vkFormat {vk}")
    if transfer != (2 if srgb else 1):
        raise GpuTextureError("DFD transfer function does not match the sRGB/UNORM vkFormat")
    if kvd_len and kvd_off + kvd_len > len(blob):
        raise GpuTextureError("invalid key/value data range")
    end = max([dfd_off + dfd_len, kvd_off + kvd_len] + [o + n for o, n, _, _ in levels])
    if end != len(blob):
        raise GpuTextureError("trailing bytes after the last KTX2 section")
    return {"kind": kind, "srgb": srgb, "width": w, "height": h, "levels": levels}


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _parse_dds(blob, strict):
    if len(blob) < 128 or not blob.startswith(DDS_MAGIC):
        raise GpuTextureError("missing DDS magic")
    size, flags, h, w, _pitch, depth, mips = struct.unpack_from("<7I", blob, 4)
    pf_size, pf_flags, fourcc, bits, rmask, gmask, bmask, amask = struct.unpack_from("<2I4s5I", blob, 76)
    _caps, caps2 = struct.unpack_from("<2I", blob, 108)
    if size != 124 or pf_size != 32:
        raise GpuTextureError("invalid DDS header size")
    if flags & _DDSD_DEPTH or caps2 & (_DDSCAPS2_CUBEMAP | _DDSCAPS2_VOLUME):
        raise GpuTextureError("only a single 2D image is allowed (no volume or cubemap)")
    nlevels = mips if (flags & _DDSD_MIPMAPCOUNT and mips) else 1
    offset = 128
    swizzle = None
    if pf_flags & _DDPF_FOURCC and fourcc == b"DX10":
        if len(blob) < 148:
            raise GpuTextureError("truncated DX10 header")
        dxgi, dim, misc, array_size, _alpha = struct.unpack_from("<5I", blob, 128)
        if dxgi not in _DXGI:
            raise GpuTextureError(f"DXGI format {dxgi} is outside the ADM DDS subset")
        if dim != 3 or misc & 0x4 or array_size != 1:
            raise GpuTextureError("only a single 2D texture is allowed (no array or cubemap)")
        kind, srgb = _DXGI[dxgi]
        offset = 148
    elif strict:
        raise GpuTextureError("ADM DDS requires the DX10 extended header")
    elif pf_flags & _DDPF_FOURCC and fourcc in (b"DXT1", b"DXT5"):
        kind, srgb = ("BC1" if fourcc == b"DXT1" else "BC3"), False
    elif pf_flags & _DDPF_RGB and bits == 32:
        kind, srgb = "RGBA8", False
        amask = amask if pf_flags & _DDPF_ALPHAPIXELS else 0
        swizzle = (rmask, gmask, bmask, amask)
    else:
        raise GpuTextureError("unsupported legacy DDS pixel format")
    sizes = [level_size(kind, lw, lh) for lw, lh in _level_dims(w, h, nlevels)]
    offsets = [offset + sum(sizes[:i]) for i in range(nlevels)]
    levels = _check_levels(blob, kind, w, h, list(zip(offsets, sizes)), 0)
    if strict and offset + sum(sizes) != len(blob):
        raise GpuTextureError("trailing bytes after the last DDS level")
    info = {"kind": kind, "srgb": srgb, "width": w, "height": h, "levels": levels}
    if swizzle:
        info["masks"] = swizzle
    return info


def _dims_of_png(blob):
    if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24 and blob[12:16] == b"IHDR":
        return struct.unpack_from(">2I", blob, 16)
    return None


def _dims_of_jpeg(blob):
    i = 2
    while i + 9 < len(blob):
        if blob[i] != 0xFF:
            return None
        marker = blob[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length, = struct.unpack_from(">H", blob, i + 2)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack_from(">2H", blob, i + 5)
            return w, h
        i += 2 + length
    return None


def portable_dims(blob, mime):
    """(width, height) of a PNG/JPEG image, or None when it cannot be determined cheaply."""
    return _dims_of_png(blob) if mime == "image/png" else _dims_of_jpeg(blob)


# ================================================================================================
# encoding (numpy)
# ================================================================================================
def _srgb_to_linear(c):
    import numpy as np
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c):
    import numpy as np
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def mip_chain(rgba, srgb, mipmaps=True):
    """uint8 (h, w, 4) -> list of uint8 levels, box-filtered (in linear light for sRGB colour)."""
    import numpy as np
    levels = [np.ascontiguousarray(rgba, dtype=np.uint8)]
    if not mipmaps:
        return levels
    f = rgba.astype(np.float64) / 255.0
    if srgb:
        f[..., :3] = _srgb_to_linear(f[..., :3])
    while f.shape[0] > 1 or f.shape[1] > 1:
        h, w = f.shape[:2]
        if h > 1:
            f = 0.5 * (f[0:h - h % 2:2] + f[1:h - h % 2 + 1:2])
        if w > 1:
            f = 0.5 * (f[:, 0:w - w % 2:2] + f[:, 1:w - w % 2 + 1:2])
        out = f.copy()
        if srgb:
            out[..., :3] = _linear_to_srgb(out[..., :3])
        levels.append((np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    return levels


def _blocks(px):
    """uint8 (h, w, 4) -> (n, 16, 4) 4x4 blocks in row-major block order (edges replicated)."""
    import numpy as np
    h, w = px.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        px = np.pad(px, ((0, ph), (0, pw), (0, 0)), mode="edge")
    bh, bw = px.shape[0] // 4, px.shape[1] // 4
    return px.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 4)


def _expand565(c):
    import numpy as np
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.int32)


def _encode_color_blocks(blk):
    """(n, 16, 4) uint8 -> (n, 8) uint8 BC1 colour blocks in 4-colour mode (alpha ignored)."""
    import numpy as np
    n = blk.shape[0]
    col = blk[..., :3].astype(np.float64)
    mean = col.mean(1)
    cen = col - mean[:, None]
    cov = np.einsum("nki,nkj->nij", cen, cen)
    axis = np.ones((n, 3))
    for _ in range(8):
        axis = np.einsum("nij,nj->ni", cov, axis)
        norm = np.linalg.norm(axis, axis=1, keepdims=True)
        axis = np.where(norm > 1e-9, axis / np.maximum(norm, 1e-12), 1.0 / np.sqrt(3.0))
    proj = np.einsum("nki,ni->nk", cen, axis)
    hi = np.clip(mean + axis * proj.max(1)[:, None], 0, 255)
    lo = np.clip(mean + axis * proj.min(1)[:, None], 0, 255)

    def q565(c):
        r = np.rint(c[:, 0] * 31 / 255).astype(np.int32)
        g = np.rint(c[:, 1] * 63 / 255).astype(np.int32)
        b = np.rint(c[:, 2] * 31 / 255).astype(np.int32)
        return (r << 11) | (g << 5) | b

    c0, c1 = q565(hi), q565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    p0, p1 = _expand565(c0), _expand565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], 1)          # (n, 4, 3)
    d = ((blk[:, :, None, :3].astype(np.int32) - pal[:, None]) ** 2).sum(-1)     # (n, 16, 4)
    idx = d.argmin(-1).astype(np.uint32)
    idx[c0 == c1] = 0
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1, dtype=np.uint64).astype(np.uint32)
    out = np.empty(n, dtype=[("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")])
    out["c0"], out["c1"], out["i"] = c0, c1, bits
    return out.view(np.uint8).reshape(n, 8)


def _encode_alpha_blocks(blk):
    """(n, 16, 4) uint8 -> (n, 8) uint8 BC3/BC4 alpha blocks in 8-value mode."""
    import numpy as np
    n = blk.shape[0]
    a = blk[..., 3].astype(np.int32)
    a0, a1 = a.max(1), a.min(1)
    pal = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)], 1)   # (n, 8)
    idx = np.abs(a[:, :, None] - pal[:, None]).argmin(-1).astype(np.uint64)
    idx[a0 == a1] = 0
    bits = (idx << (3 * np.arange(16, dtype=np.uint64))).sum(1, dtype=np.uint64)
    out = np.zeros((n, 8), dtype=np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for k in range(6):
        out[:, 2 + k] = (bits >> np.uint64(8 * k)) & np.uint64(0xFF)
    return out


def encode_level(px, kind):
    import numpy as np
    if kind == "RGBA8":
        return np.ascontiguousarray(px, dtype=np.uint8).tobytes()
    blk = _blocks(np.ascontiguousarray(px, dtype=np.uint8))
    color = _encode_color_blocks(blk)
    if kind == "BC1":
        return color.tobytes()
    return np.concatenate([_encode_alpha_blocks(blk), color], 1).tobytes()


def _dfd(kind, srgb):
    transfer = 2 if srgb else 1
    alpha_linear = 0x10 if srgb else 0
    if kind == "RGBA8":
        dims, plane = (0, 0, 0, 0), 4
        samples = [(0, 7, 0, 255), (8, 7, 1, 255), (16, 7, 2, 255), (24, 7, 15 | alpha_linear, 255)]
    elif kind == "BC1":
        dims, plane = (3, 3, 0, 0), 8
        samples = [(0, 63, 0, 0xFFFFFFFF)]
    else:
        dims, plane = (3, 3, 0, 0), 16
        samples = [(0, 63, 15 | alpha_linear, 0xFFFFFFFF), (64, 63, 0, 0xFFFFFFFF)]
    block = struct.pack("<IHH4B4B8B", 0, 2, 24 + 16 * len(samples), _DFD_MODEL[kind], 1, transfer, 0,
                        *dims, plane, 0, 0, 0, 0, 0, 0, 0)
    for off, length, chan, upper in samples:
        block += struct.pack("<HBB4BII", off, length, chan, 0, 0, 0, 0, 0, upper)
    return struct.pack("<I", 4 + len(block)) + block


def _kvd():
    kv = b"KTXwriter\x00ADM Tools for Blender\x00"
    data = struct.pack("<I", len(kv)) + kv
    return data + bytes((-len(data)) % 4)


def write_ktx2(levels, kind, srgb):
    """levels: list of uint8 (h, w, 4) arrays, level 0 first."""
    h, w = levels[0].shape[:2]
    data = [encode_level(px, kind) for px in levels]
    n = len(levels)
    dfd = _dfd(kind, srgb)
    kvd = _kvd()
    dfd_off = 80 + 24 * n
    kvd_off = dfd_off + len(dfd)
    nbytes = _BLOCK[kind][0]
    align = nbytes * 4 // _gcd(nbytes, 4)
    body = bytearray()
    pos = kvd_off + len(kvd)
    index = [None] * n
    for i in reversed(range(n)):                     # smallest mip first (KTX2 §3.9.7)
        pad = (-pos) % align
        body += bytes(pad)
        pos += pad
        index[i] = (pos, len(data[i]), len(data[i]))
        body += data[i]
        pos += len(data[i])
    head = KTX2_MAGIC + struct.pack("<9I", _VK_WRITE[(kind, srgb)], 1, w, h, 0, 0, 1, n, 0)
    head += struct.pack("<4I2Q", dfd_off, len(dfd), kvd_off, len(kvd), 0, 0)
    for entry in index:
        head += struct.pack("<3Q", *entry)
    return bytes(head) + dfd + kvd + bytes(body)


def write_dds(levels, kind, srgb):
    h, w = levels[0].shape[:2]
    data = b"".join(encode_level(px, kind) for px in levels)
    n = len(levels)
    flags = _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH | _DDSD_PIXELFORMAT
    flags |= _DDSD_PITCH if kind == "RGBA8" else _DDSD_LINEARSIZE
    caps = _DDSCAPS_TEXTURE
    if n > 1:
        flags |= _DDSD_MIPMAPCOUNT
        caps |= _DDSCAPS_COMPLEX | _DDSCAPS_MIPMAP
    pitch = w * 4 if kind == "RGBA8" else level_size(kind, w, h)
    head = DDS_MAGIC + struct.pack("<7I44x", 124, flags, h, w, pitch, 0, n)
    head += struct.pack("<2I4s5I", 32, _DDPF_FOURCC, b"DX10", 0, 0, 0, 0, 0)
    head += struct.pack("<5I", caps, 0, 0, 0, 0)
    alpha_mode = 3 if kind == "BC1" else 1           # DDS_ALPHA_MODE_OPAQUE / STRAIGHT
    head += struct.pack("<5I", _DXGI_WRITE[(kind, srgb)], 3, 0, 1, alpha_mode)
    return head + data


def encode(rgba, mime, kind="AUTO", srgb=False, mipmaps=True):
    """Encode uint8 (h, w, 4) top-to-bottom pixels as an ADM-subset KTX2 or DDS image.

    ``kind`` AUTO picks BC3 when any texel is not fully opaque, otherwise BC1.
    """
    import numpy as np
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    if kind == "AUTO":
        kind = "BC3" if (rgba[..., 3] < 255).any() else "BC1"
    if kind not in KINDS:
        raise GpuTextureError(f"unknown texture format {kind!r}")
    levels = mip_chain(rgba, srgb, mipmaps)
    if mime == MIME_KTX2:
        return write_ktx2(levels, kind, srgb), kind
    if mime == MIME_DDS:
        return write_dds(levels, kind, srgb), kind
    raise GpuTextureError(f"not a GPU texture mime type: {mime!r}")


# ================================================================================================
# decoding (numpy)
# ================================================================================================
def _decode_color(raw, four_color, punch_alpha):
    """(n, 8) uint8 -> (n, 16, 4) uint8."""
    import numpy as np
    n = raw.shape[0]
    rec = raw.copy().view(dtype=[("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")]).reshape(n)
    c0, c1 = rec["c0"].astype(np.int32), rec["c1"].astype(np.int32)
    p0, p1 = _expand565(c0), _expand565(c1)
    mode4 = np.ones(n, bool) if four_color else c0 > c1
    p2 = np.where(mode4[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(mode4[:, None], (p0 + 2 * p1) // 3, 0)
    pal = np.stack([p0, p1, p2, p3], 1)
    alpha = np.full((n, 4), 255, np.int32)
    if punch_alpha:
        alpha[~mode4, 3] = 0
    idx = (rec["i"][:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    rows = np.arange(n)[:, None]
    out = np.empty((n, 16, 4), np.uint8)
    out[..., :3] = pal[rows, idx]
    out[..., 3] = alpha[rows, idx]
    return out


def _decode_alpha(raw):
    import numpy as np
    n = raw.shape[0]
    a0, a1 = raw[:, 0].astype(np.int32), raw[:, 1].astype(np.int32)
    eight = a0 > a1
    pal8 = [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]
    pal6 = [((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)] + [np.zeros(n, np.int32), np.full(n, 255)]
    pal = np.stack([a0, a1] + [np.where(eight, x, y) for x, y in zip(pal8, pal6)], 1)
    bits = np.zeros(n, np.uint64)
    for k in range(6):
        bits |= raw[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    idx = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.intp)
    return pal[np.arange(n)[:, None], idx].astype(np.uint8)


def decode_level(blob, info, level=0, rgb_only=False):
    """Decode one level to uint8 (h, w, 4), rows top-to-bottom.

    ``rgb_only`` marks BC1 RGB formats, whose 3-colour-mode black texel stays opaque.
    """
    import numpy as np
    off, length, w, h = info["levels"][level]
    raw = np.frombuffer(blob, np.uint8, length, off)
    kind = info["kind"]
    if kind == "RGBA8":
        px = raw.reshape(h, w, 4)
        masks = info.get("masks")
        if masks:
            v = px.copy().view("<u4").reshape(h, w)
            chans = []
            for i, m in enumerate(masks):
                if not m:
                    chans.append(np.full((h, w), 255, np.uint8))
                    continue
                shift = (m & -m).bit_length() - 1
                chans.append(((v & m) >> shift).astype(np.uint8))
            px = np.stack(chans, -1)
        return np.array(px, dtype=np.uint8)
    nblk = _BLOCK[kind][0]
    raw = raw.reshape(-1, nblk)
    if kind == "BC1":
        out = _decode_color(raw, False, not rgb_only)
    else:
        out = _decode_color(raw[:, 8:], True, False)
        out[..., 3] = _decode_alpha(raw[:, :8])
    bh, bw = (h + 3) // 4, (w + 3) // 4
    img = out.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:h, :w])


def decode(blob, mime=None, strict=False):
    """Decode level 0 of a KTX2/DDS image -> (uint8 (h, w, 4), info)."""
    mime = mime or mime_of(blob)
    info = parse(blob, mime, strict)
    rgb_only = mime == MIME_KTX2 and struct.unpack_from("<I", blob, 12)[0] in (131, 132)
    return decode_level(blob, info, 0, rgb_only), info
