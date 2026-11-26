"""Render the generated advanced ADM fixture with the World Tile POM shader.

This is a fixture-specific visualization, not a general ADM renderer.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pyvista as pv
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "appartus_world_tile"))

from adm_blender.core import constants as K  # noqa: E402
from adm_blender.core.buffers import read_accessor_np, read_view  # noqa: E402
from adm_blender.core.container import read_container  # noqa: E402
from adm_blender.core.validate import validate_adm  # noqa: E402
from awt.bake import _linear_to_srgb  # noqa: E402
from awt.gui.material_panel import _mesh_with_tangents  # noqa: E402
from awt.gui.preview_shader import install_layered_preview  # noqa: E402
from awt.material import MapSlot, Surface, TerrainMaterial  # noqa: E402


def render_reference(path: Path, output: Path, *, disable_parallax: bool = False,
                     disable_pom: bool = False) -> None:
    """Render the generated fixture; reject layouts this visualization cannot represent."""
    with path.open("rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Reference ADM exceeds the 64 MiB fixture limit")
    report = validate_adm(data)
    if not report.ok:
        raise ValueError(report.format())
    doc, chunks = read_container(data, K.ADM_MAGIC)
    if len(doc.get("nodes", [])) != 8 or len(doc.get("materials", [])) != 8:
        raise ValueError("Expected the eight-material advanced reference fixture")

    plotter = pv.Plotter(off_screen=True, window_size=(960, 640))
    try:
        plotter.set_background("black")
        plotter.show(auto_close=False)
        units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()
        plotter.add_light(pv.Light(position=(-4, 8, 5), focal_point=(0, 0, 0), intensity=4))
        plotter.add_light(pv.Light(position=(4, 5, 6), focal_point=(0, 0, 0), intensity=3))
        with tempfile.TemporaryDirectory(prefix="adm_reference_render_") as tmp:
            def texture(ref):
                if ref is None:
                    return ""
                if ref.get("texCoord", 0) != 0:
                    raise ValueError("Reference visualization supports only UV set 0")
                tex = doc["textures"][ref["index"]]
                if "sampler" in tex:
                    raise ValueError("Reference visualization supports only the fixture's default samplers")
                index = tex.get("fallbackSource", tex["source"])
                image = doc["images"][index]
                if image["mimeType"] != "image/png" or "bufferView" not in image:
                    raise ValueError("Reference visualization needs embedded PNG fallbacks")
                out = os.path.join(tmp, f"{index}.png")
                if not os.path.exists(out):
                    with open(out, "wb") as stream:
                        stream.write(read_view(doc, chunks, image["bufferView"]))
                return out

            for node in doc["nodes"]:
                if set(node) - {"name", "mesh", "translation"}:
                    raise ValueError("Reference visualization supports translated mesh nodes only")
                primitives = doc["meshes"][node["mesh"]]["primitives"]
                if len(primitives) != 1:
                    raise ValueError("Reference visualization needs one primitive per mesh")
                primitive = primitives[0]
                material = doc["materials"][primitive["material"]]
                key = (material["shader"]["id"], material["shader"]["version"])
                if key not in K.SHADER_LAYERED_HEIGHT_COUNTS:
                    raise ValueError(f"Unsupported reference profile: {key}")
                params = material.get("shaderParameters", {})
                defaults = {p["name"]: p["default"] for p in K.OFFICIAL_SHADERS[key]}
                def value(name):
                    return params.get(name, defaults[name])

                attrs = primitive["attributes"]
                color0 = read_accessor_np(doc, chunks, attrs["COLOR_0"])
                if not np.allclose(color0, (0.0, 1.0, 1.0, 0.0), atol=1e-6):
                    raise ValueError("Reference visualization needs neutral COLOR_0 controls")
                extensions = material.get("extensions", {})
                if set(extensions) != {K.VERTEX_CONTROL_EXT}:
                    raise ValueError("Reference visualization needs the fixture's vertex control extension only")
                controls = extensions[K.VERTEX_CONTROL_EXT].get("parameters")
                if controls != {"tintOffset": 0.0, "normalMultiplier": 1.0,
                                "reflectionMultiplier": 1.0, "wetnessOffset": 0.0}:
                    raise ValueError("Reference visualization needs neutral vertex controls")
                count = K.SHADER_LAYERED_HEIGHT_COUNTS[key]
                allowed = {"blend_mask", "uv_scale", "height_blend_enabled", "height_blend_transition",
                           "height_blend_strength", "parallax_mode", "parallax_min_steps", "parallax_max_steps"}
                allowed.update(f"color1_{channel}_strength" for channel in "rgba")
                for i in range(count):
                    allowed.update(f"layer{i}_{suffix}" for suffix in (
                        "base_color", "texture", "normal", "metallic", "roughness", "ao_texture", "ao_channel",
                        "ao_invert", "ao_strength", "height_texture", "height_channel", "height_invert",
                        "height_scale", "height_bias", "parallax_scale"))
                if set(params) - allowed or material.get("alphaMode") != "OPAQUE":
                    raise ValueError("Reference visualization cannot represent these shader parameters")
                colors = read_accessor_np(doc, chunks, attrs["COLOR_1"])
                if not np.allclose(colors, (0.5, 0.5, 0.0, 0.0), atol=1e-6):
                    raise ValueError("Reference visualization needs the fixture's constant COLOR_1 weights")
                if any(abs(x - 1.0) > 1e-6 for x in value("uv_scale")):
                    raise ValueError("Reference visualization needs the fixture's unit UV scales")
                mask_path = texture(params.get("blend_mask"))
                if mask_path:
                    with Image.open(mask_path) as image:
                        if image.width * image.height > 1024 * 1024:
                            raise ValueError("Reference blend mask exceeds the fixture size limit")
                        mask = np.asarray(image.convert("RGBA"))
                    if not np.all(mask == mask[0, 0]) or not np.allclose(
                            mask[0, 0] / 255.0, (0.5, 0.5, 0.0, 0.0), atol=1 / 255):
                        raise ValueError("Reference visualization needs the fixture's constant blend mask")
                elif key[0] != "adm.pbr.layered":
                    raise ValueError("Reference visualization needs the fixture's blend mask")
                for channel in ("r", "g", "b", "a"):
                    name = f"color1_{channel}_strength"
                    if name in defaults and value(name) != 1.0:
                        raise ValueError("Reference visualization needs unit COLOR_1 strengths")

                points = read_accessor_np(doc, chunks, attrs["POSITION"]) + np.asarray(node["translation"])
                faces = read_accessor_np(doc, chunks, primitive["indices"]).reshape(-1, 3)
                mesh = pv.PolyData(points, np.column_stack((np.full(len(faces), 3), faces)).ravel())
                mesh.active_texture_coordinates = read_accessor_np(doc, chunks, attrs["TEXCOORD_0"])
                mesh.point_data["Normals"] = read_accessor_np(doc, chunks, attrs["NORMAL"])
                mesh = _mesh_with_tangents(mesh, pv)
                surfaces = []
                for i in range(count):
                    prefix = f"layer{i}_"
                    rgba = value(prefix + "base_color")
                    if rgba[3] != 1.0:
                        raise ValueError("Reference visualization supports opaque layers only")
                    color = np.rint(_linear_to_srgb(np.asarray(rgba[:3])) * 255).astype(int).tolist()
                    surfaces.append(Surface(
                        str(i), color=color, repeat_m=15.0,
                        albedo=texture(value(prefix + "texture")),
                        normal=texture(value(prefix + "normal")),
                        ao_map=MapSlot(texture(value(prefix + "ao_texture")),
                                       channel=int(value(prefix + "ao_channel")),
                                       invert=value(prefix + "ao_invert")),
                        ao_strength=value(prefix + "ao_strength"),
                        height_map=MapSlot(texture(value(prefix + "height_texture")),
                                           channel=int(value(prefix + "height_channel")),
                                           invert=value(prefix + "height_invert")),
                        height_scale=value(prefix + "height_scale"), height_bias=value(prefix + "height_bias"),
                        parallax_scale=0.0 if (disable_parallax or
                                               (disable_pom and value("parallax_mode") == "PARALLAX_OCCLUSION"))
                        else value(prefix + "parallax_scale"),
                        metallic=value(prefix + "metallic"), roughness=value(prefix + "roughness")))

                white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                white.SetUseSRGBColorSpace(True)
                orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                normal = pv.numpy_to_texture(np.full((2, 2, 3), (128, 128, 255), dtype=np.uint8))
                actor = plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1, render=False)
                actor.prop.SetTexture("albedoTex", white)
                actor.prop.SetORMTexture(orm)
                actor.prop.SetNormalTexture(normal)
                settings = TerrainMaterial(parallax_mode=value("parallax_mode"),
                                           parallax_min_steps=int(value("parallax_min_steps")),
                                           parallax_max_steps=int(value("parallax_max_steps")))
                install_layered_preview(
                    actor, pv, surfaces, [0.5, 0.5] + [0.0] * (count - 2), settings,
                    height_blend=value("height_blend_enabled"), transition=value("height_blend_transition"),
                    strength=value("height_blend_strength"), texture_units=units)
            plotter.camera_position = [(0, 5, 8), (0, 0.7, 0), (0, 1, 0)]
            plotter.camera.view_angle = 40
            plotter.show(auto_close=False)
            plotter.screenshot(str(output))
    finally:
        plotter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adm", type=Path, help="ADM generated by build_advanced_material_test_scene.py")
    parser.add_argument("output", type=Path, help="Output PNG")
    parser.add_argument("--disable-parallax", action="store_true", help="Render the comparison without UV offsets")
    parser.add_argument("--disable-pom", action="store_true", help="Disable POM while keeping single-step parallax")
    args = parser.parse_args()
    render_reference(args.adm, args.output, disable_parallax=args.disable_parallax, disable_pom=args.disable_pom)
