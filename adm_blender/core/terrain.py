"""Deterministic connected terrain-cell partitioning for Adaptive and Hybrid tiling."""

import heapq
import math


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


def _cell_features(samples, samples_x, samples_y, width_m, depth_m, selected):
    cells_x, cells_y = samples_x - 1, samples_y - 1
    step_x, step_y = width_m / cells_x, depth_m / cells_y
    centers, slopes = [0.0] * (cells_x * cells_y), [0.0] * (cells_x * cells_y)
    for cell in selected:
        row, column = divmod(cell, cells_x)
        i = row * samples_x + column
        h00, h10 = samples[i], samples[i + 1]
        h01, h11 = samples[i + samples_x], samples[i + samples_x + 1]
        centers[cell] = (h00 + h10 + h01 + h11) * 0.25
        gx = ((h10 + h11) - (h00 + h01)) / (2.0 * step_x)
        gy = ((h01 + h11) - (h00 + h10)) / (2.0 * step_y)
        slopes[cell] = math.hypot(gx, gy)
    return centers, slopes


def adaptive_partition(samples, samples_x, samples_y, width_m, depth_m, target_area_m2,
                       min_area_m2, max_area_m2, sensitivity=0.5, natural_boundary=0.5,
                       max_cells_per_tile=4096, allowed_cells=None, validate_samples=True,
                       max_regions=4096):
    """Partition a regular height grid into connected, terrain-aware, irregular cell regions.

    Returns a list of regions; each region is a list of row-major source-cell indices.
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

    centers, slopes = _cell_features(samples, samples_x, samples_y, width_m, depth_m, selected)
    max_slope = max(slopes[cell] for cell in selected)
    elevation_range = (max(centers[cell] for cell in selected)
                       - min(centers[cell] for cell in selected))
    allowed = set(selected)
    owner = {}
    regions = []
    seed_order = sorted(selected, key=lambda cell: (-slopes[cell], cell))
    seed_index = 0

    while len(owner) < count:
        remaining_count = count - len(owner)
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
        while seed_index < len(seed_order) and seed_order[seed_index] in owner:
            seed_index += 1
        if seed_index == len(seed_order):
            raise ValueError("terrain partition could not seed all remaining components")
        if len(regions) >= max_regions:
            raise ValueError(f"partition exceeds the {max_regions} region limit")
        seed = seed_order[seed_index]
        region_index = len(regions)
        region = [seed]
        regions.append(region)
        owner[seed] = region_index
        frontier = []
        queued = set()

        def add_frontier(from_cell):
            for candidate in _neighbors(from_cell, cells_x, cells_y):
                if candidate not in allowed or candidate in owner or candidate in queued:
                    continue
                distance = math.hypot(
                    (candidate % cells_x) - (seed % cells_x),
                    (candidate // cells_x) - (seed // cells_x))
                slope_delta = abs(slopes[candidate] - slopes[seed]) / max(max_slope, 1e-12)
                elevation_delta = abs(centers[candidate] - centers[from_cell]) / max(elevation_range, 1e-12)
                compactness = distance / max(math.sqrt(target_size), 1.0)
                score = sensitivity * slope_delta + natural_boundary * elevation_delta + 0.35 * compactness
                heapq.heappush(frontier, (score, candidate))
                queued.add(candidate)

        add_frontier(seed)
        while len(region) < target_size and frontier:
            _score, candidate = heapq.heappop(frontier)
            if candidate in owner:
                continue
            owner[candidate] = region_index
            region.append(candidate)
            add_frontier(candidate)
    if min_cells > 1:
        while True:
            small = next((index for index, region in enumerate(regions)
                          if region and len(region) < min_cells), None)
            if small is None:
                break
            neighbors = {owner[neighbor]
                         for cell in regions[small]
                         for neighbor in _neighbors(cell, cells_x, cells_y)
                         if neighbor in owner and owner[neighbor] != small and regions[owner[neighbor]]}
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
