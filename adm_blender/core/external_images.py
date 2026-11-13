"""Path and integrity helpers for portable external ADM image references."""

import hashlib
import os
import re
from pathlib import Path, PurePosixPath


_URI_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}


def normalize_image_uri(uri):
    if not isinstance(uri, str) or not uri or "\\" in uri or "\x00" in uri:
        raise ValueError("URI must be a non-empty normalized relative path using '/'")
    if uri.startswith("/") or ":" in uri or uri.startswith("//"):
        raise ValueError("URI must not be absolute or contain a scheme")
    parts = uri.split("/")
    if any(part in ("", ".", "..") or part.endswith(".") or not _URI_SEGMENT.fullmatch(part)
           or part.split(".", 1)[0].lower() in _WINDOWS_RESERVED for part in parts):
        raise ValueError("URI contains an invalid or traversal path segment")
    if PurePosixPath(uri).as_posix() != uri:
        raise ValueError("URI is not normalized")
    return uri


def resolve_image_uri(asset_root, uri, *, must_exist=False):
    """Resolve a portable URI and reject filesystem/symlink escapes from the asset root."""
    relative = normalize_image_uri(uri)
    root = Path(asset_root).resolve(strict=True)
    candidate = (root / Path(*relative.split("/"))).resolve(strict=must_exist)
    try:
        if os.path.commonpath((os.fspath(root), os.fspath(candidate))) != os.fspath(root):
            raise ValueError("resolved image path escapes the asset root")
    except ValueError as exc:
        raise ValueError("resolved image path escapes the asset root") from exc
    return candidate


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def valid_sha256(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None
