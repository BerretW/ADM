import copy
import os
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import bpy
import adm_blender
from adm_blender.blender import import_adm
from adm_blender.core import constants as K
from adm_blender.core.container import write_container
from adm_blender.core.validate import validate_adm


def ids():
    return {
        name: {item.as_pointer() for item in getattr(bpy.data, name)}
        for name in ("objects", "collections", "meshes", "armatures", "materials",
                     "images", "actions", "node_groups", "shape_keys")
    }


def context_state():
    layer = bpy.context.view_layer
    return (bpy.context.scene, layer, layer.objects.active,
            frozenset(obj for obj in layer.objects if obj.select_get()),
            bpy.context.mode, frozenset(bpy.context.objects_in_mode))


def expect_failure(path, message, options=None):
    try:
        import_adm.ModelImporter(bpy.context, str(path), options).run()
    except Exception as exc:
        assert message in str(exc), str(exc)
        return exc
    raise AssertionError("import unexpectedly succeeded")


def main(directory):
    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    layer = bpy.context.view_layer

    objects = []
    for name in ("Existing A", "Existing B"):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        obj.select_set(True)
        objects.append(obj)
    layer.objects.active = objects[0]
    pose_data = bpy.data.armatures.new("Existing pose data")
    pose_obj = bpy.data.objects.new("Existing pose rig", pose_data)
    scene.collection.objects.link(pose_obj)
    for obj in objects:
        obj.select_set(False)
    pose_obj.select_set(True)
    layer.objects.active = pose_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bone = pose_data.edit_bones.new("Existing bone")
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    pose_obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    layer.objects.active = objects[0]
    orphan = bpy.data.materials.new("Unrelated orphan")
    orphan.diffuse_color = (0.2, 0.3, 0.4, 1)
    orphan_color = tuple(orphan.diffuse_color)

    image_path = directory / "shared.png"
    image = bpy.data.images.new("Existing image", width=1, height=1)
    image.filepath_raw = str(image_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(str(image_path), check_existing=False)
    image.name = "Existing image"
    image["sentinel"] = "untouched"
    image_state = (image.name, image.filepath_raw, image.colorspace_settings.name,
                   image.alpha_mode, dict(image.items()))
    shader = scene.adm_anim.shaders.add()
    shader.shader_id, shader.version = "org.example.existing", "1.0.0"
    shader.description = "Keep this definition"

    reference = validate_adm(
        (REPO / "adm-standard" / "fixtures" / "valid" / "triangle.adm").read_bytes())
    assert reference.ok
    doc = copy.deepcopy(reference.doc)
    doc["extensionsUsed"] = ["ADM_external_images_v1"]
    doc["extensionsRequired"] = ["ADM_external_images_v1"]
    doc["images"] = [{"name": "Imported image", "mimeType": "image/png", "uri": "shared.png"}]
    doc["textures"] = [{"source": 0}]
    doc["shaderDefinitions"] = [
        {"id": "org.example.existing", "version": "1.0.0",
         "description": "Must not replace existing", "parameters": []},
        {"id": "org.example.imported", "version": "1.0.0",
         "description": "New definition", "parameters": []},
    ]
    doc["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"] = len(doc["accessors"])
    doc["accessors"].append(
        {"bufferView": 0, "componentType": "F32", "type": "VEC2", "count": 3})
    doc["materials"] = [{"name": "Imported material",
                         "baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0,
                         "roughnessFactor": 1, "emissiveFactor": [0, 0, 0],
                         "alphaMode": "OPAQUE", "normalTexture": {"index": 0},
                         "shader": {"id": "org.example.imported", "version": "1.0.0"},
                         "shaderParameters": {}}]
    doc["meshes"][0]["primitives"][0]["material"] = 0
    data = write_container(K.ADM_MAGIC, doc, reference.bin)
    report = validate_adm(data)
    assert report.ok, [(issue.code, issue.message) for issue in report.errors]
    valid = directory / "valid.adm"
    valid.write_bytes(data)
    invalid = directory / "invalid.adm"
    invalid.write_bytes(b"not an ADM model")

    baseline = ids()
    shaders_before = [(item.name, item.description) for item in scene.adm_anim.shaders]

    def assert_preserved():
        assert ids() == baseline, "import leaked or removed datablocks"
        assert [(item.name, item.description) for item in scene.adm_anim.shaders] == shaders_before
        assert (image.name, image.filepath_raw, image.colorspace_settings.name,
                image.alpha_mode, dict(image.items())) == image_state
        assert tuple(orphan.diffuse_color) == orphan_color
        assert orphan.name == "Unrelated orphan"

    def fail_after_mutation(importer):
        assert importer.root.name in bpy.data.objects
        assert importer.materials
        assert importer.images[0] != image, "pre-existing image was reused"
        assert importer.images[0].filepath_raw == str(image_path)
        bpy.data.actions.new("Partial action")
        bpy.data.node_groups.new("Partial node group", "ShaderNodeTree")
        mesh = next(obj for obj in importer.collection.objects if obj.type == "MESH")
        mesh.shape_key_add(name="Basis")
        arm = bpy.data.armatures.new("Partial armature")
        obj = bpy.data.objects.new("Partial rig", arm)
        importer.collection.objects.link(obj)
        layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        arm.edit_bones.new("Partial bone")
        raise RuntimeError("injected post-mutation failure")

    for mode in ("OBJECT", "EDIT", "POSE", "NO_ACTIVE"):
        for obj in layer.objects:
            obj.select_set(False)
        if mode in ("OBJECT", "EDIT"):
            for obj in objects:
                obj.select_set(True)
            layer.objects.active = objects[0]
        elif mode == "POSE":
            pose_obj.select_set(True)
            layer.objects.active = pose_obj
        else:
            layer.objects.active = None
        if mode in ("EDIT", "POSE"):
            bpy.ops.object.mode_set(mode=mode)
        before = context_state()
        for collection in (True, False):
            with patch.object(import_adm.ModelImporter, "metadata", fail_after_mutation):
                failure = expect_failure(valid, "injected post-mutation failure",
                                         import_adm.ImportOptions(collection=collection))
                assert isinstance(failure, import_adm.ImportError_), (
                    "post-mutation failures must be normalized for the batch import operator")
            assert context_state() == before, f"{mode} context changed"
            assert_preserved()
        with patch.object(import_adm._ImportTransaction, "prepare") as prepare:
            expect_failure(invalid, "not a valid ADM")
            prepare.assert_not_called()
        assert context_state() == before
        assert_preserved()
        if mode in ("EDIT", "POSE"):
            bpy.ops.object.mode_set(mode="OBJECT")
    print("PASS: failures and invalid input preserve IDs, shaders, images, edit/pose/no-active contexts")

    restore = import_adm._ImportTransaction.restore_context

    def failed_restore(transaction):
        restore(transaction)
        raise RuntimeError("injected restoration failure")

    with patch.object(import_adm.ModelImporter, "metadata", fail_after_mutation), \
            patch.object(import_adm._ImportTransaction, "restore_context", failed_restore):
        exc = expect_failure(valid, "rollback failed")
        assert "injected restoration failure" in str(exc)
        assert "injected post-mutation failure" in str(exc.__cause__)
    assert_preserved()
    print("PASS: rollback failures are explicit and preserve the original cause")

    # Match the operator's per-file loop: one failed file must not contaminate the next.
    for obj in objects:
        obj.select_set(True)
    layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")
    before = context_state()
    original_metadata = import_adm.ModelImporter.metadata
    calls = 0

    def fail_first(importer):
        nonlocal calls
        calls += 1
        if calls == 1:
            fail_after_mutation(importer)
        return original_metadata(importer)

    with patch.object(import_adm.ModelImporter, "metadata", fail_first):
        expect_failure(valid, "injected post-mutation failure")
        assert_preserved()
        root = import_adm.ModelImporter(bpy.context, str(valid)).run()
    assert context_state() == before
    assert root.name in bpy.data.objects
    assert len(bpy.data.objects) == len(baseline["objects"]) + 2
    assert len(bpy.data.meshes) == len(baseline["meshes"]) + 1
    assert len(bpy.data.images) == len(baseline["images"]) + 1
    assert len(bpy.data.materials) == len(baseline["materials"]) + 1
    assert len(scene.adm_anim.shaders) == len(shaders_before) + 1
    assert scene.adm_anim.shaders[0].description == "Keep this definition"
    assert (image.name, image.filepath_raw, image.colorspace_settings.name,
            image.alpha_mode, dict(image.items())) == image_state
    assert len(bpy.data.armatures) == len(baseline["armatures"])
    assert len(bpy.data.actions) == len(baseline["actions"])
    assert len(bpy.data.node_groups) == len(baseline["node_groups"])
    assert len(bpy.data.shape_keys) == len(baseline["shape_keys"])
    assert len(bpy.data.collections) == len(baseline["collections"]) + 1
    print("PASS: failed file followed by valid file imports exactly one model and restores Edit Mode")


if __name__ == "__main__":
    exit_code = 0
    try:
        with tempfile.TemporaryDirectory(prefix=".adm_import_transaction_", dir=REPO) as directory:
            with patch.object(tempfile, "tempdir", directory):
                main(Path(directory))
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
