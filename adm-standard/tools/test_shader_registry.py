#!/usr/bin/env python3
import json
import pathlib
import re
import sys
import tempfile
from copy import deepcopy

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from adm_blender.core import constants as K
from adm_blender.core.validate import param_value_error
from check_shader_registry_changes import (
    contract_digest,
    validate_revision_log,
    verify_recorded_changes,
    verify_registry,
    verify_historical_freeze_history,
    verify_revision_history,
)

registry_path = root / "adm-standard" / "shaders" / "registry.json"
registry = json.loads(registry_path.read_text(encoding="utf-8"))
entries = registry["shaders"]
assert "registryVersion" not in registry
assert len(entries) == len({(entry["id"], entry["version"]) for entry in entries})
assert all(re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", entry["id"]) for entry in entries)
assert {(entry["id"], entry["version"]) for entry in entries} == set(K.OFFICIAL_SHADERS)
assert { (entry["id"], entry["version"]): entry["parameters"] for entry in entries } == K.OFFICIAL_SHADERS
entry_by_key = {(entry["id"], entry["version"]): entry for entry in entries}
assert {key: entry_by_key[key]["capability"] for key in K.SHADER_PROFILE_CAPABILITIES} == \
    K.SHADER_PROFILE_CAPABILITIES
assert all("capability" not in entry for key, entry in entry_by_key.items()
           if key not in K.SHADER_PROFILE_CAPABILITIES)
assert set(K.OFFICIAL_SHADER_KINDS) == set(K.OFFICIAL_SHADERS)
assert set(K.OFFICIAL_SHADER_KEYS.values()) == {
    key for key in K.OFFICIAL_SHADER_KINDS if key[1] == "1.0.0"
}
edge_wear_key = (K.SHADER_CORE[0], K.SHADER_PROFILE_EDGE_WEAR)
assert K.has_color1_profile("CORE", K.SHADER_PROFILE_EDGE_WEAR)
assert not K.has_color1_profile("GLASS", K.SHADER_PROFILE_EDGE_WEAR)
edge_wear_params = {parameter["name"] for parameter in K.OFFICIAL_SHADERS[edge_wear_key]}
assert "color1_g_strength" not in edge_wear_params
assert "color1_b_strength" not in edge_wear_params
assert {"color1_g_color", "color1_b_color"} <= edge_wear_params

layered_height_profiles = {
    ("adm.terrain.four_layer", "1.1.0"): 4,
    ("adm.terrain.four_layer", "2.1.0"): 4,
    ("adm.surface.two_layer", "1.1.0"): 2,
    ("adm.pbr.layered", "2.1.0"): 4,
}
for key, layer_count in layered_height_profiles.items():
    parameters = {parameter["name"]: parameter for parameter in K.OFFICIAL_SHADERS[key]}
    assert {"height_blend_enabled", "height_blend_transition", "height_blend_strength",
            "parallax_mode", "parallax_min_steps", "parallax_max_steps"} <= set(parameters)
    assert parameters["height_blend_enabled"]["default"] is False
    assert parameters["height_blend_transition"]["default"] == 0.2
    assert parameters["height_blend_strength"]["default"] == 1.0
    mode = parameters["parallax_mode"]
    assert mode["type"] == "ENUM"
    assert mode["values"] == ["NONE", "PARALLAX", "PARALLAX_OCCLUSION"]
    assert param_value_error(mode, "PARALLAX_OCCLUSION") is None
    assert param_value_error(mode, "DISPLACEMENT")
    for index in range(layer_count):
        prefix = f"layer{index}_"
        assert {prefix + suffix for suffix in (
            "ao_texture", "ao_channel", "ao_invert", "ao_strength",
            "height_texture", "height_channel", "height_invert", "height_scale",
            "height_bias", "parallax_scale",
        )} <= set(parameters)
    old_key = (key[0], "1.0.0" if key[1] == "1.1.0" else "2.0.0")
    old_parameters = {parameter["name"] for parameter in K.OFFICIAL_SHADERS[old_key]}
    assert "height_blend_enabled" not in old_parameters

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
for kind, effects in K.COLOR1_CONTRACTS.items():
    params = {p["name"]: p for p in K.OFFICIAL_SHADERS[K.OFFICIAL_SHADER_V2_KEYS[kind]]}
    prefixes = [f"color1_{channel.lower()}" for channel, effect in zip(K.SHADER_MASK_CHANNELS, effects)
                if effect["op"] == "surface"]
    if kind == "LAYERED":
        prefixes.extend(f"layer{i}" for i in range(4))
    for prefix in prefixes:
        for prop in ("metallic", "roughness"):
            for suffix, typ in (("texture", "TEXTURE"), ("channel", "F32"), ("invert", "BOOL")):
                name = f"{prefix}_{prop}_{suffix}"
                assert name in params and params[name]["type"] == typ, f"{kind} missing {name}"

profiles, _ = verify_registry(registry, registry_path.parent)
assert len(profiles) == len(entries)
revision_log = json.loads((registry_path.parent / "revisions.json").read_text(encoding="utf-8"))
changelog = (root / "adm-standard" / "CHANGELOG.md").read_text(encoding="utf-8")
records = validate_revision_log(revision_log, changelog)
assert verify_revision_history(revision_log, {"records": []}) == records
freeze_record = json.loads((registry_path.parent / "freeze-2026-11-15.json").read_text(encoding="utf-8"))
verify_historical_freeze_history(freeze_record, freeze_record)
changed_history = deepcopy(freeze_record)
changed_history["profiles"].pop(next(iter(changed_history["profiles"])))
try:
    verify_historical_freeze_history(changed_history, freeze_record)
except ValueError as exc:
    assert "historical shader publication record changed or removed" in str(exc)
else:
    raise AssertionError("the historical publication record must remain auditable")

record = {
    "id": "test-record",
    "date": "2026-11-17",
    "summary": "Test a documented shader contract change.",
    "changelog": "CHANGELOG.md#unreleased",
    "profiles": [f'{entries[0]["id"]}@{entries[0]["version"]}'],
    "contracts": [entries[0]["contract"]],
}
verify_recorded_changes(set(record["profiles"]), set(record["contracts"]), [record])
try:
    verify_recorded_changes(set(record["profiles"]), set(record["contracts"]), [])
except ValueError as exc:
    assert "unrecorded shader profiles" in str(exc)
    assert "unrecorded shader contracts" in str(exc)
else:
    raise AssertionError("unrecorded shader changes must fail")
try:
    verify_revision_history({"records": []}, {"records": [record]})
except ValueError as exc:
    assert "changed or removed" in str(exc)
else:
    raise AssertionError("existing change records must remain in history")
try:
    verify_recorded_changes(set(), set(), [record])
except ValueError as exc:
    assert "recorded but unchanged shader profiles" in str(exc)
else:
    raise AssertionError("change records must not claim unchanged profiles")

with tempfile.TemporaryDirectory() as temporary:
    contract_dir = pathlib.Path(temporary)
    sample = contract_dir / "contract.md"
    sample.write_text("# Document\n\n## Contract\nOriginal\n\n## Other\nOriginal\n", encoding="utf-8")
    anchored = contract_digest("contract.md#contract", contract_dir)
    sample.write_text("# Document\n\n## Contract\nOriginal\n\n## Other\nChanged\n", encoding="utf-8")
    assert contract_digest("contract.md#contract", contract_dir) == anchored
    sample.write_text("# Document\n\n## Contract\nChanged\n\n## Other\nChanged\n", encoding="utf-8")
    assert contract_digest("contract.md#contract", contract_dir) != anchored
print(f"PASS shader registry ({len(entries)} official profiles); revision records and change coverage")
