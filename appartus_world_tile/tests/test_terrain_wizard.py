import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from awt.gui.main_window import MainWindow
    from awt.gui.terrain_wizard import TerrainSetupWizard
except ImportError:
    QApplication = None
    TerrainSetupWizard = None
    MainWindow = None

import numpy as np

from awt.material import Band, TerrainMaterial
from awt.heightmap import Heightmap
from awt.project import load_project


@unittest.skipIf(QApplication is None, "PySide6 is required for the terrain wizard test")
class TerrainWizardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
