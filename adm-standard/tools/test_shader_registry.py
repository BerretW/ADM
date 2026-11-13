#!/usr/bin/env python3
import json
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from adm_blender.core import constants as K
from adm_blender.core.validate import param_value_error

registry_path = root / "adm-standard" / "shaders" / "registry.json"
registry = json.loads(registry_path.read_text(encoding="utf-8"))
entries = registry["shaders"]
assert registry["registryVersion"] == "1.0.0"
assert len(entries) == 20
assert len(entries) == len({(entry["id"], entry["version"]) for entry in entries})
assert all(re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", entry["id"]) for entry in entries)
assert all(entry["version"] == "1.0.0" for entry in entries)
assert {(entry["id"], entry["version"]) for entry in entries} == set(K.OFFICIAL_SHADERS)
assert { (entry["id"], entry["version"]): entry["parameters"] for entry in entries } == K.OFFICIAL_SHADERS
assert set(K.OFFICIAL_SHADER_KINDS) == set(K.OFFICIAL_SHADERS)
assert set(K.OFFICIAL_SHADER_KEYS.values()) == set(K.OFFICIAL_SHADER_KINDS)
for entry in entries:
    relative_path = entry["contract"].split("#", 1)[0]
    contract = (root / "adm-standard" / "shaders" / relative_path).resolve()
    assert contract.is_file(), f"missing contract: {contract}"
    assert entry["id"] in contract.read_text(encoding="utf-8"), f"profile missing from contract: {entry['id']}"
    names = [p["name"] for p in entry["parameters"]]
    assert len(names) == len(set(names)), f"duplicate parameter in {entry['id']}"
    for prm in entry["parameters"]:
        assert prm.get("description", "").strip(), f"missing description: {entry['id']}/{prm['name']}"
        assert prm["type"] in K.SHADER_PARAM_TYPES, f"invalid type: {entry['id']}/{prm['name']}"
        assert not param_value_error(prm, prm["default"], None), f"invalid default: {entry['id']}/{prm['name']}"
print(f"PASS shader registry ({len(entries)} official profiles)")
