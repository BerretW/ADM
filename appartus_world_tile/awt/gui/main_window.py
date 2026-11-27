"""Main window: parameters on the left, map and 3D preview on the right."""

from __future__ import annotations

import copy
import hashlib
import math
import os
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSettings, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import texturing
from ..adm_export import Cancelled as ExportCancelled
from ..adm_export import ExportSettings, changed_tiles, export_tiles, rules_outdated
from ..heightmap import Heightmap, load_heightmap, preview
from ..material import PAINT_AUTO, Band, TerrainMaterial
from ..pipeline import (BuildParams, Cancelled, build, estimate_memory, fit_material, height_transform, hillshade,
                        load_manifest, tile_grid)
from ..project import PROJECT_EXTENSION, PROJECT_FILTER, Project, load_project
from ..roads import Road
from ..terrain_presets import list_presets, load_preset, preset_key, save_preset
from .map_view import MapView
from .material_panel import MaterialPanel, MaterialPreview, swatch
from .height_blend_preview import HeightBlendPreview
from .physical_material_dialog import PhysicalMaterialDialog
from .terrain_wizard import TerrainSetupWizard
from .viewer3d import DETAILED_MATERIAL_MODE, TRIANGLE_BUDGET, Viewer3D, triangle_count

HEIGHTMAP_FILTER = "Heightmaps (*.png *.tif *.tiff *.r16 *.raw *.npy *.pgm);;All files (*)"
MAP_MODES = ("Relief", "Biomes", "Surfaces", "Mesh density", "Physical surfaces")
BIOMES_MODE, SURFACES_MODE, DENSITY_MODE = 1, 2, 3
PHYSICAL_MODE = 4
APP_NAME = "Apparatus World Tile"


def _tile_key_id(key: tuple[int, int]) -> str:
    return f"x{key[0]:03d}_y{key[1]:03d}"


def _scroll(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


class _ChangeCheck(QThread):
    """Works out which tiles need exporting, off the UI thread (it hashes texture files)."""

    checked = Signal(int, object)

    def __init__(self, generation, manifest, material, settings, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._args = (manifest, material, settings)

    def run(self):
        try:
            self.checked.emit(self._generation, changed_tiles(*self._args))
        except Exception as exc:  # shown in the export panel
            self.checked.emit(self._generation, str(exc) or exc.__class__.__name__)


class Worker(QThread):
    """Runs ``func(progress, cancelled)`` off the UI thread."""

    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self._func = func
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self):
        try:
            self.done.emit(self._func(self.progress.emit, lambda: self._cancel))
        except (Cancelled, ExportCancelled):
            self.failed.emit("Cancelled")
        except Exception as exc:  # shown to the user
            self.failed.emit(str(exc) or exc.__class__.__name__)


def _spin(lo, hi, value, step=1.0, decimals=2, suffix=""):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    return box


def _band_factor(band: Band, value: float) -> float:
    def ramp(edge, rising):
        if band.fade <= 0:
            return 1.0 if (value >= edge) == rising else 0.0
        t = min(1.0, max(0.0, (value - edge) / band.fade + 0.5))
        t = t * t * (3 - 2 * t)
        return t if rising else 1.0 - t

    low = ramp(band.min, True) if band.min is not None else 1.0
    high = ramp(band.max, False) if band.max is not None else 1.0
    return low * high


class HeightHistogram(QWidget):
    """Height distribution coloured by the biome that wins on flat ground, with the biome height limits."""

    bandChanged = Signal(object)
    biomeSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setToolTip("Drag the selected biome's limit markers or its fade marker. "
                        "The histogram shows automatic biomes on flat ground.")
        self._counts = None
        self._range = (0.0, 1.0)
        self._material = TerrainMaterial()
        self._selected = 0
        self._drag = None

    def set_heights(self, heights_m: np.ndarray | None) -> None:
        if heights_m is None or heights_m.size == 0:
            self._counts = None
        else:
            lo, hi = float(heights_m.min()), float(heights_m.max())
            hi = hi if hi > lo else lo + 1.0
            counts, _ = np.histogram(heights_m, bins=96, range=(lo, hi))
            self._counts = np.log1p(counts)
            self._range = (lo, hi)
        self.update()

    def set_material(self, material: TerrainMaterial) -> None:
        self._material = material
        self.update()

    def set_selected(self, index: int) -> None:
        if index != self._selected:
            self._selected = index
            self._drag = None
        self.update()

    def _handles(self) -> dict[str, QPointF]:
        if self._counts is None or not 0 < self._selected < len(self._material.biomes):
            return {}
        biome = self._material.biomes[self._selected]
        if not biome.auto:
            return {}
        lo, hi = self._range
        width = max(1, self.width() - 12)

        def x(value):
            return 6 + (value - lo) / (hi - lo) * width

        band = biome.height
        handles = {}
        for key, value in (("min", band.min), ("max", band.max)):
            if value is not None and lo <= value <= hi:
                handles[key] = QPointF(x(value), 30 if key == "min" else 55)
        for key, edge, direction in (("fade_min", band.min, -1), ("fade_max", band.max, 1)):
            if edge is not None and lo <= edge <= hi:
                outer = edge + direction * band.fade / 2
                inner = edge - direction * band.fade / 2
                value = outer if lo <= outer <= hi else min(hi, max(lo, inner))
                handles[key] = QPointF(x(value), self.height() - (20 if key == "fade_min" else 42))
        return handles

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._counts is None:
            return
        handles = self._handles()
        pos = event.position()
        def distance(item):
            point = item[1]
            left = max(1, min(self.width() - 43, point.x() - 21))
            return (0 if left <= pos.x() <= left + 42 and abs(pos.y() - point.y()) <= 10
                    else (point - pos).manhattanLength())

        nearest = min(handles.items(), key=distance) if handles else None
        if nearest and distance(nearest) <= 18:
            name = nearest[0]
        else:
            lo, hi = self._range
            boundaries = []
            for index, biome in enumerate(self._material.biomes[1:], 1):
                if biome.auto:
                    for side, value in (("min", biome.height.min), ("max", biome.height.max)):
                        if value is not None and lo <= value <= hi:
                            x = 6 + (value - lo) / (hi - lo) * max(1, self.width() - 12)
                            if abs(x - pos.x()) <= 6:
                                boundaries.append((abs(x - pos.x()), index != self._selected, -index, side))
            if not boundaries:
                return
            _, _, index, name = min(boundaries)
            self.biomeSelected.emit(-index)
        self._drag = name
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag is None:
            self.setCursor(Qt.CursorShape.PointingHandCursor if any(
                (point - event.position()).manhattanLength() <= 18 for point in self._handles().values())
                           else Qt.CursorShape.ArrowCursor)
            return
        biome = self._material.biomes[self._selected]
        band = biome.height
        lo, hi = self._range
        value = lo + min(1.0, max(0.0, (event.position().x() - 6) / max(1, self.width() - 12))) * (hi - lo)
        value = round(value, 1)
        if self._drag == "min":
            band = Band(min(value, band.max) if band.max is not None else value, band.max, band.fade)
        elif self._drag == "max":
            band = Band(band.min, max(value, band.min) if band.min is not None else value, band.fade)
        else:
            anchor = band.min if self._drag == "fade_min" else band.max
            distance = abs(anchor - value)
            band = Band(band.min, band.max, round(2 * distance, 1))
        self.bandChanged.emit(band)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

    def _flat_biome(self, height: float):
        """Biome with the largest share at ``height`` on flat ground (automatic rules only)."""
        biomes = self._material.biomes
        remaining = 1.0
        best, best_share = biomes[0], 0.0
        for biome in reversed(biomes[1:]):
            share = remaining * (_band_factor(biome.height, height) * _band_factor(biome.slope, 0.0)
                                 if biome.auto else 0.0)
            if share > best_share:
                best, best_share = biome, share
            remaining -= share
        return best if best_share >= remaining else biomes[0]

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(26, 29, 34))
        if self._counts is None:
            painter.setPen(QColor(110, 116, 125))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Height histogram appears with a heightmap")
            return
        lo, hi = self._range
        w, h = self.width(), self.height() - 4
        peak = float(self._counts.max()) or 1.0
        n = len(self._counts)
        for i, value in enumerate(self._counts):
            height = lo + (i + 0.5) / n * (hi - lo)
            color = QColor(*self._flat_biome(height).color)
            x0 = int(6 + i * (w - 12) / n)
            x1 = int(6 + (i + 1) * (w - 12) / n)
            bar = int(value / peak * h)
            painter.fillRect(x0, h - bar + 1, max(1, x1 - x0 - 1), bar, color)

        def mark(value, color, style=Qt.PenStyle.SolidLine):
            if lo <= value <= hi:
                x = 6 + (value - lo) / (hi - lo) * (w - 12)
                painter.setPen(QPen(color, 1, style))
                painter.drawLine(int(x), 0, int(x), h)

        for biome in self._material.biomes[1:]:
            if biome.auto:
                for edge in (biome.height.min, biome.height.max):
                    if edge is not None:
                        mark(edge, QColor(*biome.color).lighter(130), Qt.PenStyle.DashLine)
        if 0 < self._selected < len(self._material.biomes):
            biome = self._material.biomes[self._selected]
            if biome.auto:
                painter.setPen(QPen(QColor(*biome.color).lighter(170), 2))
                points = []
                for i in range(97):
                    height = lo + (hi - lo) * i / 96
                    points.append(QPointF(6 + (w - 12) * i / 96,
                                          h - 4 - _band_factor(biome.height, height) * max(1, h - 20)))
                for start, end in zip(points, points[1:]):
                    painter.drawLine(start, end)
        painter.setPen(QColor(150, 158, 168))
        painter.drawText(4, 12, f"{lo:.0f} m")
        text = f"{hi:.0f} m"
        painter.drawText(w - painter.fontMetrics().horizontalAdvance(text) - 4, 12, text)
        handles = self._handles()
        for name, point in handles.items():
            color = QColor(*self._material.biomes[self._selected].color).lighter(150)
            painter.setPen(QPen(QColor(245, 245, 245, 210), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(point.x(), 0), QPointF(point.x(), h))
            label = {"min": "FROM", "max": "TO", "fade_min": "FADE", "fade_max": "FADE"}[name]
            rect = QRectF(max(1, min(w - 43, point.x() - 21)), point.y() - 10, 42, 20)
            painter.setPen(QPen(QColor(245, 245, 245), 1))
            painter.setBrush(QColor(38, 42, 48) if name.startswith("fade") else color.darker(130))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1500, 920)
        self.settings = QSettings()
        self.hm: Heightmap | None = None
        self.manifest: dict | None = None
        self._preview: np.ndarray | None = None  # strided heightmap samples
        self._relief: np.ndarray | None = None
        self._field: texturing.FieldPreview | None = None
        self._field_error = ""
        self._worker: Worker | None = None
        self._build_started = 0.0
        self._source_path = ""
        self._raw_size: tuple[int, int] | None = None
        self.project_path = ""
        self._dirty = False
        self._loading = False
        self._closing = False
        self._after_source = None  # callback once a heightmap has loaded
        self._check_generation = 0
        self._checker: _ChangeCheck | None = None
        self._changed_ids: list[str] | None = None
        self._check_pending = False
        self._road_point_index = -1
        self._road_loading = False
        self._height_controls_loading = False

        self._make_widgets()
        self._make_menu()
        self._field_timer = QTimer(self, singleShot=True, interval=150)
        self._field_timer.timeout.connect(self._refresh_field)
        self._check_timer = QTimer(self, singleShot=True, interval=400)
        self._check_timer.timeout.connect(self._check_changes)
        self._material_timer = QTimer(self, singleShot=True, interval=300)
        self._material_timer.timeout.connect(lambda: self.viewer.set_material(self._material()))
        self._connect()
        self._update_tile_info()
        self._set_busy(False)
        self._material_changed()
        self._update_title()

    # ---------------------------------------------------------------- UI
    def _make_widgets(self) -> None:
        # Source
        self.source = QLineEdit()
        self.source.setPlaceholderText("16-bit PNG, TIFF, R16/RAW or NPY")
        self.source.setReadOnly(True)
        self.browse_source = QPushButton("Open heightmap…")
        self.open_manifest = QPushButton("Open tiles…")
        self.open_manifest.setToolTip("Open an existing manifest.json to inspect it in 2D and 3D")
        self.source_info = QLabel("No heightmap loaded")
        self.source_info.setWordWrap(True)
        self.source_info.setStyleSheet("color: #9aa3ad")

        # Terrain scale
        self.spacing = _spin(0.001, 10000, 1.0, 0.1, 3, " m")
        self.spacing.setToolTip("Distance between neighbouring heightmap samples")
        self.height_min = _spin(-20000, 20000, 0.0, 10, 2, " m")
        self.height_max = _spin(-20000, 20000, 500.0, 10, 2, " m")
        self.remap = QCheckBox("Stretch float heights to this range")
        self.remap.setToolTip("Integer heightmaps always map black..white to min..max. "
                              "Float heightmaps are metres unless this is on.")
        self.origin = QComboBox()
        self.origin.addItem("South-west corner at 0, 0", "corner")
        self.origin.addItem("Centre at 0, 0", "center")
        self.terrain_size = QLabel()
        self.terrain_size.setStyleSheet("color: #9aa3ad")

        # Tiles and LODs
        self.tile_cells = QComboBox()
        for cells in (32, 64, 128, 256, 512, 1024, 2048, 4096):
            self.tile_cells.addItem(f"{cells} cells", cells)
        self.tile_cells.setCurrentIndex(3)
        self.lods = QLineEdit("0.25, 1, 4")
        self.lods.setToolTip("Maximum height error in metres for each LOD, finest first. "
                             "0 keeps every sample.")
        self.tile_info = QLabel()
        self.tile_info.setWordWrap(True)
        self.tile_info.setStyleSheet("color: #9aa3ad")
        self.collision_error = _spin(0.0, 1000.0, 0.0, 0.1, 2, " m")
        self.collision_error.setSpecialValueText("Off")
        self.collision_error.setToolTip("Build a separate collision mesh using a height-error bound. "
                                        "This does not change render LODs.")
        self.collision_boundary_edge = _spin(0.1, 10000.0, 4.0, 0.5, 2, " m")
        self.collision_boundary_edge.setToolTip(
            "Maximum RTIN split-edge length where physical assignments differ. "
            "Refinement also stops at the per-tile triangle cap.")
        self.collision_triangles = QSpinBox()
        self.collision_triangles.setRange(2, 2_097_152)
        self.collision_triangles.setValue(262144)
        self.collision_triangles.setSingleStep(4096)
        self.collision_triangles.setToolTip("Hard maximum number of triangles in each collision tile.")

        # Texturing
        self.histogram = HeightHistogram()
        self.texture_error = _spin(0.0, 1.0, 0.15, 0.05, 2)
        self.texture_error.setSpecialValueText("Off")
        self.texture_error.setToolTip("Split triangles where the interpolated surface weights miss the biome "
                                      "field by more than this share (0..1). Off keeps the height-only mesh.")
        self.texture_detail = _spin(0.01, 10000, 4.0, 0.5, 2, " m")
        self.texture_detail.setToolTip("Shortest triangle leg the texture split may create")
        self.rebuild_note = QLabel()
        self.rebuild_note.setWordWrap(True)
        self.rebuild_note.setStyleSheet("color: #e0b86a")
        self.rebuild_note.hide()

        # Output
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("Folder for built tiles (PLY meshes with vertex weights, manifest)")
        self.browse_out = QPushButton("…")
        self.browse_out.setFixedWidth(32)
        self.threads = QSpinBox()
        self.threads.setRange(0, os.cpu_count() or 64)
        self.threads.setSpecialValueText(f"All ({os.cpu_count()})")
        self.build_button = QPushButton("Build tiles")
        self.build_button.setStyleSheet("QPushButton { background: #b98a2c; color: #15181c; font-weight: 600;"
                                        " padding: 6px; } QPushButton:disabled { background: #4a4f57;"
                                        " color: #8a9099; }")
        self.cancel_button = QPushButton("Cancel")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(130)
        self.report.setPlaceholderText("Build and export results appear here")

        # Export
        self.material_panel = MaterialPanel()
        self.export_dir = QLineEdit()
        self.export_dir.setPlaceholderText("Folder for ADM tiles")
        self.browse_export = QPushButton("…")
        self.browse_export.setFixedWidth(32)
        self.lod_distance = _spin(0, 1_000_000, 0.0, 10, 1, " m")
        self.lod_distance.setSpecialValueText("Tile size")
        self.lod_distance.setToolTip("Camera distance where LOD 1 takes over; every further LOD doubles it")
        self.control_map_resolution = QSpinBox()
        self.control_map_resolution.setRange(0, 4096)
        self.control_map_resolution.setSingleStep(128)
        self.control_map_resolution.setSpecialValueText("Off")
        self.control_map_resolution.setToolTip(
            "Use a density-independent source-rule map or an assigned external RGBA mask. "
            "This is opt-in and requires a four-layer terrain shader profile.")
        self.external_control_map_path = QLineEdit()
        self.external_control_map_path.setPlaceholderText("Optional RGBA image spanning the full heightmap")
        self.browse_external_control_map = QPushButton("…")
        self.browse_external_control_map.setFixedWidth(32)
        self.external_control_map_channels = [QComboBox() for _ in range(4)]
        for channel, combo in zip("RGBA", self.external_control_map_channels):
            combo.setToolTip(f"Stable terrain surface ID assigned to the {channel} mask channel")
        self.gpu_container = QComboBox()
        self.gpu_container.addItem("DDS", "DDS")
        self.gpu_container.addItem("KTX2", "KTX2")
        self.gpu_encoding = QComboBox()
        self.gpu_encoding.addItem("Automatic by map role", "AUTO")
        self.gpu_encoding.addItem("BC7 (lossy)", "BC7")
        self.gpu_encoding.addItem("RGBA8 (uncompressed)", "RGBA8")
        self.palette_conflict_policy = QComboBox()
        self.palette_conflict_policy.addItem("Strict (reject conflicts)", "STRICT")
        self.palette_conflict_policy.addItem("Approximate (seam-aware reduction)", "APPROXIMATE")
        self.palette_conflict_policy.setToolTip(
            "Strict export refuses triangles with more than four active surfaces. Approximate export "
            "keeps shared-vertex weights consistent and reports the measured reduction error.")
        self.gpu_encoding.setToolTip(
            "Applies to converted 8-bit images. GPU sources remain unchanged unless conversion is enabled; "
            "16-bit data keeps its precision and can use R16 or PNG instead.")
        self.gpu_container.setToolTip(
            "Container for converted images. Compatible GPU sources remain unchanged unless conversion is enabled.")
        self.convert_gpu_sources = QCheckBox("Re-encode compatible GPU sources")
        self.convert_gpu_sources.setToolTip(
            "Off: preserve supported GPU files byte-for-byte. On: decode and re-encode them with new mipmaps; "
            "this can lose image quality. R16 data retains 16-bit precision.")
        self.embed = QCheckBox("Embed surface textures in every tile")
        self.embed.setToolTip("Off: surface textures are written once into textures/ next to the tiles "
                              "(ADM_external_images_v1).")
        self.validate = QCheckBox("Validate every file")
        self.validate.setChecked(True)
        self.export_state = QLabel("Build or open tiles first")
        self.export_state.setWordWrap(True)
        self.export_changed = QPushButton("Export changed")
        self.export_changed.setStyleSheet(self.build_button.styleSheet())
        self.export_selected = QPushButton("Export selected")
        self.export_all = QPushButton("Export all")

        terrain = QWidget()
        column = QVBoxLayout(terrain)

        group = QGroupBox("Heightmap")
        form = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(self.browse_source)
        row.addWidget(self.open_manifest)
        form.addLayout(row)
        form.addWidget(self.source)
        form.addWidget(self.source_info)
        column.addWidget(group)

        group = QGroupBox("Scale")
        form = QFormLayout(group)
        form.addRow("Sample spacing", self.spacing)
        form.addRow("Lowest height", self.height_min)
        form.addRow("Highest height", self.height_max)
        form.addRow("", self.remap)
        form.addRow("Origin", self.origin)
        form.addRow("", self.terrain_size)
        column.addWidget(group)

        group = QGroupBox("Tiles")
        form = QFormLayout(group)
        form.addRow("Tile size", self.tile_cells)
        form.addRow("LOD errors (m)", self.lods)
        form.addRow("Collision error (m)", self.collision_error)
        form.addRow("Physical-boundary edge (m)", self.collision_boundary_edge)
        form.addRow("Collision triangles/tile", self.collision_triangles)
        form.addRow("", self.tile_info)
        column.addWidget(group)

        group = QGroupBox("Texturing")
        form = QFormLayout(group)
        form.addRow(self.histogram)
        self.height_biome = QComboBox()
        self.height_auto = QCheckBox("Automatic")
        biome_row = QHBoxLayout()
        biome_row.addWidget(self.height_biome, 1)
        biome_row.addWidget(self.height_auto)
        form.addRow("Biome", biome_row)
        self.height_use_min = QCheckBox("From")
        self.height_use_max = QCheckBox("To")
        self.height_band_min = _spin(-20000, 20000, 0, 1, 1, " m")
        self.height_band_max = _spin(-20000, 20000, 0, 1, 1, " m")
        self.height_band_fade = _spin(0, 40000, 0, 1, 1, " m")
        self.height_band_min.setAccessibleName("Biome lower height limit")
        self.height_band_max.setAccessibleName("Biome upper height limit")
        self.height_band_fade.setAccessibleName("Biome height fade width")
        self.height_band_fade.setToolTip("Total transition width, centred on each limit and shared by both edges.")
        for checkbox, spin in ((self.height_use_min, self.height_band_min),
                               (self.height_use_max, self.height_band_max)):
            row = QHBoxLayout()
            row.addWidget(checkbox)
            row.addWidget(spin, 1)
            form.addRow(row)
        form.addRow("Fade (both edges)", self.height_band_fade)
        self.height_hint = QLabel("Drag circles for limits; drag the square for fade.")
        self.height_hint.setWordWrap(True)
        self.height_hint.setStyleSheet("color: #9aa3ad")
        form.addRow(self.height_hint)
        form.addRow("Texture error", self.texture_error)
        form.addRow("Texture detail", self.texture_detail)
        legend = QLabel("Biomes and surfaces are set on the Material tab and painted on the map. The build "
                        "stores per-vertex surface weights (COLOR_1) and adds triangles where the blend "
                        "needs them.")
        legend.setWordWrap(True)
        legend.setStyleSheet("color: #9aa3ad")
        form.addRow(legend)
        form.addRow(self.rebuild_note)
        column.addWidget(group)

        group = QGroupBox("Build")
        form = QFormLayout(group)
        row = QHBoxLayout()
        row.addWidget(self.out_dir)
        row.addWidget(self.browse_out)
        form.addRow("Folder", row)
        form.addRow("Threads", self.threads)
        form.addRow(self.build_button)
        column.addWidget(group)
        column.addStretch(1)

        export = QWidget()
        column = QVBoxLayout(export)
        group = QGroupBox("ADM tiles")
        form = QFormLayout(group)
        row = QHBoxLayout()
        row.addWidget(self.export_dir)
        row.addWidget(self.browse_export)
        form.addRow("Folder", row)
        form.addRow("LOD 1 from", self.lod_distance)
        form.addRow("Control Map", self.control_map_resolution)
        row = QHBoxLayout()
        row.addWidget(self.external_control_map_path)
        row.addWidget(self.browse_external_control_map)
        form.addRow("External RGBA map", row)
        for channel, combo in zip("RGBA", self.external_control_map_channels):
            form.addRow(f"{channel} surface", combo)
        form.addRow("GPU container", self.gpu_container)
        form.addRow("GPU encoding", self.gpu_encoding)
        form.addRow("Palette conflicts", self.palette_conflict_policy)
        form.addRow(self.convert_gpu_sources)
        form.addRow(self.embed)
        form.addRow(self.validate)
        note = QLabel("Each tile becomes <tile>.adm with its LODs, placed at its world position. Triangles "
                      "use four-layer materials blended by COLOR_1. Strict palette handling rejects "
                      "over-four-surface conflicts; the explicit approximate mode reports its measured "
                      "weight reduction. world.json remembers what was exported, so Export changed writes "
                      "only tiles whose terrain, weights, visual or physical material, or settings differ.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa3ad")
        form.addRow(note)
        column.addWidget(group)
        column.addWidget(self.export_state)
        column.addWidget(self.export_changed)
        row = QHBoxLayout()
        row.addWidget(self.export_selected)
        row.addWidget(self.export_all)
        column.addLayout(row)
        column.addStretch(1)

        self.side_tabs = QTabWidget()
        self.side_tabs.addTab(_scroll(terrain), "Terrain")
        self.side_tabs.addTab(_scroll(self.material_panel), "Material")
        self.side_tabs.addTab(_scroll(export), "Export")
        side = QWidget()
        side.setMinimumWidth(400)
        column = QVBoxLayout(side)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.side_tabs, 1)
        bottom = QVBoxLayout()
        bottom.setContentsMargins(8, 0, 8, 8)
        row = QHBoxLayout()
        row.addWidget(self.progress, 1)
        row.addWidget(self.cancel_button)
        bottom.addLayout(row)
        bottom.addWidget(self.status)
        bottom.addWidget(self.report)
        column.addLayout(bottom)

        # Map tab
        self.map = MapView()
        self.map_mode = QComboBox()
        self.map_mode.addItems(MAP_MODES)
        self.select_all = QPushButton("Select all")
        self.show_3d = QPushButton("Show selection in 3D")
        self.map_hint = QLabel("Click or drag to select tiles, Shift adds, double-click opens one tile in 3D")
        self.map_hint.setWordWrap(True)
        self.map_hint.setStyleSheet("color: #9aa3ad")
        self.paint = QPushButton("Paint")
        self.paint.setCheckable(True)
        self.paint.setToolTip("Left drag paints; right drag restores the underlying rules")
        self.paint_kind = QComboBox()
        self.paint_kind.addItems(("Biome", "Surface", "Physical"))
        self.paint_biome = QComboBox()
        self.paint_biome.setToolTip("Biome or surface to paint")
        self.physical_materials_button = QPushButton("Physical library…")
        self.physical_materials_button.setToolTip("Create or edit physical materials independently of visual surfaces.")
        self.physical_materials_button.hide()
        self.brush = _spin(0.1, 100000, 50.0, 5, 1, " m")
        self.brush.setToolTip("Brush radius")
        self.clear_paint = QPushButton("Clear paint")
        map_tab = QWidget()
        layout = QVBoxLayout(map_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.map_mode)
        bar.addWidget(self.select_all)
        bar.addWidget(self.show_3d)
        bar.addStretch(1)
        layout.addLayout(bar)
        paint_bar = QHBoxLayout()
        paint_bar.setContentsMargins(6, 0, 6, 0)
        for widget in (self.paint, self.paint_kind, self.paint_biome, self.physical_materials_button):
            paint_bar.addWidget(widget)
        paint_bar.addStretch(1)
        layout.addLayout(paint_bar)
        brush_bar = QHBoxLayout()
        brush_bar.setContentsMargins(6, 0, 6, 0)
        for widget in (QLabel("Brush radius"), self.brush, self.clear_paint):
            brush_bar.addWidget(widget)
        brush_bar.addStretch(1)
        layout.addLayout(brush_bar)
        road_bar = QHBoxLayout()
        road_bar.setContentsMargins(6, 0, 6, 0)
        self.road_mode = QPushButton("Edit roads")
        self.road_mode.setCheckable(True)
        self.road_list = QComboBox()
        self.road_new = QPushButton("New road")
        self.road_delete = QPushButton("Delete road")
        self.road_surface = QComboBox()
        self.road_width = _spin(0.1, 100000, 6.0, 1, 1, " m")
        self.road_shoulder = _spin(0, 100000, 3.0, 1, 1, " m")
        self.road_height = _spin(-100000, 100000, 0.0, 1, 2, " m")
        self.road_remove_point = QPushButton("Delete point")
        for widget in (self.road_mode, self.road_list, self.road_new, self.road_delete):
            road_bar.addWidget(widget)
        road_bar.addStretch(1)
        layout.addLayout(road_bar)
        road_settings = QHBoxLayout()
        road_settings.setContentsMargins(6, 0, 6, 0)
        for widget in (QLabel("Surface"), self.road_surface, QLabel("Width"), self.road_width,
                       QLabel("Shoulder"), self.road_shoulder):
            road_settings.addWidget(widget)
        road_settings.addStretch(1)
        layout.addLayout(road_settings)
        point_settings = QHBoxLayout()
        point_settings.setContentsMargins(6, 0, 6, 0)
        for widget in (QLabel("Point height"), self.road_height, self.road_remove_point):
            point_settings.addWidget(widget)
        point_settings.addStretch(1)
        layout.addLayout(point_settings)
        layout.addWidget(self.map, 1)
        layout.addWidget(self.map_hint)

        self.viewer = Viewer3D()
        self.surface_preview = MaterialPreview()
        self._height_blend_preview = None
        self.tabs = QTabWidget()
        self.tabs.addTab(map_tab, "Map")
        self.tabs.addTab(self.viewer, "3D")
        self.tabs.addTab(self.surface_preview, "Surface")

        splitter = QSplitter()
        splitter.addWidget(side)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 1060])
        self.setCentralWidget(splitter)

    def _make_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")

        def action(text, slot, shortcut=None):
            item = QAction(text, self)
            if shortcut is not None:
                item.setShortcut(shortcut)
            item.triggered.connect(slot)
            menu.addAction(item)
            return item

        action("&New project", self._new_project, QKeySequence.StandardKey.New)
        action("&Open project…", self._choose_project, QKeySequence.StandardKey.Open)
        action("&Save project", self._save_project, QKeySequence.StandardKey.Save)
        action("Save project &as…", self._save_project_as, QKeySequence.StandardKey.SaveAs)
        menu.addSeparator()
        self.heightmap_action = action("Open &heightmap…", self._choose_source)
        self.tiles_action = action("Open built &tiles…", self._choose_manifest)
        menu.addSeparator()
        action("&Quit", self.close, QKeySequence.StandardKey.Quit)

    def _connect(self) -> None:
        self.browse_source.clicked.connect(self._choose_source)
        self.open_manifest.clicked.connect(self._choose_manifest)
        self.browse_out.clicked.connect(self._choose_out)
        for box in (self.spacing, self.height_min, self.height_max):
            box.valueChanged.connect(self._scale_changed)
        self.remap.toggled.connect(self._scale_changed)
        self.tile_cells.currentIndexChanged.connect(self._update_tile_info)
        self.lods.textChanged.connect(self._update_tile_info)
        self.build_button.clicked.connect(self._start_build)
        self.cancel_button.clicked.connect(self._cancel)
        self.map_mode.currentIndexChanged.connect(self._update_map_image)
        self.select_all.clicked.connect(self.map.select_all)
        self.show_3d.clicked.connect(self._show_selection)
        self.map.tileActivated.connect(lambda ix, iy: self._show_tiles({(ix, iy)}, 0))
        self.map.selectionChanged.connect(self._selection_changed)
        self.paint.toggled.connect(self._paint_toggled)
        self.paint_kind.currentIndexChanged.connect(self._paint_kind_changed)
        self.physical_materials_button.clicked.connect(self._edit_physical_materials)
        self.brush.valueChanged.connect(self._update_brush)
        self.spacing.valueChanged.connect(self._update_brush)
        self.clear_paint.clicked.connect(self._clear_paint)
        self.map.paintStroke.connect(self._paint_stroke)
        self.map.paintFinished.connect(self._paint_finished)
        self.road_mode.toggled.connect(self._road_toggled)
        self.road_list.currentIndexChanged.connect(self._road_selected)
        self.road_new.clicked.connect(self._road_add)
        self.road_delete.clicked.connect(self._road_delete)
        self.road_remove_point.clicked.connect(self._road_remove)
        self.road_surface.currentIndexChanged.connect(self._road_edited)
        self.road_width.valueChanged.connect(self._road_edited)
        self.road_shoulder.valueChanged.connect(self._road_edited)
        self.road_height.valueChanged.connect(self._road_height_edited)
        self.map.roadPoint.connect(self._road_clicked)
        self.material_panel.fit_requested.connect(self._fit_material)
        self.material_panel.terrain_setup_requested.connect(self._terrain_setup)
        self.material_panel.save_preset_requested.connect(self._save_terrain_preset)
        self.material_panel.load_preset_requested.connect(self._load_terrain_preset)
        self.material_panel.terrain_preview_requested.connect(self._show_material_on_terrain)
        self.material_panel.surface_preview_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.surface_preview))
        self.material_panel.height_blend_preview_requested.connect(self._show_height_blend_preview)
        self.material_panel.surface_selected.connect(self.surface_preview.set_surface)
        self.surface_preview.set_material(self._material())
        self.surface_preview.set_surface(self._material().surfaces[self.material_panel.surface_list.currentRow()])
        self.side_tabs.currentChanged.connect(self._side_tab_changed)

        self.browse_export.clicked.connect(self._choose_export)
        self.browse_external_control_map.clicked.connect(self._choose_external_control_map)
        self.export_changed.clicked.connect(lambda: self._start_export("changed"))
        self.export_selected.clicked.connect(lambda: self._start_export("selected"))
        self.export_all.clicked.connect(lambda: self._start_export("all"))
        self.material_panel.changed.connect(self._material_changed)
        self.height_biome.currentIndexChanged.connect(self._height_biome_selected)
        self.height_auto.toggled.connect(self._height_auto_changed)
        self.height_use_min.toggled.connect(lambda enabled: self._height_limit_changed("min", enabled))
        self.height_use_max.toggled.connect(lambda enabled: self._height_limit_changed("max", enabled))
        self.height_band_min.valueChanged.connect(lambda value: self._height_value_changed("min", value))
        self.height_band_max.valueChanged.connect(lambda value: self._height_value_changed("max", value))
        self.height_band_fade.valueChanged.connect(lambda value: self._height_value_changed("fade", value))
        self.histogram.bandChanged.connect(self._height_band_changed)
        self.histogram.biomeSelected.connect(self.height_biome.setCurrentIndex)
        for signal in (self.material_panel.changed, self.export_dir.textChanged, self.lod_distance.valueChanged,
                       self.control_map_resolution.valueChanged,
                       self.external_control_map_path.textChanged,
                       self.embed.toggled, self.gpu_container.currentIndexChanged,
                       self.gpu_encoding.currentIndexChanged, self.palette_conflict_policy.currentIndexChanged,
                       self.convert_gpu_sources.toggled):
            signal.connect(self._schedule_check)
        self.control_map_resolution.valueChanged.connect(self.viewer.set_control_map_resolution)
        for combo in self.external_control_map_channels:
            combo.currentIndexChanged.connect(self._schedule_check)
            combo.currentIndexChanged.connect(self._mark_dirty)
            combo.currentIndexChanged.connect(self._material_changed)
        self.external_control_map_path.textChanged.connect(self._mark_dirty)
        self.external_control_map_path.textChanged.connect(self._material_changed)

        # Anything stored in the project marks it modified; the tile selection does not.
        for box in (self.spacing, self.height_min, self.height_max, self.threads, self.texture_error,
                    self.texture_detail, self.collision_error, self.collision_boundary_edge,
                    self.collision_triangles, self.lod_distance, self.control_map_resolution):
            box.valueChanged.connect(self._mark_dirty)
        for box in (self.remap, self.embed, self.validate, self.convert_gpu_sources):
            box.toggled.connect(self._mark_dirty)
        for edit in (self.lods, self.out_dir, self.export_dir):
            edit.textChanged.connect(self._mark_dirty)
        for combo in (self.origin, self.tile_cells, self.gpu_container, self.gpu_encoding,
                      self.palette_conflict_policy):
            combo.currentIndexChanged.connect(self._mark_dirty)
        self.material_panel.changed.connect(self._mark_dirty)

    # ----------------------------------------------------------- helpers
    def _params(self) -> BuildParams:
        try:
            errors = [float(v) for v in self.lods.text().replace(";", ",").split(",") if v.strip()]
        except ValueError as exc:
            raise ValueError("LOD errors must be numbers separated by commas") from exc
        return BuildParams(
            input_path=self._source_path,
            out_dir=self.out_dir.text().strip(),
            spacing_m=self.spacing.value(),
            height_min_m=self.height_min.value(),
            height_max_m=self.height_max.value(),
            remap_float=self.remap.isChecked(),
            tile_cells=self.tile_cells.currentData(),
            max_errors_m=errors,
            origin=self.origin.currentData(),
            threads=self.threads.value(),
            raw_size=self._raw_size,
            texture_error=self.texture_error.value(),
            texture_detail_m=self.texture_detail.value(),
            collision_max_error_m=self.collision_error.value(),
            collision_boundary_max_edge_m=self.collision_boundary_edge.value(),
            collision_max_triangles_per_tile=self.collision_triangles.value(),
        )

    def _material(self) -> TerrainMaterial:
        material = self.material_panel.material()
        material.external_control_map_path = self.external_control_map_path.text().strip()
        surface_ids = [str(combo.currentData() or "") for combo in self.external_control_map_channels]
        material.external_control_map_surface_ids = surface_ids if any(surface_ids) else []
        return material

    def _refresh_external_control_map_channels(self, material: TerrainMaterial) -> None:
        ids = material.external_control_map_surface_ids
        ids = ids if len(ids) == 4 else [""] * 4
        for combo, surface_id in zip(self.external_control_map_channels, ids):
            was_blocked = combo.blockSignals(True)
            combo.clear()
            combo.addItem("Select surface", "")
            for surface in material.surfaces:
                combo.addItem(surface.name, surface.id)
            if surface_id and combo.findData(surface_id) < 0:
                combo.addItem(f"Missing surface ({surface_id})", surface_id)
            combo.setCurrentIndex(max(0, combo.findData(surface_id)))
            combo.blockSignals(was_blocked)

    def _export_settings(self) -> ExportSettings:
        return ExportSettings(out_dir=self.export_dir.text().strip(), lod_distance_m=self.lod_distance.value(),
                              embed_textures=self.embed.isChecked(), validate=self.validate.isChecked(),
                              threads=self.threads.value(), gpu_container=self.gpu_container.currentData(),
                              gpu_encoding=self.gpu_encoding.currentData(),
                              palette_conflict_policy=self.palette_conflict_policy.currentData(),
                              convert_gpu_sources=self.convert_gpu_sources.isChecked(),
                              control_map_resolution=self.control_map_resolution.value())

    def _transform(self) -> tuple[float, float]:
        return height_transform(self.hm, self._params_safe())

    def _source_shape(self) -> tuple[int, int]:
        if self.hm is not None:
            return self.hm.width, self.hm.height
        if self.manifest is not None:
            return self.manifest["source"]["width"], self.manifest["source"]["height"]
        return 0, 0

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.browse_source, self.open_manifest, self.heightmap_action, self.tiles_action,
                       self.material_panel.fit):
            widget.setEnabled(not busy)
        self.paint.setEnabled(not busy and self.hm is not None)
        self.road_mode.setEnabled(not busy and self.hm is not None)
        self.road_new.setEnabled(not busy and self.hm is not None)
        if busy and self.paint.isChecked():
            self.paint.setChecked(False)
        if busy and self.road_mode.isChecked():
            self.road_mode.setChecked(False)
        self.build_button.setEnabled(not busy and self.hm is not None)
        self.cancel_button.setEnabled(busy)
        self._update_export_buttons()

    def _is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _update_export_buttons(self) -> None:
        ready = self.manifest is not None and not self._is_busy()
        count = len(self.map.selection)
        self.export_changed.setEnabled(ready and self._changed_ids != [])
        self.export_selected.setEnabled(ready and count > 0)
        self.export_selected.setText(f"Export selected ({count})" if count else "Export selected")
        self.export_all.setEnabled(ready)

    def _run(self, func, on_done, label: str) -> None:
        self._worker = Worker(func, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self.progress.setValue(0)
        self.status.setText(label)
        self._set_busy(True)
        self._worker.start()

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 1000))
        self.status.setText(message)

    def _on_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.status.setText(message)
        if message != "Cancelled":
            QMessageBox.warning(self, APP_NAME, message)
        if self._after_source is not None:  # a project whose heightmap failed still opens its tiles
            callback, self._after_source = self._after_source, None
            callback()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Cancelling…")

    # ------------------------------------------------------------ source
    def open_path(self, path: str) -> None:
        if path.lower().endswith(PROJECT_EXTENSION):
            self._open_project_file(path)
        elif os.path.isdir(path) or path.lower().endswith(".json"):
            self._load_manifest(path)
        else:
            self._load_source(path)

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open heightmap", self.settings.value("last_dir", ""),
                                              HEIGHTMAP_FILTER)
        if path:
            self.settings.setValue("last_dir", os.path.dirname(path))
            self._load_source(path)

    def _choose_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open tiles", self.settings.value("last_out", ""),
                                              "Tile manifest (manifest.json)")
        if path:
            self.settings.setValue("last_out", os.path.dirname(os.path.dirname(path)))
            self._load_manifest(path)

    def _choose_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Build folder", self.out_dir.text()
                                                or self.settings.value("last_out", ""))
        if path:
            self.out_dir.setText(path)

    def _choose_export(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "ADM tile folder", self.export_dir.text()
                                                or self.settings.value("last_out", ""))
        if path:
            self.export_dir.setText(path)

    def _choose_external_control_map(self) -> None:
        start = self.external_control_map_path.text().strip() or self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open external Control Map", start,
            "RGBA masks (*.png *.tif *.tiff *.tga);;All files (*)")
        if not path:
            return
        self.external_control_map_path.setText(path)
        material = self._material()
        if len(material.external_control_map_surface_ids) != 4 or not any(
                material.external_control_map_surface_ids):
            for combo, surface in zip(self.external_control_map_channels, material.surfaces[:4]):
                index = combo.findData(surface.id)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def _load_source(self, path: str, raw_size: tuple[int, int] | None = None) -> None:
        material = self._material()
        if (self._after_source is None and (material.has_paint() or material.has_surface_paint()
                                            or material.has_physical_paint() or material.roads)
                and QMessageBox.question(self, APP_NAME, "Opening another heightmap clears map-specific paint and "
                                         "roads. Continue?") != QMessageBox.StandardButton.Yes):
            return
        def task(progress, cancelled):
            progress(0.1, f"Reading {os.path.basename(path)}…")
            hm = load_heightmap(path, raw_size)
            progress(0.8, "Preparing preview…")
            return hm, preview(hm.data)

        self._run(task, self._source_loaded, "Loading heightmap…")

    def _source_loaded(self, result) -> None:
        self.hm, self._preview = result
        self._source_path = self.hm.path
        self.manifest = None
        self._changed_ids = None
        self.viewer.set_manifest(None)
        self.map.set_stats({}, {})
        self.map.set_marked(set())
        self.source.setText(self.hm.path)
        kind = f"{self.hm.data.dtype}" + (" (black..white = lowest..highest)" if self.hm.is_integer
                                           else " (values are metres)")
        self.source_info.setText(f"{self.hm.width:,} × {self.hm.height:,} samples, {kind}, "
                                 f"{self.hm.data.nbytes / 2**20:,.0f} MiB")
        self.remap.setEnabled(not self.hm.is_integer)
        self.progress.setValue(1000)
        self.status.setText("Heightmap loaded. Set the scale, then build.")
        callback, self._after_source = self._after_source, None
        if callback is None:
            base = os.path.splitext(self.hm.path)[0]
            self.out_dir.setText(base + "_tiles")
            self.export_dir.setText(base + "_adm")
            self._material().paint = None  # paint belongs to the previous heightmap
            self._material().surface_paint = None
            self._material().physical_paint = None
            self._material().roads.clear()
            self._road_refresh()
        self._scale_changed()
        if callback is None:
            self._fit_material()
        self.map.selection = set()
        self._selection_changed()
        self._check_changes()
        self._mark_dirty()
        if callback is not None:
            callback()

    def _load_manifest(self, path: str) -> bool:
        try:
            manifest = load_manifest(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return False
        self.hm = None
        self._preview = None
        self.histogram.set_heights(None)
        self._source_path = manifest["source"]["path"]
        self.source.setText(manifest["source"]["path"])
        self.source_info.setText(f"Tiles from {manifest['_dir']} (heightmap not loaded, "
                                 "open it to paint biomes or rebuild)")
        params = manifest.get("params", {})
        for box, key in ((self.spacing, "spacing_m"), (self.height_min, "height_min_m"),
                         (self.height_max, "height_max_m")):
            box.blockSignals(True)
            box.setValue(float(params.get(key, box.value())))
            box.blockSignals(False)
        index = self.tile_cells.findData(manifest["tile_cells"])
        self.tile_cells.blockSignals(True)
        self.tile_cells.setCurrentIndex(max(0, index))
        self.tile_cells.blockSignals(False)
        self.lods.setText(", ".join(f"{lod['max_error_m']:g}" for lod in manifest["lods"]))
        self.out_dir.setText(manifest["_dir"])
        if not self.export_dir.text().strip():
            self.export_dir.setText(os.path.normpath(manifest["_dir"]).rstrip("\\/") + "_adm")
        self._set_manifest(manifest)
        self._set_busy(False)
        self._mark_dirty()
        return True

    # -------------------------------------------------------- reactions
    def _scale_changed(self) -> None:
        width, height = self._source_shape()
        sp = self.spacing.value()
        if width:
            self.terrain_size.setText(f"Terrain {(width - 1) * sp / 1000:,.3f} × {(height - 1) * sp / 1000:,.3f} km")
        if self.hm is not None and self._preview is not None:
            scale, offset = self._transform()
            step = max(1, int(np.ceil(max(self.hm.data.shape) / 1024)))
            self._relief = hillshade(self._preview, sp * step, scale)
            self.histogram.set_heights(self._preview * scale + offset)
            self._height_biome_selected()
            self._field = None
            self._update_map_image()
        elif self.hm is None:
            self.histogram.set_heights(None)
        self._update_tile_info()
        self._update_brush()

    def _update_tile_info(self) -> None:
        width, height = self._source_shape()
        cells = self.tile_cells.currentData()
        self.map.set_grid(cells)
        self.material_panel.set_tile_size(cells * self.spacing.value())
        if not width:
            self.tile_info.setText("")
            return
        nx, ny = tile_grid(width, height, cells)
        sp = self.spacing.value()
        text = f"{cells * sp:,.1f} m per tile, {nx} × {ny} = {nx * ny:,} tiles"
        if self.hm is not None:
            memory = estimate_memory(width, height, cells, self.hm.data.itemsize)
            if self._material().roads:
                memory += width * height * 4
            text += f", at least {memory / 2**30:.2f} GiB working memory"
        self.tile_info.setText(text)
        if self.manifest is not None and self.manifest["tile_cells"] != cells:
            self.map.set_stats({}, {})

    def _params_safe(self) -> BuildParams:
        return BuildParams(input_path="", out_dir="", height_min_m=self.height_min.value(),
                           height_max_m=self.height_max.value(), remap_float=self.remap.isChecked())

    def _refresh_height_controls(self) -> None:
        material = self._material()
        selected = self.height_biome.currentData()
        selected_name = self.height_biome.currentText()
        self._height_controls_loading = True
        self.height_biome.clear()
        for biome in material.biomes:
            self.height_biome.addItem(swatch(biome.color), biome.name, biome)
        index = next((i for i, biome in enumerate(material.biomes) if biome is selected), -1)
        if index < 0:
            index = max(0, self.height_biome.findText(selected_name))
        self.height_biome.setCurrentIndex(index)
        self._height_controls_loading = False
        self._height_biome_selected()

    def _height_biome_selected(self) -> None:
        if self._height_controls_loading:
            return
        index = self.height_biome.currentIndex()
        biomes = self._material().biomes
        if not 0 <= index < len(biomes):
            self.histogram.set_selected(-1)
            return
        biome = biomes[index]
        band = biome.height
        self._height_controls_loading = True
        self.height_auto.setChecked(biome.auto)
        self.height_auto.setEnabled(index > 0)
        self.height_use_min.setChecked(band.min is not None)
        self.height_use_max.setChecked(band.max is not None)
        lo, hi = self.histogram._range
        limits = [lo, hi] + [value for value in (band.min, band.max) if value is not None]
        for spin in (self.height_band_min, self.height_band_max):
            spin.setRange(min(-20000, *limits), max(20000, *limits))
        self.height_band_fade.setMaximum(max(40000, band.fade, 2 * (hi - lo)))
        self.height_band_min.setValue(band.min if band.min is not None else lo)
        self.height_band_max.setValue(band.max if band.max is not None else hi)
        self.height_band_fade.setValue(band.fade)
        editable = index > 0 and biome.auto
        for widget in (self.height_use_min, self.height_use_max):
            widget.setEnabled(editable)
        self.height_band_min.setEnabled(editable and band.min is not None)
        self.height_band_max.setEnabled(editable and band.max is not None)
        self.height_band_fade.setEnabled(editable and not band.is_open())
        if index == 0:
            self.height_hint.setText("Fallback biome fills areas left by other automatic biomes.")
        elif not biome.auto:
            self.height_hint.setText("Paint-only biome. Enable Automatic to edit its height limits.")
        elif band.is_open():
            self.height_hint.setText("Enable From or To to add a height limit.")
        else:
            self.height_hint.setText("Drag FROM, TO or FADE in the graph. Both edges share one fade.")
        self.histogram.set_selected(index)
        self._height_controls_loading = False

    def _height_auto_changed(self, enabled: bool) -> None:
        index = self.height_biome.currentIndex()
        if self._height_controls_loading or index <= 0:
            return
        self._material().biomes[index].auto = enabled
        self.material_panel.refresh()
        self.material_panel.changed.emit()

    def _height_limit_changed(self, side: str, enabled: bool) -> None:
        if self._height_controls_loading:
            return
        index = self.height_biome.currentIndex()
        if index <= 0:
            return
        band = self._material().biomes[index].height
        value = (self.height_band_min if side == "min" else self.height_band_max).value() if enabled else None
        if value is not None:
            if side == "min" and band.max is not None:
                value = min(value, band.max)
            elif side == "max" and band.min is not None:
                value = max(value, band.min)
        self._height_band_changed(Band(value if side == "min" else band.min,
                                      value if side == "max" else band.max, band.fade))

    def _height_value_changed(self, side: str, value: float) -> None:
        if self._height_controls_loading:
            return
        index = self.height_biome.currentIndex()
        if index <= 0:
            return
        band = self._material().biomes[index].height
        if side == "min":
            value = min(value, band.max) if band.max is not None else value
            updated = Band(value, band.max, band.fade)
        elif side == "max":
            value = max(value, band.min) if band.min is not None else value
            updated = Band(band.min, value, band.fade)
        else:
            updated = Band(band.min, band.max, value)
        self._height_band_changed(updated)

    def _height_band_changed(self, band: Band) -> None:
        index = self.height_biome.currentIndex()
        if self._height_controls_loading or index <= 0:
            return
        biome = self._material().biomes[index]
        if not biome.auto:
            return
        if band == biome.height:
            self._height_biome_selected()
            return
        biome.height = band
        self.material_panel.refresh()
        self.material_panel.changed.emit()

    # ---------------------------------------------------------- texturing
    def _material_changed(self) -> None:
        """Any edit of surfaces, biomes, blending or paint."""
        material = self._material()
        self._refresh_external_control_map_channels(material)
        self.surface_preview.set_material(material)
        self.histogram.set_material(material)
        self._refresh_height_controls()
        self._material_timer.start()
        current = self.paint_biome.currentText()
        self.paint_biome.blockSignals(True)
        self.paint_biome.clear()
        kind = self.paint_kind.currentIndex()
        choices = (material.biomes if kind == 0 else material.surfaces if kind == 1
                   else material.physical_materials)
        for item in choices:
            if kind == 2:
                color = list(hashlib.sha256(item.id.encode("utf-8")).digest()[:3])
                self.paint_biome.addItem(swatch(color), item.name)
            else:
                self.paint_biome.addItem(swatch(item.color), item.name)
        self.paint_biome.setCurrentIndex(max(0, self.paint_biome.findText(current)))
        self.paint_biome.blockSignals(False)
        self.physical_materials_button.setVisible(kind == 2)
        self._road_refresh()
        self._update_tile_info()
        try:
            material.validate_rules()
            problems = [f"{a} and {b} share no surface" for a, b in texturing.unshared_pairs(material)]
            warnings = [f"Not touching yet, but would give a hard edge: {', '.join(problems)}."] if problems else []
        except ValueError as exc:
            warnings = [str(exc)]
        self._rule_warnings = warnings
        self._update_rebuild_note()
        self._field = None
        if self.map_mode.currentIndex() in (BIOMES_MODE, SURFACES_MODE):
            self._field_timer.start()
        elif self.map_mode.currentIndex() == PHYSICAL_MODE:
            self._update_map_image()
        else:
            self._show_material_warnings()

    def _show_material_warnings(self) -> None:
        lines = list(getattr(self, "_rule_warnings", []))
        if self._field is not None and self._field.problems:
            lines = [l for l in lines if not l.startswith("Not touching")]
            lines.insert(0, "Hard texture edge where these biomes meet (no shared surface): "
                         + ", ".join(f"{a} / {b}" for a, b in self._field.problems))
        if self._field_error:
            lines.insert(0, self._field_error)
        self.material_panel.set_warnings(lines)

    def _update_rebuild_note(self) -> None:
        if self.manifest is not None and rules_outdated(self.manifest, self._material()):
            self.rebuild_note.setText("Biomes, paint, roads or the surface list changed since these tiles were built. "
                                      "Rebuild to update the vertex layers before exporting.")
            self.rebuild_note.show()
        else:
            self.rebuild_note.hide()

    def _fit_material(self) -> None:
        if self.hm is None:
            QMessageBox.information(self, APP_NAME, "Open the heightmap first.")
            return
        fit_material(self.hm, self._params_safe(), self._material())
        self.material_panel.refresh()
        self._material_changed()
        self._schedule_check()
        self._mark_dirty()

    def _terrain_preset_dir(self) -> str:
        root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not root:
            raise OSError("The system has no writable application data folder")
        return os.path.join(root, "terrain_presets")

    def _terrain_setup(self) -> None:
        if self.hm is None:
            QMessageBox.information(self, APP_NAME, "Open the heightmap first.")
            return
        scale, offset = self._transform()
        heights = preview(self.hm.data, 512) * scale + offset
        wizard = TerrainSetupWizard(self._material(), heights, self)
        if wizard.exec() != wizard.DialogCode.Accepted:
            return
        self.material_panel.set_material(wizard.material())
        self.material_panel.changed.emit()

    def _save_terrain_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save terrain preset", "Preset name:")
        if not accepted:
            return
        try:
            root = self._terrain_preset_dir()
            key = preset_key(name)
            existing = os.path.join(root, key)
            overwrite = os.path.exists(existing)
            if overwrite and QMessageBox.question(
                    self, "Replace terrain preset",
                    f"A preset named '{name.strip()}' already exists. Replace its settings?") \
                    != QMessageBox.StandardButton.Yes:
                return
            save_preset(root, name, self._material(), overwrite=overwrite)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Save terrain preset", str(error))
            return
        self.status.setText(f"Saved terrain preset “{name.strip()}” with its textures.")

    def _load_terrain_preset(self) -> None:
        try:
            root = self._terrain_preset_dir()
            presets = list_presets(root)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Load terrain preset", str(error))
            return
        if not presets:
            QMessageBox.information(self, "Load terrain preset", "No saved terrain presets yet.")
            return
        names = [name for name, _key in presets]
        name, accepted = QInputDialog.getItem(self, "Load terrain preset", "Terrain preset:", names, 0, False)
        if not accepted:
            return
        material = self._material()
        if (material.has_paint() or material.has_surface_paint() or material.roads) and QMessageBox.question(
                self, "Replace terrain setup",
                "Loading a preset replaces the terrain setup and clears map-specific paint and roads. Continue?") \
                != QMessageBox.StandardButton.Yes:
            return
        key = presets[names.index(name)][1]
        try:
            material = load_preset(root, key)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Load terrain preset", str(error))
            return
        self.material_panel.set_material(material)
        self.material_panel.changed.emit()

    def _show_material_on_terrain(self) -> None:
        self.viewer.color.setCurrentIndex(DETAILED_MATERIAL_MODE)
        self.tabs.setCurrentWidget(self.viewer)

    def _side_tab_changed(self, index: int) -> None:
        if index == 1:
            self.tabs.setCurrentWidget(self.surface_preview)

    def _refresh_field(self) -> None:
        self._field = None
        self._update_map_image()

    def _show_height_blend_preview(self) -> None:
        if self._height_blend_preview is not None:
            self._height_blend_preview.close()
        self._height_blend_preview = HeightBlendPreview(self._material(), self)
        self._height_blend_preview.show()

    def _field_preview(self) -> texturing.FieldPreview | None:
        if self._field is not None or self.hm is None:
            return self._field
        scale, offset = self._transform()
        try:
            self._field = texturing.preview(self._material(), self.hm.data, scale, offset, self.spacing.value(),
                                            shade=self._relief)
            self._field_error = ""
        except ValueError as exc:
            self._field_error = f"Preview: {exc}"
        self._show_material_warnings()
        return self._field

    def _update_brush(self) -> None:
        self.map.set_brush(self.brush.value() / max(self.spacing.value(), 1e-9))

    def _paint_toggled(self, on: bool) -> None:
        if on:
            if self.hm is None:
                self.paint.setChecked(False)
                return
            self.road_mode.setChecked(False)
            material = self._material()
            kind = self.paint_kind.currentIndex()
            if kind == 2 and not material.physical_materials:
                self.paint.setChecked(False)
                QMessageBox.information(self, APP_NAME, "Create a physical material before painting assignments.")
                return
            old = (material.paint if kind == 0 else material.surface_paint if kind == 1
                   else material.physical_paint)
            ensure = (material.ensure_paint if kind == 0 else material.ensure_surface_paint if kind == 1
                      else material.ensure_physical_paint)
            changed = ensure(self.hm.width, self.hm.height)
            if changed and old is not None and np.any(old != PAINT_AUTO):
                QMessageBox.information(self, APP_NAME, "The stored paint was made for a heightmap of another "
                                                        "size and was cleared.")
            mode = (BIOMES_MODE if kind == 0 else SURFACES_MODE if kind == 1 else PHYSICAL_MODE)
            if self.map_mode.currentIndex() != mode:
                self.map_mode.setCurrentIndex(mode)
            self.map_hint.setText("Left drag paints, right drag restores the underlying rules. "
                                  "Turn Paint off to select tiles again.")
        else:
            self.map_hint.setText("Click or drag to select tiles, Shift adds, double-click opens one tile in 3D")
        self.map.set_paint_mode(on)

    def _paint_kind_changed(self) -> None:
        self.paint.setChecked(False)
        self._material_changed()

    def _paint_stroke(self, points, erase: bool) -> None:
        material = self._material()
        kind = self.paint_kind.currentIndex()
        paint = (material.paint if kind == 0 else material.surface_paint if kind == 1
                 else material.physical_paint)
        if paint is None:
            return
        value = PAINT_AUTO if erase else self.paint_biome.currentIndex()
        if value < 0:
            return
        cell = (material.paint_cell if kind == 0 else material.surface_paint_cell if kind == 1
                else material.physical_paint_cell)
        rows, cols = paint.shape
        radius = self.map._brush / cell
        r = int(math.ceil(radius))
        for col, row in points:
            cx, cy = col / cell, row / cell
            x0, x1 = max(0, int(cx) - r), min(cols, int(cx) + r + 2)
            y0, y1 = max(0, int(cy) - r), min(rows, int(cy) + r + 2)
            if x0 >= x1 or y0 >= y1:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1]
            disk = (xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 <= radius * radius
            paint[y0:y1, x0:x1][disk] = value
        self._field = None
        self._field_timer.start()

    def _paint_finished(self) -> None:
        self._material_changed()
        self._schedule_check()
        self._mark_dirty()

    def _clear_paint(self) -> None:
        material = self._material()
        kind = self.paint_kind.currentIndex()
        has_paint = (material.has_paint() if kind == 0 else material.has_surface_paint() if kind == 1
                     else material.has_physical_paint())
        if not has_paint:
            return
        if QMessageBox.question(self, APP_NAME, "Remove all paint of this type?") != QMessageBox.StandardButton.Yes:
            return
        paint = material.paint if kind == 0 else material.surface_paint if kind == 1 else material.physical_paint
        paint[:] = PAINT_AUTO
        self._paint_finished()

    def _edit_physical_materials(self) -> None:
        material = self._material()
        dialog = PhysicalMaterialDialog(material, self)
        dialog.exec()
        if dialog.changed:
            self.material_panel.refresh()
            self._material_changed()
            self._mark_dirty()

    def _road_refresh(self) -> None:
        material = self._material()
        index = self.road_list.currentIndex()
        self._road_loading = True
        self.road_list.clear()
        for i, road in enumerate(material.roads):
            self.road_list.addItem(f"Road {i + 1} ({len(road.points)} points)")
        index = min(max(index, 0), len(material.roads) - 1)
        self.road_list.setCurrentIndex(index)
        self.road_surface.clear()
        self.road_surface.addItems(material.surface_names())
        road = material.roads[index] if index >= 0 else None
        if road is not None:
            self.road_surface.setCurrentIndex(self.road_surface.findText(road.surface))
            self.road_width.setValue(road.width_m)
            self.road_shoulder.setValue(road.shoulder_m)
        self._road_point_index = min(self._road_point_index, len(road.points) - 1) if road else -1
        if road is not None and self._road_point_index >= 0:
            self.road_height.setValue(road.points[self._road_point_index][2])
        for widget in (self.road_surface, self.road_width, self.road_shoulder, self.road_delete):
            widget.setEnabled(road is not None)
        self.road_height.setEnabled(road is not None and self._road_point_index >= 0)
        self.road_remove_point.setEnabled(road is not None and self._road_point_index >= 0)
        self._road_loading = False
        self.map.set_roads(material.roads, index, self._road_point_index, self.spacing.value())

    def _road_toggled(self, on: bool) -> None:
        if on:
            if self.hm is None:
                self.road_mode.setChecked(False)
                return
            self.paint.setChecked(False)
            self.map_hint.setText("Select New road, then click to add points. Click a point to edit its height.")
        else:
            self.map_hint.setText("Click or drag to select tiles, Shift adds, double-click opens one tile in 3D")
        self.map.set_road_mode(on)

    def _road_selected(self) -> None:
        if self._road_loading:
            return
        self._road_point_index = -1
        self._road_refresh()

    def _road_add(self) -> None:
        if self.hm is None:
            return
        material = self._material()
        material.roads.append(Road(surface=material.surface_names()[0]))
        self._road_refresh()
        self.road_list.setCurrentIndex(len(material.roads) - 1)
        self.road_mode.setChecked(True)
        self._paint_finished()

    def _road_delete(self) -> None:
        index = self.road_list.currentIndex()
        if index < 0:
            return
        if QMessageBox.question(self, APP_NAME, "Delete the selected road?") != QMessageBox.StandardButton.Yes:
            return
        del self._material().roads[index]
        self._road_point_index = -1
        self._paint_finished()

    def _road_remove(self) -> None:
        index = self.road_list.currentIndex()
        if index < 0 or self._road_point_index < 0:
            return
        del self._material().roads[index].points[self._road_point_index]
        self._road_point_index = -1
        self._paint_finished()

    def _road_edited(self) -> None:
        index = self.road_list.currentIndex()
        if self._road_loading or index < 0:
            return
        road = self._material().roads[index]
        road.surface = self.road_surface.currentText()
        road.width_m = self.road_width.value()
        road.shoulder_m = self.road_shoulder.value()
        self._paint_finished()

    def _road_height_edited(self) -> None:
        index = self.road_list.currentIndex()
        if self._road_loading or index < 0 or self._road_point_index < 0:
            return
        self._material().roads[index].points[self._road_point_index][2] = self.road_height.value()
        self._paint_finished()

    def _road_clicked(self, col: float, row: float) -> None:
        index = self.road_list.currentIndex()
        if index < 0 or self.hm is None:
            self.status.setText("Select New road first.")
            return
        road = self._material().roads[index]
        frame = self.map._frame()
        radius = 8 * (self.hm.width - 1) / max(frame.width(), 1)
        for i, point in enumerate(road.points):
            if (point[0] - col) ** 2 + (point[1] - row) ** 2 <= radius ** 2:
                self._road_point_index = i
                self._road_refresh()
                return
        scale, offset = self._transform()
        height = texturing._bilinear.py_func(self.hm.data, col, row) * scale + offset
        road.points.append([float(col), float(row), float(height)])
        self._road_point_index = len(road.points) - 1
        self._paint_finished()

    def _update_map_image(self) -> None:
        width, height = self._source_shape()
        mode = self.map_mode.currentIndex()
        image = None
        if mode in (BIOMES_MODE, SURFACES_MODE):
            field = self._field_preview()
            if field is not None:
                image = field.biomes if mode == BIOMES_MODE else field.surfaces
            elif self.manifest is not None:
                image = self._read_rgb(self.manifest.get("biomes_preview" if mode == BIOMES_MODE
                                                         else "surfaces_preview"))
        elif mode == PHYSICAL_MODE:
            material = self._material()
            paint = material.physical_paint
            if paint is not None:
                image = np.full((*paint.shape, 3), (56, 61, 68), np.uint8)
                for index, item in enumerate(material.physical_materials):
                    color = np.asarray(list(hashlib.sha256(item.id.encode("utf-8")).digest()[:3]), np.uint8)
                    image[paint == index] = color
        if image is None:
            image = self._relief
        self.map.set_density_visible(mode == DENSITY_MODE)
        self.map.set_image(image, width, height)
        self.map.set_grid(self.tile_cells.currentData())

    def _read_rgb(self, name: str | None, mode: str = "RGB") -> np.ndarray | None:
        if not name or self.manifest is None:
            return None
        path = os.path.join(self.manifest["_dir"], name)
        if not os.path.exists(path):
            return None
        from PIL import Image

        with Image.open(path) as image:
            return np.asarray(image.convert(mode))

    # ------------------------------------------------------------- build
    def _start_build(self) -> None:
        if self.hm is None:
            return
        try:
            params = self._params()
            if not params.out_dir:
                raise ValueError("Choose an output folder")
            params.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Apparatus World Tile", str(exc))
            return
        self.settings.setValue("last_out", os.path.dirname(os.path.abspath(params.out_dir)))
        hm = self.hm
        self._build_started = time.perf_counter()
        self.report.clear()
        self._build_out = params.out_dir
        material = copy.deepcopy(self._material())
        try:
            material.validate()
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._run(lambda progress, cancelled: build(params, material, progress, cancelled, heightmap=hm),
                  self._build_done, "Building…")

    def _build_done(self, _manifest: dict) -> None:
        manifest = load_manifest(self._build_out)
        self._set_manifest(manifest)
        lines = [f"{manifest['tiles_x']} × {manifest['tiles_y']} tiles in {manifest['timings']['total_s']:.1f} s "
                 f"(errors {manifest['timings'].get('errors_s', 0):.1f} s, "
                 f"tiles {manifest['timings'].get('tiles_s', 0):.1f} s)"]
        for lod in manifest["lods"]:
            lines.append(f"LOD {lod['index']}: ≤ {lod['max_error_m']:g} m (measured "
                         f"{lod['measured_error_m']:.3f} m), {lod['triangles']:,} triangles")
        collision = manifest.get("collision")
        if collision:
            boundary_vertices = sum(tile["collision"]["boundary_vertices"] for tile in manifest["tiles"])
            lines.append(f"Collision: ≤ {collision['max_error_m']:g} m (measured "
                         f"{collision['max_measured_error_m']:.3f} m), "
                         f"{collision['triangles']:,} triangles; "
                         f"{boundary_vertices:,} refined tile-edge vertices; physical boundaries "
                         f"≤ {collision['physical_boundary_max_edge_m']:g} m")
        tex = manifest.get("texturing", {})
        if tex:
            lines.append(f"Vertex layers: {len(tex.get('surfaces', []))} surfaces from "
                         f"{len(tex.get('biomes', []))} biomes")
            pairs = tex.get("unshared_neighbours") or []
            if pairs:
                lines.append("Hard texture edges (biomes without a shared surface): "
                             + ", ".join(f"{a} / {b}" for a, b in pairs))
        lines.append(f"Output: {manifest['_dir']}")
        self.report.setPlainText("\n".join(lines))

    def _set_manifest(self, manifest: dict) -> None:
        self.manifest = manifest
        if self.hm is None:
            self._relief = self._read_rgb(manifest.get("preview"), "L")
            self._field = None
            self._scale_changed()
        self.viewer.set_manifest(manifest)
        self._update_rebuild_note()
        lod = 0
        peak = max((t["lods"][lod]["triangles"] for t in manifest["tiles"]), default=1) or 1
        density, info = {}, {}
        for tile in manifest["tiles"]:
            key = (tile["ix"], tile["iy"])
            density[key] = tile["lods"][lod]["triangles"] / peak
            info[key] = "\n".join(f"LOD {i}: {rec['triangles']:,} triangles, error {rec['measured_error_m']:.3f} m"
                                  for i, rec in enumerate(tile["lods"]))
        self.map.set_stats(density, info)
        self._update_map_image()
        everything = {(t["ix"], t["iy"]) for t in manifest["tiles"]}
        self.map.selection = set()
        self._selection_changed()
        self._show_tiles(everything, self._coarse_lod(everything))
        self._changed_ids = None
        self._check_changes()

    def _coarse_lod(self, tiles) -> int:
        """Finest LOD whose selection fits the 3D budget (else the coarsest)."""
        for lod in range(len(self.manifest["lods"])):
            if triangle_count(self.manifest, tiles, lod) <= TRIANGLE_BUDGET:
                return lod
        return len(self.manifest["lods"]) - 1

    # ----------------------------------------------------------------- 3D
    def _selection_changed(self) -> None:
        count = len(self.map.selection)
        self.show_3d.setEnabled(self.manifest is not None and count > 0)
        self.show_3d.setText(f"Show {count} tiles in 3D" if count else "Show selection in 3D")
        self._update_export_buttons()

    def _show_selection(self) -> None:
        if self.manifest and self.map.selection:
            self._show_tiles(self.map.selection, self._coarse_lod(self.map.selection))
            self.tabs.setCurrentWidget(self.viewer)

    def _show_tiles(self, tiles, lod: int) -> None:
        if not self.manifest or not tiles:
            return
        self.viewer.show_tiles(tiles, lod)
        if len(tiles) == 1:
            self.tabs.setCurrentWidget(self.viewer)

    def closeEvent(self, event):  # noqa: N802
        if not self._closing:
            if not self._confirm_discard():
                event.ignore()
                return
            self._closing = True
            self._field_timer.stop()
            self._check_timer.stop()
            self._material_timer.stop()
            self._check_pending = False
            self._check_generation += 1
        if self._checker is not None:
            event.ignore()
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self.surface_preview.shutdown()
        if self._height_blend_preview is not None:
            self._height_blend_preview.close()
        self.viewer.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ export
    def _schedule_check(self) -> None:
        self._check_timer.start()

    def _check_changes(self) -> None:
        if self._closing:
            return
        settings = self._export_settings()
        if self.manifest is None or not settings.out_dir:
            self._check_generation += 1
            self._changed_ids = None
            self.map.set_marked(set())
            self.export_state.setText("Build or open tiles first" if self.manifest is None
                                      else "Choose a folder for the ADM tiles")
            self._update_export_buttons()
            return
        if self._checker is not None:
            self._check_pending = True
            return
        self._check_generation += 1
        self.export_state.setText("Checking which tiles changed…")
        self._checker = _ChangeCheck(self._check_generation, self.manifest, copy.deepcopy(self._material()),
                                     settings, self)
        self._checker.checked.connect(self._on_checked)
        self._checker.finished.connect(self._checker_finished)
        self._checker.start()

    def _checker_finished(self) -> None:
        self._checker = None
        if self._closing:
            self.close()
        elif self._check_pending:
            self._check_pending = False
            self._check_changes()

    def _on_checked(self, generation: int, result) -> None:
        if generation != self._check_generation or self.manifest is None:
            return
        total = len(self.manifest["tiles"])
        if isinstance(result, str):
            self._changed_ids = None
            self.map.set_marked(set())
            self.export_state.setText(f"Cannot compare with the export folder: {result}")
        else:
            self._changed_ids = list(result)
            keys = {t["id"]: (t["ix"], t["iy"]) for t in self.manifest["tiles"]}
            self.map.set_marked({keys[i] for i in self._changed_ids if i in keys})
            count = len(self._changed_ids)
            if count == 0:
                self.export_state.setText(f"All {total:,} tiles are up to date in the export folder.")
            else:
                self.export_state.setText(f"{count:,} of {total:,} tiles are new or changed since the last "
                                          "export (red corner on the map).")
        self._update_export_buttons()

    def _start_export(self, mode: str) -> None:
        if self.manifest is None or self._is_busy():
            return
        settings = self._export_settings()
        material = copy.deepcopy(self._material())
        try:
            settings.validate_values()
            material.validate()
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        selected = sorted(_tile_key_id(key) for key in self.map.selection)
        manifest = self.manifest
        self.report.clear()
        self._run(lambda progress, cancelled: export_tiles(manifest, material, settings, mode, selected,
                                                           progress, cancelled),
                  self._export_done, "Exporting ADM tiles…")

    def _export_done(self, result: dict) -> None:
        written = len(result["written"])
        self.progress.setValue(1000)
        self.status.setText(f"Exported {written:,} tiles")
        lines = [f"Wrote {written:,} tiles ({result['bytes'] / 2**20:,.1f} MiB) in "
                 f"{result['seconds']:.1f} s, {result['skipped']:,} up to date",
                 f"Up to {result.get('max_primitives', 1)} materials per tile LOD (four surfaces each)"]
        names = {surface.id: surface.name for surface in self._material().surfaces}

        def surface_label(surface_id: str) -> str:
            name = names.get(surface_id)
            return f"{name} ({surface_id})" if name and name != surface_id else surface_id

        mean_weights = result.get("mean_exported_weights_by_lod", {})
        if mean_weights:
            lines.append("Mean exported COLOR_1 vertex weights by LOD (input data, not shader-composed):")
            for lod, weights in mean_weights.items():
                values = ", ".join(
                    f"{surface_label(surface_id)} {weight:.1%}"
                    for surface_id, weight in weights.items())
                lines.append(f"LOD {lod}: {values}")
        if self._material().has_physical_paint():
            lines.append(f"{result.get('physical_triangles', 0):,} collision triangles have physical assignments.")
        if result.get("conflicts"):
            lines.append(f"{result['conflicts']:,} triangles needed approximate palettes with at most four "
                         "surfaces.")
            if result.get("conflicts_by_lod"):
                lod_counts = ", ".join(
                    f"LOD {lod}: {count:,}" for lod, count in result["conflicts_by_lod"].items() if count)
                lines.append(f"Palette conflicts by LOD across exported tiles: {lod_counts}.")
            tile_lod_counts = result.get("conflicts_by_tile_lod", {})
            if tile_lod_counts:
                sample = [
                    f"{tile_id} LOD {lod}: {count:,}"
                    for tile_id, counts in tile_lod_counts.items()
                    for lod, count in counts.items()
                ]
                lines.append("Palette conflicts by tile and LOD: " + "; ".join(sample[:20]))
                if len(sample) > 20:
                    lines.append(f"{len(sample) - 20:,} more tile/LOD entries omitted from this report.")
        tile_weights = result.get("mean_exported_weights_by_tile_lod", {})
        if tile_weights:
            samples = [
                f"{tile_id} LOD {lod}: " + ", ".join(
                    f"{surface_label(surface_id)} {weight:.1%}"
                    for surface_id, weight in weights.items())
                for tile_id, lods in tile_weights.items()
                for lod, weights in lods.items()
            ]
            lines.append("Mean exported vertex weights by tile and LOD: " + "; ".join(samples[:20]))
            if len(samples) > 20:
                lines.append(f"{len(samples) - 20:,} more tile/LOD weight entries omitted from this report.")
            for detail in result.get("conflict_details", []):
                dropped = ", ".join(
                    f"{surface['name']} ({surface['id']}) U8 (0-255) {surface['corner_weights']}"
                    for surface in detail["dropped_surfaces"])
                lines.append(f"{detail['tile_id']} LOD {detail['lod']} triangle "
                             f"{detail['triangle_index']}: dropped corner weights for {dropped}")
            if result.get("conflict_details_truncated"):
                lines.append(f"{result['conflict_details_truncated']:,} more conflicting triangles omitted "
                             "from the detail list.")
            lines.append("Suggestion: reduce overlapping surface weights or paint fewer active surfaces "
                         "with Surface on the Map tab.")
        lines += list(result.get("warnings", []))
        lines += [f"Folder: {result['out_dir']}",
                  "Import in Blender: File > Import > ADM Model, one .adm per tile."]
        self.report.setPlainText("\n".join(lines))
        self._check_changes()

    # ----------------------------------------------------------- project
    def _mark_dirty(self, *_args) -> None:
        if self._loading or self._dirty:
            return
        self._dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}{'*' if self._dirty else ''} - {APP_NAME}")

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, APP_NAME, "Save changes to the project first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self._save_project()
        return answer == QMessageBox.StandardButton.Discard

    def _collect_project(self) -> Project:
        return Project(params=self._params(), material=self._material(),
                       export=self._export_settings(),
                       selection=sorted(_tile_key_id(key) for key in self.map.selection),
                       path=self.project_path)

    def _save_project(self) -> bool:
        if not self.project_path:
            return self._save_project_as()
        return self._write_project(self.project_path)

    def _save_project_as(self) -> bool:
        start = self.project_path or (os.path.splitext(self._source_path)[0] + PROJECT_EXTENSION
                                      if self._source_path else self.settings.value("last_dir", ""))
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, PROJECT_FILTER)
        return bool(path) and self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            project = self._collect_project()
            project.save(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not save the project: {exc}")
            return False
        self.project_path = project.path
        self.settings.setValue("last_project", project.path)
        self._dirty = False
        self._update_title()
        self.status.setText(f"Saved {project.path}")
        return True

    def _new_project(self) -> None:
        if self._is_busy() or not self._confirm_discard():
            return
        project = Project.new()
        project.params.max_errors_m = [0.25, 1.0, 4.0]
        self._open_project(project)

    def _choose_project(self) -> None:
        if self._is_busy() or not self._confirm_discard():
            return
        start = self.settings.value("last_project", "") or self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Open project", start, PROJECT_FILTER)
        if path:
            self._open_project_file(path, confirmed=True)

    def _open_project_file(self, path: str, confirmed: bool = False) -> None:
        if not confirmed and not self._confirm_discard():
            return
        try:
            project = load_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.settings.setValue("last_project", project.path)
        self._open_project(project)

    def _open_project(self, project: Project) -> None:
        """Show a project: widgets first, then the heightmap (async), then its built tiles."""
        self._loading = True
        self.hm = None
        self.manifest = None
        self._preview = self._relief = self._field = None
        self._changed_ids = None
        self.viewer.set_manifest(None)
        self.map.set_stats({}, {})
        self.map.set_marked(set())
        self.map.selection = set()
        self.project_path = project.path
        self._source_path = project.params.input_path
        self._raw_size = project.params.raw_size
        self.source.setText(self._source_path)
        self.source_info.setText("No heightmap loaded")
        self._apply_widgets(project)
        self._update_map_image()

        def finish():
            manifest_path = os.path.join(project.params.out_dir, "manifest.json")
            if project.params.out_dir and os.path.isfile(manifest_path):
                if self.hm is not None:
                    try:
                        self._set_manifest(load_manifest(manifest_path))
                    except (OSError, ValueError) as exc:
                        QMessageBox.warning(self, APP_NAME, str(exc))
                else:
                    self._load_manifest(manifest_path)
                self._apply_widgets(project)  # the manifest may describe an older build
            known = {t["id"]: (t["ix"], t["iy"]) for t in self.manifest["tiles"]} if self.manifest else {}
            self.map.selection = {known[i] for i in project.selection if i in known}
            self.map.update()
            self._selection_changed()
            self._loading = False
            self._dirty = False
            self._update_title()
            self._set_busy(self._is_busy())
            self._check_changes()
            self.status.setText(f"Opened {project.name}")

        if self._source_path and os.path.isfile(self._source_path):
            self._after_source = finish
            self._load_source(self._source_path, self._raw_size)
        else:
            finish()

    def _apply_widgets(self, project: Project) -> None:
        params, export = project.params, project.export
        self.spacing.setValue(params.spacing_m)
        self.height_min.setValue(params.height_min_m)
        self.height_max.setValue(params.height_max_m)
        self.remap.setChecked(params.remap_float)
        self.origin.setCurrentIndex(max(0, self.origin.findData(params.origin)))
        index = self.tile_cells.findData(params.tile_cells)
        if index < 0:
            self.tile_cells.addItem(f"{params.tile_cells} cells", params.tile_cells)
            index = self.tile_cells.count() - 1
        self.tile_cells.setCurrentIndex(index)
        self.lods.setText(", ".join(f"{e:g}" for e in params.max_errors_m))
        self.texture_error.setValue(params.texture_error)
        self.texture_detail.setValue(params.texture_detail_m)
        self.collision_error.setValue(params.collision_max_error_m)
        self.collision_boundary_edge.setValue(params.collision_boundary_max_edge_m)
        self.collision_triangles.setValue(params.collision_max_triangles_per_tile)
        self.out_dir.setText(params.out_dir)
        self.threads.setValue(params.threads)
        self.material_panel.set_material(project.material)
        self.external_control_map_path.blockSignals(True)
        self.external_control_map_path.setText(project.material.external_control_map_path)
        self.external_control_map_path.blockSignals(False)
        self._refresh_external_control_map_channels(project.material)
        self._material_changed()
        self.export_dir.setText(export.out_dir)
        self.lod_distance.setValue(export.lod_distance_m)
        self.control_map_resolution.setValue(export.control_map_resolution)
        self.embed.setChecked(export.embed_textures)
        self.validate.setChecked(export.validate)
        self.convert_gpu_sources.setChecked(export.convert_gpu_sources)
        policy_index = self.palette_conflict_policy.findData(export.palette_conflict_policy)
        if policy_index < 0:
            self.palette_conflict_policy.addItem(f"Unsupported: {export.palette_conflict_policy}",
                                                 export.palette_conflict_policy)
            policy_index = self.palette_conflict_policy.count() - 1
        self.palette_conflict_policy.setCurrentIndex(policy_index)
        for combo, value in ((self.gpu_container, export.gpu_container),
                             (self.gpu_encoding, export.gpu_encoding)):
            index = combo.findData(value)
            if index < 0:
                combo.addItem(f"Unsupported: {value}", value)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
        self.viewer.set_material(project.material)
        self._scale_changed()
