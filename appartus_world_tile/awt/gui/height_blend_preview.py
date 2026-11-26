"""Interactive preview for classic and height-based multi-surface blending."""

from __future__ import annotations

import io

import numpy as np
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..material import Surface, TerrainMaterial, prepare_texture


def _read_rgba(path: str) -> np.ndarray:
    from PIL import Image

    prepared = prepare_texture(path)
    with Image.open(io.BytesIO(prepared.data)) as image:
        return np.asarray(image.convert("RGBA"))


def _sample_repeat(image: np.ndarray, repeat_m: float, size: int) -> np.ndarray:
    repeat_m = max(0.01, float(repeat_m))
    coordinates = (np.arange(size, dtype=np.float64) / size * (15.0 / repeat_m)) % 1.0
    xs = np.minimum((coordinates * image.shape[1]).astype(int), image.shape[1] - 1)
    ys = np.minimum((coordinates * image.shape[0]).astype(int), image.shape[0] - 1)
    return image[ys[:, None], xs[None, :]]


def compose_preview(surfaces: list[Surface], base_weights: list[float], *, size: int = 256,
                    height_blend: bool = False, transition: float = 0.2,
                    strength: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Return a preview RGB image and per-pixel final weights for selected surfaces."""
    if not 2 <= len(surfaces) <= 4 or len(base_weights) != len(surfaces):
        raise ValueError("Select two to four surfaces and one base weight per surface")
    if not np.isfinite(transition) or transition <= 0 or not 0 <= strength <= 1:
        raise ValueError("Transition must be positive and strength must be in 0..1")
    weights = np.asarray(base_weights, dtype=np.float64)
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Base weights must be finite and non-negative")
    total = weights.sum()
    if total <= 0:
        raise ValueError("At least one base weight must be positive")
    weights /= total
    base = np.broadcast_to(weights[:, None, None], (len(surfaces), size, size))
    colors = []
    heights = []
    occlusion = []
    for surface in surfaces:
        if surface.albedo:
            color = _sample_repeat(_read_rgba(surface.albedo), surface.repeat_m, size)[..., :3]
            color = color.astype(np.float64) * (np.asarray(surface.color) / 255.0)
        else:
            color = np.broadcast_to(np.asarray(surface.color, dtype=np.float64), (size, size, 3))
        colors.append(color)
        if surface.height_map.path:
            height_rgba = _sample_repeat(_read_rgba(surface.height_map.path), surface.repeat_m, size)
            height = height_rgba[..., surface.height_map.channel].astype(np.float64) / 255.0
            if surface.height_map.invert:
                height = 1.0 - height
            heights.append(np.clip(height * surface.height_scale + surface.height_bias, 0.0, 1.0))
        else:
            heights.append(np.full((size, size), 0.5, dtype=np.float64))
        if surface.ao_map.path:
            ao_rgba = _sample_repeat(_read_rgba(surface.ao_map.path), surface.repeat_m, size)
            ao = ao_rgba[..., surface.ao_map.channel].astype(np.float64) / 255.0
            if surface.ao_map.invert:
                ao = 1.0 - ao
            occlusion.append(1.0 + (ao - 1.0) * surface.ao_strength)
        else:
            occlusion.append(np.ones((size, size), dtype=np.float64))
    final = base.copy()
    if height_blend and strength > 0:
        height_stack = np.stack(heights)
        highest = np.max(np.where(base > 0, height_stack, -np.inf), axis=0)
        delta = np.clip((height_stack - highest[None, ...]) / max(transition, 1e-8), -80.0, 0.0)
        weighted = base * np.exp(delta)
        denominator = weighted.sum(axis=0)
        aware = np.divide(weighted, denominator[None, ...], out=np.zeros_like(weighted),
                          where=denominator[None, ...] > 0)
        final = base * (1.0 - strength) + aware * strength
    color = sum(weight[..., None] * layer for weight, layer in zip(final, colors))
    ao = sum(weight * layer for weight, layer in zip(final, occlusion))
    color *= ao[..., None]
    rgb = np.clip(color + 0.5, 0, 255).astype(np.uint8)
    return rgb, final


class HeightBlendPreview(QDialog):
    """3D comparison of two to four surface weights before and after height blending."""

    def __init__(self, material: TerrainMaterial, parent=None):
        super().__init__(parent)
        import pyvista as pv
        from pyvistaqt import QtInteractor

        self.setWindowTitle("Multi-surface height blend preview")
        self.resize(900, 650)
        self._pv = pv
        self._material = material
        self._actor = None
        self.layer_count = QComboBox()
        for count in range(2, 5):
            self.layer_count.addItem(str(count), count)
        self.enabled = [QCheckBox(f"Layer {i + 1}") for i in range(4)]
        self.enabled[0].setChecked(True)
        self.enabled[1].setChecked(True)
        self.surface = [QComboBox() for _ in range(4)]
        self.weight = [QSlider() for _ in range(4)]
        for slider in self.weight:
            slider.setRange(0, 100)
        self.weight[0].setValue(50)
        self.weight[1].setValue(50)
        self.height_blend = QCheckBox("Height-based blend")
        self.height_blend.setChecked(material.height_blend_enabled)
        self.transition = QDoubleSpinBox()
        self.transition.setRange(0.001, 1.0)
        self.transition.setDecimals(3)
        self.transition.setValue(material.height_blend_transition)
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0.0, 1.0)
        self.strength.setDecimals(2)
        self.strength.setValue(material.height_blend_strength)
        self.view = QComboBox()
        self.view.addItem("Final material", -1)
        self.lighting = QComboBox()
        self.lighting.addItem("Studio", "studio")
        self.lighting.addItem("Grazing", "grazing")
        self.lighting.addItem("Soft", "soft")
        self.weight_label = QLabel()
        self.weight_label.setWordWrap(True)
        self.status = QLabel("Preview composites albedo, tint and an approximate AO darkening. "
                             "Select a layer to inspect its final weight. "
                             "Normal, emission and parallax effects are not composited here.")
        self.status.setWordWrap(True)
        self.plotter = QtInteractor(self)
        self.plotter.set_background("#15181c", top="#3b4652")
        self.plotter.enable_trackball_style()
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #e07a6a")
        self.refresh = QPushButton("Refresh")

        form = QFormLayout()
        form.addRow("Active layers", self.layer_count)
        for i in range(4):
            row = QHBoxLayout()
            row.addWidget(self.enabled[i])
            row.addWidget(self.surface[i], 1)
            row.addWidget(self.weight[i], 1)
            form.addRow(row)
        form.addRow(self.height_blend)
        form.addRow("Transition width", self.transition)
        form.addRow("Height blend strength", self.strength)
        form.addRow("Display", self.view)
        form.addRow("Lighting", self.lighting)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.plotter.interactor, 1)
        layout.addWidget(self.weight_label)
        layout.addWidget(self.status)
        layout.addWidget(self.error)
        layout.addWidget(self.refresh)

        names = material.surface_names()
        for combo in self.surface:
            combo.addItems(names)
        self.layer_count.currentIndexChanged.connect(self._controls_changed)
        self.refresh.clicked.connect(self._render)
        self.height_blend.toggled.connect(self._render)
        self.transition.valueChanged.connect(self._render)
        self.strength.valueChanged.connect(self._render)
        self.view.currentIndexChanged.connect(self._render)
        self.lighting.currentIndexChanged.connect(self._set_lighting)
        for widget in (*self.enabled, *self.surface, *self.weight):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._render)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._render)
            else:
                widget.valueChanged.connect(self._render)
        self._set_lighting()
        self._controls_changed()

    def _set_lighting(self):
        presets = {
            "studio": (((10, -8, 14), 0.9), ((-8, 5, 8), 0.45)),
            "grazing": (((14, 0, 3), 1.0), ((-6, -4, 5), 0.25)),
            "soft": (((4, -3, 12), 0.55), ((-4, 3, 10), 0.55)),
        }
        self.plotter.remove_all_lights()
        for position, intensity in presets[self.lighting.currentData()]:
            light = self._pv.Light()
            light.position = position
            light.focal_point = (0, 0, 0)
            light.intensity = intensity
            self.plotter.add_light(light)
        self.plotter.render()

    def _controls_changed(self):
        count = self.layer_count.currentData()
        for i in range(4):
            active = i < count
            self.enabled[i].setEnabled(active)
            self.enabled[i].setChecked(active)
            self.surface[i].setEnabled(active)
            self.weight[i].setEnabled(active)
        self.view.clear()
        self.view.addItem("Final material", -1)
        for i in range(count):
            self.view.addItem(f"Layer {i + 1} final weight", i)
        self._render()

    def _render(self):
        count = self.layer_count.currentData()
        indices = [i for i in range(count) if self.enabled[i].isChecked()]
        if len(indices) < 2:
            self.error.setText("Enable at least two layers.")
            return
        surfaces = [self._material.surface(self.surface[i].currentText()) for i in indices]
        weights = [self.weight[i].value() for i in indices]
        if sum(weights) == 0:
            self.error.setText("At least one layer weight must be positive.")
            return
        try:
            rgb, final = compose_preview(
                surfaces, weights, height_blend=self.height_blend.isChecked(),
                transition=self.transition.value(), strength=self.strength.value())
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        selected_view = self.view.currentData()
        if selected_view is not None and selected_view >= 0:
            if selected_view not in indices:
                self.error.setText(f"Enable Layer {selected_view + 1} to inspect its final weight.")
                return
            layer = indices.index(selected_view)
            values = np.clip(final[layer] * 255.0 + 0.5, 0, 255).astype(np.uint8)
            rgb = np.repeat(values[..., None], 3, axis=2)
        texture = self._pv.numpy_to_texture(rgb)
        texture.SetUseSRGBColorSpace(True)
        texture.repeat = True
        reset_camera = self._actor is None
        if self._actor is not None:
            self.plotter.remove_actor(self._actor, reset_camera=False, render=False)
        self._actor = self.plotter.add_mesh(
            self._pv.Plane(i_size=15, j_size=15, i_resolution=64, j_resolution=64),
            texture=texture, pbr=True, reset_camera=reset_camera, render=False)
        self._actor.prop.SetTexture("albedoTex", texture)
        self.weight_label.setText("Mean final weights: " + ", ".join(
            f"{surface.name} {float(final[i].mean()):.1%}" for i, surface in enumerate(surfaces)))
        self.plotter.render()
