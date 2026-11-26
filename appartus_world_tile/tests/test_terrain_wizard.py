import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPointF
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
