"""Editable road centre lines in heightmap sample coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Road:
    surface: str
    width_m: float = 6.0
    shoulder_m: float = 3.0
    points: list[list[float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"surface": self.surface, "width_m": float(self.width_m), "shoulder_m": float(self.shoulder_m),
                "points": [[float(v) for v in point] for point in self.points]}

    def validate(self, width: int, height: int, complete: bool = True) -> None:
        if not math.isfinite(self.width_m) or self.width_m <= 0:
            raise ValueError("Road width must be positive")
        if not math.isfinite(self.shoulder_m) or self.shoulder_m < 0:
            raise ValueError("Road shoulder must not be negative")
        if complete and len(self.points) < 2:
            raise ValueError("Each road needs at least two control points")
        for point in self.points:
            if len(point) != 3 or not all(math.isfinite(v) for v in point):
                raise ValueError("Road control points need finite x, y and height")
            if not (0 <= point[0] <= width - 1 and 0 <= point[1] <= height - 1):
                raise ValueError("A road control point is outside the heightmap")
        if any(a[:2] == b[:2] for a, b in zip(self.points, self.points[1:])):
            raise ValueError("Adjacent road control points cannot occupy the same position")


def segments(road: Road, spacing: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Approximate the centre curve with a smooth, monotone elevation profile."""
    points = np.asarray(road.points, dtype=np.float64)
    curves = []
    distances = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        before = points[max(0, i - 1)]
        after = points[min(len(points) - 1, i + 2)]
        length = np.linalg.norm(b[:2] - a[:2])
        steps = max(1, int(math.ceil(length / max(0.5, road.width_m / spacing / 4))))
        curve = [a[:2]]
        for j in range(1, steps + 1):
            t = j / steps
            xy = 0.5 * ((2 * a[:2]) + (-before[:2] + b[:2]) * t
                        + (2 * before[:2] - 5 * a[:2] + 4 * b[:2] - after[:2]) * t * t
                        + (-before[:2] + 3 * a[:2] - 3 * b[:2] + after[:2]) * t * t * t)
            curve.append(xy)
        curve = np.asarray(curve)
        distance = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))))
        if distance[-1] <= 1e-12:
            raise ValueError("Adjacent road control points cannot occupy the same position")
        curves.append(curve)
        distances.append(distance)
    if not curves:
        return []
    lengths = np.array([distance[-1] for distance in distances])
    slopes = np.diff(points[:, 2]) / lengths
    tangents = np.empty(len(points), np.float64)
    tangents[0], tangents[-1] = slopes[0], slopes[-1]
    for i in range(1, len(points) - 1):
        if slopes[i - 1] * slopes[i] <= 0:
            tangents[i] = 0.0
        else:
            w1 = 2 * lengths[i] + lengths[i - 1]
            w2 = lengths[i] + 2 * lengths[i - 1]
            tangents[i] = (w1 + w2) / (w1 / slopes[i - 1] + w2 / slopes[i])
    result = []
    for i, (curve, distance) in enumerate(zip(curves, distances)):
        t = distance / lengths[i]
        heights = ((2 * t**3 - 3 * t**2 + 1) * points[i, 2]
                   + (t**3 - 2 * t**2 + t) * lengths[i] * tangents[i]
                   + (-2 * t**3 + 3 * t**2) * points[i + 1, 2]
                   + (t**3 - t**2) * lengths[i] * tangents[i + 1])
        path = np.column_stack((curve, heights))
        result.extend(zip(path[:-1], path[1:]))
    return result


def rasterize(road: Road, spacing: float, rows: int, cols: int, cell: int = 1, cell_centres: bool = False):
    """Yield bounded raster windows with the closest centreline distance and elevation."""
    pieces = segments(road, spacing)
    if not pieces:
        raise ValueError("A road needs at least two control points")
    reach = (road.width_m / 2 + road.shoulder_m) / spacing
    offset = cell / 2 if cell_centres else 0.0
    block_size = 256
    blocks = {}
    for a, b in pieces:
        x0 = max(0, int(math.floor((min(a[0], b[0]) - reach - offset) / cell)))
        x1 = min(cols, int(math.ceil((max(a[0], b[0]) + reach - offset) / cell)) + 1)
        y0 = max(0, int(math.floor((min(a[1], b[1]) - reach - offset) / cell)))
        y1 = min(rows, int(math.ceil((max(a[1], b[1]) + reach - offset) / cell)) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        for by in range(y0 // block_size, (y1 - 1) // block_size + 1):
            for bx in range(x0 // block_size, (x1 - 1) // block_size + 1):
                blocks.setdefault((bx, by), []).append((a, b, x0, x1, y0, y1))
    if not blocks:
        raise ValueError("Road does not intersect the heightmap")
    for (bx, by), candidates in blocks.items():
        x0, y0 = bx * block_size, by * block_size
        x1, y1 = min(cols, x0 + block_size), min(rows, y0 + block_size)
        distance = np.full((y1 - y0, x1 - x0), np.inf, np.float32)
        elevation = np.zeros_like(distance)
        for a, b, left, right, top, bottom in candidates:
            bx0, bx1 = max(x0, left), min(x1, right)
            by0, by1 = max(y0, top), min(y1, bottom)
            yy, xx = np.ogrid[by0:by1, bx0:bx1]
            xx = xx * cell + offset
            yy = yy * cell + offset
            dx, dy = b[0] - a[0], b[1] - a[1]
            length2 = dx * dx + dy * dy
            if length2 <= 1e-20:
                continue
            t = np.clip(((xx - a[0]) * dx + (yy - a[1]) * dy) / length2, 0, 1)
            d = np.sqrt((xx - a[0] - t * dx) ** 2 + (yy - a[1] - t * dy) ** 2) * spacing
            window = np.s_[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
            replace = d < distance[window]
            distance[window][replace] = d[replace]
            elevation[window][replace] = (a[2] + t * (b[2] - a[2]))[replace]
        yield (slice(y0, y1), slice(x0, x1)), distance, elevation
