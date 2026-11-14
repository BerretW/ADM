#!/usr/bin/env python3
"""Independent fixture, UV hit-test and runtime-color reference checks."""

import copy
import json
import math
from pathlib import Path
import struct
import zlib

from container import AdmError, ENTRY, HEADER, verify, verify_interactive

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "fixtures" / "valid" / "interactive_terminal.adm"
expected = json.loads((ROOT / "fixtures" / "expectations" / "interactive_terminal.expected.json").read_text(
    encoding="utf-8"))
verify(path)
data = path.read_bytes()
header = HEADER.unpack_from(data)
manifest = json.loads(data[header[6]:header[6] + header[7]].decode("utf-8"))
chunks = {}
for index in range(header[9]):
    cid, _kind, _flags, codec, _reserved, offset, stored, raw, _digest = ENTRY.unpack_from(
        data, header[8] + index * ENTRY.size)
    assert codec == 0 and stored == raw
    chunks[cid] = data[offset:offset + stored]


def accessor(index):
    a = manifest["accessors"][index]
    v = manifest["bufferViews"][a["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
    code = {"F32": "f", "U16": "H"}[a["componentType"]]
    start = v["byteOffset"] + a.get("byteOffset", 0)
    values = struct.unpack_from("<" + code * (a["count"] * width), chunks[v["chunkId"]], start)
    return [values[i:i + width] for i in range(0, len(values), width)]


def close(actual, target):
    return len(actual) == len(target) and all(abs(a - b) < 1e-9 for a, b in zip(actual, target))


extension = manifest["extensions"][expected["extension"]]
assert extension["version"] == expected["version"]
ratio_check = copy.deepcopy(manifest)
ratio_check["extensions"][expected["extension"]]["surfaces"][0]["aspectRatio"] = 1e-45
verify_interactive(ratio_check)
ratio_check["extensions"][expected["extension"]]["surfaces"][0]["aspectRatio"] = 1e-46
try:
    verify_interactive(ratio_check)
except AdmError as error:
    assert str(error) == "ADM_ERR_INTERACTIVE_ASPECT"
else:
    raise AssertionError("binary32-underflowing aspect ratio was accepted")
assert manifest["nodes"][0]["name"] == manifest["nodes"][1]["name"]
found = {surface["surfaceId"]: surface["bindings"][0] for surface in extension["surfaces"]}
assert found == expected["surfaces"]
for binding in found.values():
    node = manifest["nodes"][binding["node"]]
    assert node["mesh"] == expected["sharedMesh"]
    primitive = manifest["meshes"][node["mesh"]]["primitives"][binding["primitive"]]
    assert primitive["material"] == expected["sharedMaterial"]
    indices = [row[0] for row in accessor(primitive["indices"])]
    assert len(indices) // 3 == expected["triangleCountPerSurface"]
    uv = accessor(primitive["attributes"][f"TEXCOORD_{binding['texCoord']}"])
    triangle_uv = [uv[i] for i in indices[:3]]
    assert all(close(a, b) for a, b in zip(triangle_uv, expected["firstTriangleUv"]))
    weights = expected["hitTest"]["barycentric"]
    hit = [sum(weights[i] * triangle_uv[i][axis] for i in range(3)) for axis in (0, 1)]
    assert close(hit, expected["hitTest"]["uv"])
    clamped = [max(0.0, min(1.0, component)) for component in hit]
    size = expected["hitTest"]["contentSize"]
    pixel = [min(math.floor(clamped[axis] * size[axis]), size[axis] - 1) for axis in (0, 1)]
    assert pixel == expected["hitTest"]["pixel"]
assert [min(math.floor(max(0, min(1, uv)) * n), n - 1) for uv, n in zip((-0.5, 1.5), (4, 2))] == [0, 1]

material = manifest["materials"][expected["sharedMaterial"]]
runtime = expected["runtime"]


def decode_srgb(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def sample_srgb_bilinear(texels, uv):
    height, width = len(texels), len(texels[0])
    x = max(0.0, min(1.0, uv[0])) * width - 0.5
    y = max(0.0, min(1.0, uv[1])) * height - 0.5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0

    def texel(ix, iy):
        source = texels[max(0, min(height - 1, iy))][max(0, min(width - 1, ix))]
        return [decode_srgb(value) for value in source[:3]] + [source[3]]

    top_left, top_right = texel(x0, y0), texel(x0 + 1, y0)
    bottom_left, bottom_right = texel(x0, y0 + 1), texel(x0 + 1, y0 + 1)
    return [((1 - fx) * top_left[i] + fx * top_right[i]) * (1 - fy) +
            ((1 - fx) * bottom_left[i] + fx * bottom_right[i]) * fy for i in range(4)]


rgb = [decode_srgb(value) * runtime["brightness"] for value in runtime["sourceSrgb"]]
assert material["shaderParameters"]["brightness"] == runtime["brightness"]
assert close(rgb, runtime["unlitLinearRgb"])
assert close([rgb[i] * material["baseColorFactor"][i] for i in range(3)], runtime["litBaseLinearRgb"])
assert close([value * material["shaderParameters"]["emissive_strength"] for value in rgb],
             runtime["litEmissiveLinearRgb"])
assert abs(runtime["sourceAlpha"] * material["baseColorFactor"][3] - runtime["alpha"]) < 1e-9
assert min(max(runtime["alpha"] * runtime["vertexAlpha"], 0.0), 1.0) == runtime["clampedAlpha"]
sampling = expected["sampling"]
assert close(sample_srgb_bilinear(sampling["texelsSrgb"], sampling["uv"]), sampling["linearRgba"])
assert close(sample_srgb_bilinear(sampling["texelsSrgb"], (0.25, 0.75)), sampling["bottomLeftRgba"])
assert close(sample_srgb_bilinear(sampling["texelsSrgb"], (-3.0, 4.0)), sampling["bottomLeftRgba"])
image = manifest["images"][manifest["textures"][material["baseColorTexture"]["index"]]["source"]]
image_view = manifest["bufferViews"][image["bufferView"]]
start = image_view["byteOffset"]
png = chunks[image_view["chunkId"]][start:start + image_view["byteLength"]]
assert png.startswith(b"\x89PNG\r\n\x1a\n")
offset, image_data, ended = 8, bytearray(), False
while offset < len(png):
    length = struct.unpack_from(">I", png, offset)[0]
    tag = png[offset + 4:offset + 8]
    payload = png[offset + 8:offset + 8 + length]
    crc = struct.unpack_from(">I", png, offset + 8 + length)[0]
    assert zlib.crc32(tag + payload) & 0xFFFFFFFF == crc
    offset += length + 12
    if tag == b"IHDR":
        assert payload == struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    elif tag == b"IDAT":
        image_data.extend(payload)
    elif tag == b"IEND":
        ended = True
        break
assert ended and offset == len(png)
assert zlib.decompress(image_data) == bytes((
    0, 255, 0, 0, 255, 0, 255, 0, 255,
    0, 0, 0, 255, 255, 255, 255, 255, 255,
))
print("PASS interactive fixture: identity, shared mesh, hit mapping, bilinear linear RGB, alpha and fallback")
