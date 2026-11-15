import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from awt.gui.terrain_wizard import TerrainSetupWizard
except ImportError:
    QApplication = None
    TerrainSetupWizard = None

import numpy as np

from awt.material import Band, TerrainMaterial


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
