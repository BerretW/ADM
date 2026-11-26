"""ADM PBR material <-> Blender Principled BSDF node tree (spec §8)."""

import hashlib
import json
import os
import re
import tempfile

import bpy
import numpy as np

from ..core import constants as K
from ..core import gputex
from ..core.png import encode_png
from ..core.validate import ANIMATION_ID_RE, param_value_error, shader_registry

UV_NAMES = ("UVMap", "UVMap_1")
OCCLUSION_NODE = "ADM Occlusion"
ALPHA_CLIP_NODE = "ADM Alpha Clip"
PREVIEW_PREFIX = "ADM Preview"


# ================================================================================================
# helpers
# ================================================================================================
def _from(socket):
    if socket is None or not socket.is_linked:
        return None
    for link in socket.links:
        if link.is_muted or not link.is_valid:
            continue
        s = link.from_socket
        while s.node.type == "REROUTE":
            nxt = s.node.inputs[0]
            if not nxt.is_linked:
                return None
            s = nxt.links[0].from_socket
        return s
    return None


def is_preview_node(node):
    return node.name.startswith(PREVIEW_PREFIX)


def material_output(mat):
    """The material's own output node; the shader preview output is never part of the exported data."""
    if not mat.node_tree:
        return None
    outs = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and not is_preview_node(n)]
    return next((n for n in outs if n.is_active_output), outs[0] if outs else None)


def output_surface_shader(mat):
    out = material_output(mat)
    if out is None:
        return None
    s = _from(out.inputs.get("Surface"))
    return s.node if s else None


def principled_of(mat):
    node = output_surface_shader(mat)
    if node is not None and node.type == "BSDF_PRINCIPLED":
        return node
    if mat.node_tree:
        return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED" and not is_preview_node(n)),
                    None)
    return None


def _color_inputs(node):
    return [s for s in node.inputs if s.name in ("A", "B", "Color1", "Color2") and s.type == "RGBA" and s.enabled]


def trace(socket, allow_invert=False):
    """Walk back from an input socket to an Image Texture node.

    Returns None (unlinked), or a dict with ``node`` (TEX_IMAGE or None if unsupported), ``channel``
    (None for RGB, 'R'/'G'/'B'/'A'), ``factor`` (float or rgb list) and ``clip`` (alpha cutoff or None).
    """
    s = _from(socket)
    if s is None:
        return None
    info = {"node": None, "channel": None, "factor": 1.0, "clip": None, "unsupported": None,
            "invert": False}
    guard = 0
    while s is not None and guard < 16:
        guard += 1
        n = s.node
        if n.type == "TEX_IMAGE":
            info["node"] = n
            if s.name == "Alpha" and info["channel"] is None:
                info["channel"] = "A"
            return info
        if n.type in ("SEPARATE_COLOR", "SEPRGB"):
            info["channel"] = {"Red": "R", "Green": "G", "Blue": "B", "R": "R", "G": "G", "B": "B"}.get(s.name)
            s = _from(n.inputs[0])
            continue
        if allow_invert and n.type == "MATH" and n.operation == "SUBTRACT":
            a, b = n.inputs[0], n.inputs[1]
            if not a.is_linked and abs(a.default_value - 1.0) < 1e-6 and b.is_linked:
                info["invert"] = not info["invert"]
                s = _from(b)
                continue
        if n.type == "MATH" and n.operation in ("MULTIPLY", "GREATER_THAN", "ROUND"):
            a, b = n.inputs[0], n.inputs[1]
            if n.operation == "GREATER_THAN":
                info["clip"] = float(b.default_value)
                s = _from(a)
                continue
            if n.operation == "ROUND":
                info["clip"] = 0.5
                s = _from(a)
                continue
            if info["invert"]:
                info["unsupported"] = n
                return info
            if a.is_linked and not b.is_linked:
                info["factor"] = info["factor"] * float(b.default_value)
                s = _from(a)
                continue
            if b.is_linked and not a.is_linked:
                info["factor"] = info["factor"] * float(a.default_value)
                s = _from(b)
                continue
        if (n.type == "MIX" and getattr(n, "data_type", "") == "RGBA" and n.blend_type == "MULTIPLY") or \
                (n.type == "MIX_RGB" and n.blend_type == "MULTIPLY"):
            cols = _color_inputs(n)
            fac = n.inputs[0]
            if len(cols) == 2 and not fac.is_linked and abs(fac.default_value - 1.0) < 1e-6:
                linked = [c for c in cols if c.is_linked]
                const = [c for c in cols if not c.is_linked]
                if len(linked) == 1 and len(const) == 1:
                    info["factor"] = list(const[0].default_value[:3])
                    s = _from(linked[0])
                    continue
        info["unsupported"] = n
        return info
    return info


def _uv_index(tex_node, uv_names):
    vec = tex_node.inputs.get("Vector")
    s = _from(vec)
    if s is not None and s.node.type == "UVMAP" and s.node.uv_map:
        name = s.node.uv_map
        if name in uv_names:
            return min(uv_names.index(name), 1)
    return 0


def _is_png(b):
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def _is_jpeg(b):
    return b[:3] == b"\xff\xd8\xff"


def _linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def image_pixels(image):
    """Float RGBA pixels, rows top-to-bottom, shape (h, w, 4)."""
    w, h = image.size
    if w == 0 or h == 0:
        raise ValueError(f"image '{image.name}' has no pixel data")
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1]


def _resize_nearest(a, h, w):
    sh, sw = a.shape[:2]
    if (sh, sw) == (h, w):
        return a
    ys = (np.arange(h) * sh // h).clip(0, sh - 1)
    xs = (np.arange(w) * sw // w).clip(0, sw - 1)
    return a[ys][:, xs]


class TextureExportError(Exception):
    pass


GPU_IMAGE_FORMATS = {"KTX2": gputex.MIME_KTX2, "DDS": gputex.MIME_DDS}
MAX_GPU_TEXTURE_BYTES = 512 * 1024 * 1024
MAX_GPU_TEXTURE_PIXELS = 64 * 1024 * 1024


def _read_gpu_texture(path):
    with open(path, "rb") as fh:
        data = fh.read(MAX_GPU_TEXTURE_BYTES + 1)
    if len(data) > MAX_GPU_TEXTURE_BYTES:
        raise ValueError(f"GPU texture exceeds the {MAX_GPU_TEXTURE_BYTES // (1024 * 1024)} MiB limit")
    return data


def source_bytes(image):
    """Original file bytes of an image (packed or on disk), or None."""
    if image.packed_file is not None:
        return bytes(image.packed_file.data)
    if image.source == "FILE" and image.filepath:
        path = bpy.path.abspath(image.filepath, library=image.library)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                return fh.read()
    return None


def _pixel_fingerprint(image):
    pixels = np.ascontiguousarray(image_pixels(image))
    digest = hashlib.sha256()
    digest.update(np.asarray(pixels.shape, dtype=np.int64).tobytes())
    digest.update(pixels)
    return digest.hexdigest()


def preserve_gpu_source(image, blob, fallback=None):
    """Keep a validated GPU primary alongside the editable preview image."""
    original = bpy.data.images.new(f"{image.name} ADM GPU source", 1, 1)
    original.pack(data=blob, data_len=len(blob))
    image["_adm_gpu_source"] = original
    image["_adm_gpu_pixels"] = _pixel_fingerprint(image)
    if fallback is not None and fallback != image:
        image["_adm_gpu_fallback"] = fallback


def mark_gpu_source_clean(image):
    if image.get("_adm_gpu_source") is not None:
        image["_adm_gpu_pixels"] = _pixel_fingerprint(image)


def _preserved_gpu_source(image, color_role, warn):
    original = image.get("_adm_gpu_source")
    if original is None:
        return None
    if not isinstance(original, bpy.types.Image) or original.packed_file is None:
        raise TextureExportError(f"image '{image.name}': preserved GPU source is missing")
    if _pixel_fingerprint(image) != image.get("_adm_gpu_pixels"):
        warn(f"image '{image.name}': edited pixels cannot use the preserved GPU source; exporting PNG")
        return None
    blob = bytes(original.packed_file.data)
    mime = gputex.mime_of(blob)
    try:
        info = gputex.parse(blob, mime, strict=True)
    except gputex.GpuTextureError as exc:
        raise TextureExportError(f"image '{image.name}': invalid preserved GPU source: {exc}") from exc
    if info["srgb"] != color_role:
        warn(f"image '{image.name}': preserved GPU source color space does not match the texture role; "
             "exporting PNG")
        return None
    return blob, mime


def _portable_mime(data):
    if not data:
        return None
    if _is_png(data):
        return "image/png"
    if _is_jpeg(data) and data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        return "image/jpeg"
    return None


def _has_16bit_source(image):
    if image.get("adm_source_precision_bits") == 16:
        return True
    data = source_bytes(image)
    return bool(data and len(data) >= 25 and _is_png(data)
                and data[12:16] == b"IHDR" and data[24] == 16)


def _decode_bc7_with_blender(data, mime):
    dds = gputex.repackage_bc7_as_dds(data, mime)
    with tempfile.TemporaryDirectory(prefix="adm_bc7_") as folder:
        path = os.path.join(folder, "texture.dds")
        with open(path, "wb") as handle:
            handle.write(dds)
        try:
            image = bpy.data.images.load(path, check_existing=False)
        except RuntimeError as exc:
            raise gputex.GpuTextureError(f"Blender could not decode BC7 DDS: {exc}") from exc
        try:
            image.colorspace_settings.name = "Non-Color"
            return image_pixels(image).copy()
        finally:
            bpy.data.images.remove(image)


def load_image_file(path, *, normal_map=False):
    """Load an image file; KTX2/DDS files Blender cannot read are decoded by the add-on and packed."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    mime = gputex.mime_of(head)
    data = None
    info = None
    if mime == gputex.MIME_DDS:
        data = _read_gpu_texture(path)
        try:
            info = gputex.parse(data, mime, strict=False)
        except gputex.GpuTextureError:
            # Blender may support DDS formats outside the ADM GPU subset.
            pass
    elif mime == gputex.MIME_KTX2:
        data = _read_gpu_texture(path)
        info = gputex.parse(data, mime, strict=False)
    if info is not None and info["width"] * info["height"] > MAX_GPU_TEXTURE_PIXELS:
        raise ValueError(f"GPU texture exceeds the {MAX_GPU_TEXTURE_PIXELS:,}-pixel limit")
    special = info is not None and info["kind"] in ("R8", "R16", "BC4", "BC5")
    if mime != gputex.MIME_KTX2 and not special:
        img = bpy.data.images.load(path, check_existing=mime is None)
        if mime is None or img.size[0] > 0:
            if info is not None:
                try:
                    gputex.parse(data, mime, strict=True)
                except gputex.GpuTextureError:
                    pass
                else:
                    preserve_gpu_source(img, data)
            return img
        bpy.data.images.remove(img)
    if data is None:
        data = _read_gpu_texture(path)
    if info is None:
        info = gputex.parse(data, mime, strict=False)
    if info["kind"] == "R16":
        scalar = gputex.decode_scalar_level(data, info).astype(np.float32) / 65535.0
        rgba = np.zeros((*scalar.shape, 4), dtype=np.float32)
        rgba[..., 0] = scalar
        rgba[..., 3] = 1.0
    elif info["kind"] == "BC7":
        rgba = _decode_bc7_with_blender(data, mime)
    else:
        rgba = gputex.decode(data, mime)[0].astype(np.float32) / 255.0
    if normal_map and info["kind"] == "BC5":
        rgba = gputex.reconstruct_bc5_normal(rgba)
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=True, float_buffer=info["kind"] == "R16")
    img.colorspace_settings.name = "sRGB" if info["srgb"] else "Non-Color"
    img.pixels.foreach_set(rgba[::-1].ravel())
    img.update()
    img.pack()
    if info["kind"] == "R16":
        img["adm_source_precision_bits"] = 16
    try:
        gputex.parse(data, mime, strict=True)
    except gputex.GpuTextureError:
        pass
    else:
        preserve_gpu_source(img, data)
    return img


# ================================================================================================
# export
# ================================================================================================
class MaterialExporter:
    """Export images as PNG, preserved compatible sources, or GPU images with PNG fallback."""

    def __init__(self, builder, warn, image_format="PRESERVE", jpeg_quality=90, gpu_compression="AUTO",
                 gpu_mipmaps=True, embed_images=True, vertex_controls=False):
        self.b = builder
        self.warn = warn
        self.image_format = image_format
        self.jpeg_quality = jpeg_quality
        self.gpu_compression = gpu_compression
        self.gpu_mipmaps = gpu_mipmaps
        self.embed_images = embed_images
        self.vertex_controls = vertex_controls
        self.materials = []
        self.images = []
        self.external_files = {}
        self._external_hash_cache = {}
        self.samplers = []
        self.textures = []
        self._mat_cache = {}
        self._mat_uv_names = {}
        self._img_cache = {}
        self._tex_cache = {}
        self._sampler_cache = {}
        self.normal_mapped = set()
        self.shader_defs = {}          # (id, version) -> ADMShaderDef (scene)
        self.used_definitions = {}     # (id, version) -> embedded definition dict
        self.extensions_used = set()
        self.extensions_required = set()
        self._animation_ids = set()

    # images ---------------------------------------------------------------------------------
    def _pixels(self, image, color_role, data=None):
        """Float RGBA (h, w, 4) top-to-bottom, colour textures sRGB-encoded.

        Falls back to the built-in KTX2/DDS decoder when Blender cannot read the source file.
        """
        if image.source not in ("FILE", "GENERATED"):
            self.warn(f"image '{image.name}': source {image.source} not supported, exporting first frame/tile")
        try:
            px = image_pixels(image)
        except ValueError:
            px = None
        if px is None:
            data = data if data is not None else source_bytes(image)
            mime = gputex.mime_of(data or b"")
            if mime is None:
                raise TextureExportError(f"image '{image.name}' has no readable pixel data")
            try:
                info = gputex.parse(data, mime, strict=False)
                if info["kind"] == "BC7":
                    return _decode_bc7_with_blender(data, mime)
                rgba, _ = gputex.decode(data, mime)
            except gputex.GpuTextureError as exc:
                raise TextureExportError(f"image '{image.name}': cannot convert {mime} source ({exc}); "
                                         f"convert it to PNG first") from exc
            return rgba.astype(np.float32) / 255.0
        if image.is_float and color_role and image.colorspace_settings.name not in ("sRGB",):
            px = px.copy()
            px[..., :3] = _linear_to_srgb(px[..., :3])
        return px

    def _encode_image_bytes(self, image, color_role):
        data = source_bytes(image) if image.source in ("FILE", "GENERATED") and not image.is_dirty else None
        keep = ("image/png", "image/jpeg") if self.image_format == "AUTO" else ("image/png",)
        mime = _portable_mime(data)
        if mime in keep:
            return data, mime
        if _has_16bit_source(image):
            px = self._pixels(image, color_role, data)
            rgba = (np.clip(px, 0.0, 1.0) * 65535.0 + 0.5).astype(">u2")
            return encode_png(rgba.shape[1], rgba.shape[0], rgba.tobytes(), 4, bit_depth=16), "image/png"
        return self._encode_pixels(self._pixels(image, color_role, data))

    @staticmethod
    def _to_u8(px):
        return (np.clip(px, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    def _encode_pixels(self, px):
        h, w = px.shape[:2]
        return encode_png(w, h, self._to_u8(px).tobytes(), 4), "image/png"

    def _add_blob(self, name, blob, mime, source_image=None):
        if not self.embed_images:
            from ..core.external_images import normalize_image_uri, sha256_hex
            digest = sha256_hex(blob)
            if digest in self._external_hash_cache:
                return self._external_hash_cache[digest]
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/ktx2": ".ktx2",
                   "image/vnd-ms.dds": ".dds"}.get(mime)
            if ext is None:
                raise TextureExportError(f"image '{name}' has unsupported external MIME type {mime!r}")
            uri = None
            if source_image is not None:
                old_uri = source_image.get("adm_external_uri")
                if old_uri:
                    try:
                        normalize_image_uri(old_uri)
                        source = source_bytes(source_image)
                        if source == blob and _portable_mime(source) == mime:
                            uri = old_uri
                    except (OSError, ValueError):
                        uri = None
            if uri is None:
                stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(os.path.basename(name))[0]).strip("._")
                stem = stem or "image"
                uri = f"textures/{stem}-{digest}{ext}"
            self.external_files[uri] = bytes(blob)
            self.images.append({"uri": uri, "sha256": digest, "mimeType": mime, "name": name})
            image_index = len(self.images) - 1
            self._external_hash_cache[digest] = image_index
            self.extensions_used.add(K.EXTERNAL_IMAGES_EXT)
            self.extensions_required.add(K.EXTERNAL_IMAGES_EXT)
            return image_index
        view = self.b.add_view(blob, align=4, chunk_type="IMAG")
        self.images.append({"bufferView": view, "mimeType": mime, "name": name})
        return len(self.images) - 1

    def _add_image(self, key, name, image=None, color_role=False, pixels=None):
        """Embed one image; returns ``(source, fallbackSource or None)`` image indices."""
        if key in self._img_cache:
            return self._img_cache[key]
        gpu_mime = GPU_IMAGE_FORMATS.get(self.image_format)
        preserved = (_preserved_gpu_source(image, color_role, self.warn)
                     if pixels is None and image is not None and self.image_format in ("PRESERVE", "AUTO")
                     else None)
        if preserved is not None:
            blob, mime = preserved
            primary = self._add_blob(name, blob, mime)
            fallback_image = image.get("_adm_gpu_fallback") or image
            if not isinstance(fallback_image, bpy.types.Image):
                raise TextureExportError(f"image '{image.name}': preserved fallback is invalid")
            fallback_blob, fallback_mime = self._encode_image_bytes(fallback_image, color_role)
            fallback = self._add_blob(name, fallback_blob, fallback_mime, fallback_image)
            entry = (primary, fallback)
        elif gpu_mime:
            px = pixels if pixels is not None else self._pixels(image, color_role)
            high_precision = image is not None and _has_16bit_source(image)
            scalar_r16 = (high_precision and pixels is None and not color_role
                          and self.gpu_compression == "AUTO"
                          and np.all(px[..., 1:3] == 0) and np.all(px[..., 3] == 1))
            if scalar_r16:
                scalar = (np.clip(px[..., 0], 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
                blob, _ = gputex.encode_scalar(scalar, gpu_mime, "R16", self.gpu_mipmaps)
            else:
                if high_precision:
                    self.warn(f"image '{name}': GPU export converts 16-bit samples to 8-bit; "
                              "the PNG fallback retains 16-bit precision")
                rgba = self._to_u8(px)
                blob, _ = gputex.encode(rgba, gpu_mime, self.gpu_compression, color_role, self.gpu_mipmaps)
            primary = self._add_blob(name, blob, gpu_mime)
            if high_precision:
                rgba16 = (np.clip(px, 0.0, 1.0) * 65535.0 + 0.5).astype(">u2")
                h, w = rgba16.shape[:2]
                fallback_blob = encode_png(w, h, rgba16.tobytes(), 4, bit_depth=16)
            else:
                rgba = self._to_u8(px)
                h, w = rgba.shape[:2]
                fallback_blob = encode_png(w, h, rgba.tobytes(), 4)
            fallback = self._add_blob(name, fallback_blob, "image/png")
            entry = (primary, fallback)
        else:
            blob, mime = self._encode_image_bytes(image, color_role) if pixels is None else self._encode_pixels(pixels)
            entry = (self._add_blob(name, blob, mime, image), None)
        self._img_cache[key] = entry
        return entry

    def _image_key(self, image, color_role):
        key = ("img", image.name, image.library.filepath if image.library else "")
        # GPU formats encode the sRGB/UNORM variant, so one image can need two encodings.
        return key + (color_role,) if self.image_format in (*GPU_IMAGE_FORMATS, "PRESERVE", "AUTO") else key

    def _sampler(self, tex_node):
        mag = "NEAREST" if tex_node.interpolation == "Closest" else "LINEAR"
        wrap = {"REPEAT": "REPEAT", "EXTEND": "CLAMP_TO_EDGE", "CLIP": "CLAMP_TO_EDGE",
                "MIRROR": "MIRRORED_REPEAT"}.get(tex_node.extension, "REPEAT")
        s = {}
        if mag != "LINEAR":
            s["magFilter"] = mag
            s["minFilter"] = mag
        if wrap != "REPEAT":
            s["wrapS"] = wrap
            s["wrapT"] = wrap
        if not s:
            return None
        key = tuple(sorted(s.items()))
        if key not in self._sampler_cache:
            self.samplers.append(s)
            self._sampler_cache[key] = len(self.samplers) - 1
        return self._sampler_cache[key]

    def _texture(self, entry, sampler):
        key = (entry, sampler)
        if key not in self._tex_cache:
            t = {"source": entry[0]}
            if entry[1] is not None:
                t["fallbackSource"] = entry[1]
            if sampler is not None:
                t["sampler"] = sampler
            self.textures.append(t)
            self._tex_cache[key] = len(self.textures) - 1
        return self._tex_cache[key]

    def texture_from_image(self, image, color_role):
        entry = self._add_image(self._image_key(image, color_role), image.name, image, color_role)
        return self._texture(entry, None)

    def texture_from_palette(self, image):
        pixels = self._pixels(image, True)
        if not 1 <= pixels.shape[0] <= K.TINT_PALETTE_MAX_HEIGHT or pixels.shape[1] < 1:
            raise TextureExportError(f"tint palette '{image.name}' must be an RGBA image "
                                     f"1-{K.TINT_PALETTE_MAX_HEIGHT} pixels high")
        entry = self._add_image(self._image_key(image, True), image.name, image, True, pixels=pixels)
        sampler = {"magFilter": "NEAREST", "minFilter": "NEAREST"}
        sampler_key = tuple(sorted(sampler.items()))
        if sampler_key not in self._sampler_cache:
            self.samplers.append(sampler)
            self._sampler_cache[sampler_key] = len(self.samplers) - 1
        return self._texture(entry, self._sampler_cache[sampler_key])

    def texture_from_node(self, tex_node, color_role):
        image = tex_node.image
        if image is None:
            return None
        entry = self._add_image(self._image_key(image, color_role), image.name, image, color_role)
        return self._texture(entry, self._sampler(tex_node))

    def texture_composite_mr(self, rough, metal, name):
        """Pack roughness->G and metallic->B into one generated image."""
        key = ("mr", id(rough["node"]) if rough else 0, rough["channel"] if rough else None,
               rough["invert"] if rough else False, id(metal["node"]) if metal else 0,
               metal["channel"] if metal else None, metal["invert"] if metal else False)
        entry = self._img_cache.get(key)
        if entry is None:
            srcs = [t for t in (rough, metal) if t]
            arrays = [self._pixels(t["node"].image, False) for t in srcs]
            h = max(a.shape[0] for a in arrays)
            w = max(a.shape[1] for a in arrays)
            out = np.ones((h, w, 4), dtype=np.float32)
            chan = {"R": 0, "G": 1, "B": 2, "A": 3, None: 0}
            if rough:
                values = _resize_nearest(arrays[0], h, w)[..., chan[rough["channel"]]]
                out[..., 1] = 1.0 - values if rough["invert"] else values
            if metal:
                values = _resize_nearest(arrays[-1], h, w)[..., chan[metal["channel"]]]
                out[..., 2] = 1.0 - values if metal["invert"] else values
            entry = self._add_image(key, name + "_metallicRoughness", pixels=out)
        node = (rough or metal)["node"]
        return self._texture(entry, self._sampler(node))

    # materials ------------------------------------------------------------------------------
    def index(self, mat, uv_names):
        if mat is None:
            return None
        if mat.name in self._mat_cache:
            index = self._mat_cache[mat.name]
            if mat.adm.shader_key() == K.SHADER_INTERACTIVE and tuple(uv_names) != self._mat_uv_names[mat.name]:
                current = self._export_pbr(mat, list(uv_names))
                for field in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture",
                              "occlusionTexture", "emissiveTexture"):
                    prior = self.materials[index].get(field)
                    now = current.get(field)
                    if prior is not None and now is not None and prior.get("texCoord", 0) != now.get("texCoord", 0):
                        raise ShaderExportError(f"interactive material '{mat.name}': {field} uses different UV "
                                                "set indices on shared meshes; make their UV order consistent")
            return index
        self.materials.append(self.export_material(mat, list(uv_names)))
        self._mat_cache[mat.name] = len(self.materials) - 1
        self._mat_uv_names[mat.name] = tuple(uv_names)
        return self._mat_cache[mat.name]

    def _ref(self, tex_index, tex_node, uv_names, extra=None, interactive_material=None):
        if interactive_material is not None:
            source = _from(tex_node.inputs.get("Vector"))
            if source is not None:
                if source.node.type == "UVMAP":
                    name = source.node.uv_map
                    if name and name not in uv_names:
                        raise ShaderExportError(f"interactive material '{interactive_material}': texture "
                                                f"'{tex_node.name}' requires UV map '{name}', which is not exported")
                elif source.node.type != "TEX_COORD" or source.name != "UV":
                    raise ShaderExportError(f"interactive material '{interactive_material}': texture "
                                            f"'{tex_node.name}' uses unsupported UV mapping")
        ref = {"index": tex_index}
        tc = _uv_index(tex_node, uv_names)
        if tc:
            ref["texCoord"] = tc
        if extra:
            ref.update(extra)
        return ref

    def export_material(self, mat, uv_names):
        out = self._export_pbr(mat, uv_names)
        self._export_shader(mat, out)
        if self.vertex_controls:
            p = mat.adm
            vc = {"parameters": {
                "tintOffset": float(p.tint_offset),
                "normalMultiplier": float(p.normal_multiplier),
                "reflectionMultiplier": float(p.reflection_multiplier),
                "wetnessOffset": float(p.wetness_offset),
            }}
            if p.vertex_tint_palette is not None:
                vc["tintPalette"] = {"index": self.texture_from_palette(p.vertex_tint_palette)}
            if p.vertex_tint_mode != "MULTIPLY":
                vc["tintMode"] = p.vertex_tint_mode
            out.setdefault("extensions", {})[K.VERTEX_CONTROL_EXT] = vc
            self.extensions_used.add(K.VERTEX_CONTROL_EXT)
            self.extensions_required.add(K.VERTEX_CONTROL_EXT)
        if mat.adm.shader != "CORE" or K.has_color1_profile(
                mat.adm.shader, mat.adm.shader_version):
            defaults = {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 1.0,
                        "roughnessFactor": 1.0, "emissiveFactor": [0.0, 0.0, 0.0], "alphaMode": "OPAQUE"}
            for key, value in defaults.items():
                out.setdefault(key, value)
        return out

    # shaders --------------------------------------------------------------------------------
    def _texref(self, image, tex_coord, color_role=False):
        if image is None:
            return None
        ref = {"index": self.texture_from_image(image, color_role)}
        if tex_coord:
            ref["texCoord"] = 1
        return ref

    def definition_dict(self, sdef):
        params = []
        for p in sdef.params:
            d = param_def_dict(p, lambda img, uv: self._texref(img, uv))
            params.append(d)
        out = {"id": sdef.shader_id.strip(), "version": sdef.version.strip(), "parameters": params}
        if sdef.description:
            out["description"] = sdef.description
        if sdef.author:
            out["author"] = sdef.author
        return out

    def _export_shader(self, mat, out):
        a = mat.adm
        if any(value.use for value in a.archived_params):
            self.warn(f"material '{mat.name}': inactive shader parameters are saved in the Blender project "
                      "but excluded from this ADM export")
        aid = a.animation_id.strip()
        if a.shader != "CORE" and not aid:
            aid = unique_animation_id(mat.name, self._animation_ids)
            self.warn(f"material '{mat.name}': shader materials need an animationId, using '{aid}'")
        if aid:
            if not ANIMATION_ID_RE.match(aid):
                raise ShaderExportError(f"material '{mat.name}': animationId '{aid}' must match [a-z][a-z0-9_]*")
            if aid in self._animation_ids:
                raise ShaderExportError(f"material '{mat.name}': animationId '{aid}' is used by another material")
            self._animation_ids.add(aid)
            out["animationId"] = aid
        key = a.shader_key()
        if a.shader == "CORE" and a.shader_version == "1.0.0":
            return
        if a.shader == "LAYERED" and a.shader_version == "1.0.0":
            out["shader"] = {"id": K.SHADER_LAYERED[0], "version": K.SHADER_LAYERED[1]}
            if a.layer_factor != 0.0:
                out["shaderParameters"] = {"layer_factor": _c01(a.layer_factor)}
            ext = {"base": layer_dict(a.layer_base), "overlay": layer_dict(a.layer_overlay)}
            if a.layer_mask is not None:
                ext["maskTexture"] = self._texref(a.layer_mask, a.layer_mask_uv)
            out.setdefault("extensions", {})[K.LAYERS_EXT] = ext
            self.extensions_used.add(K.LAYERS_EXT)
            if a.layers_required:
                self.extensions_required.add(K.LAYERS_EXT)
            return
        if a.shader == "CUTOUT" and a.shader_version == "1.0.0":
            if a.alpha_mode != "MASK":
                raise ShaderExportError(
                    f"material '{mat.name}': adm.surface.cutout@1.0.0 requires Alpha Mode MASK")
            out["shader"] = {"id": K.SHADER_CUTOUT[0], "version": K.SHADER_CUTOUT[1]}
            return
        if a.shader == "CUTOUT" and a.alpha_mode != "MASK":
            raise ShaderExportError(f"material '{mat.name}': {key[0]}@{key[1]} requires Alpha Mode MASK")
        if a.shader == "EMISSIVE" and a.shader_version == "1.0.0":
            emission = out.get("emissiveFactor", [0.0, 0.0, 0.0])
            if not any(float(x) > 0.0 for x in emission):
                raise ShaderExportError(
                    f"material '{mat.name}': adm.surface.emissive@1.0.0 requires nonzero emissive output")
            out["shader"] = {"id": K.SHADER_EMISSIVE[0], "version": K.SHADER_EMISSIVE[1]}
            return
        if a.shader == "EMISSIVE":
            emission = out.get("emissiveFactor", [0.0, 0.0, 0.0])
            if not any(float(x) > 0.0 for x in emission):
                raise ShaderExportError(
                    f"material '{mat.name}': {key[0]}@{key[1]} requires nonzero emissive output")
        if a.shader == "DECAL" and a.shader_version == "1.0.0":
            if a.alpha_mode != "BLEND":
                raise ShaderExportError(
                    f"material '{mat.name}': adm.surface.decal@1.0.0 requires Alpha Mode BLEND")
            out["shader"] = {"id": K.SHADER_DECAL[0], "version": K.SHADER_DECAL[1]}
            return
        if a.shader == "DECAL" and a.alpha_mode != "BLEND":
            raise ShaderExportError(f"material '{mat.name}': {key[0]}@{key[1]} requires Alpha Mode BLEND")
        if a.shader in ("GLASS", "WATER") and a.alpha_mode != "BLEND":
            raise ShaderExportError(f"material '{mat.name}': {key[0]}@{key[1]} requires Alpha Mode BLEND")
        if a.shader == "FOLIAGE" and (a.alpha_mode != "MASK" or mat.use_backface_culling):
            raise ShaderExportError(
                f"material '{mat.name}': {key[0]}@{key[1]} requires Mask alpha and double-sided rendering")
        if key in K.OFFICIAL_SHADERS:
            out["shader"] = {"id": key[0], "version": key[1]}
            defs = {p["name"]: p for p in K.OFFICIAL_SHADERS[key]}
            values = {}
            for v in a.params:
                if not v.use:
                    continue
                prm = defs.get(v.name)
                if prm is None:
                    self.warn(f"material '{mat.name}': parameter '{v.name}' is not part of {key[0]}@{key[1]}, skipped")
                    continue
                val = param_value_from_prop(prm["type"], v, lambda img, uv, n=v.name: self._texref(
                    img, uv, n in K.SHADER_COLOR_TEXTURES))
                err = param_value_error(prm, val, None)
                if err:
                    raise ShaderExportError(f"material '{mat.name}': parameter '{v.name}': {err}")
                values[v.name] = val
            if values:
                out["shaderParameters"] = values
            if not has_profile_preview(a.shader):
                self.warn(f"material '{mat.name}': {key[0]}@{key[1]} is preserved with portable PBR fallback; "
                          "this profile has no Blender node preview yet")
            return
        sdef = self.shader_defs.get(key)
        if sdef is None:
            raise ShaderExportError(f"material '{mat.name}': custom shader '{a.custom_shader}' has no definition "
                                    f"in the scene's ADM shader list")
        if key[0].startswith("adm."):
            raise ShaderExportError(f"material '{mat.name}': adm.* shader ids are reserved for the official registry")
        if key not in self.used_definitions:
            self.used_definitions[key] = self.definition_dict(sdef)
        out["shader"] = {"id": key[0], "version": key[1]}
        defs = {p["name"]: p for p in self.used_definitions[key]["parameters"]}
        values = {}
        for v in a.params:
            if not v.use:
                continue
            prm = defs.get(v.name)
            if prm is None:
                self.warn(f"material '{mat.name}': parameter '{v.name}' is not part of {key[0]}@{key[1]}, skipped")
                continue
            val = param_value_from_prop(prm["type"], v, lambda img, uv: self._texref(img, uv))
            err = param_value_error(prm, val, None)
            if err:
                raise ShaderExportError(f"material '{mat.name}': parameter '{v.name}': {err}")
            values[v.name] = val
        if values:
            out["shaderParameters"] = values

    def _export_pbr(self, mat, uv_names):
        out = {"name": mat.name}
        interactive = mat.name if mat.adm.shader_key() == K.SHADER_INTERACTIVE else None
        bsdf = principled_of(mat)
        double_sided = not mat.use_backface_culling
        if bsdf is None:
            self.warn(f"material '{mat.name}': no Principled BSDF, exporting viewport color only")
            out["baseColorFactor"] = [_c01(x) for x in mat.diffuse_color]
            out["metallicFactor"] = _c01(mat.metallic)
            out["roughnessFactor"] = _c01(mat.roughness)
            if double_sided:
                out["doubleSided"] = True
            return out

        # base color + alpha
        base = trace(bsdf.inputs["Base Color"])
        factor = list(bsdf.inputs["Base Color"].default_value[:3])
        if base is not None:
            if base["node"] is not None and base["node"].image is not None:
                ti = self.texture_from_node(base["node"], True)
                out["baseColorTexture"] = self._ref(ti, base["node"], uv_names, interactive_material=interactive)
                factor = base["factor"] if isinstance(base["factor"], list) else [base["factor"]] * 3
            elif base["node"] is not None:
                self.warn(f"material '{mat.name}': Base Color texture node has no image, skipped")
            else:
                self.warn(f"material '{mat.name}': Base Color node setup not representable, using default value")
        alpha_in = bsdf.inputs["Alpha"]
        alpha = float(alpha_in.default_value)
        alpha_tr = trace(alpha_in)
        clip = None
        if alpha_tr is not None:
            alpha = float(alpha_tr["factor"]) if not isinstance(alpha_tr["factor"], list) else 1.0
            clip = alpha_tr["clip"]
            if alpha_tr["node"] is None:
                if interactive is not None:
                    raise ShaderExportError(f"interactive material '{interactive}': alpha node setup is not "
                                            "representable in the PBR fallback")
                self.warn(f"material '{mat.name}': Alpha node setup not representable")
            elif (base is None or base["node"] is None or base["node"].image is None
                  or alpha_tr["node"].image != base["node"].image):
                if interactive is not None:
                    raise ShaderExportError(f"interactive material '{interactive}': alpha must come from the "
                                            "base color texture")
                self.warn(f"material '{mat.name}': alpha must come from the base color texture alpha channel")
            elif interactive is not None:
                alpha_ref = self._ref(0, alpha_tr["node"], uv_names, interactive_material=interactive)
                if alpha_ref.get("texCoord", 0) != out["baseColorTexture"].get("texCoord", 0):
                    raise ShaderExportError(f"interactive material '{interactive}': base color and alpha "
                                            "use different UV sets")
        bcf = [_c01(x) for x in factor] + [_c01(alpha)]
        if bcf != [1.0, 1.0, 1.0, 1.0]:
            out["baseColorFactor"] = bcf

        # metallic / roughness
        mt = trace(bsdf.inputs["Metallic"], allow_invert=True)
        rt = trace(bsdf.inputs["Roughness"], allow_invert=True)
        metallic = float(bsdf.inputs["Metallic"].default_value) if mt is None else float(_scalar(mt["factor"]))
        rough = float(bsdf.inputs["Roughness"].default_value) if rt is None else float(_scalar(rt["factor"]))
        mt = mt if mt and mt["node"] is not None and mt["node"].image else None
        rt = rt if rt and rt["node"] is not None and rt["node"].image else None
        if mt or rt:
            if interactive is not None and mt and rt:
                metal_ref = self._ref(0, mt["node"], uv_names, interactive_material=interactive)
                rough_ref = self._ref(0, rt["node"], uv_names, interactive_material=interactive)
                if metal_ref.get("texCoord", 0) != rough_ref.get("texCoord", 0):
                    raise ShaderExportError(f"interactive material '{interactive}': metallic and roughness "
                                            "textures use different UV sets")
            same = (mt and rt and mt["node"].image == rt["node"].image and mt["channel"] == "B"
                    and rt["channel"] == "G" and not mt["invert"] and not rt["invert"])
            only_ok = ((not mt and rt["channel"] == "G" and not rt["invert"])
                       or (not rt and mt["channel"] == "B" and not mt["invert"]))
            if same or only_ok:
                node = (rt or mt)["node"]
                ti = self.texture_from_node(node, False)
            else:
                ti = self.texture_composite_mr(rt, mt, mat.name)
                node = (rt or mt)["node"]
            out["metallicRoughnessTexture"] = self._ref(ti, node, uv_names, interactive_material=interactive)
        if metallic != 1.0:
            out["metallicFactor"] = _c01(metallic)
        if rough != 1.0:
            out["roughnessFactor"] = _c01(rough)

        # normal map
        ns = _from(bsdf.inputs["Normal"])
        if ns is not None:
            nm = ns.node
            if nm.type == "NORMAL_MAP" and nm.space == "TANGENT":
                ct = trace(nm.inputs["Color"])
                if ct and ct["node"] is not None and ct["node"].image:
                    ti = self.texture_from_node(ct["node"], False)
                    strength = float(nm.inputs["Strength"].default_value)
                    extra = {"scale": max(0.0, strength)} if abs(strength - 1.0) > 1e-6 else None
                    ref = self._ref(ti, ct["node"], uv_names, extra, interactive)
                    if interactive is not None:
                        if nm.uv_map and nm.uv_map not in uv_names:
                            raise ShaderExportError(f"interactive material '{interactive}': normal map requires "
                                                    f"UV map '{nm.uv_map}', which is not exported")
                        normal_uv = uv_names.index(nm.uv_map) if nm.uv_map else 0
                        if normal_uv != ref.get("texCoord", 0):
                            raise ShaderExportError(f"interactive material '{interactive}': normal-map tangent "
                                                    "and image UV sets differ")
                    if nm.uv_map and nm.uv_map in uv_names and uv_names.index(nm.uv_map) == 1:
                        ref["texCoord"] = 1
                    out["normalTexture"] = ref
                    self.normal_mapped.add(mat.name)
            else:
                self.warn(f"material '{mat.name}': Normal input must come from a tangent-space Normal Map node")

        # occlusion
        occ_node = mat.node_tree.nodes.get(OCCLUSION_NODE)
        occ = None
        if occ_node is not None and occ_node.type == "TEX_IMAGE" and occ_node.image:
            occ = occ_node
        else:
            for n in mat.node_tree.nodes:
                if n.type == "GROUP" and n.node_tree and n.node_tree.name in ("glTF Material Output", "glTF Settings"):
                    o = trace(n.inputs.get("Occlusion"))
                    if o and o["node"] is not None and o["node"].image:
                        occ = o["node"]
        if occ is not None:
            ti = self.texture_from_node(occ, False)
            st = mat.adm.occlusion_strength
            out["occlusionTexture"] = self._ref(ti, occ, uv_names, {"strength": st} if st != 1.0 else None,
                                                interactive)

        # emission
        strength = float(bsdf.inputs["Emission Strength"].default_value)
        et = trace(bsdf.inputs["Emission Color"])
        ecol = list(bsdf.inputs["Emission Color"].default_value[:3])
        if et is not None and et["node"] is not None and et["node"].image and strength > 0:
            ti = self.texture_from_node(et["node"], True)
            out["emissiveTexture"] = self._ref(ti, et["node"], uv_names, interactive_material=interactive)
            ecol = et["factor"] if isinstance(et["factor"], list) else [et["factor"]] * 3
        ef = [max(0.0, float(c) * strength) for c in ecol]
        if any(v > 0 for v in ef):
            out["emissiveFactor"] = ef

        # alpha mode
        mode = mat.adm.alpha_mode
        if mode == "AUTO":
            if clip is not None:
                mode = "MASK"
            elif alpha_tr is not None or alpha < 1.0:
                mode = "BLEND"
            else:
                mode = "OPAQUE"
        if mode != "OPAQUE":
            out["alphaMode"] = mode
        if mode == "MASK":
            cutoff = clip if (clip is not None and mat.adm.alpha_mode == "AUTO") else mat.adm.alpha_cutoff
            if abs(cutoff - 0.5) > 1e-6:
                out["alphaCutoff"] = _c01(cutoff)
        if double_sided:
            out["doubleSided"] = True
        return out


def _scalar(f):
    return f[0] if isinstance(f, list) else f


def _c01(x):
    return min(1.0, max(0.0, float(x)))


# ================================================================================================
# shaders (§8.1-8.4)
# ================================================================================================
class ShaderExportError(Exception):
    pass


def unique_animation_id(name, taken):
    base = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "material"
    if not base[0].isalpha():
        base = "m_" + base
    aid, i = base, 1
    while aid in taken:
        i += 1
        aid = f"{base}_{i}"
    return aid


def layer_dict(rec):
    d = {"baseColorFactor": [_c01(x) for x in rec.base_color],
         "metallicFactor": _c01(rec.metallic), "roughnessFactor": _c01(rec.roughness),
         "emissiveFactor": [max(0.0, float(x)) for x in rec.emissive]}
    if rec.use_normal_factor:
        d["normalFactor"] = [float(x) for x in rec.normal_factor]
    return d


def layer_from_dict(rec, d):
    rec.base_color = d.get("baseColorFactor", [1, 1, 1, 1])
    rec.metallic = d.get("metallicFactor", 1.0)
    rec.roughness = d.get("roughnessFactor", 1.0)
    rec.emissive = d.get("emissiveFactor", [0, 0, 0])
    rec.use_normal_factor = "normalFactor" in d
    if "normalFactor" in d:
        rec.normal_factor = d["normalFactor"]


def _num_value(typ, vec):
    n = K.SHADER_NUMERIC_DIMS[typ]
    return float(vec[0]) if n == 1 else [float(x) for x in vec[:n]]


def param_def_dict(p, texref):
    """ADMShaderParamDef -> JSON parameter definition."""
    d = {"name": p.name, "type": p.type}
    if p.type in K.SHADER_NUMERIC_DIMS:
        d["default"] = _num_value(p.type, p.default_vec)
        if p.use_minimum:
            d["minimum"] = _num_value(p.type, p.minimum)
        if p.use_maximum:
            d["maximum"] = _num_value(p.type, p.maximum)
        if p.animatable:
            d["animatable"] = True
    elif p.type == "BOOL":
        d["default"] = bool(p.default_bool)
    elif p.type == "ENUM":
        try:
            values = json.loads(p.enum_values)
        except (ValueError, TypeError):
            values = []
        d["values"] = values if isinstance(values, list) else []
        d["default"] = p.default_enum
    else:
        d["default"] = texref(p.default_image, p.default_tex_coord)
    d["description"] = p.description
    return d


def scene_shader_registry(scene):
    """(id, version) -> {name: param dict} for official shaders plus the scene's shader definitions."""
    defs = []
    for sdef in scene.adm_anim.shaders:
        defs.append({"id": sdef.shader_id.strip(), "version": sdef.version.strip(),
                     "parameters": [param_def_dict(p, lambda img, uv: None) for p in sdef.params]})
    return shader_registry({"shaderDefinitions": defs})


def param_value_from_prop(typ, v, texref):
    if typ in K.SHADER_NUMERIC_DIMS:
        return float(v.value_f) if typ == "F32" else _num_value(typ, v.value_vec)
    if typ == "BOOL":
        return bool(v.value_bool)
    if typ == "ENUM":
        return str(v.value_enum_custom if v.id_data.adm.shader == "CUSTOM" else v.value_enum)
    return texref(v.image, v.tex_coord)


def _set_vec(prop_owner, attr, value, n):
    vals = [value] if n == 1 else list(value)
    cur = list(getattr(prop_owner, attr))
    cur[:len(vals)] = vals
    setattr(prop_owner, attr, cur)


_param_update_lock = [0]


class quiet_param_updates:
    """Suppress the auto-override/preview-rebuild callbacks of ADMShaderParamValue while code writes them."""

    def __enter__(self):
        _param_update_lock[0] += 1

    def __exit__(self, *exc):
        _param_update_lock[0] -= 1
        return False


def param_updates_quiet():
    return _param_update_lock[0] > 0


def _quietly(fn):
    def wrapper(*args, **kwargs):
        with quiet_param_updates():
            return fn(*args, **kwargs)
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


def import_shader_definitions(scene, doc, resolve_image):
    """Add embedded definitions, rejecting incompatible existing parameter schemas."""
    shaders = scene.adm_anim.shaders
    for d in doc.get("shaderDefinitions", []) or []:
        name = f"{d['id']}@{d['version']}"
        existing = shaders.get(name)
        if existing is not None:
            if (existing.description != d.get("description", "")
                    or existing.author != d.get("author", "")):
                raise ValueError(f"custom shader '{name}' has conflicting metadata")
            existing_types = {p.name: p.type for p in existing.params}
            incoming_types = {p["name"]: p["type"] for p in d.get("parameters", [])}
            if existing_types != incoming_types:
                raise ValueError(f"custom shader '{name}' has conflicting parameter names or types")
            existing_enums = {p.name: param_def_dict(p, lambda _img, _uv: None)
                              for p in existing.params if p.type == "ENUM"}
            incoming_enums = {p["name"]: p for p in d.get("parameters", []) if p["type"] == "ENUM"}
            for param_name in existing_enums.keys() | incoming_enums.keys():
                old = existing_enums.get(param_name)
                new = incoming_enums.get(param_name)
                if (old is None or new is None or old["values"] != new["values"]
                        or old["default"] != new["default"]):
                    raise ValueError(f"custom shader '{name}' has a conflicting ENUM definition '{param_name}'")
            for incoming in d.get("parameters", []):
                old_param = existing.params[incoming["name"]]
                if old_param.description != incoming.get("description", ""):
                    raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                if incoming["type"] in K.SHADER_NUMERIC_DIMS:
                    old = param_def_dict(old_param, lambda _img, _uv: None)
                    for field in ("default", "minimum", "maximum"):
                        if (field in old) != (field in incoming):
                            raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                        if field in old and not np.array_equal(
                                np.asarray(old[field], dtype=np.float32),
                                np.asarray(incoming[field], dtype=np.float32)):
                            raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                    if old.get("animatable", False) != incoming.get("animatable", False):
                        raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                elif incoming["type"] == "BOOL" and old_param.default_bool != incoming["default"]:
                    raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                elif incoming["type"] == "TEXTURE":
                    ref, image = incoming["default"], old_param.default_image
                    if (ref is None) != (image is None):
                        raise ValueError(f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
                    if ref is not None:
                        candidate = resolve_image(ref)
                        old_source = image.get("_adm_gpu_source")
                        new_source = candidate.get("_adm_gpu_source") if candidate is not None else None
                        same_source = (old_source is None and new_source is None) or (
                            old_source is not None and new_source is not None
                            and old_source.packed_file is not None and new_source.packed_file is not None
                            and bytes(old_source.packed_file.data) == bytes(new_source.packed_file.data))
                        if (candidate is None or old_param.default_tex_coord != ref.get("texCoord", 0)
                                or image.colorspace_settings.name != candidate.colorspace_settings.name
                                or not same_source or _pixel_fingerprint(image) != _pixel_fingerprint(candidate)):
                            raise ValueError(
                                f"custom shader '{name}' has a conflicting parameter '{incoming['name']}'")
            continue
        sd = shaders.add()
        sd.shader_id = d["id"]
        sd.version = d["version"]
        sd.name = name
        sd.description = d.get("description", "")
        sd.author = d.get("author", "")
        for p in d.get("parameters", []):
            pd = sd.params.add()
            pd.name = p["name"]
            pd.type = p["type"]
            pd.description = p.get("description", "")
            pd.animatable = bool(p.get("animatable", False))
            n = K.SHADER_NUMERIC_DIMS.get(p["type"])
            if n:
                _set_vec(pd, "default_vec", p["default"], n)
                if "minimum" in p:
                    pd.use_minimum = True
                    _set_vec(pd, "minimum", p["minimum"], n)
                if "maximum" in p:
                    pd.use_maximum = True
                    _set_vec(pd, "maximum", p["maximum"], n)
            elif p["type"] == "BOOL":
                pd.default_bool = bool(p["default"])
            elif p["type"] == "ENUM":
                pd.enum_values = json.dumps(p["values"], ensure_ascii=False)
                pd.default_enum = p["default"]
            elif isinstance(p.get("default"), dict):
                pd.default_image = resolve_image(p["default"])
                pd.default_tex_coord = p["default"].get("texCoord", 0)


def _copy_shader_param(source, target):
    target.name = source.name
    if "_schema_type" in source:
        target["_schema_type"] = source["_schema_type"]
    elif "_schema_type" in target:
        del target["_schema_type"]
    target.value_f = source.value_f
    target.value_vec = source.value_vec
    target.value_bool = source.value_bool
    target.value_enum_custom = source.value_enum_custom
    if "value_enum" in source:
        target["value_enum"] = source["value_enum"]
    elif "value_enum" in target:
        del target["value_enum"]
    target.image = source.image
    target.tex_coord = source.tex_coord
    target.use = source.use


def initialize_shader_param_owners():
    """Identify active parameters in projects saved before profile caching existed."""
    for mat in bpy.data.materials:
        a = mat.adm
        if a.params_shader_id or not a.params:
            continue
        key = a.shader_key()
        if not key[0]:
            continue
        a.params_shader_id = key[0]
        schema = K.OFFICIAL_SHADERS.get(key)
        if schema is not None:
            types = {p["name"]: p["type"] for p in schema}
        else:
            definitions = [s for scene in bpy.data.scenes for s in scene.adm_anim.shaders
                           if (s.shader_id, s.version) == key]
            candidates = {}
            for definition in definitions:
                for param in definition.params:
                    candidates.setdefault(param.name, set()).add(param.type)
            types = {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}
        for value in a.params:
            if value.name in types and "_schema_type" not in value:
                value["_schema_type"] = types[value.name]


def _sync_shader_param_membership(a, shader_id, types):
    previous_id = a.params_shader_id or shader_id
    for i in range(len(a.params) - 1, -1, -1):
        value = a.params[i]
        old_type = value.get("_schema_type")
        if old_type is None:
            known = {p["type"] for key, schema in K.OFFICIAL_SHADERS.items() if key[0] == previous_id
                     for p in schema if p["name"] == value.name}
            old_type = next(iter(known)) if len(known) == 1 else None
        if value.name not in types or (old_type is not None and old_type != types[value.name]):
            old = next((p for p in a.archived_params
                        if p.name == value.name and p.get("_shader_id") == previous_id
                        and p.get("_schema_type") == old_type), None)
            if old is None:
                old = a.archived_params.add()
            _copy_shader_param(value, old)
            if old_type is not None:
                old["_schema_type"] = old_type
            old["_shader_id"] = previous_id
            a.params.remove(i)
        else:
            value["_schema_type"] = types[value.name]
    a.params_shader_id = shader_id


def _restore_shader_param(a, shader_id, name, param_type):
    for i, value in enumerate(a.archived_params):
        if (value.name == name and value.get("_shader_id") == shader_id
                and value.get("_schema_type") == param_type):
            restored = a.params.add()
            _copy_shader_param(value, restored)
            a.archived_params.remove(i)
            return True
    return False


@_quietly
def sync_material_params(mat, sdef):
    """Make active parameters match the definition, preserving inactive values."""
    a = mat.adm
    types = {p.name: p.type for p in sdef.params}
    _sync_shader_param_membership(a, sdef.shader_id, types)
    for p in sdef.params:
        if a.params.get(p.name) is not None:
            continue
        if _restore_shader_param(a, sdef.shader_id, p.name, p.type):
            continue
        v = a.params.add()
        v.name = p.name
        v["_schema_type"] = p.type
        v.use = False
        v.value_f = p.default_vec[0]
        v.value_vec = p.default_vec
        v.value_bool = p.default_bool
        if p.type == "ENUM":
            v.value_enum_custom = p.default_enum
        v.image = p.default_image
        v.tex_coord = p.default_tex_coord


@_quietly
def sync_official_shader_params(mat, key=None):
    """Make material parameter values match a registered profile's typed schema."""
    key = key or mat.adm.shader_key()
    schema = K.OFFICIAL_SHADERS.get(key)
    if schema is None:
        return
    a = mat.adm
    types = {p["name"]: p["type"] for p in schema}
    _sync_shader_param_membership(a, key[0], types)
    for prm in schema:
        if a.params.get(prm["name"]) is not None:
            continue
        if _restore_shader_param(a, key[0], prm["name"], prm["type"]):
            continue
        v = a.params.add()
        v.name = prm["name"]
        v["_schema_type"] = prm["type"]
        v.use = False
        typ = prm["type"]
        if typ in K.SHADER_NUMERIC_DIMS:
            _set_vec(v, "value_vec", prm["default"], K.SHADER_NUMERIC_DIMS[typ])
            if typ == "F32":
                v.value_f = float(prm["default"])
        elif typ == "BOOL":
            v.value_bool = bool(prm["default"])
        elif typ == "ENUM":
            v.value_enum = prm["default"]


def _apply_shader_value(v, typ, val, resolve_image):
    if typ == "F32":
        v.value_f = val
    elif typ in K.SHADER_NUMERIC_DIMS:
        _set_vec(v, "value_vec", val, K.SHADER_NUMERIC_DIMS[typ])
    elif typ == "BOOL":
        v.value_bool = bool(val)
    elif typ == "ENUM":
        if v.id_data.adm.shader == "CUSTOM":
            v.value_enum_custom = val
        else:
            v.value_enum = val
    elif isinstance(val, dict):
        v.image = resolve_image(val)
        v.tex_coord = val.get("texCoord", 0)
    else:
        v.image = None


def apply_shader(mat, m, scene, resolve_image, resolve_normal_image):
    """Read ADM shader fields of material dict ``m`` into ``mat.adm`` and rebuild the viewport preview."""
    with quiet_param_updates():
        _apply_shader(mat, m, scene, resolve_image, resolve_normal_image)
    if mat.adm.shader != "CORE" or mat.adm.vertex_controls_enabled \
            or K.has_color1_profile(mat.adm.shader, mat.adm.shader_version):
        refresh_shader_preview(mat)


def _apply_shader(mat, m, scene, resolve_image, resolve_normal_image):
    a = mat.adm
    a.animation_id = m.get("animationId", "")
    sh = m.get("shader")
    key = (sh["id"], sh["version"]) if isinstance(sh, dict) else K.SHADER_CORE
    sp = m.get("shaderParameters", {}) or {}
    if key == K.SHADER_CORE:
        a.shader = "CORE"
        a.shader_version = key[1]
    elif key == K.SHADER_LAYERED:
        a.shader = "LAYERED"
        a.shader_version = key[1]
        a.layer_factor = sp.get("layer_factor", 0.0)
        ext = (m.get("extensions") or {}).get(K.LAYERS_EXT)
        if ext:
            layer_from_dict(a.layer_base, ext.get("base", {}))
            layer_from_dict(a.layer_overlay, ext.get("overlay", {}))
            if "maskTexture" in ext:
                a.layer_mask = resolve_image(ext["maskTexture"])
                a.layer_mask_uv = ext["maskTexture"].get("texCoord", 0)
    elif key == K.SHADER_CUTOUT:
        a.shader = "CUTOUT"
        a.shader_version = key[1]
    elif key == K.SHADER_EMISSIVE:
        a.shader = "EMISSIVE"
        a.shader_version = key[1]
    elif key == K.SHADER_DECAL:
        a.shader = "DECAL"
        a.shader_version = key[1]
    elif key in K.OFFICIAL_SHADER_KINDS:
        a.shader = K.OFFICIAL_SHADER_KINDS[key]
        a.shader_version = key[1]
        sync_official_shader_params(mat, key)
        defs = {p["name"]: p for p in K.OFFICIAL_SHADERS[key]}
        for name, val in sp.items():
            v = a.params.get(name)
            prm = defs.get(name)
            if v is not None and prm is not None:
                v.use = True
                resolver = resolve_normal_image if prm["type"] == "TEXTURE" and name.endswith("_normal") else resolve_image
                _apply_shader_value(v, prm["type"], val, resolver)
                if v.image is not None and prm["type"] == "TEXTURE" and name not in K.SHADER_COLOR_TEXTURES:
                    v.image.colorspace_settings.name = "Non-Color"
                    if K.OFFICIAL_SHADER_KINDS.get(key) == "TERRAIN_4" and name == "blend_mask":
                        v.image.alpha_mode = "CHANNEL_PACKED"
    else:
        a.shader = "CUSTOM"
        a.shader_version = key[1]
        a.custom_shader = f"{key[0]}@{key[1]}"
        sdef = scene.adm_anim.shaders.get(a.custom_shader)
        if sdef is not None:
            sync_material_params(mat, sdef)
            types = {p.name: p.type for p in sdef.params}
            for name, val in sp.items():
                v = a.params.get(name)
                typ = types.get(name)
                if v is None or typ is None:
                    continue
                v.use = True
                _apply_shader_value(v, typ, val, resolve_image)


def layers_from_pbr(mat):
    """Copy the material's current PBR factors into the base layer record (overlay keeps its values)."""
    from .material_anim import pbr_values
    vals = pbr_values(mat)
    rec = mat.adm.layer_base
    rec.base_color = [_c01(x) for x in vals["baseColorFactor"]]
    rec.metallic = _c01(vals["metallicFactor"])
    rec.roughness = _c01(vals["roughnessFactor"])
    rec.emissive = vals["emissiveFactor"]


# ================================================================================================
# import
# ================================================================================================
def _uv_node(nt, tex_node, tex_coord, x, y):
    if tex_coord:
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = UV_NAMES[1]
        uv.location = (x - 220, y)
        nt.links.new(uv.outputs["UV"], tex_node.inputs["Vector"])


def _tex_node(nt, image, sampler, non_color, x, y, label):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = image
    n.label = label
    n.location = (x, y)
    if image is not None and non_color:
        try:
            image.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    sampler = sampler or {}
    if sampler.get("magFilter") == "NEAREST":
        n.interpolation = "Closest"
    n.extension = {"CLAMP_TO_EDGE": "EXTEND", "MIRRORED_REPEAT": "MIRROR"}.get(sampler.get("wrapS", "REPEAT"), "REPEAT")
    return n


def build_material(m, resolve_texture, resolve_normal_texture):
    """Create a Blender material from an ADM material dict.

    ``resolve_texture(textureRef) -> (bpy.types.Image, sampler_dict)``.
    """
    mat = bpy.data.materials.new(m.get("name", "ADM Material"))
    missing_textures = []

    def _resolve_texture(ref):
        image, sampler = resolve_texture(ref)
        if image is None:
            missing_textures.append(ref)
        return image, sampler

    def _resolve_normal_texture(ref):
        image, sampler = resolve_normal_texture(ref)
        if image is None:
            missing_textures.append(ref)
        return image, sampler

    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bcf = m.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
    bsdf.inputs["Base Color"].default_value = (bcf[0], bcf[1], bcf[2], 1.0)
    bsdf.inputs["Alpha"].default_value = bcf[3]
    bsdf.inputs["Metallic"].default_value = m.get("metallicFactor", 1.0)
    bsdf.inputs["Roughness"].default_value = m.get("roughnessFactor", 1.0)
    mat.diffuse_color = (bcf[0], bcf[1], bcf[2], bcf[3])
    alpha_mode = m.get("alphaMode", "OPAQUE")
    mat.adm.alpha_mode = alpha_mode
    mat.adm.alpha_cutoff = m.get("alphaCutoff", 0.5)
    mat.use_backface_culling = not m.get("doubleSided", False)

    y = 300
    if "baseColorTexture" in m:
        img, smp = _resolve_texture(m["baseColorTexture"])
        tn = _tex_node(nt, img, smp, False, -900, y, "Base Color")
        _uv_node(nt, tn, m["baseColorTexture"].get("texCoord", 0), -900, y)
        col = tn.outputs["Color"]
        if bcf[:3] != [1.0, 1.0, 1.0]:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-450, y)
            mix.inputs[0].default_value = 1.0
            ca, cb = _color_inputs(mix)[:2]
            nt.links.new(col, ca)
            cb.default_value = (bcf[0], bcf[1], bcf[2], 1.0)
            col = mix.outputs[2] if mix.outputs[2].type == "RGBA" else next(o for o in mix.outputs if o.type == "RGBA")
        nt.links.new(col, bsdf.inputs["Base Color"])
        if alpha_mode != "OPAQUE":
            a = tn.outputs["Alpha"]
            if bcf[3] != 1.0:
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.location = (-450, y - 200)
                nt.links.new(a, mul.inputs[0])
                mul.inputs[1].default_value = bcf[3]
                a = mul.outputs[0]
            if alpha_mode == "MASK":
                clip = nt.nodes.new("ShaderNodeMath")
                clip.name = clip.label = ALPHA_CLIP_NODE
                clip.operation = "GREATER_THAN"
                clip.location = (-250, y - 200)
                nt.links.new(a, clip.inputs[0])
                clip.inputs[1].default_value = m.get("alphaCutoff", 0.5) - 1e-6
                a = clip.outputs[0]
            nt.links.new(a, bsdf.inputs["Alpha"])
        y -= 300
    if "metallicRoughnessTexture" in m:
        img, smp = _resolve_texture(m["metallicRoughnessTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Metallic Roughness")
        _uv_node(nt, tn, m["metallicRoughnessTexture"].get("texCoord", 0), -900, y)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (-600, y)
        nt.links.new(tn.outputs["Color"], sep.inputs[0])
        for out_name, target, fac in (("Green", "Roughness", m.get("roughnessFactor", 1.0)),
                                      ("Blue", "Metallic", m.get("metallicFactor", 1.0))):
            s = sep.outputs[out_name]
            if fac != 1.0:
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.location = (-350, y - (0 if target == "Roughness" else 150))
                nt.links.new(s, mul.inputs[0])
                mul.inputs[1].default_value = fac
                s = mul.outputs[0]
            nt.links.new(s, bsdf.inputs[target])
        y -= 300
    if "normalTexture" in m:
        img, smp = _resolve_normal_texture(m["normalTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Normal")
        tc = m["normalTexture"].get("texCoord", 0)
        _uv_node(nt, tn, tc, -900, y)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-450, y)
        nm.inputs["Strength"].default_value = m["normalTexture"].get("scale", 1.0)
        if tc:
            nm.uv_map = UV_NAMES[1]
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        y -= 300
    if "occlusionTexture" in m:
        img, smp = _resolve_texture(m["occlusionTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Occlusion (ADM)")
        tn.name = OCCLUSION_NODE
        _uv_node(nt, tn, m["occlusionTexture"].get("texCoord", 0), -900, y)
        mat.adm.occlusion_strength = m["occlusionTexture"].get("strength", 1.0)
        y -= 300
    ef = m.get("emissiveFactor", [0.0, 0.0, 0.0])
    strength = max(ef) if max(ef) > 0 else 0.0
    if strength > 0:
        bsdf.inputs["Emission Strength"].default_value = strength
        bsdf.inputs["Emission Color"].default_value = (ef[0] / strength, ef[1] / strength, ef[2] / strength, 1.0)
    if "emissiveTexture" in m:
        img, smp = _resolve_texture(m["emissiveTexture"])
        tn = _tex_node(nt, img, smp, False, -900, y, "Emissive")
        _uv_node(nt, tn, m["emissiveTexture"].get("texCoord", 0), -900, y)
        col = tn.outputs["Color"]
        if strength > 0 and any(abs(c / strength - 1.0) > 1e-6 for c in ef):
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-450, y)
            mix.inputs[0].default_value = 1.0
            ca, cb = _color_inputs(mix)[:2]
            nt.links.new(col, ca)
            cb.default_value = (ef[0] / strength, ef[1] / strength, ef[2] / strength, 1.0)
            col = next(o for o in mix.outputs if o.type == "RGBA")
        nt.links.new(col, bsdf.inputs["Emission Color"])
    apply_alpha_mode_to_material(mat, alpha_mode)
    if missing_textures:
        mat["adm_incomplete_textures"] = [
            str(item.get("index")) for item in missing_textures if isinstance(item, dict)
        ]
    return mat


def apply_alpha_mode_to_material(mat, mode):
    if mode == "BLEND":
        mat.surface_render_method = "BLENDED"
    else:
        mat.surface_render_method = "DITHERED"


def convert_to_adm_material(mat):
    """Normalize any material so it has an output -> Principled BSDF chain (keeps existing nodes)."""
    nt = mat.node_tree
    if principled_of(mat) is not None and output_surface_shader(mat) is not None and \
            output_surface_shader(mat).type == "BSDF_PRINCIPLED":
        return False
    color = tuple(mat.diffuse_color)
    old = output_surface_shader(mat)
    if old is not None:
        for name in ("Color", "Base Color"):
            if name in old.inputs and not old.inputs[name].is_linked and old.inputs[name].type == "RGBA":
                color = tuple(old.inputs[name].default_value)
                break
    out = material_output(mat)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (out.location.x - 300, out.location.y)
    bsdf.inputs["Base Color"].default_value = color
    if old is not None:
        for name in ("Color", "Base Color"):
            if name in old.inputs and old.inputs[name].is_linked:
                nt.links.new(old.inputs[name].links[0].from_socket, bsdf.inputs["Base Color"])
                break
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return True


# ================================================================================================
# PBR texture slots (Sollumz-style texture parameters on the material panel)
# ================================================================================================
# The slots edit exactly the node chains the exporter traces, so no extra state is stored.
TEXTURE_SLOTS = (
    # id, label, ADM material key, non-color data, icon
    ("BASE_COLOR", "Base Color", "baseColorTexture", False, "COLOR"),
    ("METALLIC_ROUGHNESS", "Metallic-Roughness", "metallicRoughnessTexture", True, "NODE_MATERIAL"),
    ("NORMAL", "Normal", "normalTexture", True, "NORMALS_FACE"),
    ("OCCLUSION", "Occlusion", "occlusionTexture", True, "SHADING_SOLID"),
    ("EMISSIVE", "Emissive", "emissiveTexture", False, "LIGHT_SUN"),
)
SLOT_IDS = tuple(s[0] for s in TEXTURE_SLOTS)
_SLOT_INPUTS = {"BASE_COLOR": ("Base Color", "Alpha"), "METALLIC_ROUGHNESS": ("Roughness", "Metallic"),
                "EMISSIVE": ("Emission Color",), "NORMAL": (), "OCCLUSION": ()}


def _slot_info(slot):
    return next(s for s in TEXTURE_SLOTS if s[0] == slot)


def normal_map_node(mat):
    bsdf = principled_of(mat)
    s = _from(bsdf.inputs["Normal"]) if bsdf is not None else None
    return s.node if s is not None and s.node.type == "NORMAL_MAP" else None


def slot_state(mat, slot):
    """('NONE' | 'TEXTURE' | 'CUSTOM', image texture node or None) for a PBR texture slot.

    CUSTOM means the BSDF input is driven by a node setup the slot editor must not overwrite.
    """
    if mat is None or mat.node_tree is None:
        return "NONE", None
    if slot == "OCCLUSION":
        n = mat.node_tree.nodes.get(OCCLUSION_NODE)
        return ("TEXTURE", n) if n is not None and n.type == "TEX_IMAGE" else ("NONE", None)
    bsdf = principled_of(mat)
    if bsdf is None:
        return "NONE", None
    if slot == "NORMAL":
        sock = bsdf.inputs["Normal"]
        if not sock.is_linked:
            return "NONE", None
        nm = normal_map_node(mat)
        if nm is None:
            return "CUSTOM", None
        sock = nm.inputs["Color"]
        if not sock.is_linked:
            return "NONE", None
        t = trace(sock)
        return ("TEXTURE", t["node"]) if t and t["node"] is not None else ("CUSTOM", None)
    custom = False
    for name in _SLOT_INPUTS[slot][:1] if slot != "METALLIC_ROUGHNESS" else _SLOT_INPUTS[slot]:
        sock = bsdf.inputs[name]
        if not sock.is_linked:
            continue
        t = trace(sock, allow_invert=slot == "METALLIC_ROUGHNESS")
        if t is not None and t["node"] is not None:
            return "TEXTURE", t["node"]
        custom = True
    return ("CUSTOM", None) if custom else ("NONE", None)


def slot_texture_node(mat, slot):
    state, node = slot_state(mat, slot)
    return node if state == "TEXTURE" else None


def pbr_channel_settings(mat, target):
    bsdf = principled_of(mat)
    if bsdf is None:
        return None
    info = trace(bsdf.inputs[target], allow_invert=True)
    return info if info and info["node"] is not None and not info["unsupported"] else None


def set_pbr_channel(mat, target, channel, invert):
    info = pbr_channel_settings(mat, target)
    if info is None:
        return
    nt = mat.node_tree
    bsdf = principled_of(mat)
    socket = bsdf.inputs[target]
    texture = info["node"]
    old = _chain_nodes(socket, texture) - {texture}
    for link in list(socket.links):
        nt.links.remove(link)
    if channel == "A":
        source = texture.outputs["Alpha"]
    else:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (texture.location.x + 320, texture.location.y)
        nt.links.new(texture.outputs["Color"], sep.inputs[0])
        source = sep.outputs[{"R": "Red", "G": "Green", "B": "Blue"}[channel]]
    if invert:
        inverse = nt.nodes.new("ShaderNodeMath")
        inverse.operation = "SUBTRACT"
        inverse.inputs[0].default_value = 1.0
        nt.links.new(source, inverse.inputs[1])
        source = inverse.outputs[0]
    factor = float(_scalar(info["factor"]))
    if abs(factor - 1.0) > 1e-6:
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = factor
        nt.links.new(source, mul.inputs[0])
        source = mul.outputs[0]
    nt.links.new(source, socket)
    while old:
        unused = [n for n in old if not any(o.is_linked for o in n.outputs)]
        if not unused:
            break
        for n in unused:
            old.remove(n)
            nt.nodes.remove(n)
    _refresh_existing_preview(mat)


def _slot_sockets(mat, slot):
    """BSDF/normal-map input sockets a slot drives (the ones a custom setup is detached from)."""
    if slot == "OCCLUSION":
        return []
    bsdf = principled_of(mat)
    if bsdf is None:
        return []
    if slot == "NORMAL":
        nm = normal_map_node(mat)
        return [nm.inputs["Color"]] if nm is not None else [bsdf.inputs["Normal"]]
    if slot == "BASE_COLOR":
        return [bsdf.inputs["Base Color"]]
    return [bsdf.inputs[n] for n in _SLOT_INPUTS[slot]]


_SLOT_HINTS = {
    "BASE_COLOR": re.compile(r"albedo|diffuse|base.?colou?r|(^|[_.\s])(ab|d|al|abal)($|[_.\s])", re.I),
    "METALLIC_ROUGHNESS": re.compile(r"mrao|metal|rough|orm|(^|[_.\s])(ma|mr|sm)($|[_.\s])", re.I),
    "NORMAL": re.compile(r"normal|(^|[_.\s])(nm|n|nrm)($|[_.\s])", re.I),
    "EMISSIVE": re.compile(r"emiss|emit|glow|(^|[_.\s])(em|e)($|[_.\s])", re.I),
}
_SLOT_EXCLUDE = re.compile(r"palette|(^|[_.\s])pal($|[_.\s])", re.I)


def custom_source_candidates(mat, slot):
    """Image texture nodes feeding a slot's custom node setup, best match first.

    Ranked by role hints in the node label/image name, then colour space (sRGB for colour slots,
    Non-Color for data slots), then graph distance. Emissive only accepts explicitly named textures.
    """
    _, _, _, non_color, _ = _slot_info(slot)
    hint = _SLOT_HINTS.get(slot)
    found = []
    seen, frontier = set(), [s for s in _slot_sockets(mat, slot) if s.is_linked]
    for depth in range(32):
        nxt = []
        for sock in frontier:
            for link in sock.links:
                if link.is_muted or not link.is_valid:
                    continue
                n = link.from_node
                if n in seen:
                    continue
                seen.add(n)
                if n.type == "TEX_IMAGE" and n.image is not None:
                    found.append((n, depth))
                nxt.extend(i for i in n.inputs if i.is_linked and i.enabled)
        if not nxt:
            break
        frontier = nxt

    def score(item):
        n, depth = item
        text = f"{n.label} {n.image.name}"
        named = bool(hint and hint.search(text))
        cs_ok = (n.image.colorspace_settings.name == "Non-Color") == non_color
        return (not named, not cs_ok, depth)

    ranked = [it for it in found if not _SLOT_EXCLUDE.search(f"{it[0].label} {it[0].image.name}")]
    if slot == "EMISSIVE":
        ranked = [it for it in ranked if hint.search(f"{it[0].label} {it[0].image.name}")]
    return [n for n, _d in sorted(ranked, key=score)]


def custom_source_node(mat, slot):
    """Best image texture of a slot's custom node setup (None if there is none)."""
    c = custom_source_candidates(mat, slot)
    return c[0] if c else None


def detach_custom(mat, slot):
    """Disconnect a slot's custom setup from the BSDF; its nodes stay in the tree for manual reuse."""
    nt = mat.node_tree
    for sock in _slot_sockets(mat, slot):
        for link in list(sock.links):
            nt.links.remove(link)


def _set_colorspace(image, non_color):
    if image is None:
        return
    try:
        image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except TypeError:
        pass


def set_slot_image(mat, slot, image, source=None):
    """Assign ``image`` to a PBR texture slot, creating the node chain the exporter reads.

    A custom node setup on the slot is disconnected (not deleted) and replaced by the simple chain;
    ``source`` optionally supplies sampler settings and UV map to copy from an existing texture node.
    """
    convert_to_adm_material(mat)
    _, label, _, non_color, _ = _slot_info(slot)
    state, node = slot_state(mat, slot)
    if state == "CUSTOM":
        detach_custom(mat, slot)
        node = None
    if node is not None:
        node.image = image
        _set_colorspace(image, non_color)
        _refresh_existing_preview(mat)
        return node
    nt = mat.node_tree
    bsdf = principled_of(mat)
    x = bsdf.location.x - 900
    y = bsdf.location.y + 300 - 300 * SLOT_IDS.index(slot)
    tn = _tex_node(nt, image, None, non_color, x, y, label)
    _set_colorspace(image, non_color)
    if source is not None:
        tn.interpolation = source.interpolation
        tn.extension = source.extension
        uv = _from(source.inputs["Vector"])
        if uv is not None and uv.node.type == "UVMAP" and uv.node.uv_map:
            _uv_node(nt, tn, 1, x, y)
            tn.inputs["Vector"].links[0].from_node.uv_map = uv.node.uv_map
    if slot == "BASE_COLOR":
        nt.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
        if mat.adm.alpha_mode in ("BLEND", "MASK") and not bsdf.inputs["Alpha"].is_linked:
            nt.links.new(tn.outputs["Alpha"], bsdf.inputs["Alpha"])
    elif slot == "METALLIC_ROUGHNESS":
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (x + 320, y)
        nt.links.new(tn.outputs["Color"], sep.inputs[0])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    elif slot == "NORMAL":
        nm = normal_map_node(mat)
        if nm is None:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.location = (x + 450, y)
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        uvs = _from(tn.inputs["Vector"])
        if uvs is not None and uvs.node.type == "UVMAP":
            nm.uv_map = uvs.node.uv_map
    elif slot == "OCCLUSION":
        tn.name = OCCLUSION_NODE
        tn.label = "Occlusion (ADM)"
    elif slot == "EMISSIVE":
        nt.links.new(tn.outputs["Color"], bsdf.inputs["Emission Color"])
        if bsdf.inputs["Emission Strength"].default_value <= 0.0:
            bsdf.inputs["Emission Strength"].default_value = 1.0
    _refresh_existing_preview(mat)
    return tn


def _chain_nodes(socket, end):
    """Nodes between ``socket`` and the texture node ``end`` (inclusive of ``end``)."""
    nodes = set()
    s = _from(socket)
    guard = 0
    while s is not None and guard < 16:
        guard += 1
        nodes.add(s.node)
        if s.node == end:
            return nodes
        linked = [i for i in s.node.inputs if i.is_linked and i.enabled]
        s = _from(linked[0]) if len(linked) == 1 else None
    return nodes if end in nodes else set()


def clear_slot(mat, slot):
    """Remove a slot's texture, keeping the constant factors its node chain applied."""
    node = slot_texture_node(mat, slot)
    if node is None:
        return False
    nt = mat.node_tree
    bsdf = principled_of(mat)
    doomed = {node}
    for name in _SLOT_INPUTS[slot]:
        sock = bsdf.inputs[name]
        t = trace(sock, allow_invert=slot == "METALLIC_ROUGHNESS")
        if t is None or t["node"] != node:
            continue
        doomed |= _chain_nodes(sock, node)
        f = t["factor"]
        for link in list(sock.links):
            nt.links.remove(link)
        if sock.type == "RGBA":
            rgb = f if isinstance(f, list) else [f] * 3
            sock.default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        else:
            sock.default_value = float(_scalar(f))
    if slot == "NORMAL":
        nm = normal_map_node(mat)
        if nm is not None:
            doomed.add(nm)
    uv = _from(node.inputs["Vector"])
    if uv is not None and uv.node.type == "UVMAP":
        doomed.add(uv.node)
    for n in doomed:
        if all(link.to_node in doomed or link.to_node == bsdf
               for o in n.outputs for link in o.links):
            nt.nodes.remove(n)
    _refresh_existing_preview(mat)
    return True


def slot_uv_index(node, uv_names):
    return _uv_index(node, list(uv_names)) if node is not None else 0


def set_slot_uv(mat, slot, index, uv_names):
    """Route a slot texture through UV map ``index`` (0 = default UV, 1 = second UV of the mesh)."""
    node = slot_texture_node(mat, slot)
    if node is None:
        return False
    nt = mat.node_tree
    uv_names = list(uv_names) or list(UV_NAMES)
    s = _from(node.inputs["Vector"])
    uvn = s.node if s is not None and s.node.type == "UVMAP" else None
    if index == 0:
        if uvn is not None and len([lk for o in uvn.outputs for lk in o.links]) == 1:
            nt.nodes.remove(uvn)
        elif uvn is not None:
            for link in list(node.inputs["Vector"].links):
                nt.links.remove(link)
        name = ""
    else:
        name = uv_names[1] if len(uv_names) > 1 else UV_NAMES[1]
        if uvn is None:
            uvn = nt.nodes.new("ShaderNodeUVMap")
            uvn.location = (node.location.x - 220, node.location.y)
            nt.links.new(uvn.outputs["UV"], node.inputs["Vector"])
        uvn.uv_map = name
    if slot == "NORMAL":
        nm = normal_map_node(mat)
        if nm is not None:
            nm.uv_map = name
    _refresh_existing_preview(mat)
    return True


def slot_alpha_linked(mat):
    node = slot_texture_node(mat, "BASE_COLOR")
    bsdf = principled_of(mat)
    if node is None or bsdf is None:
        return False
    t = trace(bsdf.inputs["Alpha"])
    return t is not None and t["node"] == node


def set_slot_alpha(mat, use):
    """Drive BSDF Alpha from the base color texture alpha (the only alpha source ADM exports)."""
    node = slot_texture_node(mat, "BASE_COLOR")
    if node is None:
        return False
    nt = mat.node_tree
    bsdf = principled_of(mat)
    sock = bsdf.inputs["Alpha"]
    if use:
        if not slot_alpha_linked(mat):
            for link in list(sock.links):
                nt.links.remove(link)
            nt.links.new(node.outputs["Alpha"], sock)
            _refresh_existing_preview(mat)
        return True
    if slot_alpha_linked(mat):
        t = trace(sock)
        doomed = _chain_nodes(sock, node) - {node}
        for link in list(sock.links):
            nt.links.remove(link)
        sock.default_value = float(_scalar(t["factor"]))
        for n in doomed:
            if not any(link.to_node not in doomed for o in n.outputs for link in o.links):
                nt.nodes.remove(n)
        _refresh_existing_preview(mat)
    return True


# ================================================================================================
# shader preview (Sollumz-style: switching the ADM shader updates the viewport material)
# ================================================================================================
# The preview is an extra node group (output + BSDF + mix nodes, all named "ADM Preview *") made the
# active output. The material's own output/BSDF stay untouched and remain the exported PBR fallback.
def _sock(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def _out(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)


def remove_shader_preview(mat):
    nt = mat.node_tree
    if nt is None:
        return False
    doomed = [n for n in nt.nodes if is_preview_node(n)]
    if nt.animation_data is not None:
        for fc in list(nt.animation_data.drivers):
            if f'nodes["{PREVIEW_PREFIX}' in fc.data_path:
                nt.animation_data.drivers.remove(fc)
    for n in doomed:
        nt.nodes.remove(n)
    out = material_output(mat)
    if out is not None:
        out.is_active_output = True
    return bool(doomed)


def _refresh_existing_preview(mat):
    if mat.node_tree and any(is_preview_node(node) for node in mat.node_tree.nodes):
        refresh_shader_preview(mat)


def _preview_mix(nt, kind, a, b, fac, x, y, name):
    n = nt.nodes.new("ShaderNodeMix")
    n.name = n.label = f"{PREVIEW_PREFIX} {name}"
    n.data_type = kind
    n.location = (x, y)
    suffix = {"RGBA": "Color", "FLOAT": "Float", "VECTOR": "Vector"}[kind]
    _sock(n, f"A_{suffix}").default_value = a
    _sock(n, f"B_{suffix}").default_value = b
    nt.links.new(fac, _sock(n, "Factor_Float"))
    return _out(n, f"Result_{suffix}")


def _build_layered_preview(mat):
    nt = mat.node_tree
    a = mat.adm
    base, over = a.layer_base, a.layer_overlay
    own = material_output(mat)
    x0, y0 = (own.location.x, own.location.y - 700) if own is not None else (300, -700)

    def new(kind, name, x, y):
        n = nt.nodes.new(kind)
        n.name = n.label = f"{PREVIEW_PREFIX} {name}"
        n.location = (x0 + x, y0 + y)
        return n

    # a = clamp(layer_factor * mask, 0, 1)   (spec §8.4)
    fac = new("ShaderNodeMath", "Layer Factor", -900, 0)
    fac.operation = "MULTIPLY"
    fac.use_clamp = True
    fac.inputs[1].default_value = 1.0
    fc = fac.inputs[0].driver_add("default_value")
    fc.driver.type = "AVERAGE"
    var = fc.driver.variables.new()
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "MATERIAL"
    var.targets[0].id = mat
    var.targets[0].data_path = "adm.layer_factor"
    fac.inputs[0].default_value = a.layer_factor
    if a.layer_mask is not None:
        tex = new("ShaderNodeTexImage", "Mask", -1400, 0)
        tex.image = a.layer_mask
        _uv_node(nt, tex, a.layer_mask_uv, tex.location.x, tex.location.y)
        uvs = _from(tex.inputs["Vector"])
        if uvs is not None:
            uvs.node.name = uvs.node.label = f"{PREVIEW_PREFIX} Mask UV"
        sep = new("ShaderNodeSeparateColor", "Mask Red", -1150, 0)
        nt.links.new(tex.outputs["Color"], sep.inputs[0])
        nt.links.new(sep.outputs["Red"], fac.inputs[1])
    f = fac.outputs[0]

    bsdf = new("ShaderNodeBsdfPrincipled", "BSDF", -300, 0)
    col = _preview_mix(nt, "RGBA", tuple(base.base_color), tuple(over.base_color), f, x0 - 600, y0 + 200, "Base Color")
    nt.links.new(col, bsdf.inputs["Base Color"])
    for i, (key, sock, va, vb) in enumerate((
            ("Alpha", "Alpha", base.base_color[3], over.base_color[3]),
            ("Metallic", "Metallic", base.metallic, over.metallic),
            ("Roughness", "Roughness", base.roughness, over.roughness))):
        r = _preview_mix(nt, "FLOAT", va, vb, f, x0 - 600, y0 - 20 - 200 * i, key)
        nt.links.new(r, bsdf.inputs[sock])
    em = _preview_mix(nt, "RGBA", (*base.emissive, 1.0), (*over.emissive, 1.0), f, x0 - 600, y0 - 620, "Emissive")
    nt.links.new(em, bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    if base.use_normal_factor or over.use_normal_factor:
        nb = tuple(base.normal_factor) if base.use_normal_factor else (0.0, 0.0, 1.0)
        no = tuple(over.normal_factor) if over.use_normal_factor else (0.0, 0.0, 1.0)
        n = _preview_mix(nt, "VECTOR", nb, no, f, x0 - 600, y0 - 840, "Normal")
        norm = new("ShaderNodeVectorMath", "Normalize", -450, -840)
        norm.operation = "NORMALIZE"
        nt.links.new(n, norm.inputs[0])
        enc = new("ShaderNodeVectorMath", "Encode", -300, -840)
        enc.operation = "MULTIPLY_ADD"
        enc.inputs[1].default_value = (0.5, 0.5, 0.5)
        enc.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(norm.outputs[0], enc.inputs[0])
        nm = new("ShaderNodeNormalMap", "Normal Map", -150, -840)
        nt.links.new(enc.outputs[0], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    out = new("ShaderNodeOutputMaterial", "Output", 0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    out.is_active_output = True
    return out


def refresh_shader_preview(mat):
    """Rebuild the viewport preview for the material's selected ADM shader.

    Version 1 keeps the original fallback and layered preview. Version 2 uses the registered
    COLOR_1 profile graph; custom shader definitions keep their portable PBR fallback.
    """
    if mat is None or mat.node_tree is None:
        return
    remove_shader_preview(mat)
    window = bpy.context.window_manager.adm if bpy.context.window_manager else None
    mask_preview = window is not None and window.vertex_color_preview
    if mat.adm.shader == "CORE":
        convert_to_adm_material(mat)
        if mat.adm.vertex_controls_enabled or K.has_color1_profile(
                mat.adm.shader, mat.adm.shader_version) or mask_preview:
            from . import shader_preview
            shader_preview.build(mat)
    elif mat.adm.shader == "LAYERED":
        if K.has_color1_profile(mat.adm.shader, mat.adm.shader_version) or mask_preview:
            from . import shader_preview
            shader_preview.build(mat)
        else:
            out = _build_layered_preview(mat)
            if mat.adm.vertex_controls_enabled and out is not None:
                from . import shader_preview
                bsdf = _from(out.inputs["Surface"])
                if bsdf is not None:
                    controlled = shader_preview.apply_vertex_controls(mat, bsdf.node)
                    if controlled != bsdf.node:
                        for link in list(out.inputs["Surface"].links):
                            mat.node_tree.links.remove(link)
                        mat.node_tree.links.new(controlled.outputs.get("Shader") or controlled.outputs["BSDF"],
                                                out.inputs["Surface"])
    else:
        from . import shader_preview
        if mat.adm.shader in shader_preview.BUILDERS or mat.adm.vertex_controls_enabled \
                or K.has_color1_profile(mat.adm.shader, mat.adm.shader_version) or mask_preview:
            convert_to_adm_material(mat)
            shader_preview.build(mat)


def has_profile_preview(shader_kind):
    from . import shader_preview
    return shader_kind in ("CORE", "LAYERED", "CUTOUT", "EMISSIVE", "DECAL", "INTERACTIVE") \
        or shader_kind in shader_preview.BUILDERS
