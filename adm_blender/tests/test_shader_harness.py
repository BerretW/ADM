"""Blender integration test for the interactive PBR 2.1.0 edge-wear scene."""

import os
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import bpy
import adm_blender


def main():
    adm_blender.register()
    bpy.ops.wm.read_homefile(use_empty=True)
    result = bpy.ops.adm.create_edge_wear_harness()
    assert result == {"FINISHED"}, f"harness operator failed: {result}"

    scene = next(item for item in bpy.data.scenes if "adm_pbr_edge_wear_harness" in item)
    assert scene.render.engine == "CYCLES"
    assert scene.cycles.samples == 16
    expected_objects = {
        "Wear | convex geometry",
        "Control | flat mask only",
        "Wear | normal-map transition",
        "Dirt | instance A",
        "Dirt | instance B",
    }
    assert expected_objects <= {obj.name for obj in scene.objects}

    materials = {material.name: material for material in bpy.data.materials}
    for name in (
        "ADM 2.1 Edge Wear",
        "ADM 2.1 Flat Control",
        "ADM 2.1 Normal-map Wear",
        "ADM 2.1 Per-instance Dirt",
    ):
        material = materials[name]
        assert material.adm.shader_key() == ("adm.pbr.metallic_roughness", "2.1.0")
        assert "color1_g_strength" not in {param.name for param in material.adm.params}
        assert "color1_b_strength" not in {param.name for param in material.adm.params}

    from adm_blender.blender.materials import slot_texture_node
    from adm_blender.blender.shader_preview import PREVIEW_WEAR_AMOUNT

    wear = scene.objects["Wear | convex geometry"]
    assert wear[PREVIEW_WEAR_AMOUNT] == 1.0
    assert slot_texture_node(wear.active_material, "BASE_COLOR") is not None
    assert wear.data.uv_layers.active is not None
    assert any(node.name == "ADM Preview Chipped Wear Pattern" for node in wear.active_material.node_tree.nodes)

    scene.render.resolution_percentage = 50
    scene.cycles.samples = 8
    scene.cycles.seed = 9196
    renders = []
    with tempfile.TemporaryDirectory() as directory:
        for amount in (0.0, 1.0):
            wear[PREVIEW_WEAR_AMOUNT] = amount
            wear.update_tag()
            scene.render.filepath = os.path.join(directory, f"wear_{amount}.png")
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(scene.render.filepath, check_existing=False)
            image.colorspace_settings.name = "Non-Color"
            renders.append(np.asarray(image.pixels[:], dtype=np.float32).reshape(300, 600, 4)[::-1, :, :3])
            bpy.data.images.remove(image)
    difference = np.abs(renders[1] - renders[0])
    face = difference[137:175, 30:72]
    edge = difference[112:125, 20:80]
    assert face.mean() < 0.01, f"wear changed the flat face: {face.mean()}"
    assert edge.mean() > 0.08, f"wear did not visibly change the textured edge: {edge.mean()}"
    wear[PREVIEW_WEAR_AMOUNT] = 0.4

    normal_material = materials["ADM 2.1 Normal-map Wear"]
    assert slot_texture_node(normal_material, "NORMAL") is not None
    dirt_material = materials["ADM 2.1 Per-instance Dirt"]
    for name in ("Dirt | instance A", "Dirt | instance B"):
        obj = scene.objects[name]
        attr = obj.data.color_attributes.get("COLOR_1")
        assert attr is not None
        assert all(tuple(item.color) == (0.0, 1.0, 0.0, 0.0) for item in attr.data)
        assert obj.active_material == dirt_material

    count = len(scene.objects)
    assert bpy.ops.adm.create_edge_wear_harness() == {"FINISHED"}
    assert len(scene.objects) == count
    assert abs(wear[PREVIEW_WEAR_AMOUNT] - 0.4) < 1e-6
    scene["adm_pbr_edge_wear_harness"] = "2.1.0"
    assert bpy.ops.adm.create_edge_wear_harness() == {"FINISHED"}
    assert len(scene.objects) == count
    assert len([item for item in bpy.data.scenes if "adm_pbr_edge_wear_harness" in item]) == 2
    assert abs(wear[PREVIEW_WEAR_AMOUNT] - 0.4) < 1e-6
    print("PASS interactive ADM PBR 2.1.0 edge-wear harness")


if __name__ == "__main__":
    main()
