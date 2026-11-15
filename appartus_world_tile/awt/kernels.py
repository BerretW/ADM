"""Numba kernels for the global right-triangulated irregular network (RTIN).

Coordinates are integer grid positions: ``x`` is the image column, ``y`` the
image row.  Tile ``(i, j)`` covers columns ``i*T .. (i+1)*T`` and rows
``j*T .. (j+1)*T``.  Samples beyond the source (``x > W-1`` or ``y > H-1``)
only exist in the padded hierarchy and are never emitted.

Triangle ids follow the MARTINI layout: ids 2 and 3 are the two roots of a
tile, a triangle of level ``l`` has an id in ``[2**(l+1), 2**(l+2))`` and the
bits below the leading one encode the path from the root (lowest bit = root),
so the children of ``id`` are ``id + 2**(l+1)`` and ``id + 2**(l+2)``.

The error stored at a vertex ``m`` is the maximum vertical deviation of every
source sample inside the triangles whose hypotenuse midpoint is ``m`` (the
diamond of ``m``), maximised with the errors of all descendant vertices.  An
unsplit triangle therefore never deviates from the heightmap by more than the
threshold, and because the error array is global, both sides of a tile edge
split identically, so tiles never crack.
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

# float32 rounds to nearest; inflating by more than one float32 ulp before
# the cast guarantees the stored value is never below the exact error.
_F32_ROUND_UP = 1.0 + 2.0 ** -22


@njit(cache=True, inline="always")
def _height(h, x, y, w, hgt, scale, offset):
    if x > w - 1:
        x = w - 1
    if y > hgt - 1:
        y = hgt - 1
    return h[y, x] * scale + offset


@njit(cache=True, inline="always")
def decode(tid, t):
    """Return ``ax, ay, bx, by, cx, cy`` of triangle ``tid`` in tile coords."""
    if tid & 1:
        ax = 0
        ay = 0
        bx = t
        by = t
        cx = t
        cy = 0
    else:
        ax = t
        ay = t
        bx = 0
        by = 0
        cx = 0
        cy = t
    node = tid >> 1
    while node > 1:
        mx = (ax + bx) >> 1
        my = (ay + by) >> 1
        if node & 1:
            bx = ax
            by = ay
            ax = cx
            ay = cy
        else:
            ax = bx
            ay = by
            bx = cx
            by = cy
        cx = mx
        cy = my
        node >>= 1
    return ax, ay, bx, by, cx, cy


@njit(cache=True)
def triangle_error(h, w, hgt, scale, offset, ax, ay, bx, by, cx, cy):
    """Exact max |height - plane| over all samples inside the triangle."""
    za = _height(h, ax, ay, w, hgt, scale, offset)
    zb = _height(h, bx, by, w, hgt, scale, offset)
    zc = _height(h, cx, cy, w, hgt, scale, offset)
    det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
    sign = 1 if det > 0 else -1
    dzb = (zb - za) / det
    dzc = (zc - za) / det
    y0 = min(ay, by, cy)
    y1 = max(ay, by, cy)
    x0 = min(ax, bx, cx)
    x1 = max(ax, bx, cx)
    worst = 0.0
    for y in range(y0, y1 + 1):
        row = h[min(y, hgt - 1)]
        for x in range(x0, x1 + 1):
            nb = ((x - ax) * (cy - ay) - (cx - ax) * (y - ay)) * sign
            nc = ((bx - ax) * (y - ay) - (x - ax) * (by - ay)) * sign
            if nb < 0 or nc < 0 or nb + nc > det * sign:
                continue
            z = row[min(x, w - 1)] * scale + offset
            d = abs(z - (za + nb * sign * dzb + nc * sign * dzc))
            if d > worst:
                worst = d
    return worst


@njit(cache=True, inline="always")
def _side(ax, ay, bx, by, cx, cy, last_x, last_y):
    """0 = inside the source, 1 = entirely in padding, 2 = crosses the cut."""
    if max(ax, bx, cx) <= last_x and max(ay, by, cy) <= last_y:
        return 0
    if min(ax, bx, cx) >= last_x or min(ay, by, cy) >= last_y:
        return 1
    return 2


@njit(cache=True, parallel=True)
def level_pass(h, scale, offset, w, hgt, t, nx, ny, level, nonleaf_levels, errors):
    """Compute and propagate vertex errors for every triangle of ``level``.

    Must be called for ``level = nonleaf_levels-1 .. 0`` in that order.  Tiles
    are processed in four checkerboard phases so that two tiles sharing an
    edge (and therefore edge vertices) never run concurrently.
    """
    first = 1 << (level + 1)
    last_x = w - 1
    last_y = hgt - 1
    for phase in range(4):
        pi = phase & 1
        pj = phase >> 1
        nxp = (nx - pi + 1) // 2
        nyp = (ny - pj + 1) // 2
        for k in prange(nxp * nyp):
            ti = pi + 2 * (k % nxp)
            tj = pj + 2 * (k // nxp)
            ox = ti * t
            oy = tj * t
            for n in range(first):
                ax, ay, bx, by, cx, cy = decode(first + n, t)
                ax += ox
                bx += ox
                cx += ox
                ay += oy
                by += oy
                cy += oy
                side = _side(ax, ay, bx, by, cx, cy, last_x, last_y)
                if side == 1:
                    continue
                if side == 2:
                    e = np.inf
                else:
                    e = triangle_error(h, w, hgt, scale, offset, ax, ay, bx, by, cx, cy) * _F32_ROUND_UP
                if level + 1 < nonleaf_levels:
                    lc = errors[(cy + ay) >> 1, (cx + ax) >> 1]
                    rc = errors[(by + cy) >> 1, (bx + cx) >> 1]
                    if lc > e:
                        e = lc
                    if rc > e:
                        e = rc
                my = (ay + by) >> 1
                mx = (ax + bx) >> 1
                if e > errors[my, mx]:
                    errors[my, mx] = e


@njit(cache=True, inline="always")
def _vertex(index, verts, nv, gx, gy, ox, oy, stride):
    slot = (gy - oy) * stride + (gx - ox)
    vid = index[slot]
    if vid < 0:
        vid = nv
        index[slot] = vid
        verts[nv, 0] = gx
        verts[nv, 1] = gy
        nv += 1
    return vid, nv


@njit(cache=True, nogil=True)
def extract_tile(h, scale, offset, w, hgt, t, ti, tj, nonleaf_levels, errors, max_error):
    """Triangulate one tile.

    Returns ``(verts, faces, measured)``: ``verts`` holds global grid ``(x, y)``
    pairs, ``faces`` local indices wound counter-clockwise in world space
    (world Y points towards image row 0) and ``measured`` the real max error
    of the emitted triangles against every covered sample.
    """
    ox = ti * t
    oy = tj * t
    stride = t + 1
    last_x = w - 1
    last_y = hgt - 1
    index = np.full(stride * stride, -1, np.int32)
    verts = np.empty((stride * stride, 2), np.int32)
    faces = np.empty((2 * t * t, 3), np.int32)
    nv = 0
    nf = 0
    measured = 0.0

    stack = np.empty(2 * nonleaf_levels + 4, np.int64)
    stack[0] = 2
    stack[1] = 3
    sp = 2
    while sp > 0:
        sp -= 1
        tid = stack[sp]
        ax, ay, bx, by, cx, cy = decode(tid, t)
        ax += ox
        bx += ox
        cx += ox
        ay += oy
        by += oy
        cy += oy
        level = 0
        probe = tid
        while probe > 3:
            probe >>= 1
            level += 1
        if level < nonleaf_levels and errors[(ay + by) >> 1, (ax + bx) >> 1] > max_error:
            # The split choice is stored above the existing path bits.
            stack[sp] = tid + (1 << (level + 1))
            stack[sp + 1] = tid + (1 << (level + 2))
            sp += 2
            continue
        if _side(ax, ay, bx, by, cx, cy, last_x, last_y) != 0:
            continue
        ia, nv = _vertex(index, verts, nv, ax, ay, ox, oy, stride)
        ib, nv = _vertex(index, verts, nv, bx, by, ox, oy, stride)
        ic, nv = _vertex(index, verts, nv, cx, cy, ox, oy, stride)
        faces[nf, 0] = ia
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0:
            faces[nf, 1] = ib
            faces[nf, 2] = ic
        else:
            faces[nf, 1] = ic
            faces[nf, 2] = ib
        nf += 1
        err = triangle_error(h, w, hgt, scale, offset, ax, ay, bx, by, cx, cy)
        if err > measured:
            measured = err
    return verts[:nv].copy(), faces[:nf].copy(), measured
