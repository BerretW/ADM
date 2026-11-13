"""Compatibility shim: the bpy-free mapper lives in ``core.rolemap``."""

from ..core.rolemap import auto_map, suggest_role  # noqa: F401

