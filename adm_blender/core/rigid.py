"""Exact rig fingerprint ``rigId`` (spec §11.1).

Draft interpretation (the spec leaves the per-joint layout open, see README):

    {"inverseBindMatrices": [[16 x hex], ...],          # in skin.joints order
     "jointOrder": [nodeIndex, ...],                     # skin.joints
     "restTRS": [{"rotation": [4 x hex], "scale": [3 x hex], "translation": [3 x hex]}, ...],
     "roles": {"roleName": nodeIndex, ...}}

Floats are float32 little-endian bytes as 8 lowercase hex digits, -0 canonicalized to +0.
JSON uses sorted keys (Unicode code point order) and no whitespace, then SHA-256 is taken.
"""

import hashlib
import json
import struct

from .buffers import read_view


def f32_hex(value):
    b = struct.pack("<f", float(value))
    if b == b"\x00\x00\x00\x80":
        b = b"\x00\x00\x00\x00"
    return b.hex()


def _hex_raw_f32(raw4):
    if raw4 == b"\x00\x00\x00\x80":
        raw4 = b"\x00\x00\x00\x00"
    return raw4.hex()


def rig_descriptor(joint_order, rest_trs, ibm_raw, roles):
    """``rest_trs``: list of (t, q_xyzw, s); ``ibm_raw``: bytes of count*16 little-endian f32."""
    ibms = []
    for j in range(len(joint_order)):
        chunk = ibm_raw[j * 64:(j + 1) * 64]
        ibms.append([_hex_raw_f32(chunk[k * 4:k * 4 + 4]) for k in range(16)])
    desc = {
        "inverseBindMatrices": ibms,
        "jointOrder": [int(i) for i in joint_order],
        "restTRS": [{"translation": [f32_hex(v) for v in t],
                     "rotation": [f32_hex(v) for v in q],
                     "scale": [f32_hex(v) for v in s]} for (t, q, s) in rest_trs],
        "roles": {str(k): int(v) for k, v in roles.items()},
    }
    return json.dumps(desc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_rig_id(joint_order, rest_trs, ibm_raw, roles):
    return hashlib.sha256(rig_descriptor(joint_order, rest_trs, ibm_raw, roles)).hexdigest()


def rig_id_from_document(doc, bin_bytes, skin_index, roles):
    skin = doc["skins"][skin_index]
    joints = skin["joints"]
    rest = []
    for j in joints:
        node = doc["nodes"][j]
        rest.append((node.get("translation", [0.0, 0.0, 0.0]), node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
                     node.get("scale", [1.0, 1.0, 1.0])))
    acc = doc["accessors"][skin["inverseBindMatrices"]]
    start = acc.get("byteOffset", 0)
    raw = read_view(doc, bin_bytes, acc["bufferView"])
    return compute_rig_id(joints, rest, raw[start:start + len(joints) * 64], roles)
