"""Interactive preview for classic and height-based multi-surface blending."""

from __future__ import annotations

import io

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..bake import _linear_to_srgb, _srgb_to_linear
from ..material import Surface, TerrainMaterial, _eight_bit, normal_preview_array, prepare_texture
from .material_panel import _mesh_with_tangents
from .preview_shader import _height_samples


def _read_rgba(path: str) -> np.ndarray:
    from PIL import Image

    prepared = prepare_texture(path)
    with Image.open(io.BytesIO(prepared.data)) as image:
        return np.asarray(_eight_bit(image).convert("RGBA"))


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
            color = _srgb_to_linear(color.astype(np.float64) / 255.0)
        else:
            color = np.ones((size, size, 3), dtype=np.float64)
        color *= _srgb_to_linear(np.asarray(surface.color, dtype=np.float64) / 255.0)
        colors.append(color)
        if surface.height_map.path:
            height = _sample_repeat(_height_samples(surface.height_map), surface.repeat_m, size)
            heights.append(np.clip(height * surface.height_scale + surface.height_bias, 0.0, 1.0))
        else:
            heights.append(np.full((size, size), 0.5, dtype=np.float64))
        if surface.ao_map.path:
            ao = _sample_repeat(_height_samples(surface.ao_map), surface.repeat_m, size)
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
    rgb = np.clip(_linear_to_srgb(color) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return rgb, final


def _compose_pbr_maps(surfaces: list[Surface], final: np.ndarray) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    size = final.shape[1]
    roughness = np.zeros((size, size), dtype=np.float64)
    metallic = np.zeros((size, size), dtype=np.float64)
    normals = np.zeros((size, size, 3), dtype=np.float64)
    emission = np.zeros((size, size, 3), dtype=np.float64)
    has_normal = any(surface.normal for surface in surfaces)
    has_emission = any(surface.emission for surface in surfaces)
    for surface, weight in zip(surfaces, final):
        for slot, factor, target in ((surface.roughness_map, surface.roughness, roughness),
                                     (surface.metallic_map, surface.metallic, metallic)):
            if slot.path:
                rgba = _sample_repeat(_read_rgba(slot.path), surface.repeat_m, size)
                sample = rgba[..., slot.channel].astype(np.float64) / 255.0
                if slot.invert:
                    sample = 1.0 - sample
            else:
                sample = 1.0
            target += weight * factor * sample
        if has_normal:
            if surface.normal:
                rgb = _sample_repeat(normal_preview_array(surface.normal), surface.repeat_m, size)[..., :3]
                normal = rgb.astype(np.float64) / 127.5 - 1.0
                length = np.linalg.norm(normal, axis=-1, keepdims=True)
                normal = np.divide(normal, length, out=np.zeros_like(normal), where=length > 1e-12)
            else:
                normal = np.array((0.0, 0.0, 1.0))
            normals += weight[..., None] * normal
        if surface.emission:
            rgb = _sample_repeat(_read_rgba(surface.emission), surface.repeat_m, size)[..., :3]
            emission += weight[..., None] * _srgb_to_linear(rgb.astype(np.float64) / 255.0)
    orm = np.stack((np.ones_like(roughness), roughness, metallic), axis=-1)
    orm = np.clip(orm * 255.0 + 0.5, 0, 255).astype(np.uint8)
    normal_image = None
    if has_normal:
        length = np.linalg.norm(normals, axis=-1, keepdims=True)
        normalized = np.zeros_like(normals)
        normalized[..., 2] = 1.0
        normalized = np.divide(normals, length, out=normalized, where=length > 1e-12)
        normal_image = np.clip((normalized * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    emission_image = None
    if has_emission:
        emission_image = np.clip(_linear_to_srgb(emission) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return orm, normal_image, emission_image


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
        self.status = QLabel("Preview composites albedo, tint, normal, metallic, roughness and emission. "
                             "AO is approximated by darkening the color. "
                             "Select a layer to inspect its final weight. "
                             "Layer weight views use unshifted coordinates.")
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

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._render)

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
            self.view.addItem(f"Layer {i + 1} final weight (CPU estimate)", i)
        for i in range(count):
            self.view.addItem(f"Layer {i + 1} base weight (shader)", 10 + i)
            self.view.addItem(f"Layer {i + 1} final weight (shader)", 20 + i)
            self.view.addItem(f"Layer {i + 1} parallax offset (shader)", 30 + i)
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
            selected_view = self.view.currentData()
            pbr_maps = _compose_pbr_maps(surfaces, final) if selected_view == -1 else None
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        diagnostic = None
        if selected_view is not None and selected_view >= 0:
            selected_layer = selected_view % 10
            if selected_layer not in indices:
                self.error.setText(f"Enable Layer {selected_layer + 1} to inspect it.")
                return
            layer = indices.index(selected_layer)
            if selected_view < 10:
                values = np.clip(final[layer] * 255.0 + 0.5, 0, 255).astype(np.uint8)
                rgb = np.repeat(values[..., None], 3, axis=2)
            else:
                kind = {1: "base", 2: "final", 3: "offset"}[selected_view // 10]
                diagnostic = (kind, layer)
                rgb = np.full((2, 2, 3), 255, dtype=np.uint8)
        texture = self._pv.numpy_to_texture(rgb)
        texture.SetUseSRGBColorSpace(True)
        texture.repeat = True
        reset_camera = self._actor is None
        if self._actor is not None:
            self.plotter.remove_actor(self._actor, reset_camera=False, render=False)
        mesh = self._pv.Plane(i_size=15, j_size=15, i_resolution=64, j_resolution=64)
        if pbr_maps is not None and pbr_maps[1] is not None:
            mesh = _mesh_with_tangents(mesh, self._pv)
        self._actor = self.plotter.add_mesh(
            mesh, texture=texture, pbr=True, metallic=1.0 if pbr_maps is not None else 0.0,
            roughness=1.0 if pbr_maps is not None else 0.5,
            reset_camera=reset_camera, render=False)
        self._actor.prop.SetTexture("albedoTex", texture)
        if pbr_maps is not None:
            orm, normal, emission = pbr_maps
            self._actor.prop.SetORMTexture(self._pv.numpy_to_texture(orm))
            if normal is not None:
                self._actor.prop.SetNormalTexture(self._pv.numpy_to_texture(normal))
            if emission is not None:
                emission_texture = self._pv.numpy_to_texture(emission)
                emission_texture.SetUseSRGBColorSpace(True)
                self._actor.prop.SetEmissiveTexture(emission_texture)
                self._actor.prop.SetEmissiveFactor(1.0, 1.0, 1.0)
        elif diagnostic is not None:
            white = self._pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
            self._actor.prop.SetORMTexture(white)
            emission = self._pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
            emission.SetUseSRGBColorSpace(True)
            self._actor.prop.SetEmissiveTexture(emission)
            self._actor.prop.SetEmissiveFactor(1.0, 1.0, 1.0)
        configured = False
        if diagnostic is not None or (pbr_maps is not None and self._material.parallax_mode != "NONE"):
            try:
                from .preview_shader import install_layered_preview

                units = self.plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits()
                if units == 0:
                    units = 16
                install_layered_preview(
                    self._actor, self._pv, surfaces, weights, self._material,
                    height_blend=self.height_blend.isChecked(), transition=self.transition.value(),
                    strength=self.strength.value(), texture_units=units, diagnostic=diagnostic)
                configured = True
            except (OSError, ValueError) as exc:
                self.error.setText(f"Could not configure layered parallax preview: {exc}")
        if diagnostic is not None and not configured:
            self._actor.SetVisibility(False)
            self.status.setText("Shader diagnostic could not be configured; see the error.")
        elif diagnostic is not None:
            detail = ("Red and green encode signed U/V displacement relative to the layer's parallax scale; "
                      "neutral is 0.5 in linear color." if diagnostic[0] == "offset"
                      else "Grayscale shows the selected layer's per-fragment weight.")
            self.status.setText(f"Shader diagnostic: {detail} Mean weights remain unshifted CPU estimates.")
        elif configured:
            self.status.setText("Per-layer parallax is configured with independent texture sampling. "
                                "Mean weights use unshifted coordinates.")
        elif self.error.text():
            self.status.setText("Shader configuration failed; showing the CPU approximation.")
        else:
            self.status.setText("Preview composites albedo, tint, normal, metallic, roughness and emission. "
                                "AO is approximated by darkening the color. "
                                "CPU weight views use unshifted coordinates.")
        self.weight_label.setText("Mean final weights: " + ", ".join(
            f"{surface.name} {float(final[i].mean()):.1%}" for i, surface in enumerate(surfaces)))
        self.plotter.render()
