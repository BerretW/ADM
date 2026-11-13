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


@unittest.skipIf(np is None, "numpy required")
class CodecTests(unittest.TestCase):
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
    def model(self, mime, kind="BC1", srgb=True, fallback_size=(8, 8), role="baseColorTexture", fallback=True):
        img = gradient(8, 8, alpha=kind == "BC3")
        b = BinBuilder()
        primary = b.add_view(G.encode(img, mime, kind, srgb)[0], chunk_type="IMAG")
        fw, fh = fallback_size
        alt = b.add_view(encode_png(fw, fh, bytes(4 * fw * fh)), chunk_type="IMAG")
        tex = {"source": 0, "fallbackSource": 1} if fallback else {"source": 0}
        doc = {"asset": {}, "nodes": [{}], "scenes": [{"nodes": [0]}], "scene": 0, "meshes": [],
               "accessors": [], "bufferViews": b.buffer_views,
               "images": [{"bufferView": primary, "mimeType": mime}, {"bufferView": alt, "mimeType": "image/png"}],
               "textures": [tex], "materials": [{role: {"index": 0}}]}
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


if __name__ == "__main__":
    unittest.main()
