"""3D preview of built tiles (pyvista / VTK inside Qt)."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..material import srgb_to_linear
from ..ply import read_ply, weight_fields

TRIANGLE_BUDGET = 8_000_000
DETAIL_TRIANGLE_BUDGET = 250_000
DETAIL_PALETTE_BUDGET = 128
DETAIL_TEXTURE_BUDGET = 512 * 1024 * 1024
COLOR_MODES = ("Height", "Surfaces (vertex layers)", "Tiles", "Material", "Detailed material")
MATERIAL_MODE = 3
DETAILED_MATERIAL_MODE = 4


def triangle_count(manifest: dict, tiles, lod: int) -> int:
    wanted = set(tiles)
    return sum(t["lods"][lod]["triangles"] for t in manifest["tiles"] if (t["ix"], t["iy"]) in wanted)


def _tile_color(ix: int, iy: int) -> np.ndarray:
    k = (ix * 73856093 ^ iy * 19349663) & 0xFFFFFF
    hue = (k % 360) / 360.0
    i = int(hue * 6)
    f = hue * 6 - i
    q, t = 1 - f, f
    rgb = [(1, t, 0), (q, 1, 0), (0, 1, t), (0, q, 1), (t, 0, 1), (1, 0, q)][i % 6]
    return (np.array(rgb) * 150 + 70).astype(np.uint8)


def load_tiles(manifest: dict, tiles, lod: int, detailed: bool = False) -> dict:
    """Merge the selected tiles of one LOD into world-space arrays."""
    wanted = set(tiles)
    root = manifest["_dir"]
    texturing = manifest.get("texturing") or {}
    colors = np.array([[srgb_to_linear(c) for c in rgb] for rgb in texturing.get("surface_colors", [])],
                      np.float32).reshape(-1, 3)
    points, faces, normals, zones, tint, material_tiles = [], [], [], [], [], []
    base = 0
    triangle_total = 0
    for tile in manifest["tiles"]:
        if (tile["ix"], tile["iy"]) not in wanted:
            continue
        verts, tri = read_ply(os.path.join(root, tile["lods"][lod]["file"]))
        triangle_total += len(tri)
        if detailed and triangle_total > DETAIL_TRIANGLE_BUDGET:
            raise ValueError(f"Detailed material exceeds the {DETAIL_TRIANGLE_BUDGET:,}-triangle budget")
        ox, oy, oz = tile["origin_m"]
        points.append(np.column_stack((verts["x"] + ox, verts["y"] + oy, verts["z"] + oz)).astype(np.float32))
        normals.append(np.column_stack((verts["nx"], verts["ny"], verts["nz"])).astype(np.float32))
        faces.append(tri.astype(np.int64) + base)
        base += len(verts)
        tint.append(np.broadcast_to(_tile_color(tile["ix"], tile["iy"]), (len(verts), 3)))
        names = weight_fields(verts)
        if detailed:
            if not names or len(names) != len(texturing.get("surfaces", [])):
                raise ValueError(f"Tile {tile['id']} has no matching built surface weights; rebuild the tiles")
            material_tiles.append({
                "points": points[-1], "normals": normals[-1], "faces": tri.astype(np.int64),
                "uv": np.column_stack((verts["s"], 1.0 - verts["t"])).astype(np.float32),
                "weights": np.column_stack([verts[name] for name in names]).astype(np.uint8),
            })
        if names and len(names) == len(colors):
            weights = np.column_stack([verts[name] for name in names]).astype(np.float32) / 255.0
            linear = np.clip(weights @ colors, 0.0, 1.0)
            srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1 / 2.4) - 0.055)
            zones.append((srgb * 255.0 + 0.5).astype(np.uint8))
        else:
            zones.append(np.full((len(verts), 3), 128, np.uint8))
    if not points:
        return {}
    result = {
        "points": np.concatenate(points),
        "faces": np.concatenate(faces),
        "normals": np.concatenate(normals),
        "zones": np.concatenate(zones),
        "tiles": np.concatenate(tint),
    }
    if detailed:
        result["material_tiles"] = material_tiles
    return result


class _Loader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, manifest, tiles, lod, detailed, parent=None):
        super().__init__(parent)
        self._args = (manifest, list(tiles), lod, detailed)

    def run(self):
        try:
            self.loaded.emit(load_tiles(*self._args))
        except Exception as exc:  # reported in the UI
            self.failed.emit(f"Could not load tiles: {exc}")


class _Baker(QThread):
    baked = Signal(int, object)
    failed = Signal(str)

    def __init__(self, generation, manifest, material, tiles, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._args = (manifest, material, list(tiles))

    def run(self):
        from ..bake import bake

        try:
            self.baked.emit(self._generation, bake(*self._args))
        except Exception as exc:  # reported in the UI
            self.failed.emit(f"Could not bake the material preview: {exc}")


class Viewer3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._manifest: dict | None = None
        self._tiles: list[tuple[int, int]] = []
        self._data: dict = {}
        self._loader: _Loader | None = None
        self._pending = False
        self._actor = None
        self._extra_actors = []
        self._framed: tuple | None = None
        self._material = None
        self._baked = None  # (image, bbox) for self._baked_key
        self._baked_key = None
        self._bake_generation = 0
        self._baker: _Baker | None = None

        self.lod = QComboBox()
        self.lod.setToolTip("Level of detail to display")
        self.color = QComboBox()
        self.color.addItems(COLOR_MODES)
        self.color.setToolTip("Material is a fast albedo bake. Detailed material samples each layer in the "
                              "shader, including height blending and parallax.")
        self.exaggeration = QDoubleSpinBox()
        self.exaggeration.setRange(0.1, 20.0)
        self.exaggeration.setSingleStep(0.5)
        self.exaggeration.setValue(1.0)
        self.exaggeration.setSuffix(" ×")
        self.exaggeration.setToolTip("Vertical exaggeration")
        self.wire = QCheckBox("Wireframe")
        self.reset = QPushButton("Reset view")
        self.status = QLabel("Build or open tiles, then pick them on the map")
        self.status.setStyleSheet("color: #9aa3ad")

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        for label, widget in (("LOD", self.lod), ("Colour", self.color), ("Height", self.exaggeration)):
            bar.addWidget(QLabel(label))
            bar.addWidget(widget)
        bar.addWidget(self.wire)
        bar.addWidget(self.reset)
        bar.addStretch(1)

        from pyvistaqt import QtInteractor

        self.plotter = QtInteractor(self)
        self.plotter.set_background("#15181c", top="#3b4652")
        self.plotter.add_axes(color="#c8ced6")
        self.plotter.enable_terrain_style(mouse_wheel_zooms=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.plotter.interactor, 1)
        layout.addWidget(self.status)

        self.lod.currentIndexChanged.connect(self._reload)
        self.color.currentIndexChanged.connect(self._color_changed)
        self.wire.toggled.connect(self._redraw)
        self.exaggeration.valueChanged.connect(self._rescale)
        self.reset.clicked.connect(self._reset_camera)

    # ------------------------------------------------------------- public
    def set_manifest(self, manifest: dict | None) -> None:
        self._manifest = manifest
        self._tiles = []
        self._data = {}
        self.lod.blockSignals(True)
        self.lod.clear()
        if manifest:
            for lod in manifest["lods"]:
                self.lod.addItem(f"{lod['index']}  ({lod['max_error_m']:g} m)")
            self.lod.setCurrentIndex(len(manifest["lods"]) - 1)
        self.lod.blockSignals(False)
        self.plotter.clear_actors()
        self._actor = None
        self._extra_actors = []
        self.plotter.render()

    def show_tiles(self, tiles, lod: int | None = None) -> None:
        if not self._manifest:
            return
        self._tiles = sorted(tiles)
        if lod is not None and lod != self.lod.currentIndex():
            self.lod.setCurrentIndex(lod)  # triggers _reload
        else:
            self._reload()

    def set_material(self, material) -> None:
        """Material for the Material colour mode; re-bakes when that mode is visible."""
        self._material = material
        self._baked_key = None
        self._bake_generation += 1
        if self.color.currentIndex() in (MATERIAL_MODE, DETAILED_MATERIAL_MODE) and self._data:
            self._redraw()

    def shutdown(self) -> None:
        if self._loader is not None:
            self._loader.wait()
        if self._baker is not None:
            self._baker.wait()
        self.plotter.close()

    # ------------------------------------------------------------ loading
    def _color_changed(self) -> None:
        if self.color.currentIndex() == DETAILED_MATERIAL_MODE and "material_tiles" not in self._data:
            self._reload()
        else:
            self._redraw()

    def _reload(self) -> None:
        if not self._manifest or not self._tiles or self.lod.currentIndex() < 0:
            return
        if self._loader is not None and self._loader.isRunning():
            self._pending = True
            return
        lod = self.lod.currentIndex()
        count = triangle_count(self._manifest, self._tiles, lod)
        detailed = self.color.currentIndex() == DETAILED_MATERIAL_MODE
        budget = DETAIL_TRIANGLE_BUDGET if detailed else TRIANGLE_BUDGET
        if count > budget:
            self.status.setText(f"{len(self._tiles)} tiles at LOD {lod} have {count:,} triangles, above the "
                                f"{budget:,} preview budget. Select fewer tiles or a coarser LOD.")
            return
        self.status.setText(f"Loading {len(self._tiles)} tiles, {count:,} triangles…")
        self._loader = _Loader(self._manifest, self._tiles, lod, detailed, self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self.status.setText)
        self._loader.finished.connect(self._on_finished)
        self._loader.start()

    def _on_finished(self) -> None:
        if self._pending:
            self._pending = False
            self._reload()

    def _on_loaded(self, data: dict) -> None:
        if self._loader is not None:
            manifest, tiles, lod, detailed = self._loader._args
            if (manifest is not self._manifest or tiles != self._tiles or lod != self.lod.currentIndex()
                    or detailed != (self.color.currentIndex() == DETAILED_MATERIAL_MODE)):
                self._pending = True
                return
        key = tuple(self._tiles)
        first = self._framed != key
        self._framed = key
        self._data = data
        self._redraw()
        if first:
            self._reset_camera()
        if data and self.color.currentIndex() != DETAILED_MATERIAL_MODE:
            self.status.setText(f"{len(self._tiles)} tiles, LOD {self.lod.currentIndex()}: "
                                f"{len(data['faces']):,} triangles, {len(data['points']):,} vertices. "
                                "Left drag rotates, right drag or wheel zooms, middle drag pans.")

    # ------------------------------------------------------------ drawing
    def _redraw(self) -> None:
        import pyvista as pv

        for actor in ([self._actor] if self._actor is not None else []) + self._extra_actors:
            self.plotter.remove_actor(actor, render=False)
        self._actor = None
        self._extra_actors = []
        if not self._data:
            self.plotter.render()
            return
        if self.color.currentIndex() == DETAILED_MATERIAL_MODE:
            if "material_tiles" not in self._data:
                self._reload()
                return
            try:
                actors, conflicts = self._draw_detailed(pv)
            except (OSError, ValueError) as exc:
                self.status.setText(f"Could not configure detailed material: {exc}")
                self.plotter.render()
                return
            if actors:
                self._actor, self._extra_actors = actors[0], actors[1:]
            message = ("Detailed material configured using built weights; rebuild after changing biome rules or paint. "
                       "Shader compilation depends on the VTK renderer.")
            if conflicts:
                message += f" {conflicts} triangles exceed four surfaces and may show seams."
            self.status.setText(message)
            self._rescale()
            return
        mesh = pv.PolyData.from_regular_faces(self._data["points"], self._data["faces"])
        mesh.point_data["Normals"] = self._data["normals"]
        mesh.point_data.active_normals_name = "Normals"
        mode = self.color.currentIndex()
        options = dict(smooth_shading=True, show_scalar_bar=False, show_edges=self.wire.isChecked(),
                       edge_color="#5a636e", line_width=0.5, specular=0.05)
        if mode == 0 or (mode == MATERIAL_MODE and not self._material_ready()):
            z = self._data["points"][:, 2]
            lo, hi = self._manifest.get("edited_height_range_m", self._manifest["source"]["height_range_m"])
            mesh.point_data["height"] = z
            self._actor = self.plotter.add_mesh(mesh, scalars="height", cmap="gist_earth",
                                                clim=(lo, hi if hi > lo else lo + 1), **options)
        elif mode == MATERIAL_MODE:
            image, (x0, y0, x1, y1) = self._baked
            points = self._data["points"]
            mesh.active_texture_coordinates = np.column_stack(
                ((points[:, 0] - x0) / max(x1 - x0, 1e-9), (points[:, 1] - y0) / max(y1 - y0, 1e-9)))
            texture = pv.Texture(np.ascontiguousarray(image))  # pyvista maps array row 0 to v = 1
            texture.interpolate = True
            texture.mipmap = True
            self._actor = self.plotter.add_mesh(mesh, texture=texture, **options)
        else:
            mesh.point_data["rgb"] = self._data["zones" if mode == 1 else "tiles"]
            self._actor = self.plotter.add_mesh(mesh, scalars="rgb", rgb=True, **options)
        self._actor.scale = (1.0, 1.0, self.exaggeration.value())
        self.plotter.render()

    def _draw_detailed(self, pv):
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper
        from ..adm_export import _slots, build_surfaces, color1, group_masks, triangle_masks
        from .material_panel import _mesh_with_tangents
        from .preview_shader import install_layered_preview

        if self._material is None:
            raise ValueError("Choose a material before using the detailed preview")
        surfaces = build_surfaces(self._manifest, self._material)
        tile_size = float(self._manifest["tile_size_m"])
        units = self.plotter.render_window.GetTextureUnitManager().GetNumberOfTextureUnits() or 16
        white = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
        white.SetUseSRGBColorSpace(True)
        orm = pv.numpy_to_texture(np.full((2, 2, 3), 255, dtype=np.uint8))
        normal = pv.numpy_to_texture(np.full((2, 2, 3), (128, 128, 255), dtype=np.uint8))
        actors = []
        conflicts = 0
        texture_cache = {}
        try:
            for tile in self._data["material_tiles"]:
                masks, count = triangle_masks(tile["weights"], tile["faces"])
                conflicts += count
                sets, assign = group_masks(masks)
                groups = np.array([assign[int(mask)] for mask in masks])
                for group, mask in enumerate(sets):
                    if len(actors) >= DETAIL_PALETTE_BUDGET:
                        raise ValueError(f"Detailed material exceeds the {DETAIL_PALETTE_BUDGET}-palette budget; "
                                         "select fewer tiles")
                    selected_faces = tile["faces"][groups == group]
                    keep, local = np.unique(selected_faces.ravel(), return_inverse=True)
                    mesh = pv.PolyData.from_regular_faces(tile["points"][keep], local.reshape(-1, 3))
                    mesh.point_data["Normals"] = tile["normals"][keep]
                    mesh.point_data.active_normals_name = "Normals"
                    mesh.active_texture_coordinates = tile["uv"][keep]
                    slots = _slots(mask)
                    mesh.point_data["layer_weights"] = color1(tile["weights"][keep], slots).astype(np.float32) / 255
                    mesh = _mesh_with_tangents(mesh, pv)
                    actor = self.plotter.add_mesh(mesh, texture=white, pbr=True, metallic=1, roughness=1,
                                                  smooth_shading=True, show_edges=self.wire.isChecked(),
                                                  edge_color="#5a636e", render=False)
                    actors.append(actor)
                    mapper = vtkPolyDataMapper()
                    mapper.SetInputData(mesh)
                    mapper.ScalarVisibilityOff()
                    actor.SetMapper(mapper)
                    actor.prop.SetTexture("albedoTex", white)
                    actor.prop.SetORMTexture(orm)
                    actor.prop.SetNormalTexture(normal)
                    actor.prop.SetEmissiveTexture(white)
                    actor.prop.SetEmissiveFactor(1, 1, 1)
                    layers = [surfaces[slot] for slot in slots]
                    install_layered_preview(
                        actor, pv, layers, [1] * len(layers), self._material,
                        height_blend=self._material.height_blend_enabled,
                        transition=self._material.height_blend_transition,
                        strength=self._material.height_blend_strength, texture_units=units,
                        vertex_weights="layer_weights", uv_scales=self._material.uv_scale(tile_size, layers),
                        texture_cache=texture_cache, texture_budget_bytes=DETAIL_TEXTURE_BUDGET)
        except (OSError, ValueError):
            for actor in actors:
                self.plotter.remove_actor(actor, render=False)
            raise
        return actors, conflicts

    def _material_ready(self) -> bool:
        """True when a bake for the shown tiles exists; otherwise starts one."""
        key = (tuple(self._tiles), self._bake_generation)
        if self._baked_key == key:
            return True
        if self._material is None:
            self.status.setText("Material preview needs a material")
            return False
        if self._baker is not None and self._baker.isRunning():
            self._baker.finished.connect(self._redraw, Qt.ConnectionType.SingleShotConnection)
            return False
        self.status.setText("Baking the material preview…")
        self._baker = _Baker(self._bake_generation, self._manifest, self._material, self._tiles, self)
        tiles = tuple(self._tiles)
        self._baker.baked.connect(lambda generation, result: self._on_baked(generation, tiles, result))
        self._baker.failed.connect(self.status.setText)
        self._baker.start()
        return False

    def _on_baked(self, generation: int, tiles: tuple, result) -> None:
        if generation != self._bake_generation or tiles != tuple(self._tiles):
            return
        self._baked = result
        self._baked_key = (tiles, generation)
        if self.color.currentIndex() == MATERIAL_MODE:
            self._redraw()
            image = result[0]
            self.status.setText(f"Material preview {image.shape[1]:,} × {image.shape[0]:,} px "
                                "(albedo blended by vertex weights; lighting without normal maps)")

    def _rescale(self) -> None:
        if self._actor is not None:
            for actor in [self._actor] + self._extra_actors:
                actor.scale = (1.0, 1.0, self.exaggeration.value())
            self.plotter.render()

    def _reset_camera(self) -> None:
        if not self._data:
            return
        self.plotter.view_isometric()
        self.plotter.reset_camera()
        self.plotter.camera.zoom(1.3)
        self.plotter.render()
