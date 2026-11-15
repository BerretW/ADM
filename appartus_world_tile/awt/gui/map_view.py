"""2D overview: hillshaded heightmap or biome maps, tile grid, per-tile density, selection and biome paint."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

_SELECT = QColor(255, 196, 64)
_GRID = QColor(120, 210, 255, 150)
_MARK = QColor(240, 110, 90)


def _ramp(value: float) -> QColor:
    """Blue (sparse) -> yellow -> red (dense), semi-transparent."""
    value = min(1.0, max(0.0, value))
    if value < 0.5:
        k = value / 0.5
        return QColor(int(40 + 215 * k), int(110 + 120 * k), int(220 - 180 * k), 95)
    k = (value - 0.5) / 0.5
    return QColor(255, int(230 - 180 * k), int(40 - 20 * k), 110)


class MapView(QWidget):
    selectionChanged = Signal()
    tileActivated = Signal(int, int)  # ix, iy
    # Paint mode: (col, row) sample positions along the stroke, erase flag; then the stroke end.
    paintStroke = Signal(object, bool)
    paintFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)
        self._image: QImage | None = None
        self._cols = 0  # source samples
        self._rows = 0
        self._tile = 0
        self._nx = 0
        self._ny = 0
        self._density: dict[tuple[int, int], float] = {}
        self._info: dict[tuple[int, int], str] = {}
        self.selection: set[tuple[int, int]] = set()
        self._drag_start: tuple[int, int] | None = None
        self._drag_now: tuple[int, int] | None = None
        self._message = "Open a heightmap or a tile manifest"
        self._show_density = False
        self._marked: set[tuple[int, int]] = set()
        self._paint_mode = False
        self._brush = 32.0  # radius in source samples
        self._stroke: tuple[float, float] | None = None
        self._erase = False
        self._hover: QPointF | None = None

    # ----------------------------------------------------------------- data
    def set_image(self, image: np.ndarray | None, cols: int, rows: int) -> None:
        """``image`` is grayscale (H, W) or RGB (H, W, 3) uint8."""
        if image is None:
            self._image = None
        else:
            image = np.ascontiguousarray(image, dtype=np.uint8)
            height, width = image.shape[:2]
            if image.ndim == 3:
                self._image = QImage(image.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
            else:
                self._image = QImage(image.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
        self._cols, self._rows = cols, rows
        self.update()

    def set_density_visible(self, visible: bool) -> None:
        self._show_density = visible
        self.update()

    def set_grid(self, tile_cells: int) -> None:
        self._tile = tile_cells
        if self._cols > 1 and tile_cells > 0:
            self._nx = max(1, -(-(self._cols - 1) // tile_cells))
            self._ny = max(1, -(-(self._rows - 1) // tile_cells))
        else:
            self._nx = self._ny = 0
        self.selection = {t for t in self.selection if t[0] < self._nx and t[1] < self._ny}
        self.update()

    def set_stats(self, density: dict, info: dict) -> None:
        """``density`` maps (ix, iy) to 0..1, ``info`` to a tooltip string."""
        self._density = density
        self._info = info
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def set_marked(self, tiles: set[tuple[int, int]]) -> None:
        """Tiles flagged with a corner marker, e.g. not exported since they changed."""
        self._marked = set(tiles)
        self.update()

    def set_paint_mode(self, enabled: bool) -> None:
        self._paint_mode = enabled
        self._stroke = None
        self._drag_start = self._drag_now = None
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_brush(self, radius_samples: float) -> None:
        self._brush = max(0.5, float(radius_samples))
        self.update()

    def grid_size(self) -> tuple[int, int]:
        return self._nx, self._ny

    # ------------------------------------------------------------ geometry
    def _frame(self) -> QRectF:
        if self._cols < 2:
            return QRectF()
        margin = 12
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        scale = min(avail_w / (self._cols - 1), avail_h / (self._rows - 1))
        w = (self._cols - 1) * scale
        h = (self._rows - 1) * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _tile_rect(self, frame: QRectF, ix: int, iy: int) -> QRectF:
        sx = frame.width() / (self._cols - 1)
        sy = frame.height() / (self._rows - 1)
        tj = self._ny - 1 - iy  # iy counts from the south, rows from the north
        x0 = ix * self._tile
        y0 = tj * self._tile
        x1 = min(self._cols - 1, x0 + self._tile)
        y1 = min(self._rows - 1, y0 + self._tile)
        return QRectF(frame.left() + x0 * sx, frame.top() + y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy)

    def _sample_at(self, pos: QPointF) -> tuple[float, float] | None:
        frame = self._frame()
        if frame.isEmpty():
            return None
        col = (pos.x() - frame.left()) / frame.width() * (self._cols - 1)
        row = (pos.y() - frame.top()) / frame.height() * (self._rows - 1)
        return col, row

    def _tile_at(self, pos: QPointF) -> tuple[int, int] | None:
        frame = self._frame()
        if not self._nx or not frame.contains(pos):
            return None
        col = (pos.x() - frame.left()) / frame.width() * (self._cols - 1)
        row = (pos.y() - frame.top()) / frame.height() * (self._rows - 1)
        ix = min(self._nx - 1, int(col // self._tile))
        tj = min(self._ny - 1, int(row // self._tile))
        return ix, self._ny - 1 - tj

    # --------------------------------------------------------------- paint
    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 27, 31))
        frame = self._frame()
        if frame.isEmpty():
            painter.setPen(QColor(150, 158, 168))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return
        if self._image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(frame, self._image)
        if self._nx:
            for (ix, iy), value in (self._density.items() if self._show_density else ()):
                if ix < self._nx and iy < self._ny:
                    painter.fillRect(self._tile_rect(frame, ix, iy), _ramp(value))
            painter.setPen(QPen(_GRID, 1))
            sx = frame.width() / (self._cols - 1)
            sy = frame.height() / (self._rows - 1)
            if self._nx <= 256:
                for i in range(1, self._nx):
                    x = frame.left() + i * self._tile * sx
                    painter.drawLine(QPointF(x, frame.top()), QPointF(x, frame.bottom()))
            if self._ny <= 256:
                for j in range(1, self._ny):
                    y = frame.top() + j * self._tile * sy
                    painter.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))
            if self._marked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_MARK)
                for ix, iy in self._marked:
                    if ix < self._nx and iy < self._ny:
                        rect = self._tile_rect(frame, ix, iy)
                        side = max(4.0, min(12.0, rect.width() * 0.3, rect.height() * 0.3))
                        corner = rect.topRight()
                        painter.drawPolygon([corner, QPointF(corner.x() - side, corner.y()),
                                             QPointF(corner.x(), corner.y() + side)])
            painter.setBrush(QColor(255, 196, 64, 40))
            painter.setPen(QPen(_SELECT, 2))
            for ix, iy in self.selection:
                painter.drawRect(self._tile_rect(frame, ix, iy))
            if self._drag_start and self._drag_now:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_SELECT, 1, Qt.PenStyle.DashLine))
                painter.drawRect(self._drag_rect(frame))
        painter.setPen(QColor(90, 98, 108))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        if self._paint_mode and self._hover is not None:
            radius = self._brush * frame.width() / (self._cols - 1)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            painter.drawEllipse(self._hover, radius, radius)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 1, Qt.PenStyle.DotLine))
            painter.drawEllipse(self._hover, radius + 1, radius + 1)

    def _drag_rect(self, frame: QRectF) -> QRectF:
        a = self._tile_rect(frame, *self._drag_start)
        b = self._tile_rect(frame, *self._drag_now)
        return a.united(b)

    # --------------------------------------------------------------- mouse
    def _paint_to(self, pos: QPointF) -> None:
        sample = self._sample_at(pos)
        if sample is None:
            return
        start = self._stroke or sample
        dx, dy = sample[0] - start[0], sample[1] - start[1]
        steps = max(1, int((dx * dx + dy * dy) ** 0.5 / max(0.5, self._brush * 0.35)))
        points = [(start[0] + dx * k / steps, start[1] + dy * k / steps) for k in range(1 if self._stroke else 0,
                                                                                         steps + 1)]
        self._stroke = sample
        if points:
            self.paintStroke.emit(points, self._erase)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if self._paint_mode:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self._erase = event.button() == Qt.MouseButton.RightButton
                self._stroke = None
                self._paint_to(event.position())
            return
        tile = self._tile_at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and tile:
            self._drag_start = self._drag_now = tile
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._paint_mode:
            self._hover = event.position()
            if self._stroke is not None:
                self._paint_to(event.position())
            self.update()
            return
        tile = self._tile_at(event.position())
        if self._drag_start and tile and tile != self._drag_now:
            self._drag_now = tile
            self.update()
        if tile:
            text = f"Tile x{tile[0]:03d}_y{tile[1]:03d}"
            if tile in self._info:
                text += "\n" + self._info[tile]
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._paint_mode:
            if self._stroke is not None:
                self._stroke = None
                self.paintFinished.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_start:
            return
        (x0, y0), (x1, y1) = self._drag_start, self._drag_now
        tiles = {(ix, iy) for ix in range(min(x0, x1), max(x0, x1) + 1)
                 for iy in range(min(y0, y1), max(y0, y1) + 1)}
        additive = event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        if additive:
            if len(tiles) == 1 and tiles <= self.selection:
                self.selection -= tiles
            else:
                self.selection |= tiles
        else:
            self.selection = tiles
        self._drag_start = self._drag_now = None
        self.update()
        self.selectionChanged.emit()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if self._paint_mode:
            return
        tile = self._tile_at(event.position())
        if tile:
            self.selection = {tile}
            self.update()
            self.selectionChanged.emit()
            self.tileActivated.emit(*tile)

    def select_all(self) -> None:
        self.selection = {(ix, iy) for ix in range(self._nx) for iy in range(self._ny)}
        self.update()
        self.selectionChanged.emit()

    def select_center(self, count: int) -> None:
        """Select a block of about ``count`` tiles around the centre."""
        side = max(1, int(count ** 0.5))
        cx, cy = self._nx // 2, self._ny // 2
        x0 = max(0, cx - side // 2)
        y0 = max(0, cy - side // 2)
        self.selection = {(ix, iy) for ix in range(x0, min(self._nx, x0 + side))
                          for iy in range(y0, min(self._ny, y0 + side))}
        self.update()
        self.selectionChanged.emit()
