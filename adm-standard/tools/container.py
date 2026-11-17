#!/usr/bin/env python3
"""ADM 1.0 container writer/validator (not full semantic compliance)."""
import hashlib, json, math, re, struct, sys, pathlib
HEADER=struct.Struct('<4sHHIIQQQQIIQ')
ENTRY=struct.Struct('<Q4sII I QQQ32s')
assert HEADER.size == 64 and ENTRY.size == 80
LIMIT_MANIFEST=16*1024*1024
LIMIT_CHUNK=256*1024*1024
LIMIT_FILE=8*1024*1024*1024
HASH_BLOCK=1024*1024
MAX_CHUNKS=65535
class AdmError(ValueError): pass

def align(n):return (n+15)&~15

def serial(o):return json.dumps(o,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')

def create(path, magic, manifest, chunks):
    if magic not in (b'ADM0',b'AMA0'):raise AdmError('magic')
    mb=serial(manifest); n=len(chunks); d=align(64+len(mb)); cursor=align(d+80*n)
    directory=[];payload=[]
    for cid,typ,raw,required in sorted(chunks,key=lambda x:x[0]):
        assert len(typ)==4 and 0 < cid < 2**32 and raw and len(raw)<=LIMIT_CHUNK
        directory.append(ENTRY.pack(cid,typ,1 if required else 0,0,0,cursor,len(raw),len(raw),hashlib.sha256(raw).digest()))
        payload.append((cursor,raw));cursor=align(cursor+len(raw))
    out=bytearray(cursor)
    out[:64]=HEADER.pack(magic,1,0,64,0,len(out),64,len(mb),d,n,80,0)
    out[64:64+len(mb)]=mb
    out[d:d+80*n]=b''.join(directory)
    for offset,data in payload:out[offset:offset+len(data)]=data
    pathlib.Path(path).write_bytes(out)

def no_duplicate(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise AdmError('ADM_ERR_DUPLICATE_JSON_KEY')
        d[k]=v
    return d


def _strict_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise AdmError("ADM_ERR_NONFINITE")
    return value


def _read_at(stream, offset, length, file_size):
    if type(offset) is not int or type(length) is not int or offset < 0 or length < 0 or offset + length > file_size:
        raise AdmError("ADM_ERR_BOUNDS")
    stream.seek(offset)
    data = stream.read(length)
    if len(data) != length:
        raise AdmError("ADM_ERR_BOUNDS")
    return data


def _zero_region(stream, start, end, file_size):
    if end < start or end - start > 15:
        raise AdmError("ADM_ERR_BOUNDS")
    if any(_read_at(stream, start, end - start, file_size)):
        raise AdmError("ADM_ERR_PADDING")


def _hash_region(stream, offset, length, file_size):
    digest = hashlib.sha256()
    cursor, remaining = offset, length
    while remaining:
        amount = min(remaining, HASH_BLOCK)
        digest.update(_read_at(stream, cursor, amount, file_size))
        cursor += amount
        remaining -= amount
    return digest.digest()


def _validate_json_tree(value, depth=0, max_depth=64):
    if depth > max_depth:
        raise AdmError("ADM_ERR_RESOURCE_LIMIT")
    if isinstance(value, str):
        try:
            value.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise AdmError("ADM_ERR_JSON") from exc
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_json_tree(key, depth + 1, max_depth)
            _validate_json_tree(child, depth + 1, max_depth)
    elif isinstance(value, list):
        for child in value:
            _validate_json_tree(child, depth + 1, max_depth)


def verify_interactive(manifest):
    """Independently check the interactive fixture's manifest-level binding contract."""
    name = "ADM_interactive_surfaces_v1"
    joint_display = "ADM_joint_display_v1"
    used = manifest.get("extensionsUsed", [])
    required = manifest.get("extensionsRequired", [])
    if not isinstance(used, list) or not isinstance(required, list):
        raise AdmError("ADM_ERR_EXTENSIONS")
    supported = {"ADM_material_layers_v1", "ADM_vertex_control_v1", "ADM_external_images_v1",
                 "ADM_physical_surfaces_v1", joint_display, name}
    for extension in required:
        if not isinstance(extension, str) or extension not in used or extension not in supported:
            raise AdmError("ADM_ERR_UNSUPPORTED_EXTENSION")
    if joint_display in used:
        nodes = manifest.get("nodes", [])
        if not isinstance(nodes, list):
            raise AdmError("ADM_ERR_JOINT_DISPLAY")

        def number(value):
            return type(value) is int or (type(value) is float and math.isfinite(value))

        def valid_joint_display(data):
            if not isinstance(data, dict) or set(data) != {"version", "displayFrame", "tail"}:
                return False
            frame, tail = data.get("displayFrame"), data.get("tail")
            if data.get("version") != "1.0.0" or not isinstance(frame, list) or len(frame) != 16:
                return False
            if not all(number(value) for value in frame) or not isinstance(tail, list) or len(tail) != 3:
                return False
            if not all(number(value) for value in tail) or not any(value != 0 for value in tail):
                return False
            if frame[3] != 0 or frame[7] != 0 or frame[11] != 0 or frame[15] != 1:
                return False
            determinant = (frame[0] * (frame[5] * frame[10] - frame[9] * frame[6])
                           - frame[4] * (frame[1] * frame[10] - frame[9] * frame[2])
                           + frame[8] * (frame[1] * frame[6] - frame[5] * frame[2]))
            return math.isfinite(determinant) and determinant != 0

        joints = set()
        if joint_display in required:
            skins = manifest.get("skins", [])
            if not isinstance(skins, list):
                raise AdmError("ADM_ERR_JOINT_DISPLAY")
            for skin in skins:
                if not isinstance(skin, dict) or not isinstance(skin.get("joints"), list):
                    raise AdmError("ADM_ERR_JOINT_DISPLAY")
                for index in skin["joints"]:
                    if type(index) is not int or not 0 <= index < len(nodes):
                        raise AdmError("ADM_ERR_JOINT_DISPLAY")
                    joints.add(index)
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise AdmError("ADM_ERR_JOINT_DISPLAY")
            node_extensions = node.get("extensions", {})
            if not isinstance(node_extensions, dict):
                raise AdmError("ADM_ERR_JOINT_DISPLAY")
            if joint_display in node_extensions and not valid_joint_display(node_extensions[joint_display]):
                raise AdmError("ADM_ERR_JOINT_DISPLAY")
        for index in joints:
            node_extensions = nodes[index].get("extensions", {})
            if joint_display not in node_extensions:
                raise AdmError("ADM_ERR_JOINT_DISPLAY")
    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict):
        raise AdmError("ADM_ERR_EXTENSIONS")
    extension = extensions.get(name)
    if extension is None and name in used:
        raise AdmError("ADM_ERR_INTERACTIVE_EXTENSION")

    def item(array, index, error):
        if not isinstance(array, list) or type(index) is not int or not 0 <= index < len(array):
            raise AdmError(error)
        return array[index]

    def number(value):
        return type(value) is int or (type(value) is float and math.isfinite(value))

    nodes, meshes = manifest.get("nodes", []), manifest.get("meshes", [])
    materials, accessors = manifest.get("materials", []), manifest.get("accessors", [])
    occupied, identities = set(), set()
    if extension is not None:
        if name not in used or not isinstance(extension, dict) or set(extension) - {"version", "surfaces", "extras",
                                                                                      "extensions"}:
            raise AdmError("ADM_ERR_INTERACTIVE_EXTENSION")
        if extension.get("version") != "1.0.0":
            raise AdmError("ADM_ERR_INTERACTIVE_VERSION")
        surfaces = extension.get("surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            raise AdmError("ADM_ERR_INTERACTIVE_SURFACES")
        for surface in surfaces:
            if not isinstance(surface, dict) or set(surface) - {"surfaceId", "bindings", "aspectRatio", "extras",
                                                                  "extensions"}:
                raise AdmError("ADM_ERR_INTERACTIVE_SURFACE")
            ident, bindings = surface.get("surfaceId"), surface.get("bindings")
            if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", ident) or ident in identities:
                raise AdmError("ADM_ERR_INTERACTIVE_ID")
            identities.add(ident)
            if "aspectRatio" in surface:
                ratio = surface["aspectRatio"]
                if (not number(ratio) or not 0 < ratio <= 1000
                        or struct.unpack("<f", struct.pack("<f", ratio))[0] <= 0):
                    raise AdmError("ADM_ERR_INTERACTIVE_ASPECT")
            if not isinstance(bindings, list) or not bindings:
                raise AdmError("ADM_ERR_INTERACTIVE_BINDING")
            for binding in bindings:
                if not isinstance(binding, dict) or set(binding) - {"node", "primitive", "texCoord", "extras",
                                                                    "extensions"}:
                    raise AdmError("ADM_ERR_INTERACTIVE_BINDING")
                node_index, primitive_index, texcoord = (binding.get(k) for k in ("node", "primitive", "texCoord"))
                node = item(nodes, node_index, "ADM_ERR_INTERACTIVE_NODE")
                if not isinstance(node, dict):
                    raise AdmError("ADM_ERR_INTERACTIVE_NODE")
                mesh = item(meshes, node.get("mesh"), "ADM_ERR_INTERACTIVE_MESH")
                if not isinstance(mesh, dict):
                    raise AdmError("ADM_ERR_INTERACTIVE_MESH")
                primitive = item(mesh.get("primitives"), primitive_index, "ADM_ERR_INTERACTIVE_PRIMITIVE")
                if not isinstance(primitive, dict):
                    raise AdmError("ADM_ERR_INTERACTIVE_PRIMITIVE")
                if (node_index, primitive_index) in occupied:
                    raise AdmError("ADM_ERR_INTERACTIVE_BINDING_DUPLICATE")
                occupied.add((node_index, primitive_index))
                material = item(materials, primitive.get("material"), "ADM_ERR_INTERACTIVE_MATERIAL")
                shader = material.get("shader") if isinstance(material, dict) else None
                if not isinstance(shader, dict) or (shader.get("id"), shader.get("version")) != (
                        "adm.surface.interactive", "1.0.0"):
                    raise AdmError("ADM_ERR_INTERACTIVE_MATERIAL")
                animation_id = material.get("animationId")
                if not isinstance(animation_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", animation_id):
                    raise AdmError("ADM_ERR_INTERACTIVE_ANIMATION_ID")
                parameters = material.get("shaderParameters", {})
                if not isinstance(parameters, dict):
                    raise AdmError("ADM_ERR_INTERACTIVE_PARAMETER")
                for key, value in parameters.items():
                    if key in ("brightness", "emissive_strength"):
                        if not number(value) or not 0 <= value <= 16:
                            raise AdmError("ADM_ERR_INTERACTIVE_PARAMETER")
                    elif key in ("enabled", "unlit"):
                        if type(value) is not bool:
                            raise AdmError("ADM_ERR_INTERACTIVE_PARAMETER")
                    else:
                        raise AdmError("ADM_ERR_INTERACTIVE_PARAMETER")
                if type(texcoord) is not int or texcoord not in (0, 1):
                    raise AdmError("ADM_ERR_INTERACTIVE_UV")
                attrs = primitive.get("attributes")
                if not isinstance(attrs, dict):
                    raise AdmError("ADM_ERR_INTERACTIVE_UV")
                uv = item(accessors, attrs.get(f"TEXCOORD_{texcoord}"), "ADM_ERR_INTERACTIVE_UV")
                if not isinstance(uv, dict) or uv.get("componentType") != "F32" or uv.get("type") != "VEC2":
                    raise AdmError("ADM_ERR_INTERACTIVE_UV")
    if not isinstance(nodes, list):
        return
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict) or type(node.get("mesh")) is not int:
            continue
        mesh_index = node["mesh"]
        if not isinstance(meshes, list) or not 0 <= mesh_index < len(meshes) or not isinstance(meshes[mesh_index], dict):
            continue
        primitives = meshes[mesh_index].get("primitives")
        if not isinstance(primitives, list):
            continue
        for primitive_index, primitive in enumerate(primitives):
            if not isinstance(primitive, dict) or type(primitive.get("material")) is not int:
                continue
            material_index = primitive["material"]
            if not isinstance(materials, list) or not 0 <= material_index < len(materials):
                continue
            material = materials[material_index]
            shader = material.get("shader") if isinstance(material, dict) else None
            if isinstance(shader, dict) and (shader.get("id"), shader.get("version")) == (
                    "adm.surface.interactive", "1.0.0") and (node_index, primitive_index) not in occupied:
                raise AdmError("ADM_ERR_INTERACTIVE_BINDING_MISSING")


def verify(path, verify_payload=True, *, max_file_bytes=LIMIT_FILE):
    """Validate container structure without loading payloads into memory."""
    file_path = pathlib.Path(path)
    file_size = file_path.stat().st_size
    if type(max_file_bytes) is not int or max_file_bytes < 0:
        raise ValueError("max_file_bytes must be a nonnegative integer")
    if file_size > max_file_bytes:
        raise AdmError("ADM_ERR_RESOURCE_LIMIT")

    with file_path.open("rb") as stream:
        if file_size < HEADER.size:
            raise AdmError("ADM_ERR_TRUNCATED_HEADER")
        header = _read_at(stream, 0, HEADER.size, file_size)
        magic, major, minor, header_size, flags, declared_size, manifest_offset, manifest_size, \
            directory_offset, chunk_count, entry_size, reserved = HEADER.unpack(header)
        if magic not in (b"ADM0", b"AMA0"):
            raise AdmError("ADM_ERR_HEADER")
        if (major, minor) != (1, 0):
            raise AdmError(
                f"ADM_ERR_UNSUPPORTED_VERSION: container version {major}.{minor} is unsupported; "
                "this reader supports 1.0 (ADM 1.0 Development / Experimental). "
                "Older development versions are not migrated."
            )
        if header_size != 64:
            raise AdmError(
                f"ADM_ERR_UNSUPPORTED_LAYOUT: header size {header_size} is unsupported; "
                "ADM 1.0 Development / Experimental requires 64 bytes. "
                "Older development layouts are not migrated."
            )
        if (flags, reserved, manifest_offset, entry_size) != (0, 0, 64, ENTRY.size):
            raise AdmError("ADM_ERR_HEADER")
        if (declared_size != file_size or not 2 <= manifest_size <= LIMIT_MANIFEST
                or chunk_count > MAX_CHUNKS or directory_offset != align(64 + manifest_size)
                or directory_offset + chunk_count * ENTRY.size > file_size):
            raise AdmError("ADM_ERR_BOUNDS")
        _zero_region(stream, manifest_offset + manifest_size, directory_offset, file_size)
        manifest_bytes = _read_at(stream, manifest_offset, manifest_size, file_size)
        try:
            manifest = json.loads(
                manifest_bytes.decode("utf-8", "strict"),
                object_pairs_hook=no_duplicate,
                parse_constant=lambda _value: (_ for _ in ()).throw(AdmError("ADM_ERR_NONFINITE")),
                parse_float=_strict_float,
            )
        except AdmError:
            raise
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise AdmError("ADM_ERR_JSON") from exc
        if not isinstance(manifest, dict):
            raise AdmError("ADM_ERR_MANIFEST")
        _validate_json_tree(manifest)

        if magic == b"ADM0":
            required = ("asset", "nodes", "scenes", "scene", "meshes", "accessors", "bufferViews")
        else:
            required = ("asset", "library", "clips", "accessors", "bufferViews")
        for key in required:
            if key not in manifest:
                raise AdmError("ADM_ERR_MANIFEST_REQUIRED:" + key)
        if magic == b"AMA0":
            if not isinstance(manifest["clips"], list):
                raise AdmError("ADM_ERR_MANIFEST")
            for clip in manifest["clips"]:
                if not isinstance(clip, dict) or not str(clip.get("description", "")).strip():
                    raise AdmError("ADM_ERR_MISSING_DESCRIPTION")

        directory_size = chunk_count * ENTRY.size
        directory = _read_at(stream, directory_offset, directory_size, file_size)
        data_start = align(directory_offset + directory_size)
        _zero_region(stream, directory_offset + directory_size, data_start, file_size)
        chunks = {}
        last_id = 0
        payload_end = data_start
        for index in range(chunk_count):
            cid, chunk_type, entry_flags, codec, entry_reserved, offset, stored, raw, digest = \
                ENTRY.unpack_from(directory, index * ENTRY.size)
            if type(cid) is not int or not 0 < cid <= 0xffffffff or cid <= last_id:
                raise AdmError("ADM_ERR_CHUNK_ID")
            if (entry_flags & ~1 or entry_reserved or not stored or not raw or raw > LIMIT_CHUNK
                    or any(byte < 32 or byte > 126 for byte in chunk_type)):
                raise AdmError("ADM_ERR_CHUNK_ENTRY")
            if (offset % 16 or offset < align(payload_end) or offset + stored > file_size):
                raise AdmError("ADM_ERR_CHUNK_BOUNDS")
            _zero_region(stream, payload_end, offset, file_size)
            if chunk_type not in (b"GEOM", b"ANIM", b"IMAG", b"DATA") and entry_flags & 1:
                raise AdmError("ADM_ERR_UNSUPPORTED_CHUNK")
            if codec not in (0, 1) and entry_flags & 1:
                raise AdmError("ADM_ERR_UNSUPPORTED_CODEC")
            if codec == 0 and stored != raw:
                raise AdmError("ADM_ERR_CHUNK_SIZE")
            if verify_payload:
                if codec != 0:
                    raise AdmError("ADM_ERR_UNSUPPORTED_CODEC")
                if _hash_region(stream, offset, stored, file_size) != digest:
                    raise AdmError("ADM_ERR_HASH_MISMATCH")
            chunks[cid] = (chunk_type, raw)
            last_id = cid
            payload_end = offset + stored
        if file_size != align(payload_end):
            raise AdmError("ADM_ERR_TRAILING_BYTES")
        _zero_region(stream, payload_end, file_size, file_size)

        buffer_views = manifest.get("bufferViews", [])
        if not isinstance(buffer_views, list):
            raise AdmError("ADM_ERR_BUFFER_VIEW")
        for view in buffer_views:
            if not isinstance(view, dict) or not all(k in view for k in ("chunkId", "byteOffset", "byteLength")):
                raise AdmError("ADM_ERR_BUFFER_VIEW")
            chunk_id, start, length = (view[k] for k in ("chunkId", "byteOffset", "byteLength"))
            if (type(chunk_id) is not int or type(start) is not int or type(length) is not int or
                    chunk_id not in chunks or start < 0 or length < 0 or start + length > chunks[chunk_id][1]):
                raise AdmError("ADM_ERR_BUFFER_VIEW")

        materials = manifest.get("materials", [])
        if not isinstance(materials, list):
            raise AdmError("ADM_ERR_MATERIAL")
        for material in materials:
            if not isinstance(material, dict):
                raise AdmError("ADM_ERR_MATERIAL")
            shader = material.get("shader")
            if shader is not None and not isinstance(shader, dict):
                raise AdmError("ADM_ERR_MATERIAL_SHADER")
            if shader is not None and (shader.get("id"), shader.get("version")) != (
                    "adm.pbr.metallic_roughness", "1.0.0"):
                fallback = ("baseColorFactor", "metallicFactor", "roughnessFactor", "emissiveFactor", "alphaMode")
                if any(key not in material for key in fallback):
                    raise AdmError("ADM_ERR_MISSING_PBR_FALLBACK")
        if magic == b"ADM0":
            verify_interactive(manifest)

        accessors = manifest.get("accessors", [])
        if not isinstance(accessors, list):
            raise AdmError("ADM_ERR_ACCESSOR")
        for accessor in accessors:
            try:
                view = manifest["bufferViews"][accessor["bufferView"]]
                unit = {"F32": 4, "U32": 4, "U16": 2, "U8": 1}[accessor["componentType"]]
                elements = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[accessor["type"]]
                offset, count = accessor.get("byteOffset", 0), accessor["count"]
                if (type(offset) is not int or type(count) is not int or offset < 0 or count < 0
                        or offset % unit or offset + count * unit * elements > view["byteLength"]):
                    raise ValueError("bounds")
            except (KeyError, IndexError, ValueError, TypeError):
                raise AdmError("ADM_ERR_ACCESSOR") from None

        dependencies = manifest.get("chunkDependencies", [])
        if not isinstance(dependencies, list):
            raise AdmError("ADM_ERR_DEPENDENCY")
        graph = {}
        for dependency in dependencies:
            if not isinstance(dependency, dict) or not all(k in dependency for k in ("chunkId", "requires")):
                raise AdmError("ADM_ERR_DEPENDENCY")
            node, required_chunks = dependency["chunkId"], dependency["requires"]
            if (type(node) is not int or node not in chunks or node in graph
                    or not isinstance(required_chunks, list)
                    or any(type(chunk_id) is not int or chunk_id not in chunks for chunk_id in required_chunks)
                    or len(set(required_chunks)) != len(required_chunks) or node in required_chunks):
                raise AdmError("ADM_ERR_DEPENDENCY")
            graph[node] = required_chunks
        colors = {}
        for root in graph:
            stack = [(root, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    colors[node] = 2
                    continue
                state = colors.get(node, 0)
                if state == 1:
                    raise AdmError("ADM_ERR_DEPENDENCY_CYCLE")
                if state == 2:
                    continue
                colors[node] = 1
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(graph.get(node, [])))

    return {"file": str(path), "kind": magic.decode(), "chunks": chunk_count,
            "manifestBytes": manifest_size, "bufferViews": len(buffer_views),
            "verifiedPayloads": verify_payload}

if __name__=='__main__':
    status=0
    for arg in sys.argv[1:]:
        try:print('OK',verify(arg))
        except Exception as e: print('FAIL',arg,repr(e));status=1
    sys.exit(status)

class RangeReader:
    """Minimal demonstrator: header/manifest/directory via seek; demand-load RAW chunks."""
    def __init__(self, path, *, max_file_bytes=LIMIT_FILE):
        if type(max_file_bytes) is not int or max_file_bytes < 0:
            raise ValueError("max_file_bytes must be a nonnegative integer")
        self.path = pathlib.Path(path)
        self.file_size = self.path.stat().st_size
        if self.file_size > max_file_bytes:
            raise AdmError("ADM_ERR_RESOURCE_LIMIT")
        self.bytes_read = 0

        with self.path.open("rb") as stream:
            header_bytes = self._read(stream, 0, HEADER.size)
            if len(header_bytes) != HEADER.size:
                raise AdmError("ADM_ERR_TRUNCATED_HEADER")
            magic, major, minor, header_size, flags, declared_size, manifest_offset, manifest_size, \
                directory_offset, chunk_count, entry_size, reserved = HEADER.unpack(header_bytes)
            if magic not in (b"ADM0", b"AMA0"):
                raise AdmError("ADM_ERR_HEADER")
            if (major, minor) != (1, 0):
                raise AdmError(
                    f"ADM_ERR_UNSUPPORTED_VERSION: container version {major}.{minor} is unsupported; "
                    "this reader supports 1.0 (ADM 1.0 Development / Experimental). "
                    "Older development versions are not migrated."
                )
            if header_size != 64:
                raise AdmError(
                    f"ADM_ERR_UNSUPPORTED_LAYOUT: header size {header_size} is unsupported; "
                    "ADM 1.0 Development / Experimental requires 64 bytes. "
                    "Older development layouts are not migrated."
                )
            if ((flags, reserved, manifest_offset, entry_size) != (0, 0, 64, ENTRY.size)
                    or declared_size != self.file_size
                    or not 2 <= manifest_size <= LIMIT_MANIFEST
                    or chunk_count > MAX_CHUNKS
                    or directory_offset != align(64 + manifest_size)
                    or directory_offset + chunk_count * ENTRY.size > self.file_size):
                raise AdmError("ADM_ERR_HEADER")

            manifest_bytes = self._read(stream, manifest_offset, manifest_size)
            try:
                self.manifest = json.loads(
                    manifest_bytes.decode("utf-8", "strict"),
                    object_pairs_hook=no_duplicate,
                    parse_constant=lambda _value: (_ for _ in ()).throw(AdmError("ADM_ERR_NONFINITE")),
                    parse_float=_strict_float,
                )
            except AdmError:
                raise
            except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
                raise AdmError("ADM_ERR_JSON") from exc
            if not isinstance(self.manifest, dict):
                raise AdmError("ADM_ERR_MANIFEST")
            _validate_json_tree(self.manifest)

            directory_size = chunk_count * ENTRY.size
            directory = self._read(stream, directory_offset, directory_size)
            payload_start = align(directory_offset + directory_size)
            self.chunks = {}
            last_id = 0
            payload_end = payload_start
            for index in range(chunk_count):
                cid, chunk_type, entry_flags, codec, entry_reserved, offset, stored, raw, digest = \
                    ENTRY.unpack_from(directory, index * ENTRY.size)
                if (not 0 < cid <= 0xffffffff or cid <= last_id
                        or entry_flags & ~1 or entry_reserved
                        or not stored or stored > LIMIT_CHUNK or not raw or raw > LIMIT_CHUNK
                        or any(byte < 32 or byte > 126 for byte in chunk_type)
                        or offset % 16 or offset < align(payload_end)
                        or offset + stored > self.file_size):
                    raise AdmError("ADM_ERR_CHUNK_ENTRY")
                if codec == 0 and stored != raw:
                    raise AdmError("ADM_ERR_CHUNK_SIZE")
                if codec not in (0, 1) and entry_flags & 1:
                    raise AdmError("ADM_ERR_UNSUPPORTED_CODEC")
                if chunk_type not in (b"GEOM", b"ANIM", b"IMAG", b"DATA") and entry_flags & 1:
                    raise AdmError("ADM_ERR_UNSUPPORTED_CHUNK")
                self.chunks[cid] = (chunk_type, codec, offset, stored, raw, digest)
                last_id = cid
                payload_end = offset + stored
            if self.file_size != align(payload_end):
                raise AdmError("ADM_ERR_TRAILING_BYTES")

    def _read(self, stream, offset, length):
        if (type(offset) is not int or type(length) is not int or offset < 0 or length < 0
                or offset + length > self.file_size):
            raise AdmError("ADM_ERR_BOUNDS")
        stream.seek(offset)
        data = stream.read(length)
        self.bytes_read += len(data)
        if len(data) != length:
            raise AdmError("ADM_ERR_BOUNDS")
        return data

    def load(self, cid):
        if type(cid) is not int or cid not in self.chunks:
            raise AdmError("ADM_ERR_CHUNK_ID")
        _typ, codec, offset, stored, _raw, digest = self.chunks[cid]
        if codec != 0:
            raise AdmError("ADM_ERR_UNSUPPORTED_CODEC")
        with self.path.open("rb") as stream:
            data = self._read(stream, offset, stored)
        if hashlib.sha256(data).digest() != digest:
            raise AdmError("ADM_ERR_HASH_MISMATCH")
        return data
