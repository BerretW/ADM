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
from check_shader_registry_freeze import contract_digest, digest, verify_baseline_history, verify_freeze

registry_path = root / "adm-standard" / "shaders" / "registry.json"
registry = json.loads(registry_path.read_text(encoding="utf-8"))
entries = registry["shaders"]
assert registry["registryVersion"] == "1.1.0"
assert len(entries) == len({(entry["id"], entry["version"]) for entry in entries})
assert all(re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", entry["id"]) for entry in entries)
assert {(entry["id"], entry["version"]) for entry in entries} == set(K.OFFICIAL_SHADERS)
assert { (entry["id"], entry["version"]): entry["parameters"] for entry in entries } == K.OFFICIAL_SHADERS
assert set(K.OFFICIAL_SHADER_KINDS) == set(K.OFFICIAL_SHADERS)
assert set(K.OFFICIAL_SHADER_KEYS.values()) == {
    key for key in K.OFFICIAL_SHADER_KINDS if key[1] == "1.0.0"
}
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

baseline = json.loads((registry_path.parent / "freeze-2026-11-15.json").read_text(encoding="utf-8"))
contracts = {entry["contract"]: contract_digest(entry["contract"], registry_path.parent) for entry in entries}
verify_freeze(registry, baseline, contracts)


def expect_freeze_failure(test_registry, test_baseline, test_contracts, message):
    try:
        verify_freeze(test_registry, test_baseline, test_contracts)
    except ValueError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f"freeze check should reject {message}")


changed = deepcopy(registry)
changed["shaders"][0]["parameters"].append({"name": "new_parameter"})
expect_freeze_failure(changed, baseline, contracts, "changed without a new version")
removed = deepcopy(registry)
removed["shaders"].pop(0)
expect_freeze_failure(removed, baseline, contracts, "published shader removed")
changed_contracts = dict(contracts)
changed_contracts[entries[0]["contract"]] = "changed"
expect_freeze_failure(registry, baseline, changed_contracts, "published shader contract changed")
added = deepcopy(registry)
new_entry = deepcopy(added["shaders"][0])
new_entry["version"] = "9.0.0"
added["shaders"].append(new_entry)
expect_freeze_failure(added, baseline, contracts, "new shader needs a reviewed freeze entry")
extended = deepcopy(baseline)
extended["profiles"][f'{new_entry["id"]}@{new_entry["version"]}'] = digest(new_entry)
verify_freeze(added, extended, contracts)
verify_baseline_history(extended, baseline)
tampered = deepcopy(baseline)
tampered["profiles"][f'{entries[0]["id"]}@{entries[0]["version"]}'] = digest(changed["shaders"][0])
try:
    verify_baseline_history(tampered, baseline)
except ValueError as exc:
    assert "published freeze record changed or removed" in str(exc)
else:
    raise AssertionError("freeze history should reject replacing an existing hash")
tampered_contract = deepcopy(baseline)
tampered_contract["contracts"][entries[0]["contract"]] = "changed"
try:
    verify_baseline_history(tampered_contract, baseline)
except ValueError as exc:
    assert "published freeze record changed or removed" in str(exc)
else:
    raise AssertionError("freeze history should reject replacing an existing contract hash")
with tempfile.TemporaryDirectory() as temporary:
    contract_dir = pathlib.Path(temporary)
    sample = contract_dir / "contract.md"
    sample.write_text("# Document\n\n## Contract\nOriginal\n\n## Other\nOriginal\n", encoding="utf-8")
    anchored = contract_digest("contract.md#contract", contract_dir)
    sample.write_text("# Document\n\n## Contract\nOriginal\n\n## Other\nChanged\n", encoding="utf-8")
    assert contract_digest("contract.md#contract", contract_dir) == anchored
    sample.write_text("# Document\n\n## Contract\nChanged\n\n## Other\nChanged\n", encoding="utf-8")
    assert contract_digest("contract.md#contract", contract_dir) != anchored
print(f"PASS shader registry ({len(entries)} official profiles)")
