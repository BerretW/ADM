"""Material tab: the surface library (texture sets) and the biomes that blend them."""

from __future__ import annotations

import io
import math
import os

import numpy as np
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QMessageBox, QPushButton, QSlider, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..bake import _linear_to_srgb, _srgb_to_linear
from ..material import (CHANNELS, IMAGE_FILTER, MAX_BIOMES, MAX_SURFACES, SURFACES_PER_BIOME, Band, Biome,
                        BiomeSurface, MapSlot, Surface, TerrainMaterial, _eight_bit, normal_preview_array,
                        prepare_texture)
from ..material_set_import import apply_material_sets
from .material_set_import import MaterialSetImportDialog

THUMB = 40


def _mesh_with_tangents(mesh, pv):
    from vtkmodules.vtkFiltersCore import vtkPolyDataTangents

    mesh = mesh.triangulate()
    tangents = vtkPolyDataTangents()
    tangents.SetInputData(mesh)
    tangents.Update()
    return pv.wrap(tangents.GetOutput())


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


class MaterialPreview(QWidget):
    """Interactive 3D preview of a single surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import pyvista as pv
        from pyvistaqt import QtInteractor

        self._pv = pv
        self._surface = None
        self._actor = None
        self.mode = QComboBox()
        self.mode.addItems(("Sphere", "Plane", "Terrain relief"))
        self.map_mode = QComboBox()
        self.map_mode.addItem("Material", "material")
        for label in ("Albedo", "Normal", "AO", "Roughness", "Metallic", "Height", "Emission"):
            self.map_mode.addItem(label, label.lower())
        self.reset = QPushButton("Reset view")
        self.scale_info = QLabel()
        self.scale_info.setWordWrap(True)
        self.status = QLabel("Preview shows albedo, tint and scalar metallic/roughness. "
                             "AO, height, emission, normal and parallax maps are not rendered.")
        self.status.setWordWrap(True)
        self.plotter = QtInteractor(self)
        self.plotter.set_background("#15181c", top="#3b4652")
        self.plotter.enable_trackball_style()
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Surface preview"))
        bar.addWidget(self.mode)
        bar.addWidget(self.map_mode)
        bar.addWidget(self.reset)
        bar.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.scale_info)
        layout.addWidget(self.plotter.interactor, 1)
        layout.addWidget(self.status)
        self.mode.currentIndexChanged.connect(self._shape_changed)
        self.map_mode.currentIndexChanged.connect(self._map_changed)
        self.reset.clicked.connect(self.plotter.reset_camera)

    def _mesh(self):
        pv = self._pv
        if self.mode.currentIndex() == 0:
            return pv.Sphere(theta_resolution=96, phi_resolution=64).texture_map_to_sphere(inplace=False)
        if self.mode.currentIndex() == 1:
            return pv.Plane(i_size=15, j_size=15, i_resolution=32, j_resolution=32)
        u, v = np.meshgrid(np.linspace(-1, 1, 100), np.linspace(-1, 1, 100))
        x, y = u * 7.5, v * 7.5
        z = 7.5 * (0.32 * np.exp(-((u + 0.3) ** 2 + (v - 0.25) ** 2) * 5)
                   + 0.24 * np.exp(-((u - 0.4) ** 2 + (v + 0.3) ** 2) * 9)
                   + 0.04 * np.sin(u * 12) * np.cos(v * 10))
        mesh = pv.StructuredGrid(x, y, z).extract_surface().triangulate()
        mesh.active_texture_coordinates = (mesh.points[:, :2] + 7.5) / 15
        return mesh

    def _shape_changed(self) -> None:
        self._redraw(reset=True)

    def _map_changed(self) -> None:
        self._redraw()

    def set_surface(self, surface: Surface) -> None:
        self._surface = surface
        self._redraw(reset=self._actor is None)

    @staticmethod
    def _image_array(path):
        from PIL import Image

        prepared = prepare_texture(path)
        with Image.open(io.BytesIO(prepared.data)) as image:
            return np.array(_eight_bit(image).convert("RGBA"))

    @staticmethod
    def _tint_albedo(rgb, color):
        linear = _srgb_to_linear(np.asarray(rgb, dtype=np.float32) / 255.0)
        tint = _srgb_to_linear(np.asarray(color, dtype=np.float32) / 255.0)
        return np.clip(_linear_to_srgb(linear * tint) * 255.0 + 0.5, 0, 255).astype(np.uint8)

    @classmethod
    def _scalar_preview(cls, slot: MapSlot, size: tuple[int, int] | None, factor: float = 1.0,
                        bias: float = 0.0):
        from PIL import Image

        if not slot.path:
            return None
        image = cls._image_array(slot.path)
        if size is None:
            size = (image.shape[1], image.shape[0])
        channel = image[..., slot.channel].astype(np.float32) / 255.0
        if slot.invert:
            channel = 1.0 - channel
        channel = np.clip(channel * factor + bias, 0.0, 1.0)
        scalar = Image.fromarray(np.rint(channel * 255).astype(np.uint8))
        if scalar.size != size:
            scalar = scalar.resize(size, Image.Resampling.BILINEAR)
        values = np.asarray(scalar)
        return np.repeat(values[..., None], 3, axis=2)

    def _pbr_maps(self, surface):
        from PIL import Image

        candidates = [surface.albedo, surface.normal, surface.ao_map.path,
                      surface.roughness_map.path, surface.metallic_map.path, surface.emission]
        dimensions = []
        for path in candidates:
            if path:
                try:
                    prepared = prepare_texture(path)
                except (OSError, ValueError):
                    continue
                dimensions.append((prepared.width, prepared.height))
        width, height = max(dimensions, key=lambda size: size[0] * size[1]) if dimensions else (4, 4)
        scale = min(1.0, 1024.0 / max(width, height))
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        ao = self._scalar_preview(surface.ao_map, size, surface.ao_strength, 1.0 - surface.ao_strength)
        roughness = self._scalar_preview(surface.roughness_map, size)
        metallic = self._scalar_preview(surface.metallic_map, size)
        if any(value is not None for value in (ao, roughness, metallic)):
            ao = np.full((size[1], size[0], 3), 255, np.uint8) if ao is None else ao
            roughness = (np.full((size[1], size[0], 3), 255, np.uint8)
                         if roughness is None else roughness)
            metallic = (np.full((size[1], size[0], 3), 255, np.uint8)
                        if metallic is None else metallic)
            packed = np.stack((ao[..., 0], roughness[..., 0], metallic[..., 0], np.full(
                (size[1], size[0]), 255, np.uint8)), axis=-1)
            orm = self._pv.numpy_to_texture(packed)
            orm.repeat = True
        else:
            orm = None
        normal = self._pv.numpy_to_texture(normal_preview_array(surface.normal)) if surface.normal else None
        emission = self._pv.numpy_to_texture(self._image_array(surface.emission)) if surface.emission else None
        if normal is not None:
            normal.repeat = True
        if emission is not None:
            emission.repeat = True
            emission.SetUseSRGBColorSpace(True)
        return orm, normal, emission

    def _map_texture(self, surface, name):
        slot = {
            "ao": surface.ao_map,
            "roughness": surface.roughness_map,
            "metallic": surface.metallic_map,
        }.get(name)
        if name == "albedo":
            path = surface.albedo
            image = self._image_array(path) if path else None
            if image is not None:
                image = self._tint_albedo(image[..., :3], surface.color)
        elif name == "normal":
            path, image = surface.normal, normal_preview_array(surface.normal) if surface.normal else None
        elif name == "height":
            slot = surface.height_map
            path = slot.path
            image = self._scalar_preview(slot, None, surface.height_scale, surface.height_bias) \
                if path else None
        elif name == "emission":
            path, image = surface.emission, self._image_array(surface.emission) if surface.emission else None
        else:
            path = slot.path if slot else ""
            factor = surface.ao_strength if name == "ao" else (
                surface.roughness if name == "roughness" else surface.metallic)
            bias = 1.0 - factor if name == "ao" else 0.0
            image = self._scalar_preview(slot, (1024, 1024), factor, bias) if path else None
        if image is None:
            return None
        texture = self._pv.numpy_to_texture(image)
        texture.repeat = True
        texture.SetUseSRGBColorSpace(True)
        return texture

    def _redraw(self, reset: bool = False) -> None:
        if self._surface is None:
            return
        surface = self._surface
        texture = None
        orm_texture = normal_texture = emission_texture = None
        error = ""
        repeat = surface.repeat_m
        self.scale_info.setText(f"Sphere: 1 m diameter | Plane and relief: 15 × 15 m | Repeat: {repeat:g} m")
        if not math.isfinite(repeat) or repeat <= 0:
            error = f"Surface '{surface.name}': texture repeat must be positive and finite."
        map_mode = self.map_mode.currentData()
        if map_mode == "material":
            if surface.albedo:
                try:
                    from PIL import Image

                    prepared = prepare_texture(surface.albedo)
                    with Image.open(io.BytesIO(prepared.data)) as image:
                        rgb = image.convert("RGB")
                        rgb.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                        texture = self._pv.numpy_to_texture(self._tint_albedo(rgb, surface.color))
                        texture.repeat = True
                        texture.SetUseSRGBColorSpace(True)
                except (OSError, ValueError) as exc:
                    error = f"Could not load albedo: {exc}"
            try:
                orm_texture, normal_texture, emission_texture = self._pbr_maps(surface)
            except (OSError, ValueError) as exc:
                error = error or f"Could not load material map: {exc}"
        else:
            try:
                texture = self._map_texture(surface, map_mode)
            except (OSError, ValueError) as exc:
                error = f"Could not load {map_mode} map: {exc}"
            if texture is None:
                error = error or f"No {map_mode} map is assigned to this surface."
        if self._actor is not None:
            self.plotter.remove_actor(self._actor, reset_camera=False, render=False)
        mesh = self._mesh()
        if math.isfinite(repeat) and repeat > 0:
            scale = (math.pi / repeat, math.pi / (2 * repeat)) if self.mode.currentIndex() == 0 else (
                15 / repeat, 15 / repeat)
            mesh.active_texture_coordinates *= scale
        if normal_texture is not None:
            mesh = _mesh_with_tangents(mesh, self._pv)
        self._actor = self.plotter.add_mesh(
            mesh, texture=texture, color="white" if texture else tuple(c / 255 for c in surface.color),
            pbr=map_mode == "material", metallic=surface.metallic, roughness=surface.roughness,
            reset_camera=False, render=False)
        if texture is not None:
            self._actor.prop.SetTexture("albedoTex", texture)
        if map_mode == "material":
            if orm_texture is not None:
                self._actor.prop.SetORMTexture(orm_texture)
            if normal_texture is not None:
                self._actor.prop.SetNormalTexture(normal_texture)
            if emission_texture is not None:
                self._actor.prop.SetEmissiveTexture(emission_texture)
                self._actor.prop.SetEmissiveFactor(1.0, 1.0, 1.0)
        self.status.setText(error or "Drag to rotate, middle-drag to pan, wheel to zoom. "
                            "Material mode applies supported maps; Height is a diagnostic view. "
                            "Parallax/POM and layer blending are not rendered.")
        if reset:
            self.plotter.camera_position = "iso"
            self.plotter.reset_camera()
        self.plotter.render()

    def shutdown(self) -> None:
        self.plotter.close()


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
    large_preview_requested = Signal()
    height_blend_preview_requested = Signal()

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
        self.ao = MapRow("Ambient occlusion")
        self.height = MapRow("Height")
        self.height.factor.setRange(0.0, 1000.0)
        self.height.factor.setDecimals(4)
        self.height.factor.setToolTip("Height range used when blending or parallax is enabled")
        self.height_bias = QDoubleSpinBox()
        self.height_bias.setRange(-1.0, 1.0)
        self.height_bias.setDecimals(4)
        self.height_bias.setSingleStep(0.01)
        self.height_bias.setToolTip("Offset applied to the selected height channel")
        self.parallax_scale = QDoubleSpinBox()
        self.parallax_scale.setRange(0.0, 1.0)
        self.parallax_scale.setDecimals(4)
        self.parallax_scale.setSingleStep(0.005)
        self.parallax_scale.setSuffix(" m")
        self.parallax_scale.setToolTip("Maximum apparent depth for this surface")
        self.emission = TexturePicker("Emission texture")
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
        form.addRow("Ambient occlusion", self.ao)
        form.addRow("Height", self.height)
        form.addRow("Height offset", self.height_bias)
        form.addRow("Parallax depth", self.parallax_scale)
        form.addRow("Emission", self.emission)
        form.addRow("Normal", self.normal)
        self.show_terrain = QPushButton("Show blended terrain")
        self.show_terrain.setToolTip("Open the 3D terrain preview with the current biome blending")
        self.show_preview = QPushButton("Show large preview")
        self.show_blend_preview = QPushButton("Compare surface blending")
        self.show_blend_preview.setToolTip("Compare ordinary layer weights with height-based blending")
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self.show_preview)
        row.addWidget(self.show_blend_preview)
        row.addWidget(self.show_terrain)
        layout.addLayout(row)
        for widget in (self.tint, self.albedo, self.metallic, self.roughness, self.ao, self.height,
                       self.emission, self.normal):
            widget.changed.connect(self.changed)
        for widget in (self.repeat, self.height_bias, self.parallax_scale):
            widget.valueChanged.connect(self.changed)
        self.show_terrain.clicked.connect(self.terrain_requested)
        self.show_preview.clicked.connect(self.large_preview_requested)
        self.show_blend_preview.clicked.connect(self.height_blend_preview_requested)

    def set_surface(self, surface: Surface) -> None:
        self.setTitle(f"Surface: {surface.name}")
        self.tint.set_rgb(surface.color)
        self.albedo.set_path(surface.albedo)
        self.repeat.setValue(surface.repeat_m)
        self.metallic.set_values(surface.metallic, surface.metallic_map)
        self.roughness.set_values(surface.roughness, surface.roughness_map)
        self.ao.set_values(surface.ao_strength, surface.ao_map)
        self.height.set_values(surface.height_scale, surface.height_map)
        self.height_bias.setValue(surface.height_bias)
        self.parallax_scale.setValue(surface.parallax_scale)
        self.emission.set_path(surface.emission)
        self.normal.set_path(surface.normal)

    def apply(self, surface: Surface) -> None:
        surface.color = self.tint.rgb()
        surface.albedo = self.albedo.path()
        surface.repeat_m = self.repeat.value()
        surface.metallic, surface.metallic_map = self.metallic.values()
        surface.roughness, surface.roughness_map = self.roughness.values()
        surface.ao_strength, surface.ao_map = self.ao.values()
        surface.height_scale, surface.height_map = self.height.values()
        surface.height_bias = self.height_bias.value()
        surface.parallax_scale = self.parallax_scale.value()
        surface.emission = self.emission.path()
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
        self.noise = QSlider(Qt.Orientation.Horizontal)
        self._noise_edited = False
        self.noise.setRange(0, 100)
        self.noise.setToolTip("Blend this biome's surfaces with smooth 20 m variation. "
                              "At least two surfaces are required; noise can add surfaces outside their bands.")
        self.noise_value = QLabel("0%")
        self.noise_hint = QLabel()
        self.noise_hint.setWordWrap(True)
        self.noise_hint.setStyleSheet("color: #9aa3ad")
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
        noise_row = QHBoxLayout()
        noise_row.addWidget(self.noise, 1)
        noise_row.addWidget(self.noise_value)
        form.addRow("Surface noise", noise_row)
        form.addRow(self.noise_hint)
        layout.addLayout(form)
        for row_widget in self.rows:
            layout.addWidget(row_widget)
            row_widget.changed.connect(self.changed)
        self.color.changed.connect(self.changed)
        self.auto.toggled.connect(self._auto_toggled)
        self.height.changed.connect(self.changed)
        self.slope.changed.connect(self.changed)
        self.noise.valueChanged.connect(self._noise_changed)

    def _noise_changed(self, value: int) -> None:
        self.noise_value.setText(f"{value}%")
        self._noise_edited = True
        self.changed.emit()

    def _noise_hint(self, biome: Biome) -> None:
        self.noise_hint.setText("Add another surface to use noise." if len(biome.surfaces) < 2 else
                                "Noise mixes biome surfaces, including outside their height and slope bands.")

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
        self.noise.blockSignals(True)
        self.noise.setValue(round(biome.noise * 100))
        self.noise.blockSignals(False)
        self._noise_edited = False
        self.noise_value.setText(f"{self.noise.value()}%")
        self._noise_hint(biome)
        self.height.setEnabled(biome.auto)
        self.slope.setEnabled(biome.auto)
        for i, row in enumerate(self.rows):
            row.set_entry(biome.surfaces[i] if i < len(biome.surfaces) else None, names, i > 0)

    def apply(self, biome: Biome) -> None:
        biome.color = self.color.rgb()
        biome.auto = self.auto.isChecked()
        biome.height = self.height.band()
        biome.slope = self.slope.band()
        if self._noise_edited:
            biome.noise = self.noise.value() / 100.0
            self._noise_edited = False
        entries = [entry for entry in (row.entry() for row in self.rows) if entry is not None]
        if entries:
            biome.surfaces = entries
        self._noise_hint(biome)


class MaterialPanel(QWidget):
    """Edits a :class:`TerrainMaterial` in place; ``changed`` fires after every edit."""

    changed = Signal()
    surface_selected = Signal(object)
    surface_preview_requested = Signal()
    height_blend_preview_requested = Signal()
    fit_requested = Signal()
    terrain_preview_requested = Signal()
    terrain_setup_requested = Signal()
    save_preset_requested = Signal()
    load_preset_requested = Signal()

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
        self.import_surface_sets = QPushButton("Import sets…")
        for i, button in enumerate((self.add_surface, self.rename_surface, self.remove_surface,
                                    self.import_surface_sets)):
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

        # Terrain blending and shader effects
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
        self.terrain_setup = QPushButton("Terrain setup wizard…")
        self.terrain_setup.setToolTip("Choose a terrain type, tune biome thresholds and assign surface textures")
        self.save_preset = QPushButton("Save preset…")
        self.load_preset = QPushButton("Load preset…")
        self.fit = QPushButton("Fit biome heights to the heightmap")
        self.fit.setToolTip("Place water, shore and snow levels of the default biomes from the height distribution")
        form.addRow("Slope radius", self.slope_radius)
        form.addRow("Paint softness", self.paint_softness)
        form.addRow(self.double_sided)
        form.addRow(self.terrain_setup)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.save_preset)
        preset_row.addWidget(self.load_preset)
        form.addRow(preset_row)
        form.addRow(self.fit)

        effects = QGroupBox("Terrain shader settings")
        effects_form = QFormLayout(effects)
        self.terrain_shader_version = QComboBox()
        self.terrain_shader_version.addItem("Legacy layered profile (2.0.0)", "2.0.0")
        self.terrain_shader_version.addItem("AO, height and parallax profile (2.1.0)", "2.1.0")
        self.terrain_shader_version.setToolTip(
            "Choose 2.1.0 explicitly to export AO, height blending, emission maps or parallax settings")
        self.height_blend = QCheckBox("Blend surfaces by height")
        self.height_blend.setToolTip("Use height maps to choose the visible surface at layer transitions")
        self.height_blend_transition = QDoubleSpinBox()
        self.height_blend_transition.setRange(0.001, 1.0)
        self.height_blend_transition.setDecimals(4)
        self.height_blend_transition.setSingleStep(0.01)
        self.height_blend_transition.setToolTip("Width of the height blend transition")
        self.height_blend_strength = QDoubleSpinBox()
        self.height_blend_strength.setRange(0.0, 1.0)
        self.height_blend_strength.setDecimals(2)
        self.height_blend_strength.setSingleStep(0.05)
        self.parallax_mode = QComboBox()
        self.parallax_mode.addItem("Off", "NONE")
        self.parallax_mode.addItem("Parallax", "PARALLAX")
        self.parallax_mode.addItem("Parallax occlusion", "PARALLAX_OCCLUSION")
        self.parallax_min_steps = QSpinBox()
        self.parallax_min_steps.setRange(1, 256)
        self.parallax_max_steps = QSpinBox()
        self.parallax_max_steps.setRange(1, 256)
        self.parallax_min_steps.setToolTip("Minimum parallax-occlusion ray-march steps")
        self.parallax_max_steps.setToolTip("Maximum parallax-occlusion ray-march steps")
        effects_form.addRow("Terrain shader profile", self.terrain_shader_version)
        effects_form.addRow(self.height_blend)
        effects_form.addRow("Transition width", self.height_blend_transition)
        effects_form.addRow("Blend strength", self.height_blend_strength)
        effects_form.addRow("Parallax mode", self.parallax_mode)
        effects_form.addRow("POM minimum steps", self.parallax_min_steps)
        effects_form.addRow("POM maximum steps", self.parallax_max_steps)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.warnings)
        layout.addWidget(biomes)
        layout.addWidget(surfaces)
        layout.addWidget(blending)
        layout.addWidget(effects)
        layout.addStretch(1)

        self.surface_list.currentRowChanged.connect(self._show_surface)
        self.biome_list.currentRowChanged.connect(self._show_biome)
        self.surface_editor.changed.connect(self._surface_edited)
        self.surface_editor.terrain_requested.connect(self.terrain_preview_requested)
        self.surface_editor.large_preview_requested.connect(self.surface_preview_requested)
        self.surface_editor.height_blend_preview_requested.connect(self.height_blend_preview_requested)
        self.biome_editor.changed.connect(self._biome_edited)
        self.add_surface.clicked.connect(self._add_surface)
        self.import_surface_sets.clicked.connect(self._import_surface_sets)
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
        self.terrain_shader_version.currentIndexChanged.connect(self._global_edited)
        self.height_blend.toggled.connect(self._global_edited)
        for spin in (self.height_blend_transition, self.height_blend_strength,
                     self.parallax_min_steps, self.parallax_max_steps):
            spin.valueChanged.connect(self._global_edited)
        self.parallax_mode.currentIndexChanged.connect(self._global_edited)
        self.fit.clicked.connect(self.fit_requested)
        self.terrain_setup.clicked.connect(self.terrain_setup_requested)
        self.save_preset.clicked.connect(self.save_preset_requested)
        self.load_preset.clicked.connect(self.load_preset_requested)
        self.set_material(self._material)

    # ------------------------------------------------------------ public
    def set_material(self, material: TerrainMaterial) -> None:
        self._material = material
        self._loading = True
        self.slope_radius.setValue(material.slope_radius_m)
        self.paint_softness.setValue(material.paint_softness_m)
        self.double_sided.setChecked(material.double_sided)
        self.terrain_shader_version.setCurrentIndex(
            max(0, self.terrain_shader_version.findData(material.terrain_shader_version)))
        self.height_blend.setChecked(material.height_blend_enabled)
        self.height_blend_transition.setValue(material.height_blend_transition)
        self.height_blend_strength.setValue(material.height_blend_strength)
        self.parallax_mode.setCurrentIndex(
            max(0, self.parallax_mode.findData(material.parallax_mode)))
        self.parallax_min_steps.setValue(material.parallax_min_steps)
        self.parallax_max_steps.setValue(material.parallax_max_steps)
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
        self.surface_selected.emit(self._material.surfaces[row])

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
        self.surface_selected.emit(surface)
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
        self._material.terrain_shader_version = self.terrain_shader_version.currentData()
        self._material.height_blend_enabled = self.height_blend.isChecked()
        self._material.height_blend_transition = self.height_blend_transition.value()
        self._material.height_blend_strength = self.height_blend_strength.value()
        self._material.parallax_mode = self.parallax_mode.currentData()
        self._material.parallax_min_steps = self.parallax_min_steps.value()
        self._material.parallax_max_steps = self.parallax_max_steps.value()
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

    def _import_surface_sets(self) -> None:
        settings = QSettings()
        directory = QFileDialog.getExistingDirectory(
            self, "Import material sets from directory", settings.value("last_texture_dir", ""))
        if not directory:
            return
        settings.setValue("last_texture_dir", directory)
        dialog = MaterialSetImportDialog(directory, self._material, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.scan is None:
            QMessageBox.warning(self, "Import material sets", "The directory scan is no longer available.")
            return
        try:
            result = apply_material_sets(
                self._material, dialog.scan, dialog.selected_names, dialog.conflict_choices,
                dialog.update_existing)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Import material sets", str(error))
            return
        if not result["added"] and not result["updated"]:
            return
        self._refresh_lists(self.surface_list.currentRow(), self.biome_list.currentRow())
        self._emit()
        QMessageBox.information(
            self, "Import material sets",
            f"Added {result['added']} surfaces; updated {result['updated']}; "
            f"preserved {result['skipped']} existing surfaces.")

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
        if any(road.surface == name for road in self._material.roads):
            QMessageBox.warning(self, "Remove surface", f"'{name}' is used by a road. Change the road surface first.")
            return
        paint = self._material.surface_paint
        painted = paint is not None and bool((paint == row).any())
        impacts = []
        if users:
            impacts.append(f"remove it from {', '.join(users)}")
        if painted:
            impacts.append("clear its surface paint")
        if impacts and QMessageBox.question(self, "Remove surface",
                                           f"Removing '{name}' will {' and '.join(impacts)}. Continue?") \
                != QMessageBox.StandardButton.Yes:
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
