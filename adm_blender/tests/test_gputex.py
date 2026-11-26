"""ADM-TEX-KTX2-1 / ADM-TEX-DDS-1 container subset, BC1/BC3 codec and validator rules (spec §8.6)."""

import struct
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - CI installs numpy
    np = None

from adm_blender.core import constants as K
from adm_blender.core import gputex as G
from adm_blender.core.buffers import BinBuilder
from adm_blender.core.container import write_container
from adm_blender.core.png import encode_png
from adm_blender.core.validate import validate_adm


def gradient(h=37, w=53, alpha=True):
    y, x = np.mgrid[0:h, 0:w]
    a = np.where(x > w // 2, 96, 255) if alpha else np.full_like(x, 255)
    return np.stack([x * 255 // (w - 1), y * 255 // (h - 1), (x + y) * 255 // (w + h - 2), a], -1).astype(np.uint8)


def advanced_gpu_fixture(mime, kind, srgb=False, width=5, height=3):
    vk = {"R8": 9, "R16": 70, "BC4": 139, "BC5": 141, "BC7": 145}
    dxgi = {"R8": 61, "R16": 56, "BC4": 80, "BC5": 83, "BC7": 98}
    if kind == "BC7" and srgb:
        vk[kind], dxgi[kind] = 146, 99
    size = G.level_size(kind, width, height)
    payload = bytes(size)
    if mime == G.MIME_DDS:
        flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
        header = b"DDS " + struct.pack("<7I44x", 124, flags, height, width, size, 0, 1)
        header += struct.pack("<2I4s5I", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
        header += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        header += struct.pack("<5I", dxgi[kind], 3, 0, 1, 3)
        return header + payload

    block_size, edge = {"R8": (1, 1), "R16": (2, 1), "BC4": (8, 4), "BC5": (16, 4),
                        "BC7": (16, 4)}[kind]
    model = {"R8": 1, "R16": 1, "BC4": 131, "BC5": 132, "BC7": 134}[kind]
    sample_data = {
        "R8": [(0, 7, 0, 255)],
        "R16": [(0, 15, 0, 65535)],
        "BC4": [(0, 63, 0, 0xFFFFFFFF)],
        "BC5": [(0, 63, 0, 0xFFFFFFFF), (64, 63, 1, 0xFFFFFFFF)],
        "BC7": [(0, 127, 0, 0xFFFFFFFF)],
    }[kind]
    dfd = bytearray(28 + 16 * len(sample_data))
    struct.pack_into("<I", dfd, 0, len(dfd))
    struct.pack_into("<H", dfd, 8, 2)
    struct.pack_into("<H", dfd, 10, len(dfd) - 4)
    dfd[12:16] = bytes((model, 1, 2 if srgb else 1, 0))
    dfd[16:20] = bytes((edge.bit_length() - 1, edge.bit_length() - 1, 0, 0))
    dfd[20] = block_size
    for i, (bit_offset, bit_length, channel, upper) in enumerate(sample_data):
        struct.pack_into("<HBB4BII", dfd, 28 + 16 * i, bit_offset, bit_length, channel, 0, 0, 0, 0,
                         0, upper)
    offset = 80 + 24 + len(dfd)
    alignment = block_size * 4 // __import__("math").gcd(block_size, 4)
    offset += (-offset) % alignment
    type_size = 2 if kind == "R16" else 1
    header = G.KTX2_MAGIC + struct.pack("<9I", vk[kind], type_size, width, height, 0, 0, 1, 1, 0)
    header += struct.pack("<4I2Q", 104, len(dfd), 0, 0, 0, 0)
    header += struct.pack("<3Q", offset, size, size)
    return header + dfd + bytes(offset - (104 + len(dfd))) + payload


@unittest.skipIf(np is None, "numpy required")
class CodecTests(unittest.TestCase):
    def test_bc5_normal_reconstruction_normalizes_out_of_disk_samples(self):
        samples = np.array([[[0.5, 0.5, 0.0, 1.0], [1.0, 1.0, 0.0, 0.5]]], dtype=np.float32)
        decoded = G.reconstruct_bc5_normal(samples)
        np.testing.assert_allclose(decoded[0, 0], [0.5, 0.5, 1.0, 1.0], atol=1e-6)
        vectors = decoded[..., :3] * 2 - 1
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=-1), 1.0, atol=1e-6)
        self.assertAlmostEqual(float(decoded[0, 1, 2]), 0.5)
        self.assertAlmostEqual(float(decoded[0, 1, 3]), 0.5)
        with self.assertRaises(ValueError):
            G.reconstruct_bc5_normal(np.full((1, 1, 4), np.nan))

    def test_version_two_gpu_formats_parse_exact_odd_dimension_sizes(self):
        cases = (("R8", False), ("R16", False), ("BC4", False), ("BC5", False),
                 ("BC7", False), ("BC7", True))
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for kind, srgb in cases:
                with self.subTest(mime=mime, kind=kind, srgb=srgb):
                    blob = advanced_gpu_fixture(mime, kind, srgb)
                    info = G.parse(blob, mime, strict=True)
                    self.assertEqual((info["kind"], info["srgb"], info["width"], info["height"]),
                                     (kind, srgb, 5, 3))
                    self.assertEqual(info["levels"][0][1], G.level_size(kind, 5, 3))
                    self.assertEqual(info["capability"], f"ADM-TEX-{mime == G.MIME_KTX2 and 'KTX2' or 'DDS'}-2")

    def test_r16_ktx2_requires_two_byte_type_size(self):
        blob = bytearray(advanced_gpu_fixture(G.MIME_KTX2, "R16"))
        struct.pack_into("<I", blob, 16, 1)
        with self.assertRaisesRegex(G.GpuTextureError, "typeSize must be 2 for R16"):
            G.parse(blob, G.MIME_KTX2)

    def test_dds_rejects_excessive_mip_count_before_allocating_levels(self):
        blob = bytearray(advanced_gpu_fixture(G.MIME_DDS, "BC5"))
        flags, = struct.unpack_from("<I", blob, 8)
        struct.pack_into("<I", blob, 8, flags | 0x20000)
        struct.pack_into("<I", blob, 28, 0xFFFFFFFF)
        with self.assertRaisesRegex(G.GpuTextureError, "level count"):
            G.parse(blob, G.MIME_DDS, strict=False)

    def test_round_trip_every_container_format_and_colorspace(self):
        img = gradient()
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for kind, rgb_tol, a_tol in (("RGBA8", 0, 0), ("BC1", 6.0, None), ("BC3", 6.0, 0)):
                for srgb in (False, True):
                    with self.subTest(mime=mime, kind=kind, srgb=srgb):
                        blob, used = G.encode(img, mime, kind, srgb, mipmaps=True)
                        self.assertEqual(used, kind)
                        self.assertEqual(G.mime_of(blob), mime)
                        info = G.parse(blob, mime, strict=True)
                        self.assertEqual((info["kind"], info["srgb"], info["width"], info["height"]),
                                         (kind, srgb, 53, 37))
                        dims = [(lw, lh) for _, _, lw, lh in info["levels"]]
                        self.assertEqual(dims, [(53, 37), (26, 18), (13, 9), (6, 4), (3, 2), (1, 1)])
                        px, _ = G.decode(blob, mime, strict=True)
                        self.assertEqual(px.shape, (37, 53, 4))
                        err = np.abs(px[..., :3].astype(int) - img[..., :3]).mean()
                        self.assertLessEqual(err, rgb_tol)
                        if a_tol is not None:
                            self.assertLessEqual(np.abs(px[..., 3].astype(int) - img[..., 3]).max(), a_tol)
                        else:
                            self.assertTrue((px[..., 3] == 255).all())

    def test_bc1_solid_block_is_exact_and_bit_packed(self):
        px = np.zeros((4, 4, 4), np.uint8)
        px[...] = (255, 0, 0, 255)
        raw = G.encode_level(px, "BC1")
        self.assertEqual(len(raw), 8)
        c0, c1, bits = struct.unpack("<HHI", raw)
        self.assertEqual((c0, c1, bits), (0xF800, 0xF800, 0))
        # Two-colour block: left half white, right half black -> indices 0 (c0) and 1 (c1).
        px[:, :2] = (255, 255, 255, 255)
        px[:, 2:] = (0, 0, 0, 255)
        c0, c1, bits = struct.unpack("<HHI", G.encode_level(px, "BC1"))
        self.assertEqual((c0, c1), (0xFFFF, 0x0000))
        self.assertEqual(bits, sum(1 << (2 * i) for i in range(16) if i % 4 >= 2))
        info = {"kind": "BC1", "levels": [(0, 8, 4, 4)]}
        out = G.decode_level(G.encode_level(px, "BC1"), info)
        self.assertTrue((out == px).all())

    def test_bc3_alpha_block_uses_eight_value_palette(self):
        px = np.zeros((4, 4, 4), np.uint8)
        px[..., 3] = np.arange(16).reshape(4, 4) * 17          # 0..255
        raw = G.encode_level(px, "BC3")
        self.assertEqual(len(raw), 16)
        self.assertEqual((raw[0], raw[1]), (255, 0))
        out = G.decode_level(raw, {"kind": "BC3", "levels": [(0, 16, 4, 4)]})
        self.assertLessEqual(np.abs(out[..., 3].astype(int) - px[..., 3]).max(), 255 // 14 + 1)

    def test_bc4_bc5_round_trip_both_containers_and_normal_mips(self):
        source = gradient(alpha=False)
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for kind, channels in (("BC4", (0,)), ("BC5", (0, 1))):
                with self.subTest(mime=mime, kind=kind):
                    blob, used = G.encode(source, mime, kind, mipmaps=True)
                    self.assertEqual(used, kind)
                    info = G.parse(blob, mime, strict=True)
                    self.assertEqual(len(info["levels"]), 6)
                    decoded, _ = G.decode(blob, mime, strict=True)
                    self.assertLessEqual(
                        np.abs(decoded[..., channels].astype(int) - source[..., channels]).mean(), 8)
                    self.assertTrue((decoded[..., 3] == 255).all())
                    for channel in set((0, 1, 2)) - set(channels):
                        self.assertTrue((decoded[..., channel] == 0).all())

        normals = np.zeros((2, 2, 4), dtype=np.uint8)
        normals[..., 0] = np.array([[255, 0], [255, 0]], dtype=np.uint8)
        normals[..., 1] = 128
        mip = G.normal_mip_chain(normals)[1][0, 0]
        x, y = (mip[:2].astype(float) / 255.0) * 2.0 - 1.0
        z = np.sqrt(max(0.0, 1.0 - x * x - y * y))
        self.assertAlmostEqual(np.sqrt(x * x + y * y + z * z), 1.0, delta=1e-5)

    def test_bc4_bc5_spec_derived_solid_block_vectors(self):
        red = np.zeros((4, 4, 4), dtype=np.uint8)
        red[..., 0] = 255
        red[..., 3] = 255
        bc4_block = bytes((255, 255, 0, 0, 0, 0, 0, 0))
        self.assertEqual(G.encode_level(red, "BC4"), bc4_block)
        decoded = G.decode_level(bc4_block, {"kind": "BC4", "levels": [(0, 8, 4, 4)]})
        self.assertTrue((decoded[..., 0] == 255).all())

        blue = np.zeros((4, 4, 4), dtype=np.uint8)
        blue[..., 0] = 255
        blue[..., 3] = 255
        bc5_block = bc4_block + bytes((0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(G.encode_level(blue, "BC5"), bc5_block)
        decoded = G.decode_level(bc5_block, {"kind": "BC5", "levels": [(0, 16, 4, 4)]})
        self.assertTrue((decoded[..., 0] == 255).all())
        self.assertTrue((decoded[..., 1] == 0).all())

    def test_bc7_encoder_emits_mode_six_blocks(self):
        pixels = np.full((4, 4, 4), 128, dtype=np.uint8)
        encoded = G.encode_level(pixels, "BC7")
        self.assertEqual(len(encoded), 16)
        self.assertEqual(encoded[0] & 0x7F, 0x40)

    def test_repackage_ktx_as_dds_preserves_bc7_mips(self):
        blob, _ = G.encode(gradient(alpha=True), G.MIME_KTX2, "BC7", srgb=True, mipmaps=True)
        original = G.parse(blob, G.MIME_KTX2)
        wrapped = G.repackage_bc7_as_dds(blob)
        converted = G.parse(wrapped, G.MIME_DDS)
        self.assertEqual((converted["kind"], converted["srgb"]), ("BC7", True))
        self.assertEqual(len(original["levels"]), len(converted["levels"]))
        for src, dst in zip(original["levels"], converted["levels"]):
            self.assertEqual(src[2:], dst[2:])
            self.assertEqual(blob[src[0]:src[0] + src[1]], wrapped[dst[0]:dst[0] + dst[1]])
        non_bc7, _ = G.encode(gradient(), G.MIME_KTX2, "BC1", mipmaps=False)
        with self.assertRaisesRegex(G.GpuTextureError, "requires BC7"):
            G.repackage_bc7_as_dds(non_bc7)

    def test_bc4_bc5_match_independent_decoder(self):
        try:
            import texture2ddecoder
        except ImportError:
            self.skipTest("texture2ddecoder is an optional independent verification dependency")
        y, x = np.mgrid[:37, :53]
        source = np.zeros((37, 53, 4), dtype=np.uint8)
        source[..., 0] = x * 255 // 52
        source[..., 1] = y * 255 // 36
        source[..., 3] = 255
        for kind in ("BC4", "BC5"):
            with self.subTest(kind=kind):
                blob, _ = G.encode(source, G.MIME_DDS, kind, mipmaps=False)
                info = G.parse(blob, G.MIME_DDS, strict=True)
                offset, _, _, _ = info["levels"][0]
                expected = G.decode(blob, G.MIME_DDS, strict=True)[0]
                raw = getattr(texture2ddecoder, f"decode_{kind.lower()}")(blob[offset:], 53, 37)
                actual = np.frombuffer(raw, dtype=np.uint8).reshape(37, 53, 4)[..., [2, 1, 0, 3]]
                self.assertTrue(np.array_equal(actual, expected))

    def test_bc7_decoding_matches_independent_decoder(self):
        try:
            import texture2ddecoder
        except ImportError:
            self.skipTest("texture2ddecoder is an optional BC7 decoder dependency")
        source = gradient(alpha=True)
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for srgb in (False, True):
                with self.subTest(mime=mime, srgb=srgb):
                    blob, _ = G.encode(source, mime, "BC7", srgb=srgb, mipmaps=False)
                    info = G.parse(blob, mime, strict=True)
                    offset, _, width, height = info["levels"][0]
                    expected_bytes = texture2ddecoder.decode_bc7(blob[offset:], width, height)
                    expected = np.frombuffer(expected_bytes, dtype=np.uint8).reshape(
                        height, width, 4)[..., [2, 1, 0, 3]]
                    decoded, _ = G.decode(blob, mime, strict=True)
                    self.assertTrue(np.array_equal(decoded, expected))
                    self.assertLessEqual(
                        np.abs(decoded.astype(int) - source).mean(), 18)

    def test_r8_r16_and_bc4_scalar_codecs_preserve_precision(self):
        samples8 = np.array([[0, 50, 150], [200, 250, 255], [3, 5, 7]], dtype=np.uint8)
        samples16 = np.array([[0, 1001, 2002, 3003], [4004, 5005, 6006, 65535],
                              [500, 1000, 2000, 4000], [10000, 20000, 30000, 40000]], dtype=np.uint16)
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for kind, samples in (("R8", samples8), ("R16", samples16), ("BC4", samples8)):
                with self.subTest(mime=mime, kind=kind):
                    blob, used = G.encode_scalar(samples, mime, kind, mipmaps=True)
                    self.assertEqual(used, kind)
                    info = G.parse(blob, mime, strict=True)
                    decoded, _ = G.decode_scalar(blob, mime, strict=True)
                    self.assertEqual(decoded.dtype, samples.dtype if kind != "BC4" else np.uint8)
                    if kind == "BC4":
                        self.assertLessEqual(np.abs(decoded.astype(int) - samples).mean(), 8)
                    else:
                        self.assertTrue(np.array_equal(decoded, samples))
                    self.assertEqual(len(info["levels"]), 3 if kind == "R16" else 2)
                    if kind == "R16":
                        offset, length, _, _ = info["levels"][0]
                        self.assertEqual(blob[offset:offset + length], samples.astype("<u2").tobytes())
                        self.assertEqual(G.decode_scalar_level(blob, info, 1)[0, 0], 2503)

    def test_mips_are_filtered_in_linear_light_for_srgb(self):
        px = np.zeros((2, 2, 4), np.uint8)
        px[0] = (255, 255, 255, 255)
        px[1] = (0, 0, 0, 255)
        self.assertEqual(G.mip_chain(px, srgb=False)[1][0, 0, 0], 128)
        self.assertEqual(G.mip_chain(px, srgb=True)[1][0, 0, 0], 188)    # sRGB(0.5 linear)
        self.assertEqual(G.mip_chain(px, srgb=True)[1][0, 0, 3], 255)
        self.assertEqual(len(G.mip_chain(px, True, mipmaps=False)), 1)

    def test_auto_picks_bc1_for_opaque_and_bc3_for_alpha(self):
        self.assertEqual(G.encode(gradient(alpha=False), G.MIME_DDS)[1], "BC1")
        self.assertEqual(G.encode(gradient(alpha=True), G.MIME_DDS)[1], "BC3")

    def test_ktx2_layout_fields(self):
        blob, _ = G.encode(gradient(8, 8), G.MIME_KTX2, "BC3", srgb=True)
        vk, type_size, w, h, depth, layers, faces, levels, scheme = struct.unpack_from("<9I", blob, 12)
        self.assertEqual((vk, type_size, w, h, depth, layers, faces, levels, scheme), (138, 1, 8, 8, 0, 0, 1, 4, 0))
        index = [struct.unpack_from("<3Q", blob, 80 + 24 * i) for i in range(levels)]
        offsets = [o for o, _, _ in index]
        self.assertEqual(offsets, sorted(offsets, reverse=True), "smallest mip stored first")
        self.assertTrue(all(o % 16 == 0 for o in offsets))
        dfd_off, = struct.unpack_from("<I", blob, 48)
        model, primaries, transfer = struct.unpack_from("<3B", blob, dfd_off + 12)
        self.assertEqual((model, primaries, transfer), (130, 1, 2))
        self.assertIn(b"KTXwriter\x00", blob)

    def test_dds_dx10_header_fields(self):
        blob, _ = G.encode(gradient(8, 8, alpha=False), G.MIME_DDS, "BC1", srgb=False)
        self.assertEqual(blob[84:88], b"DX10")
        h, w = struct.unpack_from("<2I", blob, 12)
        mips, = struct.unpack_from("<I", blob, 28)
        dxgi, dim, misc, array, _ = struct.unpack_from("<5I", blob, 128)
        self.assertEqual((h, w, mips, dxgi, dim, misc, array), (8, 8, 4, 71, 3, 0, 1))
        self.assertEqual(len(blob), 148 + 32 + 8 + 8 + 8)

    def test_strict_subset_rejections(self):
        good, _ = G.encode(gradient(8, 8), G.MIME_KTX2, "RGBA8")

        def patched(offset, fmt, value):
            b = bytearray(good)
            struct.pack_into(fmt, b, offset, value)
            return bytes(b)

        for name, blob in (("supercompressed", patched(44, "<I", 2)),
                           ("cubemap", patched(36, "<I", 6)),
                           ("array", patched(32, "<I", 2)),
                           ("BC7", patched(12, "<I", 145)),
                           ("trailing", good + b"\0\0\0\0"),
                           ("truncated", good[:-1])):
            with self.subTest(name):
                with self.assertRaises(G.GpuTextureError):
                    G.parse(blob, G.MIME_KTX2, strict=True)

    def test_ktx2_rejects_overlapping_mip_payloads(self):
        blob, _ = G.encode(gradient(8, 8), G.MIME_KTX2, "BC3")
        first_level_offset, = struct.unpack_from("<Q", blob, 80)
        corrupted = bytearray(blob)
        struct.pack_into("<Q", corrupted, 104, first_level_offset)
        with self.assertRaisesRegex(G.GpuTextureError, "overlaps"):
            G.parse(corrupted, G.MIME_KTX2, strict=True)

    def test_legacy_dds_only_accepted_for_source_conversion(self):
        px = gradient(8, 8, alpha=False)
        data = G.encode_level(px, "BC1")
        head = b"DDS " + struct.pack("<7I44x", 124, 0x81007, 8, 8, len(data), 0, 1)
        head += struct.pack("<2I4s5I", 32, 0x4, b"DXT1", 0, 0, 0, 0, 0) + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        legacy = head + data
        with self.assertRaises(G.GpuTextureError):
            G.parse(legacy, G.MIME_DDS, strict=True)
        out, info = G.decode(legacy)
        self.assertEqual(info["kind"], "BC1")
        same = G.decode_level(data, {"kind": "BC1", "levels": [(0, len(data), 8, 8)]})
        self.assertTrue((out == same).all())
        # 32-bit BGRA with masks.
        bgra = px[..., [2, 1, 0, 3]].tobytes()
        head = b"DDS " + struct.pack("<7I44x", 124, 0x100F, 8, 8, 32, 0, 1)
        head += struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
        head += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        out, _ = G.decode(head + bgra)
        self.assertTrue((out == px).all())


@unittest.skipIf(np is None, "numpy required")
class ValidatorTests(unittest.TestCase):
    def model(self, mime, kind="BC1", srgb=True, fallback_size=(8, 8), role="baseColorTexture", fallback=True,
              height_extension=None, declare_height_extension=True, shader=None, shader_parameters=None):
        img = gradient(8, 8, alpha=kind == "BC3")
        b = BinBuilder()
        primary = b.add_view(G.encode(img, mime, kind, srgb)[0], chunk_type="IMAG")
        fw, fh = fallback_size
        alt = b.add_view(encode_png(fw, fh, bytes(4 * fw * fh)), chunk_type="IMAG")
        tex = {"source": 0, "fallbackSource": 1} if fallback else {"source": 0}
        material = {role: {"index": 0}}
        if shader is not None:
            material.update({
                "shader": {"id": shader[0], "version": shader[1]},
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
                "emissiveFactor": [0.0, 0.0, 0.0],
                "alphaMode": "OPAQUE",
            })
        if shader_parameters is not None:
            material["shaderParameters"] = shader_parameters
        if height_extension is not None:
            material["extensions"] = {K.MATERIAL_HEIGHT_EXT: height_extension}
        doc = {"asset": {}, "nodes": [{}], "scenes": [{"nodes": [0]}], "scene": 0, "meshes": [],
               "accessors": [], "bufferViews": b.buffer_views,
               "images": [{"bufferView": primary, "mimeType": mime}, {"bufferView": alt, "mimeType": "image/png"}],
               "textures": [tex], "materials": [material]}
        if height_extension is not None and declare_height_extension:
            doc["extensionsUsed"] = [K.MATERIAL_HEIGHT_EXT]
        return validate_adm(write_container(K.ADM_MAGIC, doc, b.bytes()))

    def test_valid_ktx2_and_dds_with_fallback(self):
        for mime in (G.MIME_KTX2, G.MIME_DDS):
            for kind in ("RGBA8", "BC1", "BC3"):
                with self.subTest(mime=mime, kind=kind):
                    report = self.model(mime, kind)
                    self.assertTrue(report.ok, report.format())
        self.assertTrue(self.model(G.MIME_DDS, srgb=False, role="normalTexture").ok)

    def test_rule_violations(self):
        cases = ((dict(mime=G.MIME_DDS, fallback=False), "IMAGE_FALLBACK_REQUIRED"),
                 (dict(mime=G.MIME_KTX2, fallback_size=(4, 8)), "IMAGE_FALLBACK_SIZE"),
                 (dict(mime=G.MIME_KTX2, srgb=False), "IMAGE_COLORSPACE"),
                 (dict(mime=G.MIME_DDS, srgb=True, role="metallicRoughnessTexture"), "IMAGE_COLORSPACE"))
        for kwargs, code in cases:
            with self.subTest(code=code, **{k: v for k, v in kwargs.items() if k != "mime"}):
                self.assertIn(code, {e.code for e in self.model(**kwargs).errors})

    def test_layered_height_profiles_validate_enum_steps_uv_sets_and_texture_roles(self):
        profile = (K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V2)
        valid = self.model(
            G.MIME_KTX2, shader=profile,
            shader_parameters={"parallax_mode": "PARALLAX_OCCLUSION",
                               "parallax_min_steps": 12, "parallax_max_steps": 48},
        )
        self.assertTrue(valid.ok, valid.format())

        invalid_enum = self.model(
            G.MIME_KTX2, shader=profile, shader_parameters={"parallax_mode": "GEOMETRIC_DISPLACEMENT"},
        )
        self.assertIn("SHADER_PARAM_VALUE", {issue.code for issue in invalid_enum.errors})

        invalid_steps = self.model(
            G.MIME_KTX2, shader=profile,
            shader_parameters={"parallax_min_steps": 49, "parallax_max_steps": 48},
        )
        self.assertIn("SHADER_POM_STEPS", {issue.code for issue in invalid_steps.errors})

        invalid_maps = self.model(
            G.MIME_KTX2, shader=(K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V1),
            shader_parameters={"layer0_texture": {"index": 0, "texCoord": 0},
                               "layer0_ao_texture": {"index": 0, "texCoord": 1}},
        )
        codes = {issue.code for issue in invalid_maps.errors}
        self.assertIn("SHADER_LAYER_TEXCOORD", codes)
        self.assertIn("IMAGE_COLORSPACE", codes)
        emissive = self.model(
            G.MIME_KTX2, shader=(K.SHADER_TERRAIN_4[0], K.SHADER_PROFILE_LAYERED_HEIGHT_V1),
            shader_parameters={"layer0_emissive_texture": {"index": 0}},
        )
        self.assertTrue(emissive.ok, emissive.format())

    def test_material_height_extension_validates_uvs_ranges_and_parallax_requirements(self):
        extension = {
            "version": "1.0.0",
            "heightTexture": {"index": 0, "texCoord": 1},
            "channel": "G",
            "invert": True,
            "scale": 0.4,
            "bias": -0.1,
            "referenceHeight": 0.5,
            "parallaxMode": "PARALLAX_OCCLUSION",
            "parallaxScale": 0.025,
            "pomMinSteps": 12,
            "pomMaxSteps": 48,
        }
        report = self.model(G.MIME_KTX2, height_extension=extension)
        self.assertTrue(report.ok, report.format())

        invalid = (
            ({"channel": "Q"}, "MATERIAL_HEIGHT_CHANNEL"),
            ({"scale": -0.1}, "MATERIAL_RANGE"),
            ({"parallaxMode": "MAGIC"}, "MATERIAL_HEIGHT_PARALLAX"),
            ({"pomMinSteps": 49, "pomMaxSteps": 48}, "MATERIAL_HEIGHT_POM_STEPS"),
            ({"heightTexture": {"index": 0, "texCoord": 2}}, "MATERIAL_TEXCOORD"),
        )
        for update, expected in invalid:
            with self.subTest(expected=expected):
                candidate = dict(extension)
                candidate.update(update)
                result = self.model(G.MIME_KTX2, height_extension=candidate)
                self.assertIn(expected, {issue.code for issue in result.errors})

    def test_material_height_extension_must_be_declared(self):
        extension = {"version": "1.0.0", "heightTexture": {"index": 0, "texCoord": 1}}
        result = self.model(G.MIME_KTX2, height_extension=extension, declare_height_extension=False)
        self.assertIn("EXTENSION_NOT_DECLARED", {issue.code for issue in result.errors})


if __name__ == "__main__":
    unittest.main()
