"""Material tab: the four TERRAIN_4 layers with their textures, tint, repeat and PBR maps."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..material import CHANNELS, IMAGE_FILTER, Layer, MapSlot, TerrainMaterial

THUMB = 40


def _thumbnail(path: str) -> QPixmap | None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.draft("RGB", (THUMB * 2, THUMB * 2))
            rgb = image.convert("RGB")
            rgb.thumbnail((THUMB, THUMB))
            data = rgb.tobytes()
            qimage = QImage(data, rgb.width, rgb.height, 3 * rgb.width, QImage.Format.Format_RGB888).copy()
            return QPixmap.fromImage(qimage)
    except (OSError, ValueError):
        return None


class TexturePicker(QWidget):
    """Thumbnail, file name, browse and clear."""

    changed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._path = ""
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB, THUMB)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #22262b; border: 1px solid #3a4048; color: #6c747e")
        self.name = QLabel()
        self.name.setStyleSheet("color: #c8ced6")
        self.browse = QPushButton("Choose…")
        self.clear = QToolButton()
        self.clear.setText("✕")
        self.clear.setToolTip("Remove the texture")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.thumb)
        row.addWidget(self.name, 1)
        row.addWidget(self.browse)
        row.addWidget(self.clear)
        self.browse.clicked.connect(self._choose)
        self.clear.clicked.connect(lambda: self._set(""))
        self._refresh()

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        self._path = path or ""
        self._refresh()

    def _set(self, path: str) -> None:
        if path != self._path:
            self.set_path(path)
            self.changed.emit()

    def _choose(self) -> None:
        settings = QSettings()
        start = os.path.dirname(self._path) if self._path else settings.value("last_texture_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, self._title, start, IMAGE_FILTER)
        if path:
            settings.setValue("last_texture_dir", os.path.dirname(path))
            self._set(os.path.normpath(path))

    def _refresh(self) -> None:
        self.clear.setEnabled(bool(self._path))
        if not self._path:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("none")
            self.name.setText("No texture")
            self.name.setToolTip("")
            return
        exists = os.path.isfile(self._path)
        pixmap = _thumbnail(self._path) if exists else None
        self.thumb.setText("" if pixmap else "?")
        self.thumb.setPixmap(pixmap or QPixmap())
        self.name.setText(os.path.basename(self._path) + ("" if exists else "  (missing)"))
        self.name.setStyleSheet("color: #c8ced6" if exists else "color: #e07a6a")
        self.name.setToolTip(self._path)


class MapRow(QWidget):
    """Metallic or roughness: factor, optional texture, its channel and inversion."""

    changed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.factor = QDoubleSpinBox()
        self.factor.setRange(0.0, 1.0)
        self.factor.setDecimals(2)
        self.factor.setSingleStep(0.05)
        self.factor.setKeyboardTracking(False)
        self.factor.setToolTip(f"{title} factor; multiplies the texture value when a texture is set")
        self.picker = TexturePicker(f"{title} texture")
        self.channel = QComboBox()
        for letter in CHANNELS:
            self.channel.addItem(letter)
        self.channel.setToolTip(f"Channel of the texture that holds {title.lower()}")
        self.invert = QCheckBox("Invert")
        self.invert.setToolTip("Use 1 − value, for example a gloss or smoothness map as roughness")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        row = QHBoxLayout()
        row.addWidget(self.factor)
        row.addWidget(QLabel("channel"))
        row.addWidget(self.channel)
        row.addWidget(self.invert)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self.picker)
        self.factor.valueChanged.connect(self.changed)
        self.channel.currentIndexChanged.connect(self.changed)
        self.invert.toggled.connect(self.changed)
        self.picker.changed.connect(self._picker_changed)
        self._update_enabled()

    def _picker_changed(self) -> None:
        self._update_enabled()
        self.changed.emit()

    def _update_enabled(self) -> None:
        has = bool(self.picker.path())
        self.channel.setEnabled(has)
        self.invert.setEnabled(has)

    def set_values(self, factor: float, slot: MapSlot) -> None:
        self.factor.setValue(factor)
        self.picker.set_path(slot.path)
        self.channel.setCurrentIndex(slot.channel)
        self.invert.setChecked(slot.invert)
        self._update_enabled()

    def values(self) -> tuple[float, MapSlot]:
        return self.factor.value(), MapSlot(self.picker.path(), self.channel.currentIndex(),
                                             self.invert.isChecked())


class LayerCard(QGroupBox):
    changed = Signal()

    def __init__(self, index: int, name: str, parent=None):
        super().__init__(f"Layer {index}: {name} (mask {CHANNELS[index]})", parent)
        self._name = name
        self._color = [255, 255, 255]
        self.tint = QPushButton()
        self.tint.setFixedWidth(64)
        self.tint.setToolTip("Tint multiplied with the albedo texture (the whole colour when there is no texture)")
        self.albedo = TexturePicker("Albedo texture")
        self.repeat = QDoubleSpinBox()
        self.repeat.setRange(0.01, 100000)
        self.repeat.setDecimals(2)
        self.repeat.setSuffix(" m")
        self.repeat.setKeyboardTracking(False)
        self.repeat.setToolTip("Ground size of one texture repeat; rounded so each tile holds a whole number")
        self.repeat_info = QLabel()
        self.repeat_info.setStyleSheet("color: #9aa3ad")
        self.metallic = MapRow("Metallic")
        self.roughness = MapRow("Roughness")
        self.normal = TexturePicker("Normal map")
        form = QFormLayout(self)
        form.addRow("Albedo", self.albedo)
        row = QHBoxLayout()
        row.addWidget(self.tint)
        row.addStretch(1)
        form.addRow("Tint", row)
        row = QHBoxLayout()
        row.addWidget(self.repeat)
        row.addWidget(self.repeat_info, 1)
        form.addRow("Repeat", row)
        form.addRow("Metallic", self.metallic)
        form.addRow("Roughness", self.roughness)
        form.addRow("Normal", self.normal)
        self.tint.clicked.connect(self._choose_tint)
        for widget in (self.albedo, self.metallic, self.roughness, self.normal):
            widget.changed.connect(self.changed)
        self.repeat.valueChanged.connect(self.changed)

    def _choose_tint(self) -> None:
        color = QColorDialog.getColor(QColor(*self._color), self, f"Tint of {self._name}")
        if color.isValid():
            self._set_color([color.red(), color.green(), color.blue()])
            self.changed.emit()

    def _set_color(self, rgb: list[int]) -> None:
        self._color = list(rgb)
        r, g, b = rgb
        text = "#15181c" if (0.3 * r + 0.59 * g + 0.11 * b) > 140 else "#eef1f6"
        self.tint.setText(f"#{r:02x}{g:02x}{b:02x}")
        self.tint.setStyleSheet(f"background: rgb({r},{g},{b}); color: {text}")

    def set_layer(self, layer: Layer) -> None:
        self._set_color(layer.color)
        self.albedo.set_path(layer.albedo)
        self.repeat.setValue(layer.repeat_m)
        self.metallic.set_values(layer.metallic, layer.metallic_map)
        self.roughness.set_values(layer.roughness, layer.roughness_map)
        self.normal.set_path(layer.normal)

    def layer(self) -> Layer:
        metallic, metallic_map = self.metallic.values()
        roughness, roughness_map = self.roughness.values()
        return Layer(name=self._name, color=list(self._color), repeat_m=self.repeat.value(),
                     albedo=self.albedo.path(), metallic=metallic, metallic_map=metallic_map,
                     roughness=roughness, roughness_map=roughness_map, normal=self.normal.path())


class MaterialPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._tile_size = 0.0
        self.double_sided = QCheckBox("Double-sided")
        self.double_sided.setToolTip("Render back faces too (off for normal terrain)")
        intro = QLabel("Every tile uses this TERRAIN_4 material. The blend masks decide where each "
                       "layer shows; textures repeat across tile borders without seams.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9aa3ad")
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        self.cards = []
        default = TerrainMaterial()
        for index, layer in enumerate(default.layers):
            card = LayerCard(index, layer.name)
            card.changed.connect(self._card_changed)
            layout.addWidget(card)
            self.cards.append(card)
        layout.addWidget(self.double_sided)
        layout.addStretch(1)
        self.double_sided.toggled.connect(self._card_changed)
        self.set_material(default)

    def set_material(self, material: TerrainMaterial) -> None:
        self._loading = True
        for card, layer in zip(self.cards, material.layers):
            card.set_layer(layer)
        self.double_sided.setChecked(material.double_sided)
        self._loading = False
        self._update_repeats()

    def material(self) -> TerrainMaterial:
        return TerrainMaterial(layers=[card.layer() for card in self.cards],
                               double_sided=self.double_sided.isChecked())

    def set_tile_size(self, metres: float) -> None:
        self._tile_size = metres
        self._update_repeats()

    def _update_repeats(self) -> None:
        if self._tile_size <= 0:
            for card in self.cards:
                card.repeat_info.setText("")
            return
        scales = self.material().uv_scale(self._tile_size)
        for card, scale in zip(self.cards, scales):
            actual = self._tile_size / scale
            card.repeat_info.setText(f"{scale:g}× per {self._tile_size:g} m tile = {actual:.2f} m")

    def _card_changed(self) -> None:
        self._update_repeats()
        if not self._loading:
            self.changed.emit()
