"""bufferViews / accessors encoding and decoding (spec §5)."""

import array
import math
import struct
import sys

from .constants import COMPONENT_SIZES, COMPONENT_STRUCT, COMPONENT_MAX, TYPE_COUNTS
from .container import AdmFormatError, ChunkCollection, chunk_length, chunk_type, has_chunk

_ARRAY_CODES = {"F32": "f", "U32": "I", "U16": "H", "U8": "B"}


def accessor_span(doc, index):
    """Return ``(chunk_relative_start, byte_length, ncomp)``; assumes validated input."""
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    ncomp = TYPE_COUNTS[acc["type"]]
    start = view["byteOffset"] + acc.get("byteOffset", 0)
    return start, acc["count"] * ncomp * COMPONENT_SIZES[acc["componentType"]], ncomp


def read_view(doc, payloads, index):
    """Read one chunk-addressed view, loading only its dependency closure."""
    try:
        if type(index) is not int or index < 0:
            raise ValueError()
        view = doc["bufferViews"][index]
        cid, start, length = (view[k] for k in ("chunkId", "byteOffset", "byteLength"))
        if (any(type(v) is not int or not 0 <= v <= 0xffffffff for v in (cid, start, length))
                or not cid or not has_chunk(payloads, cid)
                or start + length > chunk_length(payloads, cid)):
            raise ValueError()
        if chunk_type(payloads, cid) not in ("GEOM", "ANIM", "IMAG", "DATA"):
            raise AdmFormatError("ADM_ERR_UNSUPPORTED_CHUNK", "view references unknown chunk type")
    except (KeyError, IndexError, TypeError, ValueError):
        raise AdmFormatError("ADM_ERR_BUFFER_VIEW", "invalid chunk-addressed view") from None
    raw = payloads[cid]
    if len(raw) != chunk_length(payloads, cid):
        raise AdmFormatError("ADM_ERR_CHUNK_SIZE", "payload length differs from directory metadata")
    return bytes(raw[start:start + length])


def _accessor_bytes(doc, payloads, index):
    try:
        if type(index) is not int or index < 0:
            raise ValueError()
        acc = doc["accessors"][index]
        view_index = acc["bufferView"]
        if type(view_index) is not int or view_index < 0:
            raise ValueError()
        view = doc["bufferViews"][view_index]
        size = COMPONENT_SIZES[acc["componentType"]]
        ncomp = TYPE_COUNTS[acc["type"]]
        offset, count = acc.get("byteOffset", 0), acc["count"]
        if (type(offset) is not int or type(count) is not int
                or not 0 <= offset <= 0xffffffff or not 0 <= count <= 0xffffffff
                or offset % size or (view["byteOffset"] + offset) % size
                or offset + count * ncomp * size > view["byteLength"]
                or type(acc.get("normalized", False)) is not bool
                or (acc.get("normalized", False) and acc["componentType"] == "F32")):
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise AdmFormatError("ADM_ERR_ACCESSOR", "invalid accessor shape, alignment or bounds") from None
    raw = read_view(doc, payloads, view_index)[offset:offset + count * ncomp * size]
    if acc["componentType"] == "F32" and any(
            not math.isfinite(value[0]) for value in struct.iter_unpack("<f", raw)):
        raise AdmFormatError("ADM_ERR_NONFINITE", "accessor contains non-finite F32 values")
    return raw, ncomp


def read_accessor_flat(doc, bin_bytes, index):
    """Decode an accessor into a flat ``array.array`` (raw, not normalized) and component count."""
    raw, ncomp = _accessor_bytes(doc, bin_bytes, index)
    acc = doc["accessors"][index]
    length = len(raw)
    code = _ARRAY_CODES[acc["componentType"]]
    arr = array.array(code)
    if array.array(code).itemsize != COMPONENT_SIZES[acc["componentType"]]:
        fmt = "<%d%s" % (length // COMPONENT_SIZES[acc["componentType"]], COMPONENT_STRUCT[acc["componentType"]])
        return array.array("d" if code == "f" else "q", struct.unpack_from(fmt, raw)), ncomp
    arr.frombytes(raw)
    if sys.byteorder != "little":
        arr.byteswap()
    return arr, ncomp


def read_accessor(doc, bin_bytes, index):
    """Decode an accessor to a list of tuples (floats when normalized or F32)."""
    flat, ncomp = read_accessor_flat(doc, bin_bytes, index)
    acc = doc["accessors"][index]
    if acc.get("normalized", False):
        scale = 1.0 / COMPONENT_MAX[acc["componentType"]]
        flat = [v * scale for v in flat]
    return [tuple(flat[i:i + ncomp]) for i in range(0, len(flat), ncomp)]


def read_accessor_np(doc, bin_bytes, index, dtype=None):
    """Decode an accessor to a numpy array of shape (count, ncomp) (requires numpy)."""
    import numpy as np
    raw, ncomp = _accessor_bytes(doc, bin_bytes, index)
    acc = doc["accessors"][index]
    np_dtype = {"F32": "<f4", "U32": "<u4", "U16": "<u2", "U8": "u1"}[acc["componentType"]]
    out = np.frombuffer(raw, dtype=np_dtype, count=acc["count"] * ncomp)
    out = out.reshape(acc["count"], ncomp)
    if acc.get("normalized", False):
        out = out.astype(np.float64) / COMPONENT_MAX[acc["componentType"]]
    if dtype is not None:
        out = out.astype(dtype)
    return out


class BinBuilder:
    """One independent chunk per view, plus manifest bufferViews/accessors."""

    def __init__(self, chunk_type="GEOM"):
        self.chunks = ChunkCollection()
        self.chunk_type = chunk_type
        self.size = 0
        self.buffer_views = []
        self.accessors = []

    def add_view(self, data, align=4, chunk_type=None):
        if type(align) is not int or align < 1:
            raise ValueError("align must be a positive integer")
        data = bytes(data)
        cid = len(self.chunks) + 1
        self.chunks.add(cid, data, self.chunk_type if chunk_type is None else chunk_type)
        self.buffer_views.append({"chunkId": cid, "byteOffset": 0, "byteLength": len(data)})
        self.size += len(data)
        return len(self.buffer_views) - 1

    def add_accessor(self, values, component_type, acc_type, normalized=False):
        """``values`` is anything numpy can turn into a (count, ncomp) or flat array."""
        import numpy as np
        ncomp = TYPE_COUNTS[acc_type]
        np_dtype = {"F32": "<f4", "U32": "<u4", "U16": "<u2", "U8": "u1"}[component_type]
        arr = np.ascontiguousarray(np.asarray(values).reshape(-1), dtype=np_dtype)
        if arr.size % ncomp:
            raise ValueError("accessor data size is not a multiple of the component count")
        if component_type == "F32" and not np.all(np.isfinite(arr)):
            raise ValueError("refusing to write non-finite float data")
        if component_type == "F32":
            arr = arr + np.float32(0.0)  # canonicalize -0.0 to +0.0
        view = self.add_view(arr.tobytes(), align=max(4, COMPONENT_SIZES[component_type]))
        acc = {"bufferView": view, "componentType": component_type, "type": acc_type,
               "count": int(arr.size // ncomp)}
        if normalized:
            acc["normalized"] = True
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def bytes(self):
        """Return the typed chunk collection accepted by write_container/validators."""
        return self.chunks
