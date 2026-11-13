"""Blender test: export image formats (PNG default, Keep PNG/JPEG, KTX2/DDS + PNG fallback).

Run: blender -b --factory-startup --python adm_blender/tests/test_texture_formats.py
Checks real pixel values: source JPEG/DDS/KTX2 textures convert to PNG, GPU primaries carry the
right sRGB/UNORM variant and match their PNG fallback, Blender (OpenImageIO) reads the add-on's
DDS output identically to the add-on decoder, and import resolves the fallback.
"""
import os
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

    print("== default PNG: everything converted")
    data, doc, chunks = export()
    check(ExportOptions().image_format == "PNG", "PNG is the default")
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
