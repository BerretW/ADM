"""Local external asset discovery and explicit permission checks."""

import json
from pathlib import Path
import re

FORMATS = {"FBX": ".fbx", "BLEND": ".blend", "ADM": ".adm", "ADM_ANIM": ".adm_anim"}
UNCLEAR = re.compile(
    r"\b(?:unknown|unclear|unsure|unlicensed|pending|tbd|"
    r"not sure|not known|no license|to be determined)\b", re.IGNORECASE)
PLACEHOLDERS = {"none", "n/a", "na", "?", "creator or source url",
                "license name or description of permission"}


def discover(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return {kind: [] for kind in FORMATS}
    files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.lower())
    return {kind: [p for p in files if p.suffix.lower() == suffix]
            for kind, suffix in FORMATS.items()}


def permission(path):
    """Require a sidecar specific to this filename and permission for local testing."""
    sidecar = Path(str(path) + ".rights.json")
    try:
        with sidecar.open(encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError, UnicodeError) as exc:
        return False, f"rights manifest missing or unreadable ({exc})"
    if not isinstance(data, dict):
        return False, "rights manifest must be a JSON object"
    if data.get("asset") != path.name:
        return False, "rights manifest asset must match the complete filename"
    if data.get("permission_for_local_testing") is not True:
        return False, "rights manifest must explicitly permit local testing"
    for field in ("source", "license"):
        value = data.get(field)
        if (not isinstance(value, str) or not value.strip()
                or value.strip().lower() in PLACEHOLDERS or UNCLEAR.search(value)):
            return False, f"rights manifest {field} is missing or unclear"
    return True, "explicit local testing permission recorded"
