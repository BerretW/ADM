"""Bone-name -> humanoid.vrm1 role suggestions for common rigs (Mixamo, Rigify, UE, VRM/VRoid, CC, generic).

Used only by the explicit "Auto-Map Roles" tool; exporters never guess roles.
"""

import re

from . import constants as K

_PREFIXES = ("mixamorig", "def", "org", "mch", "jbipc", "jbipl", "jbipr", "jbip", "bip01", "bip001", "bip",
             "cc_base_", "ccbase", "rl", "valvebiped", "bone", "armature")

_SIDE_PATTERNS = [
    (re.compile(r"^(left|l)(?=[a-z0-9])"), "left"), (re.compile(r"^(right|r)(?=[a-z0-9])"), "right"),
    (re.compile(r"(left|l)$"), "left"), (re.compile(r"(right|r)$"), "right"),
]

# base name (normalised, side removed) -> role stem (without left/right)
_BASE = {
    "hips": "hips", "hip": "hips", "pelvis": "hips", "spine": "spine", "spine0": "hips",
    "spine1": "spine", "spine01": "spine", "spine001": "spine", "abdomen": "spine", "waist": "spine",
    "spine2": "chest", "spine02": "chest", "spine002": "chest", "chest": "chest", "torso": "chest",
    "spine3": "upperChest", "spine03": "upperChest", "spine003": "upperChest", "upperchest": "upperChest",
    "chestupper": "upperChest",
    "neck": "neck", "neck1": "neck", "neck01": "neck", "spine004": "neck", "head": "head", "spine006": "head",
    "eye": "Eye", "jaw": "jaw",
    "shoulder": "Shoulder", "clavicle": "Shoulder", "collar": "Shoulder",
    "upperarm": "UpperArm", "arm": "UpperArm", "uparm": "UpperArm",
    "lowerarm": "LowerArm", "forearm": "LowerArm", "elbow": "LowerArm",
    "hand": "Hand", "wrist": "Hand",
    "upperleg": "UpperLeg", "upleg": "UpperLeg", "thigh": "UpperLeg", "leg1": "UpperLeg",
    "lowerleg": "LowerLeg", "leg": "LowerLeg", "shin": "LowerLeg", "calf": "LowerLeg", "knee": "LowerLeg",
    "foot": "Foot", "ankle": "Foot", "toes": "Toes", "toe": "Toes", "toebase": "Toes", "ball": "Toes",
}

_FINGERS = {"thumb": "Thumb", "index": "Index", "middle": "Middle", "ring": "Ring", "little": "Little",
            "pinky": "Little", "pinkie": "Little", "findex": "Index", "fmiddle": "Middle", "fring": "Ring",
            "fpinky": "Little"}
_THUMB = ("Metacarpal", "Proximal", "Distal")
_FINGER = ("Proximal", "Intermediate", "Distal")

_ROLE_LOWER = {r.lower(): r for r in K.VRM1_ROLES}


def _normalise(name):
    n = name.strip()
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", n)  # camelCase -> camel_case
    n = n.lower()
    n = n.replace("mixamorig:", "")
    tokens = [t for t in re.split(r"[^a-z0-9]+", n) if t]
    side = None
    out = []
    for t in tokens:
        if t in ("l", "left", "lft"):
            side = "left"
            continue
        if t in ("r", "right", "rgt", "rt"):
            side = "right"
            continue
        out.append(t)
    while out and out[0] in _PREFIXES:
        out.pop(0)
    joined = "".join(out)
    for pre in ("jbipc", "jbipl", "jbipr", "jbip", "mixamorig", "def", "ccbase"):
        if joined.startswith(pre) and len(joined) > len(pre):
            if pre == "jbipl":
                side = "left"
            elif pre == "jbipr":
                side = "right"
            joined = joined[len(pre):]
    if side is None and not _known(joined):
        for pat, s in _SIDE_PATTERNS:
            m = pat.search(joined)
            rest = joined[:m.start()] + joined[m.end():] if m else ""
            if m and len(rest) >= 2 and _known(rest):
                side = s
                joined = rest
                break
    return joined, side


_FINGER_RE = re.compile(r"^(?:hand)?(thumb|index|middle|ring|little|pinky|pinkie|findex|fmiddle|fring|fpinky)"
                        r"(?:finger)?0*([1-4])?$")


def _known(base):
    return base in _BASE or bool(_FINGER_RE.match(base))


def suggest_role(name, chain_index=None):
    """Return a humanoid.vrm1 role for a bone name, or None."""
    direct = _ROLE_LOWER.get(name.strip().lower())
    if direct:
        return direct
    base, side = _normalise(name)
    if not base:
        return None
    # fingers: thumb1/thumb_01/thumb.01 / f_index.01 ...
    m = _FINGER_RE.match(base)
    if m and side:
        finger = _FINGERS[m.group(1)]
        i = int(m.group(2) or 1) - 1
        names = _THUMB if finger == "Thumb" else _FINGER
        if 0 <= i < 3:
            return side + finger + names[i]
        return None
    stem = _BASE.get(base)
    if stem is None:
        return None
    if stem[0].isupper():
        return side + stem if side else None
    return stem if side is None else None


def auto_map(bone_names, parent_of=None):
    """Map a list of bone names to unique roles. Returns {bone_name: role}."""
    result = {}
    used = set()
    bases = {name: _normalise(name)[0] for name in bone_names}
    # Mixamo / CC style: Spine, Spine1, Spine2 -> spine, chest, upperChest
    shift = "spine" in bases.values() and any(b in ("spine1", "spine2") for b in bases.values())
    for name in bone_names:
        role = suggest_role(name)
        if shift and bases[name] in ("spine1", "spine2", "spine3"):
            role = {"spine1": "chest", "spine2": "upperChest", "spine3": None}[bases[name]]
        if role is None or role in used:
            continue
        result[name] = role
        used.add(role)
    # Rigify DEF-spine chain: spine, spine.001 ... — remap by order when the classic names are used
    spine = sorted(n for n in bone_names if re.match(r"^(DEF|ORG)[-_]spine(\.\d{3})?$", n))
    if spine:
        order = ["hips", "spine", "chest", "upperChest", "neck", "neck", "head"]
        for n in list(result):
            if n in spine:
                used.discard(result.pop(n))
        if len(spine) == 6:
            order = ["hips", "spine", "chest", "neck", "neck", "head"]
        for i, n in enumerate(spine):
            if i < len(order):
                role = order[i]
                if role not in used:
                    result[n] = role
                    used.add(role)
    return result
