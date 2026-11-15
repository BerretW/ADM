"""Deterministic connected terrain-cell partitioning for Adaptive and Hybrid tiling."""

import heapq
import math
from itertools import accumulate


def _neighbors(cell, cells_x, cells_y):
    row, column = divmod(cell, cells_x)
    if row:
        yield cell - cells_x
    if column:
        yield cell - 1
    if column + 1 < cells_x:
        yield cell + 1
    if row + 1 < cells_y:
        yield cell + cells_x


def _box_blur(values, width, height, radius):
    """Separable box average over a row-major width x height grid; edges use the clipped window."""
    if radius < 1:
        return values
    rows = []
    for y in range(height):
        prefix = [0.0, *accumulate(values[y * width:(y + 1) * width])]
        rows.extend((prefix[min(width, x + radius + 1)] - prefix[max(0, x - radius)])
                    / (min(width, x + radius + 1) - max(0, x - radius)) for x in range(width))
    result = [0.0] * (width * height)
    for x in range(width):
        prefix = [0.0, *accumulate(rows[x::width])]
        result[x::width] = [(prefix[min(height, y + radius + 1)] - prefix[max(0, y - radius)])
                            / (min(height, y + radius + 1) - max(0, y - radius)) for y in range(height)]
    return result


def _cell_features(samples, samples_x, samples_y, width_m, depth_m, bounds, radius):
    """Cell centre heights and slopes over a cell rectangle, smoothed at the tile scale.

    Per-cell slopes of a high-resolution heightmap are dominated by noise; growing regions on them
    leaves single-cell holes everywhere, so features are box-averaged over ``radius`` cells.
    """
    x0, x1, y0, y1 = bounds
    step_x, step_y = width_m / (samples_x - 1), depth_m / (samples_y - 1)
    centers, slopes = [], []
    for row in range(y0, y1):
        for column in range(x0, x1):
            i = row * samples_x + column
            h00, h10 = samples[i], samples[i + 1]
            h01, h11 = samples[i + samples_x], samples[i + samples_x + 1]
            centers.append((h00 + h10 + h01 + h11) * 0.25)
            slopes.append(math.hypot(((h10 + h11) - (h00 + h01)) / (2.0 * step_x),
                                     ((h01 + h11) - (h00 + h10)) / (2.0 * step_y)))
    width, height = x1 - x0, y1 - y0
    return _box_blur(centers, width, height, radius), _box_blur(slopes, width, height, radius)


def adaptive_partition(samples, samples_x, samples_y, width_m, depth_m, target_area_m2,
                       min_area_m2, max_area_m2, sensitivity=0.5, natural_boundary=0.5,
                       max_cells_per_tile=4096, allowed_cells=None, validate_samples=True,
                       max_regions=4096, progress=None):
    """Partition a regular height grid into connected, terrain-aware, irregular cell regions.

    Returns a list of regions; each region is a list of row-major source-cell indices.
    ``progress`` is called with the assigned fraction (0-1) while regions grow.
    """
    values = (width_m, depth_m, target_area_m2, min_area_m2, max_area_m2,
              sensitivity, natural_boundary)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("terrain partition settings and heights must be finite")
    if samples_x < 2 or samples_y < 2 or len(samples) != samples_x * samples_y:
        raise ValueError("height sample count must match a grid of at least 2 x 2 samples")
    if width_m <= 0 or depth_m <= 0:
        raise ValueError("terrain width and depth must be positive")
    if min_area_m2 <= 0 or max_area_m2 < min_area_m2 or target_area_m2 <= 0:
        raise ValueError("tile areas must be positive and minimum area cannot exceed maximum area")
    if not 0 <= sensitivity <= 1 or not 0 <= natural_boundary <= 1:
        raise ValueError("terrain sensitivity and natural-boundary preference must be in [0, 1]")
    if max_cells_per_tile < 1 or max_regions < 1:
        raise ValueError("maximum cells per tile and maximum regions must be positive")
    if validate_samples and not all(math.isfinite(value) for value in samples):
        raise ValueError("height samples contain NaN or infinity")

    cells_x, cells_y = samples_x - 1, samples_y - 1
    total_cells = cells_x * cells_y
    selected = sorted(set(range(total_cells) if allowed_cells is None else allowed_cells))
    if not selected or selected[0] < 0 or selected[-1] >= total_cells:
        raise ValueError("partition must contain valid terrain cells")

    cell_area = width_m * depth_m / total_cells
    if not math.isfinite(cell_area) or cell_area <= 0:
        raise ValueError("terrain cell area must be finite and positive")
    min_cells = max(1, int(math.ceil(min_area_m2 / cell_area - 1e-12)))
    max_cells = min(max_cells_per_tile, int(math.floor(max_area_m2 / cell_area + 1e-12)))
    if max_cells < 1:
        raise ValueError("maximum tile area is smaller than one terrain grid cell")
    count = len(selected)
    target_cells = max(1, int(math.floor(target_area_m2 / cell_area + 0.5)))
    if count < min_cells and count > max_cells:
        raise ValueError("tile area limits cannot partition this grid; adjust minimum/maximum area")
    if count > max_cells and min_cells > max_cells:
        raise ValueError(
            f"tile area limits cannot partition this grid: Minimum Area needs {min_cells} cells "
            f"but at most {max_cells} cells fit in a tile ({max_cells * cell_area:.0f} m2); raise "
            f"Maximum Cells per Tile or lower Minimum Area")

    x0 = min(cell % cells_x for cell in selected)
    x1 = max(cell % cells_x for cell in selected) + 1
    y0, y1 = selected[0] // cells_x, selected[-1] // cells_x + 1
    box_width = x1 - x0
    radius = int(math.sqrt(min(target_cells, max_cells)) / 8)
    centers, slopes = _cell_features(samples, samples_x, samples_y, width_m, depth_m,
                                     (x0, x1, y0, y1), radius)

    def local(cell):
        row, column = divmod(cell, cells_x)
        return (row - y0) * box_width + column - x0

    max_slope = max(slopes[local(cell)] for cell in selected)
    selected_centers = [centers[local(cell)] for cell in selected]
    elevation_range = max(selected_centers) - min(selected_centers)
    del selected_centers
    allowed = bytearray(total_cells)
    for cell in selected:
        allowed[cell] = 1
    owner = [-1] * total_cells
    assigned = 0
    regions = []
    seed_order = sorted(selected, key=lambda cell: (-slopes[local(cell)], cell))
    seed_index = 0
    report_step = max(1, count // 100)
    next_report = report_step

    while assigned < count:
        remaining_count = count - assigned
        if remaining_count >= min_cells:
            min_regions = int(math.ceil(remaining_count / max_cells))
            max_regions_possible = max(1, remaining_count // min_cells)
            if min_regions > max_regions_possible:
                raise ValueError("tile area limits cannot partition this grid; adjust minimum/maximum area")
            region_count = min(max_regions_possible,
                               max(min_regions, int(math.ceil(remaining_count / target_cells))))
            if region_count > max_regions:
                raise ValueError(f"partition exceeds the {max_regions} region limit")
            target_size = int(math.ceil(remaining_count / region_count))
        else:
            target_size = remaining_count
        while seed_index < len(seed_order) and owner[seed_order[seed_index]] >= 0:
            seed_index += 1
        if seed_index == len(seed_order):
            raise ValueError("terrain partition could not seed all remaining components")
        if len(regions) >= max_regions:
            raise ValueError(f"partition exceeds the {max_regions} region limit")
        seed = seed_order[seed_index]
        seed_row, seed_column = divmod(seed, cells_x)
        seed_slope = slopes[local(seed)]
        region_index = len(regions)
        region = [seed]
        regions.append(region)
        owner[seed] = region_index
        frontier = []
        queued = set()
        slope_scale = sensitivity / max(max_slope, 1e-12)
        elevation_scale = natural_boundary / max(elevation_range, 1e-12)
        compact_scale = 0.35 / max(math.sqrt(target_size), 1.0)

        def add_frontier(from_cell):
            from_center = centers[local(from_cell)]
            for candidate in _neighbors(from_cell, cells_x, cells_y):
                if not allowed[candidate] or owner[candidate] >= 0 or candidate in queued:
                    continue
                row, column = divmod(candidate, cells_x)
                index = (row - y0) * box_width + column - x0
                score = (slope_scale * abs(slopes[index] - seed_slope)
                         + elevation_scale * abs(centers[index] - from_center)
                         + compact_scale * math.hypot(column - seed_column, row - seed_row))
                heapq.heappush(frontier, (score, candidate))
                queued.add(candidate)

        add_frontier(seed)
        while len(region) < target_size and frontier:
            _score, candidate = heapq.heappop(frontier)
            if owner[candidate] >= 0:
                continue
            owner[candidate] = region_index
            region.append(candidate)
            add_frontier(candidate)
        assigned += len(region)
        if progress is not None and (assigned >= next_report or assigned == count):
            progress(assigned / count)
            next_report = assigned + report_step
    if min_cells > 1:
        # always merge the lowest-index undersized region first; the heap avoids rescanning every region
        pending = [index for index, region in enumerate(regions) if len(region) < min_cells]
        heapq.heapify(pending)
        while pending:
            small = heapq.heappop(pending)
            if not regions[small] or len(regions[small]) >= min_cells:
                continue
            neighbors = {owner[neighbor]
                         for cell in regions[small]
                         for neighbor in _neighbors(cell, cells_x, cells_y)
                         if owner[neighbor] >= 0 and owner[neighbor] != small and regions[owner[neighbor]]}
            candidates = sorted((len(regions[index]) + len(regions[small]), index)
                                for index in neighbors
                                if len(regions[index]) + len(regions[small]) <= max_cells)
            if not candidates:
                if len(regions[small]) == count:
                    break
                raise ValueError("minimum tile area cannot be met without breaking region connectivity")
            _combined, target = candidates[0]
            for cell in regions[small]:
                owner[cell] = target
            regions[target].extend(regions[small])
            regions[small] = []
            if len(regions[target]) < min_cells:
                heapq.heappush(pending, target)
    regions = [sorted(region) for region in regions if region]
    return regions

def sector_cells(samples_x, samples_y, width_m, depth_m, sector_width_m, sector_length_m):
    """Return row-major cell groups for regular Hybrid sectors."""
    if not all(math.isfinite(value) and value > 0 for value in
               (width_m, depth_m, sector_width_m, sector_length_m)):
        raise ValueError("hybrid sector and terrain dimensions must be finite and positive")

    def boundaries(sample_count, extent, size):
        intervals = sample_count - 1
        if intervals < 1:
            raise ValueError("terrain must contain at least two samples per axis")
        if size >= extent:
            return [0, intervals]
        step = max(1, int(math.floor(size / extent * intervals + 0.5)))
        return list(range(0, intervals, step)) + [intervals]

    cells_x = samples_x - 1
    xs = boundaries(samples_x, width_m, sector_width_m)
    ys = boundaries(samples_y, depth_m, sector_length_m)
    return [[row * cells_x + column
             for row in range(y0, y1) for column in range(x0, x1)]
            for y0, y1 in zip(ys, ys[1:])
            for x0, x1 in zip(xs, xs[1:])]
