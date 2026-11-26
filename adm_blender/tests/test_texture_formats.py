"""Blender test: export image formats (PNG default, Keep PNG/JPEG, KTX2/DDS + PNG fallback).

Run: blender -b --factory-startup --python adm_blender/tests/test_texture_formats.py
Checks real pixel values: source JPEG/DDS/KTX2 textures convert to PNG, GPU primaries carry the
right sRGB/UNORM variant and match their PNG fallback, Blender (OpenImageIO) reads the add-on's
DDS output identically to the add-on decoder, and import resolves the fallback.
"""
import hashlib
import os
import random
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import adm_blender  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def gradient(h, w, alpha=255):
    y, x = np.mgrid[0:h, 0:w]
    return np.stack([x * 255 // (w - 1), y * 255 // (h - 1), np.full_like(x, 90),
                     np.full_like(x, alpha)], -1).astype(np.uint8)


def blender_image(name, rgba):
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set((rgba[::-1].astype(np.float32) / 255.0).ravel())
    img.pack()
    return img


def u8(px):
    return (np.clip(px, 0, 1) * 255 + 0.5).astype(np.uint8)


def main(tmp):
    adm_blender.register()
    from adm_blender.blender import materials as M
    from adm_blender.blender.export_adm import ExportOptions, ModelExporter
    from adm_blender.blender.import_adm import ImportOptions, ModelImporter
    from adm_blender.core import gputex as G
    from adm_blender.core.buffers import read_view
    from adm_blender.core.container import read_container
    from adm_blender.core import constants as K

    def blob_pixels(blob, ext):
        p = os.path.join(tmp, f"probe_{len(os.listdir(tmp))}{ext}")
        with open(p, "wb") as fh:
            fh.write(blob)
        img = bpy.data.images.load(p)
        px = u8(M.image_pixels(img))
        bpy.data.images.remove(img)
        return px

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = bpy.context.active_object
    mat = bpy.data.materials.new("Formats")
    cube.data.materials.append(mat)
    bpy.ops.adm.create_model_root(name="Box")
    root = bpy.data.objects["Box"]

    base_px = gradient(16, 24)
    normal_px = gradient(8, 8)
    normal_px[..., 2] = 255

    print("== source textures in DDS / KTX2 / JPEG")
    # DDS written by the add-on, read by Blender's own (OpenImageIO) DDS reader.
    dds_path = os.path.join(tmp, "occlusion.dds")
    occ_px = gradient(8, 12)
    with open(dds_path, "wb") as fh:
        fh.write(G.encode(occ_px, G.MIME_DDS, "RGBA8", srgb=False, mipmaps=True)[0])
    dds_img = bpy.data.images.load(dds_path)
    check(tuple(dds_img.size) == (12, 8), f"Blender reads add-on DDS ({tuple(dds_img.size)})")
    check((u8(M.image_pixels(dds_img)) == occ_px).all(), "Blender DDS pixels identical to source")
    for kind in ("BC1", "BC3"):
        blob = G.encode(gradient(16, 16, 128 if kind == "BC3" else 255), G.MIME_DDS, kind)[0]
        diff = np.abs(blob_pixels(blob, ".dds").astype(int) - G.decode(blob)[0]).max()
        check(diff <= 1, f"OpenImageIO and add-on decode {kind} DDS identically (max diff {diff})")

    ktx_path = os.path.join(tmp, "emissive.ktx2")
    emi_px = gradient(8, 8)
    with open(ktx_path, "wb") as fh:
        fh.write(G.encode(emi_px, G.MIME_KTX2, "RGBA8", srgb=True)[0])
    ktx_img = M.load_image_file(ktx_path)
    check(ktx_img.packed_file is not None and ktx_img.colorspace_settings.name == "sRGB",
          "KTX2 file decoded by the add-on and packed as sRGB")
    check((u8(M.image_pixels(ktx_img)) == emi_px).all(), "KTX2 pixels preserved on load")
    bc7_pixels = gradient(7, 13, 180)
    for srgb in (False, True):
        bc7_ktx_path = os.path.join(tmp, f"bc7_{srgb}.ktx2")
        bc7_dds_path = os.path.join(tmp, f"bc7_{srgb}.dds")
        for bc7_path, bc7_mime in ((bc7_ktx_path, G.MIME_KTX2), (bc7_dds_path, G.MIME_DDS)):
            with open(bc7_path, "wb") as fh:
                fh.write(G.encode(bc7_pixels, bc7_mime, "BC7", srgb=srgb, mipmaps=True)[0])
        bc7_ktx = M.load_image_file(bc7_ktx_path)
        bc7_dds = bpy.data.images.load(bc7_dds_path)
        bc7_dds.colorspace_settings.name = "Non-Color"
        check(bc7_ktx.colorspace_settings.name == ("sRGB" if srgb else "Non-Color")
              and np.array_equal(u8(M.image_pixels(bc7_ktx)), u8(M.image_pixels(bc7_dds))),
              f"BC7 KTX2 srgb={srgb} uses native DDS decoding for odd dimensions")
    bc7_ref = bpy.data.images.new("bc7_ref", 1, 1)
    bc7_ref.source, bc7_ref.filepath = "FILE", bc7_ktx_path
    bc7_exporter = M.MaterialExporter(None, lambda warning: None)
    check(np.array_equal(u8(bc7_exporter._pixels(bc7_ref, False)), u8(M.image_pixels(bc7_dds))),
          "unloaded BC7 KTX2 file reference decodes for export")
    # Expected RGBA hashes were generated with the independent texture2ddecoder package.
    hashes = (
        "c65d0c24a6f988d4de8a879f19a1682252a5c22b18e9652851ec4ab81be626a1",
        "b8d0bf4c0f6f54eb54b9193b548813315ddb3222b9eb3a5d686722c9b5a9dc36",
        "42777edab8433bada288c9007677079ede19e37cd38631a585867489319b355b",
        "c3097bf8e51fc561ad039817873858f16de25f4cbd9de7cdf9b52587f7e05d03",
        "8fc6c140e71d463f3a89911f009d8b8a40998e72e7f283783320fcc08f8e88e7",
        "bc66539d47bf8574ca1b317d8b6d2115676bf171253aba21835495ac79dbfe4c",
        "54e9c16bb256256ab1ad79d0783b4b235251e5dff428f4ccd9b24171ccf17997",
        "095bd0f23a0bf5afbcfa945a74cdb1296fa6ad52696272eabc2e2452271db957",
    )
    rng = random.Random(4792)
    for mode, expected_hash in enumerate(hashes):
        block = bytearray(rng.getrandbits(8) for _ in range(16))
        block[0] = (block[0] & (255 << (mode + 1))) | (1 << mode)
        path = os.path.join(tmp, f"bc7_mode_{mode}.ktx2")
        with open(path, "wb") as fh:
            fh.write(G._write_ktx2_data([bytes(block)], 4, 4, "BC7", False))
        decoded = M.load_image_file(path)
        digest = hashlib.sha256(u8(M.image_pixels(decoded)).tobytes()).hexdigest()
        check(digest == expected_hash, f"BC7 mode {mode} matches independent decoder vector")
    bc7_ktx.use_fake_user = True
    bc7_name = bc7_ktx.name
    bc7_expected = u8(M.image_pixels(bc7_ktx))
    # An image that merely references a .ktx2 path (as other importers create) is decoded on export.
    raw_ktx = bpy.data.images.new("ktx_ref", 1, 1)
    raw_ktx.source, raw_ktx.filepath = "FILE", ktx_path

    jpg_path = os.path.join(tmp, "base.jpg")
    tmp_img = blender_image("jpg_src", base_px)
    tmp_img.filepath_raw, tmp_img.file_format = jpg_path, "JPEG"
    tmp_img.save()
    jpg_img = bpy.data.images.load(jpg_path)

    M.set_slot_image(mat, "BASE_COLOR", jpg_img)
    M.set_slot_image(mat, "NORMAL", blender_image("normal", normal_px))
    M.set_slot_image(mat, "OCCLUSION", dds_img)
    M.set_slot_image(mat, "EMISSIVE", raw_ktx)
    M.principled_of(mat).inputs["Emission Strength"].default_value = 1.0

    def export(**kw):
        data, rep = ModelExporter(bpy.context, root, ExportOptions(**kw)).export()
        check(rep.ok, f"{kw or 'default'}: export valid ({len(rep.errors)} errors)")
        doc, chunks = read_container(data, K.ADM_MAGIC)
        return data, doc, chunks

    def tex_blob(doc, chunks, key, which="source"):
        t = doc["textures"][doc["materials"][0][key]["index"]]
        im = doc["images"][t[which]]
        return read_view(doc, chunks, im["bufferView"]), im["mimeType"], t

    print("== preserve supported source formats across ADM round-trip", flush=True)
    for gpu_mime, extension in ((G.MIME_DDS, "dds"), (G.MIME_KTX2, "ktx2")):
        for kind in ("R8", "R16", "BC4", "BC5", "BC7"):
            if kind in ("R8", "R16", "BC4"):
                dtype = np.uint16 if kind == "R16" else np.uint8
                scalar = np.arange(64, dtype=dtype).reshape(8, 8)
                if kind == "R16":
                    scalar *= 1001
                original, _ = G.encode_scalar(scalar, gpu_mime, kind, mipmaps=True)
            else:
                original, _ = G.encode(gradient(8, 8), gpu_mime, kind, srgb=False, mipmaps=True)
            source_path = os.path.join(tmp, f"source_{kind}.{extension}")
            with open(source_path, "wb") as stream:
                stream.write(original)
            M.set_slot_image(mat, "OCCLUSION", M.load_image_file(source_path))
            source_data, source_doc, source_chunks = export()
            emitted, emitted_mime, _ = tex_blob(source_doc, source_chunks, "occlusionTexture")
            check(emitted == original and emitted_mime == gpu_mime,
                  f"{kind} {extension}: authoring retains complete GPU source")
            adm_path = os.path.join(tmp, f"source_{kind}_{extension}.adm")
            with open(adm_path, "wb") as stream:
                stream.write(source_data)
            imported = ModelImporter(bpy.context, adm_path, ImportOptions())
            imported.run()
            emitted_data, report = ModelExporter(bpy.context, imported.root, ExportOptions()).export()
            emitted_doc, emitted_chunks = read_container(emitted_data, K.ADM_MAGIC)
            emitted, emitted_mime, _ = tex_blob(emitted_doc, emitted_chunks, "occlusionTexture")
            check(report.ok and emitted == original and emitted_mime == gpu_mime,
                  f"{kind} {extension}: import and export retain complete GPU source")
    M.set_slot_image(mat, "OCCLUSION", dds_img)

    color_source, _ = G.encode(gradient(8, 8), G.MIME_KTX2, "BC7", srgb=True, mipmaps=True)
    color_path = os.path.join(tmp, "color_bc7.ktx2")
    with open(color_path, "wb") as stream:
        stream.write(color_source)
    M.set_slot_image(mat, "BASE_COLOR", M.load_image_file(color_path))
    color_data, color_doc, color_chunks = export()
    check(tex_blob(color_doc, color_chunks, "baseColorTexture")[0] == color_source,
          "BC7 sRGB source bytes are preserved in a color role")
    color_adm = os.path.join(tmp, "color_bc7.adm")
    with open(color_adm, "wb") as stream:
        stream.write(color_data)
    color_import = ModelImporter(bpy.context, color_adm, ImportOptions())
    color_import.run()
    color_data, color_report = ModelExporter(bpy.context, color_import.root, ExportOptions()).export()
    color_doc, color_chunks = read_container(color_data, K.ADM_MAGIC)
    check(color_report.ok and tex_blob(color_doc, color_chunks, "baseColorTexture")[0] == color_source,
          "BC7 sRGB survives ADM import and export")
    M.set_slot_image(mat, "BASE_COLOR", jpg_img)

    print("== default: preserve compatible GPU and PNG sources")
    data, doc, chunks = export()
    check(ExportOptions().image_format == "PRESERVE", "compatible GPU sources are preserved by default")
    check({im["mimeType"] for im in doc["images"]} == {"image/png"}, "only PNG images embedded")
    check(all("fallbackSource" not in t for t in doc["textures"]), "no fallbackSource for PNG")
    jpg_ref = u8(M.image_pixels(jpg_img))
    for key, want in (("baseColorTexture", jpg_ref), ("occlusionTexture", occ_px), ("emissiveTexture", emi_px)):
        got = blob_pixels(tex_blob(doc, chunks, key)[0], ".png")
        check(got.shape == want.shape and (got == want).all(), f"{key}: converted PNG has the source pixels")

    print("== Keep PNG/JPEG")
    _, doc, chunks = export(image_format="AUTO")
    blob, mime, _ = tex_blob(doc, chunks, "baseColorTexture")
    check(mime == "image/jpeg" and blob == open(jpg_path, "rb").read(), "JPEG source bytes kept unchanged")
    check(tex_blob(doc, chunks, "occlusionTexture")[1] == "image/png", "DDS source still converted to PNG")

    for fmt, mime, ext in (("KTX2", G.MIME_KTX2, ".ktx2"), ("DDS", G.MIME_DDS, ".dds")):
        for comp in ("RGBA8", "AUTO"):
            print(f"== {fmt} / {comp} + PNG fallback")
            data, doc, chunks = export(image_format=fmt, gpu_compression=comp)
            for key, srgb in (("baseColorTexture", True), ("normalTexture", False),
                              ("occlusionTexture", False), ("emissiveTexture", True)):
                blob, got_mime, t = tex_blob(doc, chunks, key)
                fb, fb_mime, _ = tex_blob(doc, chunks, key, "fallbackSource")
                info = G.parse(blob, got_mime, strict=True)
                fb_px = blob_pixels(fb, ".png")
                primary = G.decode(blob, got_mime, strict=True)[0]
                err = np.abs(primary.astype(int) - fb_px)
                # BC1 puts each 4x4 block on one colour line, so gradients in two channels have a
                # large per-pixel maximum; the mean bounds the block encoder quality.
                diff = err.max() if comp == "RGBA8" else err.mean()
                tol = 0 if comp == "RGBA8" else 12
                check(got_mime == mime and fb_mime == "image/png" and info["srgb"] == srgb
                      and len(info["levels"]) > 1 and diff <= tol,
                      f"{key}: {info['kind']} srgb={info['srgb']} levels={len(info['levels'])} "
                      f"primary~fallback {'max' if comp == 'RGBA8' else 'mean'} diff {diff:.2f}")
            if comp == "AUTO":
                kinds = {G.parse(*tex_blob(doc, chunks, k)[:2])["kind"] for k in ("normalTexture", "baseColorTexture")}
                check(kinds == {"BC1"}, f"AUTO picks BC1 for opaque textures ({kinds})")
            if fmt == "DDS" and comp == "RGBA8":
                blob = tex_blob(doc, chunks, "baseColorTexture")[0]
                check((blob_pixels(blob, ".dds") == G.decode(blob)[0]).all(),
                      "Blender reads the exported DDS primary")
            path = os.path.join(tmp, f"gpu_{fmt}_{comp}.adm")
            with open(path, "wb") as fh:
                fh.write(data)
            imp = ModelImporter(bpy.context, path, ImportOptions())
            imp.run()
            code = "KTX2_FALLBACK" if fmt == "KTX2" else "DDS_FALLBACK"
            check(any(w.startswith(code) for w in imp.warnings), f"import reports {code}")
            mat2 = imp.materials[0]
            img = M.slot_texture_node(mat2, "BASE_COLOR").image
            check((u8(M.image_pixels(img)) == jpg_ref).all(), "imported base colour = PNG fallback pixels")

    print("== mipmaps off")
    _, doc, chunks = export(image_format="DDS", gpu_mipmaps=False)
    info = G.parse(*tex_blob(doc, chunks, "baseColorTexture")[:2])
    check(len(info["levels"]) == 1, "single level without mipmaps")

    print("== R16 KTX2 precision across Blender save and reload")
    values = np.array([[1, 257], [12345, 65535]], dtype=np.uint16)
    path = os.path.join(tmp, "height_r16.ktx2")
    with open(path, "wb") as fh:
        fh.write(G.encode_scalar(values, G.MIME_KTX2, "R16", mipmaps=False)[0])
    image = M.load_image_file(path)
    image.use_fake_user = True
    expected = values.astype(np.float32) / 65535.0
    pixels = M.image_pixels(image)
    check(image.is_float and np.allclose(pixels[..., 0], expected, atol=1e-6)
          and np.allclose(pixels[..., 1:3], 0) and np.allclose(pixels[..., 3], 1),
          "R16 KTX2 loads with full scalar precision and missing channels")
    dds_r16_path = os.path.join(tmp, "height_r16.dds")
    with open(dds_r16_path, "wb") as fh:
        fh.write(G.encode_scalar(values, G.MIME_DDS, "R16", mipmaps=False)[0])
    dds_r16 = M.load_image_file(dds_r16_path)
    check(np.allclose(M.image_pixels(dds_r16)[..., 0], expected, atol=1e-6),
          "R16 DDS loads with full scalar precision")
    image_name = image.name
    blend_path = os.path.join(tmp, "r16.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    check(np.array_equal(u8(M.image_pixels(bpy.data.images[bc7_name])), bc7_expected),
          "decoded BC7 KTX2 pixels survive Blender save and reload")
    pixels = M.image_pixels(bpy.data.images[image_name])
    check(np.allclose(pixels[..., 0], expected, atol=1e-6),
          "packed R16 image retains scalar precision after project reload")
    image = bpy.data.images[image_name]
    exporter = M.MaterialExporter(None, lambda warning: None)
    blob, mime = exporter._encode_image_bytes(image, False)
    png_path = os.path.join(tmp, "r16_fallback.png")
    with open(png_path, "wb") as fh:
        fh.write(blob)
    fallback = bpy.data.images.load(png_path, check_existing=False)
    fallback.colorspace_settings.name = "Non-Color"
    pixels = M.image_pixels(fallback)
    check(mime == "image/png" and blob[24] == 16 and np.allclose(pixels[..., 0], expected, atol=1e-6)
          and np.allclose(pixels[..., 1:3], 0) and np.allclose(pixels[..., 3], 1),
          "PNG export preserves 16-bit scalar values and missing channels")
    root = bpy.data.objects["Box"]
    mat = bpy.data.materials["Formats"]
    M.set_slot_image(mat, "OCCLUSION", image)
    _, saved_doc, saved_chunks = export()
    with open(path, "rb") as stream:
        saved_original = stream.read()
    check(tex_blob(saved_doc, saved_chunks, "occlusionTexture")[0] == saved_original,
          "authored R16 source bytes survive Blender project save and reload")
    data, doc, chunks = export(image_format="PNG")
    blob = tex_blob(doc, chunks, "occlusionTexture")[0]
    check(blob[24] == 16, "ADM contains the 16-bit PNG")
    path = os.path.join(tmp, "r16.adm")
    with open(path, "wb") as fh:
        fh.write(data)
    imp = ModelImporter(bpy.context, path, ImportOptions())
    imp.run()
    imported = M.slot_texture_node(imp.materials[0], "OCCLUSION").image
    check(np.allclose(M.image_pixels(imported)[..., 0], expected, atol=1e-6),
          "ADM round-trip retains R16 source values")
    imported.pixels.foreach_set(np.asarray(imported.pixels[:], dtype=np.float32))
    blob, _ = exporter._encode_image_bytes(imported, False)
    check(blob[24] == 16, "edited imported 16-bit PNG retains its precision on export")
    for fmt in ("KTX2", "DDS"):
        gpu_data, gpu_doc, gpu_chunks = export(image_format=fmt, gpu_compression="AUTO")
        primary, gpu_mime, _ = tex_blob(gpu_doc, gpu_chunks, "occlusionTexture")
        info = G.parse(primary, gpu_mime, strict=True)
        fb, _, _ = tex_blob(gpu_doc, gpu_chunks, "occlusionTexture", "fallbackSource")
        check(info["kind"] == "R16" and np.array_equal(G.decode_scalar_level(primary, info), values)
              and len(info["levels"]) == 2
              and int(G.decode_scalar_level(primary, info, 1)[0, 0]) == 19535
              and fb[24] == 16, f"{fmt} AUTO preserves R16 primary, mip and 16-bit fallback")
        gpu_path = os.path.join(tmp, f"r16_{fmt}.adm")
        with open(gpu_path, "wb") as fh:
            fh.write(gpu_data)
        gpu_import = ModelImporter(bpy.context, gpu_path, ImportOptions())
        gpu_import.run()
        gpu_image = M.slot_texture_node(gpu_import.materials[0], "OCCLUSION").image
        check(np.allclose(M.image_pixels(gpu_image)[..., 0], expected, atol=1e-6),
              f"{fmt} ADM round-trip retains R16 values through fallback")
        M.set_slot_image(mat, "OCCLUSION", gpu_image)
        preserved_exporter = ModelExporter(bpy.context, root, ExportOptions())
        preserved_data, preserved_report = preserved_exporter.export()
        preserved_doc, preserved_chunks = read_container(preserved_data, K.ADM_MAGIC)
        preserved, preserved_mime, _ = tex_blob(preserved_doc, preserved_chunks, "occlusionTexture")
        check(preserved == primary and preserved_mime == gpu_mime,
              f"{fmt} import and default export preserve the original R16 mip chain byte-for-byte "
              f"(mime={preserved_mime}, warnings={preserved_exporter.warnings})")
        _, second_doc, second_chunks = export(image_format=fmt, gpu_compression="AUTO")
        second, second_mime, _ = tex_blob(second_doc, second_chunks, "occlusionTexture")
        second_info = G.parse(second, second_mime, strict=True)
        check(second_info["kind"] == "R16"
              and np.array_equal(G.decode_scalar_level(second, second_info), values),
              f"{fmt} re-export of imported fallback retains R16 values")
        M.set_slot_image(mat, "OCCLUSION", image)
        gpu_image.pixels.foreach_set(np.zeros(len(gpu_image.pixels), dtype=np.float32))
        gpu_image.update()
        gpu_image.pack()
        M.set_slot_image(mat, "OCCLUSION", gpu_image)
        edited_exporter = ModelExporter(bpy.context, root, ExportOptions())
        edited_data, edited_report = edited_exporter.export()
        edited_doc, edited_chunks = read_container(edited_data, K.ADM_MAGIC)
        _, edited_mime, _ = tex_blob(edited_doc, edited_chunks, "occlusionTexture")
        check(edited_report.ok and edited_mime == "image/png"
              and any("edited pixels" in warning for warning in edited_exporter.warnings),
              f"{fmt} edited and repacked image does not reuse stale GPU bytes")
        M.set_slot_image(mat, "OCCLUSION", image)
    gpu_exporter = ModelExporter(bpy.context, root, ExportOptions(image_format="KTX2", gpu_compression="RGBA8"))
    gpu_data, report = gpu_exporter.export()
    gpu_doc, gpu_chunks = read_container(gpu_data, K.ADM_MAGIC)
    fb, _, _ = tex_blob(gpu_doc, gpu_chunks, "occlusionTexture", "fallbackSource")
    check(report.ok and fb[24] == 16
          and any("converts 16-bit samples to 8-bit" in warning for warning in gpu_exporter.warnings),
          "explicit 8-bit GPU conversion reports precision loss and retains a 16-bit fallback")
    edited = M.image_pixels(image).copy()
    edited[..., 1] = 0.25
    image.pixels.foreach_set(edited[::-1].ravel())
    gpu_exporter = ModelExporter(bpy.context, root, ExportOptions(image_format="KTX2"))
    gpu_data, report = gpu_exporter.export()
    gpu_doc, gpu_chunks = read_container(gpu_data, K.ADM_MAGIC)
    primary, gpu_mime, _ = tex_blob(gpu_doc, gpu_chunks, "occlusionTexture")
    fb, _, _ = tex_blob(gpu_doc, gpu_chunks, "occlusionTexture", "fallbackSource")
    edited_path = os.path.join(tmp, "edited_fallback.png")
    with open(edited_path, "wb") as fh:
        fh.write(fb)
    edited_fallback = bpy.data.images.load(edited_path, check_existing=False)
    edited_fallback.colorspace_settings.name = "Non-Color"
    check(report.ok and G.parse(primary, gpu_mime)["kind"] != "R16" and fb[24] == 16
          and np.allclose(M.image_pixels(edited_fallback)[..., 1], 0.25, atol=1e-5)
          and any("converts 16-bit samples to 8-bit" in warning for warning in gpu_exporter.warnings),
          "edited non-scalar channels are not discarded by R16 conversion")
    adm_blender.unregister()


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="adm_texfmt_") as tmp:
            main(tmp)
    except Exception:
        traceback.print_exc()
        FAILS.append("exception")
    print("RESULT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.stdout.flush()
    os._exit(0 if not FAILS else 1)
