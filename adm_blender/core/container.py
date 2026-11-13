"""Byte-exact ADM / ADM_ANIM container reading and writing (spec §3, §13)."""

import json
import math
import struct
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from .constants import VERSION_MAJOR, VERSION_MINOR, ADM_MAGIC, ANIM_MAGIC

HEADER = struct.Struct("<4sHHIIQQQQIIQ")
ENTRY = struct.Struct("<Q4sIIIQQQ32s")
HEADER_SIZE = HEADER.size
MAX_MANIFEST = 16 * 1024 * 1024
MAX_CHUNK = 256 * 1024 * 1024
KNOWN_TYPES = frozenset(("GEOM", "ANIM", "IMAG", "DATA"))
U64_MAX = (1 << 64) - 1


class AdmFormatError(Exception):
    """Malformed container or JSON. ``code`` is a stable machine readable identifier."""

    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ResourceLimitError(AdmFormatError):
    """Raised when a configurable safety limit is exceeded (reported distinctly, §25)."""


class Limits:
    def __init__(self, max_json_bytes=MAX_MANIFEST, max_bin_bytes=8 * 1024 * 1024 * 1024,
                 max_json_depth=64, max_chunk_bytes=MAX_CHUNK, max_chunks=65535,
                 max_stored_bytes=None, max_total_raw_bytes=None):
        self.max_json_bytes = max_json_bytes
        self.max_bin_bytes = max_bin_bytes
        self.max_json_depth = max_json_depth
        self.max_chunk_bytes = max_chunk_bytes
        self.max_chunks = max_chunks
        self.max_stored_bytes = max_bin_bytes if max_stored_bytes is None else max_stored_bytes
        self.max_total_raw_bytes = max_bin_bytes if max_total_raw_bytes is None else max_total_raw_bytes


DEFAULT_LIMITS = Limits()


def _reject_constant(name):
    raise AdmFormatError("ADM_ERR_NONFINITE", f"non-finite JSON constant {name!r} is forbidden")


def _parse_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise AdmFormatError("ADM_ERR_NONFINITE", f"JSON number {text!r} overflows to a non-finite value")
    return value


def _pairs_hook(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise AdmFormatError("ADM_ERR_DUPLICATE_JSON_KEY", f"duplicate JSON object key {key!r}")
        obj[key] = value
    return obj


def _check_strings_and_depth(value, depth, limit):
    if depth > limit:
        raise ResourceLimitError("ADM_ERR_RESOURCE_LIMIT", f"JSON nesting deeper than {limit}")
    stack = [(value, depth)]
    while stack:
        item, d = stack.pop()
        if d > limit:
            raise ResourceLimitError("ADM_ERR_RESOURCE_LIMIT", f"JSON nesting deeper than {limit}")
        if isinstance(item, str):
            _check_scalar_string(item)
        elif isinstance(item, dict):
            for k, v in item.items():
                _check_scalar_string(k)
                stack.append((v, d + 1))
        elif isinstance(item, list):
            for v in item:
                stack.append((v, d + 1))


def _check_scalar_string(s):
    try:
        s.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise AdmFormatError("ADM_ERR_JSON", "string contains an unpaired surrogate") from None


def parse_json_strict(raw, limits=DEFAULT_LIMITS):
    if len(raw) > limits.max_json_bytes:
        raise ResourceLimitError("ADM_ERR_RESOURCE_LIMIT", "manifest exceeds configured limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AdmFormatError("ADM_ERR_JSON", "JSON chunk must not start with a UTF-8 BOM")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise AdmFormatError("ADM_ERR_JSON", f"invalid UTF-8 in JSON chunk: {exc}") from None
    try:
        doc = json.loads(text, object_pairs_hook=_pairs_hook, parse_constant=_reject_constant,
                         parse_float=_parse_float)
    except AdmFormatError:
        raise
    except RecursionError:
        raise ResourceLimitError("ADM_ERR_RESOURCE_LIMIT", "JSON nesting too deep") from None
    except ValueError as exc:
        raise AdmFormatError("ADM_ERR_JSON", f"malformed JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise AdmFormatError("ADM_ERR_MANIFEST", "manifest must be exactly one JSON object")
    _check_strings_and_depth(doc, 0, limits.max_json_depth)
    return doc


def _fail(code, message):
    raise AdmFormatError("ADM_ERR_" + code, message)


def _limit(condition, message):
    if condition:
        raise ResourceLimitError("ADM_ERR_RESOURCE_LIMIT", message)


def _u32(value, nonzero=False):
    return type(value) is int and int(nonzero) <= value <= 0xffffffff


def _add(a, b):
    if a < 0 or b < 0 or a > U64_MAX - b:
        _fail("BOUNDS", "64-bit region overflow")
    return a + b


def _align(value):
    return _add(value, 15) & ~15


@dataclass(frozen=True)
class ChunkEntry:
    chunk_id: int
    chunk_type: str
    required: bool
    codec: int
    file_offset: int
    stored_length: int
    raw_length: int
    sha256: bytes


class ChunkCollection(dict):
    """In-memory ``chunkId -> bytes`` mapping with directory metadata in ``entries``."""

    def __init__(self, payloads=None, *, chunk_types=None, required=True):
        super().__init__()
        self.entries = {}
        for cid, raw in (payloads or {}).items():
            self.add(cid, raw, (chunk_types or {}).get(cid, "DATA"), required)

    def add(self, chunk_id, raw, chunk_type="DATA", required=True):
        raw = bytes(raw)
        if not _u32(chunk_id, True) or chunk_id in self:
            _fail("CHUNK_ID", "chunk IDs must be unique nonzero u32 values")
        if isinstance(chunk_type, bytes):
            chunk_type = chunk_type.decode("ascii")
        if (not isinstance(chunk_type, str) or len(chunk_type) != 4
                or not all(32 <= ord(c) <= 126 for c in chunk_type)):
            _fail("CHUNK_ENTRY", "chunk type must be an ASCII FourCC")
        if not raw or len(raw) > MAX_CHUNK:
            _fail("CHUNK_ENTRY", "chunk length must be 1..256 MiB")
        self[chunk_id] = raw
        self.entries[chunk_id] = ChunkEntry(chunk_id, chunk_type, bool(required), 0, 0,
                                          len(raw), len(raw), hashlib.sha256(raw).digest())


def has_chunk(payloads, chunk_id):
    return chunk_id in payloads


def chunk_length(payloads, chunk_id):
    """Uncompressed length; does not fetch a lazy chunk."""
    if hasattr(payloads, "entries"):
        return payloads.entries[chunk_id].raw_length
    return len(payloads[chunk_id])


def chunk_type(payloads, chunk_id):
    """FourCC string; plain byte mappings default to DATA."""
    if hasattr(payloads, "entries"):
        return payloads.entries[chunk_id].chunk_type
    return "DATA"


class _Source:
    def __init__(self, data, file_size=None):
        self.data = data
        if callable(data):
            if type(file_size) is not int or not 0 <= file_size <= U64_MAX:
                _fail("BOUNDS", "range readers require a u64 file_size")
            self.size = file_size
        elif hasattr(data, "seek") and hasattr(data, "read"):
            pos = data.tell()
            data.seek(0, 2)
            self.size = data.tell()
            data.seek(pos)
        else:
            # Mutable input must not change after its metadata was validated.
            self.data = data if isinstance(data, bytes) else bytes(data)
            self.size = len(self.data)

    def read(self, offset, length):
        if _add(offset, length) > self.size:
            _fail("BOUNDS", "read outside physical file")
        if callable(self.data):
            result = self.data(offset, length)
        elif hasattr(self.data, "seek"):
            self.data.seek(offset)
            result = self.data.read(length)
        else:
            result = self.data[offset:offset + length]
        if len(result) != length:
            _fail("BOUNDS", "truncated range read")
        return bytes(result)

    def padding(self, start, end):
        if end < start or end - start > 15:
            _fail("BOUNDS", "unaddressed bytes are not alignment padding")
        if any(self.read(start, end - start)):
            _fail("PADDING", "alignment padding must be zero")


class ChunkStore(Mapping):
    """Lazy verified payload mapping. Source streams must remain open while in use."""

    def __init__(self, source, entries, dependencies):
        from types import MappingProxyType
        self._source = source
        self.entries = MappingProxyType(dict(entries))
        self.dependencies = MappingProxyType(dict(dependencies))
        self._cache = {}

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def __contains__(self, key):
        return key in self.entries

    def dependency_closure(self, chunk_ids):
        """Return deterministic prerequisite-first IDs without fetching payloads."""
        if type(chunk_ids) is int:
            chunk_ids = (chunk_ids,)
        result, seen = [], set()
        for root in sorted(set(chunk_ids)):
            if root not in self.entries:
                _fail("DEPENDENCY", f"unknown requested chunk {root}")
            stack = [(root, False)]
            while stack:
                cid, done = stack.pop()
                if cid in seen:
                    continue
                if done:
                    seen.add(cid)
                    result.append(cid)
                else:
                    stack.append((cid, True))
                    stack.extend((dep, False) for dep in reversed(self.dependencies.get(cid, ())))
        return tuple(result)

    def _load_one(self, cid):
        if cid not in self._cache:
            entry = self.entries[cid]
            _supported(entry)
            raw = self._source.read(entry.file_offset, entry.stored_length)
            if not hmac.compare_digest(hashlib.sha256(raw).digest(), entry.sha256):
                _fail("HASH_MISMATCH", f"SHA-256 mismatch in chunk {cid}")
            self._cache[cid] = raw
        return self._cache[cid]

    def load_requested(self, chunk_ids):
        order = self.dependency_closure(chunk_ids)
        # Fail unsupported capabilities before fetching any prerequisite bytes.
        for cid in order:
            _supported(self.entries[cid])
        return {cid: self._load_one(cid) for cid in order}

    def __getitem__(self, cid):
        if cid not in self.entries:
            raise KeyError(cid)
        self.load_requested((cid,))
        return self._cache[cid]

    def load(self, cid):
        return self[cid]

    def verify_all(self):
        """Explicit full integrity validation (including otherwise unused chunks)."""
        self.load_requested(self.entries)


def _supported(entry):
    if entry.chunk_type not in KNOWN_TYPES:
        _fail("UNSUPPORTED_CHUNK", f"unsupported chunk type {entry.chunk_type}")
    if entry.codec != 0:
        _fail("UNSUPPORTED_CODEC", f"unsupported codec {entry.codec}")


def _dependencies(doc, entries):
    records = doc.get("chunkDependencies", [])
    if not isinstance(records, list):
        _fail("DEPENDENCY", "chunkDependencies must be an array")
    graph = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"chunkId", "requires"}:
            _fail("DEPENDENCY", "invalid dependency record")
        cid, deps = record["chunkId"], record["requires"]
        if (not _u32(cid, True) or cid not in entries or cid in graph
                or not isinstance(deps, list)
                or any(not _u32(d, True) or d not in entries or d == cid for d in deps)
                or len(set(deps)) != len(deps)):
            _fail("DEPENDENCY", "invalid, missing or duplicate dependency")
        graph[cid] = tuple(sorted(deps))
    colors = {}
    for root in entries:
        stack = [(root, False)]
        while stack:
            cid, done = stack.pop()
            if done:
                colors[cid] = 2
                continue
            if colors.get(cid) == 1:
                _fail("DEPENDENCY_CYCLE", "cyclic chunk dependencies")
            if colors.get(cid) == 2:
                continue
            colors[cid] = 1
            stack.append((cid, True))
            stack.extend((dep, False) for dep in reversed(graph.get(cid, ())))
    # A required GEOM's prerequisite chain may not require an unsupported optional feature.
    pending = [cid for cid, e in entries.items() if e.required and e.chunk_type == "GEOM"]
    seen = set()
    while pending:
        cid = pending.pop()
        if cid in seen:
            continue
        seen.add(cid)
        for dep in graph.get(cid, ()):
            _supported(entries[dep])
            pending.append(dep)
    return graph


def _views(doc, entries):
    views = doc.get("bufferViews", [])
    if not isinstance(views, list):
        _fail("BUFFER_VIEW", "bufferViews must be an array")
    for view in views:
        if (not isinstance(view, dict) or set(view) != {"chunkId", "byteOffset", "byteLength"}
                or not all(_u32(view[k], k == "chunkId")
                           for k in ("chunkId", "byteOffset", "byteLength"))):
            _fail("BUFFER_VIEW", "invalid chunk-addressed buffer view")
        entry = entries.get(view["chunkId"])
        if entry is None or view["byteOffset"] + view["byteLength"] > entry.raw_length:
            _fail("BUFFER_VIEW", "view extends beyond its chunk")
        if entry.chunk_type not in KNOWN_TYPES:
            _fail("UNSUPPORTED_CHUNK", "view references unknown chunk type")


def _stream_hints(doc, entries):
    hints = doc.get("streamHints", [])
    if not isinstance(hints, list):
        _fail("STREAM_HINT", "streamHints must be an array")
    seen = set()
    for hint in hints:
        if (not isinstance(hint, dict) or set(hint) != {"chunkId", "priority"}
                or not _u32(hint["chunkId"], True) or hint["chunkId"] not in entries
                or hint["chunkId"] in seen or not _u32(hint["priority"])
                or hint["priority"] > 255):
            _fail("STREAM_HINT", "invalid stream hint chunk ID or priority")
        seen.add(hint["chunkId"])


def read_container(data, expected_magic, limits=DEFAULT_LIMITS, *, file_size=None):
    """Return ``(doc, ChunkStore)`` without payload reads.

    ``data`` is immutable bytes, a seekable binary stream, or a callable
    ``read_range(offset, length)`` accompanied by ``file_size``. Only metadata
    and at most 15 padding bytes per region are read until chunks are requested.
    """
    source = _Source(data, file_size)
    if source.size < HEADER_SIZE:
        _fail("TRUNCATED_HEADER", "file shorter than the 64-byte header")
    (magic, major, minor, hsize, flags, size, moff, mlen, doff,
     count, esize, reserved) = HEADER.unpack(source.read(0, HEADER_SIZE))
    if (expected_magic not in (ADM_MAGIC, ANIM_MAGIC) or magic != expected_magic
            or (major, minor, hsize, flags, moff, esize, reserved)
            != (VERSION_MAJOR, VERSION_MINOR, HEADER_SIZE, 0, HEADER_SIZE, ENTRY.size, 0)):
        _fail("HEADER", "unsupported magic, version or header fields")
    if (size != source.size or not 2 <= mlen <= MAX_MANIFEST or count > 65535
            or doff != _align(_add(moff, mlen)) or _add(doff, count * ENTRY.size) > size):
        _fail("BOUNDS", "invalid file, manifest or directory bounds")
    _limit(mlen > limits.max_json_bytes or count > limits.max_chunks,
           "manifest or directory exceeds configured limit")
    doc = parse_json_strict(source.read(moff, mlen), limits)
    source.padding(moff + mlen, doff)
    directory_end = doff + count * ENTRY.size
    data_start = _align(directory_end)
    if data_start > size:
        _fail("BOUNDS", "directory alignment exceeds physical file")
    source.padding(directory_end, data_start)
    directory = source.read(doff, count * ENTRY.size)
    entries, last_id, total_raw, total_stored = {}, 0, 0, 0
    for i in range(count):
        cid, typ, eflags, codec, res, off, stored, raw, sha = ENTRY.unpack_from(directory, i * ENTRY.size)
        if not 0 < cid <= 0xffffffff or cid <= last_id:
            _fail("CHUNK_ID", "chunk IDs must be nonzero, unique and increasing")
        if (eflags & ~1 or res or not stored or not 0 < raw <= MAX_CHUNK
                or any(c < 32 or c > 126 for c in typ)):
            _fail("CHUNK_ENTRY", "invalid chunk flags, type or lengths")
        if off % 16 or off < data_start or _add(off, stored) > size:
            _fail("CHUNK_BOUNDS", "unaligned or out-of-bounds chunk")
        if codec == 0 and stored != raw:
            _fail("CHUNK_SIZE", "RAW stored and raw lengths differ")
        total_raw = _add(total_raw, raw)
        total_stored = _add(total_stored, stored)
        _limit(raw > limits.max_chunk_bytes or total_raw > limits.max_total_raw_bytes
               or total_stored > limits.max_stored_bytes,
               "chunk lengths exceed configured limits")
        entry = ChunkEntry(cid, typ.decode("ascii"), bool(eflags & 1), codec, off, stored, raw, sha)
        if entry.required:
            _supported(entry)
        entries[cid] = entry
        last_id = cid
    cursor = data_start
    for entry in sorted(entries.values(), key=lambda e: e.file_offset):
        if entry.file_offset < cursor:
            _fail("CHUNK_BOUNDS", "overlapping chunks")
        if entry.file_offset != _align(cursor):
            _fail("CHUNK_BOUNDS", "unaddressed bytes between chunks")
        source.padding(cursor, entry.file_offset)
        cursor = entry.file_offset + entry.stored_length
    if size not in (cursor, _align(cursor)):
        _fail("TRAILING_BYTES", "bytes after final payload")
    source.padding(cursor, size)
    _views(doc, entries)
    dependencies = _dependencies(doc, entries)
    _stream_hints(doc, entries)
    return doc, ChunkStore(source, entries, dependencies)


def _sanitize(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("refusing to write non-finite number")
        return 0.0 if value == 0.0 else value
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def dump_json(doc):
    return json.dumps(_sanitize(doc), separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def write_container(magic, doc, payloads=None, *, chunk_types=None, limits=DEFAULT_LIMITS):
    """Write RAW chunks. Plain mappings use DATA, or ``chunk_types[id]`` FourCC.

    ``ChunkCollection`` and ``ChunkStore`` preserve type/required metadata.
    No legacy monolithic BIN input is accepted.
    """
    if magic not in (ADM_MAGIC, ANIM_MAGIC):
        _fail("HEADER", "unsupported magic")
    if payloads is None:
        payloads = ChunkCollection()
    if not isinstance(payloads, Mapping):
        raise TypeError("payloads must be a chunkId -> bytes mapping")
    _limit(len(payloads) > limits.max_chunks, "too many chunks")
    if len(payloads) > 65535:
        _fail("BOUNDS", "too many chunks")
    if any(not _u32(cid, True) for cid in payloads):
        _fail("CHUNK_ID", "chunk IDs must be nonzero u32 values")
    js = dump_json(doc)
    if not 2 <= len(js) <= MAX_MANIFEST:
        _fail("BOUNDS", "manifest exceeds interoperable limit")
    _limit(len(js) > limits.max_json_bytes, "manifest exceeds configured limit")
    parse_json_strict(js, limits)
    doff = _align(HEADER_SIZE + len(js))
    cursor = _align(doff + len(payloads) * ENTRY.size)
    packed, blocks, metadata = [], [], {}
    total_raw = 0
    for cid in sorted(payloads):
        raw = bytes(payloads[cid])
        previous = getattr(payloads, "entries", {}).get(cid)
        typ = (chunk_types or {}).get(cid, previous.chunk_type if previous else "DATA")
        required = previous.required if previous else True
        one = ChunkCollection()
        one.add(cid, raw, typ, required)
        entry = one.entries[cid]
        if required:
            _supported(entry)
        total_raw = _add(total_raw, len(raw))
        _limit(len(raw) > limits.max_chunk_bytes or total_raw > limits.max_total_raw_bytes
               or total_raw > limits.max_stored_bytes, "chunks exceed configured limits")
        packed.append(ENTRY.pack(cid, entry.chunk_type.encode("ascii"), int(required), 0, 0,
                                 cursor, len(raw), len(raw), entry.sha256))
        blocks.append((cursor, raw))
        metadata[cid] = entry
        cursor = _align(_add(cursor, len(raw)))
    _views(doc, metadata)
    _dependencies(doc, metadata)
    _stream_hints(doc, metadata)
    out = bytearray(cursor)
    out[:HEADER_SIZE] = HEADER.pack(magic, VERSION_MAJOR, VERSION_MINOR, HEADER_SIZE, 0,
                                    cursor, HEADER_SIZE, len(js), doff, len(packed), ENTRY.size, 0)
    out[HEADER_SIZE:HEADER_SIZE + len(js)] = js
    out[doff:doff + len(packed) * ENTRY.size] = b"".join(packed)
    for off, raw in blocks:
        out[off:off + len(raw)] = raw
    return bytes(out)
