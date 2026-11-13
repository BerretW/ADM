"""ADM-IK-1 two-bone solver (ADM 1.0 Draft 0.4 §20.1-20.2), pure Python, f64.

Quaternions are ``(x, y, z, w)`` Hamilton, acting on column vectors; vectors are 3-tuples in ADM
model space.  The functions mirror the normative text step by step so they can serve as the
reference used by the Blender preview and by the tests.
"""

import math

EPS = 1e-6
SOLVED, CLAMPED, INVALID = "SOLVED", "CLAMPED", "INVALID"
_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    n = length(a)
    return scale(a, 1.0 / n) if n > 0 else (0.0, 0.0, 0.0)


def least_aligned_axis(x):
    """Least aligned of X, Y, Z (ties X then Y then Z)."""
    best, best_v = None, None
    for ax in _AXES:
        v = abs(dot(normalize(x), ax))
        if best_v is None or v < best_v - 1e-15:
            best, best_v = ax, v
    return best


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def q_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def q_norm(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def q_rotate(q, v):
    p = q_mul(q_mul(q, (v[0], v[1], v[2], 0.0)), q_conj(q))
    return (p[0], p[1], p[2])


def q_axis_angle(axis, angle):
    a = normalize(axis)
    s = math.sin(angle / 2.0)
    return (a[0] * s, a[1] * s, a[2] * s, math.cos(angle / 2.0))


def from_to(x, y):
    """Unique shortest-arc rotation taking direction x to direction y (§20.2)."""
    x, y = normalize(x), normalize(y)
    d = dot(x, y)
    if d <= -1.0 + 1e-8:
        axis = normalize(cross(x, least_aligned_axis(x)))
        return q_axis_angle(axis, math.pi)
    c = cross(x, y)
    return q_norm((c[0], c[1], c[2], 1.0 + d))


def slerp(a, b, t):
    """Shortest-arc spherical interpolation."""
    d = sum(i * j for i, j in zip(a, b))
    if d < 0.0:
        b, d = tuple(-c for c in b), -d
    if d > 0.9999995:
        return q_norm(tuple(i + (j - i) * t for i, j in zip(a, b)))
    th = math.acos(min(1.0, d))
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return q_norm(tuple(wa * i + wb * j for i, j in zip(a, b)))


def solve_points(A, B, C, P, pole):
    """§20.1: returns dict(status, mid=B*, end=C*, d, d_solved)."""
    l1, l2 = length(sub(B, A)), length(sub(C, B))
    if l1 <= 1e-6 or l2 <= 1e-6:
        return {"status": INVALID}
    d = length(sub(P, A))
    lo, hi = abs(l1 - l2) + EPS, l1 + l2 - EPS
    if lo <= hi:
        d_solved = min(max(d, lo), hi)
        status = SOLVED if lo <= d <= hi else CLAMPED
    else:
        # documented zero-fold rule: fully folded/extended endpoint nearest to d, h = 0
        d_solved = abs(l1 - l2) if d < (abs(l1 - l2) + l1 + l2) / 2 else l1 + l2
        d_solved = max(d_solved, EPS)
        status = CLAMPED
    if d > EPS:
        u = scale(sub(P, A), 1.0 / d)
    elif length(sub(C, A)) > 0:
        u = normalize(sub(C, A))
    else:
        u = normalize(sub(B, A))
    v = sub(pole, scale(u, dot(pole, u)))
    if length(v) < 1e-8:
        ax = least_aligned_axis(u)
        v = sub(ax, scale(u, dot(ax, u)))
    v = normalize(v)
    a = (l1 * l1 - l2 * l2 + d_solved * d_solved) / (2.0 * d_solved)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))
    mid = add(A, add(scale(u, a), scale(v, h)))
    end = add(A, scale(u, d_solved))
    return {"status": status, "mid": mid, "end": end, "d": d, "d_solved": d_solved}


def solve_chain(A, B, C, R_parent, R_root, R_mid, P, pole, weight=1.0):
    """Full §20.1/20.2 evaluation for one chain.

    A, B, C        -- model-space positions of root, mid, end (FK, before IK)
    R_parent       -- model-space rotation of root's parent (identity if root has no parent)
    R_root, R_mid  -- model-space rotations of root and mid
    Returns dict(status, root_local, mid_local, root_world, mid_world, end, target, error).
    Local rotations are relative to the parent world rotation (no scale handling: ADM-IK-1 forbids
    nonuniform/negative chain scale).
    """
    root_local0 = q_mul(q_conj(R_parent), R_root)
    mid_local0 = q_mul(q_conj(R_root), R_mid)
    if weight <= 0.0:
        return {"status": SOLVED, "root_local": root_local0, "mid_local": mid_local0, "root_world": R_root,
                "mid_world": R_mid, "end": C, "target": P, "error": length(sub(C, P)), "unchanged": True}
    s = solve_points(A, B, C, P, pole)
    if s["status"] == INVALID:
        return {"status": INVALID}
    Bs, Cs = s["mid"], s["end"]
    swing_root = from_to(sub(B, A), sub(Bs, A))
    R_root_new = q_mul(swing_root, R_root)
    C_after = add(A, q_rotate(swing_root, sub(C, A)))
    R_mid_after = q_mul(swing_root, R_mid)
    swing_mid = from_to(sub(C_after, Bs), sub(Cs, Bs))
    R_mid_new = q_mul(swing_mid, R_mid_after)
    root_local = q_mul(q_conj(R_parent), R_root_new)
    mid_local = q_mul(q_conj(R_root_new), R_mid_new)
    if weight < 1.0:
        root_local = slerp(root_local0, root_local, weight)
        mid_local = slerp(mid_local0, mid_local, weight)
    # FK with the final local rotations (segment offsets expressed in the old joint frames)
    off_mid = q_rotate(q_conj(R_root), sub(B, A))
    off_end = q_rotate(q_conj(R_mid), sub(C, B))
    root_w = q_mul(R_parent, root_local)
    B_f = add(A, q_rotate(root_w, off_mid))
    mid_w = q_mul(root_w, mid_local)
    C_f = add(B_f, q_rotate(mid_w, off_end))
    return {"status": s["status"], "root_local": root_local, "mid_local": mid_local, "root_world": root_w,
            "mid_world": mid_w, "mid": B_f, "end": C_f, "target": Cs, "error": length(sub(C_f, P))}
