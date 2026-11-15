"""Minimal binary little-endian PLY reader/writer for tile meshes."""

from __future__ import annotations

import numpy as np

VERTEX_DTYPE = np.dtype(
    [
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4"),
        ("s", "<f4"), ("t", "<f4"),  # UV0: 0..1 per full tile, for repeating layer textures
        ("s1", "<f4"), ("t1", "<f4"),  # UV1: blend mask of this tile (half-texel inset)
    ]
)
FACE_DTYPE = np.dtype([("n", "u1"), ("v", "<i4", (3,))])

_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "<i2", "int16": "<i2", "ushort": "<u2", "uint16": "<u2",
    "int": "<i4", "int32": "<i4", "uint": "<u4", "uint32": "<u4",
    "float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
}


def write_ply(path: str, vertices: np.ndarray, faces: np.ndarray, comment: str = "") -> None:
    """``vertices`` is a VERTEX_DTYPE array, ``faces`` an (n, 3) int array."""
    face_rows = np.empty(len(faces), FACE_DTYPE)
    face_rows["n"] = 3
    face_rows["v"] = faces
    header = ["ply", "format binary_little_endian 1.0"]
    if comment:
        header.append(f"comment {comment}")
    header.append(f"element vertex {len(vertices)}")
    header += [f"property float {name}" for name in VERTEX_DTYPE.names]
    header.append(f"element face {len(faces)}")
    header.append("property list uchar int vertex_indices")
    header.append("end_header")
    with open(path, "wb") as handle:
        handle.write(("\n".join(header) + "\n").encode("ascii"))
        handle.write(np.ascontiguousarray(vertices, VERTEX_DTYPE).tobytes())
        handle.write(face_rows.tobytes())


def read_ply(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Read a binary little-endian triangle PLY. Returns (vertices, faces)."""
    with open(path, "rb") as handle:
        if handle.readline().strip() != b"ply":
            raise ValueError(f"{path}: not a PLY file")
        elements: list[list] = []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError(f"{path}: truncated PLY header")
            words = line.decode("ascii").split()
            if not words or words[0] == "comment":
                continue
            if words[0] == "format" and words[1] != "binary_little_endian":
                raise ValueError(f"{path}: only binary_little_endian PLY is supported")
            if words[0] == "element":
                elements.append([words[1], int(words[2]), []])
            elif words[0] == "property":
                elements[-1][2].append(words[1:])
            elif words[0] == "end_header":
                break
        vertices = faces = None
        for name, count, props in elements:
            if name == "face":
                list_prop = props[0]
                if list_prop[0] != "list":
                    raise ValueError(f"{path}: face element must be a list property")
                dtype = np.dtype([("n", _TYPES[list_prop[1]]), ("v", _TYPES[list_prop[2]], (3,))])
                rows = np.frombuffer(handle.read(dtype.itemsize * count), dtype, count)
                if count and not np.all(rows["n"] == 3):
                    raise ValueError(f"{path}: only triangle faces are supported")
                faces = rows["v"].astype(np.int32)
            else:
                dtype = np.dtype([(p[1], _TYPES[p[0]]) for p in props])
                data = np.frombuffer(handle.read(dtype.itemsize * count), dtype, count)
                if name == "vertex":
                    vertices = data
    if vertices is None or faces is None:
        raise ValueError(f"{path}: missing vertex or face element")
    return vertices, faces
