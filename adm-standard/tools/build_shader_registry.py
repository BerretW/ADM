#!/usr/bin/env python3
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from adm_blender.core import constants as K

contracts = {
    K.SHADER_CORE: "../ADM-1.0-SPEC.md#83-required-core-shader-and-reference-parameter-table",
    K.SHADER_LAYERED: "../ADM-1.0-SPEC.md#84-standard-optional-layered-shader-adm-shader-layered-1",
}
for key in K.OFFICIAL_SHADERS:
    if key not in contracts:
        contracts[key] = f"{key[0]}.v1.md"

data = {
    "registryVersion": "1.0.0",
    "shaders": [
        {"id": sid, "version": version, "parameters": K.OFFICIAL_SHADERS[(sid, version)],
         "contract": contracts[(sid, version)]}
        for sid, version in K.OFFICIAL_SHADERS
    ],
}
path = root / "adm-standard" / "shaders" / "registry.json"
rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
if "--check" in sys.argv:
    if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
        raise SystemExit(f"Shader registry is stale; run {pathlib.Path(__file__).name}")
    print(f"PASS registry matches {len(data['shaders'])} shader profiles")
else:
    path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {len(data['shaders'])} shader profiles to {path}")
