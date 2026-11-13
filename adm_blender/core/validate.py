"""Independent file-level validator for ``.adm`` and ``.adm_anim`` (ADM 1.0 Draft 0.4).

Usage::

    python -m adm_blender.core.validate file.adm [file2.adm_anim ...]

Exit code 0 when every file is valid (warnings allowed), 1 otherwise.
"""

import json
import math
import re
import struct
import sys

from . import constants as K
from .buffers import read_accessor_flat, read_accessor_np, read_view
from .container import (AdmFormatError, DEFAULT_LIMITS, ResourceLimitError, read_container)
from .mathutil import (IDENTITY, det3, mat_mul, mat_translation, node_local_matrix, vcross, vlen, vsub)
from .rigid import rig_id_from_document

try:  # optional acceleration
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

U32_MAX = 2 ** 32 - 1
EXT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
LIBRARY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(@[a-z][a-z0-9_]*)*$")
EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)*\.v[0-9]+$")
RIG_ID_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+$")
SHADER_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ANIMATION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
BCP47_RE = re.compile(
    r"^(?:(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4,8})"
    r"(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*"
    r"(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
    r"(?:-[Xx](?:-[A-Za-z0-9]{1,8})+)?"
    r"|[Xx](?:-[A-Za-z0-9]{1,8})+)$")


# ------------------------------------------------------------------------------------------------
class Issue:
    __slots__ = ("severity", "code", "path", "message")

    def __init__(self, severity, code, path, message):
        self.severity, self.code, self.path, self.message = severity, code, path, message

    def __str__(self):
        return f"{self.severity.upper():7s} {self.code:28s} {self.path}: {self.message}"


class Report:
    def __init__(self, kind):
        self.kind = kind
        self.issues = []
        self.doc = None
        self.bin = None
        self.resource_limit = False

    def error(self, code, path, message):
        self.issues.append(Issue("error", code, path, message))

    def warning(self, code, path, message):
        self.issues.append(Issue("warning", code, path, message))

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self):
        return not self.errors

    def format(self, limit=None):
        items = self.issues if limit is None else self.issues[:limit]
        lines = [str(i) for i in items]
        if limit is not None and len(self.issues) > limit:
            lines.append(f"... {len(self.issues) - limit} more")
        return "\n".join(lines)


# ------------------------------------------------------------------------------------------------
def _is_int(v, lo=0, hi=U32_MAX):
    return type(v) is int and lo <= v <= hi


def _is_num(v):
    return type(v) in (int, float) and math.isfinite(v)


def _is_vec(v, n):
    return isinstance(v, list) and len(v) == n and all(_is_num(x) for x in v)


def _is_str(v):
    return isinstance(v, str)


def _nonblank(v):
    return isinstance(v, str) and v.strip() != ""


def _f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def is_exact_semver(v):
    return isinstance(v, str) and SEMVER_RE.match(v) is not None and "+" not in v


def param_value_error(param, value, ntex=None):
    """Return an error message when ``value`` does not fit the typed shader parameter (§8.2)."""
    typ = param.get("type")
    if typ in K.SHADER_NUMERIC_DIMS:
        n = K.SHADER_NUMERIC_DIMS[typ]
        vals = [value] if n == 1 else value
        if n == 1 and not _is_num(value):
            return f"{typ} parameter needs a finite number"
        if n > 1 and not _is_vec(value, n):
            return f"{typ} parameter needs {n} finite numbers"
        lo, hi = param.get("minimum"), param.get("maximum")
        lo = [lo] if n == 1 and lo is not None else lo
        hi = [hi] if n == 1 and hi is not None else hi
        for i, x in enumerate(vals):
            if lo is not None and _is_vec(lo, n) and x < lo[i]:
                return f"component {i} = {x} below minimum {lo[i]}"
            if hi is not None and _is_vec(hi, n) and x > hi[i]:
                return f"component {i} = {x} above maximum {hi[i]}"
        return None
    if typ == "BOOL":
        return None if isinstance(value, bool) else "BOOL parameter needs true/false"
    if typ == "TEXTURE":
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - {"index", "texCoord"} or not _is_int(value.get("index")):
            return "TEXTURE parameter needs null or a textureRef {index, texCoord?}"
        if ntex is not None and value["index"] >= ntex:
            return f"texture index {value['index']} out of range"
        if value.get("texCoord", 0) not in (0, 1) or type(value.get("texCoord", 0)) is not int:
            return "texCoord must be 0 or 1"
        return None
    return f"unknown parameter type {typ!r}"


def shader_registry(doc):
    """(id, version) -> {name: param} for official shaders plus the document's embedded definitions."""
    table = {k: {p["name"]: p for p in v} for k, v in K.OFFICIAL_SHADERS.items()}
    defs = doc.get("shaderDefinitions") if isinstance(doc, dict) else None
    if isinstance(defs, list):
        for d in defs:
            if isinstance(d, dict) and isinstance(d.get("parameters"), list):
                key = (d.get("id"), d.get("version"))
                if key not in table:
                    table[key] = {p.get("name"): p for p in d["parameters"] if isinstance(p, dict)}
    return table


def material_shader(m):
    sh = m.get("shader") if isinstance(m, dict) else None
    if isinstance(sh, dict):
        return sh.get("id"), sh.get("version")
    return K.SHADER_CORE


class _Base:
    def __init__(self, report):
        self.r = report
        self.doc = None
        self.bin = b""
        self.good_acc = set()
        self.acc_cache = {}

    # generic helpers ---------------------------------------------------------------------------
    def keys(self, obj, path, required=(), optional=()):
        if not isinstance(obj, dict):
            self.r.error("TYPE_OBJECT", path, "must be a JSON object")
            return False
        ok = True
        for k in required:
            if k not in obj:
                self.r.error("MISSING_FIELD", path, f"required field '{k}' missing")
                ok = False
        allowed = set(required) | set(optional) | {"extras", "extensions"}
        for k in obj:
            if k not in allowed:
                code = "IMAGE_EXTERNAL_URI" if k == "uri" else "UNKNOWN_FIELD"
                self.r.error(code, path, f"field '{k}' is not permitted here")
                ok = False
        if "extras" in obj and not isinstance(obj["extras"], dict):
            self.r.error("EXTRAS_TYPE", path + ".extras", "extras must be a JSON object")
        if "extensions" in obj:
            self.check_extensions_obj(obj["extensions"], path + ".extensions")
        return ok

    def check_extensions_obj(self, ext, path):
        if not isinstance(ext, dict):
            self.r.error("EXTENSIONS_TYPE", path, "extensions must be a JSON object")
            return
        used = self.doc.get("extensionsUsed", []) if isinstance(self.doc, dict) else []
        for name in ext:
            if not isinstance(used, list) or name not in used:
                self.r.error("EXTENSION_NOT_DECLARED", path, f"extension '{name}' not listed in extensionsUsed")

    def array(self, name, required=False):
        if name not in self.doc:
            if required:
                return []
            return []
        v = self.doc[name]
        if not isinstance(v, list):
            self.r.error("TYPE_ARRAY", name, "must be a JSON array")
            return []
        return v

    def index(self, v, length, path, what):
        if not _is_int(v):
            self.r.error("TYPE_INDEX", path, f"must be a u32 index into {what}")
            return False
        if v >= length:
            self.r.error("INDEX_RANGE", path, f"index {v} out of range for {what} (length {length})")
            return False
        return True

    def check_extensions_top(self):
        used = self.doc.get("extensionsUsed", [])
        req = self.doc.get("extensionsRequired", [])
        for name, arr in (("extensionsUsed", used), ("extensionsRequired", req)):
            if not isinstance(arr, list):
                self.r.error("TYPE_ARRAY", name, "must be an array")
                continue
            if len(set(x for x in arr if isinstance(x, str))) != len(arr):
                self.r.error("EXTENSION_DUPLICATE", name, "entries must be unique strings")
            for x in arr:
                if not isinstance(x, str) or not EXT_NAME_RE.match(x):
                    self.r.error("EXTENSION_NAME", name, f"invalid extension name {x!r}")
        if isinstance(used, list) and isinstance(req, list):
            for x in req:
                if x not in used:
                    self.r.error("EXTENSION_REQUIRED_NOT_USED", "extensionsRequired",
                                 f"'{x}' must also be listed in extensionsUsed")
                elif x not in K.SUPPORTED_EXTENSIONS:
                    self.r.error("EXTENSION_UNSUPPORTED", "extensionsRequired",
                                 f"required extension '{x}' is not supported by this implementation")
        if "extensions" in self.doc:
            self.check_extensions_obj(self.doc["extensions"], "extensions")
        if "extras" in self.doc and not isinstance(self.doc["extras"], dict):
            self.r.error("EXTRAS_TYPE", "extras", "extras must be a JSON object")

    def check_asset(self):
        asset = self.doc.get("asset")
        if not isinstance(asset, dict):
            self.r.error("TYPE_OBJECT", "asset", "asset must be an object")
            return
        for k in asset:
            if k == "version" or k == "minVersion":
                self.r.error("ASSET_VERSION", "asset", "version must only come from the binary header")
            elif k not in ("generator", "copyright", "extras", "extensions"):
                self.r.error("UNKNOWN_FIELD", "asset", f"field '{k}' is not permitted")
        for k in ("generator", "copyright"):
            if k in asset and not _is_str(asset[k]):
                self.r.error("TYPE_STRING", f"asset.{k}", "must be a string")
        if "extras" in asset and not isinstance(asset["extras"], dict):
            self.r.error("EXTRAS_TYPE", "asset.extras", "extras must be a JSON object")

    # buffers -------------------------------------------------------------------------------------
    def check_buffers(self):
        views = self.array("bufferViews")
        self.good_views = set()
        for i, v in enumerate(views):
            p = f"bufferViews[{i}]"
            if not self.keys(v, p, ("chunkId", "byteOffset", "byteLength")):
                continue
            if not _is_int(v["chunkId"], 1) or not _is_int(v["byteOffset"]) or not _is_int(v["byteLength"]):
                self.r.error("TYPE_U32", p, "chunkId must be nonzero u32; offsets/lengths must be u32")
                continue
            entry = self.bin.entries.get(v["chunkId"])
            if entry is None:
                self.r.error("VIEW_CHUNK", p, "view references a missing chunk")
                continue
            if entry.chunk_type not in ("GEOM", "ANIM", "DATA", "IMAG"):
                self.r.error("VIEW_CHUNK_TYPE", p, "view must reference GEOM, ANIM, DATA or IMAG")
                continue
            if v["byteOffset"] + v["byteLength"] > entry.raw_length:
                self.r.error("VIEW_RANGE", p, "view exceeds uncompressed chunk length")
                continue
            self.good_views.add(i)
        accs = self.array("accessors")
        for i, a in enumerate(accs):
            p = f"accessors[{i}]"
            if not self.keys(a, p, ("bufferView", "componentType", "type", "count"), ("byteOffset", "normalized")):
                continue
            if not self.index(a["bufferView"], len(views), p + ".bufferView", "bufferViews"):
                continue
            ct, ty = a["componentType"], a["type"]
            if ct not in K.COMPONENT_SIZES:
                self.r.error("ACCESSOR_COMPONENT", p, f"invalid componentType {ct!r}")
                continue
            if ty not in K.TYPE_COUNTS:
                self.r.error("ACCESSOR_TYPE", p, f"invalid type {ty!r}")
                continue
            if not _is_int(a["count"]):
                self.r.error("TYPE_U32", p + ".count", "must be a u32 integer")
                continue
            off = a.get("byteOffset", 0)
            if not _is_int(off):
                self.r.error("TYPE_U32", p + ".byteOffset", "must be a u32 integer")
                continue
            norm = a.get("normalized", False)
            if not isinstance(norm, bool):
                self.r.error("TYPE_BOOL", p + ".normalized", "must be a boolean")
                continue
            if norm and ct not in ("U8", "U16"):
                self.r.error("ACCESSOR_NORMALIZED", p, "normalized is only allowed for U8 and U16")
            if a["bufferView"] not in self.good_views:
                continue
            view = views[a["bufferView"]]
            if self.r.kind == "adm_anim" and self.bin.entries[view["chunkId"]].chunk_type != "ANIM":
                self.r.error("ANIMATION_CHUNK_TYPE", p, "animation accessors must reference ANIM chunks")
                continue
            csize = K.COMPONENT_SIZES[ct]
            nbytes = a["count"] * K.TYPE_COUNTS[ty] * csize
            if off + nbytes > view["byteLength"]:
                self.r.error("ACCESSOR_RANGE", p, "accessor data does not fit in its bufferView")
                continue
            if (view["byteOffset"] + off) % csize:
                self.r.error("ACCESSOR_ALIGNMENT", p, f"absolute start not aligned to {csize} bytes")
                continue
            if ct == "F32" and a["count"]:
                if _np is not None:
                    arr = read_accessor_np(self.doc, self.bin, i)
                    finite = bool(_np.all(_np.isfinite(arr)))
                else:
                    flat, _ = read_accessor_flat(self.doc, self.bin, i)
                    finite = all(math.isfinite(x) for x in flat)
                if not finite:
                    self.r.error("ACCESSOR_NONFINITE", p, "float data contains NaN or Infinity")
                    continue
            self.good_acc.add(i)

    def acc(self, index):
        """Decoded accessor as numpy array (count, ncomp) when numpy is present, else list of tuples."""
        if index in self.acc_cache:
            return self.acc_cache[index]
        acc = self.doc["accessors"][index]
        if _np is not None:
            data = read_accessor_np(self.doc, self.bin, index, _np.float64)
        else:
            flat, ncomp = read_accessor_flat(self.doc, self.bin, index)
            if acc.get("normalized", False):
                s = 1.0 / K.COMPONENT_MAX[acc["componentType"]]
                flat = [x * s for x in flat]
            data = [tuple(flat[i:i + ncomp]) for i in range(0, len(flat), ncomp)]
        self.acc_cache[index] = data
        return data

    def use_acc(self, index, path, comp_types, types, normalized=None, min_count=1):
        """Validate accessor usage; return True when data can be read."""
        accs = self.doc.get("accessors", [])
        if not self.index(index, len(accs) if isinstance(accs, list) else 0, path, "accessors"):
            return False
        if index not in self.good_acc:
            self.r.error("ACCESSOR_INVALID", path, f"references invalid accessor {index}")
            return False
        a = accs[index]
        if a["componentType"] not in comp_types or a["type"] not in types:
            self.r.error("ACCESSOR_USAGE", path,
                         f"accessor {index} is {a['componentType']} {a['type']}, expected "
                         f"{'/'.join(comp_types)} {'/'.join(types)}")
            return False
        if normalized is not None:
            want = normalized(a["componentType"]) if callable(normalized) else normalized
            if bool(a.get("normalized", False)) != want:
                self.r.error("ACCESSOR_NORMALIZED", path,
                             f"accessor {index} must {'be' if want else 'not be'} normalized")
                return False
        if a["count"] < min_count:
            self.r.error("ACCESSOR_COUNT", path, f"accessor {index} count must be >= {min_count}")
            return False
        return True


# ------------------------------------------------------------------------------------------------
class AdmValidator(_Base):
    def run(self):
        d = self.doc
        for k in K.ADM_REQUIRED_TOP:
            if k not in d:
                self.r.error("MISSING_FIELD", "$", f"required top-level member '{k}' missing")
        allowed = set(K.ADM_REQUIRED_TOP) | set(K.ADM_OPTIONAL_TOP)
        for k in d:
            if k not in allowed:
                code = "ANIM_IN_MODEL" if k == "animations" else "UNKNOWN_FIELD"
                self.r.error(code, "$", f"top-level member '{k}' is not permitted")
        self.check_asset()
        self.check_extensions_top()
        self.check_buffers()
        self.nodes = self.array("nodes")
        self.meshes = self.array("meshes")
        self.skins = self.array("skins")
        self.materials = self.array("materials")
        self.check_textures()
        self.check_shader_definitions()
        self.check_materials()
        self.check_meshes()
        self.check_nodes_and_scenes()
        self.check_skins()
        self.check_node_mesh_usage()
        self.check_skeleton_profiles()
        self.check_facial_profiles()
        self.check_expressions()
        self.check_ik()
        self.check_component_roles()
        self.check_colliders()
        self.check_lods()
        self.check_attachments()
        self.check_physical_metadata()
        self.check_model_components()

    # textures ------------------------------------------------------------------------------------
    def check_textures(self):
        images = self.array("images")
        views = self.array("bufferViews")
        for i, im in enumerate(images):
            p = f"images[{i}]"
            if not self.keys(im, p, ("bufferView", "mimeType"), ("name",)):
                continue
            if "name" in im and not _is_str(im["name"]):
                self.r.error("TYPE_STRING", p + ".name", "must be a string")
            if im["mimeType"] not in K.IMAGE_MIMES:
                self.r.error("IMAGE_MIME", p, f"mimeType {im['mimeType']!r} not allowed")
                continue
            if not self.index(im["bufferView"], len(views), p + ".bufferView", "bufferViews"):
                continue
            if im["bufferView"] not in self.good_views:
                continue
            v = views[im["bufferView"]]
            if self.bin.entries[v["chunkId"]].chunk_type != "IMAG":
                self.r.error("IMAGE_CHUNK_TYPE", p, "image views must reference IMAG chunks")
                continue
            if im["mimeType"] == "image/ktx2":
                self.r.warning("KTX2_FALLBACK", p,
                               "KTX2 decoding is unsupported; portable image will be used")
                continue
            blob = read_view(self.doc, self.bin, im["bufferView"])
            if im["mimeType"] == "image/png":
                if not blob.startswith(b"\x89PNG\r\n\x1a\n") or b"IEND" not in blob[-12:]:
                    self.r.error("IMAGE_DECODE", p, "bufferView does not contain exactly one PNG image")
                elif b"acTL" in blob[:4096]:
                    self.r.error("IMAGE_ANIMATED", p, "animated PNG (APNG) is not allowed")
            elif im["mimeType"] == "image/jpeg":
                if not (blob.startswith(b"\xff\xd8\xff") and blob.rstrip(b"\x00").endswith(b"\xff\xd9")):
                    self.r.error("IMAGE_DECODE", p, "bufferView does not contain exactly one JPEG image")
        samplers = self.array("samplers")
        for i, s in enumerate(samplers):
            p = f"samplers[{i}]"
            if not self.keys(s, p, (), ("magFilter", "minFilter", "wrapS", "wrapT", "name")):
                continue
            for k in ("magFilter", "minFilter"):
                if k in s and s[k] not in K.FILTERS:
                    self.r.error("SAMPLER_FILTER", f"{p}.{k}", f"invalid value {s[k]!r}")
            for k in ("wrapS", "wrapT"):
                if k in s and s[k] not in K.WRAPS:
                    self.r.error("SAMPLER_WRAP", f"{p}.{k}", f"invalid value {s[k]!r}")
        textures = self.array("textures")
        for i, t in enumerate(textures):
            p = f"textures[{i}]"
            if not self.keys(t, p, ("source",), ("sampler", "fallbackSource")):
                continue
            source_ok = self.index(t["source"], len(images), p + ".source", "images")
            source = images[t["source"]] if source_ok else {}
            is_ktx = isinstance(source, dict) and source.get("mimeType") == "image/ktx2"
            if is_ktx:
                if "fallbackSource" not in t:
                    self.r.error("IMAGE_FALLBACK_REQUIRED", p, "KTX2 requires a PNG/JPEG fallbackSource")
                elif self.index(t["fallbackSource"], len(images), p + ".fallbackSource", "images"):
                    fallback = images[t["fallbackSource"]]
                    if not isinstance(fallback, dict) or fallback.get("mimeType") not in ("image/png", "image/jpeg"):
                        self.r.error("IMAGE_FALLBACK_TYPE", p, "fallbackSource must reference PNG/JPEG")
            elif "fallbackSource" in t:
                self.r.error("IMAGE_FALLBACK_FORBIDDEN", p, "only KTX2 sources may declare fallbackSource")
            if "sampler" in t:
                self.index(t["sampler"], len(samplers), p + ".sampler", "samplers")

    # shaders -------------------------------------------------------------------------------------
    def check_shader_param_def(self, prm, p, ntex):
        if not self.keys(prm, p, ("name", "type", "default", "description"),
                         ("minimum", "maximum", "animatable")):
            return False
        ok = True
        if not isinstance(prm["name"], str) or not PARAM_NAME_RE.match(prm["name"]):
            self.r.error("SHADER_PARAM_NAME", p + ".name", f"invalid parameter name {prm['name']!r}")
            ok = False
        typ = prm["type"]
        if typ not in K.SHADER_PARAM_TYPES:
            self.r.error("SHADER_PARAM_TYPE", p + ".type", f"invalid parameter type {typ!r}")
            return False
        if not _nonblank(prm["description"]) or len(prm["description"]) > 2048:
            self.r.error("TEXT_BLANK", p + ".description", "description must be non-whitespace text <= 2048")
        numeric = typ in K.SHADER_NUMERIC_DIMS
        if "animatable" in prm:
            if not isinstance(prm["animatable"], bool):
                self.r.error("TYPE_BOOL", p + ".animatable", "must be a boolean")
            elif prm["animatable"] and not numeric:
                self.r.error("SHADER_PARAM_ANIMATABLE", p + ".animatable", f"{typ} parameters cannot be animatable")
        for b in ("minimum", "maximum"):
            if b not in prm:
                continue
            if not numeric:
                self.r.error("SHADER_PARAM_BOUNDS", f"{p}.{b}", f"bounds are not allowed for {typ}")
                ok = False
                continue
            n = K.SHADER_NUMERIC_DIMS[typ]
            if not ((n == 1 and _is_num(prm[b])) or (n > 1 and _is_vec(prm[b], n))):
                self.r.error("SHADER_PARAM_BOUNDS", f"{p}.{b}", f"must be {'a finite number' if n == 1 else f'{n} finite numbers'}")
                ok = False
        if ok and numeric and "minimum" in prm and "maximum" in prm:
            lo = prm["minimum"] if isinstance(prm["minimum"], list) else [prm["minimum"]]
            hi = prm["maximum"] if isinstance(prm["maximum"], list) else [prm["maximum"]]
            if any(a > b for a, b in zip(lo, hi)):
                self.r.error("SHADER_PARAM_BOUNDS", p, "minimum must be <= maximum componentwise")
                ok = False
        if ok:
            err = param_value_error(prm, prm["default"], ntex)
            if err:
                self.r.error("SHADER_PARAM_DEFAULT", p + ".default", err)
        return ok

    def check_shader_definitions(self):
        ntex = len(self.array("textures"))
        defs = self.array("shaderDefinitions")
        seen = set()
        for i, d in enumerate(defs):
            p = f"shaderDefinitions[{i}]"
            if not self.keys(d, p, ("id", "version", "parameters"), ("description", "author")):
                continue
            sid, ver = d["id"], d["version"]
            if not isinstance(sid, str) or not SHADER_ID_RE.match(sid) or not 3 <= len(sid.encode()) <= 160:
                self.r.error("SHADER_ID", p + ".id", f"invalid shader id {sid!r}")
            elif sid.startswith("adm."):
                self.r.error("SHADER_OFFICIAL_REDEFINED", p + ".id", "official adm.* shaders must not be embedded")
            if not is_exact_semver(ver):
                self.r.error("SHADER_VERSION", p + ".version", f"invalid exact SemVer {ver!r}")
            key = (sid, ver) if isinstance(sid, str) and isinstance(ver, str) else None
            if key in seen:
                self.r.error("SHADER_DEFINITION_DUPLICATE", p, f"duplicate definition {sid}@{ver}")
            seen.add(key)
            for k in ("description", "author"):
                if k in d and not _is_str(d[k]):
                    self.r.error("TYPE_STRING", f"{p}.{k}", "must be a string")
            if not isinstance(d["parameters"], list):
                self.r.error("TYPE_ARRAY", p + ".parameters", "must be an array")
                continue
            names = set()
            for j, prm in enumerate(d["parameters"]):
                pp = f"{p}.parameters[{j}]"
                if self.check_shader_param_def(prm, pp, ntex):
                    if prm["name"] in names:
                        self.r.error("SHADER_PARAM_DUPLICATE", pp + ".name", f"duplicate parameter {prm['name']!r}")
                    names.add(prm["name"])
        self.shaders = shader_registry(self.doc)

    def check_layer_record(self, rec, p):
        if not self.keys(rec, p, ("baseColorFactor", "metallicFactor", "roughnessFactor", "emissiveFactor"),
                         ("normalFactor",)):
            return
        if not (_is_vec(rec["baseColorFactor"], 4) and all(0 <= x <= 1 for x in rec["baseColorFactor"])):
            self.r.error("MATERIAL_RANGE", p + ".baseColorFactor", "must be 4 numbers in [0,1]")
        for k in ("metallicFactor", "roughnessFactor"):
            if not (_is_num(rec[k]) and 0 <= rec[k] <= 1):
                self.r.error("MATERIAL_RANGE", f"{p}.{k}", "must be a number in [0,1]")
        if not (_is_vec(rec["emissiveFactor"], 3) and all(x >= 0 for x in rec["emissiveFactor"])):
            self.r.error("MATERIAL_RANGE", p + ".emissiveFactor", "must be 3 finite numbers >= 0")
        if "normalFactor" in rec and not (_is_vec(rec["normalFactor"], 3) and vlen(rec["normalFactor"]) > 0):
            self.r.error("MATERIAL_LAYER_NORMAL", p + ".normalFactor", "must be a nonzero vec3")

    def check_material_shader(self, m, p, ntex):
        if "animationId" in m:
            aid = m["animationId"]
            if not isinstance(aid, str) or not ANIMATION_ID_RE.match(aid):
                self.r.error("MATERIAL_ANIMATION_ID", p + ".animationId", f"invalid animationId {aid!r}")
            elif aid in self.animation_ids:
                self.r.error("MATERIAL_ANIMATION_ID_DUPLICATE", p + ".animationId", f"duplicate animationId {aid!r}")
            else:
                self.animation_ids[aid] = m
        key = K.SHADER_CORE
        if "shader" in m:
            sh = m["shader"]
            if not self.keys(sh, p + ".shader", ("id", "version")):
                return
            sid, ver = sh["id"], sh["version"]
            if not isinstance(sid, str) or not SHADER_ID_RE.match(sid) or not 3 <= len(sid.encode()) <= 160:
                self.r.error("SHADER_ID", p + ".shader.id", f"invalid shader id {sid!r}")
                return
            if not is_exact_semver(ver):
                self.r.error("SHADER_VERSION", p + ".shader.version", f"invalid exact SemVer {ver!r}")
                return
            key = (sid, ver)
        if key != K.SHADER_CORE:
            missing = [field for field in K.PBR_FALLBACK_FIELDS if field not in m]
            if missing:
                self.r.error("ADM_ERR_MISSING_PBR_FALLBACK", p,
                             f"non-core shaders require explicit portable PBR fields: {', '.join(missing)}")
        params = self.shaders.get(key)
        if params is None:
            if key[0].startswith("adm."):
                self.r.warning("SHADER_UNKNOWN_OFFICIAL", p + ".shader",
                               f"official shader {key[0]}@{key[1]} unknown to this validator; PBR fallback applies")
            else:
                self.r.error("SHADER_DEFINITION_MISSING", p + ".shader",
                             f"custom shader {key[0]}@{key[1]} has no embedded shaderDefinitions entry")
        sp = m.get("shaderParameters")
        if sp is not None:
            if not isinstance(sp, dict):
                self.r.error("TYPE_OBJECT", p + ".shaderParameters", "must be a JSON object")
            elif key == K.SHADER_CORE and sp:
                self.r.error("SHADER_CORE_PARAMETERS", p + ".shaderParameters",
                             "the core PBR shader must not have shader parameters")
            elif params is not None:
                for name, val in sp.items():
                    prm = params.get(name)
                    if prm is None:
                        self.r.error("SHADER_PARAM_UNKNOWN", f"{p}.shaderParameters.{name}",
                                     f"unknown parameter for {key[0]}@{key[1]}")
                        continue
                    err = param_value_error(prm, val, ntex)
                    if err:
                        self.r.error("SHADER_PARAM_VALUE", f"{p}.shaderParameters.{name}", err)
                    elif prm.get("type") == "TEXTURE" and isinstance(val, dict):
                        self.material_uv_needs.setdefault(self._mi, set()).add("TEXCOORD_%d" % val.get("texCoord", 0))
        if params and any(pr.get("animatable") for pr in params.values()) and "animationId" not in m:
            self.r.error("MATERIAL_ANIMATION_ID_REQUIRED", p,
                         "materials using a shader with animatable parameters must provide animationId")
        ext = m.get("extensions") if isinstance(m.get("extensions"), dict) else {}
        layers = ext.get(K.LAYERS_EXT)
        if key == K.SHADER_LAYERED:
            if layers is None:
                self.r.error("MATERIAL_LAYERS_MISSING", p, f"{key[0]} requires extensions.{K.LAYERS_EXT}")
        elif layers is not None:
            self.r.warning("MATERIAL_LAYERS_UNUSED", p, f"{K.LAYERS_EXT} present but shader is not {K.SHADER_LAYERED[0]}")
        if layers is not None:
            lp = f"{p}.extensions.{K.LAYERS_EXT}"
            if self.keys(layers, lp, ("base", "overlay"), ("maskTexture",)):
                self.check_layer_record(layers["base"], lp + ".base")
                self.check_layer_record(layers["overlay"], lp + ".overlay")
                if "maskTexture" in layers:
                    ref = layers["maskTexture"]
                    if self.keys(ref, lp + ".maskTexture", ("index",), ("texCoord",)):
                        self.index(ref["index"], ntex, lp + ".maskTexture.index", "textures")
                        tc = ref.get("texCoord", 0)
                        if tc not in (0, 1) or type(tc) is not int:
                            self.r.error("MATERIAL_TEXCOORD", lp + ".maskTexture.texCoord", "must be 0 or 1")
                        else:
                            self.material_uv_needs.setdefault(self._mi, set()).add("TEXCOORD_%d" % tc)

    # materials -----------------------------------------------------------------------------------
    def check_materials(self):
        ntex = len(self.array("textures"))
        self.material_uv_needs = {}
        self.animation_ids = {}
        for i, m in enumerate(self.materials):
            p = f"materials[{i}]"
            if not self.keys(m, p, (), ("name", "baseColorFactor", "baseColorTexture", "metallicFactor",
                                         "roughnessFactor", "metallicRoughnessTexture", "normalTexture",
                                         "occlusionTexture", "emissiveTexture", "emissiveFactor", "alphaMode",
                                         "alphaCutoff", "doubleSided", "shader", "shaderParameters",
                                         "animationId")):
                continue
            needs = set()
            if "baseColorFactor" in m and not (_is_vec(m["baseColorFactor"], 4)
                                               and all(0 <= x <= 1 for x in m["baseColorFactor"])):
                self.r.error("MATERIAL_RANGE", p + ".baseColorFactor", "must be 4 numbers in [0,1]")
            for k in ("metallicFactor", "roughnessFactor", "alphaCutoff"):
                if k in m and not (_is_num(m[k]) and 0 <= m[k] <= 1):
                    self.r.error("MATERIAL_RANGE", f"{p}.{k}", "must be a number in [0,1]")
            if "emissiveFactor" in m and not (_is_vec(m["emissiveFactor"], 3)
                                              and all(x >= 0 for x in m["emissiveFactor"])):
                self.r.error("MATERIAL_RANGE", p + ".emissiveFactor", "must be 3 finite numbers >= 0")
            if "alphaMode" in m and m["alphaMode"] not in K.ALPHA_MODES:
                self.r.error("MATERIAL_ALPHA_MODE", p + ".alphaMode", f"invalid value {m['alphaMode']!r}")
            if "doubleSided" in m and not isinstance(m["doubleSided"], bool):
                self.r.error("TYPE_BOOL", p + ".doubleSided", "must be a boolean")
            for k in ("baseColorTexture", "metallicRoughnessTexture", "emissiveTexture", "normalTexture",
                      "occlusionTexture"):
                if k not in m:
                    continue
                ref = m[k]
                extra = ("scale",) if k == "normalTexture" else ("strength",) if k == "occlusionTexture" else ()
                if not self.keys(ref, f"{p}.{k}", ("index",), ("texCoord",) + extra):
                    continue
                self.index(ref["index"], ntex, f"{p}.{k}.index", "textures")
                tc = ref.get("texCoord", 0)
                if tc not in (0, 1) or type(tc) is not int:
                    self.r.error("MATERIAL_TEXCOORD", f"{p}.{k}.texCoord", "must be 0 or 1")
                else:
                    needs.add("TEXCOORD_%d" % tc)
                if "scale" in ref and not (_is_num(ref["scale"]) and ref["scale"] >= 0):
                    self.r.error("MATERIAL_RANGE", f"{p}.{k}.scale", "must be a finite number >= 0")
                if "strength" in ref and not (_is_num(ref["strength"]) and 0 <= ref["strength"] <= 1):
                    self.r.error("MATERIAL_RANGE", f"{p}.{k}.strength", "must be in [0,1]")
                if k == "normalTexture":
                    needs.add("@normalmap")
            self.material_uv_needs[i] = needs
            self._mi = i
            self.check_material_shader(m, p, ntex)

    # meshes --------------------------------------------------------------------------------------
    def check_meshes(self):
        self.mesh_targets = {}
        self.mesh_skinned = {}
        self.mesh_max_joint = {}
        self.mesh_vcount = {}
        attr_rules = {
            "POSITION": (("F32",), ("VEC3",), False),
            "NORMAL": (("F32",), ("VEC3",), False),
            "TANGENT": (("F32",), ("VEC4",), False),
            "TEXCOORD_0": (("F32",), ("VEC2",), False),
            "TEXCOORD_1": (("F32",), ("VEC2",), False),
            "COLOR_0": (("U8", "F32"), ("VEC4",), lambda ct: ct == "U8"),
            "JOINTS_0": (("U8", "U16"), ("VEC4",), False),
            "WEIGHTS_0": (("F32", "U8", "U16"), ("VEC4",), lambda ct: ct != "F32"),
        }
        nmat = len(self.materials)
        for mi, mesh in enumerate(self.meshes):
            p = f"meshes[{mi}]"
            if not self.keys(mesh, p, ("primitives",), ("name", "targetNames", "weights")):
                continue
            prims = mesh["primitives"]
            if not isinstance(prims, list) or not prims:
                self.r.error("MESH_PRIMITIVES", p, "primitives must be a non-empty array")
                continue
            ntargets = None
            skinned = None
            max_joint = -1
            for pi, prim in enumerate(prims):
                pp = f"{p}.primitives[{pi}]"
                if not self.keys(prim, pp, ("attributes", "indices"), ("material", "targets", "mode")):
                    continue
                if "mode" in prim:
                    self.r.error("MESH_TOPOLOGY", pp, "only triangle lists exist in ADM 1.0 ('mode' forbidden)")
                attrs = prim["attributes"]
                if not isinstance(attrs, dict):
                    self.r.error("TYPE_OBJECT", pp + ".attributes", "must be an object")
                    continue
                if "POSITION" not in attrs:
                    self.r.error("MESH_NO_POSITION", pp, "POSITION attribute is required")
                    continue
                for sem in attrs:
                    if sem not in attr_rules:
                        self.r.error("MESH_ATTRIBUTE_UNKNOWN", pp, f"unknown attribute semantic '{sem}'")
                ok_attrs = {}
                for sem, (cts, tys, norm) in attr_rules.items():
                    if sem in attrs and self.use_acc(attrs[sem], f"{pp}.attributes.{sem}", cts, tys, norm):
                        ok_attrs[sem] = attrs[sem]
                if "POSITION" not in ok_attrs:
                    continue
                vcount = self.doc["accessors"][ok_attrs["POSITION"]]["count"]
                if vcount < 3:
                    self.r.error("MESH_VERTEX_COUNT", pp, "POSITION count must be >= 3")
                self.mesh_vcount.setdefault(mi, []).append(vcount)
                for sem, ai in ok_attrs.items():
                    if self.doc["accessors"][ai]["count"] != vcount:
                        self.r.error("MESH_ATTRIBUTE_COUNT", f"{pp}.attributes.{sem}",
                                     "attribute count differs from POSITION count")
                        ok_attrs[sem] = None
                has_j, has_w = "JOINTS_0" in attrs, "WEIGHTS_0" in attrs
                if has_j != has_w:
                    self.r.error("MESH_SKIN_PAIR", pp, "JOINTS_0 and WEIGHTS_0 must occur together")
                prim_skinned = has_j and has_w
                if skinned is None:
                    skinned = prim_skinned
                elif skinned != prim_skinned:
                    self.r.error("MESH_SKIN_MIXED", pp, "all primitives of a mesh must agree on skinning")
                # indices
                if self.use_acc(prim["indices"], pp + ".indices", ("U16", "U32"), ("SCALAR",), False, 3):
                    ic = self.doc["accessors"][prim["indices"]]["count"]
                    if ic % 3:
                        self.r.error("MESH_INDEX_COUNT", pp + ".indices", "index count must be divisible by 3")
                    else:
                        idx = self.acc(prim["indices"])
                        if _np is not None:
                            mx = int(idx.max()) if len(idx) else 0
                            tri = idx.reshape(-1, 3)
                            degenerate = int(_np.count_nonzero((tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2])
                                                               | (tri[:, 0] == tri[:, 2])))
                        else:
                            flat = [v[0] for v in idx]
                            mx = max(flat) if flat else 0
                            degenerate = sum(1 for t in range(0, len(flat), 3)
                                             if len({flat[t], flat[t + 1], flat[t + 2]}) < 3)
                        if mx >= vcount:
                            self.r.error("MESH_INDEX_RANGE", pp + ".indices", f"index {mx} >= vertex count {vcount}")
                        if degenerate:
                            self.r.warning("MESH_DEGENERATE", pp, f"{degenerate} triangle(s) repeat a vertex index")
                # unit vectors
                for sem in ("NORMAL", "TANGENT"):
                    if ok_attrs.get(sem) is None:
                        continue
                    data = self.acc(ok_attrs[sem])
                    if _np is not None:
                        lens = _np.linalg.norm(data[:, :3], axis=1)
                        bad = int(_np.count_nonzero(_np.abs(lens - 1.0) > 1e-3))
                        badw = int(_np.count_nonzero(_np.abs(_np.abs(data[:, 3]) - 1.0) > 1e-6)) if sem == "TANGENT" else 0
                    else:
                        bad = sum(1 for v in data if abs(vlen(v[:3]) - 1.0) > 1e-3)
                        badw = sum(1 for v in data if abs(abs(v[3]) - 1.0) > 1e-6) if sem == "TANGENT" else 0
                    if bad:
                        self.r.error("MESH_UNIT_VECTOR", f"{pp}.attributes.{sem}", f"{bad} vector(s) not unit length")
                    if badw:
                        self.r.error("MESH_TANGENT_W", f"{pp}.attributes.TANGENT", "tangent w must be +1 or -1")
                if prim_skinned and ok_attrs.get("WEIGHTS_0") is not None and ok_attrs.get("JOINTS_0") is not None:
                    w = self.acc(ok_attrs["WEIGHTS_0"])
                    j = self.acc(ok_attrs["JOINTS_0"])
                    if _np is not None:
                        sums = w.sum(axis=1)
                        if bool(_np.any(w < 0)):
                            self.r.error("MESH_WEIGHT_NEGATIVE", pp, "negative skin weight")
                        nbad = int(_np.count_nonzero(_np.abs(sums - 1.0) > 1e-3))
                        if nbad:
                            self.r.error("MESH_WEIGHT_SUM", pp, f"{nbad} vertex weight sum(s) outside 1±1e-3")
                        used = j[w > 0]
                        max_joint = max(max_joint, int(used.max()) if used.size else -1)
                    else:
                        for wi, (wv, jv) in enumerate(zip(w, j)):
                            if any(x < 0 for x in wv):
                                self.r.error("MESH_WEIGHT_NEGATIVE", pp, f"vertex {wi} has a negative weight")
                                break
                            if abs(sum(wv) - 1.0) > 1e-3:
                                self.r.error("MESH_WEIGHT_SUM", pp, f"vertex {wi} weight sum outside 1±1e-3")
                                break
                            for x, jj in zip(wv, jv):
                                if x > 0:
                                    max_joint = max(max_joint, int(jj))
                if "material" in prim:
                    if self.index(prim["material"], nmat, pp + ".material", "materials"):
                        for need in self.material_uv_needs.get(prim["material"], ()):
                            if need == "@normalmap":
                                if "NORMAL" not in attrs or "TANGENT" not in attrs:
                                    self.r.warning("MATERIAL_NORMALMAP_TANGENTS", pp,
                                                   "normalTexture used without NORMAL+TANGENT; readers must "
                                                   "generate tangents or report unsupported shading")
                            elif need not in attrs:
                                self.r.error("MATERIAL_TEXCOORD_MISSING", pp,
                                             f"material {prim['material']} requires {need}")
                # morph targets
                tg = prim.get("targets")
                n = 0 if tg is None else (len(tg) if isinstance(tg, list) else -1)
                if n < 0:
                    self.r.error("TYPE_ARRAY", pp + ".targets", "must be an array")
                    continue
                if ntargets is None:
                    ntargets = n
                elif ntargets != n:
                    self.r.error("MORPH_COUNT", pp, "all primitives must have the same number of targets")
                for ti, t in enumerate(tg or []):
                    tp = f"{pp}.targets[{ti}]"
                    if not self.keys(t, tp, (), ("POSITION", "NORMAL", "TANGENT")):
                        continue
                    for sem in ("POSITION", "NORMAL", "TANGENT"):
                        if sem in t and self.use_acc(t[sem], f"{tp}.{sem}", ("F32",), ("VEC3",), False):
                            if self.doc["accessors"][t[sem]]["count"] != vcount:
                                self.r.error("MORPH_VERTEX_COUNT", f"{tp}.{sem}", "count differs from POSITION count")
                    if "NORMAL" in t and "NORMAL" not in attrs:
                        self.r.warning("MORPH_NORMAL_WITHOUT_BASE", tp, "NORMAL delta without base NORMAL is ignored")
            ntargets = ntargets or 0
            self.mesh_targets[mi] = ntargets
            self.mesh_skinned[mi] = bool(skinned)
            self.mesh_max_joint[mi] = max_joint
            names = mesh.get("targetNames")
            weights = mesh.get("weights")
            if ntargets == 0:
                if names is not None or weights is not None:
                    self.r.error("MORPH_COUNT", p, "mesh without targets must not have targetNames/weights")
            else:
                if names is not None:
                    if not isinstance(names, list) or len(names) != ntargets:
                        self.r.error("MORPH_NAMES", p + ".targetNames", f"must have exactly {ntargets} entries")
                    else:
                        if not all(_nonblank(x) for x in names):
                            self.r.error("MORPH_NAMES", p + ".targetNames", "names must be nonempty strings")
                        if len(set(names)) != len(names):
                            self.r.error("MORPH_NAMES_DUPLICATE", p + ".targetNames", "names must be unique")
                if weights is not None and not (isinstance(weights, list) and len(weights) == ntargets
                                                 and all(_is_num(w) and 0 <= w <= 1 for w in weights)):
                    self.r.error("MORPH_WEIGHTS", p + ".weights", f"must be {ntargets} numbers in [0,1]")

    def target_names(self, mesh_index):
        mesh = self.meshes[mesh_index] if 0 <= mesh_index < len(self.meshes) else None
        if not isinstance(mesh, dict):
            return []
        names = mesh.get("targetNames")
        return names if isinstance(names, list) else []

    # nodes / scenes ------------------------------------------------------------------------------
    def check_nodes_and_scenes(self):
        n = len(self.nodes)
        self.parent = [None] * n
        self.local = [list(IDENTITY)] * n
        self.world = [None] * n
        self.node_ok = [False] * n
        for i, node in enumerate(self.nodes):
            p = f"nodes[{i}]"
            if not self.keys(node, p, (), ("name", "children", "translation", "rotation", "scale", "matrix",
                                           "mesh", "skin", "weights")):
                continue
            ok = True
            if "name" in node and not _is_str(node["name"]):
                self.r.error("TYPE_STRING", p + ".name", "must be a string")
            if "matrix" in node:
                if any(k in node for k in ("translation", "rotation", "scale")):
                    self.r.error("NODE_MATRIX_TRS", p, "matrix and TRS are mutually exclusive")
                    ok = False
                if not _is_vec(node["matrix"], 16):
                    self.r.error("NODE_MATRIX", p + ".matrix", "must be 16 finite numbers")
                    ok = False
            if "translation" in node and not _is_vec(node["translation"], 3):
                self.r.error("NODE_TRANSLATION", p, "translation must be vec3")
                ok = False
            if "scale" in node and not _is_vec(node["scale"], 3):
                self.r.error("NODE_SCALE", p, "scale must be vec3")
                ok = False
            if "rotation" in node:
                q = node["rotation"]
                if not _is_vec(q, 4):
                    self.r.error("NODE_ROTATION", p, "rotation must be a quaternion [x,y,z,w]")
                    ok = False
                elif abs(math.sqrt(sum(x * x for x in q)) - 1.0) > 1e-4:
                    self.r.error("NODE_QUAT_NORM", p, "rotation quaternion length outside 1±1e-4")
            if "mesh" in node:
                self.index(node["mesh"], len(self.meshes), p + ".mesh", "meshes")
            if "skin" in node:
                self.index(node["skin"], len(self.skins), p + ".skin", "skins")
                if "mesh" not in node:
                    self.r.error("NODE_SKIN_WITHOUT_MESH", p, "skin requires mesh")
            if "weights" in node:
                nt = self.mesh_targets.get(node.get("mesh"), 0) if _is_int(node.get("mesh", -1)) else 0
                w = node["weights"]
                if nt == 0:
                    self.r.error("NODE_WEIGHTS", p, "weights require a mesh with morph targets")
                elif not (isinstance(w, list) and len(w) == nt and all(_is_num(x) and 0 <= x <= 1 for x in w)):
                    self.r.error("NODE_WEIGHTS", p + ".weights", f"must be {nt} numbers in [0,1]")
            ch = node.get("children", [])
            if not isinstance(ch, list):
                self.r.error("TYPE_ARRAY", p + ".children", "must be an array")
                ch = []
            if len(set(c for c in ch if _is_int(c))) != len(ch):
                self.r.error("NODE_CHILD_DUPLICATE", p + ".children", "duplicate child indices")
            for c in ch:
                if self.index(c, n, p + ".children", "nodes"):
                    if c == i:
                        self.r.error("NODE_CYCLE", p, "node is its own child")
                    elif self.parent[c] is not None and self.parent[c] != i:
                        self.r.error("NODE_MULTI_PARENT", f"nodes[{c}]", "node has more than one parent")
                    else:
                        self.parent[c] = i
            if ok:
                self.local[i] = node_local_matrix(node)
            self.node_ok[i] = ok
        scenes = self.array("scenes")
        if not scenes:
            self.r.error("SCENES_EMPTY", "scenes", "scenes must be a non-empty array")
        if "scene" in self.doc:
            self.index(self.doc["scene"], len(scenes), "scene", "scenes")
        self.node_scene = [None] * n
        for si, sc in enumerate(scenes):
            p = f"scenes[{si}]"
            if not self.keys(sc, p, ("nodes",), ("name",)):
                continue
            roots = sc["nodes"]
            if not isinstance(roots, list):
                self.r.error("TYPE_ARRAY", p + ".nodes", "must be an array")
                continue
            for r in roots:
                if not self.index(r, n, p + ".nodes", "nodes"):
                    continue
                if self.parent[r] is not None:
                    self.r.error("SCENE_ROOT_HAS_PARENT", p, f"root node {r} also occurs as a child")
                    continue
                stack = [(r, IDENTITY)]
                while stack:
                    ni, pw = stack.pop()
                    if self.node_scene[ni] is not None:
                        self.r.error("SCENE_OVERLAP" if self.node_scene[ni] != si else "NODE_CYCLE",
                                     f"nodes[{ni}]", "node reachable more than once")
                        continue
                    self.node_scene[ni] = si
                    self.world[ni] = mat_mul(pw, self.local[ni])
                    node = self.nodes[ni]
                    for c in (node.get("children", []) if isinstance(node, dict) else []):
                        if _is_int(c) and c < n and self.parent[c] == ni:
                            stack.append((c, self.world[ni]))
        for i in range(n):
            if self.node_scene[i] is None:
                self.r.error("NODE_UNREACHABLE", f"nodes[{i}]", "node is not reachable from any scene (or in a cycle)")
                self.world[i] = list(IDENTITY)

    def is_ancestor(self, a, b):
        """True when node a is a strict ancestor of node b."""
        seen = 0
        p = self.parent[b] if 0 <= b < len(self.parent) else None
        while p is not None and seen <= len(self.parent):
            if p == a:
                return True
            p = self.parent[p]
            seen += 1
        return False

    # skins -----------------------------------------------------------------------------------------
    def check_skins(self):
        n = len(self.nodes)
        self.joint_nodes = set()
        self.skin_ok = {}
        nprof = len(self.array("skeletonProfiles"))
        for si, skin in enumerate(self.skins):
            p = f"skins[{si}]"
            if not self.keys(skin, p, ("joints", "inverseBindMatrices"), ("name", "skeletonProfile")):
                continue
            joints = skin["joints"]
            if not isinstance(joints, list) or not joints:
                self.r.error("SKIN_JOINTS", p + ".joints", "must be a non-empty array")
                continue
            if not all(self.index(j, n, p + ".joints", "nodes") for j in joints):
                continue
            if len(set(joints)) != len(joints):
                self.r.error("SKIN_JOINTS_DUPLICATE", p + ".joints", "joint node indices must be unique")
            for j in joints:
                self.joint_nodes.add(j)
                node = self.nodes[j]
                if not isinstance(node, dict):
                    continue
                if "matrix" in node:
                    self.r.error("SKIN_JOINT_MATRIX", f"nodes[{j}]", "skin joints must use TRS")
                s = node.get("scale", [1, 1, 1])
                if _is_vec(s, 3) and any(x <= 0 for x in s):
                    self.r.error("SKIN_JOINT_SCALE", f"nodes[{j}]", "skin joints must have positive scale")
                if abs(det3(self.world[j])) < 1e-12:
                    self.r.error("SKIN_JOINT_SINGULAR", f"nodes[{j}]", "joint world matrix is not invertible")
            scenes = {self.node_scene[j] for j in joints}
            if len(scenes) > 1:
                self.r.error("SKIN_SCENES", p, "all joints must be in the same scene")
            if self.use_acc(skin["inverseBindMatrices"], p + ".inverseBindMatrices", ("F32",), ("MAT4",), False):
                cnt = self.doc["accessors"][skin["inverseBindMatrices"]]["count"]
                if cnt != len(joints):
                    self.r.error("SKIN_IBM_COUNT", p, "inverseBindMatrices count must equal joints length")
                else:
                    ibm = self.acc(skin["inverseBindMatrices"])
                    for k in range(cnt):
                        if abs(det3(list(ibm[k]))) < 1e-12:
                            self.r.error("SKIN_IBM_SINGULAR", p, f"inverse bind matrix {k} is not invertible")
                            break
                    self.skin_ok[si] = True
            if "skeletonProfile" in skin:
                self.index(skin["skeletonProfile"], nprof, p + ".skeletonProfile", "skeletonProfiles")

    def check_node_mesh_usage(self):
        for i, node in enumerate(self.nodes):
            if not isinstance(node, dict) or not _is_int(node.get("mesh", -1)) or node.get("mesh", -1) >= len(self.meshes):
                continue
            mi = node["mesh"]
            skinned = self.mesh_skinned.get(mi, False)
            if skinned and "skin" not in node:
                self.r.error("MESH_SKIN_USAGE", f"nodes[{i}]", "skinned mesh used by a node without skin")
            if not skinned and "skin" in node:
                self.r.error("MESH_SKIN_USAGE", f"nodes[{i}]", "unskinned mesh used by a node with skin")
            if skinned and _is_int(node.get("skin", -1)) and node["skin"] < len(self.skins):
                skin = self.skins[node["skin"]]
                if isinstance(skin, dict) and isinstance(skin.get("joints"), list):
                    if self.mesh_max_joint.get(mi, -1) >= len(skin["joints"]):
                        self.r.error("MESH_JOINT_RANGE", f"nodes[{i}]",
                                     "mesh uses a joint index >= skin.joints length")
                    js = {self.node_scene[j] for j in skin["joints"] if _is_int(j) and j < len(self.nodes)}
                    if js and self.node_scene[i] not in js:
                        self.r.error("SKIN_SCENES", f"nodes[{i}]", "skin joints must be in the mesh node's scene")
            if abs(det3(self.world[i])) < 1e-12 and "NORMAL" in str(self.meshes[mi]):
                self.r.warning("NODE_SINGULAR", f"nodes[{i}]", "node matrix is not invertible; normals undefined")

    # skeleton profiles ---------------------------------------------------------------------------
    def check_skeleton_profiles(self):
        profiles = self.array("skeletonProfiles")
        self.profile_roles = []
        for pi, prof in enumerate(profiles):
            p = f"skeletonProfiles[{pi}]"
            self.profile_roles.append({})
            if not self.keys(prof, p, ("id", "skin", "roles"),
                             ("referencePose", "targetHeight", "referenceCorrection", "rigId")):
                continue
            pid = prof["id"]
            if not isinstance(pid, str) or not (pid in K.BUILTIN_SKELETON_PROFILES or PROFILE_ID_RE.match(pid)):
                self.r.error("PROFILE_ID", p + ".id", f"invalid or unversioned profile id {pid!r}")
            if not self.index(prof["skin"], len(self.skins), p + ".skin", "skins"):
                continue
            skin = self.skins[prof["skin"]]
            joints = set(skin.get("joints", [])) if isinstance(skin, dict) and isinstance(skin.get("joints"), list) else set()
            roles = prof["roles"]
            if not isinstance(roles, dict):
                self.r.error("TYPE_OBJECT", p + ".roles", "must be an object")
                continue
            seen_nodes = {}
            for role, node in roles.items():
                if not self.index(node, len(self.nodes), f"{p}.roles.{role}", "nodes"):
                    continue
                if node not in joints:
                    self.r.error("PROFILE_ROLE_NOT_JOINT", f"{p}.roles.{role}", f"node {node} is not in skin joints")
                if node in seen_nodes:
                    self.r.error("PROFILE_ROLE_DUPLICATE_NODE", f"{p}.roles.{role}",
                                 f"node {node} already mapped to '{seen_nodes[node]}'")
                seen_nodes[node] = role
            self.profile_roles[pi] = dict(roles)
            if pid == "humanoid.vrm1":
                for role in roles:
                    if role not in K.VRM1_PARENT:
                        self.r.error("PROFILE_ROLE_UNKNOWN", f"{p}.roles", f"'{role}' is not a VRM 1.0 humanoid role")
                missing = [r for r in K.VRM1_REQUIRED if r not in roles]
                if missing:
                    self.r.error("PROFILE_ROLE_MISSING", p, "missing required humanoid roles: " + ", ".join(missing))
                if prof.get("referencePose") != "T":
                    self.r.error("PROFILE_REFERENCE_POSE", p, "humanoid.vrm1 requires referencePose \"T\"")
                node_role = {v: k for k, v in roles.items() if _is_int(v) and v < len(self.nodes)}
                for role, node in roles.items():
                    if role not in K.VRM1_PARENT or not _is_int(node) or node >= len(self.nodes):
                        continue
                    expected = K.VRM1_PARENT[role]
                    while expected is not None and expected not in roles:
                        expected = K.VRM1_PARENT[expected]
                    actual = None
                    a = self.parent[node]
                    guard = 0
                    while a is not None and guard <= len(self.nodes):
                        if a in node_role:
                            actual = node_role[a]
                            break
                        a = self.parent[a]
                        guard += 1
                    if actual != expected:
                        self.r.error("PROFILE_HIERARCHY", f"{p}.roles.{role}",
                                     f"nearest mapped ancestor is {actual!r}, VRM hierarchy requires {expected!r}")
            elif "referencePose" in prof and prof["referencePose"] != "T":
                self.r.error("PROFILE_REFERENCE_POSE", p, "referencePose must be \"T\"")
            if "targetHeight" in prof and not (_is_num(prof["targetHeight"]) and prof["targetHeight"] > 0):
                self.r.error("PROFILE_TARGET_HEIGHT", p + ".targetHeight", "must be a finite number > 0")
            if "referenceCorrection" in prof:
                rc = prof["referenceCorrection"]
                if not isinstance(rc, dict):
                    self.r.error("TYPE_OBJECT", p + ".referenceCorrection", "must be an object")
                else:
                    for role, q in rc.items():
                        if role not in roles:
                            self.r.error("PROFILE_CORRECTION_ROLE", p + ".referenceCorrection", f"unknown role {role!r}")
                        if not _is_vec(q, 4) or abs(math.sqrt(sum(x * x for x in q)) - 1) > 1e-4:
                            self.r.error("PROFILE_CORRECTION_QUAT", f"{p}.referenceCorrection.{role}",
                                         "must be a unit quaternion")
            if "rigId" in prof:
                rid = prof["rigId"]
                if not isinstance(rid, str) or not RIG_ID_RE.match(rid):
                    self.r.error("RIG_ID_FORMAT", p + ".rigId", "must be 64 lowercase hex digits")
                elif self.skin_ok.get(prof["skin"]) and all(_is_int(v) for v in roles.values()):
                    try:
                        calc = rig_id_from_document(self.doc, self.bin, prof["skin"], roles)
                    except Exception as exc:  # malformed TRS etc.
                        self.r.error("RIG_ID_COMPUTE", p, f"cannot compute rig fingerprint: {exc}")
                    else:
                        if calc != rid:
                            self.r.error("RIG_ID_MISMATCH", p + ".rigId", f"declared {rid} but computed {calc}")

    # face ----------------------------------------------------------------------------------------
    def morph_node_targets(self, node_index):
        node = self.nodes[node_index] if 0 <= node_index < len(self.nodes) else None
        if not isinstance(node, dict) or not _is_int(node.get("mesh", -1)) or node.get("mesh", -1) >= len(self.meshes):
            return None
        return self.target_names(node["mesh"])

    def check_facial_profiles(self):
        for fi, fp in enumerate(self.array("facialProfiles")):
            p = f"facialProfiles[{fi}]"
            if not self.keys(fp, p, ("id", "bindings"), ("coverage",)):
                continue
            if fp["id"] != K.FACE_PROFILE_ID:
                if isinstance(fp["id"], str) and PROFILE_ID_RE.match(fp["id"]):
                    self.r.warning("FACE_PROFILE_UNKNOWN", p + ".id", f"unknown facial profile {fp['id']!r}")
                else:
                    self.r.error("FACE_PROFILE_ID", p + ".id", f"invalid facial profile id {fp['id']!r}")
                continue
            cov = fp.get("coverage")
            if cov not in ("partial", "complete"):
                self.r.error("FACE_COVERAGE", p + ".coverage", "coverage must be \"partial\" or \"complete\"")
            bindings = fp["bindings"]
            if not isinstance(bindings, list):
                self.r.error("TYPE_ARRAY", p + ".bindings", "must be an array")
                continue
            seen = set()
            channels = set()
            for bi, b in enumerate(bindings):
                bp = f"{p}.bindings[{bi}]"
                if not self.keys(b, bp, ("channel", "node", "target"), ("scale",)):
                    continue
                if b["channel"] not in K.ARKIT52_SET:
                    self.r.error("FACE_CHANNEL", bp + ".channel", f"{b['channel']!r} is not an ARKit52 channel")
                else:
                    channels.add(b["channel"])
                if "scale" in b and not (_is_num(b["scale"]) and 0 <= b["scale"] <= 1):
                    self.r.error("FACE_SCALE", bp + ".scale", "must be in [0,1]")
                if self.index(b["node"], len(self.nodes), bp + ".node", "nodes"):
                    names = self.morph_node_targets(b["node"])
                    if not names:
                        self.r.error("FACE_NODE_NOT_MORPH", bp + ".node", "node has no morph-capable mesh")
                    elif b["target"] not in names:
                        self.r.error("FACE_TARGET_MISSING", bp + ".target", f"mesh has no target {b['target']!r}")
                key = (b["channel"], b["node"], b["target"])
                if key in seen:
                    self.r.error("FACE_BINDING_DUPLICATE", bp, "duplicate (channel,node,target)")
                seen.add(key)
            if cov == "complete" and len(channels) != 52:
                missing = [c for c in K.ARKIT52 if c not in channels]
                self.r.error("FACE_COVERAGE_INCOMPLETE", p, f"coverage complete but {len(missing)} channels unbound "
                                                            f"(e.g. {', '.join(missing[:5])})")

    def check_expressions(self):
        names = set()
        for ei, ex in enumerate(self.array("expressions")):
            p = f"expressions[{ei}]"
            if not self.keys(ex, p, ("name", "bindings"), ("priority", "group")):
                continue
            if not _nonblank(ex["name"]):
                self.r.error("EXPRESSION_NAME", p + ".name", "must be a nonempty string")
            elif ex["name"] in names:
                self.r.error("EXPRESSION_DUPLICATE", p + ".name", f"duplicate expression {ex['name']!r}")
            names.add(ex["name"])
            if "priority" in ex and not _is_int(ex["priority"]):
                self.r.error("TYPE_U32", p + ".priority", "must be a u32")
            if "group" in ex and ex["group"] not in K.EXPRESSION_GROUPS:
                self.r.error("EXPRESSION_GROUP", p + ".group", f"invalid group {ex['group']!r}")
            if not isinstance(ex["bindings"], list):
                self.r.error("TYPE_ARRAY", p + ".bindings", "must be an array")
                continue
            for bi, b in enumerate(ex["bindings"]):
                bp = f"{p}.bindings[{bi}]"
                if not self.keys(b, bp, ("node", "target", "weight")):
                    continue
                if not (_is_num(b["weight"]) and 0 <= b["weight"] <= 1):
                    self.r.error("EXPRESSION_WEIGHT", bp + ".weight", "must be in [0,1]")
                if self.index(b["node"], len(self.nodes), bp + ".node", "nodes"):
                    tn = self.morph_node_targets(b["node"])
                    if not tn or b["target"] not in tn:
                        self.r.error("EXPRESSION_TARGET", bp, f"node {b['node']} has no morph target {b['target']!r}")

    # IK --------------------------------------------------------------------------------------------
    def check_ik(self):
        ids = set()
        used = {}
        for ci, ch in enumerate(self.array("ikChains")):
            p = f"ikChains[{ci}]"
            if not self.keys(ch, p, ("id", "solver", "root", "mid", "end", "pole"),
                             ("effectorOffset", "weight", "stretch", "targetSpace")):
                continue
            if not _nonblank(ch["id"]):
                self.r.error("IK_ID", p + ".id", "must be a nonempty string")
            elif ch["id"] in ids:
                self.r.error("IK_ID_DUPLICATE", p + ".id", f"duplicate chain id {ch['id']!r}")
            ids.add(ch["id"])
            if ch["solver"] != "TWO_BONE":
                self.r.error("IK_SOLVER", p + ".solver", "ADM-IK-1 only defines TWO_BONE")
            if ch.get("effectorOffset", [0, 0, 0]) != [0, 0, 0] and not (
                    _is_vec(ch.get("effectorOffset"), 3) and all(x == 0 for x in ch["effectorOffset"])):
                self.r.error("IK_EFFECTOR_OFFSET", p + ".effectorOffset", "must be [0,0,0] for TWO_BONE")
            if ch.get("stretch", False) is not False:
                self.r.error("IK_STRETCH", p + ".stretch", "must be false in 1.0")
            if ch.get("targetSpace", "MODEL") != "MODEL":
                self.r.error("IK_TARGET_SPACE", p + ".targetSpace", "must be MODEL in 1.0")
            if "weight" in ch and not (_is_num(ch["weight"]) and 0 <= ch["weight"] <= 1):
                self.r.error("IK_WEIGHT", p + ".weight", "must be in [0,1]")
            bones = []
            for k in ("root", "mid", "end"):
                if self.index(ch[k], len(self.nodes), f"{p}.{k}", "nodes"):
                    if ch[k] not in self.joint_nodes:
                        self.r.error("IK_NOT_JOINT", f"{p}.{k}", f"node {ch[k]} is not a skin joint")
                    bones.append(ch[k])
            if len(bones) != 3:
                continue
            r, m, e = bones
            if len({r, m, e}) != 3:
                self.r.error("IK_DUPLICATE_BONE", p, "root, mid and end must be distinct")
                continue
            if self.parent[m] != r or self.parent[e] != m:
                self.r.error("IK_NOT_DIRECT_CHAIN", p, "chain must be direct parent-child links root->mid->end")
                continue
            for b in bones:
                s = self.nodes[b].get("scale", [1, 1, 1]) if isinstance(self.nodes[b], dict) else [1, 1, 1]
                if _is_vec(s, 3) and (min(s) <= 0 or max(s) - min(s) > 1e-6):
                    self.r.error("IK_SCALE", f"nodes[{b}]", "IK chain bones must have uniform positive scale")
            A, B, C = (mat_translation(self.world[x]) for x in bones)
            if vlen(vsub(B, A)) <= 1e-6 or vlen(vsub(C, B)) <= 1e-6:
                self.r.error("IK_SEGMENT_LENGTH", p, "segment rest length must be > 1e-6 m")
            pole = ch["pole"]
            if not _is_vec(pole, 3) or abs(vlen(pole) - 1.0) > 1e-3:
                self.r.error("IK_POLE", p + ".pole", "pole must be a unit vec3 in model space")
            else:
                re_ = vsub(C, A)
                if vlen(re_) > 1e-9 and vlen(vcross(pole, tuple(x / vlen(re_) for x in re_))) < 1e-6:
                    self.r.error("IK_POLE_COLLINEAR", p + ".pole", "pole is collinear with root-to-end vector")
            for b in bones:
                if b in used:
                    self.r.error("IK_OVERLAP", p, f"bone node {b} already used by chain {used[b]!r}")
                used[b] = ch["id"]

    def check_component_roles(self):
        seen = set()
        for ri, cr in enumerate(self.array("componentRoles")):
            p = f"componentRoles[{ri}]"
            if not self.keys(cr, p, ("role", "node", "profile")):
                continue
            if not _nonblank(cr["role"]) or not _nonblank(cr["profile"]):
                self.r.error("COMPONENT_ROLE", p, "role and profile must be nonempty strings")
            self.index(cr["node"], len(self.nodes), p + ".node", "nodes")
            key = (cr["profile"], cr["role"])
            if key in seen:
                self.r.error("COMPONENT_ROLE_DUPLICATE", p, f"role {cr['role']!r} repeated in profile {cr['profile']!r}")
            seen.add(key)
            if isinstance(cr["profile"], str) and not cr["profile"].startswith("custom."):
                self.r.warning("COMPONENT_PROFILE_UNREGISTERED", p,
                               f"profile {cr['profile']!r} is not a published registry profile; non-normative")

    def check_colliders(self):
        for ci, c in enumerate(self.array("colliders")):
            p = f"colliders[{ci}]"
            if not isinstance(c, dict):
                self.r.error("TYPE_OBJECT", p, "must be an object")
                continue
            shape = c.get("shape")
            fields = {"BOX": ("size",), "SPHERE": ("radius",), "CAPSULE": ("radius", "height"), "MESH": ("mesh",)}
            if shape not in fields:
                self.r.error("COLLIDER_SHAPE", p + ".shape", f"invalid shape {shape!r}")
                continue
            if not self.keys(c, p, ("node", "shape") + fields[shape], ("name", "trigger", "physicalMaterial")):
                continue
            self.index(c["node"], len(self.nodes), p + ".node", "nodes")
            if "trigger" in c and not isinstance(c["trigger"], bool):
                self.r.error("TYPE_BOOL", p + ".trigger", "must be a boolean")
            if shape == "BOX" and not (_is_vec(c["size"], 3) and all(x > 0 for x in c["size"])):
                self.r.error("COLLIDER_SIZE", p + ".size", "BOX size components must be > 0")
            if shape in ("SPHERE", "CAPSULE") and not (_is_num(c["radius"]) and c["radius"] > 0):
                self.r.error("COLLIDER_RADIUS", p + ".radius", "radius must be > 0")
            if shape == "CAPSULE" and _is_num(c["radius"]) and not (
                    _is_num(c["height"]) and c["height"] >= 2 * c["radius"]):
                self.r.error("COLLIDER_HEIGHT", p + ".height", "capsule height must be >= 2*radius")
            if shape == "MESH":
                self.index(c["mesh"], len(self.meshes), p + ".mesh", "meshes")

    def check_model_components(self):
        attachments = {a["name"] for a in self.array("attachments")
                       if isinstance(a, dict) and isinstance(a.get("name"), str)}
        seen = set()
        for i, item in enumerate(self.array("modelComponents")):
            p = f"modelComponents[{i}]"
            if not self.keys(item, p, ("id", "role", "node"), ("socket",)):
                continue
            ident = item["id"]
            if not isinstance(ident, str) or not EVENT_NAME_RE.fullmatch(ident):
                self.r.error("COMPONENT_ID", p + ".id", "must match [a-z][a-z0-9_.]*")
            elif ident in seen:
                self.r.error("COMPONENT_ID_DUPLICATE", p, f"duplicate id {ident!r}")
            else:
                seen.add(ident)
            if not _nonblank(item["role"]):
                self.r.error("COMPONENT_ROLE", p + ".role", "must be a nonempty semantic role")
            self.index(item["node"], len(self.nodes), p + ".node", "nodes")
            if "socket" in item and (not isinstance(item["socket"], str) or item["socket"] not in attachments):
                self.r.error("COMPONENT_SOCKET", p + ".socket", "must name an existing attachment")

    def check_physical_metadata(self):
        materials = set()
        for i, item in enumerate(self.array("physicalMaterials")):
            p = f"physicalMaterials[{i}]"
            if not self.keys(item, p, ("id", "friction", "restitution")):
                continue
            ident = item["id"]
            if not _nonblank(ident):
                self.r.error("PHYSICAL_MATERIAL_ID", p + ".id", "must be a nonempty string")
            elif ident in materials:
                self.r.error("PHYSICAL_MATERIAL_DUPLICATE", p, f"duplicate id {ident!r}")
            else:
                materials.add(ident)
            for key in ("friction", "restitution"):
                if not _is_num(item[key]) or not 0 <= item[key] <= 1:
                    self.r.error("PHYSICAL_MATERIAL_RANGE", p + "." + key, "must be finite in [0,1]")
        colliders = self.array("colliders")
        for i, collider in enumerate(colliders):
            if isinstance(collider, dict) and "physicalMaterial" in collider:
                ref = collider["physicalMaterial"]
                if not isinstance(ref, str) or ref not in materials:
                    self.r.error("PHYSICAL_MATERIAL_REFERENCE", f"colliders[{i}].physicalMaterial",
                                 "must reference a physicalMaterials id")
        seen = set()
        for i, item in enumerate(self.array("hitboxes")):
            p = f"hitboxes[{i}]"
            if not self.keys(item, p, ("id", "collider"), ("boneNode", "role")):
                continue
            ident = item["id"]
            if not _nonblank(ident):
                self.r.error("HITBOX_ID", p + ".id", "must be a nonempty string")
            elif ident in seen:
                self.r.error("HITBOX_ID_DUPLICATE", p, f"duplicate id {ident!r}")
            else:
                seen.add(ident)
            valid_collider = self.index(item["collider"], len(colliders), p + ".collider", "colliders")
            if "role" in item and not _nonblank(item["role"]):
                self.r.error("HITBOX_ROLE", p + ".role", "must be a nonempty string")
            if "boneNode" in item and self.index(item["boneNode"], len(self.nodes), p + ".boneNode", "nodes"):
                collider = colliders[item["collider"]] if valid_collider else None
                node = collider.get("node") if isinstance(collider, dict) else None
                if _is_int(node) and node < len(self.nodes):
                    if item["boneNode"] != node and not self.is_ancestor(item["boneNode"], node):
                        self.r.error("HITBOX_ANCESTRY", p + ".boneNode",
                                     "must be the collider's node or an ancestor")

    def check_lods(self):
        owner = {}
        for gi, g in enumerate(self.array("lodGroups")):
            p = f"lodGroups[{gi}]"
            if not self.keys(g, p, ("levels",), ("name",)):
                continue
            levels = g["levels"]
            if not isinstance(levels, list) or len(levels) < 2:
                self.r.error("LOD_LEVELS", p + ".levels", "at least two levels are required")
                continue
            nodes = []
            prev = None
            for li, lv in enumerate(levels):
                lp = f"{p}.levels[{li}]"
                if not self.keys(lv, lp, ("node", "minDistance")):
                    continue
                if self.index(lv["node"], len(self.nodes), lp + ".node", "nodes"):
                    nodes.append(lv["node"])
                d = lv["minDistance"]
                if not (_is_num(d) and d >= 0):
                    self.r.error("LOD_DISTANCE", lp + ".minDistance", "must be finite >= 0")
                    continue
                if li == 0 and d != 0:
                    self.r.error("LOD_FIRST_DISTANCE", lp + ".minDistance", "level 0 minDistance must be 0")
                if prev is not None and not d > prev:
                    self.r.error("LOD_ORDER", lp + ".minDistance", "minDistance must be strictly increasing")
                prev = d
            if len(set(nodes)) != len(nodes):
                self.r.error("LOD_DUPLICATE_NODE", p, "level nodes must be distinct")
            for a in nodes:
                for b in nodes:
                    if a != b and self.is_ancestor(a, b):
                        self.r.error("LOD_NESTED", p, f"level node {a} is an ancestor of level node {b}")
            for a in nodes:
                stack = [a]
                while stack:
                    x = stack.pop()
                    if x in owner and owner[x] != gi:
                        self.r.error("LOD_OVERLAP", p, f"node {x} also belongs to lodGroups[{owner[x]}]")
                        break
                    owner[x] = gi
                    node = self.nodes[x]
                    stack.extend(c for c in (node.get("children", []) if isinstance(node, dict) else [])
                                 if _is_int(c) and c < len(self.nodes) and self.parent[c] == x)

    def check_attachments(self):
        names = set()
        for ai, a in enumerate(self.array("attachments")):
            p = f"attachments[{ai}]"
            if not self.keys(a, p, ("name", "node")):
                continue
            if not _nonblank(a["name"]):
                self.r.error("ATTACHMENT_NAME", p + ".name", "must be a nonempty string")
            elif a["name"] in names:
                self.r.error("ATTACHMENT_DUPLICATE", p + ".name", f"duplicate attachment {a['name']!r}")
            names.add(a["name"])
            self.index(a["node"], len(self.nodes), p + ".node", "nodes")


# ------------------------------------------------------------------------------------------------
def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class AnimValidator(_Base):
    def run(self):
        d = self.doc
        for k in K.ANIM_REQUIRED_TOP:
            if k not in d:
                self.r.error("MISSING_FIELD", "$", f"required top-level member '{k}' missing")
        allowed = set(K.ANIM_REQUIRED_TOP) | set(K.ANIM_OPTIONAL_TOP)
        for k in d:
            if k not in allowed:
                self.r.error("UNKNOWN_FIELD", "$", f"top-level member '{k}' is not permitted")
        self.check_asset()
        self.check_extensions_top()
        self.check_buffers()
        self.check_library()
        self.check_clips()

    def check_text(self, obj, key, path, maxlen):
        v = obj.get(key)
        if not _nonblank(v):
            self.r.error("TEXT_BLANK", f"{path}.{key}", "must contain non-whitespace text")
        elif len(v) > maxlen:
            self.r.error("TEXT_LENGTH", f"{path}.{key}", f"longer than {maxlen} code points")

    def check_tags(self, tags, path):
        if not isinstance(tags, list) or not all(isinstance(t, str) and SEGMENT_RE.match(t) for t in tags):
            self.r.error("TAGS", path, "tags must be lowercase segments [a-z][a-z0-9_]*")
            return
        if len(set(tags)) != len(tags):
            self.r.error("TAGS_DUPLICATE", path, "tags must be unique")
        if tags != sorted(tags):
            self.r.warning("TAGS_UNSORTED", path, "tags should be sorted lexically")

    def check_library(self):
        lib = self.doc.get("library")
        self.lib = lib if isinstance(lib, dict) else {}
        if not self.keys(lib, "library", ("id", "title", "description", "language", "targetProfile", "binding"),
                         ("rigId", "tags", "author", "license", "revision", "namespace", "motionScale",
                          "sourceHeight", "rootMotionSource")):
            return
        if not isinstance(lib["id"], str) or not LIBRARY_ID_RE.match(lib["id"]):
            self.r.error("LIBRARY_ID", "library.id", f"invalid library id {lib['id']!r}")
        elif "@" not in lib["id"]:
            self.r.warning("LIBRARY_ID_SEGMENTS", "library.id", "library ids should have at least two segments")
        self.check_text(lib, "title", "library", 256)
        self.check_text(lib, "description", "library", 2048)
        if not isinstance(lib["language"], str) or not BCP47_RE.match(lib["language"]):
            self.r.error("LANGUAGE", "library.language", f"invalid BCP-47 tag {lib['language']!r}")
        tp = lib["targetProfile"]
        if not isinstance(tp, str) or not (tp in K.BUILTIN_SKELETON_PROFILES or tp == K.MODEL_ANY_PROFILE
                                           or PROFILE_ID_RE.match(tp)):
            self.r.error("PROFILE_ID", "library.targetProfile", f"invalid profile id {tp!r}")
        if tp == K.MODEL_ANY_PROFILE and lib["binding"] != "SEMANTIC":
            self.r.error("LIBRARY_MODEL_ANY_BINDING", "library.binding", "model.any.v1 requires SEMANTIC binding")
        if lib["binding"] not in K.BINDINGS:
            self.r.error("LIBRARY_BINDING", "library.binding", f"invalid binding {lib['binding']!r}")
        elif lib["binding"] == "EXACT":
            if not isinstance(lib.get("rigId"), str) or not RIG_ID_RE.match(lib["rigId"]):
                self.r.error("RIG_ID_FORMAT", "library.rigId", "EXACT binding requires a 64-hex rigId")
        elif "rigId" in lib:
            self.r.error("LIBRARY_RIG_ID", "library.rigId", "SEMANTIC binding must not include rigId")
        if "tags" in lib:
            self.check_tags(lib["tags"], "library.tags")
        for k in ("author", "license"):
            if k in lib and not _is_str(lib[k]):
                self.r.error("TYPE_STRING", f"library.{k}", "must be a string")
        if "revision" in lib and not (isinstance(lib["revision"], str) and SEMVER_RE.match(lib["revision"])):
            self.r.error("LIBRARY_REVISION", "library.revision", "must be a SemVer 2.0.0 string")
        if "namespace" in lib and not (isinstance(lib["namespace"], str) and NAMESPACE_RE.match(lib["namespace"])):
            self.r.error("LIBRARY_NAMESPACE", "library.namespace", "must be a reverse-DNS name")
        if "motionScale" in lib:
            if lib["motionScale"] != "SOURCE_HEIGHT":
                self.r.error("LIBRARY_MOTION_SCALE", "library.motionScale", "only SOURCE_HEIGHT is defined")
            if not (_is_num(lib.get("sourceHeight")) and lib["sourceHeight"] > 0):
                self.r.error("LIBRARY_SOURCE_HEIGHT", "library.sourceHeight", "must be a finite number > 0")
        elif "sourceHeight" in lib:
            self.r.error("LIBRARY_SOURCE_HEIGHT", "library.sourceHeight", "requires motionScale SOURCE_HEIGHT")
        if "rootMotionSource" in lib and lib["rootMotionSource"] != "hips":
            self.r.error("LIBRARY_ROOT_SOURCE", "library.rootMotionSource", "only \"hips\" is defined")

    def semantic_roles(self):
        tp = self.lib.get("targetProfile")
        if tp == "humanoid.vrm1":
            return set(K.VRM1_ROLES)
        if tp == K.MODEL_ANY_PROFILE:
            return set()
        return None  # unknown registry contents

    def check_clips(self):
        clips = self.doc.get("clips")
        if not isinstance(clips, list):
            self.r.error("TYPE_ARRAY", "clips", "must be an array")
            return
        binding = self.lib.get("binding")
        roles = self.semantic_roles()
        ids = set()
        for ci, clip in enumerate(clips):
            p = f"clips[{ci}]"
            if not self.keys(clip, p, ("id", "title", "description", "language", "duration", "loop", "rootMotion",
                                       "channels", "samplers"), ("tags", "events")):
                continue
            if not isinstance(clip["id"], str) or not SEGMENT_RE.match(clip["id"]):
                self.r.error("CLIP_ID", p + ".id", f"invalid clip id {clip['id']!r}")
            elif clip["id"] in ids:
                self.r.error("CLIP_ID_DUPLICATE", p + ".id", f"duplicate clip id {clip['id']!r}")
            ids.add(clip["id"])
            self.check_text(clip, "title", p, 256)
            self.check_text(clip, "description", p, 2048)
            if not isinstance(clip["language"], str) or not BCP47_RE.match(clip["language"]):
                self.r.error("LANGUAGE", p + ".language", f"invalid BCP-47 tag {clip['language']!r}")
            if "tags" in clip:
                self.check_tags(clip["tags"], p + ".tags")
            dur = clip["duration"]
            if not (_is_num(dur) and dur >= 0):
                self.r.error("CLIP_DURATION", p + ".duration", "must be finite >= 0")
                dur = None
            if clip["loop"] not in K.LOOP_MODES:
                self.r.error("CLIP_LOOP", p + ".loop", f"invalid loop {clip['loop']!r}")
            if clip["rootMotion"] not in K.ROOT_MOTION_MODES:
                self.r.error("CLIP_ROOT_MOTION", p + ".rootMotion", f"invalid rootMotion {clip['rootMotion']!r}")
            sampler_kind = self.check_samplers(clip["samplers"], p, dur)
            self.check_channels(clip, p, binding, roles, sampler_kind)
            self.check_events(clip.get("events", []), p, dur)

    def check_samplers(self, samplers, p, dur):
        kinds = {}
        if not isinstance(samplers, list):
            self.r.error("TYPE_ARRAY", p + ".samplers", "must be an array")
            return kinds
        for si, s in enumerate(samplers):
            sp = f"{p}.samplers[{si}]"
            if not self.keys(s, sp, ("input", "output", "interpolation")):
                continue
            interp = s["interpolation"]
            if interp not in K.INTERPOLATIONS:
                self.r.error("SAMPLER_INTERPOLATION", sp, f"invalid interpolation {interp!r}")
                continue
            if not self.use_acc(s["input"], sp + ".input", ("F32",), ("SCALAR",), False, 1):
                continue
            times = [float(t[0]) for t in self.acc(s["input"])]
            if any(t < 0 for t in times):
                self.r.error("SAMPLER_TIME_NEGATIVE", sp + ".input", "times must be >= 0")
            if any(b <= a for a, b in zip(times, times[1:])):
                self.r.error("SAMPLER_TIME_ORDER", sp + ".input", "times must be strictly increasing")
            if dur is not None and times and times[-1] > _f32(dur):
                self.r.error("SAMPLER_TIME_RANGE", sp + ".input", f"last key {times[-1]} > duration {dur}")
            if not self.use_acc(s["output"], sp + ".output", ("F32",), ("SCALAR", "VEC2", "VEC3", "VEC4"), False, 1):
                continue
            out = self.doc["accessors"][s["output"]]
            want = len(times) * (3 if interp == "CUBICSPLINE" else 1)
            if out["count"] != want:
                self.r.error("SAMPLER_OUTPUT_COUNT", sp + ".output", f"count {out['count']} != expected {want}")
                continue
            kinds[si] = (out["type"], interp, s["output"])
        return kinds

    def check_quaternion_sampler(self, info, sp):
        _typ, interp, acc_index = info
        vals = self.acc(acc_index)
        rng = range(1, len(vals), 3) if interp == "CUBICSPLINE" else range(len(vals))
        for k in rng:
            if abs(vlen(vals[k][:3]) ** 2 + vals[k][3] ** 2 - 1.0) > 2e-3:
                self.r.error("SAMPLER_QUAT_NORM", sp, f"rotation key {k} is not a unit quaternion")
                return

    def check_value_bounds(self, info, lo, hi, cp):
        _typ, interp, acc_index = info
        vals = self.acc(acc_index)
        rng = range(1, len(vals), 3) if interp == "CUBICSPLINE" else range(len(vals))
        for k in rng:
            for x in vals[k]:
                if (lo is not None and x < lo - 1e-6) or (hi is not None and x > hi + 1e-6):
                    self.r.warning("CHANNEL_VALUE_RANGE", cp, f"key {k} value {x} outside [{lo}, {hi}]; "
                                                              "clamped by the evaluator")
                    return

    def check_channels(self, clip, p, binding, roles, sampler_kind):
        chans = clip["channels"]
        if not isinstance(chans, list):
            self.r.error("TYPE_ARRAY", p + ".channels", "must be an array")
            return
        seen = set()
        root_tracks = 0
        bone_tracks = 0
        nsamp = len(clip["samplers"]) if isinstance(clip["samplers"], list) else 0
        for ci, ch in enumerate(chans):
            cp = f"{p}.channels[{ci}]"
            if not self.keys(ch, cp, ("target", "path", "sampler"), ("optional",)):
                continue
            if "optional" in ch and not isinstance(ch["optional"], bool):
                self.r.error("TYPE_BOOL", cp + ".optional", "must be a boolean")
            t = ch["target"]
            if not isinstance(t, dict):
                self.r.error("TYPE_OBJECT", cp + ".target", "must be an object")
                continue
            kind = t.get("kind")
            path = ch["path"]
            model_any = self.lib.get("targetProfile") == K.MODEL_ANY_PROFILE
            want = None
            bounds = None
            if kind == "bone":
                if model_any:
                    self.r.error("CHANNEL_MODEL_ANY_BONE", cp + ".target", "model.any.v1 libraries forbid bone targets")
                key_field = "role" if binding == "SEMANTIC" else "nodeName"
                if not self.keys(t, cp + ".target", ("kind", key_field)):
                    continue
                ident = t[key_field]
                if not _nonblank(ident):
                    self.r.error("CHANNEL_TARGET", cp + ".target", f"{key_field} must be a nonempty string")
                if path not in ("translation", "rotation", "scale"):
                    self.r.error("CHANNEL_PATH", cp + ".path", f"path {path!r} invalid for bone targets")
                bone_tracks += 1
                if binding == "SEMANTIC":
                    if roles is not None and ident not in roles and ident != "root":
                        self.r.error("CHANNEL_ROLE", cp + ".target.role", f"role {ident!r} not in {self.lib.get('targetProfile')}")
                    if ident == "root" and roles is not None:
                        self.r.error("CHANNEL_ROLE", cp + ".target.role",
                                     f"profile {self.lib.get('targetProfile')} does not define role 'root'")
                    if path == "scale":
                        self.r.error("CHANNEL_SEMANTIC_SCALE", cp, "scale tracks are forbidden for SEMANTIC binding")
                    if path == "translation" and ident not in ("hips", "root"):
                        self.r.error("CHANNEL_SEMANTIC_TRANSLATION", cp,
                                     "SEMANTIC translation is only allowed for hips/root")
                    if path == "translation" and (ident == "root" or (
                            ident == "hips" and self.lib.get("rootMotionSource") == "hips")):
                        root_tracks += 1
                else:
                    if path == "translation":
                        root_tracks += 1
            elif kind in ("morph", "expression"):
                if not self.keys(t, cp + ".target", ("kind", "name")):
                    continue
                if not _nonblank(t["name"]):
                    self.r.error("CHANNEL_TARGET", cp + ".target.name", "must be a nonempty string")
                if path != "weight":
                    self.r.error("CHANNEL_PATH", cp + ".path", f"{kind} targets only support path 'weight'")
                ident = t["name"]
            elif kind == "pbrParameter":
                if not self.keys(t, cp + ".target", ("kind", "materialId", "parameter")):
                    continue
                if not isinstance(t["materialId"], str) or not ANIMATION_ID_RE.match(t["materialId"]):
                    self.r.error("CHANNEL_MATERIAL_ID", cp + ".target.materialId", "invalid materialId")
                spec = K.PBR_PARAMETERS.get(t["parameter"])
                if spec is None:
                    self.r.error("CHANNEL_PBR_PARAMETER", cp + ".target.parameter",
                                 f"{t['parameter']!r} is not an animatable PBR parameter")
                else:
                    want, bounds = spec[0], spec[1:]
                if path != "value":
                    self.r.error("CHANNEL_PATH", cp + ".path", "pbrParameter targets only support path 'value'")
                ident = f"{t['materialId']}:{t['parameter']}"
            elif kind == "shaderParameter":
                if not self.keys(t, cp + ".target", ("kind", "materialId", "shaderId", "shaderVersion", "parameter")):
                    continue
                if not isinstance(t["materialId"], str) or not ANIMATION_ID_RE.match(t["materialId"]):
                    self.r.error("CHANNEL_MATERIAL_ID", cp + ".target.materialId", "invalid materialId")
                sid, ver = t["shaderId"], t["shaderVersion"]
                if not isinstance(sid, str) or not SHADER_ID_RE.match(sid):
                    self.r.error("SHADER_ID", cp + ".target.shaderId", f"invalid shader id {sid!r}")
                if not is_exact_semver(ver):
                    self.r.error("SHADER_VERSION", cp + ".target.shaderVersion", f"invalid exact SemVer {ver!r}")
                if not isinstance(t["parameter"], str) or not PARAM_NAME_RE.match(t["parameter"]):
                    self.r.error("SHADER_PARAM_NAME", cp + ".target.parameter", "invalid parameter name")
                official = K.OFFICIAL_SHADERS.get((sid, ver)) if isinstance(sid, str) and isinstance(ver, str) else None
                if official is not None:
                    prm = {q["name"]: q for q in official}.get(t["parameter"])
                    if prm is None or not prm.get("animatable"):
                        self.r.error("CHANNEL_SHADER_PARAMETER", cp + ".target.parameter",
                                     f"{t['parameter']!r} is not an animatable parameter of {sid}@{ver}")
                    else:
                        want = K.SHADER_TYPE_TO_ACCESSOR[prm["type"]]
                        if prm["type"] == "F32":
                            bounds = (prm.get("minimum"), prm.get("maximum"))
                if path != "value":
                    self.r.error("CHANNEL_PATH", cp + ".path", "shaderParameter targets only support path 'value'")
                ident = f"{t['materialId']}:{sid}@{ver}:{t['parameter']}"
            else:
                self.r.error("CHANNEL_KIND", cp + ".target.kind", f"invalid target kind {kind!r}")
                continue
            key = (kind, ident if isinstance(ident, str) else repr(ident), path)
            if key in seen:
                self.r.error("CHANNEL_DUPLICATE", cp, f"target {key} repeated in clip")
            seen.add(key)
            if self.index(ch["sampler"], nsamp, cp + ".sampler", "clip samplers"):
                info = sampler_kind.get(ch["sampler"])
                out_type = info[0] if info else None
                if want is None:
                    want = {"translation": "VEC3", "scale": "VEC3", "rotation": "VEC4", "weight": "SCALAR"}.get(path)
                if out_type is not None and want is not None and out_type != want:
                    self.r.error("CHANNEL_SAMPLER_TYPE", cp, f"path {path} needs {want} output, sampler has {out_type}")
                elif info is not None and kind == "bone" and path == "rotation":
                    self.check_quaternion_sampler(info, cp)
                elif info is not None and bounds is not None and out_type == want:
                    self.check_value_bounds(info, bounds[0], bounds[1], cp)
        if clip.get("rootMotion") == "EXTRACT" and self.lib.get("targetProfile") == K.MODEL_ANY_PROFILE:
            self.r.error("CLIP_MODEL_ANY_EXTRACT", p + ".rootMotion", "model.any.v1 forbids rootMotion EXTRACT")
        elif clip.get("rootMotion") == "EXTRACT":
            if binding == "SEMANTIC" and root_tracks == 0:
                self.r.error("CLIP_ROOT_TRACK", p, "EXTRACT requires a root translation track (role 'root' or "
                                                   "hips with library.rootMotionSource='hips')")
            elif binding == "EXACT" and bone_tracks == 0:
                self.r.error("CLIP_ROOT_TRACK", p, "EXTRACT requires a root transform channel")

    def check_events(self, events, p, dur):
        if not isinstance(events, list):
            self.r.error("TYPE_ARRAY", p + ".events", "must be an array")
            return
        prev = None
        for ei, ev in enumerate(events):
            ep = f"{p}.events[{ei}]"
            if not self.keys(ev, ep, ("time", "name"), ("payload",)):
                continue
            if not _is_num(ev["time"]) or ev["time"] < 0 or (dur is not None and ev["time"] > dur):
                self.r.error("EVENT_TIME", ep + ".time", "must be finite within [0,duration]")
                continue
            if not isinstance(ev["name"], str) or not EVENT_NAME_RE.match(ev["name"]):
                self.r.error("EVENT_NAME", ep + ".name", f"invalid event name {ev['name']!r}")
                continue
            payload = b""
            if "payload" in ev:
                if not isinstance(ev["payload"], dict):
                    self.r.error("EVENT_PAYLOAD", ep + ".payload", "payload must be a JSON object")
                    continue
                payload = _canonical_json(ev["payload"])
                if len(payload) > 4096:
                    self.r.error("EVENT_PAYLOAD_SIZE", ep + ".payload", "payload exceeds 4096 bytes")
            key = (ev["time"], ev["name"], payload)
            if prev is not None and key < prev:
                self.r.error("EVENT_ORDER", ep, "events must be sorted by time, name, payload")
            prev = key


# ------------------------------------------------------------------------------------------------
def material_binding_issues(model_doc, anim_doc):
    """Check shader/PBR channel targets of a library against a model (§15, §18.1).

    Returns a list of ``(severity, code, path, message)``; non-optional unresolved targets are errors.
    """
    out = []
    mats = {}
    for m in model_doc.get("materials", []) or []:
        if isinstance(m, dict) and isinstance(m.get("animationId"), str):
            mats[m["animationId"]] = m
    registry = shader_registry(model_doc)
    for ci, clip in enumerate(anim_doc.get("clips", []) or []):
        for chi, ch in enumerate(clip.get("channels", []) or []):
            t = ch.get("target", {})
            kind = t.get("kind")
            if kind not in ("pbrParameter", "shaderParameter"):
                continue
            p = f"clips[{ci}].channels[{chi}]"
            sev = "warning" if ch.get("optional") else "error"
            m = mats.get(t.get("materialId"))
            if m is None:
                out.append((sev, "BIND_MATERIAL_MISSING", p, f"no material with animationId {t.get('materialId')!r}"))
                continue
            if kind == "pbrParameter":
                if t.get("parameter") == "normalScale" and "normalTexture" not in m:
                    out.append((sev, "BIND_NORMAL_SCALE", p, "normalScale requires the material to have normalTexture"))
                continue
            key = (t.get("shaderId"), t.get("shaderVersion"))
            if material_shader(m) != key:
                out.append((sev, "BIND_SHADER_MISMATCH", p,
                            f"material uses {'@'.join(material_shader(m))}, channel needs {key[0]}@{key[1]}"))
                continue
            prm = registry.get(key, {}).get(t.get("parameter"))
            if prm is None or not prm.get("animatable") or prm.get("type") not in K.SHADER_NUMERIC_DIMS:
                out.append((sev, "BIND_SHADER_PARAMETER", p,
                            f"{t.get('parameter')!r} is not an animatable numeric parameter of {key[0]}@{key[1]}"))
    return out


# ------------------------------------------------------------------------------------------------
def _validate(data, magic, cls, kind, limits):
    report = Report(kind)
    try:
        doc, bin_bytes = read_container(data, magic, limits)
    except ResourceLimitError as exc:
        report.resource_limit = True
        report.error(exc.code, "$", exc.message)
        return report
    except AdmFormatError as exc:
        report.error(exc.code, "$", exc.message)
        return report
    v = cls(report)
    v.doc, v.bin = doc, bin_bytes
    report.doc, report.bin = doc, bin_bytes
    try:
        v.run()
    except ResourceLimitError as exc:
        report.resource_limit = True
        report.error(exc.code, "$", exc.message)
    except AdmFormatError as exc:
        report.error(exc.code, "$", exc.message)
    except Exception as exc:  # defensive: malformed structures must never crash a reader
        report.error("VALIDATOR_INTERNAL", "$", f"validation aborted on malformed data: {exc!r}")
    return report


def validate_adm(data, limits=DEFAULT_LIMITS):
    return _validate(data, K.ADM_MAGIC, AdmValidator, "adm", limits)


def validate_anim(data, limits=DEFAULT_LIMITS):
    return _validate(data, K.ANIM_MAGIC, AnimValidator, "adm_anim", limits)


def validate_bytes(data, limits=DEFAULT_LIMITS):
    if bytes(data[:4]) == K.ANIM_MAGIC:
        return validate_anim(data, limits)
    return validate_adm(data, limits)


def validate_file(path, limits=DEFAULT_LIMITS):
    with open(path, "rb") as fh:
        data = fh.read()
    if str(path).lower().endswith(".adm_anim"):
        return validate_anim(data, limits)
    return validate_adm(data, limits)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    status = 0
    for path in argv:
        rep = validate_file(path)
        print(f"{path}: {'VALID' if rep.ok else 'INVALID'} ({len(rep.errors)} errors, {len(rep.warnings)} warnings)")
        if rep.issues:
            print(rep.format())
        if not rep.ok:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
