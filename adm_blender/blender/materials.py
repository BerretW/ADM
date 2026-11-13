"""ADM PBR material <-> Blender Principled BSDF node tree (spec §8)."""

import os
import re

import bpy
import numpy as np

from ..core import constants as K
from ..core.png import encode_png
from ..core.validate import ANIMATION_ID_RE, param_value_error, shader_registry

UV_NAMES = ("UVMap", "UVMap_1")
OCCLUSION_NODE = "ADM Occlusion"
ALPHA_CLIP_NODE = "ADM Alpha Clip"


# ================================================================================================
# helpers
# ================================================================================================
def _from(socket):
    if socket is None or not socket.is_linked:
        return None
    for link in socket.links:
        if link.is_muted or not link.is_valid:
            continue
        s = link.from_socket
        while s.node.type == "REROUTE":
            nxt = s.node.inputs[0]
            if not nxt.is_linked:
                return None
            s = nxt.links[0].from_socket
        return s
    return None


def output_surface_shader(mat):
    if not mat.node_tree:
        return None
    outs = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
    out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
    if out is None:
        return None
    s = _from(out.inputs.get("Surface"))
    return s.node if s else None


def principled_of(mat):
    node = output_surface_shader(mat)
    if node is not None and node.type == "BSDF_PRINCIPLED":
        return node
    if mat.node_tree:
        return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    return None


def _color_inputs(node):
    return [s for s in node.inputs if s.name in ("A", "B", "Color1", "Color2") and s.type == "RGBA" and s.enabled]


def trace(socket):
    """Walk back from an input socket to an Image Texture node.

    Returns None (unlinked), or a dict with ``node`` (TEX_IMAGE or None if unsupported), ``channel``
    (None for RGB, 'R'/'G'/'B'/'A'), ``factor`` (float or rgb list) and ``clip`` (alpha cutoff or None).
    """
    s = _from(socket)
    if s is None:
        return None
    info = {"node": None, "channel": None, "factor": 1.0, "clip": None, "unsupported": None}
    guard = 0
    while s is not None and guard < 16:
        guard += 1
        n = s.node
        if n.type == "TEX_IMAGE":
            info["node"] = n
            if s.name == "Alpha" and info["channel"] is None:
                info["channel"] = "A"
            return info
        if n.type in ("SEPARATE_COLOR", "SEPRGB"):
            info["channel"] = {"Red": "R", "Green": "G", "Blue": "B", "R": "R", "G": "G", "B": "B"}.get(s.name)
            s = _from(n.inputs[0])
            continue
        if n.type == "MATH" and n.operation in ("MULTIPLY", "GREATER_THAN", "ROUND"):
            a, b = n.inputs[0], n.inputs[1]
            if n.operation == "GREATER_THAN":
                info["clip"] = float(b.default_value)
                s = _from(a)
                continue
            if n.operation == "ROUND":
                info["clip"] = 0.5
                s = _from(a)
                continue
            if a.is_linked and not b.is_linked:
                info["factor"] = info["factor"] * float(b.default_value)
                s = _from(a)
                continue
            if b.is_linked and not a.is_linked:
                info["factor"] = info["factor"] * float(a.default_value)
                s = _from(b)
                continue
        if (n.type == "MIX" and getattr(n, "data_type", "") == "RGBA" and n.blend_type == "MULTIPLY") or \
                (n.type == "MIX_RGB" and n.blend_type == "MULTIPLY"):
            cols = _color_inputs(n)
            fac = n.inputs[0]
            if len(cols) == 2 and not fac.is_linked and abs(fac.default_value - 1.0) < 1e-6:
                linked = [c for c in cols if c.is_linked]
                const = [c for c in cols if not c.is_linked]
                if len(linked) == 1 and len(const) == 1:
                    info["factor"] = list(const[0].default_value[:3])
                    s = _from(linked[0])
                    continue
        info["unsupported"] = n
        return info
    return info


def _uv_index(tex_node, uv_names):
    vec = tex_node.inputs.get("Vector")
    s = _from(vec)
    if s is not None and s.node.type == "UVMAP" and s.node.uv_map:
        name = s.node.uv_map
        if name in uv_names:
            return min(uv_names.index(name), 1)
    return 0


def _is_png(b):
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def _is_jpeg(b):
    return b[:3] == b"\xff\xd8\xff"


def _linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def image_pixels(image):
    """Float RGBA pixels, rows top-to-bottom, shape (h, w, 4)."""
    w, h = image.size
    if w == 0 or h == 0:
        raise ValueError(f"image '{image.name}' has no pixel data")
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1]


def _resize_nearest(a, h, w):
    sh, sw = a.shape[:2]
    if (sh, sw) == (h, w):
        return a
    ys = (np.arange(h) * sh // h).clip(0, sh - 1)
    xs = (np.arange(w) * sw // w).clip(0, sw - 1)
    return a[ys][:, xs]


# ================================================================================================
# export
# ================================================================================================
class MaterialExporter:
    def __init__(self, builder, warn, image_format="AUTO", jpeg_quality=90):
        self.b = builder
        self.warn = warn
        self.image_format = image_format
        self.jpeg_quality = jpeg_quality
        self.materials = []
        self.images = []
        self.samplers = []
        self.textures = []
        self._mat_cache = {}
        self._img_cache = {}
        self._tex_cache = {}
        self._sampler_cache = {}
        self.normal_mapped = set()
        self.shader_defs = {}          # (id, version) -> ADMShaderDef (scene)
        self.used_definitions = {}     # (id, version) -> embedded definition dict
        self.extensions_used = set()
        self.extensions_required = set()
        self._animation_ids = set()

    # images ---------------------------------------------------------------------------------
    def _encode_image_bytes(self, image, color_role):
        if image.source not in ("FILE", "GENERATED"):
            self.warn(f"image '{image.name}': source {image.source} not supported, exporting first frame/tile")
        data = None
        if self.image_format in ("AUTO", "JPEG") and image.packed_file is not None:
            data = bytes(image.packed_file.data)
        elif self.image_format == "AUTO" and image.source == "FILE" and image.filepath:
            path = bpy.path.abspath(image.filepath, library=image.library)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    data = fh.read()
        if data is not None and (_is_png(data) or (_is_jpeg(data) and data.rstrip(b"\x00").endswith(b"\xff\xd9"))):
            if self.image_format == "JPEG" and _is_png(data):
                data = None
            else:
                return data, "image/png" if _is_png(data) else "image/jpeg"
        px = image_pixels(image)
        if image.is_float and color_role and image.colorspace_settings.name not in ("sRGB",):
            px = px.copy()
            px[..., :3] = _linear_to_srgb(px[..., :3])
        return self._encode_pixels(px)

    def _encode_pixels(self, px):
        h, w = px.shape[:2]
        rgba = (np.clip(px, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        return encode_png(w, h, rgba.tobytes(), 4), "image/png"

    def _add_image(self, key, name, blob, mime):
        if key in self._img_cache:
            return self._img_cache[key]
        view = self.b.add_view(blob, align=4, chunk_type="IMAG")
        self.images.append({"bufferView": view, "mimeType": mime, "name": name})
        self._img_cache[key] = len(self.images) - 1
        return self._img_cache[key]

    def _sampler(self, tex_node):
        mag = "NEAREST" if tex_node.interpolation == "Closest" else "LINEAR"
        wrap = {"REPEAT": "REPEAT", "EXTEND": "CLAMP_TO_EDGE", "CLIP": "CLAMP_TO_EDGE",
                "MIRROR": "MIRRORED_REPEAT"}.get(tex_node.extension, "REPEAT")
        s = {}
        if mag != "LINEAR":
            s["magFilter"] = mag
            s["minFilter"] = mag
        if wrap != "REPEAT":
            s["wrapS"] = wrap
            s["wrapT"] = wrap
        if not s:
            return None
        key = tuple(sorted(s.items()))
        if key not in self._sampler_cache:
            self.samplers.append(s)
            self._sampler_cache[key] = len(self.samplers) - 1
        return self._sampler_cache[key]

    def _texture(self, image_index, sampler):
        key = (image_index, sampler)
        if key not in self._tex_cache:
            t = {"source": image_index}
            if sampler is not None:
                t["sampler"] = sampler
            self.textures.append(t)
            self._tex_cache[key] = len(self.textures) - 1
        return self._tex_cache[key]

    def texture_from_image(self, image, color_role):
        key = ("img", image.name, image.library.filepath if image.library else "")
        if key not in self._img_cache:
            blob, mime = self._encode_image_bytes(image, color_role)
            self._add_image(key, image.name, blob, mime)
        return self._texture(self._img_cache[key], None)

    def texture_from_node(self, tex_node, color_role):
        image = tex_node.image
        if image is None:
            return None
        key = ("img", image.name, image.library.filepath if image.library else "")
        if key not in self._img_cache:
            blob, mime = self._encode_image_bytes(image, color_role)
            self._add_image(key, image.name, blob, mime)
        return self._texture(self._img_cache[key], self._sampler(tex_node))

    def texture_composite_mr(self, rough, metal, name):
        """Pack roughness->G and metallic->B into one generated PNG."""
        key = ("mr", id(rough["node"]) if rough else 0, rough["channel"] if rough else None,
               id(metal["node"]) if metal else 0, metal["channel"] if metal else None)
        if key not in self._img_cache:
            srcs = [t for t in (rough, metal) if t]
            arrays = [image_pixels(t["node"].image) for t in srcs]
            h = max(a.shape[0] for a in arrays)
            w = max(a.shape[1] for a in arrays)
            out = np.ones((h, w, 4), dtype=np.float32)
            chan = {"R": 0, "G": 1, "B": 2, "A": 3, None: 0}
            if rough:
                out[..., 1] = _resize_nearest(arrays[0], h, w)[..., chan[rough["channel"]]]
            if metal:
                out[..., 2] = _resize_nearest(arrays[-1], h, w)[..., chan[metal["channel"]]]
            blob, mime = self._encode_pixels(out)
            self._add_image(key, name + "_metallicRoughness", blob, mime)
        node = (rough or metal)["node"]
        return self._texture(self._img_cache[key], self._sampler(node))

    # materials ------------------------------------------------------------------------------
    def index(self, mat, uv_names):
        if mat is None:
            return None
        if mat.name in self._mat_cache:
            return self._mat_cache[mat.name]
        self.materials.append(self.export_material(mat, list(uv_names)))
        self._mat_cache[mat.name] = len(self.materials) - 1
        return self._mat_cache[mat.name]

    def _ref(self, tex_index, tex_node, uv_names, extra=None):
        ref = {"index": tex_index}
        tc = _uv_index(tex_node, uv_names)
        if tc:
            ref["texCoord"] = tc
        if extra:
            ref.update(extra)
        return ref

    def export_material(self, mat, uv_names):
        out = self._export_pbr(mat, uv_names)
        self._export_shader(mat, out)
        if mat.adm.shader != "CORE":
            defaults = {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 1.0,
                        "roughnessFactor": 1.0, "emissiveFactor": [0.0, 0.0, 0.0], "alphaMode": "OPAQUE"}
            for key, value in defaults.items():
                out.setdefault(key, value)
        return out

    # shaders --------------------------------------------------------------------------------
    def _texref(self, image, tex_coord):
        if image is None:
            return None
        ref = {"index": self.texture_from_image(image, False)}
        if tex_coord:
            ref["texCoord"] = 1
        return ref

    def definition_dict(self, sdef):
        params = []
        for p in sdef.params:
            d = param_def_dict(p, lambda img, uv: self._texref(img, uv))
            params.append(d)
        out = {"id": sdef.shader_id.strip(), "version": sdef.version.strip(), "parameters": params}
        if sdef.description.strip():
            out["description"] = sdef.description.strip()
        if sdef.author.strip():
            out["author"] = sdef.author.strip()
        return out

    def _export_shader(self, mat, out):
        a = mat.adm
        aid = a.animation_id.strip()
        if a.shader != "CORE" and not aid:
            aid = unique_animation_id(mat.name, self._animation_ids)
            self.warn(f"material '{mat.name}': shader materials need an animationId, using '{aid}'")
        if aid:
            if not ANIMATION_ID_RE.match(aid):
                raise ShaderExportError(f"material '{mat.name}': animationId '{aid}' must match [a-z][a-z0-9_]*")
            if aid in self._animation_ids:
                raise ShaderExportError(f"material '{mat.name}': animationId '{aid}' is used by another material")
            self._animation_ids.add(aid)
            out["animationId"] = aid
        if a.shader == "CORE":
            return
        if a.shader == "LAYERED":
            out["shader"] = {"id": K.SHADER_LAYERED[0], "version": K.SHADER_LAYERED[1]}
            if a.layer_factor != 0.0:
                out["shaderParameters"] = {"layer_factor": _c01(a.layer_factor)}
            ext = {"base": layer_dict(a.layer_base), "overlay": layer_dict(a.layer_overlay)}
            if a.layer_mask is not None:
                ext["maskTexture"] = self._texref(a.layer_mask, a.layer_mask_uv)
            out.setdefault("extensions", {})[K.LAYERS_EXT] = ext
            self.extensions_used.add(K.LAYERS_EXT)
            if a.layers_required:
                self.extensions_required.add(K.LAYERS_EXT)
            return
        key = a.shader_key()
        sdef = self.shader_defs.get(key)
        if sdef is None:
            raise ShaderExportError(f"material '{mat.name}': custom shader '{a.custom_shader}' has no definition "
                                    f"in the scene's ADM shader list")
        if key[0].startswith("adm."):
            raise ShaderExportError(f"material '{mat.name}': adm.* shader ids are reserved for the official registry")
        if key not in self.used_definitions:
            self.used_definitions[key] = self.definition_dict(sdef)
        out["shader"] = {"id": key[0], "version": key[1]}
        defs = {p["name"]: p for p in self.used_definitions[key]["parameters"]}
        values = {}
        for v in a.params:
            if not v.use:
                continue
            prm = defs.get(v.name)
            if prm is None:
                self.warn(f"material '{mat.name}': parameter '{v.name}' is not part of {key[0]}@{key[1]}, skipped")
                continue
            val = param_value_from_prop(prm["type"], v, lambda img, uv: self._texref(img, uv))
            err = param_value_error(prm, val, None)
            if err:
                raise ShaderExportError(f"material '{mat.name}': parameter '{v.name}': {err}")
            values[v.name] = val
        if values:
            out["shaderParameters"] = values

    def _export_pbr(self, mat, uv_names):
        out = {"name": mat.name}
        bsdf = principled_of(mat)
        double_sided = not mat.use_backface_culling
        if bsdf is None:
            self.warn(f"material '{mat.name}': no Principled BSDF, exporting viewport color only")
            out["baseColorFactor"] = [_c01(x) for x in mat.diffuse_color]
            out["metallicFactor"] = _c01(mat.metallic)
            out["roughnessFactor"] = _c01(mat.roughness)
            if double_sided:
                out["doubleSided"] = True
            return out

        # base color + alpha
        base = trace(bsdf.inputs["Base Color"])
        factor = list(bsdf.inputs["Base Color"].default_value[:3])
        if base is not None:
            if base["node"] is not None and base["node"].image is not None:
                ti = self.texture_from_node(base["node"], True)
                out["baseColorTexture"] = self._ref(ti, base["node"], uv_names)
                factor = base["factor"] if isinstance(base["factor"], list) else [base["factor"]] * 3
            else:
                self.warn(f"material '{mat.name}': Base Color node setup not representable, using default value")
        alpha_in = bsdf.inputs["Alpha"]
        alpha = float(alpha_in.default_value)
        alpha_tr = trace(alpha_in)
        clip = None
        if alpha_tr is not None:
            alpha = float(alpha_tr["factor"]) if not isinstance(alpha_tr["factor"], list) else 1.0
            clip = alpha_tr["clip"]
            if alpha_tr["node"] is None:
                self.warn(f"material '{mat.name}': Alpha node setup not representable")
            elif base is None or base["node"] is None or alpha_tr["node"].image != base["node"].image:
                self.warn(f"material '{mat.name}': alpha must come from the base color texture alpha channel")
        bcf = [_c01(x) for x in factor] + [_c01(alpha)]
        if bcf != [1.0, 1.0, 1.0, 1.0]:
            out["baseColorFactor"] = bcf

        # metallic / roughness
        mt = trace(bsdf.inputs["Metallic"])
        rt = trace(bsdf.inputs["Roughness"])
        metallic = float(bsdf.inputs["Metallic"].default_value) if mt is None else float(_scalar(mt["factor"]))
        rough = float(bsdf.inputs["Roughness"].default_value) if rt is None else float(_scalar(rt["factor"]))
        mt = mt if mt and mt["node"] is not None and mt["node"].image else None
        rt = rt if rt and rt["node"] is not None and rt["node"].image else None
        if mt or rt:
            same = (mt and rt and mt["node"].image == rt["node"].image and mt["channel"] == "B" and rt["channel"] == "G")
            only_ok = (not mt and rt["channel"] == "G") or (not rt and mt["channel"] == "B")
            if same or only_ok:
                node = (rt or mt)["node"]
                ti = self.texture_from_node(node, False)
            else:
                ti = self.texture_composite_mr(rt, mt, mat.name)
                node = (rt or mt)["node"]
            out["metallicRoughnessTexture"] = self._ref(ti, node, uv_names)
        if metallic != 1.0:
            out["metallicFactor"] = _c01(metallic)
        if rough != 1.0:
            out["roughnessFactor"] = _c01(rough)

        # normal map
        ns = _from(bsdf.inputs["Normal"])
        if ns is not None:
            nm = ns.node
            if nm.type == "NORMAL_MAP" and nm.space == "TANGENT":
                ct = trace(nm.inputs["Color"])
                if ct and ct["node"] is not None and ct["node"].image:
                    ti = self.texture_from_node(ct["node"], False)
                    strength = float(nm.inputs["Strength"].default_value)
                    extra = {"scale": max(0.0, strength)} if abs(strength - 1.0) > 1e-6 else None
                    ref = self._ref(ti, ct["node"], uv_names, extra)
                    if nm.uv_map and nm.uv_map in uv_names and uv_names.index(nm.uv_map) == 1:
                        ref["texCoord"] = 1
                    out["normalTexture"] = ref
                    self.normal_mapped.add(mat.name)
            else:
                self.warn(f"material '{mat.name}': Normal input must come from a tangent-space Normal Map node")

        # occlusion
        occ_node = mat.node_tree.nodes.get(OCCLUSION_NODE)
        occ = None
        if occ_node is not None and occ_node.type == "TEX_IMAGE" and occ_node.image:
            occ = occ_node
        else:
            for n in mat.node_tree.nodes:
                if n.type == "GROUP" and n.node_tree and n.node_tree.name in ("glTF Material Output", "glTF Settings"):
                    o = trace(n.inputs.get("Occlusion"))
                    if o and o["node"] is not None and o["node"].image:
                        occ = o["node"]
        if occ is not None:
            ti = self.texture_from_node(occ, False)
            st = mat.adm.occlusion_strength
            out["occlusionTexture"] = self._ref(ti, occ, uv_names, {"strength": st} if st != 1.0 else None)

        # emission
        strength = float(bsdf.inputs["Emission Strength"].default_value)
        et = trace(bsdf.inputs["Emission Color"])
        ecol = list(bsdf.inputs["Emission Color"].default_value[:3])
        if et is not None and et["node"] is not None and et["node"].image and strength > 0:
            ti = self.texture_from_node(et["node"], True)
            out["emissiveTexture"] = self._ref(ti, et["node"], uv_names)
            ecol = et["factor"] if isinstance(et["factor"], list) else [et["factor"]] * 3
        ef = [max(0.0, float(c) * strength) for c in ecol]
        if any(v > 0 for v in ef):
            out["emissiveFactor"] = ef

        # alpha mode
        mode = mat.adm.alpha_mode
        if mode == "AUTO":
            if clip is not None:
                mode = "MASK"
            elif alpha_tr is not None or alpha < 1.0:
                mode = "BLEND"
            else:
                mode = "OPAQUE"
        if mode != "OPAQUE":
            out["alphaMode"] = mode
        if mode == "MASK":
            cutoff = clip if (clip is not None and mat.adm.alpha_mode == "AUTO") else mat.adm.alpha_cutoff
            if abs(cutoff - 0.5) > 1e-6:
                out["alphaCutoff"] = _c01(cutoff)
        if double_sided:
            out["doubleSided"] = True
        return out


def _scalar(f):
    return f[0] if isinstance(f, list) else f


def _c01(x):
    return min(1.0, max(0.0, float(x)))


# ================================================================================================
# shaders (§8.1-8.4)
# ================================================================================================
class ShaderExportError(Exception):
    pass


def unique_animation_id(name, taken):
    base = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "material"
    if not base[0].isalpha():
        base = "m_" + base
    aid, i = base, 1
    while aid in taken:
        i += 1
        aid = f"{base}_{i}"
    return aid


def layer_dict(rec):
    d = {"baseColorFactor": [_c01(x) for x in rec.base_color],
         "metallicFactor": _c01(rec.metallic), "roughnessFactor": _c01(rec.roughness),
         "emissiveFactor": [max(0.0, float(x)) for x in rec.emissive]}
    if rec.use_normal_factor:
        d["normalFactor"] = [float(x) for x in rec.normal_factor]
    return d


def layer_from_dict(rec, d):
    rec.base_color = d.get("baseColorFactor", [1, 1, 1, 1])
    rec.metallic = d.get("metallicFactor", 1.0)
    rec.roughness = d.get("roughnessFactor", 1.0)
    rec.emissive = d.get("emissiveFactor", [0, 0, 0])
    rec.use_normal_factor = "normalFactor" in d
    if "normalFactor" in d:
        rec.normal_factor = d["normalFactor"]


def _num_value(typ, vec):
    n = K.SHADER_NUMERIC_DIMS[typ]
    return float(vec[0]) if n == 1 else [float(x) for x in vec[:n]]


def param_def_dict(p, texref):
    """ADMShaderParamDef -> JSON parameter definition."""
    d = {"name": p.name, "type": p.type}
    if p.type in K.SHADER_NUMERIC_DIMS:
        d["default"] = _num_value(p.type, p.default_vec)
        if p.use_minimum:
            d["minimum"] = _num_value(p.type, p.minimum)
        if p.use_maximum:
            d["maximum"] = _num_value(p.type, p.maximum)
        if p.animatable:
            d["animatable"] = True
    elif p.type == "BOOL":
        d["default"] = bool(p.default_bool)
    else:
        d["default"] = texref(p.default_image, p.default_tex_coord)
    d["description"] = p.description.strip()
    return d


def scene_shader_registry(scene):
    """(id, version) -> {name: param dict} for official shaders plus the scene's shader definitions."""
    defs = []
    for sdef in scene.adm_anim.shaders:
        defs.append({"id": sdef.shader_id.strip(), "version": sdef.version.strip(),
                     "parameters": [param_def_dict(p, lambda img, uv: None) for p in sdef.params]})
    return shader_registry({"shaderDefinitions": defs})


def param_value_from_prop(typ, v, texref):
    if typ in K.SHADER_NUMERIC_DIMS:
        return float(v.value_f) if typ == "F32" else _num_value(typ, v.value_vec)
    if typ == "BOOL":
        return bool(v.value_bool)
    return texref(v.image, v.tex_coord)


def _set_vec(prop_owner, attr, value, n):
    vals = [value] if n == 1 else list(value)
    cur = list(getattr(prop_owner, attr))
    cur[:len(vals)] = vals
    setattr(prop_owner, attr, cur)


def import_shader_definitions(scene, doc, resolve_image):
    """Add the document's embedded shader definitions to ``scene.adm_anim.shaders`` (skip existing)."""
    shaders = scene.adm_anim.shaders
    for d in doc.get("shaderDefinitions", []) or []:
        name = f"{d['id']}@{d['version']}"
        if shaders.get(name) is not None:
            continue
        sd = shaders.add()
        sd.shader_id = d["id"]
        sd.version = d["version"]
        sd.name = name
        sd.description = d.get("description", "")
        sd.author = d.get("author", "")
        for p in d.get("parameters", []):
            pd = sd.params.add()
            pd.name = p["name"]
            pd.type = p["type"]
            pd.description = p.get("description", "")
            pd.animatable = bool(p.get("animatable", False))
            n = K.SHADER_NUMERIC_DIMS.get(p["type"])
            if n:
                _set_vec(pd, "default_vec", p["default"], n)
                if "minimum" in p:
                    pd.use_minimum = True
                    _set_vec(pd, "minimum", p["minimum"], n)
                if "maximum" in p:
                    pd.use_maximum = True
                    _set_vec(pd, "maximum", p["maximum"], n)
            elif p["type"] == "BOOL":
                pd.default_bool = bool(p["default"])
            elif isinstance(p.get("default"), dict):
                pd.default_image = resolve_image(p["default"])
                pd.default_tex_coord = p["default"].get("texCoord", 0)


def sync_material_params(mat, sdef):
    """Make ``mat.adm.params`` mirror the definition (keeps existing values, drops stale entries)."""
    a = mat.adm
    names = [p.name for p in sdef.params]
    for i in range(len(a.params) - 1, -1, -1):
        if a.params[i].name not in names:
            a.params.remove(i)
    for p in sdef.params:
        if a.params.get(p.name) is not None:
            continue
        v = a.params.add()
        v.name = p.name
        v.use = False
        v.value_f = p.default_vec[0]
        v.value_vec = p.default_vec
        v.value_bool = p.default_bool
        v.image = p.default_image
        v.tex_coord = p.default_tex_coord


def apply_shader(mat, m, scene, resolve_image):
    """Read ADM shader fields of material dict ``m`` into ``mat.adm``."""
    a = mat.adm
    a.animation_id = m.get("animationId", "")
    sh = m.get("shader")
    key = (sh["id"], sh["version"]) if isinstance(sh, dict) else K.SHADER_CORE
    sp = m.get("shaderParameters", {}) or {}
    if key == K.SHADER_CORE:
        a.shader = "CORE"
    elif key == K.SHADER_LAYERED:
        a.shader = "LAYERED"
        a.layer_factor = sp.get("layer_factor", 0.0)
        ext = (m.get("extensions") or {}).get(K.LAYERS_EXT)
        if ext:
            layer_from_dict(a.layer_base, ext.get("base", {}))
            layer_from_dict(a.layer_overlay, ext.get("overlay", {}))
            if "maskTexture" in ext:
                a.layer_mask = resolve_image(ext["maskTexture"])
                a.layer_mask_uv = ext["maskTexture"].get("texCoord", 0)
    else:
        a.shader = "CUSTOM"
        a.custom_shader = f"{key[0]}@{key[1]}"
        sdef = scene.adm_anim.shaders.get(a.custom_shader)
        if sdef is not None:
            sync_material_params(mat, sdef)
            types = {p.name: p.type for p in sdef.params}
            for name, val in sp.items():
                v = a.params.get(name)
                typ = types.get(name)
                if v is None or typ is None:
                    continue
                v.use = True
                if typ == "F32":
                    v.value_f = val
                elif typ in K.SHADER_NUMERIC_DIMS:
                    _set_vec(v, "value_vec", val, K.SHADER_NUMERIC_DIMS[typ])
                elif typ == "BOOL":
                    v.value_bool = bool(val)
                elif isinstance(val, dict):
                    v.image = resolve_image(val)
                    v.tex_coord = val.get("texCoord", 0)
                else:
                    v.image = None


def layers_from_pbr(mat):
    """Copy the material's current PBR factors into the base layer record (overlay keeps its values)."""
    from .material_anim import pbr_values
    vals = pbr_values(mat)
    rec = mat.adm.layer_base
    rec.base_color = [_c01(x) for x in vals["baseColorFactor"]]
    rec.metallic = _c01(vals["metallicFactor"])
    rec.roughness = _c01(vals["roughnessFactor"])
    rec.emissive = vals["emissiveFactor"]


# ================================================================================================
# import
# ================================================================================================
def _uv_node(nt, tex_node, tex_coord, x, y):
    if tex_coord:
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = UV_NAMES[1]
        uv.location = (x - 220, y)
        nt.links.new(uv.outputs["UV"], tex_node.inputs["Vector"])


def _tex_node(nt, image, sampler, non_color, x, y, label):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = image
    n.label = label
    n.location = (x, y)
    if image is not None and non_color:
        try:
            image.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    sampler = sampler or {}
    if sampler.get("magFilter") == "NEAREST":
        n.interpolation = "Closest"
    n.extension = {"CLAMP_TO_EDGE": "EXTEND", "MIRRORED_REPEAT": "MIRROR"}.get(sampler.get("wrapS", "REPEAT"), "REPEAT")
    return n


def build_material(m, resolve_texture):
    """Create a Blender material from an ADM material dict.

    ``resolve_texture(textureRef) -> (bpy.types.Image, sampler_dict)``.
    """
    mat = bpy.data.materials.new(m.get("name", "ADM Material"))
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bcf = m.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
    bsdf.inputs["Base Color"].default_value = (bcf[0], bcf[1], bcf[2], 1.0)
    bsdf.inputs["Alpha"].default_value = bcf[3]
    bsdf.inputs["Metallic"].default_value = m.get("metallicFactor", 1.0)
    bsdf.inputs["Roughness"].default_value = m.get("roughnessFactor", 1.0)
    mat.diffuse_color = (bcf[0], bcf[1], bcf[2], bcf[3])
    alpha_mode = m.get("alphaMode", "OPAQUE")
    mat.adm.alpha_mode = alpha_mode
    mat.adm.alpha_cutoff = m.get("alphaCutoff", 0.5)
    mat.use_backface_culling = not m.get("doubleSided", False)

    y = 300
    if "baseColorTexture" in m:
        img, smp = resolve_texture(m["baseColorTexture"])
        tn = _tex_node(nt, img, smp, False, -900, y, "Base Color")
        _uv_node(nt, tn, m["baseColorTexture"].get("texCoord", 0), -900, y)
        col = tn.outputs["Color"]
        if bcf[:3] != [1.0, 1.0, 1.0]:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-450, y)
            mix.inputs[0].default_value = 1.0
            ca, cb = _color_inputs(mix)[:2]
            nt.links.new(col, ca)
            cb.default_value = (bcf[0], bcf[1], bcf[2], 1.0)
            col = mix.outputs[2] if mix.outputs[2].type == "RGBA" else next(o for o in mix.outputs if o.type == "RGBA")
        nt.links.new(col, bsdf.inputs["Base Color"])
        if alpha_mode != "OPAQUE":
            a = tn.outputs["Alpha"]
            if bcf[3] != 1.0:
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.location = (-450, y - 200)
                nt.links.new(a, mul.inputs[0])
                mul.inputs[1].default_value = bcf[3]
                a = mul.outputs[0]
            if alpha_mode == "MASK":
                clip = nt.nodes.new("ShaderNodeMath")
                clip.name = clip.label = ALPHA_CLIP_NODE
                clip.operation = "GREATER_THAN"
                clip.location = (-250, y - 200)
                nt.links.new(a, clip.inputs[0])
                clip.inputs[1].default_value = m.get("alphaCutoff", 0.5) - 1e-6
                a = clip.outputs[0]
            nt.links.new(a, bsdf.inputs["Alpha"])
        y -= 300
    if "metallicRoughnessTexture" in m:
        img, smp = resolve_texture(m["metallicRoughnessTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Metallic Roughness")
        _uv_node(nt, tn, m["metallicRoughnessTexture"].get("texCoord", 0), -900, y)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (-600, y)
        nt.links.new(tn.outputs["Color"], sep.inputs[0])
        for out_name, target, fac in (("Green", "Roughness", m.get("roughnessFactor", 1.0)),
                                      ("Blue", "Metallic", m.get("metallicFactor", 1.0))):
            s = sep.outputs[out_name]
            if fac != 1.0:
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.location = (-350, y - (0 if target == "Roughness" else 150))
                nt.links.new(s, mul.inputs[0])
                mul.inputs[1].default_value = fac
                s = mul.outputs[0]
            nt.links.new(s, bsdf.inputs[target])
        y -= 300
    if "normalTexture" in m:
        img, smp = resolve_texture(m["normalTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Normal")
        tc = m["normalTexture"].get("texCoord", 0)
        _uv_node(nt, tn, tc, -900, y)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-450, y)
        nm.inputs["Strength"].default_value = m["normalTexture"].get("scale", 1.0)
        if tc:
            nm.uv_map = UV_NAMES[1]
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        y -= 300
    if "occlusionTexture" in m:
        img, smp = resolve_texture(m["occlusionTexture"])
        tn = _tex_node(nt, img, smp, True, -900, y, "Occlusion (ADM)")
        tn.name = OCCLUSION_NODE
        _uv_node(nt, tn, m["occlusionTexture"].get("texCoord", 0), -900, y)
        mat.adm.occlusion_strength = m["occlusionTexture"].get("strength", 1.0)
        y -= 300
    ef = m.get("emissiveFactor", [0.0, 0.0, 0.0])
    strength = max(ef) if max(ef) > 0 else 0.0
    if strength > 0:
        bsdf.inputs["Emission Strength"].default_value = strength
        bsdf.inputs["Emission Color"].default_value = (ef[0] / strength, ef[1] / strength, ef[2] / strength, 1.0)
    if "emissiveTexture" in m:
        img, smp = resolve_texture(m["emissiveTexture"])
        tn = _tex_node(nt, img, smp, False, -900, y, "Emissive")
        _uv_node(nt, tn, m["emissiveTexture"].get("texCoord", 0), -900, y)
        col = tn.outputs["Color"]
        if strength > 0 and any(abs(c / strength - 1.0) > 1e-6 for c in ef):
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-450, y)
            mix.inputs[0].default_value = 1.0
            ca, cb = _color_inputs(mix)[:2]
            nt.links.new(col, ca)
            cb.default_value = (ef[0] / strength, ef[1] / strength, ef[2] / strength, 1.0)
            col = next(o for o in mix.outputs if o.type == "RGBA")
        nt.links.new(col, bsdf.inputs["Emission Color"])
    apply_alpha_mode_to_material(mat, alpha_mode)
    return mat


def apply_alpha_mode_to_material(mat, mode):
    if mode == "BLEND":
        mat.surface_render_method = "BLENDED"
    else:
        mat.surface_render_method = "DITHERED"


def convert_to_adm_material(mat):
    """Normalize any material so it has an output -> Principled BSDF chain (keeps existing nodes)."""
    nt = mat.node_tree
    if principled_of(mat) is not None and output_surface_shader(mat) is not None and \
            output_surface_shader(mat).type == "BSDF_PRINCIPLED":
        return False
    color = tuple(mat.diffuse_color)
    old = output_surface_shader(mat)
    if old is not None:
        for name in ("Color", "Base Color"):
            if name in old.inputs and not old.inputs[name].is_linked and old.inputs[name].type == "RGBA":
                color = tuple(old.inputs[name].default_value)
                break
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (out.location.x - 300, out.location.y)
    bsdf.inputs["Base Color"].default_value = color
    if old is not None:
        for name in ("Color", "Base Color"):
            if name in old.inputs and old.inputs[name].is_linked:
                nt.links.new(old.inputs[name].links[0].from_socket, bsdf.inputs["Base Color"])
                break
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return True
