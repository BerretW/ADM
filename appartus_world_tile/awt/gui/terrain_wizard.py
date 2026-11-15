"""Guided setup for terrain profiles, biome bands and their shared surface textures."""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QScrollArea, QVBoxLayout, QWizard, QWizardPage, QWidget)

from ..material import BiomeSurface, SURFACES_PER_BIOME, TerrainMaterial, prepare_texture
from ..terrain_setup import PROFILES, apply_profile
from .material_panel import BandEdit, TexturePicker, swatch


class _ProfilePage(QWizardPage):
    def __init__(self, wizard: "TerrainSetupWizard"):
        super().__init__()
        self._wizard = wizard
        self.setTitle("Choose the terrain character")
        self.setSubTitle("This sets starting altitude levels; you can adjust every automatic biome next.")
        self.profile = QComboBox()
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(42)
        self.range = QLabel()
        self.range.setStyleSheet("color: #9aa3ad")

        form = QFormLayout()
        form.addRow("Terrain type", self.profile)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.description)
        layout.addSpacing(10)
        layout.addWidget(self.range)
        layout.addStretch(1)

        for key, (title, _description) in PROFILES.items():
            self.profile.addItem(title, key)
        for key, (_, description) in PROFILES.items():
            self.profile.setItemData(self.profile.findData(key), description, Qt.ItemDataRole.ToolTipRole)
        lo, hi = float(wizard._heights.min()), float(wizard._heights.max())
        self.range.setText(f"Heightmap range: {lo:.1f} m to {hi:.1f} m")
        self.profile.currentIndexChanged.connect(self._select_profile)
        self._update_description()

    def _select_profile(self) -> None:
        key = self.profile.currentData()
        self._update_description()
        self._wizard.select_profile(key)

    def _update_description(self) -> None:
        self.description.setText(PROFILES[self.profile.currentData()][1])


class _BiomeBands(QGroupBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto = QCheckBox("Place automatically")
        self.auto.toggled.connect(self._toggle_bands)
        self.height = BandEdit(" m", -20000.0, 20000.0, "height")
        self.slope = BandEdit("°", 0.0, 90.0, "slope")
        self.layers = [QComboBox() for _ in range(SURFACES_PER_BIOME)]
        self.note = QLabel()
        self.note.setStyleSheet("color: #9aa3ad")
        form = QFormLayout()
        form.addRow(self.auto)
        form.addRow("Height", self.height)
        form.addRow("Slope", self.slope)
        surfaces = QFormLayout()
        for index, combo in enumerate(self.layers):
            combo.setToolTip("Surface assigned to this biome layer; choose none to remove the layer")
            surfaces.addRow(f"Layer {index + 1}", combo)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(surfaces)
        layout.addWidget(self.note)

    def _toggle_bands(self, enabled: bool) -> None:
        self.height.setEnabled(enabled and self.auto.isEnabled())
        self.slope.setEnabled(enabled and self.auto.isEnabled())

    def set_biome(self, biome, first: bool, surface_names: list[str]) -> None:
        self.setTitle(biome.name)
        self.auto.blockSignals(True)
        self.auto.setChecked(biome.auto)
        self.auto.blockSignals(False)
        self.height.set_band(biome.height)
        self.slope.set_band(biome.slope)
        self.auto.setEnabled(not first)
        self._toggle_bands(biome.auto)
        self.note.setText("Fallback biome: fills the terrain left by other rules."
                          if first else "Fade softens the transition around each limit.")
        for index, combo in enumerate(self.layers):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— none —", "")
            for name in surface_names:
                combo.addItem(name, name)
            current = biome.surfaces[index].surface if index < len(biome.surfaces) else ""
            if current and current not in surface_names:
                combo.addItem(current, current)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

    def apply(self, biome, first: bool) -> None:
        if not first:
            biome.auto = self.auto.isChecked()
            biome.height = self.height.band()
            biome.slope = self.slope.band()
        entries = []
        seen = set()
        for index, combo in enumerate(self.layers):
            name = combo.currentData()
            if not name:
                continue
            if name in seen:
                raise ValueError(f"Biome '{biome.name}' uses surface '{name}' more than once. "
                                 "Choose a different surface or clear the duplicate layer.")
            seen.add(name)
            if index < len(biome.surfaces):
                entry = biome.surfaces[index]
                if entry.surface != name:
                    entry = copy.deepcopy(entry)
                    entry.surface = name
            else:
                entry = BiomeSurface(name)
            entries.append(entry)
        biome.surfaces = entries


class _BandsPage(QWizardPage):
    def __init__(self, wizard: "TerrainSetupWizard"):
        super().__init__()
        self._wizard = wizard
        self.setTitle("Set biome boundaries")
        self.setSubTitle("Set automatic height/slope bands and surface layers. The first biome remains the fallback.")
        self.rows: list[_BiomeBands] = []
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(2, 2, 2, 2)
        self.body_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        self.refresh()

    def initializePage(self) -> None:  # noqa: N802
        self.refresh()

    def refresh(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.rows.clear()
        for index, biome in enumerate(self._wizard.working.biomes):
            row = _BiomeBands()
            row.set_biome(biome, index == 0, self._wizard.working.surface_names())
            self.body_layout.addWidget(row)
            self.rows.append(row)
        self.body_layout.addStretch(1)

    def validatePage(self) -> bool:  # noqa: N802
        try:
            for index, (biome, row) in enumerate(zip(self._wizard.working.biomes, self.rows)):
                row.apply(biome, index == 0)
            self._wizard.working.validate_rules()
        except ValueError as error:
            QMessageBox.warning(self, "Biome boundaries", str(error))
            return False
        return True


class _SurfaceTexturesPage(QWizardPage):
    def __init__(self, wizard: "TerrainSetupWizard"):
        super().__init__()
        self._wizard = wizard
        self.setTitle("Choose biome textures")
        self.setSubTitle("Textures belong to shared surfaces, so neighbouring biomes can blend without a hard edge.")
        self.note = QLabel("Each surface appears once, even when several biomes use it. Pick an albedo image or "
                           "leave the current texture unchanged.")
        self.note.setWordWrap(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(2, 2, 2, 2)
        self.body_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        layout = QVBoxLayout(self)
        layout.addWidget(self.note)
        layout.addWidget(scroll, 1)
        self._pickers: dict[str, TexturePicker] = {}
        self._changed: set[str] = set()
        self.refresh()

    def initializePage(self) -> None:  # noqa: N802
        self.refresh()

    def refresh(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._pickers.clear()
        used = {entry.surface for biome in self._wizard.working.biomes for entry in biome.surfaces}
        for surface in self._wizard.working.surfaces:
            if surface.name not in used:
                continue
            biomes = [biome.name for biome in self._wizard.working.biomes
                      if surface.name in biome.surface_names()]
            group = QGroupBox()
            group.setTitle(surface.name)
            row_layout = QVBoxLayout(group)
            users = QLabel("Used by: " + ", ".join(biomes))
            users.setStyleSheet("color: #9aa3ad")
            picker = TexturePicker(f"{surface.name} texture")
            picker.set_path(surface.albedo)
            picker.changed.connect(lambda name=surface.name, widget=picker: self._set_texture(name, widget))
            heading = QHBoxLayout()
            color = QLabel()
            color.setPixmap(swatch(surface.color).pixmap(14, 14))
            heading.addWidget(color)
            heading.addWidget(users, 1)
            row_layout.addLayout(heading)
            row_layout.addWidget(picker)
            self.body_layout.addWidget(group)
            self._pickers[surface.name] = picker
        self.body_layout.addStretch(1)

    def reset_profile(self) -> None:
        self._changed.clear()
        self.refresh()

    def _set_texture(self, name: str, picker: TexturePicker) -> None:
        self._wizard.working.surface(name).albedo = picker.path()
        self._changed.add(name)

    def validatePage(self) -> bool:  # noqa: N802
        try:
            for name in self._changed:
                path = self._wizard.working.surface(name).albedo
                if path:
                    prepare_texture(path)
            self._wizard.working.validate_rules()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Biome textures", str(error))
            return False
        return True


class TerrainSetupWizard(QWizard):
    def __init__(self, material: TerrainMaterial, heights_m, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Terrain setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(760, 600)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Apply setup")
        self._base = copy.deepcopy(material)
        self.working = copy.deepcopy(material)
        self._heights = heights_m
        self._selected_profile = "current"

        self.profile_page = _ProfilePage(self)
        self.bands_page = _BandsPage(self)
        self.textures_page = _SurfaceTexturesPage(self)
        self.setPage(0, self.profile_page)
        self.setPage(1, self.bands_page)
        self.setPage(2, self.textures_page)
        self.setStartId(0)

    def select_profile(self, profile: str) -> None:
        if profile == self._selected_profile:
            return
        if profile == "current":
            texture_paths = {surface.name: surface.albedo for surface in self.working.surfaces}
            self.working = copy.deepcopy(self._base)
            for name, path in texture_paths.items():
                if name in self.working.surface_names():
                    self.working.surface(name).albedo = path
        else:
            if self._selected_profile == "arid":
                original = next((biome for biome in self._base.biomes if biome.name == "lowland"), None)
                current = next((biome for biome in self.working.biomes if biome.name == "lowland"), None)
                if original and current and original.surfaces and current.surfaces:
                    current.surfaces[0].surface = original.surfaces[0].surface
            apply_profile(self.working, self._heights, profile)
        self._selected_profile = profile
        if hasattr(self, "bands_page"):
            self.bands_page.refresh()
        if hasattr(self, "textures_page"):
            self.textures_page.reset_profile()

    def material(self) -> TerrainMaterial:
        return self.working
