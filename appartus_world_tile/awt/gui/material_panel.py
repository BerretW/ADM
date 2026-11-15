"""Material tab: the surface library (texture sets) and the biomes that blend them."""

from __future__ import annotations

import io
import os

from PySide6.QtCore import QSettings, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..material import (CHANNELS, IMAGE_FILTER, MAX_BIOMES, MAX_SURFACES, SURFACES_PER_BIOME, Band, Biome,
                        BiomeSurface, MapSlot, Surface, TerrainMaterial, prepare_texture)

THUMB = 40


def _thumbnail(path: str) -> QPixmap | None:
    from PIL import Image

    try:
        prepared = prepare_texture(path)
        with Image.open(io.BytesIO(prepared.data)) as image:
            image.draft("RGB", (THUMB * 2, THUMB * 2))
            rgb = image.convert("RGB")
            rgb.thumbnail((THUMB, THUMB))
            data = rgb.tobytes()
            qimage = QImage(data, rgb.width, rgb.height, 3 * rgb.width, QImage.Format.Format_RGB888).copy()
            return QPixmap.fromImage(qimage)
    except (OSError, ValueError):
        return None


class SurfacePreview(QWidget):
    """Lit sphere or tiled plane showing the selected surface albedo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._surface: Surface | None = None
        self._texture = QPixmap()
        self._error = ""
        self._mode = 0
        self.setMinimumHeight(132)
        self.setMaximumHeight(160)

    def set_mode(self, mode: int) -> None:
        self._mode = mode
        self.update()

    def set_surface(self, surface: Surface) -> None:
        self._surface = surface
        self._texture = QPixmap()
        self._error = ""
        if surface.albedo:
            try:
                prepared = prepare_texture(surface.albedo)
                from PIL import Image, ImageChops

                with Image.open(io.BytesIO(prepared.data)) as image:
                    rgb = image.convert("RGB")
                    tint = Image.new("RGB", rgb.size, tuple(surface.color))
                    rgb = ImageChops.multiply(rgb, tint)
                    rgb.thumbnail((256, 256), Image.Resampling.LANCZOS)
                    qimage = QImage(rgb.tobytes(), rgb.width, rgb.height, 3 * rgb.width,
                                    QImage.Format.Format_RGB888).copy()
                    self._texture = QPixmap.fromImage(qimage)
            except (OSError, ValueError) as error:
                self._error = str(error)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#1b1f24"))
        if self._surface is None:
            return
        bounds = self.rect().adjusted(10, 8, -10, -8)
        if self._mode == 0:
            side = min(bounds.height(), bounds.width() * 0.48)
            disc = QRectF(bounds.center().x() - side * 0.5, bounds.center().y() - side * 0.5, side, side)
            path = QPainterPath()
            path.addEllipse(disc)
            painter.save()
            painter.setClipPath(path)
            if self._texture.isNull():
                painter.fillRect(disc, QColor(*self._surface.color))
            else:
                painter.drawPixmap(disc.toRect(), self._texture)
            light = QRadialGradient(disc.left() + side * 0.3, disc.top() + side * 0.24, side * 0.85)
            light.setColorAt(0.0, QColor(255, 255, 255, 65 if self._surface.roughness > 0.7 else 110))
            light.setColorAt(0.32, QColor(255, 255, 255, 12))
            light.setColorAt(1.0, QColor(0, 0, 0, 140))
            painter.fillRect(disc, light)
            highlight = 34 + round(100 * self._surface.metallic * (1.0 - self._surface.roughness))
            painter.setBrush(QColor(255, 255, 255, highlight))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(disc.left() + side * 0.23, disc.top() + side * 0.13,
                                       side * 0.22, side * 0.11))
            painter.restore()
        else:
            rect = QRectF(bounds.left() + bounds.width() * 0.08, bounds.top() + bounds.height() * 0.12,
                          bounds.width() * 0.84, bounds.height() * 0.76)
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * 0.1, rect.top())
            path.lineTo(rect.right(), rect.top())
            path.lineTo(rect.right() - rect.width() * 0.1, rect.bottom())
            path.lineTo(rect.left(), rect.bottom())
            path.closeSubpath()
            painter.save()
            painter.setClipPath(path)
            if self._texture.isNull():
                painter.fillPath(path, QColor(*self._surface.color))
            else:
                tile = self._texture.scaled(max(24, int(rect.width() / 4)),
                                            max(24, int(rect.height() / 3)),
                                            Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                painter.drawTiledPixmap(rect.toRect(), tile)
            shade = QLinearGradient(rect.topLeft(), rect.bottomRight())
            shade.setColorAt(0.0, QColor(255, 255, 255, 34))
            shade.setColorAt(1.0, QColor(0, 0, 0, 74))
            painter.fillPath(path, shade)
            painter.restore()
        if self._error:
            painter.setPen(QColor("#e07a6a"))
            painter.drawText(bounds.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignBottom
                             | Qt.AlignmentFlag.AlignHCenter, self._error[:110])


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


def swatch(rgb) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(*rgb))
    return QIcon(pixmap)


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, title: str, tooltip: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._rgb = [255, 255, 255]
        self.setFixedWidth(72)
        self.setToolTip(tooltip)
        self.clicked.connect(self._choose)
        self.set_rgb(self._rgb)

    def rgb(self) -> list[int]:
        return list(self._rgb)

    def set_rgb(self, rgb) -> None:
        self._rgb = [int(c) for c in rgb]
        r, g, b = self._rgb
        text = "#15181c" if (0.3 * r + 0.59 * g + 0.11 * b) > 140 else "#eef1f6"
        self.setText(f"#{r:02x}{g:02x}{b:02x}")
        self.setStyleSheet(f"background: rgb({r},{g},{b}); color: {text}")

    def _choose(self) -> None:
        color = QColorDialog.getColor(QColor(*self._rgb), self, self._title)
        if color.isValid():
            self.set_rgb([color.red(), color.green(), color.blue()])
            self.changed.emit()


class SurfaceEditor(QGroupBox):
    """Textures, tint, repeat and PBR values of the selected surface."""

    changed = Signal()
    terrain_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Surface", parent)
        self.tint = ColorButton("Surface tint", "Tint multiplied with the albedo texture (the whole colour when "
                                                "there is no texture); also the surface colour in previews")
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
        form = QFormLayout()
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
        self.preview_mode = QComboBox()
        self.preview_mode.addItems(("Sphere", "Plane"))
        self.preview_mode.setToolTip("Preview the selected surface on a lit sphere or tiled plane")
        self.show_terrain = QPushButton("Show blended terrain")
        self.show_terrain.setToolTip("Open the 3D terrain preview with the current biome blending")
        self.preview = SurfacePreview()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(QLabel("Preview"))
        row.addWidget(self.preview_mode)
        row.addStretch(1)
        row.addWidget(self.show_terrain)
        layout.addLayout(row)
        layout.addWidget(self.preview)
        for widget in (self.tint, self.albedo, self.metallic, self.roughness, self.normal):
            widget.changed.connect(self.changed)
        self.repeat.valueChanged.connect(self.changed)
        self.preview_mode.currentIndexChanged.connect(self.preview.set_mode)
        self.show_terrain.clicked.connect(self.terrain_requested)

    def set_surface(self, surface: Surface) -> None:
        self.setTitle(f"Surface: {surface.name}")
        self.tint.set_rgb(surface.color)
        self.albedo.set_path(surface.albedo)
        self.repeat.setValue(surface.repeat_m)
        self.metallic.set_values(surface.metallic, surface.metallic_map)
        self.roughness.set_values(surface.roughness, surface.roughness_map)
        self.normal.set_path(surface.normal)
        self.preview.set_surface(surface)

    def apply(self, surface: Surface) -> None:
        surface.color = self.tint.rgb()
        surface.albedo = self.albedo.path()
        surface.repeat_m = self.repeat.value()
        surface.metallic, surface.metallic_map = self.metallic.values()
        surface.roughness, surface.roughness_map = self.roughness.values()
        surface.normal = self.normal.path()


class BandEdit(QWidget):
    """Optional lower and upper limit with a fade width; an unchecked side is open."""

    changed = Signal()

    def __init__(self, unit: str, low: float, high: float, what: str, parent=None):
        super().__init__(parent)
        self.use_min = QCheckBox("from")
        self.use_max = QCheckBox("to")
        self.min = self._spin(unit, low, high)
        self.max = self._spin(unit, low, high)
        self.fade = self._spin(unit, 0.0, high - low)
        self.use_min.setToolTip(f"Only above this {what}")
        self.use_max.setToolTip(f"Only below this {what}")
        self.fade.setToolTip("Width of the soft edge, centred on each limit")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (self.use_min, self.min, self.use_max, self.max, QLabel("fade"), self.fade):
            row.addWidget(widget)
        row.addStretch(1)
        for box in (self.use_min, self.use_max):
            box.toggled.connect(self._toggled)
        for spin in (self.min, self.max, self.fade):
            spin.valueChanged.connect(self.changed)
        self._toggled()

    @staticmethod
    def _spin(unit: str, low: float, high: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(1)
        spin.setSuffix(unit)
        spin.setKeyboardTracking(False)
        spin.setMinimumWidth(84)
        return spin

    def _toggled(self) -> None:
        self.min.setEnabled(self.use_min.isChecked())
        self.max.setEnabled(self.use_max.isChecked())
        self.fade.setEnabled(self.use_min.isChecked() or self.use_max.isChecked())
        self.changed.emit()

    def set_band(self, band: Band) -> None:
        for box, spin, value in ((self.use_min, self.min, band.min), (self.use_max, self.max, band.max)):
            box.blockSignals(True)
            box.setChecked(value is not None)
            box.blockSignals(False)
            spin.blockSignals(True)
            if value is not None:
                spin.setValue(value)
            spin.blockSignals(False)
        self.fade.blockSignals(True)
        self.fade.setValue(band.fade)
        self.fade.blockSignals(False)
        self.min.setEnabled(self.use_min.isChecked())
        self.max.setEnabled(self.use_max.isChecked())
        self.fade.setEnabled(not band.is_open())

    def band(self) -> Band:
        return Band(self.min.value() if self.use_min.isChecked() else None,
                    self.max.value() if self.use_max.isChecked() else None, self.fade.value())


def _height_band() -> BandEdit:
    return BandEdit(" m", -20000.0, 20000.0, "height")


def _slope_band() -> BandEdit:
    return BandEdit("°", 0.0, 90.0, "slope")


NONE = "— none —"


class BiomeSurfaceRow(QGroupBox):
    changed = Signal()

    def __init__(self, index: int, parent=None):
        super().__init__(f"Surface {index + 1}" + (" (base, fills the rest)" if index == 0 else ""), parent)
        self.surface = QComboBox()
        self.surface.setToolTip("Surface from the library" + ("" if index == 0 else
                                "; covers the surfaces above it where its bands allow"))
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0.0, 1.0)
        self.strength.setDecimals(2)
        self.strength.setSingleStep(0.05)
        self.strength.setKeyboardTracking(False)
        self.strength.setToolTip("Share this surface takes where its bands allow it")
        self.height = _height_band()
        self.slope = _slope_band()
        form = QFormLayout(self)
        row = QHBoxLayout()
        row.addWidget(self.surface, 1)
        row.addWidget(QLabel("strength"))
        row.addWidget(self.strength)
        form.addRow(row)
        form.addRow("Height", self.height)
        form.addRow("Slope", self.slope)
        self.surface.currentIndexChanged.connect(self._surface_changed)
        for widget in (self.height, self.slope):
            widget.changed.connect(self.changed)
        self.strength.valueChanged.connect(self.changed)

    def _surface_changed(self) -> None:
        used = self.surface.currentText() != NONE
        for widget in (self.strength, self.height, self.slope):
            widget.setEnabled(used)
        self.changed.emit()

    def set_entry(self, entry: BiomeSurface | None, names: list[str], allow_none: bool) -> None:
        self.surface.blockSignals(True)
        self.surface.clear()
        if allow_none:
            self.surface.addItem(NONE)
        self.surface.addItems(names)
        self.surface.setCurrentText(entry.surface if entry else NONE)
        self.surface.blockSignals(False)
        entry = entry or BiomeSurface("")
        self.strength.blockSignals(True)
        self.strength.setValue(entry.strength)
        self.strength.blockSignals(False)
        self.height.set_band(entry.height)
        self.slope.set_band(entry.slope)
        for widget in (self.strength, self.height, self.slope):
            widget.setEnabled(self.surface.currentText() != NONE)

    def entry(self) -> BiomeSurface | None:
        name = self.surface.currentText()
        if not name or name == NONE:
            return None
        return BiomeSurface(name, self.height.band(), self.slope.band(), self.strength.value())


class BiomeEditor(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Biome", parent)
        self.color = ColorButton("Biome colour", "Colour of the biome on the map")
        self.auto = QCheckBox("Place automatically")
        self.auto.setToolTip("Use the height and slope rule below; otherwise the biome appears only where painted")
        self.height = _height_band()
        self.slope = _slope_band()
        self.rows = [BiomeSurfaceRow(i) for i in range(SURFACES_PER_BIOME)]
        layout = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.color)
        row.addWidget(self.auto)
        row.addStretch(1)
        form.addRow("Map colour", row)
        form.addRow("Height", self.height)
        form.addRow("Slope", self.slope)
        layout.addLayout(form)
        for row_widget in self.rows:
            layout.addWidget(row_widget)
            row_widget.changed.connect(self.changed)
        self.color.changed.connect(self.changed)
        self.auto.toggled.connect(self._auto_toggled)
        self.height.changed.connect(self.changed)
        self.slope.changed.connect(self.changed)

    def _auto_toggled(self) -> None:
        self.height.setEnabled(self.auto.isChecked())
        self.slope.setEnabled(self.auto.isChecked())
        self.changed.emit()

    def set_biome(self, biome: Biome, names: list[str], first: bool) -> None:
        self.setTitle(f"Biome: {biome.name}" + ("  (fallback: covers everything the others leave)" if first else ""))
        self.color.set_rgb(biome.color)
        self.auto.blockSignals(True)
        self.auto.setChecked(biome.auto)
        self.auto.blockSignals(False)
        self.height.set_band(biome.height)
        self.slope.set_band(biome.slope)
        self.height.setEnabled(biome.auto)
        self.slope.setEnabled(biome.auto)
        for i, row in enumerate(self.rows):
            row.set_entry(biome.surfaces[i] if i < len(biome.surfaces) else None, names, i > 0)

    def apply(self, biome: Biome) -> None:
        biome.color = self.color.rgb()
        biome.auto = self.auto.isChecked()
        biome.height = self.height.band()
        biome.slope = self.slope.band()
        entries = [entry for entry in (row.entry() for row in self.rows) if entry is not None]
        if entries:
            biome.surfaces = entries


class MaterialPanel(QWidget):
    """Edits a :class:`TerrainMaterial` in place; ``changed`` fires after every edit."""

    changed = Signal()
    fit_requested = Signal()
    terrain_preview_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._tile_size = 0.0
        self._material = TerrainMaterial()
        intro = QLabel("Surfaces are texture sets. Biomes pick up to four surfaces and blend them by height "
                       "and slope; the build writes the blend as vertex weights (COLOR_1) and the export "
                       "splits tiles into four-surface materials. Neighbouring biomes should share a surface "
                       "so the textures cross over smoothly.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9aa3ad")
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #e0b86a")
        self.warnings.hide()

        # Surface library
        self.surface_list = QListWidget()
        self.surface_list.setMaximumHeight(150)
        self.surface_editor = SurfaceEditor()
        surfaces = QGroupBox("Surface library")
        grid = QGridLayout(surfaces)
        grid.addWidget(self.surface_list, 0, 0, 4, 1)
        self.add_surface = QPushButton("Add")
        self.rename_surface = QPushButton("Rename…")
        self.remove_surface = QPushButton("Remove")
        for i, button in enumerate((self.add_surface, self.rename_surface, self.remove_surface)):
            grid.addWidget(button, i, 1)
        grid.addWidget(self.surface_editor, 4, 0, 1, 2)

        # Biomes
        self.biome_list = QListWidget()
        self.biome_list.setMaximumHeight(150)
        self.biome_list.setToolTip("Priority order: a later biome covers the earlier ones where its rule applies")
        self.biome_editor = BiomeEditor()
        biomes = QGroupBox("Biomes (later in the list wins)")
        grid = QGridLayout(biomes)
        grid.addWidget(self.biome_list, 0, 0, 5, 1)
        self.add_biome = QPushButton("Add")
        self.rename_biome = QPushButton("Rename…")
        self.remove_biome = QPushButton("Remove")
        self.biome_up = QPushButton("Up")
        self.biome_down = QPushButton("Down")
        for i, button in enumerate((self.add_biome, self.rename_biome, self.remove_biome, self.biome_up,
                                    self.biome_down)):
            grid.addWidget(button, i, 1)
        grid.addWidget(self.biome_editor, 5, 0, 1, 2)

        # Blending
        blending = QGroupBox("Blending")
        form = QFormLayout(blending)
        self.slope_radius = QDoubleSpinBox()
        self.slope_radius.setRange(0.0, 1000.0)
        self.slope_radius.setSuffix(" m")
        self.slope_radius.setKeyboardTracking(False)
        self.slope_radius.setToolTip("Slope is measured over this distance; larger values ignore small bumps")
        self.paint_softness = QDoubleSpinBox()
        self.paint_softness.setRange(0.0, 10000.0)
        self.paint_softness.setSuffix(" m")
        self.paint_softness.setKeyboardTracking(False)
        self.paint_softness.setToolTip("Painted biome borders fade over about this distance")
        self.double_sided = QCheckBox("Double-sided")
        self.double_sided.setToolTip("Render back faces too (off for normal terrain)")
        self.fit = QPushButton("Fit biome heights to the heightmap")
        self.fit.setToolTip("Place water, shore and snow levels of the default biomes from the height distribution")
        form.addRow("Slope radius", self.slope_radius)
        form.addRow("Paint softness", self.paint_softness)
        form.addRow(self.double_sided)
        form.addRow(self.fit)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.warnings)
        layout.addWidget(biomes)
        layout.addWidget(surfaces)
        layout.addWidget(blending)
        layout.addStretch(1)

        self.surface_list.currentRowChanged.connect(self._show_surface)
        self.biome_list.currentRowChanged.connect(self._show_biome)
        self.surface_editor.changed.connect(self._surface_edited)
        self.surface_editor.terrain_requested.connect(self.terrain_preview_requested)
        self.biome_editor.changed.connect(self._biome_edited)
        self.add_surface.clicked.connect(self._add_surface)
        self.rename_surface.clicked.connect(self._rename_surface)
        self.remove_surface.clicked.connect(self._remove_surface)
        self.add_biome.clicked.connect(self._add_biome)
        self.rename_biome.clicked.connect(self._rename_biome)
        self.remove_biome.clicked.connect(self._remove_biome)
        self.biome_up.clicked.connect(lambda: self._move_biome(-1))
        self.biome_down.clicked.connect(lambda: self._move_biome(1))
        for spin in (self.slope_radius, self.paint_softness):
            spin.valueChanged.connect(self._global_edited)
        self.double_sided.toggled.connect(self._global_edited)
        self.fit.clicked.connect(self.fit_requested)
        self.set_material(self._material)

    # ------------------------------------------------------------ public
    def set_material(self, material: TerrainMaterial) -> None:
        self._material = material
        self._loading = True
        self.slope_radius.setValue(material.slope_radius_m)
        self.paint_softness.setValue(material.paint_softness_m)
        self.double_sided.setChecked(material.double_sided)
        self._loading = False
        self._refresh_lists(0, 0)

    def material(self) -> TerrainMaterial:
        return self._material

    def set_tile_size(self, metres: float) -> None:
        self._tile_size = metres
        self._update_repeat_info()

    def set_warnings(self, lines: list[str]) -> None:
        self.warnings.setText("\n".join(lines))
        self.warnings.setVisible(bool(lines))

    def refresh(self) -> None:
        """Reload after the material was changed elsewhere (fit, paint)."""
        self._refresh_lists(self.surface_list.currentRow(), self.biome_list.currentRow())

    # ------------------------------------------------------------ lists
    def _refresh_lists(self, surface_row: int, biome_row: int) -> None:
        self._loading = True
        self.surface_list.clear()
        for surface in self._material.surfaces:
            self.surface_list.addItem(surface.name)
            self.surface_list.item(self.surface_list.count() - 1).setIcon(swatch(surface.color))
        self.biome_list.clear()
        for i, biome in enumerate(self._material.biomes):
            label = f"{biome.name}   ({', '.join(biome.surface_names())}){'' if biome.auto else '  · paint only'}"
            self.biome_list.addItem(label)
            self.biome_list.item(i).setIcon(swatch(biome.color))
        self._loading = False
        self.surface_list.setCurrentRow(max(0, min(surface_row, self.surface_list.count() - 1)))
        self.biome_list.setCurrentRow(max(0, min(biome_row, self.biome_list.count() - 1)))
        self._show_surface(self.surface_list.currentRow())
        self._show_biome(self.biome_list.currentRow())

    def _show_surface(self, row: int) -> None:
        if self._loading or not 0 <= row < len(self._material.surfaces):
            return
        self._loading = True
        self.surface_editor.set_surface(self._material.surfaces[row])
        self._loading = False
        self._update_repeat_info()

    def _show_biome(self, row: int) -> None:
        if self._loading or not 0 <= row < len(self._material.biomes):
            return
        self._loading = True
        self.biome_editor.set_biome(self._material.biomes[row], self._material.surface_names(), row == 0)
        self._loading = False
        self.biome_up.setEnabled(row > 0)
        self.biome_down.setEnabled(row < len(self._material.biomes) - 1)

    def _update_repeat_info(self) -> None:
        row = self.surface_list.currentRow()
        if self._tile_size <= 0 or not 0 <= row < len(self._material.surfaces):
            self.surface_editor.repeat_info.setText("")
            return
        scale = self._material.uv_scale(self._tile_size, [self._material.surfaces[row]])[0]
        self.surface_editor.repeat_info.setText(
            f"{scale:g}× per {self._tile_size:g} m tile = {self._tile_size / scale:.2f} m")

    # ------------------------------------------------------------ edits
    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _surface_edited(self) -> None:
        row = self.surface_list.currentRow()
        if self._loading or not 0 <= row < len(self._material.surfaces):
            return
        surface = self._material.surfaces[row]
        self.surface_editor.apply(surface)
        self.surface_editor.preview.set_surface(surface)
        self.surface_list.item(row).setIcon(swatch(surface.color))
        self._update_repeat_info()
        self._emit()

    def _biome_edited(self) -> None:
        row = self.biome_list.currentRow()
        if self._loading or not 0 <= row < len(self._material.biomes):
            return
        biome = self._material.biomes[row]
        self.biome_editor.apply(biome)
        item = self.biome_list.item(row)
        item.setIcon(swatch(biome.color))
        item.setText(f"{biome.name}   ({', '.join(biome.surface_names())}){'' if biome.auto else '  · paint only'}")
        self._emit()

    def _global_edited(self) -> None:
        if self._loading:
            return
        self._material.slope_radius_m = self.slope_radius.value()
        self._material.paint_softness_m = self.paint_softness.value()
        self._material.double_sided = self.double_sided.isChecked()
        self._emit()

    def _ask_name(self, title: str, current: str, taken: list[str]) -> str | None:
        name, ok = QInputDialog.getText(self, title, "Name:", text=current)
        name = name.strip()
        if not ok or not name or name == current:
            return None
        if name in taken:
            QMessageBox.warning(self, title, f"'{name}' is already used.")
            return None
        return name

    @staticmethod
    def _unique(base: str, taken: list[str]) -> str:
        index = 1
        while f"{base}_{index}" in taken:
            index += 1
        return f"{base}_{index}"

    def _add_surface(self) -> None:
        if len(self._material.surfaces) >= MAX_SURFACES:
            QMessageBox.information(self, "Add surface", f"The library holds at most {MAX_SURFACES} surfaces.")
            return
        self._material.surfaces.append(Surface(self._unique("surface", self._material.surface_names())))
        self._refresh_lists(len(self._material.surfaces) - 1, self.biome_list.currentRow())
        self._emit()

    def _rename_surface(self) -> None:
        row = self.surface_list.currentRow()
        if not 0 <= row < len(self._material.surfaces):
            return
        old = self._material.surfaces[row].name
        new = self._ask_name("Rename surface", old, self._material.surface_names())
        if new:
            self._material.rename_surface(old, new)
            self._refresh_lists(row, self.biome_list.currentRow())
            self._emit()

    def _remove_surface(self) -> None:
        row = self.surface_list.currentRow()
        if not 0 <= row < len(self._material.surfaces):
            return
        name = self._material.surfaces[row].name
        users = [b.name for b in self._material.biomes if name in b.surface_names()]
        if users and QMessageBox.question(self, "Remove surface", f"'{name}' is used by {', '.join(users)}. "
                                          "Remove it from those biomes too?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self._material.remove_surface(name)
        except ValueError as error:
            QMessageBox.warning(self, "Remove surface", str(error))
            return
        self._refresh_lists(row, self.biome_list.currentRow())
        self._emit()

    def _add_biome(self) -> None:
        if len(self._material.biomes) >= MAX_BIOMES:
            QMessageBox.information(self, "Add biome", f"At most {MAX_BIOMES} biomes are supported.")
            return
        name = self._unique("biome", [b.name for b in self._material.biomes])
        self._material.biomes.append(Biome(name, [200, 80, 160], [BiomeSurface(self._material.surfaces[0].name)],
                                           auto=False))
        self._refresh_lists(self.surface_list.currentRow(), len(self._material.biomes) - 1)
        self._emit()

    def _rename_biome(self) -> None:
        row = self.biome_list.currentRow()
        if not 0 <= row < len(self._material.biomes):
            return
        biome = self._material.biomes[row]
        new = self._ask_name("Rename biome", biome.name, [b.name for b in self._material.biomes])
        if new:
            biome.name = new
            self._refresh_lists(self.surface_list.currentRow(), row)
            self._emit()

    def _remove_biome(self) -> None:
        row = self.biome_list.currentRow()
        if not 0 <= row < len(self._material.biomes):
            return
        try:
            self._material.remove_biome(row)
        except ValueError as error:
            QMessageBox.warning(self, "Remove biome", str(error))
            return
        self._refresh_lists(self.surface_list.currentRow(), row)
        self._emit()

    def _move_biome(self, step: int) -> None:
        row = self.biome_list.currentRow()
        target = row + step
        if not (0 <= row < len(self._material.biomes) and 0 <= target < len(self._material.biomes)):
            return
        self._material.move_biome(row, target)
        self._refresh_lists(self.surface_list.currentRow(), target)
        self._emit()
