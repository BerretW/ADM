"""Verify BC5 normal reconstruction through Blender import, save, and ADM round-trip."""

import os
import sys
import tempfile
import hashlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import numpy as np

import adm_blender
from adm_blender.blender import materials as M
from adm_blender.blender.export_adm import ExportOptions, ModelExporter
from adm_blender.blender.import_adm import ImportOptions, ModelImporter
from adm_blender.core import constants as K, gputex
from adm_blender.core.buffers import read_view
from adm_blender.core.container import ChunkCollection, read_container, write_container
from adm_blender.core.png import encode_png
from adm_blender.core.validate import validate_adm


def main():
    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    mat = bpy.data.materials.new("BC5 normal test")
    mat.use_nodes = True
    obj.data.materials.append(mat)
    image = bpy.data.images.new("Normal source", 4, 4, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(np.tile(np.array((0.7, 0.35, 0.95, 1.0), dtype=np.float32), 16))
    image.update()
    image.pack()
    M.set_slot_image(mat, "NORMAL", image)
    M.convert_to_adm_material(mat)
    mat.adm.shader = "TWO_LAYER"
    mat.adm.shader_version = K.SHADER_PROFILE_LAYERED_HEIGHT_V1
    mat.adm.params["layer0_normal"].image = image
    mat.adm.params["layer0_ao_texture"].image = image
    bpy.ops.adm.create_model_root(name="BC5 root")
    root = bpy.data.objects["BC5 root"]
    pixels = np.full((4, 4, 4), [180, 95, 235, 255], dtype=np.uint8)
    fixtures = {}
    for fmt in ("DDS", "KTX2"):
        data, report = ModelExporter(
            bpy.context, root, ExportOptions(image_format=fmt, gpu_compression="RGBA8")).export()
        assert report.ok, report.errors
        fixtures[fmt] = data

    with tempfile.TemporaryDirectory(prefix="adm_bc5_normal_") as tmp:
        print("PHASE: open GPU shader texture parameters", flush=True)
        bpy.context.view_layer.objects.active = obj
        for mime, extension in ((gputex.MIME_DDS, "dds"), (gputex.MIME_KTX2, "ktx2")):
            path = os.path.join(tmp, "operator." + extension)
            blob, _ = gputex.encode(pixels, mime, "BC5", mipmaps=True)
            with open(path, "wb") as stream:
                stream.write(blob)
            assert bpy.ops.adm.material_shader_texture_open(name="layer0_normal", filepath=path) == {"FINISHED"}
            assert np.min(M.image_pixels(mat.adm.params["layer0_normal"].image)[..., 2]) > 0.9
            assert bpy.ops.adm.material_shader_texture_open(name="layer0_ao_texture", filepath=path) == {"FINISHED"}
            assert np.max(M.image_pixels(mat.adm.params["layer0_ao_texture"].image)[..., 2]) < 0.01
            assert bpy.ops.adm.material_texture_open(slot="NORMAL", filepath=path) == {"FINISHED"}
            normal_node = M.slot_texture_node(mat, "NORMAL")
            normal_node.extension = "EXTEND"
            assert np.min(M.image_pixels(normal_node.image)[..., 2]) > 0.9
            print(f"PHASE {extension}: export directly opened BC5 normals", flush=True)
            exporter = ModelExporter(bpy.context, root, ExportOptions())
            exported, report = exporter.export()
            assert report.ok, report.errors
            assert not any("core PBR normal uses BC5" in warning for warning in exporter.warnings)
            direct_doc, direct_chunks = read_container(exported, K.ADM_MAGIC)
            direct_mat = direct_doc["materials"][0]
            core_texture = direct_doc["textures"][direct_mat["normalTexture"]["index"]]
            assert direct_doc["samplers"][core_texture["sampler"]]["wrapS"] == "CLAMP_TO_EDGE"
            core_source = direct_doc["images"][core_texture["source"]]
            assert core_source["mimeType"] == "image/png"
            core_path = os.path.join(tmp, "direct_pbr_normal.png")
            with open(core_path, "wb") as stream:
                stream.write(read_view(direct_doc, direct_chunks, core_source["bufferView"]))
            core_image = bpy.data.images.load(core_path, check_existing=False)
            try:
                expected = gputex.reconstruct_bc5_normal(gputex.decode(blob, mime, strict=True)[0] / 255.0)
                np.testing.assert_allclose(M.image_pixels(core_image), expected, atol=1 / 255)
            finally:
                bpy.data.images.remove(core_image)
            for ref in (direct_mat["shaderParameters"]["layer0_normal"],):
                texture = direct_doc["textures"][ref["index"]]
                source = direct_doc["images"][texture["source"]]
                assert read_view(direct_doc, direct_chunks, source["bufferView"]) == blob
                fallback = direct_doc["images"][texture["fallbackSource"]]
                fallback_path = os.path.join(tmp, "direct_fallback.png")
                with open(fallback_path, "wb") as stream:
                    stream.write(read_view(direct_doc, direct_chunks, fallback["bufferView"]))
                fallback_image = bpy.data.images.load(fallback_path, check_existing=False)
                try:
                    actual = M.image_pixels(fallback_image)
                    np.testing.assert_allclose(actual, gputex.decode(blob, mime, strict=True)[0] / 255.0,
                                               atol=1 / 255)
                finally:
                    bpy.data.images.remove(fallback_image)
            print(f"PHASE {extension}: export split normal with external textures", flush=True)
            exporter = ModelExporter(bpy.context, root, ExportOptions(embed_textures=False))
            external, report = exporter.export()
            assert report.ok, report.errors
            external_doc, _ = read_container(external, K.ADM_MAGIC)
            external_mat = external_doc["materials"][0]
            pbr_tex = external_doc["textures"][external_mat["normalTexture"]["index"]]
            layer_tex = external_doc["textures"][external_mat["shaderParameters"]["layer0_normal"]["index"]]
            pbr_image = external_doc["images"][pbr_tex["source"]]
            layer_image = external_doc["images"][layer_tex["source"]]
            assert pbr_image["mimeType"] == "image/png"
            assert exporter.mat.external_files[layer_image["uri"]] == blob
            assert exporter.mat.external_files[pbr_image["uri"]].startswith(b"\x89PNG\r\n\x1a\n")
            print(f"PHASE {extension}: unreferenced core-only BC5 remains preserved", flush=True)
            for name in ("layer0_normal", "layer0_ao_texture"):
                mat.adm.params[name].use = False
            exporter = ModelExporter(bpy.context, root, ExportOptions())
            core_only, report = exporter.export()
            assert report.ok, report.errors
            assert any("core PBR normal uses BC5" in warning for warning in exporter.warnings)
            core_only_doc, core_only_chunks = read_container(core_only, K.ADM_MAGIC)
            core_ref = core_only_doc["materials"][0]["normalTexture"]
            primary = core_only_doc["images"][core_only_doc["textures"][core_ref["index"]]["source"]]
            assert read_view(core_only_doc, core_only_chunks, primary["bufferView"]) == blob
            for name in ("layer0_normal", "layer0_ao_texture"):
                mat.adm.params[name].use = True
            for kind in ("BC4", "BC5"):
                print(f"PHASE {extension}: export converted {kind} normals", flush=True)
                exporter = ModelExporter(
                    bpy.context, root, ExportOptions(image_format=extension.upper(), gpu_compression=kind))
                converted, report = exporter.export()
                assert report.ok, report.errors
                assert not any("core PBR normal uses BC5" in warning for warning in exporter.warnings)
                converted_doc, converted_chunks = read_container(converted, K.ADM_MAGIC)
                converted_mat = converted_doc["materials"][0]
                refs = [converted_mat["shaderParameters"]["layer0_normal"]]
                if kind == "BC4":
                    refs.append(converted_mat["normalTexture"])
                else:
                    core = converted_doc["textures"][converted_mat["normalTexture"]["index"]]
                    assert converted_doc["images"][core["source"]]["mimeType"] == "image/png"
                for ref in refs:
                    texture = converted_doc["textures"][ref["index"]]
                    source = converted_doc["images"][texture["source"]]
                    assert gputex.parse(read_view(converted_doc, converted_chunks, source["bufferView"]),
                                        mime, strict=True)["kind"] == kind
                    fallback = converted_doc["images"][texture["fallbackSource"]]
                    fallback_path = os.path.join(tmp, "converted_fallback.png")
                    with open(fallback_path, "wb") as stream:
                        stream.write(read_view(converted_doc, converted_chunks, fallback["bufferView"]))
                    fallback_image = bpy.data.images.load(fallback_path, check_existing=False)
                    try:
                        actual = M.image_pixels(fallback_image)
                        assert np.max(actual[..., 2]) == 0.0
                        assert kind != "BC4" or np.max(actual[..., 1]) == 0.0
                        assert np.min(actual[..., 3]) == 1.0
                    finally:
                        bpy.data.images.remove(fallback_image)
            if mime == gputex.MIME_DDS:
                with open(path, "ab") as stream:
                    stream.write(b"trailing metadata")
                trailing = M.load_image_file(path, normal_map=True)
                assert np.min(M.image_pixels(trailing)[..., 2]) > 0.9
        shader = bpy.context.scene.adm_anim.shaders.add()
        shader.shader_id, shader.version = "org.example.texture", "1.0.0"
        definition = shader.params.add()
        definition.name, definition.type = "detail_normal", "TEXTURE"
        custom = bpy.data.materials.new("Custom GPU texture")
        custom.adm.shader = "CUSTOM"
        custom.adm.custom_shader = shader.name
        obj.data.materials[0] = custom
        assert bpy.ops.adm.material_shader_texture_open(name="detail_normal", filepath=path) == {"FINISHED"}
        assert np.max(M.image_pixels(custom.adm.params["detail_normal"].image)[..., 2]) < 0.01
        original = custom.adm.params["detail_normal"].image
        try:
            bpy.ops.adm.material_shader_texture_open(name="detail_normal", filepath=os.path.join(tmp, "missing.ktx2"))
        except RuntimeError as exc:
            assert "missing.ktx2" in str(exc)
        else:
            raise AssertionError("Missing GPU texture was accepted")
        assert custom.adm.params["detail_normal"].image == original
        obj.data.materials[0] = mat
        old_limit = M.MAX_GPU_TEXTURE_PIXELS
        try:
            M.MAX_GPU_TEXTURE_PIXELS = 15
            try:
                M.load_image_file(path)
            except ValueError as exc:
                assert "pixel limit" in str(exc)
            else:
                raise AssertionError("Oversized GPU texture was accepted")
        finally:
            M.MAX_GPU_TEXTURE_PIXELS = old_limit
        old_limit = M.MAX_GPU_TEXTURE_BYTES
        try:
            M.MAX_GPU_TEXTURE_BYTES = len(blob) - 1
            try:
                M.load_image_file(path)
            except ValueError as exc:
                assert "MiB limit" in str(exc)
            else:
                raise AssertionError("Oversized GPU texture file was accepted")
        finally:
            M.MAX_GPU_TEXTURE_BYTES = old_limit
        for kind in ("R8", "BC4"):
            blob, _ = gputex.encode_scalar(np.full((4, 4), 130, dtype=np.uint8),
                                           gputex.MIME_DDS, kind, mipmaps=False)
            path = os.path.join(tmp, f"{kind}.dds")
            with open(path, "wb") as stream:
                stream.write(blob)
            loaded = M.load_image_file(path)
            np.testing.assert_allclose(M.image_pixels(loaded),
                                       gputex.decode(blob, strict=True)[0] / 255.0, atol=1 / 255)
        for fmt, mime in (("DDS", gputex.MIME_DDS), ("KTX2", gputex.MIME_KTX2)):
            print(f"PHASE {fmt}: create BC5 fixture", flush=True)
            doc, old_chunks = read_container(fixtures[fmt], K.ADM_MAGIC)
            chunks = ChunkCollection({cid: old_chunks[cid] for cid in old_chunks},
                                     chunk_types={cid: entry.chunk_type for cid, entry in old_chunks.entries.items()})
            blob, _ = gputex.encode(pixels, mime, "BC5", mipmaps=True)
            fallback = gputex.decode(blob, mime, strict=True)[0]
            png = encode_png(4, 4, fallback.tobytes())
            source_path = os.path.join(tmp, "source." + fmt.lower())
            with open(source_path, "wb") as stream:
                stream.write(blob)
            direct_normal = M.load_image_file(source_path, normal_map=True)
            direct_data = M.load_image_file(source_path)
            assert np.min(M.image_pixels(direct_normal)[..., 2]) > 0.9
            assert np.max(M.image_pixels(direct_data)[..., 2]) < 0.01
            params = doc["materials"][0]["shaderParameters"]
            indices = {doc["materials"][0]["normalTexture"]["index"],
                       params["layer0_normal"]["index"], params["layer0_ao_texture"]["index"]}
            external_path = None
            for index in indices:
                texture = doc["textures"][index]
                for image_index, content in ((texture["source"], blob), (texture["fallbackSource"], png)):
                    chunk_id = max(chunks) + 1
                    chunks.add(chunk_id, content, "IMAG")
                    doc["bufferViews"].append({"chunkId": chunk_id, "byteOffset": 0, "byteLength": len(content)})
                    doc["images"][image_index]["bufferView"] = len(doc["bufferViews"]) - 1
                if fmt == "KTX2":
                    external_path = os.path.join(tmp, "bc5.ktx2")
                    with open(external_path, "wb") as stream:
                        stream.write(blob)
                    source = doc["images"][texture["source"]]
                    source.pop("bufferView", None)
                    source["uri"] = "bc5.ktx2"
                    source["sha256"] = hashlib.sha256(blob).hexdigest()
            if external_path is not None:
                for field in ("extensionsUsed", "extensionsRequired"):
                    doc.setdefault(field, []).append(K.EXTERNAL_IMAGES_EXT)
            modified = write_container(K.ADM_MAGIC, doc, chunks)
            validation = validate_adm(modified)
            assert validation.ok, validation.errors
            path = os.path.join(tmp, f"bc5_{fmt}.adm")
            with open(path, "wb") as stream:
                stream.write(modified)
            print(f"PHASE {fmt}: import and inspect normal", flush=True)
            importer = ModelImporter(bpy.context, path, ImportOptions())
            importer.run()
            imported = importer.materials[0]
            normal = M.slot_texture_node(imported, "NORMAL").image
            layer = imported.adm.params["layer0_normal"].image
            data_image = imported.adm.params["layer0_ao_texture"].image
            assert normal is not None and layer is not None and data_image is not None
            expected_xy = fallback[..., :2].astype(float) / 127.5 - 1.0
            expected_z = np.sqrt(np.maximum(0, 1 - np.sum(expected_xy ** 2, axis=-1)))
            for normal_image in (normal, layer):
                actual = M.image_pixels(normal_image)
                np.testing.assert_allclose(actual[..., :2], fallback[..., :2] / 255.0, atol=1 / 255)
                np.testing.assert_allclose(actual[..., 2], expected_z * 0.5 + 0.5, atol=1 / 255)
            assert np.max(M.image_pixels(data_image)[..., 2]) < 0.01
            print(f"PHASE {fmt}: bake layered normal preview", flush=True)
            from adm_blender.tests.test_shader_preview import bake_socket

            bpy.context.scene.render.engine = "CYCLES"
            bpy.context.scene.cycles.samples = 1
            bpy.ops.mesh.primitive_plane_add()
            plane = bpy.context.object
            plane.data.materials.append(imported)
            normal_node = next(node for node in imported.node_tree.nodes
                               if node.type == "NORMAL_MAP" and node.name.endswith("Terrain Normal"))
            baked = bake_socket(plane, imported, normal_node.inputs["Color"].links[0].from_socket)[8, 8, :3]
            np.testing.assert_allclose(baked[:2], fallback[0, 0, :2] / 255.0, atol=0.025)
            np.testing.assert_allclose(baked[2], expected_z[0, 0] * 0.5 + 0.5, atol=0.025)
            if external_path is not None:
                with open(external_path, "wb") as stream:
                    stream.write(blob[:-1] + bytes([blob[-1] ^ 1]))
                corrupted = ModelImporter(bpy.context, path, ImportOptions())
                corrupted.run()
                assert any("GPU_NORMAL_SOURCE" in warning and "SHA-256 mismatch" in warning
                           for warning in corrupted.warnings)
                with open(external_path, "wb") as stream:
                    stream.write(blob)
            print(f"PHASE {fmt}: re-export and re-import", flush=True)
            encoded, report = ModelExporter(bpy.context, importer.root, ExportOptions()).export()
            assert report.ok, report.errors
            exported_doc, exported_chunks = read_container(encoded, K.ADM_MAGIC)
            parameters = exported_doc["materials"][0]["shaderParameters"]
            pbr = exported_doc["textures"][exported_doc["materials"][0]["normalTexture"]["index"]]
            assert exported_doc["images"][pbr["source"]]["mimeType"] == "image/png"
            refs = (parameters["layer0_normal"], parameters["layer0_ao_texture"])
            for ref in refs:
                tex = exported_doc["textures"][ref["index"]]
                source_image = exported_doc["images"][tex["source"]]
                assert source_image["mimeType"] == mime
                assert read_view(exported_doc, exported_chunks, source_image["bufferView"]) == blob
            roundtrip_path = os.path.join(tmp, f"roundtrip_{fmt}.adm")
            with open(roundtrip_path, "wb") as stream:
                stream.write(encoded)
            again = ModelImporter(bpy.context, roundtrip_path, ImportOptions())
            again.run()
            restored = again.materials[0].adm.params["layer0_normal"].image
            np.testing.assert_allclose(M.image_pixels(restored)[..., 2], expected_z * 0.5 + 0.5, atol=2 / 255)
            print(f"PHASE {fmt}: save and reload Blender project", flush=True)
            restored.use_fake_user = True
            name = restored.name
            root_name = again.root.name
            blend_path = os.path.join(tmp, f"roundtrip_{fmt}.blend")
            bpy.ops.wm.save_as_mainfile(filepath=blend_path)
            bpy.ops.wm.open_mainfile(filepath=blend_path)
            np.testing.assert_allclose(M.image_pixels(bpy.data.images[name])[..., 2],
                                       expected_z * 0.5 + 0.5, atol=2 / 255)
            saved_export, report = ModelExporter(bpy.context, bpy.data.objects[root_name], ExportOptions()).export()
            assert report.ok, report.errors
            saved_doc, saved_chunks = read_container(saved_export, K.ADM_MAGIC)
            ref = saved_doc["materials"][0]["shaderParameters"]["layer0_normal"]
            source = saved_doc["textures"][ref["index"]]["source"]
            assert read_view(saved_doc, saved_chunks, saved_doc["images"][source]["bufferView"]) == blob
    print("RESULT: PASS", flush=True)


if __name__ == "__main__":
    main()
