"""Tiny dependency-free math helpers following ADM conventions (column-major, column vectors)."""

import math

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def mat_mul(a, b):
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = (a[0 * 4 + r] * b[c * 4 + 0] + a[1 * 4 + r] * b[c * 4 + 1]
                              + a[2 * 4 + r] * b[c * 4 + 2] + a[3 * 4 + r] * b[c * 4 + 3])
    return out


def quat_to_mat3(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def trs_to_mat(t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    r = quat_to_mat3(q)
    m = [0.0] * 16
    for c in range(3):
        for row in range(3):
            m[c * 4 + row] = r[row][c] * s[c]
    m[12], m[13], m[14], m[15] = t[0], t[1], t[2], 1.0
    return m


def node_local_matrix(node):
    if "matrix" in node:
        return list(node["matrix"])
    return trs_to_mat(node.get("translation", (0, 0, 0)), node.get("rotation", (0, 0, 0, 1)),
                      node.get("scale", (1, 1, 1)))


def det3(m):
    a, b, c = m[0], m[4], m[8]
    d, e, f = m[1], m[5], m[9]
    g, h, i = m[2], m[6], m[10]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def mat_translation(m):
    return (m[12], m[13], m[14])


def mat_col3(m, c):
    return (m[c * 4], m[c * 4 + 1], m[c * 4 + 2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vlen(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def mat_is_affine(m, eps=1e-6):
    return abs(m[3]) < eps and abs(m[7]) < eps and abs(m[11]) < eps and abs(m[15] - 1.0) < eps
