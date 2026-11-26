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
    from awt.gui.material_panel import MaterialPanel
    from awt.gui.terrain_wizard import TerrainSetupWizard
except ImportError:
    QApplication = None
    TerrainSetupWizard = None
    MainWindow = None
    MaterialPanel = None
    compose_preview = None
    HeightBlendPreview = None

import numpy as np

from awt.material import Band, MapSlot, Surface, TerrainMaterial
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
