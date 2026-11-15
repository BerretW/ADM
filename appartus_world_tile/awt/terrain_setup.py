"""Terrain-type starting points for the biome setup wizard."""

from __future__ import annotations

import copy

import numpy as np

from .material import TerrainMaterial, default_biomes

PROFILES = {
    "current": ("Keep current rules", "Start from the biome rules already in this project."),
    "temperate": ("Temperate", "Balanced water, shore and snow bands fitted to this heightmap."),
    "alpine": ("Alpine", "Snow begins lower and rocky high ground becomes more prominent."),
    "coastal": ("Coastal / island", "A wider shoreline and a higher, more localized snow band."),
    "arid": ("Arid", "A sandy lowland, narrow shoreline and no automatic snow."),
}


def profile_levels(heights_m: np.ndarray, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"Unknown terrain type {profile!r}")
    heights = np.asarray(heights_m, dtype=np.float64)
    if heights.size == 0 or not np.isfinite(heights).all():
        raise ValueError("A terrain profile needs finite height samples")

    levels = TerrainMaterial.fitted_levels(heights)
    if profile == "current":
        return levels

    lo, hi = float(heights.min()), float(heights.max())
    span = max(hi - lo, 1e-6)
    p70, p85, p98, p995 = (float(value) for value in np.percentile(heights, (70, 85, 98, 99.5)))
    if profile == "alpine":
        snow_start = p70
        levels.update(water_m=lo + 0.01 * span, shore_m=max(0.5, 0.008 * span),
                      snow_start_m=snow_start, snow_full_m=max(p85, snow_start + 0.01 * span),
                      depth_m=max(0.5, 0.008 * span))
    elif profile == "coastal":
        snow_start = p98
        levels.update(water_m=lo + 0.04 * span, shore_m=max(1.0, 0.06 * span),
                      snow_start_m=snow_start, snow_full_m=max(p995, snow_start + 0.005 * span),
                      depth_m=max(0.5, 0.008 * span))
    elif profile == "arid":
        levels.update(water_m=lo + 0.005 * span, shore_m=max(0.5, 0.015 * span),
                      snow_start_m=hi + 0.02 * span, snow_full_m=hi + 0.04 * span,
                      depth_m=max(0.5, 0.005 * span))
    return levels


def apply_profile(material: TerrainMaterial, heights_m: np.ndarray, profile: str) -> dict:
    """Apply fitted default bands by known biome/surface names without replacing the user's library."""
    levels = profile_levels(heights_m, profile)
    if profile == "current":
        return levels

    templates = {biome.name: biome for biome in default_biomes(**levels)}
    for biome in material.biomes:
        template = templates.get(biome.name)
        if template is None:
            continue
        biome.height = copy.deepcopy(template.height)
        template_entries = {entry.surface: entry for entry in template.surfaces}
        for entry in biome.surfaces:
            if entry.surface in template_entries:
                entry.height = copy.deepcopy(template_entries[entry.surface].height)

    if profile == "arid" and "sand" in material.surface_names():
        lowland = next((biome for biome in material.biomes if biome.name == "lowland"), None)
        if lowland and lowland.surfaces and not any(entry.surface == "sand" for entry in lowland.surfaces):
            lowland.surfaces[0].surface = "sand"
    return levels
