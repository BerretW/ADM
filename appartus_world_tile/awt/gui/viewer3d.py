"""3D preview of built tiles (pyvista / VTK inside Qt)."""

from __future__ import annotations

import hashlib
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
COLLISION_PREVIEW_TRIANGLE_BUDGET = 250_000
COLLISION_PREVIEW_FILE_BUDGET = 256 * 1024 * 1024
COLOR_MODES = ("Height", "Surfaces (vertex layers)", "Tiles", "Material", "Detailed material",
               "COLOR_1 palette channel", "Control Map channel")
MATERIAL_MODE = 3
DETAILED_MATERIAL_MODE = 4
COLOR1_MODE = 5
CONTROL_MAP_MODE = 6


def triangle_count(manifest: dict, tiles, lod: int) -> int:
    wanted = set(tiles)
    return sum(t["lods"][lod]["triangles"] for t in manifest["tiles"] if (t["ix"], t["iy"]) in wanted)


def _palette_groups(tile):
    from ..adm_export import group_masks, seam_consistent_weights, triangle_masks

    masks, conflicts = triangle_masks(tile["weights"], tile["faces"])
    sets, assign = group_masks(masks)
    face_palettes = np.fromiter(
        (sets[assign[int(mask)]] for mask in masks), dtype=np.uint64, count=len(masks))
    effective_weights, errors = seam_consistent_weights(tile["weights"], tile["faces"], face_palettes)
    groups = np.array([assign[int(mask)] for mask in masks])
    return ((mask, tile["faces"][groups == group]) for group, mask in enumerate(sets)), conflicts, (
        effective_weights, errors)


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
                "ix": tile["ix"], "iy": tile["iy"],
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


def load_collision_tiles(manifest: dict, tiles, material) -> dict:
    """Load bounded collision geometry with physical assignments and hover metadata."""
    from ..adm_export import _collision_file_path, _physical_face_assignments

    wanted = set(tiles)
    points, faces, colors, info = [], [], [], []
    base = 0
    triangle_total = 0
    measured_error = 0.0
    surface_names = (manifest.get("texturing") or {}).get("surfaces") or []
    if not isinstance(surface_names, list) or not all(isinstance(name, str) for name in surface_names):
        raise ValueError("Manifest surface names are invalid for collision inspection")
    materials = {item.id: item for item in material.physical_materials}
    root = manifest.get("_dir")
    if not isinstance(root, str) or not root:
        raise ValueError("Collision inspection requires a manifest directory")
    seen = set()
    for tile in manifest.get("tiles", []):
        if not isinstance(tile, dict):
            raise ValueError("Manifest tile records must be objects")
        ix, iy = tile.get("ix"), tile.get("iy")
        if (isinstance(ix, bool) or not isinstance(ix, int)
                or isinstance(iy, bool) or not isinstance(iy, int)):
            raise ValueError("Manifest tile coordinates must be integers")
        if (ix, iy) not in wanted:
            continue
        seen.add((ix, iy))
        collision = tile.get("collision")
        if not isinstance(collision, dict):
            raise ValueError(f"{tile.get('id', 'Tile')}: collision mesh is unavailable")
        declared_count = collision.get("triangles")
        if (isinstance(declared_count, bool) or not isinstance(declared_count, int)
                or declared_count < 1):
            raise ValueError(f"{tile['id']}: collision triangle count is invalid")
        triangle_total += declared_count
        if triangle_total > COLLISION_PREVIEW_TRIANGLE_BUDGET:
            raise ValueError(f"Collision preview exceeds the {COLLISION_PREVIEW_TRIANGLE_BUDGET:,}-triangle budget")
        relative = collision.get("file")
        path = _collision_file_path(root, relative)
        if os.path.getsize(path) > COLLISION_PREVIEW_FILE_BUDGET:
            raise ValueError(f"{tile['id']}: collision mesh exceeds the "
                             f"{COLLISION_PREVIEW_FILE_BUDGET // (1024 * 1024)} MiB preview limit")
        vertices, tile_faces = read_ply(path)
        if len(tile_faces) != declared_count:
            raise ValueError(f"{tile['id']}: collision triangle count does not match the manifest")
        if (tile_faces.ndim != 2 or tile_faces.shape[1] != 3 or len(vertices) < 3
                or np.any(tile_faces < 0) or np.any(tile_faces >= len(vertices))):
            raise ValueError(f"{tile['id']}: collision mesh faces are invalid")
        origin = tile.get("origin_m")
        if (not isinstance(origin, list) or len(origin) != 3
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not np.isfinite(value) for value in origin)):
            raise ValueError(f"{tile['id']}: collision tile origin is invalid")
        local_points = np.column_stack((vertices["x"], vertices["y"], vertices["z"]))
        if not np.isfinite(local_points).all():
            raise ValueError(f"{tile['id']}: collision vertices must be finite")
        points.append((local_points + np.asarray(origin, dtype=np.float64)).astype(np.float32))
        faces.append(tile_faces.astype(np.int64) + base)
        base += len(vertices)
        assignments = _physical_face_assignments(manifest, tile, material, vertices, tile_faces)
        fields = weight_fields(vertices)
        if fields:
            if len(fields) != len(surface_names):
                raise ValueError(f"{tile['id']}: collision surface weights do not match the manifest")
            weights = np.column_stack([vertices[name] for name in fields])
            dominant = np.argmax(weights[tile_faces].astype(np.uint16).sum(axis=1), axis=1)
        else:
            dominant = np.full(len(tile_faces), -1, dtype=np.int64)
        tile_colors = np.empty((len(tile_faces), 3), dtype=np.uint8)
        for index, (surface_index, physical_id) in enumerate(zip(dominant, assignments)):
            surface_name = (surface_names[int(surface_index)]
                            if 0 <= surface_index < len(surface_names) else "Unknown surface")
            physical = materials.get(physical_id) if physical_id else None
            if not physical_id:
                color = (96, 101, 108)
                physical_name = "Unassigned"
            elif physical is None:
                color = (214, 72, 196)
                physical_name = "Unknown"
            else:
                digest = hashlib.sha256(physical_id.encode("utf-8")).digest()
                color = tuple(64 + value % 160 for value in digest[:3])
                physical_name = physical.name
            tile_colors[index] = color
            info.append({
                "tile": tile["id"],
                "triangle": index,
                "surface": surface_name,
                "physical_id": physical_id or "",
                "physical_name": physical_name,
            })
        colors.append(tile_colors)
        error = collision.get("measured_error_m")
        if (isinstance(error, bool) or not isinstance(error, (int, float))
                or not np.isfinite(error) or error < 0):
            raise ValueError(f"{tile['id']}: measured collision error is invalid")
        measured_error = max(measured_error, float(error))
    if seen != wanted:
        raise ValueError("One or more selected tiles are missing from the collision manifest")
    if not points:
        return {}
    summary = manifest.get("collision") or {}
    error_limit = summary.get("max_error_m")
    if (isinstance(error_limit, bool) or not isinstance(error_limit, (int, float))
            or not np.isfinite(error_limit) or error_limit < 0):
        raise ValueError("Manifest collision error limit is invalid")
    return {
        "points": np.concatenate(points),
        "faces": np.concatenate(faces),
        "physical_colors": np.concatenate(colors),
        "collision_info": info,
        "collision_triangles": triangle_total,
        "collision_error_m": float(error_limit),
        "collision_measured_error_m": measured_error,
    }


class _Loader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, manifest, tiles, lod, detailed, collision=False, material=None, parent=None):
        super().__init__(parent)
        self._args = (manifest, list(tiles), lod, detailed)
        self._collision = collision
        self._material = material

    def run(self):
        try:
            if self._collision:
                self.loaded.emit(load_collision_tiles(self._args[0], self._args[1], self._material))
            else:
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
        self._control_map_resolution = 0
        self._baked = None  # (image, bbox) for self._baked_key
        self._baked_key = None
        self._bake_generation = 0
        self._baker: _Baker | None = None
        self._collision_info = []
        self._picker = None
        self._hover_observer = None

        self.lod = QComboBox()
        self.lod.setToolTip("Level of detail to display")
        self.color = QComboBox()
        self.color.addItems(COLOR_MODES)
        self.color.setToolTip("Material is a fast albedo bake. Detailed material samples each layer in the "
                              "shader, including height blending and parallax.")
        self.weight_channel = QComboBox()
        self.weight_channel.addItems(("R", "G", "B", "A"))
        self.weight_channel.setToolTip("COLOR_1 channels refer to local palette slots, which can differ "
                                       "between primitives.")
        self.weight_channel.setVisible(False)
        self.exaggeration = QDoubleSpinBox()
        self.exaggeration.setRange(0.1, 20.0)
        self.exaggeration.setSingleStep(0.5)
        self.exaggeration.setValue(1.0)
        self.exaggeration.setSuffix(" ×")
        self.exaggeration.setToolTip("Vertical exaggeration")
        self.wire = QCheckBox("Wireframe")
        self.collision = QCheckBox("Collision mesh")
        self.collision.setToolTip("Show collision geometry with physical-material colours instead of render tiles.")
        self.collision.setEnabled(False)
        self.reset = QPushButton("Reset view")
        self.status = QLabel("Build or open tiles, then pick them on the map")
        self.status.setStyleSheet("color: #9aa3ad")

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        for label, widget in (("LOD", self.lod), ("Colour", self.color), ("Height", self.exaggeration)):
            bar.addWidget(QLabel(label))
            bar.addWidget(widget)
        bar.addWidget(self.weight_channel)
        bar.addWidget(self.wire)
        bar.addWidget(self.collision)
        bar.addWidget(self.reset)
        bar.addStretch(1)

        from pyvistaqt import QtInteractor

        self.plotter = QtInteractor(self)
        self.plotter.set_background("#15181c", top="#3b4652")
        self.plotter.add_axes(color="#c8ced6")
        self.plotter.enable_terrain_style(mouse_wheel_zooms=True)
        self._hover_observer = self.plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.plotter.interactor, 1)
        layout.addWidget(self.status)

        self.lod.currentIndexChanged.connect(self._reload)
        self.color.currentIndexChanged.connect(self._color_changed)
        self.weight_channel.currentIndexChanged.connect(self._redraw)
        self.wire.toggled.connect(self._redraw)
        self.collision.toggled.connect(self._collision_changed)
        self.exaggeration.valueChanged.connect(self._rescale)
        self.reset.clicked.connect(self._reset_camera)

    # ------------------------------------------------------------- public
    def set_manifest(self, manifest: dict | None) -> None:
        self._manifest = manifest
        self._tiles = []
        self._data = {}
        self._collision_info = []
        self.collision.blockSignals(True)
        self.collision.setChecked(False)
        self.collision.setEnabled(bool(manifest and manifest.get("collision")))
        self.collision.blockSignals(False)
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

    def _on_mouse_move(self, interactor, _event) -> None:
        if not self.collision.isChecked() or self._actor is None or not self._collision_info:
            return
        if self._picker is None:
            from vtkmodules.vtkRenderingCore import vtkCellPicker

            self._picker = vtkCellPicker()
            self._picker.SetTolerance(0.005)
        x, y = interactor.GetEventPosition()
        if not self._picker.Pick(x, y, 0, self.plotter.renderer) or self._picker.GetActor() != self._actor:
            return
        cell = self._picker.GetCellId()
        if 0 <= cell < len(self._collision_info):
            info = self._collision_info[cell]
            physical = (f"{info['physical_name']} ({info['physical_id']})"
                        if info["physical_id"] else info["physical_name"])
            self.status.setText(
                f"{info['tile']} face {info['triangle'] + 1}: {info['surface']} - {physical}")

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
        if self.color.currentIndex() in (MATERIAL_MODE, DETAILED_MATERIAL_MODE, CONTROL_MAP_MODE) and self._data:
            self._redraw()
        elif self.collision.isChecked() and self._manifest:
            self._reload()

    def set_control_map_resolution(self, resolution: int) -> None:
        """Set the optional source-rule map resolution used by detailed previews."""
        self._control_map_resolution = resolution
        if self.color.currentIndex() in (DETAILED_MATERIAL_MODE, CONTROL_MAP_MODE) and self._data:
            self._redraw()

    def shutdown(self) -> None:
        if self._loader is not None:
            self._loader.wait()
        if self._baker is not None:
            self._baker.wait()
        if self._hover_observer is not None:
            self.plotter.iren.remove_observer(self._hover_observer)
        self.plotter.close()

    # ------------------------------------------------------------ loading
    def _color_changed(self) -> None:
        mode = self.color.currentIndex()
        self.weight_channel.setVisible(mode in (COLOR1_MODE, CONTROL_MAP_MODE))
        if mode in (DETAILED_MATERIAL_MODE, COLOR1_MODE, CONTROL_MAP_MODE) and "material_tiles" not in self._data:
            self._reload()
        else:
            self._redraw()

    def _collision_changed(self, enabled: bool) -> None:
        self.color.setEnabled(not enabled)
        if enabled and self._material is None:
            self.collision.setChecked(False)
            self.status.setText("Choose a material before inspecting physical assignments.")
            return
        self._reload()

    def _reload(self) -> None:
        if not self._manifest or not self._tiles or self.lod.currentIndex() < 0:
            return
        if self._loader is not None and self._loader.isRunning():
            self._pending = True
            return
        lod = self.lod.currentIndex()
        collision = self.collision.isChecked()
        if collision:
            selected = {(tile["ix"], tile["iy"]): tile for tile in self._manifest["tiles"]}
            try:
                count = sum(selected[key]["collision"]["triangles"] for key in self._tiles)
            except (KeyError, TypeError):
                self.status.setText("Collision meshes are unavailable for one or more selected tiles.")
                return
        else:
            count = triangle_count(self._manifest, self._tiles, lod)
        detailed = self.color.currentIndex() in (DETAILED_MATERIAL_MODE, COLOR1_MODE, CONTROL_MAP_MODE)
        budget = (COLLISION_PREVIEW_TRIANGLE_BUDGET if collision else
                  DETAIL_TRIANGLE_BUDGET if detailed else TRIANGLE_BUDGET)
        if count > budget:
            self.status.setText(f"{len(self._tiles)} tiles at LOD {lod} have {count:,} triangles, above the "
                                f"{budget:,} preview budget. Select fewer tiles or a coarser LOD.")
            return
        mode = "collision" if collision else "tiles"
        self.status.setText(f"Loading {len(self._tiles)} {mode}, {count:,} triangles…")
        self._loader = _Loader(self._manifest, self._tiles, lod, detailed, collision, self._material, self)
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
                    or detailed != (self.color.currentIndex() in (
                        DETAILED_MATERIAL_MODE, COLOR1_MODE, CONTROL_MAP_MODE))
                    or self._loader._collision != self.collision.isChecked()
                    or self._loader._material is not self._material):
                self._pending = True
                return
        key = tuple(self._tiles)
        first = self._framed != key
        self._framed = key
        self._data = data
        self._collision_info = data.get("collision_info", [])
        self._redraw()
        if first:
            self._reset_camera()
        if (data and "physical_colors" not in data
                and self.color.currentIndex() not in (DETAILED_MATERIAL_MODE, COLOR1_MODE, CONTROL_MAP_MODE)):
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
        if self.collision.isChecked():
            if "physical_colors" not in self._data:
                self._reload()
                return
            mesh = pv.PolyData.from_regular_faces(self._data["points"], self._data["faces"])
            mesh.cell_data["physical"] = self._data["physical_colors"]
            self._actor = self.plotter.add_mesh(
                mesh, scalars="physical", rgb=True, lighting=False, show_scalar_bar=False,
                show_edges=self.wire.isChecked(), edge_color="#e2e4e8", line_width=0.7)
            self._actor.scale = (1.0, 1.0, self.exaggeration.value())
            self.status.setText(
                f"Collision: {self._data['collision_triangles']:,} triangles; "
                f"error <= {self._data['collision_error_m']:g} m "
                f"(measured {self._data['collision_measured_error_m']:.3f} m). "
                "Move the pointer over a face for surface and physical-material details.")
            self.plotter.render()
            return
        if self.color.currentIndex() in (DETAILED_MATERIAL_MODE, COLOR1_MODE, CONTROL_MAP_MODE):
            if "material_tiles" not in self._data:
                self._reload()
                return
            try:
                if self.color.currentIndex() == COLOR1_MODE:
                    actors, conflicts = self._draw_color1(pv)
                else:
                    actors, conflicts = self._draw_detailed(
                        pv, control_map_diagnostic=self.color.currentIndex() == CONTROL_MAP_MODE)
            except (OSError, ValueError) as exc:
                label = ("COLOR_1 preview" if self.color.currentIndex() == COLOR1_MODE else
                         "Control Map preview" if self.color.currentIndex() == CONTROL_MAP_MODE else
                         "detailed material")
                self.status.setText(f"Could not configure {label}: {exc}")
                self.plotter.render()
                return
            if actors:
                self._actor, self._extra_actors = actors[0], actors[1:]
            if self.color.currentIndex() == COLOR1_MODE:
                message = ("COLOR_1 shows the selected local palette channel; slots can refer to different "
                           "surfaces across primitives. Rebuild after changing biome rules or paint.")
            elif self.color.currentIndex() == CONTROL_MAP_MODE:
                source_kind = "external-mask" if self._material.external_control_map_path else "source-rule"
                message = (f"Control Map shows the selected {source_kind} channel in local palette order; "
                           "unused channels remain zero.")
            elif self._control_map_resolution:
                source_kind = "external-mask" if self._material.external_control_map_path else "source-rule"
                message = (f"Detailed material uses {self._control_map_resolution}px {source_kind} Control Maps "
                           "before per-layer parallax and height blending; collision assignments remain separate.")
            else:
                message = ("Detailed material configured using built weights; rebuild after changing biome rules "
                           "or paint. Shader compilation depends on the VTK renderer.")
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

    def _draw_color1(self, pv):
        from ..adm_export import _slots, color1

        actors = []
        conflicts = 0
        try:
            for tile in self._data["material_tiles"]:
                groups, count, (effective_weights, _errors) = _palette_groups(tile)
                conflicts += count
                for mask, selected_faces in groups:
                    if len(actors) >= DETAIL_PALETTE_BUDGET:
                        raise ValueError(f"COLOR_1 preview exceeds the {DETAIL_PALETTE_BUDGET}-palette budget; "
                                         "select fewer tiles")
                    keep, local = np.unique(selected_faces.ravel(), return_inverse=True)
                    mesh = pv.PolyData.from_regular_faces(tile["points"][keep], local.reshape(-1, 3))
                    weights = color1(effective_weights[keep], _slots(mask))
                    mesh.point_data["COLOR_1"] = weights
                    mesh.point_data["channel"] = weights[:, self.weight_channel.currentIndex()]
                    actors.append(self.plotter.add_mesh(mesh, scalars="channel", cmap="gray", clim=(0, 255),
                                                        lighting=False, show_scalar_bar=False,
                                                        show_edges=self.wire.isChecked(), edge_color="#5a636e",
                                                        render=False))
        except (OSError, ValueError):
            for actor in actors:
                self.plotter.remove_actor(actor, render=False)
            raise
        return actors, conflicts

    def _draw_detailed(self, pv, control_map_diagnostic=False):
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper
        from ..adm_export import _slots, build_surfaces, color1
        from .material_panel import _mesh_with_tangents
        from .preview_shader import install_layered_preview

        if self._material is None:
            raise ValueError("Choose a material before using the detailed preview")
        surfaces = build_surfaces(self._manifest, self._material)
        control_source = None
        if control_map_diagnostic and not self._control_map_resolution:
            raise ValueError("Set a nonzero Control Map resolution to preview its channels")
        if self._control_map_resolution:
            from ..adm_export import _control_map_source

            control_source = _control_map_source(self._manifest, self._material)
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
                groups, count, (effective_weights, _errors) = _palette_groups(tile)
                conflicts += count
                if control_source is not None and "external_mask" in control_source:
                    surface_index = {surface.id: index for index, surface in enumerate(surfaces)}
                    external_slots = [surface_index[ident] for ident in control_source["surface_ids"]]
                    external_palette = sum(1 << index for index in external_slots)
                    groups = [(external_palette, np.concatenate([faces for _mask, faces in groups]))]
                for mask, selected_faces in groups:
                    if len(actors) >= DETAIL_PALETTE_BUDGET:
                        raise ValueError(f"Detailed material exceeds the {DETAIL_PALETTE_BUDGET}-palette budget; "
                                         "select fewer tiles")
                    keep, local = np.unique(selected_faces.ravel(), return_inverse=True)
                    mesh = pv.PolyData.from_regular_faces(tile["points"][keep], local.reshape(-1, 3))
                    mesh.point_data["Normals"] = tile["normals"][keep]
                    mesh.point_data.active_normals_name = "Normals"
                    mesh.active_texture_coordinates = tile["uv"][keep]
                    slots = _slots(mask)
                    mesh.point_data["layer_weights"] = color1(effective_weights[keep], slots).astype(np.float32) / 255
                    mesh = _mesh_with_tangents(mesh, pv)
                    control_map_pixels = None
                    if control_source is not None:
                        from ..adm_export import _tile_source_bounds
                        bounds = _tile_source_bounds(
                            self._manifest, tile, control_source["heightmap"].shape)
                        size = (self._control_map_resolution, self._control_map_resolution)
                        if "external_mask" in control_source:
                            from ..texturing import rasterize_external_control_map

                            target_ids = tuple(surfaces[slot].id for slot in slots)
                            control_map_pixels = rasterize_external_control_map(
                                control_source["external_mask"], control_source["heightmap"].shape,
                                bounds, size, tuple(control_source["surface_ids"]), target_ids,
                            )
                        else:
                            from ..texturing import rasterize_control_map

                            control_map_pixels = rasterize_control_map(
                                control_source["rules"], control_source["heightmap"],
                                control_source["scale"], control_source["offset"],
                                control_source["spacing"], bounds, size,
                                tuple(slots + [-1] * (4 - len(slots))),
                            )
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
                        texture_cache=texture_cache, texture_budget_bytes=DETAIL_TEXTURE_BUDGET,
                        control_map_pixels=control_map_pixels,
                        diagnostic=("control", self.weight_channel.currentIndex())
                        if control_map_diagnostic else None)
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
