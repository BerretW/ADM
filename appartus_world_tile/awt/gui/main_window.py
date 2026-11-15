"""Main window: parameters on the left, map and 3D preview on the right."""

from __future__ import annotations

import os
import time

import numpy as np
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from ..adm_export import Cancelled as ExportCancelled
from ..adm_export import ExportSettings, changed_tiles, export_tiles
from ..heightmap import Heightmap, load_heightmap, preview
from ..masks import LAYERS, ZoneRules, zones_preview
from ..pipeline import (BuildParams, Cancelled, build, estimate_memory, height_transform, hillshade,
                        load_manifest, suggest_zones, tile_grid)
from ..project import PROJECT_EXTENSION, PROJECT_FILTER, Project, load_project
from .map_view import MapView
from .material_panel import MaterialPanel
from .viewer3d import TRIANGLE_BUDGET, Viewer3D, triangle_count

HEIGHTMAP_FILTER = "Heightmaps (*.png *.tif *.tiff *.r16 *.raw *.npy *.pgm);;All files (*)"
MAP_MODES = ("Relief", "Zones", "Mesh density")
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


class HeightHistogram(QWidget):
    """Height distribution with the water and snow thresholds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self._counts = None
        self._range = (0.0, 1.0)
        self._rules = ZoneRules()

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

    def set_rules(self, rules: ZoneRules) -> None:
        self._rules = rules
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(26, 29, 34))
        if self._counts is None:
            painter.setPen(QColor(110, 116, 125))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Height histogram appears with a heightmap")
            return
        lo, hi = self._range
        w, h = self.width(), self.height() - 2
        peak = float(self._counts.max()) or 1.0
        n = len(self._counts)
        rules = self._rules
        colors = {layer["name"]: QColor(*layer["color"]) for layer in LAYERS}
        for i, value in enumerate(self._counts):
            height = lo + (i + 0.5) / n * (hi - lo)
            if rules.water and height <= rules.water_level_m + rules.shore_m * 0.5:
                color = colors["water"]
            elif rules.snow and height >= (rules.snow_start_m + rules.snow_full_m) / 2:
                color = colors["snow"]
            else:
                color = colors["ground"]
            x0 = int(i * w / n)
            x1 = int((i + 1) * w / n)
            bar = int(value / peak * h)
            painter.fillRect(x0, h - bar + 1, max(1, x1 - x0 - 1), bar, color)

        def mark(value, color, style=Qt.PenStyle.SolidLine):
            if lo <= value <= hi:
                x = (value - lo) / (hi - lo) * w
                painter.setPen(QPen(color, 1, style))
                painter.drawLine(int(x), 0, int(x), h)

        if rules.water:
            mark(rules.water_level_m, QColor(110, 180, 255))
            mark(rules.water_level_m + rules.shore_m, QColor(110, 180, 255), Qt.PenStyle.DashLine)
        if rules.snow:
            mark(rules.snow_start_m, QColor(255, 255, 255), Qt.PenStyle.DashLine)
            mark(rules.snow_full_m, QColor(255, 255, 255))
        painter.setPen(QColor(150, 158, 168))
        painter.drawText(4, 12, f"{lo:.0f} m")
        text = f"{hi:.0f} m"
        painter.drawText(w - painter.fontMetrics().horizontalAdvance(text) - 4, 12, text)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1500, 920)
        self.settings = QSettings()
        self.hm: Heightmap | None = None
        self.manifest: dict | None = None
        self._preview: np.ndarray | None = None  # strided heightmap samples
        self._relief: np.ndarray | None = None
        self._zones_image: np.ndarray | None = None
        self._worker: Worker | None = None
        self._build_started = 0.0
        self._source_path = ""
        self._raw_size: tuple[int, int] | None = None
        self.project_path = ""
        self._dirty = False
        self._loading = False
        self._after_source = None  # callback once a heightmap has loaded
        self._check_generation = 0
        self._checker: _ChangeCheck | None = None
        self._changed_ids: list[str] | None = None
        self._check_pending = False

        self._make_widgets()
        self._make_menu()
        self._zones_timer = QTimer(self, singleShot=True, interval=200)
        self._zones_timer.timeout.connect(self._refresh_zones)
        self._check_timer = QTimer(self, singleShot=True, interval=400)
        self._check_timer.timeout.connect(self._check_changes)
        self._material_timer = QTimer(self, singleShot=True, interval=300)
        self._material_timer.timeout.connect(lambda: self.viewer.set_material(self.material_panel.material()))
        self._connect()
        self._update_tile_info()
        self._set_busy(False)
        self.viewer.set_material(self.material_panel.material())
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

        # Masks and zones
        self.masks = QCheckBox("Write TERRAIN_4 blend mask per tile")
        self.masks.setChecked(True)
        self.mask_px = QSpinBox()
        self.mask_px.setRange(0, 8192)
        self.mask_px.setSpecialValueText("Same as tile cells")
        self.mask_px.setSuffix(" px")
        self.water = QCheckBox("Water (A)")
        self.water.setChecked(True)
        self.water_level = _spin(-20000, 20000, 0.0, 1, 2, " m")
        self.shore = _spin(0, 5000, 2.0, 0.5, 2, " m")
        self.snow = QCheckBox("Snow (B)")
        self.snow.setChecked(True)
        self.snow_start = _spin(-20000, 20000, 400.0, 10, 1, " m")
        self.snow_full = _spin(-20000, 20000, 450.0, 10, 1, " m")
        self.snow_slope = _spin(0, 90, 55.0, 1, 1, "°")
        self.rock_start = _spin(0, 90, 30.0, 1, 1, "°")
        self.rock_full = _spin(0, 90, 45.0, 1, 1, "°")
        self.auto_zones = QPushButton("Suggest from heights")
        self.histogram = HeightHistogram()

        # Output
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("Folder for built tiles (PLY meshes, masks, manifest)")
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
        self.embed = QCheckBox("Embed layer textures in every tile")
        self.embed.setToolTip("Off: layer textures are written once into textures/ next to the tiles "
                              "(ADM_external_images_v1). Blend masks are always embedded.")
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
        form.addRow("", self.tile_info)
        column.addWidget(group)

        group = QGroupBox("Material zones")
        form = QFormLayout(group)
        form.addRow(self.masks)
        form.addRow("Mask size", self.mask_px)
        form.addRow(self.histogram)
        row = QHBoxLayout()
        row.addWidget(self.water_level)
        row.addWidget(QLabel("shore"))
        row.addWidget(self.shore)
        form.addRow(self.water, row)
        row = QHBoxLayout()
        row.addWidget(self.snow_start)
        row.addWidget(QLabel("to"))
        row.addWidget(self.snow_full)
        form.addRow(self.snow, row)
        form.addRow("Snow up to slope", self.snow_slope)
        row = QHBoxLayout()
        row.addWidget(self.rock_start)
        row.addWidget(QLabel("to"))
        row.addWidget(self.rock_full)
        form.addRow("Rock (G) slope", row)
        form.addRow("", self.auto_zones)
        legend = QLabel("Mask channels: <b style='color:#7fa654'>R ground</b>, "
                        "<b style='color:#a69c92'>G rock</b>, <b style='color:#eef1f6'>B snow</b>, "
                        "<b style='color:#5b9bd5'>A water</b> = TERRAIN_4 layers 0–3")
        legend.setWordWrap(True)
        form.addRow(legend)
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
        form.addRow(self.embed)
        form.addRow(self.validate)
        note = QLabel("Each tile becomes <tile>.adm with its LODs and blend mask, placed at its world "
                      "position. world.json remembers what was exported, so Export changed writes only "
                      "tiles whose terrain, mask, material or settings differ.")
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
        self.map_hint.setStyleSheet("color: #9aa3ad")
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
        layout.addWidget(self.map, 1)
        layout.addWidget(self.map_hint)

        self.viewer = Viewer3D()
        self.tabs = QTabWidget()
        self.tabs.addTab(map_tab, "Map")
        self.tabs.addTab(self.viewer, "3D")

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
        self.mask_px.valueChanged.connect(self._update_tile_info)
        for widget in (self.water_level, self.shore, self.snow_start, self.snow_full, self.snow_slope,
                       self.rock_start, self.rock_full):
            widget.valueChanged.connect(self._zones_changed)
        for widget in (self.water, self.snow, self.masks):
            widget.toggled.connect(self._zones_changed)
        self.auto_zones.clicked.connect(self._suggest_zones)
        self.build_button.clicked.connect(self._start_build)
        self.cancel_button.clicked.connect(self._cancel)
        self.map_mode.currentIndexChanged.connect(self._update_map_image)
        self.select_all.clicked.connect(self.map.select_all)
        self.show_3d.clicked.connect(self._show_selection)
        self.map.tileActivated.connect(lambda ix, iy: self._show_tiles({(ix, iy)}, 0))
        self.map.selectionChanged.connect(self._selection_changed)

        self.browse_export.clicked.connect(self._choose_export)
        self.export_changed.clicked.connect(lambda: self._start_export("changed"))
        self.export_selected.clicked.connect(lambda: self._start_export("selected"))
        self.export_all.clicked.connect(lambda: self._start_export("all"))
        self.material_panel.changed.connect(self._material_timer.start)
        for signal in (self.material_panel.changed, self.export_dir.textChanged, self.lod_distance.valueChanged,
                       self.embed.toggled):
            signal.connect(self._schedule_check)

        # Anything stored in the project marks it modified; the tile selection does not.
        for box in (self.spacing, self.height_min, self.height_max, self.mask_px, self.threads, self.water_level,
                    self.shore, self.snow_start, self.snow_full, self.snow_slope, self.rock_start, self.rock_full,
                    self.lod_distance):
            box.valueChanged.connect(self._mark_dirty)
        for box in (self.remap, self.masks, self.water, self.snow, self.embed, self.validate):
            box.toggled.connect(self._mark_dirty)
        for edit in (self.lods, self.out_dir, self.export_dir):
            edit.textChanged.connect(self._mark_dirty)
        for combo in (self.origin, self.tile_cells):
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
            masks=self.masks.isChecked(),
            mask_px=self.mask_px.value(),
            zones=self._rules(),
            raw_size=self._raw_size,
        )

    def _export_settings(self) -> ExportSettings:
        return ExportSettings(out_dir=self.export_dir.text().strip(), lod_distance_m=self.lod_distance.value(),
                              embed_textures=self.embed.isChecked(), validate=self.validate.isChecked(),
                              threads=self.threads.value())

    def _rules(self) -> ZoneRules:
        return ZoneRules(
            water=self.water.isChecked(), water_level_m=self.water_level.value(), shore_m=self.shore.value(),
            snow=self.snow.isChecked(), snow_start_m=self.snow_start.value(),
            snow_full_m=self.snow_full.value(), rock_start_deg=self.rock_start.value(),
            rock_full_deg=self.rock_full.value(), snow_max_slope_deg=self.snow_slope.value(),
        )

    def _set_rules(self, rules: ZoneRules) -> None:
        widgets = (self.water, self.water_level, self.shore, self.snow, self.snow_start, self.snow_full,
                   self.rock_start, self.rock_full, self.snow_slope)
        for widget in widgets:
            widget.blockSignals(True)
        self.water.setChecked(rules.water)
        self.water_level.setValue(rules.water_level_m)
        self.shore.setValue(rules.shore_m)
        self.snow.setChecked(rules.snow)
        self.snow_start.setValue(rules.snow_start_m)
        self.snow_full.setValue(rules.snow_full_m)
        self.rock_start.setValue(rules.rock_start_deg)
        self.rock_full.setValue(rules.rock_full_deg)
        self.snow_slope.setValue(rules.snow_max_slope_deg)
        for widget in widgets:
            widget.blockSignals(False)
        self._zones_changed()

    def _transform(self) -> tuple[float, float]:
        return height_transform(self.hm, self._params_safe())

    def _source_shape(self) -> tuple[int, int]:
        if self.hm is not None:
            return self.hm.width, self.hm.height
        if self.manifest is not None:
            return self.manifest["source"]["width"], self.manifest["source"]["height"]
        return 0, 0

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.browse_source, self.open_manifest, self.auto_zones, self.heightmap_action,
                       self.tiles_action):
            widget.setEnabled(not busy)
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

    def _load_source(self, path: str, raw_size: tuple[int, int] | None = None) -> None:
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
        self._scale_changed()
        if callback is None:
            self._suggest_zones()
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
        self._source_path = manifest["source"]["path"]
        self.source.setText(manifest["source"]["path"])
        self.source_info.setText(f"Tiles from {manifest['_dir']} (heightmap not loaded, "
                                 "open it to change zones or rebuild)")
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
        self._set_rules(ZoneRules.from_dict(manifest.get("zones", {})))
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
            self._zones_image = None
            self._update_map_image()
        self._update_tile_info()

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
            text += f", about {memory / 2**30:.2f} GiB working memory"
        if self.masks.isChecked():
            px = self.mask_px.value() or max(16, min(2048, cells))
            text += f"\nMask {px} px per tile = {cells * sp / px:.2f} m per mask pixel"
        self.tile_info.setText(text)
        if self.manifest is not None and self.manifest["tile_cells"] != cells:
            self.map.set_stats({}, {})

    def _zones_changed(self) -> None:
        rules = self._rules()
        self.histogram.set_rules(rules)
        self._zones_image = None
        if self.map_mode.currentIndex() == 1:
            self._zones_timer.start()
        self._update_tile_info()

    def _suggest_zones(self) -> None:
        if self.hm is None:
            return
        self._set_rules(suggest_zones(self.hm, self._params_safe()))

    def _params_safe(self) -> BuildParams:
        return BuildParams(input_path="", out_dir="", height_min_m=self.height_min.value(),
                           height_max_m=self.height_max.value(), remap_float=self.remap.isChecked())

    def _refresh_zones(self) -> None:
        self._zones_image = None
        self._update_map_image()

    def _update_map_image(self) -> None:
        width, height = self._source_shape()
        mode = self.map_mode.currentIndex()
        image = None
        if mode == 1:
            image = self._zones()
        if image is None:
            image = self._relief
        self.map.set_density_visible(mode == 2)
        self.map.set_image(image, width, height)
        self.map.set_grid(self.tile_cells.currentData())

    def _zones(self) -> np.ndarray | None:
        if self._zones_image is not None:
            return self._zones_image
        if self.hm is not None:
            scale, offset = self._transform()
            self._zones_image = zones_preview(self.hm.data, scale, offset, self.spacing.value(), self._rules(),
                                              shade=self._relief)
        elif self.manifest is not None:
            self._zones_image = self._read_rgb(self.manifest.get("zones_preview"))
        return self._zones_image

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
        self._run(lambda progress, cancelled: build(params, progress, cancelled, heightmap=hm),
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
        if manifest.get("mask_layers"):
            lines.append("Masks: masks/<tile>_mask.png, RGBA = ground, rock, snow, water")
        lines.append(f"Output: {manifest['_dir']}")
        self.report.setPlainText("\n".join(lines))

    def _set_manifest(self, manifest: dict) -> None:
        self.manifest = manifest
        if self.hm is None:
            self._relief = self._read_rgb(manifest.get("preview"), "L")
            self._zones_image = None
            self._scale_changed()
        self.viewer.set_manifest(manifest)
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
        if not self._confirm_discard():
            event.ignore()
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        if self._checker is not None:
            self._checker.wait()
        self.viewer.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ export
    def _schedule_check(self) -> None:
        self._check_timer.start()

    def _check_changes(self) -> None:
        settings = self._export_settings()
        if self.manifest is None or not settings.out_dir:
            self._check_generation += 1
            self._changed_ids = None
            self.map.set_marked(set())
            self.export_state.setText("Build or open tiles first" if self.manifest is None
                                      else "Choose a folder for the ADM tiles")
            self._update_export_buttons()
            return
        if self._checker is not None and self._checker.isRunning():
            self._check_pending = True
            return
        self._check_generation += 1
        self.export_state.setText("Checking which tiles changed…")
        self._checker = _ChangeCheck(self._check_generation, self.manifest, self.material_panel.material(),
                                     settings, self)
        self._checker.checked.connect(self._on_checked)
        self._checker.finished.connect(self._checker_finished)
        self._checker.start()

    def _checker_finished(self) -> None:
        if self._check_pending:
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
        material = self.material_panel.material()
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
        self.report.setPlainText(f"Wrote {written:,} tiles ({result['bytes'] / 2**20:,.1f} MiB) in "
                                 f"{result['seconds']:.1f} s, {result['skipped']:,} up to date\n"
                                 f"Folder: {result['out_dir']}\n"
                                 "Import in Blender: File > Import > ADM Model, one .adm per tile.")
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
        return Project(params=self._params(), material=self.material_panel.material(),
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
        self._preview = self._relief = self._zones_image = None
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
        self.masks.setChecked(params.masks)
        self.mask_px.setValue(params.mask_px)
        self._set_rules(params.zones)
        self.out_dir.setText(params.out_dir)
        self.threads.setValue(params.threads)
        self.material_panel.set_material(project.material)
        self.export_dir.setText(export.out_dir)
        self.lod_distance.setValue(export.lod_distance_m)
        self.embed.setChecked(export.embed_textures)
        self.validate.setChecked(export.validate)
        self.viewer.set_material(project.material)
        self._scale_changed()
