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
    (K.SHADER_CORE[0], K.SHADER_PROFILE_EDGE_WEAR): "ADM_shader_vertex_masks_v2_1.md",
}
contracts.update({key: "ADM_layered_height_profiles_v1.md" for key in K.SHADER_LAYERED_HEIGHT_COUNTS})
for key in K.OFFICIAL_SHADERS:
    if key not in contracts:
        contracts[key] = "ADM_shader_vertex_masks_v2.md" if key[1] == K.SHADER_PROFILE_V2 \
            else f"{key[0]}.v1.md"

shaders = []
for sid, version in K.OFFICIAL_SHADERS:
    key = (sid, version)
    entry = {"id": sid, "version": version, "parameters": K.OFFICIAL_SHADERS[key],
             "contract": contracts[key]}
    if key in K.SHADER_PROFILE_CAPABILITIES:
        entry["capability"] = K.SHADER_PROFILE_CAPABILITIES[key]
    shaders.append(entry)
data = {"shaders": shaders}
path = root / "adm-standard" / "shaders" / "registry.json"
rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
if "--check" in sys.argv:
    if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
        raise SystemExit(f"Shader registry is stale; run {pathlib.Path(__file__).name}")
    print(f"PASS registry matches {len(data['shaders'])} shader profiles")
else:
    path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {len(data['shaders'])} shader profiles to {path}")
