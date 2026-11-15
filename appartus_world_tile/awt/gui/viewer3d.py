"""3D preview of built tiles (pyvista / VTK inside Qt)."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..masks import layer_colors
from ..ply import read_ply

TRIANGLE_BUDGET = 8_000_000
COLOR_MODES = ("Height", "Zones (masks)", "Tiles", "Material")
MATERIAL_MODE = 3


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


def load_tiles(manifest: dict, tiles, lod: int) -> dict:
    """Merge the selected tiles of one LOD into world-space arrays."""
    from PIL import Image

    wanted = set(tiles)
    root = manifest["_dir"]
    colors = layer_colors()
    points, faces, normals, zones, tint = [], [], [], [], []
    base = 0
    for tile in manifest["tiles"]:
        if (tile["ix"], tile["iy"]) not in wanted:
            continue
        verts, tri = read_ply(os.path.join(root, tile["lods"][lod]["file"]))
        ox, oy, oz = tile["origin_m"]
        points.append(np.column_stack((verts["x"] + ox, verts["y"] + oy, verts["z"] + oz)).astype(np.float32))
        normals.append(np.column_stack((verts["nx"], verts["ny"], verts["nz"])).astype(np.float32))
        faces.append(tri.astype(np.int64) + base)
        base += len(verts)
        tint.append(np.broadcast_to(_tile_color(tile["ix"], tile["iy"]), (len(verts), 3)))
        mask_file = tile.get("mask")
        if mask_file and os.path.exists(os.path.join(root, mask_file)):
            with Image.open(os.path.join(root, mask_file)) as image:
                mask = np.asarray(image.convert("RGBA"), np.float32) / 255.0
            ry, rx = mask.shape[:2]
            col = np.clip((verts["s1"] * rx).astype(int), 0, rx - 1)
            row = np.clip(((1.0 - verts["t1"]) * ry).astype(int), 0, ry - 1)
            zones.append(np.clip(mask[row, col] @ colors * 255, 0, 255).astype(np.uint8))
        else:
            zones.append(np.full((len(verts), 3), 128, np.uint8))
    if not points:
        return {}
    return {
        "points": np.concatenate(points),
        "faces": np.concatenate(faces),
        "normals": np.concatenate(normals),
        "zones": np.concatenate(zones),
        "tiles": np.concatenate(tint),
    }


class _Loader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, manifest, tiles, lod, parent=None):
        super().__init__(parent)
        self._args = (manifest, list(tiles), lod)

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
        self.color.setToolTip("Zones show the blend masks the way TERRAIN_4 will mix the layers; "
                              "Material shows the layer textures blended by the masks")
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
        self.color.currentIndexChanged.connect(self._redraw)
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
        if self.color.currentIndex() == MATERIAL_MODE and self._data:
            self._redraw()

    def shutdown(self) -> None:
        if self._loader is not None:
            self._loader.wait()
        if self._baker is not None:
            self._baker.wait()
        self.plotter.close()

    # ------------------------------------------------------------ loading
    def _reload(self) -> None:
        if not self._manifest or not self._tiles or self.lod.currentIndex() < 0:
            return
        if self._loader is not None and self._loader.isRunning():
            self._pending = True
            return
        lod = self.lod.currentIndex()
        count = triangle_count(self._manifest, self._tiles, lod)
        if count > TRIANGLE_BUDGET:
            self.status.setText(f"{len(self._tiles)} tiles at LOD {lod} have {count:,} triangles, above the "
                                f"{TRIANGLE_BUDGET:,} preview budget. Select fewer tiles or a coarser LOD.")
            return
        self.status.setText(f"Loading {len(self._tiles)} tiles, {count:,} triangles…")
        self._loader = _Loader(self._manifest, self._tiles, lod, self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self.status.setText)
        self._loader.finished.connect(self._on_finished)
        self._loader.start()

    def _on_finished(self) -> None:
        if self._pending:
            self._pending = False
            self._reload()

    def _on_loaded(self, data: dict) -> None:
        key = tuple(self._tiles)
        first = self._framed != key
        self._framed = key
        self._data = data
        self._redraw()
        if first:
            self._reset_camera()
        if data:
            self.status.setText(f"{len(self._tiles)} tiles, LOD {self.lod.currentIndex()}: "
                                f"{len(data['faces']):,} triangles, {len(data['points']):,} vertices. "
                                "Left drag rotates, right drag or wheel zooms, middle drag pans.")

    # ------------------------------------------------------------ drawing
    def _redraw(self) -> None:
        import pyvista as pv

        if self._actor is not None:
            self.plotter.remove_actor(self._actor, render=False)
            self._actor = None
        if not self._data:
            self.plotter.render()
            return
        mesh = pv.PolyData.from_regular_faces(self._data["points"], self._data["faces"])
        mesh.point_data["Normals"] = self._data["normals"]
        mesh.point_data.active_normals_name = "Normals"
        mode = self.color.currentIndex()
        options = dict(smooth_shading=True, show_scalar_bar=False, show_edges=self.wire.isChecked(),
                       edge_color="#5a636e", line_width=0.5, specular=0.05)
        if mode == 0 or (mode == MATERIAL_MODE and not self._material_ready()):
            z = self._data["points"][:, 2]
            lo, hi = self._manifest["source"]["height_range_m"]
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
                                "(albedo and masks; lighting without normal maps)")

    def _rescale(self) -> None:
        if self._actor is not None:
            self._actor.scale = (1.0, 1.0, self.exaggeration.value())
            self.plotter.render()

    def _reset_camera(self) -> None:
        if not self._data:
            return
        self.plotter.view_isometric()
        self.plotter.reset_camera()
        self.plotter.camera.zoom(1.3)
        self.plotter.render()
