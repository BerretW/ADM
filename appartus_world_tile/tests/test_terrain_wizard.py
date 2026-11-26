import os
import math
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from awt.gui.main_window import MainWindow
    from awt.gui.height_blend_preview import compose_preview
    from awt.gui.height_blend_preview import HeightBlendPreview
    from awt.gui.height_blend_preview import _compose_pbr_maps, _read_rgba
    from awt.gui.material_panel import MaterialPanel, MaterialPreview
    from awt.gui.terrain_wizard import TerrainSetupWizard
except ImportError:
    QApplication = None
    TerrainSetupWizard = None
    MainWindow = None
    MaterialPanel = None
    compose_preview = None
    HeightBlendPreview = None
    _compose_pbr_maps = None

import numpy as np

from awt.material import Band, MapSlot, Surface, TerrainMaterial, normal_preview_array
from awt.heightmap import Heightmap
from awt.project import load_project


@unittest.skipIf(QApplication is None, "PySide6 is required for the terrain wizard test")
class TerrainWizardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_biome_noise_slider_updates_and_saves_project(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.material_panel.biome_list.setCurrentRow(0)
        editor = window.material_panel.biome_editor
        window._dirty = False
        window._field = object()
        editor.noise.setValue(65)
        self.assertEqual(window._material().biomes[0].noise, 0.65)
        self.assertEqual(editor.noise_value.text(), "65%")
        self.assertTrue(window._dirty)
        self.assertIsNone(window._field)
        window.material_panel.biome_list.setCurrentRow(1)
        self.assertEqual(editor.noise.value(), 0)
        window.material_panel.biome_list.setCurrentRow(0)
        self.assertEqual(editor.noise.value(), 65)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "world.awtp")
            self.assertTrue(window._write_project(path))
            loaded = load_project(path)
            self.assertEqual(loaded.to_dict()["format_version"], 4)
            self.assertEqual(loaded.material.biomes[0].noise, 0.65)
            window._open_project_file(path)
            window.material_panel.biome_list.setCurrentRow(0)
            self.assertEqual(window.material_panel.biome_editor.noise.value(), 65)

    def test_advanced_material_controls_update_surface_and_shader_settings(self):
        panel = MaterialPanel()
        self.addCleanup(panel.close)
        surface = panel.material().surface("grass")

        panel.surface_editor.ao.factor.setValue(0.65)
        panel.surface_editor.height.factor.setValue(0.4)
        panel.surface_editor.height_bias.setValue(-0.1)
        panel.surface_editor.parallax_scale.setValue(0.025)
        panel._surface_edited()

        panel.height_blend.setChecked(True)
        panel.height_blend_transition.setValue(0.15)
        panel.parallax_mode.setCurrentIndex(panel.parallax_mode.findData("PARALLAX_OCCLUSION"))
        panel.parallax_min_steps.setValue(12)
        panel.parallax_max_steps.setValue(48)

        self.assertAlmostEqual(surface.ao_strength, 0.65)
        self.assertAlmostEqual(surface.height_scale, 0.4)
        self.assertAlmostEqual(surface.height_bias, -0.1)
        self.assertAlmostEqual(surface.parallax_scale, 0.025)
        self.assertTrue(panel.material().height_blend_enabled)
        self.assertAlmostEqual(panel.material().height_blend_transition, 0.15)
        self.assertEqual(panel.material().parallax_mode, "PARALLAX_OCCLUSION")
        self.assertEqual(panel.material().parallax_min_steps, 12)
        self.assertEqual(panel.material().parallax_max_steps, 48)
        panel.terrain_shader_version.setCurrentIndex(
            panel.terrain_shader_version.findData("2.1.0"))
        self.assertEqual(panel.material().terrain_shader_version, "2.1.0")
        panel.material().validate()

    def test_surface_preview_parallax_and_pom_render_view_dependent_offsets(self):
        import pyvista as pv
        from PIL import Image
        from awt.adm_export import _core
        _core()
        from adm_blender.core.material_math import parallax_offset, parallax_occlusion

        with tempfile.TemporaryDirectory() as directory:
            albedo = os.path.join(directory, "gradient.png")
            height = os.path.join(directory, "height.png")
            gradient = np.broadcast_to(np.arange(256, dtype=np.uint8)[None, :, None], (32, 256, 3)).copy()
            Image.fromarray(gradient).save(albedo)
            Image.new("L", (32, 32), 51).save(height)
            surface = Surface("test", albedo=albedo, height_map=MapSlot(height),
                              repeat_m=15.0, parallax_scale=0.2)
            material = TerrainMaterial(parallax_mode="NONE")
            preview = MaterialPreview()
            self.addCleanup(preview.shutdown)
            preview.mode.setCurrentIndex(1)
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.enable_parallel_projection()

            def sample(mode, camera, lit=False):
                material.parallax_mode = mode
                preview.set_material(material)
                preview.set_surface(surface)
                plotter.clear()
                if lit:
                    plotter.add_light(pv.Light(position=(10, 0, 20), focal_point=(0, 0, 0)))
                plotter.add_actor(preview._actor, reset_camera=False)
                plotter.camera_position = [camera, (0, 0, 0), (0, 1, 0)]
                plotter.camera.parallel_scale = 10
                plotter.show(auto_close=False)
                return int(plotter.screenshot(return_img=True)[100, 100, 0])

            none = sample("NONE", (12, 0, 20))
            single = sample("PARALLAX", (12, 0, 20))
            pom = sample("PARALLAX_OCCLUSION", (12, 0, 20))
            single_offset = parallax_offset((0.5, 0.5), (12, 0, 20), 0.2, scale=0.2)
            pom_offset, _ = parallax_occlusion((0.5, 0.5), (12, 0, 20), lambda _: 0.2, scale=0.2)
            self.assertAlmostEqual(single - none, single_offset[0] * 255, delta=3)
            self.assertAlmostEqual(pom - none, pom_offset[0] * 255, delta=3)
            frontal = sample("PARALLAX_OCCLUSION", (0, 0, 20))
            frontal_none = sample("NONE", (0, 0, 20))
            self.assertAlmostEqual(frontal, frontal_none, delta=2)
            back_none = sample("NONE", (12, 0, -20))
            back_pom = sample("PARALLAX_OCCLUSION", (12, 0, -20))
            self.assertGreater(back_none, 10)
            self.assertAlmostEqual(back_none, back_pom, delta=2)
            surface.height_map.invert = True
            inverted = sample("PARALLAX_OCCLUSION", (12, 0, 20))
            self.assertGreater(inverted, pom + 5)

            normal = os.path.join(directory, "normal.png")
            orm = os.path.join(directory, "orm.png")
            emission = os.path.join(directory, "emission.png")
            Image.new("RGB", (32, 32), (128, 128, 255)).save(normal)
            Image.new("RGB", (32, 32), (255, 180, 90)).save(orm)
            Image.new("RGB", (32, 32), (20, 10, 5)).save(emission)
            surface.normal = normal
            surface.ao_map = MapSlot(orm, channel=0)
            surface.roughness_map = MapSlot(orm, channel=1)
            surface.metallic_map = MapSlot(orm, channel=2)
            surface.emission = emission
            surface.height_map.invert = False
            lit_none = sample("NONE", (12, 0, 20), lit=True)
            lit_pom = sample("PARALLAX_OCCLUSION", (12, 0, 20), lit=True)
            self.assertGreater(lit_none, 5)
            self.assertGreater(abs(lit_none - lit_pom), 3)

    def test_parallax_height_sampling_preserves_r16_and_missing_channels(self):
        from awt.gui.preview_shader import _height_samples
        from awt.adm_export import _core
        _core()
        from adm_blender.core import gputex
        from adm_blender.core.png import encode_png

        values = np.array([[1, 255], [1000, 65535]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            for mime, extension in ((gputex.MIME_DDS, "dds"), (gputex.MIME_KTX2, "ktx2")):
                path = os.path.join(directory, "height." + extension)
                data, _ = gputex.encode_scalar(values, mime, "R16", mipmaps=False)
                with open(path, "wb") as stream:
                    stream.write(data)
                np.testing.assert_allclose(_height_samples(MapSlot(path)), values / 65535.0, atol=1e-7)
                np.testing.assert_array_equal(_height_samples(MapSlot(path, channel=1)), 0.0)
                np.testing.assert_array_equal(_height_samples(MapSlot(path, channel=3)), 1.0)
            rgba = np.zeros((2, 2, 4), dtype=">u2")
            rgba[..., 0] = values
            rgba[..., 3] = 65535
            path = os.path.join(directory, "fallback.png")
            with open(path, "wb") as stream:
                stream.write(encode_png(2, 2, rgba.tobytes(), 4, bit_depth=16))
            np.testing.assert_allclose(_height_samples(MapSlot(path)), values / 65535.0, atol=1e-7)
            np.testing.assert_allclose(_height_samples(MapSlot(path, invert=True)),
                                       1.0 - values / 65535.0, atol=1e-7)

    def test_multi_surface_height_blend_retains_r16_precision(self):
        from awt.adm_export import _core
        _core()
        from adm_blender.core import gputex

        with tempfile.TemporaryDirectory() as directory:
            surfaces = []
            for value in (32768, 32769):
                path = os.path.join(directory, f"height{value}.dds")
                data, _ = gputex.encode_scalar(np.full((2, 2), value, dtype=np.uint16),
                                               gputex.MIME_DDS, "R16", mipmaps=False)
                with open(path, "wb") as stream:
                    stream.write(data)
                surfaces.append(Surface(str(value), repeat_m=15, height_map=MapSlot(path)))
            _, weights = compose_preview(surfaces, [1, 1], size=2, height_blend=True,
                                         transition=1.0 / 65535.0)
            self.assertAlmostEqual(float(weights[1, 0, 0]), 1.0 / (1.0 + math.exp(-1)), delta=0.001)

    def test_parallax_renders_all_surface_preview_shapes_with_lighting(self):
        import pyvista as pv
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            albedo = os.path.join(directory, "gradient.png")
            height = os.path.join(directory, "height.png")
            normal = os.path.join(directory, "normal.png")
            gradient = np.broadcast_to(np.arange(256, dtype=np.uint8)[None, :, None], (32, 256, 3)).copy()
            Image.fromarray(gradient).save(albedo)
            Image.new("L", (32, 32), 51).save(height)
            Image.new("RGB", (32, 32), (128, 128, 255)).save(normal)
            surface = Surface("test", albedo=albedo, normal=normal, height_map=MapSlot(height),
                              repeat_m=3.0, parallax_scale=0.15)
            material = TerrainMaterial()
            preview = MaterialPreview()
            self.addCleanup(preview.shutdown)
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.enable_parallel_projection()
            for shape in range(3):
                preview.mode.setCurrentIndex(shape)
                images = []
                for mode in ("NONE", "PARALLAX_OCCLUSION"):
                    material.parallax_mode = mode
                    preview.set_material(material)
                    preview.set_surface(surface)
                    plotter.clear()
                    plotter.add_light(pv.Light(position=(10, 0, 20), focal_point=(0, 0, 0)))
                    plotter.add_actor(preview._actor, reset_camera=False)
                    camera = (3, -5, 4) if shape == 0 else (12, 0, 20)
                    plotter.camera_position = [camera, (0, 0, 0), (0, 1, 0)]
                    plotter.camera.parallel_scale = 1.0 if shape == 0 else 10.0
                    plotter.show(auto_close=False)
                    images.append(plotter.screenshot(return_img=True))
                self.assertGreater(np.count_nonzero(images[1]), 1000, f"shape {shape} failed to render")
                self.assertGreater(np.count_nonzero(np.abs(images[1].astype(int) - images[0]) > 5),
                                   100, f"shape {shape} has no visible POM")

    def test_multi_surface_parallax_uses_independent_layer_offsets(self):
        import pyvista as pv
        from PIL import Image
        from awt.adm_export import _core
        from awt.bake import _linear_to_srgb, _srgb_to_linear
        _core()
        from adm_blender.core.material_math import height_blend_weights, parallax_offset, parallax_occlusion

        with tempfile.TemporaryDirectory() as directory:
            albedo = os.path.join(directory, "gradient.png")
            gradient = np.broadcast_to(np.arange(256, dtype=np.uint8)[None, :, None], (32, 256, 3)).copy()
            Image.fromarray(gradient).save(albedo)
            surfaces = []
            for index, (height, scale) in enumerate(((51, 0.2), (204, 0.1))):
                path = os.path.join(directory, f"height{index}.png")
                Image.new("L", (32, 32), height).save(path)
                surfaces.append(Surface(f"layer{index}", albedo=albedo, repeat_m=15.0,
                                        height_map=MapSlot(path), parallax_scale=scale))
            material = TerrainMaterial(surfaces=surfaces)
            preview = HeightBlendPreview(material)
            self.addCleanup(preview.close)
            preview.surface[1].setCurrentIndex(1)
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.enable_parallel_projection()

            def sample(mode, blend=False, lit=False):
                material.parallax_mode = mode
                preview.height_blend.setChecked(blend)
                preview._render()
                self.assertEqual(preview.error.text(), "")
                plotter.clear()
                if lit:
                    plotter.add_light(pv.Light(position=(10, 0, 20), focal_point=(0, 0, 0)))
                plotter.add_actor(preview._actor, reset_camera=False)
                plotter.camera_position = [(12, 0, 20), (0, 0, 0), (0, 1, 0)]
                plotter.camera.parallel_scale = 10
                plotter.show(auto_close=False)
                return int(plotter.screenshot(return_img=True)[100, 100, 0])

            baseline = sample("NONE")
            single = sample("PARALLAX")
            pom = sample("PARALLAX_OCCLUSION")
            view = (12, 0, 20)
            heights, scales = (0.2, 0.8), (0.2, 0.1)
            single_offsets = [parallax_offset((0.5, 0.5), view, h, scale=s)[0]
                              for h, s in zip(heights, scales)]
            pom_offsets = [parallax_occlusion((0.5, 0.5), view, lambda _, h=h: h, scale=s)[0][0]
                           for h, s in zip(heights, scales)]

            def expected(offsets, weights):
                samples = np.array([baseline / 255.0 + offset for offset in offsets])
                return float(_linear_to_srgb(np.dot(weights, _srgb_to_linear(samples))) * 255.0)

            self.assertAlmostEqual(single, expected(single_offsets, (0.5, 0.5)), delta=4)
            self.assertAlmostEqual(pom, expected(pom_offsets, (0.5, 0.5)), delta=4)
            blended = sample("PARALLAX_OCCLUSION", True)
            weights = height_blend_weights((0.5, 0.5), heights, transition=0.2)
            self.assertAlmostEqual(blended, expected(pom_offsets, weights), delta=4)
            for surface in surfaces:
                surface.albedo = ""
                surface.color = [0, 0, 0]
                surface.emission = albedo
            emission_none = sample("NONE", lit=True)
            emission_pom = sample("PARALLAX_OCCLUSION", lit=True)
            self.assertGreater(emission_none, 30)
            self.assertGreater(emission_none - emission_pom, 5)
            normal = os.path.join(directory, "normal.png")
            normal_pixels = np.zeros((32, 256, 3), dtype=np.uint8)
            normal_pixels[..., 0] = np.arange(256, dtype=np.uint8)
            normal_pixels[..., 1] = 128
            normal_pixels[..., 2] = 230
            Image.fromarray(normal_pixels).save(normal)
            for surface in surfaces:
                surface.color = [180, 180, 180]
                surface.emission = ""
                surface.normal = normal
            normal_none = sample("NONE", lit=True)
            normal_pom = sample("PARALLAX_OCCLUSION", lit=True)
            self.assertGreater(normal_none, 30)
            self.assertGreater(abs(normal_none - normal_pom), 2)

    def test_four_layer_pom_renders_and_reports_texture_exhaustion(self):
        import pyvista as pv
        from PIL import Image
        from awt.gui.preview_shader import install_layered_preview

        with tempfile.TemporaryDirectory() as directory:
            surfaces = []
            for i in range(4):
                paths = {}
                width, height = 64 + i * 8, 24 + i * 4
                gradient = np.broadcast_to(np.linspace(0, 255, width, dtype=np.uint8)[None, :, None],
                                           (height, width, 3)).copy()
                for name, pixels in (
                    ("albedo", gradient),
                    ("emission", gradient // 3),
                    ("normal", np.full((height, width, 3), (128, 128, 255), dtype=np.uint8)),
                    ("scalar", np.full((height, width, 3), (40 + 25 * i, 160, 80), dtype=np.uint8)),
                ):
                    paths[name] = os.path.join(directory, f"{i}-{name}.png")
                    Image.fromarray(pixels).save(paths[name])
                surfaces.append(Surface(
                    str(i), albedo=paths["albedo"], normal=paths["normal"], emission=paths["emission"],
                    height_map=MapSlot(paths["scalar"], channel=0, invert=bool(i % 2)),
                    ao_map=MapSlot(paths["scalar"], channel=1, invert=bool(i % 2)),
                    roughness_map=MapSlot(paths["scalar"], channel=1),
                    metallic_map=MapSlot(paths["scalar"], channel=2),
                    repeat_m=15.0 + i, parallax_scale=0.15, height_scale=0.8, height_bias=0.1))
            material = TerrainMaterial(parallax_mode="PARALLAX_OCCLUSION")
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.show(auto_close=False)
            units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()

            def actor_for(scale, budget):
                plotter.clear()
                plotter.add_light(pv.Light(position=(10, 0, 20), focal_point=(0, 0, 0)))
                mesh = pv.Plane(i_size=15, j_size=15)
                from awt.gui.material_panel import _mesh_with_tangents
                white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                white.SetUseSRGBColorSpace(True)
                orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                normal = pv.numpy_to_texture(np.full((2, 2, 3), (128, 128, 255), dtype=np.uint8))
                actor = plotter.add_mesh(_mesh_with_tangents(mesh, pv), texture=white, pbr=True,
                                         metallic=1.0, roughness=1.0, render=False)
                actor.prop.SetTexture("albedoTex", white)
                actor.prop.SetORMTexture(orm)
                actor.prop.SetNormalTexture(normal)
                actor.prop.SetEmissiveTexture(white)
                actor.prop.SetEmissiveFactor(1, 1, 1)
                for surface in surfaces:
                    surface.parallax_scale = scale
                install_layered_preview(actor, pv, surfaces, [1, 2, 3, 4], material,
                                        height_blend=True, transition=0.2, strength=1.0,
                                        texture_units=budget)
                plotter.camera_position = [(12, 0, 20), (0, 0, 0), (0, 1, 0)]
                plotter.show(auto_close=False)
                return plotter.screenshot(return_img=True)

            with self.assertRaisesRegex(ValueError, "texture units"):
                actor_for(0.15, 16)
            if units < 32:
                with self.assertRaisesRegex(ValueError, "texture units"):
                    actor_for(0.15, units)
                for surface in surfaces:
                    surface.ao_map.path = ""
                    surface.roughness_map.path = ""
                    surface.metallic_map.path = ""
                    surface.normal = ""
                    surface.emission = ""
            baseline = actor_for(0.0, units)
            pom = actor_for(0.15, units)
            self.assertGreater(np.count_nonzero(baseline), 1000)
            self.assertGreater(np.count_nonzero(np.abs(pom.astype(int) - baseline.astype(int)) > 5), 100)

    def test_pom_render_matches_across_permuted_mixed_lod_tile_edge(self):
        import pyvista as pv
        from PIL import Image
        from awt.gui.preview_shader import install_layered_preview

        with tempfile.TemporaryDirectory() as directory:
            surfaces = []
            for i, color in enumerate(((220, 100, 30), (40, 140, 230))):
                albedo = os.path.join(directory, f"albedo{i}.png")
                height = os.path.join(directory, f"height{i}.png")
                gradient = np.linspace(0.2, 1.0, 128)[None, :, None]
                pixels = np.broadcast_to(np.asarray(color)[None, None, :] * gradient,
                                         (32, 128, 3)).astype(np.uint8)
                Image.fromarray(pixels).save(albedo)
                Image.new("L", (32, 32), 60 + i * 120).save(height)
                surfaces.append(Surface(str(i), albedo=albedo, repeat_m=15.0 if i == 0 else 10.0,
                                        height_map=MapSlot(height), parallax_scale=0.3))
            material = TerrainMaterial(parallax_mode="PARALLAX_OCCLUSION")
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.enable_parallel_projection()
            plotter.show(auto_close=False)
            units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()

            def actor(center, width, resolution, reverse):
                mesh = pv.Plane(center=(center, 0, 0), i_size=width, j_size=15,
                                i_resolution=resolution, j_resolution=resolution)
                mesh.active_texture_coordinates = np.column_stack(
                    (mesh.points[:, 0] / 15 + 0.5, mesh.points[:, 1] / 15 + 0.5))
                white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                white.SetUseSRGBColorSpace(True)
                orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                obj = plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1,
                                       render=False)
                obj.prop.SetTexture("albedoTex", white)
                obj.prop.SetORMTexture(orm)
                layers = surfaces[::-1] if reverse else surfaces
                weights = [0.3, 0.7] if reverse else [0.7, 0.3]
                install_layered_preview(obj, pv, layers, weights, material,
                                        height_blend=True, transition=0.2, strength=1.0,
                                        texture_units=units)

            def render(split):
                plotter.clear()
                plotter.add_light(pv.Light(position=(10, 0, 20), focal_point=(0, 0, 0)))
                if split:
                    actor(-3.75, 7.5, 24, False)
                    actor(2.25, 4.5, 8, True)
                else:
                    actor(-1.5, 12, 24, False)
                plotter.camera_position = [(12, 0, 20), (0, 0, 0), (0, 1, 0)]
                plotter.camera.parallel_scale = 10
                plotter.show(auto_close=False)
                return plotter.screenshot(return_img=True).astype(int)

            reference = render(False)
            tiled = render(True)
            band = np.s_[60:140, 97:103, :]
            self.assertGreater(np.count_nonzero(reference[band]), 500)
            self.assertLessEqual(np.max(np.abs(reference[band] - tiled[band])), 3)
            for surface in surfaces:
                surface.parallax_scale = 0.0
            no_pom = render(False)
            delta = np.abs(reference[band] - no_pom[band])
            self.assertGreater(np.count_nonzero(delta > 3), 100, f"maximum POM difference: {delta.max()}")

    def test_layered_preview_interpolates_vertex_weights(self):
        import pyvista as pv
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper
        from awt.gui.preview_shader import install_layered_preview

        surfaces = [Surface("red", color=[255, 0, 0]), Surface("blue", color=[0, 0, 255])]
        settings = TerrainMaterial(parallax_mode="PARALLAX_OCCLUSION")
        plotter = pv.Plotter(off_screen=True, window_size=(128, 128))
        self.addCleanup(plotter.close)
        plotter.set_background("black")
        plotter.show(auto_close=False)
        units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()

        def render(reverse, constant=None):
            plotter.clear()
            plotter.add_light(pv.Light(position=(0, 0, 10), focal_point=(0, 0, 0)))
            mesh = pv.Plane(i_size=15, j_size=15, i_resolution=8, j_resolution=8)
            weight = np.clip(mesh.points[:, 0] / 15 + 0.5, 0, 1)
            if reverse:
                weight = 1 - weight
            mesh.point_data["layer_weights"] = np.column_stack(
                (weight, 1 - weight, np.zeros_like(weight), np.zeros_like(weight))).astype(np.float32)
            if constant is not None:
                mesh.point_data["layer_weights"][:] = constant
            white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
            white.SetUseSRGBColorSpace(True)
            orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
            actor = plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1, render=False)
            mapper = vtkPolyDataMapper()
            mapper.SetInputData(mesh)
            mapper.ScalarVisibilityOff()
            actor.SetMapper(mapper)
            actor.prop.SetTexture("albedoTex", white)
            actor.prop.SetORMTexture(orm)
            install_layered_preview(actor, pv, surfaces[::-1] if reverse else surfaces, [1, 1], settings,
                                    height_blend=False, transition=0.2, strength=1, texture_units=units,
                                    vertex_weights="layer_weights")
            plotter.view_xy()
            plotter.camera.parallel_projection = True
            plotter.camera.parallel_scale = 8
            plotter.show(auto_close=False)
            return plotter.screenshot(return_img=True).astype(int)

        image = render(False)
        permuted = render(True)
        red_delta = image[64, 96, 0] - image[64, 32, 0]
        blue_delta = image[64, 96, 2] - image[64, 32, 2]
        self.assertGreater(abs(red_delta), 30)
        self.assertGreater(abs(blue_delta), 30)
        self.assertLess(red_delta * blue_delta, 0)
        np.testing.assert_allclose(image, permuted, atol=2)
        np.testing.assert_allclose(render(False, [0, 0, 0, 0]), render(False, [1, 0, 0, 0]), atol=2)

    def test_exported_irregular_tiles_render_with_mixed_lods_and_permuted_layers(self):
        self._check_exported_irregular_tiles_render(curved=False, disjoint=False)

    def test_exported_curved_irregular_tiles_render_with_mixed_lods(self):
        self._check_exported_irregular_tiles_render(curved=True, disjoint=False)

    def test_exported_disjoint_biomes_render_with_mixed_lods(self):
        self._check_exported_irregular_tiles_render(curved=True, disjoint=True)

    def _check_exported_irregular_tiles_render(self, curved, disjoint):
        from dataclasses import replace
        import pyvista as pv
        from PIL import Image
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper
        from awt.adm_export import ExportSettings, export_tiles
        from awt.gui.preview_shader import install_layered_preview
        from awt.material import Biome, BiomeSurface
        from awt.pipeline import BuildParams, build, load_manifest
        from tests.test_export import _accessor, _read_adm

        with tempfile.TemporaryDirectory() as directory:
            heightmap = os.path.join(directory, "terrain.npy")
            y, x = np.mgrid[:49, :65]
            heights = 0.015 * x + 0.01 * y
            if curved:
                heights += 0.08 * np.sin(x / 9.0) * np.sin(y / 11.0)
            np.save(heightmap, heights.astype(np.float32))
            material = TerrainMaterial()
            high_surfaces = ("soil", "sand") if disjoint else ("rock", "grass")
            material.biomes = [
                Biome("noise", surfaces=[BiomeSurface("grass"), BiomeSurface("rock")], noise=0.8),
                Biome("high", surfaces=[BiomeSurface(name) for name in high_surfaces],
                      height=Band(0.88, None, 0.2), noise=0.4),
            ]
            material.terrain_shader_version = "2.1.0"
            material.height_blend_enabled = True
            material.parallax_mode = "PARALLAX_OCCLUSION"
            names_used = ("grass", "rock", "soil", "sand") if disjoint else ("grass", "rock")
            for index, name in enumerate(names_used):
                surface = material.surface(name)
                surface.color = [255, 255, 255]
                surface.repeat_m = (13.0, 17.0, 11.0, 19.0)[index]
                surface.parallax_scale = 0.12
                x = np.arange(64, dtype=np.float64)
                y = np.arange(32, dtype=np.float64)
                pattern = np.sin(x[None, :] * 2 * np.pi / 64) * np.sin(y[:, None] * 2 * np.pi / 32)
                stripe = (0.55 + 0.4 * pattern)[:, :, None]
                color = np.asarray(((210, 80, 35), (45, 130, 210),
                                    (110, 190, 60), (200, 180, 90))[index])[None, None, :]
                albedo = (stripe * color).astype(np.uint8)
                height = 127 + 100 * pattern
                surface.albedo = os.path.join(directory, name + "_albedo.png")
                surface.height_map.path = os.path.join(directory, name + "_height.png")
                Image.fromarray(albedo).save(surface.albedo)
                Image.fromarray(height.astype(np.uint8)).save(surface.height_map.path)
            params = BuildParams(input_path=heightmap, out_dir=os.path.join(directory, "build"),
                                 tile_cells=32, max_errors_m=[0.1, 1.0], spacing_m=2.0)
            build(params, material)
            manifest = load_manifest(params.out_dir)
            settings = ExportSettings(out_dir=os.path.join(directory, "adm"))
            export_tiles(manifest, material, settings, "all")
            tiles = sorted((tile for tile in manifest["tiles"]
                            if tile["size_m"][1] < manifest["tile_size_m"]), key=lambda x: x["ix"])
            self.assertEqual(len(tiles), 2)
            self.assertTrue(all(tile["size_m"][1] < manifest["tile_size_m"] for tile in tiles))
            geometry = []
            for index, tile in enumerate(tiles):
                doc, chunks = _read_adm(os.path.join(settings.out_dir, tile["id"] + ".adm"))
                lod = 0 if index == 0 else len(tile["lods"]) - 1
                for primitive in doc["meshes"][lod]["primitives"]:
                    attributes = {name: _accessor(doc, chunks, accessor)
                                  for name, accessor in primitive["attributes"].items()}
                    shader = doc["materials"][primitive["material"]]
                    names = shader["name"].split(" ", 3)[-1].split("+")
                    self.assertTrue(set(names).issubset(names_used))

                    def fallback(ref):
                        texture = doc["textures"][ref["index"]]
                        image = doc["images"][texture["fallbackSource"]]
                        return os.path.join(settings.out_dir, *image["uri"].split("/"))

                    shader_params = shader["shaderParameters"]
                    self.assertEqual(shader_params["parallax_mode"], "PARALLAX_OCCLUSION")
                    layers = []
                    for i, name in enumerate(names):
                        prefix = f"layer{i}_"
                        surface = material.surface(name)
                        layers.append(replace(
                            surface, repeat_m=15.0 / shader_params["uv_scale"][i],
                            albedo=fallback(shader_params[prefix + "texture"]),
                            height_map=replace(surface.height_map,
                                               path=fallback(shader_params[prefix + "height_texture"])),
                            parallax_scale=shader_params[prefix + "parallax_scale"]))
                    geometry.append((attributes, _accessor(doc, chunks, primitive["indices"]).reshape(-1, 3),
                                     doc["nodes"][0]["translation"], layers, shader_params))
            self.assertGreater(len(geometry), 1)
            self.assertGreater(np.ptp(np.concatenate([g[0]["POSITION"][:, 1] for g in geometry])), 0.5)
            all_weights = np.concatenate([g[0]["COLOR_1"][:, 0] for g in geometry])
            self.assertGreater(np.ptp(all_weights), 0.05)
            edge_weights = np.concatenate([
                attrs["COLOR_1"][np.isclose(attrs["POSITION"][:, 0] + translation[0],
                                            manifest["tile_size_m"]), 0]
                for attrs, _, translation, _, _ in geometry])
            edge_heights = np.concatenate([
                attrs["POSITION"][np.isclose(attrs["POSITION"][:, 0] + translation[0],
                                              manifest["tile_size_m"]), 1] + translation[1]
                for attrs, _, translation, _, _ in geometry])
            self.assertGreater(len(edge_weights), 2)
            self.assertGreater(np.ptp(edge_weights), 0.02)
            self.assertLess(edge_heights.min(), 0.88)
            self.assertGreater(edge_heights.max(), 0.88)

            plotter = pv.Plotter(off_screen=True, window_size=(320, 240))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.show(auto_close=False)
            units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()

            def render(reverse_right=False, pom=True):
                plotter.clear()
                plotter.add_light(pv.Light(position=(64, 120, -48), focal_point=(64, 0, -48)))
                for attributes, faces, translation, exported_layers, shader_params in geometry:
                    vertices = attributes["POSITION"] + np.asarray(translation)
                    mesh = pv.PolyData(vertices, np.column_stack((np.full(len(faces), 3), faces)).ravel())
                    mesh.active_texture_coordinates = attributes["TEXCOORD_0"]
                    mesh.point_data["Normals"] = attributes["NORMAL"]
                    weights = attributes["COLOR_1"].astype(np.float32).copy()
                    layers = [replace(surface, parallax_scale=surface.parallax_scale if pom else 0.0)
                              for surface in exported_layers]
                    if reverse_right and translation[0] > manifest["tile_size_m"]:
                        layers.reverse()
                        weights[:, :len(layers)] = weights[:, :len(layers)][:, ::-1]
                    mesh.point_data["layer_weights"] = weights
                    white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                    white.SetUseSRGBColorSpace(True)
                    orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                    actor = plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1, render=False)
                    mapper = vtkPolyDataMapper()
                    mapper.SetInputData(mesh)
                    mapper.ScalarVisibilityOff()
                    actor.SetMapper(mapper)
                    actor.prop.SetTexture("albedoTex", white)
                    actor.prop.SetORMTexture(orm)
                    install_layered_preview(actor, pv, layers, [1] * len(layers), material,
                                            height_blend=shader_params["height_blend_enabled"],
                                            transition=shader_params["height_blend_transition"],
                                            strength=shader_params["height_blend_strength"], texture_units=units,
                                            vertex_weights="layer_weights")
                plotter.camera_position = [(64, 100, -130), (64, 0, -48), (0, 1, 0)]
                plotter.camera.view_angle = 45
                plotter.show(auto_close=False)
                return plotter.screenshot(return_img=True).astype(int)

            image = render()
            permuted = render(reverse_right=True)
            unshifted = render(pom=False)
            valid = np.any(image[:, 158] != 0, axis=1) & np.any(image[:, 161] != 0, axis=1)
            jumps = np.abs(image[valid, 159] - image[valid, 160])
            self.assertGreater(len(jumps), 30)
            self.assertTrue(np.all(np.any(image[valid, 159] != 0, axis=1)))
            self.assertTrue(np.all(np.any(image[valid, 160] != 0, axis=1)))
            self.assertLessEqual(jumps.max(), 18)
            self.assertGreater(np.count_nonzero(image), 10000)
            np.testing.assert_allclose(image, permuted, atol=3)
            self.assertGreater(np.count_nonzero(np.abs(image[valid, 155:165] - unshifted[valid, 155:165]) > 5), 20)

    def test_over_four_surface_conflict_is_visible_in_pom_shader(self):
        from dataclasses import replace
        import pyvista as pv
        from PIL import Image
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper
        from awt.adm_export import color1, triangle_masks
        from awt.gui.preview_shader import install_layered_preview

        weights = np.array([[51, 51, 51, 51, 51], [51, 51, 51, 51, 51],
                            [255, 0, 0, 0, 0], [0, 60, 60, 60, 75]], dtype=np.uint8)
        faces = np.array([[2, 0, 1], [0, 3, 1]])
        masks, conflicts = triangle_masks(weights, faces)
        self.assertEqual(conflicts, 2)
        slots = [[i for i in range(5) if int(mask) & (1 << i)] for mask in masks]
        self.assertEqual(slots, [[0, 1, 2, 3], [1, 2, 3, 4]])
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "height.png")
            albedo = os.path.join(directory, "albedo.png")
            x = np.arange(64)
            gradient = np.broadcast_to((127 + 100 * np.sin(x * 2 * np.pi / 64))[None, :], (32, 64))
            Image.fromarray(gradient.astype(np.uint8)).save(path)
            albedo_values = 90 + gradient * 0.7
            Image.fromarray(np.repeat(albedo_values[:, :, None].astype(np.uint8), 3, axis=2)).save(albedo)
            colors = [[255, 0, 0], [80, 80, 80], [80, 80, 80], [80, 80, 80], [0, 0, 255]]
            surfaces = [Surface(str(i), color=color, albedo=albedo, height_map=MapSlot(path), parallax_scale=0.2)
                        for i, color in enumerate(colors)]
            settings = TerrainMaterial(parallax_mode="PARALLAX_OCCLUSION")
            plotter = pv.Plotter(off_screen=True, window_size=(160, 160))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.show(auto_close=False)
            units = plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()
            points = np.array([[0, -5, 0], [0, 5, 0], [-8, 0, 0], [8, 0, 0]], dtype=np.float32)

            def render(pom):
                plotter.clear()
                plotter.add_light(pv.Light(position=(0, 0, 10), focal_point=(0, 0, 0)))
                for face, chosen in zip(faces, slots):
                    mesh = pv.PolyData(points[face], np.array([3, 0, 1, 2]))
                    mesh.active_texture_coordinates = points[face, :2] / 15 + 0.5
                    mesh.point_data["layer_weights"] = color1(weights[face], chosen).astype(np.float32) / 255
                    white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                    white.SetUseSRGBColorSpace(True)
                    orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
                    actor = plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1, render=False)
                    mapper = vtkPolyDataMapper()
                    mapper.SetInputData(mesh)
                    mapper.ScalarVisibilityOff()
                    actor.SetMapper(mapper)
                    actor.prop.SetTexture("albedoTex", white)
                    actor.prop.SetORMTexture(orm)
                    layers = [replace(surfaces[i], parallax_scale=0.2 if pom else 0.0) for i in chosen]
                    install_layered_preview(actor, pv, layers, [1, 1, 1, 1], settings,
                                            height_blend=True, transition=0.2, strength=1, texture_units=units,
                                            vertex_weights="layer_weights")
                plotter.camera_position = [(3, 0, 16), (0, 0, 0), (0, 1, 0)]
                plotter.camera.view_angle = 40
                plotter.show(auto_close=False)
                return plotter.screenshot(return_img=True).astype(int)

            image = render(True)
            unshifted = render(False)
            jump = np.abs(image[60:100, 79] - image[60:100, 80])
            self.assertGreater(np.median(np.max(jump, axis=1)), 10)
            self.assertGreater(np.count_nonzero(np.abs(image - unshifted) > 5), 100)

    def test_export_reports_surface_conflict_seam_risk(self):
        import argparse
        import contextlib
        import io
        from awt.cli import _export
        from awt.project import Project

        result = {"written": ["tile"], "skipped": 0, "bytes": 0, "seconds": 0.1, "out_dir": "output",
                  "conflicts": 2, "warnings": []}
        window = MainWindow()
        self.addCleanup(window.close)
        with patch.object(window, "_check_changes"):
            window._export_done(result)
        self.assertIn("visible seams may result", window.report.toPlainText())

        args = argparse.Namespace(project="project.awtp", out="", no_validate=False,
                                  build=False, all=True, tiles=None)
        output = io.StringIO()
        with patch("awt.project.load_project", return_value=Project.new()), \
                patch("awt.pipeline.load_manifest", return_value={}), \
                patch("awt.adm_export.export_tiles", return_value=result), \
                contextlib.redirect_stdout(output):
            self.assertEqual(_export(args), 0)
        self.assertIn("warning: 2 triangles", output.getvalue())
        self.assertIn("visible seams may result", output.getvalue())

    def test_generated_reference_adm_renders_pom(self):
        import shutil
        import subprocess
        import sys
        from pathlib import Path
        import pyvista as pv
        from PIL import Image

        root = Path(__file__).resolve().parents[2]
        blender = os.environ.get("BLENDER_EXECUTABLE") or shutil.which("blender")
        if not blender and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / (
                r"Blender Foundation\Blender 5.2\blender.exe")
            blender = str(candidate) if candidate.is_file() else None
        if not blender:
            self.skipTest("Blender is required to generate the reference ADM fixture")
        probe = pv.Plotter(off_screen=True)
        try:
            probe.show(auto_close=False)
            units = probe.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()
        finally:
            probe.close()
        if units < 17:
            self.skipTest(f"Reference fixture requires 17 texture units; renderer reports {units}")

        def run(command, timeout):
            try:
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                self.fail(f"Reference process timed out after {timeout}s: {exc.cmd}")
            self.assertEqual(result.returncode, 0,
                             f"Reference process failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            run([blender, "-b", "--factory-startup", "--python-exit-code", "1",
                 "--python", str(root / "adm_blender" / "tests" / "build_advanced_material_test_scene.py"),
                 "--", str(path / "reference.blend")], 180)
            renderer = root / "appartus_world_tile" / "tools" / "render_advanced_reference.py"
            for name, options in (("pom.png", []), ("no-pom.png", ["--disable-pom"])):
                run([sys.executable, str(renderer), str(path / "reference.adm"), str(path / name), *options], 120)
            with Image.open(path / "pom.png") as image:
                pom = np.asarray(image).astype(int)
            with Image.open(path / "no-pom.png") as image:
                no_pom = np.asarray(image).astype(int)
            self.assertGreater(np.count_nonzero(pom), 10000)
            self.assertGreater(np.count_nonzero(np.abs(pom - no_pom) > 5), 500)
            from awt.adm_export import _core
            _core()
            from adm_blender.core.constants import ADM_MAGIC
            from adm_blender.core.container import read_container, write_container
            doc, chunks = read_container((path / "reference.adm").read_bytes(), ADM_MAGIC)
            doc["materials"][0]["shaderParameters"]["uv_scale"] = [2.0, 1.0, 1.0, 1.0]
            (path / "unsupported.adm").write_bytes(write_container(ADM_MAGIC, doc, chunks))
            rejected = subprocess.run([sys.executable, str(renderer), str(path / "unsupported.adm"),
                                       str(path / "unsupported.png")], cwd=root,
                                      capture_output=True, text=True, timeout=120)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unit UV scales", rejected.stderr)
            self.assertFalse((path / "unsupported.png").exists())

    def test_multi_surface_preview_uses_height_weights_and_preserves_zero_layers(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            low_path = os.path.join(directory, "low.png")
            high_path = os.path.join(directory, "high.png")
            Image.new("L", (8, 8), 20).save(low_path)
            Image.new("L", (8, 8), 230).save(high_path)
            low = Surface("soil", color=[120, 80, 40], repeat_m=15,
                          height_map=MapSlot(low_path))
            high = Surface("rock", color=[180, 180, 180], repeat_m=15,
                           height_map=MapSlot(high_path))

            classic_rgb, classic_weights = compose_preview([low, high], [50, 50], size=16)
            blended_rgb, blended_weights = compose_preview(
                [low, high], [50, 50], size=16, height_blend=True, transition=0.2, strength=1.0)
            self.assertGreater(float(blended_weights[1].mean()), float(classic_weights[1].mean()))
            self.assertGreater(float(blended_rgb[..., 0].mean()), float(classic_rgb[..., 0].mean()))
            np.testing.assert_allclose(blended_weights.sum(axis=0), 1.0)
            _, one_hot = compose_preview([low, high], [100, 0], size=16,
                                         height_blend=True, transition=0.01)
            self.assertTrue((one_hot[1] == 0).all())

    def test_sixteen_bit_height_preview_normalizes_values(self):
        from awt.adm_export import _core
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "height.png")
            values = np.array([[0, 32768, 65535]], dtype=np.uint16)
            Image.fromarray(values).save(path)
            for pixels in (_read_rgba(path), MaterialPreview._image_array(path)):
                np.testing.assert_array_equal(pixels[0, :, 0], [0, 128, 255])
            _core()
            from adm_blender.core import gputex
            for mime, extension in ((gputex.MIME_DDS, ".dds"), (gputex.MIME_KTX2, ".ktx2")):
                data, _ = gputex.encode_scalar(values, mime, "R16", mipmaps=False)
                path = os.path.join(directory, "height" + extension)
                with open(path, "wb") as handle:
                    handle.write(data)
                for pixels in (_read_rgba(path), MaterialPreview._image_array(path)):
                    np.testing.assert_allclose(pixels[0, :, 0], [0, 128, 255], atol=1)
                    self.assertTrue(np.all(pixels[..., 1:3] == 0))

    def test_bc5_normal_preview_reconstructs_positive_z(self):
        from awt.adm_export import _core, prepare_adm_texture
        from PIL import Image
        import io

        _core()
        from adm_blender.core import gputex

        pixels = np.full((4, 4, 4), [180, 95, 235, 255], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            for mime, extension in ((gputex.MIME_DDS, ".dds"), (gputex.MIME_KTX2, ".ktx2")):
                with self.subTest(mime=mime):
                    blob, _ = gputex.encode(pixels, mime, "BC5", mipmaps=False)
                    path = os.path.join(directory, "normal" + extension)
                    with open(path, "wb") as handle:
                        handle.write(blob)
                    with Image.open(io.BytesIO(prepare_adm_texture(path, "normal").fallback.data)) as image:
                        self.assertTrue(np.all(np.asarray(image)[..., 2] == 0))
                    preview = normal_preview_array(path)
                    xy = preview[..., :2].astype(float) / 127.5 - 1
                    z = preview[..., 2].astype(float) / 127.5 - 1
                    decoded = gputex.decode(blob, strict=True)[0]
                    np.testing.assert_allclose(preview[..., :2], decoded[..., :2], atol=1)
                    np.testing.assert_allclose(np.sum(xy * xy, axis=-1) + z * z, 1, atol=0.02)
                    self.assertTrue(np.all(z > 0.5))
                    surface = Surface("normal", normal=path, repeat_m=15)
                    _, blended, _ = _compose_pbr_maps([surface], np.ones((1, 4, 4)))
                    self.assertTrue(np.all(blended[..., 2] > 192))

    def test_multi_surface_preview_uses_weighted_ao_channel_inversion_and_strength(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ao.png")
            Image.new("RGBA", (4, 4), (0, 64, 255, 255)).save(path)
            occluded = Surface("occluded", color=[200, 200, 200], repeat_m=15,
                               ao_map=MapSlot(path, channel=1, invert=True), ao_strength=0.5)
            clear = Surface("clear", color=[200, 200, 200], repeat_m=15)
            rgb, weights = compose_preview([occluded, clear], [1, 1], size=4)
            from awt.bake import _linear_to_srgb, _srgb_to_linear

            expected = round(float(_linear_to_srgb(
                _srgb_to_linear(np.array(200 / 255)) * (1 - 0.5 * 0.5 * 64 / 255))) * 255)
            np.testing.assert_array_equal(rgb, np.full((4, 4, 3), expected, dtype=np.uint8))
            np.testing.assert_allclose(weights[:, 0, 0], (0.5, 0.5))
            rgb, _ = compose_preview([occluded, clear], [0, 1], size=4)
            self.assertTrue(np.all(rgb == 200))

    def test_multi_surface_preview_composes_material_maps(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for name, color in (("normal", (255, 128, 128)), ("emission", (255, 0, 0)),
                                ("packed", (0, 128, 64))):
                path = os.path.join(directory, name + ".png")
                Image.new("RGB", (4, 4), color).save(path)
                paths[name] = path
            mapped = Surface("mapped", repeat_m=15, normal=paths["normal"], emission=paths["emission"],
                             roughness=0.8, roughness_map=MapSlot(paths["packed"], channel=1, invert=True),
                             metallic=0.4, metallic_map=MapSlot(paths["packed"], channel=2))
            plain = Surface("plain", repeat_m=15, roughness=0.4, metallic=0.2)
            _, weights = compose_preview([mapped, plain], [1, 1], size=4)
            orm, normal, emission = _compose_pbr_maps([mapped, plain], weights)
            expected_roughness = round((0.5 * 0.8 * (1 - 128 / 255) + 0.5 * 0.4) * 255)
            expected_metallic = round((0.5 * 0.4 * 64 / 255 + 0.5 * 0.2) * 255)
            np.testing.assert_array_equal(orm[0, 0], (255, expected_roughness, expected_metallic))
            self.assertGreater(normal[0, 0, 0], 200)
            self.assertGreater(normal[0, 0, 2], 200)
            self.assertGreater(emission[0, 0, 0], 180)
            self.assertEqual(int(emission[0, 0, 1]), 0)
            _, one_hot = compose_preview([mapped, plain], [0, 1], size=4)
            orm, normal, emission = _compose_pbr_maps([mapped, plain], one_hot)
            np.testing.assert_array_equal(orm[0, 0], (255, 102, 51))
            np.testing.assert_array_equal(normal[0, 0], (128, 128, 255))
            np.testing.assert_array_equal(emission[0, 0], (0, 0, 0))

    def test_multi_surface_preview_dialog_renders_and_switches_weight_view(self):
        preview = HeightBlendPreview(TerrainMaterial())
        self.addCleanup(preview.close)
        self.app.processEvents()
        self.assertIsNotNone(preview._actor)
        self.assertIn("Mean final weights", preview.weight_label.text())
        preview.height_blend.setChecked(True)
        preview.view.setCurrentIndex(1)
        preview.lighting.setCurrentIndex(1)
        self.assertIsNotNone(preview._actor)
        self.assertFalse(preview.error.text())

    def test_multi_surface_preview_renders_composed_emission_and_normal(self):
        import pyvista as pv
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            normal = os.path.join(directory, "normal.png")
            emission = os.path.join(directory, "emission.png")
            Image.new("RGB", (4, 4), (128, 128, 255)).save(normal)
            Image.new("RGB", (4, 4), (255, 0, 0)).save(emission)
            material = TerrainMaterial()
            material.surfaces[0].normal = normal
            material.surfaces[0].emission = emission
            material.surfaces[0].color = [0, 0, 0]
            material.surfaces[1].color = [0, 0, 0]
            preview = HeightBlendPreview(material)
            self.addCleanup(preview.close)
            preview.surface[1].setCurrentIndex(1)
            self.assertFalse(preview.error.text())
            self.assertIsNotNone(preview._actor.prop.GetTexture("materialTex"))
            self.assertIsNotNone(preview._actor.prop.GetTexture("normalTex"))
            self.assertIsNotNone(preview._actor.prop.GetTexture("emissiveTex"))
            self.assertIsNotNone(preview._actor.mapper.dataset.GetPointData().GetTangents())
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            plotter.remove_all_lights()
            plotter.add_light(pv.Light(position=(0, 0, 10), focal_point=(0, 0, 0),
                                      light_type="scene light"))
            plotter.add_actor(preview._actor, reset_camera=False)
            plotter.view_xy()
            plotter.reset_camera()
            plotter.show(auto_close=False)
            color = plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean(axis=(0, 1))
            self.assertGreater(color[0], 50, color)
            self.assertGreater(color[0], color[1] * 2, color)
            material.surfaces[0].emission = ""
            for surface in material.surfaces[:2]:
                surface.color = [100, 100, 100]
            brightness = []
            for name, normal_color in (("flat", (128, 128, 255)), ("side", (255, 128, 128))):
                path = os.path.join(directory, name + ".png")
                Image.new("RGB", (4, 4), normal_color).save(path)
                material.surfaces[0].normal = path
                preview.weight[0].setValue(100)
                preview.weight[1].setValue(0)
                preview._render()
                plotter.clear()
                plotter.add_light(pv.Light(position=(0, 0, 10), focal_point=(0, 0, 0),
                                          light_type="scene light"))
                plotter.add_actor(preview._actor, reset_camera=False)
                plotter.render()
                brightness.append(plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean())
            self.assertGreater(brightness[0] - brightness[1], 10.0, brightness)

    def test_duplicate_biome_surface_can_be_fixed_in_the_wizard(self):
        material = TerrainMaterial()
        lowland = material.biomes[0]
        lowland.surfaces[1].surface = lowland.surfaces[0].surface
        lowland.surfaces[1].height = Band(12.0, None, 4.0)
        wizard = TerrainSetupWizard(material, np.linspace(0, 100, 400).reshape(20, 20))
        wizard.bands_page.refresh()
        row = wizard.bands_page.rows[0]
        row.layers[1].setCurrentIndex(row.layers[1].findData("soil"))

        self.assertTrue(wizard.bands_page.validatePage())
        fixed = wizard.material().biomes[0]
        self.assertEqual(fixed.surface_names(), ["grass", "soil", "gravel"])
        self.assertEqual(fixed.surfaces[1].height, Band(12.0, None, 4.0))
        wizard.reject()

    def test_map_edits_surface_paint_and_road_point_height(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.hm = Heightmap(np.full((33, 33), 10.0, np.float32), "terrain.npy", 0.0)
        window.map.set_image(np.zeros((33, 33), np.uint8), 33, 33)
        anchor = window.map._frame().center() + QPointF(20, 10)
        before = window.map._sample_at(anchor)
        window.map._zoom_at(anchor, 4)
        self.assertTrue(np.allclose(window.map._sample_at(anchor), before))
        window._set_busy(False)
        window.paint_kind.setCurrentIndex(1)
        window.paint.setChecked(True)
        window.paint_biome.setCurrentIndex(window.paint_biome.findText("soil"))
        window._paint_stroke([(16, 16)], False)
        self.assertTrue(window._material().has_surface_paint())
        window._paint_stroke([(16, 16)], True)
        self.assertFalse(window._material().has_surface_paint())

        window._road_add()
        window._road_clicked(4, 8)
        window._road_clicked(28, 24)
        window.road_height.setValue(20)
        road = window._material().roads[0]
        self.assertEqual(len(road.points), 2)
        self.assertEqual(road.points[0][2], 10)
        self.assertEqual(road.points[1][2], 20)
        window._road_clicked(4, 8)
        window.road_height.setValue(5)
        self.assertEqual(road.points[0][2], 5)

    def test_removing_painted_surface_requires_confirmation(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        material = window._material()
        material.ensure_surface_paint(16, 16)
        index = material.surface_names().index("soil")
        material.surface_paint[0, 0] = index
        window.material_panel.surface_list.setCurrentRow(index)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            window.material_panel._remove_surface()
        question.assert_called_once()
        self.assertIn("soil", material.surface_names())
        self.assertEqual(material.surface_paint[0, 0], index)

    def test_histogram_drag_updates_rules_material_editor_and_saved_project(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.histogram.resize(400, 112)
        window.histogram.set_heights(np.linspace(0, 100, 101))
        biome = window._material().biomes[1]
        biome.auto = True
        biome.height = Band(40.0, 80.0, 10.0)
        biome.slope = Band()
        for other in window._material().biomes[2:]:
            other.auto = False
        window.material_panel.refresh()
        window.material_panel.biome_list.setCurrentRow(1)
        window.height_biome.setCurrentIndex(1)
        window._dirty = False
        window._field = object()
        self.assertIs(window.histogram._flat_biome(45), biome)
        self.assertFalse(window.histogram.grab().isNull())

        def drag(handle, height):
            point = window.histogram._handles()[handle].toPoint()
            x = round(6 + height / 100 * (window.histogram.width() - 12))
            QTest.mousePress(window.histogram, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(window.histogram, QPoint((x + point.x()) // 2, point.y()))
            QTest.mouseMove(window.histogram, QPoint(x, point.y()))
            QTest.mouseRelease(window.histogram, Qt.MouseButton.LeftButton, pos=QPoint(x, point.y()))

        drag("min", 50)
        self.assertAlmostEqual(biome.height.min, 50, delta=0.3)
        self.assertAlmostEqual(window.material_panel.biome_editor.height.min.value(), 50, delta=0.3)
        self.assertTrue(window._dirty)
        self.assertIsNone(window._field)
        self.assertIsNot(window.histogram._flat_biome(45), biome)
        drag("fade_min", 35)
        self.assertAlmostEqual(biome.height.fade, 30, delta=0.6)
        self.assertAlmostEqual(window.height_band_fade.value(), biome.height.fade)
        drag("max", 70)
        self.assertAlmostEqual(biome.height.max, 70, delta=0.3)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "world.awtp")
            self.assertTrue(window._write_project(path))
            self.assertEqual(load_project(path).material.biomes[1].height, biome.height)
            self.assertFalse(window._dirty)
            window._open_project_file(path)
            self.assertEqual(window._material().biomes[1].height, biome.height)
            self.assertFalse(window._dirty)
            window.height_biome.setCurrentIndex(1)
            window.material_panel.biome_list.setCurrentRow(1)
            window.material_panel.biome_editor.height.min.setValue(52.0)
            self.assertEqual(window.height_band_min.value(), 52.0)

    def test_histogram_preserves_open_and_off_map_limits_and_paint_only_rules(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.histogram.set_heights(np.linspace(0, 100, 101))
        biome = window._material().biomes[1]
        biome.auto = True
        biome.height = Band(None, 500.0, 20.0)
        window.height_biome.setCurrentIndex(1)
        self.assertEqual(biome.height, Band(None, 500.0, 20.0))
        self.assertFalse(window.height_use_min.isChecked())
        self.assertEqual(window.histogram._handles(), {})
        window.height_use_min.setChecked(True)
        self.assertEqual(biome.height, Band(0.0, 500.0, 20.0))
        window.height_use_min.setChecked(False)
        self.assertEqual(biome.height, Band(None, 500.0, 20.0))

        window.height_auto.setChecked(False)
        self.assertFalse(biome.auto)
        self.assertFalse(window.height_use_max.isEnabled())
        self.assertEqual(window.histogram._handles(), {})
        window.height_biome.setCurrentIndex(0)
        self.assertFalse(window.height_auto.isEnabled())
        self.assertFalse(window.height_use_min.isEnabled())
        self.assertIn("Fallback", window.height_hint.text())
        window.height_biome.setCurrentIndex(1)
        self.assertFalse(window.height_auto.isChecked())
        self.assertEqual(biome.height, Band(None, 500.0, 20.0))
        window.height_auto.setChecked(True)
        self.assertTrue(biome.auto)
        self.assertEqual(biome.height, Band(None, 500.0, 20.0))
        biome.height.max = 25000.0
        window.material_panel.changed.emit()
        self.assertEqual(window.height_band_max.value(), 25000.0)
        window.height_band_fade.setValue(25.0)
        self.assertEqual(biome.height.max, 25000.0)

    def test_histogram_selection_tracks_renamed_and_reordered_biome(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.height_biome.setCurrentIndex(1)
        biome = window._material().biomes[1]
        biome.name = "renamed"
        window.material_panel.changed.emit()
        self.assertIs(window.height_biome.currentData(), biome)
        biomes = window._material().biomes
        biomes[1], biomes[2] = biomes[2], biomes[1]
        window.material_panel.changed.emit()
        self.assertIs(window.height_biome.currentData(), biome)
        self.assertEqual(window.histogram._selected, 2)

    def test_histogram_fade_handle_remains_usable_at_range_edge(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.histogram.resize(400, 180)
        window.histogram.set_heights(np.linspace(0, 60, 100))
        biome = window._material().biomes[3]
        biome.auto = True
        biome.height = Band(None, 1.2, 8)
        window.height_biome.setCurrentIndex(3)
        point = window.histogram._handles()["fade_max"].toPoint()
        self.assertGreater(point.x(), window.histogram._handles()["max"].x())
        destination = QPoint(round(6 + 8 / 60 * (window.histogram.width() - 12)), point.y())
        QTest.mousePress(window.histogram, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(window.histogram, destination)
        QTest.mouseRelease(window.histogram, Qt.MouseButton.LeftButton, pos=destination)
        self.assertAlmostEqual(biome.height.fade, 13.6, delta=0.4)
        self.assertIsNone(biome.height.min)

    def test_dragging_a_biome_boundary_selects_and_edits_it(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.histogram.resize(400, 180)
        window.histogram.set_heights(np.linspace(0, 100, 100))
        biome = window._material().biomes[2]
        biome.auto = True
        biome.height = Band(40, None, 4)
        start = QPoint(round(6 + 0.4 * (window.histogram.width() - 12)), 95)
        end = QPoint(round(6 + 0.55 * (window.histogram.width() - 12)), 95)
        QTest.mousePress(window.histogram, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(window.histogram, end)
        QTest.mouseRelease(window.histogram, Qt.MouseButton.LeftButton, pos=end)
        self.assertIs(window.height_biome.currentData(), biome)
        self.assertAlmostEqual(biome.height.min, 55, delta=0.3)

    def test_large_surface_preview_tracks_selection_edits_and_mesh_modes(self):
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        window.side_tabs.setCurrentIndex(1)
        self.assertIs(window.tabs.currentWidget(), window.surface_preview)
        panel = window.material_panel
        panel.surface_list.setCurrentRow(1)
        surface = window._material().surfaces[1]
        self.assertIs(window.surface_preview._surface, surface)
        panel.surface_editor.roughness.factor.setValue(0.35)
        self.assertAlmostEqual(window.surface_preview._actor.prop.roughness, 0.35)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "albedo.png")
            Image.new("RGB", (16, 16), (90, 140, 50)).save(path)
            panel.surface_editor.albedo._set(path)
            for index in range(3):
                window.surface_preview.mode.setCurrentIndex(index)
                actor = window.surface_preview._actor
                mesh = actor.mapper.dataset
                self.assertGreater(mesh.n_points, 100)
                self.assertIsNotNone(mesh.active_texture_coordinates)
                self.assertIsNotNone(actor.texture)
                if index:
                    self.assertGreater(mesh.active_texture_coordinates.max(), 1)
        window.tabs.setCurrentIndex(0)
        panel.surface_editor.show_preview.click()
        self.assertIs(window.tabs.currentWidget(), window.surface_preview)

    def test_surface_preview_renders_albedo_on_all_shapes(self):
        import pyvista as pv
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        surface = window._material().surfaces[0]
        surface.color = [255, 255, 255]
        surface.metallic = 0
        surface.roughness = 0.8
        with tempfile.TemporaryDirectory() as directory:
            png = os.path.join(directory, "red.png")
            dds = os.path.join(directory, "red.dds")
            Image.new("RGB", (16, 16), (240, 30, 30)).save(png)
            Image.new("RGBA", (16, 16), (240, 30, 30, 255)).save(dds)
            plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
            self.addCleanup(plotter.close)
            plotter.set_background("black")
            for path in (png, dds):
                surface.albedo = path
                window.surface_preview.set_surface(surface)
                for mode in range(3):
                    with self.subTest(path=path, mode=mode):
                        window.surface_preview.mode.setCurrentIndex(mode)
                        plotter.clear()
                        plotter.add_actor(window.surface_preview._actor, reset_camera=False)
                        plotter.view_xy()
                        plotter.reset_camera()
                        plotter.show(auto_close=False)
                        center = plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean(axis=(0, 1))
                        self.assertGreater(center[0], center[1] * 2, center)
            white = os.path.join(directory, "white.png")
            Image.new("RGB", (16, 16), (255, 255, 255)).save(white)
            surface.albedo = white
            surface.color = [40, 240, 40]
            window.surface_preview.set_surface(surface)
            plotter.clear()
            plotter.add_actor(window.surface_preview._actor, reset_camera=False)
            plotter.view_xy()
            plotter.reset_camera()
            plotter.show(auto_close=False)
            center = plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean(axis=(0, 1))
            self.assertGreater(center[1], center[0] * 2, center)

            surface.albedo = ""
            surface.color = [40, 40, 240]
            window.surface_preview.set_surface(surface)
            plotter.clear()
            plotter.add_actor(window.surface_preview._actor, reset_camera=False)
            plotter.view_xy()
            plotter.reset_camera()
            plotter.show(auto_close=False)
            center = plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean(axis=(0, 1))
            self.assertGreater(center[2], center[1] * 2, center)

    def test_surface_preview_applies_material_maps_and_shows_map_views(self):
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        surface = window._material().surfaces[0]
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for name, color in (("albedo", (120, 160, 80)), ("normal", (128, 128, 255)),
                                ("ao", (128, 128, 128)), ("roughness", (180, 180, 180)),
                                ("metallic", (90, 90, 90)), ("height", (220, 220, 220)),
                                ("emission", (20, 40, 60))):
                path = os.path.join(directory, name + ".png")
                Image.new("RGB", (16, 16), color).save(path)
                paths[name] = path
            surface.albedo = paths["albedo"]
            surface.normal = paths["normal"]
            surface.ao_map = MapSlot(paths["ao"], channel=1, invert=True)
            surface.roughness_map = MapSlot(paths["roughness"], channel=0)
            surface.metallic_map = MapSlot(paths["metallic"], channel=0)
            surface.height_map = MapSlot(paths["height"], channel=0)
            surface.emission = paths["emission"]
            preview = window.surface_preview
            preview.set_surface(surface)
            self.assertGreaterEqual(preview._actor.prop.GetNumberOfTextures(), 4)
            for mode in ("albedo", "normal", "ao", "roughness", "metallic", "height", "emission"):
                with self.subTest(mode=mode):
                    preview.map_mode.setCurrentIndex(preview.map_mode.findData(mode))
                    self.assertIsNotNone(preview._actor.texture)
                    self.assertNotIn("No ", preview.status.text())

    def test_surface_preview_uses_neutral_orm_channels_for_missing_maps(self):
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        surface = window._material().surfaces[0]
        surface.roughness = 0.4
        surface.metallic = 0.3
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ao.png")
            Image.new("RGB", (4, 4), (128, 128, 128)).save(path)
            surface.ao_map = MapSlot(path)
            preview = window.surface_preview
            preview.set_surface(surface)
            orm, _, _ = preview._pbr_maps(surface)
            pixels = orm.to_array()
            self.assertTrue(np.all(pixels[..., 0] == 128))
            self.assertTrue(np.all(pixels[..., 1:3] == 255))
            self.assertAlmostEqual(preview._actor.prop.GetRoughness(), 0.4)
            self.assertAlmostEqual(preview._actor.prop.GetMetallic(), 0.3)

    def test_surface_preview_uses_linear_tint_and_ao_strength(self):
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        surface = window._material().surfaces[0]
        surface.color = [128, 128, 128]
        surface.ao_strength = 0.0
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "map.png")
            Image.new("RGB", (4, 4), (128, 128, 128)).save(path)
            surface.albedo = path
            surface.ao_map = MapSlot(path)
            preview = window.surface_preview
            preview.set_surface(surface)
            self.assertTrue(np.all(preview._actor.texture.to_array()[..., :3] == 61))
            self.assertTrue(np.all(preview._map_texture(surface, "albedo").to_array()[..., :3] == 61))
            self.assertTrue(np.all(preview._map_texture(surface, "ao").to_array()[..., :3] == 255))

    def test_surface_preview_normal_map_changes_render_and_has_tangents(self):
        import pyvista as pv
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        surface = window._material().surfaces[0]
        surface.color = [100, 100, 100]
        surface.metallic = 0.0
        surface.roughness = 0.8
        preview = window.surface_preview
        plotter = pv.Plotter(off_screen=True, window_size=(200, 200))
        self.addCleanup(plotter.close)
        plotter.set_background("black")
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for name, normal in (("flat", (128, 128, 255)), ("side", (255, 128, 128))):
                path = os.path.join(directory, name + ".png")
                Image.new("RGB", (4, 4), normal).save(path)
                surface.normal = path
                preview.set_surface(surface)
                for mode in range(3):
                    preview.mode.setCurrentIndex(mode)
                    mesh = preview._actor.mapper.dataset
                    self.assertIsNotNone(mesh.GetPointData().GetTangents())
                preview.mode.setCurrentIndex(1)
                plotter.clear()
                plotter.add_light(pv.Light(position=(0, 0, 10), focal_point=(0, 0, 0),
                                          light_type="scene light"))
                plotter.add_actor(preview._actor, reset_camera=False)
                plotter.view_xy()
                plotter.reset_camera()
                plotter.show(auto_close=False)
                plotter.render()
                results.append(plotter.screenshot(return_img=True)[80:120, 80:120, :3].mean())
            self.assertGreater(results[0] - results[1], 10.0, results)

    def test_surface_preview_repeat_uses_physical_dimensions(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        preview = window.surface_preview
        editor = window.material_panel.surface_editor
        for repeat in (1.0, 3.0):
            editor.repeat.setValue(repeat)
            for mode in range(3):
                with self.subTest(repeat=repeat, mode=mode):
                    preview.mode.setCurrentIndex(mode)
                    mesh = preview._actor.mapper.dataset
                    widths = np.ptp(mesh.active_texture_coordinates, axis=0)
                    expected = ((math.pi / repeat, math.pi / (2 * repeat)) if mode == 0 else
                                (15 / repeat, 15 / repeat))
                    np.testing.assert_allclose(widths, expected, rtol=1e-5)
                    bounds = mesh.bounds
                    self.assertAlmostEqual(bounds[1] - bounds[0], 1 if mode == 0 else 15, places=2)
                    self.assertAlmostEqual(bounds[3] - bounds[2], 1 if mode == 0 else 15, places=2)
                    self.assertIn("1 m diameter", preview.scale_info.text())
                    self.assertIn("15 × 15 m", preview.scale_info.text())
                    self.assertIn(f"Repeat: {repeat:g} m", preview.scale_info.text())

    def test_surface_preview_repeat_changes_rendered_pattern(self):
        import pyvista as pv
        from PIL import Image

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(lambda: setattr(window, "_dirty", False))
        surface = window._material().surfaces[0]
        surface.color = [255, 255, 255]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "stripes.png")
            pixels = np.zeros((32, 32, 3), dtype=np.uint8)
            pixels[:, :16] = 255
            Image.fromarray(pixels).save(path)
            surface.albedo = path
            preview = window.surface_preview
            preview.mode.setCurrentIndex(1)
            plotter = pv.Plotter(off_screen=True, window_size=(300, 300))
            self.addCleanup(plotter.close)
            counts = []
            for repeat in (5.0, 1.0):
                surface.repeat_m = repeat
                preview.set_surface(surface)
                plotter.clear()
                plotter.add_actor(preview._actor, reset_camera=False)
                plotter.view_xy()
                plotter.reset_camera()
                plotter.show(auto_close=False)
                row = plotter.screenshot(return_img=True)[150, 70:230, :3].mean(axis=1)
                counts.append(np.count_nonzero(np.diff(row > 80)))
            self.assertGreater(counts[1], counts[0] * 2, counts)
