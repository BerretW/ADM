"""Viewport node previews for the official ADM shader profiles (Core 20 registry).

Every preview is a separate node group named ``ADM Preview *`` with its own active Material Output.
The material's own output -> Principled BSDF chain stays untouched and is what the exporter writes as
the portable PBR fallback, so preview nodes never leak into the ``.adm`` file.

Numeric parameters are wired through drivers on ``mat.adm.params[...]``: dragging a value or playing
an animated parameter updates the viewport without rebuilding.  Toggling *Override* or changing a
texture rebuilds the preview (see ``props.py`` update callbacks).

Light-dependent terms that Blender material nodes cannot express exactly (skin wrap diffuse, fur and
fabric tangent lobes) use Principled BSDF approximations; ``APPROXIMATE`` lists those profiles.
"""

import bpy

from ..core import constants as K
from .materials import PREVIEW_PREFIX, UV_NAMES, _from, material_output, principled_of

APPROXIMATE = frozenset({"SKIN", "FUR", "FABRIC"})

# Principled inputs mirrored live from the fallback BSDF when they are plain values.
_DRIVEN_INPUTS = ("Base Color", "Alpha", "Metallic", "Roughness", "Emission Color", "Emission Strength")
_SKIP_PROPS = {
    "rna_type", "name", "label", "location", "location_absolute", "width", "height", "dimensions", "parent",
    "select", "show_options", "show_preview", "hide", "mute", "show_texture", "use_custom_color", "color",
    "is_active_output", "inputs", "outputs", "internal_links", "type", "warning_propagation", "color_tag",
}


class _Graph:
    def __init__(self, mat):
        self.mat = mat
        self.nt = mat.node_tree
        self.a = mat.adm
        self.fallback = principled_of(mat)
        own = material_output(mat)
        self.x0, self.y0 = (own.location.x, own.location.y - 900) if own is not None else (300.0, -900.0)
        self._n = 0
        self._clones = {}
        self.uv_xform = None
        key = self.a.shader_key()
        self.schema = {p["name"]: p for p in K.OFFICIAL_SHADERS.get(key, [])}

    # -- nodes -------------------------------------------------------------------------------------
    def new(self, kind, name, **props):
        n = self.nt.nodes.new(kind)
        n.name = n.label = f"{PREVIEW_PREFIX} {name}"
        col, row = divmod(self._n, 10)
        n.location = (self.x0 - 260 - 220 * col, self.y0 - 190 * row)
        self._n += 1
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.new("ShaderNodeMath", op.title(), operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self._feed(n.inputs[i], v)
        return n.outputs[0]

    def vmath(self, op, a, b=None, c=None):
        n = self.new("ShaderNodeVectorMath", op.title(), operation=op)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self._feed(n.inputs[i], v)
        return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector"]

    def mix(self, kind, a, b, fac):
        n = self.new("ShaderNodeMix", f"Mix {kind.title()}", data_type=kind, clamp_factor=True)
        suffix = {"RGBA": "Color", "FLOAT": "Float", "VECTOR": "Vector"}[kind]
        self._feed(_sock(n, "Factor_Float"), fac)
        self._feed(_sock(n, f"A_{suffix}"), a)
        self._feed(_sock(n, f"B_{suffix}"), b)
        return _out(n, f"Result_{suffix}")

    def _feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.nt.links.new(value, socket)
        elif isinstance(value, (tuple, list)):
            cur = list(socket.default_value)
            cur[:len(value)] = value
            socket.default_value = cur
        else:
            socket.default_value = value

    def combine(self, xyz):
        n = self.new("ShaderNodeCombineXYZ", "Combine")
        for i, v in enumerate(xyz):
            self._feed(n.inputs[i], v)
        return n.outputs[0]

    def separate(self, vec):
        n = self.new("ShaderNodeSeparateXYZ", "Separate")
        self._feed(n.inputs[0], vec)
        return n.outputs

    def _driver(self, socket, path, index=-1, id_type="MATERIAL", id_=None, expression=None):
        fc = socket.driver_add("default_value", index) if index >= 0 else socket.driver_add("default_value")
        fc.driver.type = "SCRIPTED" if expression else "AVERAGE"
        var = fc.driver.variables.new()
        var.name = "v"
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = id_type
        var.targets[0].id = id_ if id_ is not None else self.mat
        var.targets[0].data_path = path
        if expression:
            fc.driver.expression = expression
        return fc

    # -- parameters --------------------------------------------------------------------------------
    def _param(self, name):
        v = self.a.params.get(name)
        return v if v is not None and v.use else None

    def comp(self, name, i=0):
        """Value socket for component ``i`` of numeric parameter ``name`` (driven when overridden)."""
        prm = self.schema[name]
        dflt = prm["default"]
        dflt = float(dflt) if prm["type"] == "F32" else float(dflt[i])
        node = self.new("ShaderNodeValue", f"{name}[{i}]" if prm["type"] != "F32" else name)
        node.outputs[0].default_value = dflt
        v = self._param(name)
        if v is not None:
            path = f'adm.params["{name}"].value_f' if prm["type"] == "F32" else f'adm.params["{name}"].value_vec[{i}]'
            self._driver(node.outputs[0], path)
        return node.outputs[0]

    def num(self, name):
        return self.comp(name)

    def vec(self, name):
        n = K.SHADER_NUMERIC_DIMS[self.schema[name]["type"]]
        return self.combine([self.comp(name, i) for i in range(min(n, 3))])

    def tex(self, name, vector=None, scaled=False):
        """Image Texture node for TEXTURE parameter ``name`` or None when unset/not overridden."""
        v = self._param(name)
        if v is None or v.image is None:
            return None
        n = self.new("ShaderNodeTexImage", name)
        n.image = v.image
        uv = vector if vector is not None else self.uv(v.tex_coord)
        if scaled and self.uv_xform is not None:
            uv = self.uv_xform(uv)
        self.nt.links.new(uv, n.inputs["Vector"])
        return n

    def red(self, tex_node):
        sep = self.new("ShaderNodeSeparateColor", "Red")
        self.nt.links.new(tex_node.outputs["Color"], sep.inputs[0])
        return sep.outputs["Red"]

    def uv(self, tex_coord=0):
        if tex_coord:
            n = self.new("ShaderNodeUVMap", "UV1", uv_map=UV_NAMES[1])
            return n.outputs["UV"]
        return self.new("ShaderNodeTexCoord", "UV").outputs["UV"]

    def scale_uv(self, factor_socket):
        self.uv_xform = lambda uv: self.vmath("MULTIPLY", uv, factor_socket)

    # -- fallback BSDF mirroring ------------------------------------------------------------------
    def clone(self, socket):
        """Clone the subgraph feeding ``socket`` (fallback side) and return the cloned output socket."""
        s = _from(socket)
        if s is None:
            return None
        node = self._clone_node(s.node)
        return next(o for o in node.outputs if o.identifier == s.identifier)

    def _clone_node(self, src):
        if src.name in self._clones:
            return self._clones[src.name]
        dst = self.new(src.bl_idname, f"Clone {src.name}")
        self._clones[src.name] = dst
        for p in src.bl_rna.properties:
            if p.identifier in _SKIP_PROPS or p.is_readonly or p.identifier.startswith("bl_"):
                continue
            try:
                setattr(dst, p.identifier, getattr(src, p.identifier))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        for si, di in zip(src.inputs, dst.inputs):
            if hasattr(si, "default_value"):
                try:
                    di.default_value = si.default_value
                except (AttributeError, TypeError, ValueError):
                    pass
            up = self.clone(si)
            if src.type == "TEX_IMAGE" and si.identifier == "Vector":
                up = up if up is not None else self.uv(0)
                if self.uv_xform is not None:
                    up = self.uv_xform(up)
            if up is not None:
                self.nt.links.new(up, di)
        return dst

    def source(self, input_name):
        """Preview socket equivalent to the fallback BSDF input (cloned chain or driven constant)."""
        fb = self.fallback
        if fb is None:
            return None
        inp = fb.inputs[input_name]
        up = self.clone(inp)
        if up is not None or input_name == "Normal":
            return up
        path = f'node_tree.nodes["{fb.name}"].inputs["{input_name}"].default_value'
        if inp.type == "RGBA":
            n = self.new("ShaderNodeRGB", input_name)
            n.outputs[0].default_value = tuple(inp.default_value)
            for i in range(3):
                self._driver(n.outputs[0], f"{path}[{i}]", index=i)
        else:
            n = self.new("ShaderNodeValue", input_name)
            n.outputs[0].default_value = float(inp.default_value)
            self._driver(n.outputs[0], path)
        return n.outputs[0]

    def bsdf(self):
        """Preview Principled BSDF mirroring every fallback input; returns the node."""
        b = self.new("ShaderNodeBsdfPrincipled", "BSDF")
        b.location = (self.x0 - 300, self.y0)
        fb = self.fallback
        if fb is None:
            return b
        for attr in ("distribution", "subsurface_method"):
            setattr(b, attr, getattr(fb, attr))
        for si in fb.inputs:
            di = b.inputs.get(si.name)
            if di is None:
                continue
            if si.name in _DRIVEN_INPUTS or si.is_linked:
                up = self.source(si.name)
                if up is not None:
                    self.nt.links.new(up, di)
                    continue
            if hasattr(si, "default_value"):
                try:
                    di.default_value = si.default_value
                except (AttributeError, TypeError, ValueError):
                    pass
        return b

    def link(self, value, socket):
        self._feed(socket, value)

    def output(self, bsdf):
        out = self.new("ShaderNodeOutputMaterial", "Output")
        out.location = (self.x0, self.y0)
        self.nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        out.is_active_output = True
        return out

    # -- shared math ------------------------------------------------------------------------------
    def shading_normal(self, bsdf):
        up = _from(bsdf.inputs["Normal"])
        return up if up is not None else self.new("ShaderNodeNewGeometry", "Geometry").outputs["Normal"]

    def fresnel_c(self, normal):
        """clamp(abs(dot(N, V)), 0, 1) with V = Geometry Incoming (towards the viewer)."""
        geo = self.new("ShaderNodeNewGeometry", "View")
        d = self.vmath("DOT_PRODUCT", normal, geo.outputs["Incoming"])
        return self.math("ABSOLUTE", d, clamp=True)

    def schlick(self, c, f0):
        """F = F0 + (1 - F0) * (1 - c)^5; ``f0`` is a socket or float."""
        p5 = self.math("POWER", self.math("SUBTRACT", 1.0, c), 5.0)
        return self.math("MULTIPLY_ADD", p5, self.math("SUBTRACT", 1.0, f0), f0) \
            if isinstance(f0, bpy.types.NodeSocket) else self.math("MULTIPLY_ADD", p5, 1.0 - f0, f0)

    def f0_from_ior(self, ior):
        r = self.math("DIVIDE", self.math("SUBTRACT", ior, 1.0), self.math("ADD", ior, 1.0))
        return self.math("POWER", r, 2.0)

    def normal_from_tex(self, tex_node, strength=1.0):
        nm = self.new("ShaderNodeNormalMap", "Normal Map")
        nm.inputs["Strength"].default_value = strength
        self.nt.links.new(tex_node.outputs["Color"], nm.inputs["Color"])
        return nm.outputs["Normal"]

    def combine_normals(self, bsdf, detail_world):
        """normalize(coreNormal + detailNormal) in world space; wires the BSDF normal."""
        if detail_world is None:
            return
        n = self.vmath("NORMALIZE", self.vmath("ADD", self.shading_normal(bsdf), detail_world))
        self.nt.links.new(n, bsdf.inputs["Normal"])


def _sock(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def _out(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)


# =================================================================================================
# per-profile builders (each mirrors the pseudocode of adm-standard/shaders/<id>.v1.md)
# =================================================================================================
def _detail_normal(g, b, name, scaled=False, vector=None):
    t = g.tex(name, vector=vector, scaled=scaled)
    if t is not None:
        g.combine_normals(b, g.normal_from_tex(t))


def _brick(g):
    g.scale_uv(g.vec("uv_scale"))
    b = g.bsdf()
    brick = g.source("Base Color")
    t = g.tex("mortar_mask", scaled=True)
    m = g.red(t) if t is not None else 0.0
    color = g.mix("RGBA", brick, g.vec("mortar_color"), m)
    g.link(g.mix("FLOAT", g.num("brick_roughness"), g.num("mortar_roughness"), m), b.inputs["Roughness"])
    dt = g.tex("dirt_mask")
    if dt is not None:
        color = g.vmath("MULTIPLY", color, g.mix("FLOAT", 1.0, 0.35, g.red(dt)))
    g.link(color, b.inputs["Base Color"])
    return b


def _concrete(g):
    b = g.bsdf()
    color = g.source("Base Color")
    scale = g.num("detail_scale")

    def detail_uv(name):
        v = g._param(name)
        if v is None or v.image is None:
            return None
        return g.vmath("MULTIPLY", g.uv(v.tex_coord), g.combine((scale, scale, 1.0)))

    dtex = g.tex("detail_texture", vector=detail_uv("detail_texture"))
    if dtex is not None:
        color = g.vmath("MULTIPLY", color, dtex.outputs["Color"])
    _detail_normal(g, b, "detail_normal", vector=detail_uv("detail_normal"))
    dt = g.tex("dirt_mask")
    if dt is not None:
        d = g.math("MULTIPLY", g.red(dt), g.num("dirt_amount"), clamp=True)
        color = g.mix("RGBA", color, g.vmath("MULTIPLY", color, (0.35, 0.35, 0.35)), d)
    g.link(color, b.inputs["Base Color"])
    return b


def _roof(g):
    b = g.bsdf()
    color = g.source("Base Color")
    t = g.tex("detail_mask")
    if t is not None:
        w = g.math("MULTIPLY", g.red(t), g.num("weather_amount"), clamp=True)
        color = g.mix("RGBA", color, g.vec("weather_tint"), w)
    g.link(color, b.inputs["Base Color"])
    return b


def _bark(g):
    g.scale_uv(g.vec("uv_scale"))
    b = g.bsdf()
    color = g.source("Base Color")
    t = g.tex("moss_mask")
    if t is not None:
        m = g.math("MULTIPLY", g.red(t), g.num("moss_amount"), clamp=True)
        color = g.mix("RGBA", color, g.vmath("MULTIPLY", color, (0.45, 0.45, 0.45)), m)
    g.link(color, b.inputs["Base Color"])
    _detail_normal(g, b, "detail_normal", scaled=True)
    return b


def _rock(g):
    b = g.bsdf()
    color = g.source("Base Color")
    tc = g.new("ShaderNodeTexCoord", "Object")
    p = g.vmath("SCALE", tc.outputs["Object"], None)
    g.link(g.math("MULTIPLY", g.num("triplanar_scale"), g.num("detail_scale")), p.node.inputs["Scale"])
    pn = g.separate(p)
    nn = tc.outputs["Normal"]
    an = g.separate(g.vmath("ABSOLUTE", nn))
    w4 = [g.math("POWER", an[i], 4.0) for i in range(3)]
    total = g.math("MAXIMUM", g.math("ADD", g.math("ADD", w4[0], w4[1]), w4[2]), 1e-8)
    w = [g.math("DIVIDE", w4[i], total) for i in range(3)]
    projections = ((pn[1], pn[2]), (pn[0], pn[2]), (pn[0], pn[1]))
    vectors = [g.combine((u, v, 0.0)) for u, v in projections]
    samples = [g.tex("detail_texture", vector=vec) for vec in vectors]
    if samples[0] is not None:
        acc = None
        for i, s in enumerate(samples):
            term = g.vmath("SCALE", s.outputs["Color"])
            g.link(w[i], term.node.inputs["Scale"])
            acc = term if acc is None else g.vmath("ADD", acc, term)
        color = g.vmath("MULTIPLY", color, acc)
    nsamples = [g.tex("detail_normal", vector=vec) for vec in vectors]
    if nsamples[0] is not None:
        sn = g.separate(nn)
        sign = [g.math("SIGN", sn[i]) for i in range(3)]
        acc = None
        for i, s in enumerate(nsamples):
            t = g.separate(g.vmath("MULTIPLY_ADD", s.outputs["Color"], (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0)))
            tz = g.math("MULTIPLY", t[2], sign[i])
            comps = ((tz, t[0], t[1]), (t[0], tz, t[1]), (t[0], t[1], tz))[i]
            term = g.vmath("SCALE", g.combine(comps))
            g.link(w[i], term.node.inputs["Scale"])
            acc = term if acc is None else g.vmath("ADD", acc, term)
        xf = g.new("ShaderNodeVectorTransform", "Object To World", vector_type="NORMAL",
                   convert_from="OBJECT", convert_to="WORLD")
        g.link(g.vmath("NORMALIZE", acc), xf.inputs[0])
        g.combine_normals(b, xf.outputs[0])
    mt = g.tex("moss_mask")
    if mt is not None:
        color = g.vmath("MULTIPLY", color, g.mix("FLOAT", 1.0, 0.4, g.red(mt)))
    g.link(color, b.inputs["Base Color"])
    return b


def _terrain(g):
    b = g.bsdf()
    mask = g.tex("blend_mask")
    if mask is not None:
        rgb = g.new("ShaderNodeSeparateColor", "Mask RGB")
        g.link(mask.outputs["Color"], rgb.inputs[0])
        ch = [g.math("MAXIMUM", s, 0.0) for s in (rgb.outputs[0], rgb.outputs[1], rgb.outputs[2],
                                                  mask.outputs["Alpha"])]
        total = g.math("ADD", g.math("ADD", ch[0], ch[1]), g.math("ADD", ch[2], ch[3]))
        safe = g.math("MAXIMUM", total, 1e-8)
        zero = g.math("LESS_THAN", total, 1e-8)
        w = [g.math("DIVIDE", c, safe) for c in ch]
        w[0] = g.math("ADD", w[0], zero)
    else:
        w = [1.0, 0.0, 0.0, 0.0]
    albedo = alpha = metal = rough = emis = normal = None
    uvs = g.separate(g.combine((g.comp("uv_scale", 0), g.comp("uv_scale", 1), g.comp("uv_scale", 2))))
    scales = [uvs[0], uvs[1], uvs[2], g.comp("uv_scale", 3)]

    def acc(total, term):
        return term if total is None else (g.vmath("ADD", total, term) if isinstance(term, bpy.types.NodeSocket)
                                           and term.type == "VECTOR" else g.math("ADD", total, term))

    def wvec(i, vec):
        n = g.vmath("SCALE", vec)
        g.link(w[i], n.node.inputs["Scale"])
        return n

    for i in range(4):
        if not isinstance(w[i], bpy.types.NodeSocket) and w[i] == 0.0:
            continue
        base = g.combine((g.comp(f"layer{i}_base_color", 0), g.comp(f"layer{i}_base_color", 1),
                          g.comp(f"layer{i}_base_color", 2)))
        balpha = g.comp(f"layer{i}_base_color", 3)
        v = g._param(f"layer{i}_texture")
        uv = g.vmath("SCALE", g.uv(v.tex_coord if v else 0))
        g.link(scales[i], uv.node.inputs["Scale"])
        t = g.tex(f"layer{i}_texture", vector=uv)
        if t is not None:
            base = g.vmath("MULTIPLY", base, t.outputs["Color"])
            balpha = g.math("MULTIPLY", balpha, t.outputs["Alpha"])
        albedo = acc(albedo, wvec(i, base))
        alpha = acc(alpha, g.math("MULTIPLY", w[i], balpha))
        metal = acc(metal, g.math("MULTIPLY", w[i], g.num(f"layer{i}_metallic")))
        rough = acc(rough, g.math("MULTIPLY", w[i], g.num(f"layer{i}_roughness")))
        emis = acc(emis, wvec(i, g.vec(f"layer{i}_emissive")))
        nt = g.tex(f"layer{i}_normal", vector=uv)
        tn = g.vmath("MULTIPLY_ADD", nt.outputs["Color"], (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0)) \
            if nt is not None else g.combine((0.0, 0.0, 1.0))
        normal = acc(normal, wvec(i, tn))
    g.link(albedo, b.inputs["Base Color"])
    g.link(alpha, b.inputs["Alpha"])
    g.link(metal, b.inputs["Metallic"])
    g.link(rough, b.inputs["Roughness"])
    g.link(emis, b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 1.0
    enc = g.vmath("MULTIPLY_ADD", g.vmath("NORMALIZE", normal), (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    nm = g.new("ShaderNodeNormalMap", "Terrain Normal")
    g.link(enc, nm.inputs["Color"])
    g.link(nm.outputs["Normal"], b.inputs["Normal"])
    return b


def _thin_fresnel(g, b, tint_a, tint_b, transparency, ior, base_alpha):
    f = g.schlick(g.fresnel_c(g.shading_normal(b)), g.f0_from_ior(ior))
    g.link(g.mix("RGBA", tint_a, tint_b, f), b.inputs["Base Color"])
    cover = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", transparency, g.math("SUBTRACT", 1.0, f)), clamp=True)
    g.link(g.math("MULTIPLY", cover, base_alpha) if base_alpha is not None else cover, b.inputs["Alpha"])


def _glass(g):
    b = g.bsdf()
    alpha = g.source("Alpha")
    _thin_fresnel(g, b, g.vec("glass_tint"), g.vec("reflection_tint"), g.num("transparency"), g.num("ior"), alpha)
    return b


def _water(g):
    vel = g.vec("uv_velocity")
    time = g.new("ShaderNodeValue", "Time").outputs[0]
    fc = g._driver(time, "render.fps", id_type="SCENE", id_=bpy.context.scene, expression="frame / v")
    del fc
    g.uv_xform = lambda uv: g.vmath("FRACTION", g.vmath("MULTIPLY_ADD", vel, g.combine((time, time, 0.0)), uv))
    b = g.bsdf()
    _thin_fresnel(g, b, g.vec("water_tint"), (1.0, 1.0, 1.0, 1.0), g.num("transparency"), g.num("ior"), None)
    return b


def _vehicle_paint(g):
    b = g.bsdf()
    f = g.schlick(g.fresnel_c(g.shading_normal(b)), 0.04)
    k = g.math("MULTIPLY", f, g.num("edge_tint_strength"))
    g.link(g.mix("RGBA", g.source("Base Color"), g.vec("edge_tint"), k), b.inputs["Base Color"])
    g.link(g.num("clearcoat"), b.inputs["Coat Weight"])
    g.link(g.num("clearcoat_roughness"), b.inputs["Coat Roughness"])
    b.inputs["Coat IOR"].default_value = 1.5
    return b


def _skin(g):
    b = g.bsdf()
    s = g.num("subsurface_strength")
    tint = g.vec("subsurface_color")
    g.link(g.mix("RGBA", g.source("Base Color"), tint, s), b.inputs["Base Color"])
    g.link(s, b.inputs["Subsurface Weight"])
    g.link(tint, b.inputs["Subsurface Radius"])
    _detail_normal(g, b, "detail_normal")
    return b


def _fiber(g, b, tex_name, weight):
    color = g.vec("fiber_tint")
    t = g.tex(tex_name)
    if t is not None:
        color = g.vmath("MULTIPLY", color, g.combine((g.red(t),) * 3))
    g.link(weight, b.inputs["Anisotropic"])
    g.link(color, b.inputs["Specular Tint"])
    tan = g.new("ShaderNodeTangent", "Tangent", direction_type="UV_MAP")
    g.link(tan.outputs["Tangent"], b.inputs["Tangent"])


def _fur(g):
    b = g.bsdf()
    _fiber(g, b, "fur_detail", g.math("MULTIPLY", g.num("anisotropy"),
                                      g.math("SUBTRACT", 1.0, g.num("fiber_roughness")), clamp=True))
    return b


def _fabric(g):
    b = g.bsdf()
    _fiber(g, b, "fiber_detail", g.math("MULTIPLY", g.num("fiber_strength"), g.num("anisotropy"), clamp=True))
    _detail_normal(g, b, "detail_normal")
    return b


def _feather(g):
    b = g.bsdf()
    _detail_normal(g, b, "detail_normal")
    c = g.fresnel_c(g.shading_normal(b))
    f = g.math("POWER", g.math("SUBTRACT", 1.0, c), 5.0)
    sheen = g.vmath("SCALE", g.vec("sheen_tint"))
    g.link(g.math("MULTIPLY", g.num("sheen_strength"), f), sheen.node.inputs["Scale"])
    color = g.vmath("MAXIMUM", g.vmath("ADD", g.source("Base Color"), sheen), (0.0, 0.0, 0.0))
    g.link(color, b.inputs["Base Color"])
    return b


def _scales(g):
    b = g.bsdf()
    color = g.source("Base Color")
    t = g.tex("detail_texture")
    if t is not None:
        color = g.vmath("MULTIPLY", color, t.outputs["Color"])
    g.link(color, b.inputs["Base Color"])
    g.link(g.num("scale_metallic"), b.inputs["Metallic"])
    # Principled F0 = 0.08 * level at IOR 1.5, so F0 = mix(0.04, 0.08, s) gives level = 0.5 + 0.5*s.
    b.inputs["IOR"].default_value = 1.5
    g.link(g.math("MULTIPLY_ADD", g.num("specular_strength"), 0.5, 0.5), b.inputs["Specular IOR Level"])
    nt = g.tex("scale_normal")
    if nt is not None:
        g.combine_normals(b, g.normal_from_tex(nt))
    return b


def _foliage(g):
    b = g.bsdf()
    base = g.source("Base Color")
    back = g.new("ShaderNodeNewGeometry", "Backfacing").outputs["Backfacing"]
    k = g.math("MULTIPLY", back, g.num("transmission"))
    g.link(g.mix("RGBA", base, g.vmath("MULTIPLY", base, g.vec("backface_tint")), k), b.inputs["Base Color"])
    return b


def _vertex_color(g):
    """Return COLOR_0 components, using the extension defaults when no mesh supplies the attribute."""
    has_attribute = any(
        obj.type == "MESH" and g.mat.name in obj.data.materials
        and obj.data.color_attributes.get("COLOR_0") is not None
        for obj in bpy.data.objects
    )
    if not has_attribute:
        return (0.0, 1.0, 1.0, 0.0)
    node = g.new("ShaderNodeVertexColor", "COLOR_0", layer_name="COLOR_0")
    separate = g.new("ShaderNodeSeparateColor", "COLOR_0 Channels")
    g.link(node.outputs["Color"], separate.inputs[0])
    return (*tuple(separate.outputs[name] for name in ("Red", "Green", "Blue")), node.outputs["Alpha"])


def _socket_source(g, socket):
    return _from(socket) if socket.is_linked else socket.default_value


def _apply_vertex_controls(g, bsdf):
    a = g.a
    if not a.vertex_controls_enabled:
        return

    color0 = _vertex_color(g)
    red, green, blue, alpha = color0
    tint_offset = g.new("ShaderNodeValue", "Tint Offset").outputs[0]
    tint_offset.default_value = float(a.tint_offset)
    g._driver(tint_offset, "adm.tint_offset")
    normal_multiplier = g.new("ShaderNodeValue", "Normal Multiplier").outputs[0]
    normal_multiplier.default_value = float(a.normal_multiplier)
    g._driver(normal_multiplier, "adm.normal_multiplier")
    reflection_multiplier = g.new("ShaderNodeValue", "Reflection Multiplier").outputs[0]
    reflection_multiplier.default_value = float(a.reflection_multiplier)
    g._driver(reflection_multiplier, "adm.reflection_multiplier")
    wetness_offset = g.new("ShaderNodeValue", "Wetness Offset").outputs[0]
    wetness_offset.default_value = float(a.wetness_offset)
    g._driver(wetness_offset, "adm.wetness_offset")

    base_color = _socket_source(g, bsdf.inputs["Base Color"])
    base_parts = g.new("ShaderNodeSeparateColor", "Base Color Channels")
    g.link(base_color, base_parts.inputs[0])
    base_alpha = _socket_source(g, bsdf.inputs["Alpha"])
    palette_alpha = 1.0
    palette_rgb = None
    palette = a.vertex_tint_palette
    if palette is not None and palette.size[0] > 0:
        count = int(palette.size[0])
        position = g.math("MULTIPLY_ADD", red, float(count), tint_offset)
        index = g.math("FLOOR", g.math("MINIMUM", g.math("MAXIMUM", position, 0.0), float(count - 1)))
        u = g.math("DIVIDE", g.math("ADD", index, 0.5), float(count))
        sample = g.new("ShaderNodeTexImage", "Tint Palette", interpolation="Closest", extension="CLIP")
        sample.image = palette
        g.link(g.combine((u, 0.5, 0.0)), sample.inputs["Vector"])
        palette_parts = g.new("ShaderNodeSeparateColor", "Palette Channels")
        g.link(sample.outputs["Color"], palette_parts.inputs[0])
        palette_rgb = tuple(palette_parts.outputs[name] for name in ("Red", "Green", "Blue"))
        palette_alpha = sample.outputs["Alpha"]

    if palette_rgb is None:
        tinted_rgb = tuple(base_parts.outputs[name] for name in ("Red", "Green", "Blue"))
    elif a.vertex_tint_mode == "REPLACE":
        tinted_rgb = palette_rgb
    else:
        tinted_rgb = tuple(g.math("MULTIPLY", base_parts.outputs[name], value)
                           for name, value in zip(("Red", "Green", "Blue"), palette_rgb))
        base_alpha = g.math("MULTIPLY", base_alpha, palette_alpha)

    wetness = g.math("ADD", alpha, wetness_offset, clamp=True)
    color_scale = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", wetness, 0.15))
    g.link(g.combine(tuple(g.math("MULTIPLY", component, color_scale) for component in tinted_rgb)),
           bsdf.inputs["Base Color"])
    g.link(base_alpha, bsdf.inputs["Alpha"])

    base_roughness = _socket_source(g, bsdf.inputs["Roughness"])
    wet_roughness = g.math("MINIMUM", base_roughness, 0.10)
    g.link(g.mix("FLOAT", base_roughness, wet_roughness, wetness), bsdf.inputs["Roughness"])

    normal_strength = g.math("MULTIPLY", green, normal_multiplier, clamp=True)
    for node in list(g.nt.nodes):
        if node.type == "NORMAL_MAP" and node.name.startswith(PREVIEW_PREFIX):
            base_strength = float(node.inputs["Strength"].default_value)
            node.inputs["Strength"].default_value = 1.0
            scaled_strength = g.math("MULTIPLY", normal_strength, base_strength, clamp=True)
            g.link(scaled_strength, node.inputs["Strength"])

    specular = bsdf.inputs.get("Specular IOR Level")
    if specular is not None:
        base_f0 = g.math("MULTIPLY", _socket_source(g, specular), 0.08)
        reflected_f0 = g.math("MULTIPLY", base_f0,
                              g.math("MULTIPLY", blue, reflection_multiplier, clamp=True))
        water_f0 = ((1.333 - 1.0) / (1.333 + 1.0)) ** 2
        wet_f0 = g.mix("FLOAT", reflected_f0,
                       g.math("MULTIPLY_ADD", reflected_f0, (1.0 - water_f0) ** 2, water_f0), wetness)
        g.link(g.math("DIVIDE", wet_f0, 0.08, clamp=True), specular)


BUILDERS = {
    "BRICK": _brick, "CONCRETE": _concrete, "ROOF": _roof, "BARK": _bark, "ROCK": _rock,
    "TERRAIN_4": _terrain, "GLASS": _glass, "WATER": _water, "VEHICLE_PAINT": _vehicle_paint,
    "SKIN": _skin, "FUR": _fur, "FABRIC": _fabric, "FEATHER": _feather, "SCALES": _scales,
    "FOLIAGE": _foliage,
}


def build(mat):
    """Build the preview for ``mat``'s official profile; returns the preview output or None."""
    fn = BUILDERS.get(mat.adm.shader)
    if mat.node_tree is None or (fn is None and not mat.adm.vertex_controls_enabled):
        return None
    g = _Graph(mat)
    bsdf = fn(g) if fn is not None else g.bsdf()
    _apply_vertex_controls(g, bsdf)
    return g.output(bsdf)


def apply_vertex_controls(mat, bsdf):
    """Apply the shared vertex-control preview to an already-built preview BSDF."""
    if mat.node_tree is None or not mat.adm.vertex_controls_enabled:
        return
    _apply_vertex_controls(_Graph(mat), bsdf)
