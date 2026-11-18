"""Semantic ADM manifest comparisons for QA reports."""

import math


_NON_SEMANTIC_TOP_LEVEL = frozenset(("accessors", "bufferViews", "buffers"))
_ENCODING_FIELDS = frozenset(("byteLength", "byteOffset", "bufferView", "chunkId"))
_ABS_TOLERANCE = 1e-6
_REL_TOLERANCE = 1e-6


def _pointer(path, part):
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _is_accessor_reference(key, path):
    if key in ("attributes", "indices", "targets") and "/meshes/" in path:
        return True
    if key in ("input", "output") and "/animations/" in path:
        return True
    return key == "inverseBindMatrices" and "/skins/" in path


def _record_change(changes, path, kind, max_changes, total):
    total[0] += 1
    if len(changes) < max_changes:
        changes.append({"path": path or "/", "change": kind})


def _compare(before, after, path, changes, max_changes, total):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if not path and key in _NON_SEMANTIC_TOP_LEVEL:
                continue
            if key in _ENCODING_FIELDS or _is_accessor_reference(key, path):
                continue
            child_path = _pointer(path, key)
            if key not in before:
                _record_change(changes, child_path, "added", max_changes, total)
            elif key not in after:
                _record_change(changes, child_path, "removed", max_changes, total)
            else:
                _compare(before[key], after[key], child_path, changes, max_changes, total)
        return

    if isinstance(before, list) and isinstance(after, list):
        common_length = min(len(before), len(after))
        for index in range(common_length):
            _compare(before[index], after[index], _pointer(path, index),
                     changes, max_changes, total)
        for index in range(common_length, len(before)):
            _record_change(changes, _pointer(path, index), "removed", max_changes, total)
        for index in range(common_length, len(after)):
            _record_change(changes, _pointer(path, index), "added", max_changes, total)
        return

    if (isinstance(before, (int, float)) and not isinstance(before, bool)
            and isinstance(after, (int, float)) and not isinstance(after, bool)):
        if math.isclose(before, after, rel_tol=_REL_TOLERANCE, abs_tol=_ABS_TOLERANCE):
            return
    elif type(before) is type(after) and before == after:
        return

    _record_change(changes, path, "changed", max_changes, total)


def compare_adm_manifests(before, after, max_changes=500):
    """Return bounded JSON-pointer differences between ADM manifest properties.

    Binary accessors and their storage references are excluded because their values
    require decoded-payload comparisons; Blender integration tests verify those.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise TypeError("ADM manifests must be dictionaries")
    if type(max_changes) is not int or max_changes < 1:
        raise ValueError("max_changes must be a positive integer")

    changes = []
    total = [0]
    _compare(before, after, "", changes, max_changes, total)
    return {
        "schema_version": 1,
        "change_count": total[0],
        "truncated": total[0] > len(changes),
        "changes": changes,
    }
