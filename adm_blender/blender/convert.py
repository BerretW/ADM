"""Coordinate conversion Blender (Z-up, -Y forward) <-> ADM (Y-up, -Z forward), spec §2/§26.

ADM = C · Blender with C: (x, y, z) -> (x, z, -y). C is a proper rotation, so winding is preserved.
"""

import math

import numpy as np
from mathutils import Matrix, Quaternion, Vector

C = Matrix(((1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0)))
C_INV = C.transposed()
C3 = C.to_3x3()
C3_INV = C_INV.to_3x3()


def f32(x):
    """Shortest decimal for a float32 value (keeps JSON compact and float32-exact)."""
    v = float(str(np.float32(x)))
    return 0.0 if v == 0.0 else v


def f32_exact(x):
    """The float64 value exactly equal to float32(x) (used where JSON/f32 comparisons must agree)."""
    return float(np.float32(x))


def vec_to_adm(v):
    return [f32(v[0]), f32(v[2]), f32(-v[1])]


def vec_from_adm(v):
    return Vector((v[0], -v[2], v[1]))


def quat_to_adm(q):
    """Blender Quaternion (w,x,y,z) -> ADM [x,y,z,w]."""
    q = q.normalized()
    if q.w < 0:
        q = -q
    return [f32(q.x), f32(q.z), f32(-q.y), f32(q.w)]


def quat_from_adm(q):
    x, y, z, w = q
    out = Quaternion((w, x, -z, y))
    out.normalize()
    return out


def scale_to_adm(s):
    return [f32(s[0]), f32(s[2]), f32(s[1])]


def scale_from_adm(s):
    return Vector((s[0], s[2], s[1]))


def mat_to_adm(m):
    return C @ m @ C_INV


def mat_from_adm(m):
    return C_INV @ m @ C


def matrix_to_list(m):
    """mathutils 4x4 -> ADM column-major 16 list."""
    return [f32(m[r][c]) for c in range(4) for r in range(4)]


def matrix_from_list(values):
    return Matrix([[values[c * 4 + r] for c in range(4)] for r in range(4)])


def trs_matrix_from_adm_node(node):
    """ADM node local matrix (ADM space) as mathutils Matrix."""
    if "matrix" in node:
        return matrix_from_list(node["matrix"])
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    q = Quaternion((r[3], r[0], r[1], r[2]))
    q.normalize()
    return Matrix.LocRotScale(Vector(t), q, Vector(s))


def is_trs_decomposable(m, eps=1e-5):
    loc, rot, sca = m.decompose()
    re = Matrix.LocRotScale(loc, rot, sca)
    return all(abs(re[r][c] - m[r][c]) <= eps * max(1.0, abs(m[r][c])) for r in range(4) for c in range(4))


def node_transform_fields(local_blender, force_trs=False):
    """Blender-space local matrix -> dict with ADM TRS fields (or ``matrix`` when not decomposable)."""
    m = mat_to_adm(local_blender)
    if not force_trs and not is_trs_decomposable(m):
        return {"matrix": matrix_to_list(m)}
    loc, rot, sca = m.decompose()
    out = {}
    if loc.length > 1e-9:
        out["translation"] = [f32(loc.x), f32(loc.y), f32(loc.z)]
    rot.normalize()
    if rot.w < 0:
        rot = -rot
    if abs(rot.w - 1.0) > 1e-9:
        out["rotation"] = [f32(rot.x), f32(rot.y), f32(rot.z), f32(rot.w)]
        n = math.sqrt(sum(v * v for v in out["rotation"]))
        out["rotation"] = [f32(v / n) for v in out["rotation"]]
    if (sca - Vector((1.0, 1.0, 1.0))).length > 1e-7:
        out["scale"] = [f32(sca.x), f32(sca.y), f32(sca.z)]
    return out


# numpy batch helpers ---------------------------------------------------------------------------
def np_vec_to_adm(a):
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    return np.stack((a[:, 0], a[:, 2], -a[:, 1]), axis=1)


def np_vec_from_adm(a):
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    return np.stack((a[:, 0], -a[:, 2], a[:, 1]), axis=1)


def np_uv_to_adm(uv):
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2).copy()
    uv[:, 1] = 1.0 - uv[:, 1]
    return uv


np_uv_from_adm = np_uv_to_adm
