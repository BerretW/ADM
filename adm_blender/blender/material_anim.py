"""Material animation (§15 pbrParameter / shaderParameter, §18.1) <-> Blender actions.

A clip action animates a material through two action slots named after the material:

* ``MATERIAL`` slot -> ``Material.adm`` properties (``adm.layer_factor``, ``adm.params["x"].value_*``,
  ``adm.alpha_cutoff``),
* ``NODETREE`` slot -> the material's Principled BSDF node inputs (portable PBR fallback fields).
"""

import re

import bpy

from ..core import constants as K
from .materials import ALPHA_CLIP_NODE, _color_inputs, _from, principled_of, trace

PARAM_PATH_RE = re.compile(r'^adm\.params\[(?:"(.+)"|(\d+))\]\.(value_f|value_vec)$')
VERTEX_CONTROL_PROP_BY_PARAM = {
    "tintOffset": "tint_offset",
    "normalMultiplier": "normal_multiplier",
    "reflectionMultiplier": "reflection_multiplier",
    "wetnessOffset": "wetness_offset",
}


def param_name_from_path(mat, data_path):
    """Shader parameter name addressed by an F-Curve path (Blender stores collection items by index)."""
    m = PARAM_PATH_RE.match(data_path)
    if not m:
        return None
    if m.group(1) is not None:
        return m.group(1)
    i = int(m.group(2))
    return mat.adm.params[i].name if i < len(mat.adm.params) else None


# ------------------------------------------------------------------------------------------------
# slots
# ------------------------------------------------------------------------------------------------
def find_slot(action, id_type, idb):
    if action is None or idb is None:
        return None
    for s in action.slots:
        if s.target_id_type != id_type:
            continue
        try:
            if idb in s.users():
                return s
        except Exception:
            pass
    name = idb.name if id_type == "MATERIAL" else getattr(idb, "_adm_owner_name", None)
    for s in action.slots:
        if s.target_id_type == id_type and name and s.name_display == name:
            return s
    return None


def material_slots(action, mat):
    """(material slot, node tree slot) of ``mat`` inside ``action``; either may be None."""
    if action is None:
        return None, None
    ms = find_slot(action, "MATERIAL", mat)
    ns = None
    if mat.node_tree is not None:
        for s in action.slots:
            if s.target_id_type != "NODETREE":
                continue
            try:
                if mat.node_tree in s.users():
                    ns = s
                    break
            except Exception:
                pass
        if ns is None:
            ns = next((s for s in action.slots if s.target_id_type == "NODETREE" and s.name_display == mat.name),
                      None)
    return ms, ns


def ensure_material_slots(action, mat, node_tree=True):
    ms, ns = material_slots(action, mat)
    if ms is None:
        ms = action.slots.new(id_type="MATERIAL", name=mat.name)
    if node_tree and ns is None and mat.node_tree is not None:
        ns = action.slots.new(id_type="NODETREE", name=mat.name)
    return ms, ns


def bind_material(mat, action, assign=None):
    """Assign ``action`` with the material's slots to the material and its node tree."""
    ms, ns = ensure_material_slots(action, mat)
    for idb, slot in ((mat, ms), (mat.node_tree, ns)):
        if idb is None or slot is None:
            continue
        if assign is not None:
            assign.assign(idb, action, slot)
        else:
            ad = idb.animation_data or idb.animation_data_create()
            ad.action = action
            ad.action_slot = slot
    return ms, ns


def animated_materials(action):
    """Materials with an animationId that own a slot in ``action``."""
    out = []
    if action is None:
        return out
    for mat in bpy.data.materials:
        if not mat.adm.animation_id.strip():
            continue
        ms, ns = material_slots(action, mat)
        if ms is not None or ns is not None:
            out.append((mat, ms, ns))
    return sorted(out, key=lambda x: x[0].adm.animation_id)


# ------------------------------------------------------------------------------------------------
# PBR sampling (export) - mirrors MaterialExporter factor logic
# ------------------------------------------------------------------------------------------------
def _scalar(f):
    return f[0] if isinstance(f, list) else f


def _normal_map_node(bsdf):
    s = _from(bsdf.inputs["Normal"])
    if s is not None and s.node.type == "NORMAL_MAP":
        return s.node
    return None


def pbr_values(mat):
    """Current (frame-evaluated) PBR fallback factor values of ``mat``."""
    bsdf = principled_of(mat)
    if bsdf is None:
        return {"baseColorFactor": list(mat.diffuse_color), "metallicFactor": mat.metallic,
                "roughnessFactor": mat.roughness, "emissiveFactor": [0.0, 0.0, 0.0],
                "alphaCutoff": mat.adm.alpha_cutoff}
    base = trace(bsdf.inputs["Base Color"])
    factor = list(bsdf.inputs["Base Color"].default_value[:3])
    if base is not None and base["node"] is not None:
        factor = base["factor"] if isinstance(base["factor"], list) else [base["factor"]] * 3
    alpha = float(bsdf.inputs["Alpha"].default_value)
    alpha_tr = trace(bsdf.inputs["Alpha"])
    clip = None
    if alpha_tr is not None:
        alpha = float(alpha_tr["factor"]) if not isinstance(alpha_tr["factor"], list) else 1.0
        clip = alpha_tr["clip"]
    mt = trace(bsdf.inputs["Metallic"])
    rt = trace(bsdf.inputs["Roughness"])
    metallic = float(bsdf.inputs["Metallic"].default_value) if mt is None else float(_scalar(mt["factor"]))
    rough = float(bsdf.inputs["Roughness"].default_value) if rt is None else float(_scalar(rt["factor"]))
    strength = float(bsdf.inputs["Emission Strength"].default_value)
    et = trace(bsdf.inputs["Emission Color"])
    ecol = list(bsdf.inputs["Emission Color"].default_value[:3])
    if et is not None and et["node"] is not None:
        ecol = et["factor"] if isinstance(et["factor"], list) else [et["factor"]] * 3
    out = {
        "baseColorFactor": [float(x) for x in factor] + [alpha],
        "metallicFactor": metallic,
        "roughnessFactor": rough,
        "emissiveFactor": [max(0.0, float(c) * strength) for c in ecol],
        "alphaCutoff": clip if (clip is not None and mat.adm.alpha_mode == "AUTO") else mat.adm.alpha_cutoff,
    }
    nm = _normal_map_node(bsdf)
    if nm is not None:
        out["normalScale"] = max(0.0, float(nm.inputs["Strength"].default_value))
    return out


def shader_param_values(mat, registry):
    """name -> current numeric value list for every animatable parameter of the material's shader."""
    a = mat.adm
    key = a.shader_key()
    params = registry.get(key, {})
    out = {}
    for name, prm in params.items():
        if not prm.get("animatable") or prm.get("type") not in K.SHADER_NUMERIC_DIMS:
            continue
        n = K.SHADER_NUMERIC_DIMS[prm["type"]]
        if key == K.SHADER_LAYERED and name == "layer_factor":
            out[name] = [a.layer_factor]
            continue
        v = a.params.get(name)
        if v is None or not v.use:
            d = prm.get("default")
            out[name] = [float(d)] if n == 1 else [float(x) for x in d]
        else:
            out[name] = [v.value_f] if n == 1 else list(v.value_vec[:n])
    if a.vertex_controls_enabled:
        for name, prop in VERTEX_CONTROL_PROP_BY_PARAM.items():
            out[name] = [float(getattr(a, prop))]
    return out


def animated_shader_params(mat, fcurves):
    names = set()
    for fc in fcurves:
        if fc.data_path == "adm.layer_factor":
            names.add("layer_factor")
        for name, prop in VERTEX_CONTROL_PROP_BY_PARAM.items():
            if fc.data_path == f"adm.{prop}":
                names.add(name)
        name = param_name_from_path(mat, fc.data_path)
        if name:
            names.add(name)
    return names


# ------------------------------------------------------------------------------------------------
# import: resolve writable sockets/properties for a PBR parameter
# ------------------------------------------------------------------------------------------------
def _socket_path(sock):
    return sock.path_from_id() + ".default_value"


def _factor_socket(nt, target, color):
    """Socket holding the constant factor feeding ``target`` (inserting a multiply node if needed)."""
    if not target.is_linked:
        return target
    s = _from(target)
    walk = s
    guard = 0
    while walk is not None and guard < 8:
        guard += 1
        n = walk.node
        if n.type == "MATH" and n.operation in ("GREATER_THAN", "ROUND"):
            walk = _from(n.inputs[0])
            continue
        if n.type == "MATH" and n.operation == "MULTIPLY":
            a, b = n.inputs[0], n.inputs[1]
            if a.is_linked and not b.is_linked:
                return b
            if b.is_linked and not a.is_linked:
                return a
        if n.type == "MIX" and getattr(n, "data_type", "") == "RGBA" and n.blend_type == "MULTIPLY":
            cols = _color_inputs(n)
            const = [c for c in cols if not c.is_linked]
            if len(const) == 1:
                return const[0]
        break
    # insert a multiply node right before the target socket
    if color:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        mix.location = (target.node.location.x - 220, target.node.location.y - 40)
        ca, cb = _color_inputs(mix)[:2]
        nt.links.new(s, ca)
        cb.default_value = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(next(o for o in mix.outputs if o.type == "RGBA"), target)
        return cb
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.location = (target.node.location.x - 220, target.node.location.y - 40)
    nt.links.new(s, mul.inputs[0])
    mul.inputs[1].default_value = 1.0
    nt.links.new(mul.outputs[0], target)
    return mul.inputs[1]


def pbr_write_targets(mat, param):
    """List of ``(id_kind, data_path, array_index, component, scale)`` receiving ADM value[component]*scale.

    Returns None when the material cannot express the parameter.
    """
    if param == "alphaCutoff":
        out = [("MATERIAL", "adm.alpha_cutoff", 0, 0, 1.0)]
        if mat.node_tree is not None:
            node = mat.node_tree.nodes.get(ALPHA_CLIP_NODE)
            if node is not None:
                out.append(("NODETREE", _socket_path(node.inputs[1]), 0, 0, 1.0))
        return out
    bsdf = principled_of(mat)
    if bsdf is None:
        return None
    nt = mat.node_tree
    if param == "baseColorFactor":
        col = _factor_socket(nt, bsdf.inputs["Base Color"], True)
        alpha = _factor_socket(nt, bsdf.inputs["Alpha"], False)
        return [("NODETREE", _socket_path(col), i, i, 1.0) for i in range(3)] + \
               [("NODETREE", _socket_path(alpha), 0, 3, 1.0)]
    if param in ("metallicFactor", "roughnessFactor"):
        sock = _factor_socket(nt, bsdf.inputs["Metallic" if param == "metallicFactor" else "Roughness"], False)
        return [("NODETREE", _socket_path(sock), 0, 0, 1.0)]
    if param == "emissiveFactor":
        st = bsdf.inputs["Emission Strength"]
        if st.is_linked:
            return None
        if st.default_value <= 0.0:
            st.default_value = 1.0
        col = _factor_socket(nt, bsdf.inputs["Emission Color"], True)
        return [("NODETREE", _socket_path(col), i, i, 1.0 / st.default_value) for i in range(3)]
    if param == "normalScale":
        nm = _normal_map_node(bsdf)
        if nm is None or nm.inputs["Strength"].is_linked:
            return None
        return [("NODETREE", _socket_path(nm.inputs["Strength"]), 0, 0, 1.0)]
    return None


def shader_write_targets(mat, param, n):
    """``(data_path, array_index, component)`` for a shader parameter on ``Material.adm``."""
    a = mat.adm
    prop = VERTEX_CONTROL_PROP_BY_PARAM.get(param)
    if prop is not None:
        if not a.vertex_controls_enabled:
            return None
        return [(f"adm.{prop}", 0, 0)]
    if a.shader == "LAYERED" and param == "layer_factor":
        return [("adm.layer_factor", 0, 0)]
    v = a.params.get(param)
    if v is None:
        v = a.params.add()
        v.name = param
    v.use = True
    if n == 1:
        return [(f'adm.params["{param}"].value_f', 0, 0)]
    return [(f'adm.params["{param}"].value_vec', i, i) for i in range(n)]
