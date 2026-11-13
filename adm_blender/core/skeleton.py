"""Rig analysis against the skeleton profile registry (bpy-free).

The Blender add-on converts an armature into an abstract joint table in **ADM model space**::

    bones = {"Hips": {"parent": None, "head": (x, y, z)}, ...}
    assignments = [("Hips", "hips"), ...]          # (bone name, semantic role)

and feeds it to :func:`analyze_rig`.  Issues carry the offending bone, role, reason and – only when
the remedy is unambiguous – a fix identifier that the UI may offer as a one-click repair.
"""

import math
import re

from . import constants as K
from . import skeleton_profiles as SP

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"

# fix identifiers understood by the Blender UI
FIX_ROTATE_180 = "ROTATE_180"        # rotate the armature 180 deg about the up axis (faces +Z instead of -Z)
FIX_AUTO_MAP = "AUTO_MAP"            # run the auto mapper for missing roles (user reviews the result)
FIX_DROP_UNKNOWN = "DROP_UNKNOWN"    # clear a role string that does not exist in the profile
FIX_NORMALIZE_POLE = "NORMALIZE_POLE"
FIX_SORT_CHAINS = "SORT_CHAINS"


class RigIssue:
    __slots__ = ("severity", "code", "role", "bone", "message", "fix")

    def __init__(self, severity, code, message, role="", bone="", fix=""):
        self.severity, self.code, self.message = severity, code, message
        self.role, self.bone, self.fix = role, bone, fix

    def __repr__(self):
        return f"RigIssue({self.severity} {self.code} role={self.role!r} bone={self.bone!r}: {self.message})"


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _len(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _angle_deg(a, b):
    la, lb = _len(a), _len(b)
    if la < 1e-9 or lb < 1e-9:
        return 180.0
    c = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (la * lb)))
    return math.degrees(math.acos(c))


def _rot180(v):
    return (-v[0], v[1], -v[2])


def _nearest_mapped_ancestor(bone, bones, node_role):
    seen = set()
    a = bones[bone]["parent"]
    while a is not None and a not in seen:
        seen.add(a)
        if a in node_role:
            return node_role[a]
        a = bones.get(a, {}).get("parent")
    return None


def _expected_ancestor(role, defs, mapped):
    exp = defs[role]["parent"]
    while exp is not None and exp not in mapped:
        exp = defs[exp]["parent"]
    return exp


def pose_deviations(profile_id, bones, role_bone, rotate180=False):
    """Yield (check, angle_deg) for each reference pose check whose roles are mapped."""
    prof = SP.get(profile_id)
    if not prof or not prof.get("referencePose"):
        return []
    out = []
    for chk in prof["referencePose"]["checks"]:
        a, b = role_bone.get(chk["from"]), role_bone.get(chk["to"])
        if a is None or b is None or a not in bones or b not in bones:
            continue
        v = _sub(bones[b]["head"], bones[a]["head"])
        if rotate180:
            v = _rot180(v)
        out.append((chk, _angle_deg(v, chk["direction"])))
    return out


def facing_mirrored(profile_id, bones, role_bone):
    """True/False when every side pair indicates the rig faces +Z (left side on +X); None if undecidable."""
    prof = SP.get(profile_id)
    if not prof or not prof.get("referencePose"):
        return None
    votes = []
    for pair in prof["referencePose"]["sides"]:
        lb, rb = role_bone.get(pair["left"]), role_bone.get(pair["right"])
        if lb in bones and rb in bones:
            dx = bones[rb]["head"][0] - bones[lb]["head"][0]
            if abs(dx) > 1e-6:
                votes.append(dx < 0)
    if not votes:
        return None
    if all(votes):
        return True
    if not any(votes):
        return False
    return None


def analyze_rig(profile_id, bones, assignments, check_pose=True):
    """Validate a role mapping against a profile. Returns a list of :class:`RigIssue`."""
    issues = []
    add = lambda *a, **k: issues.append(RigIssue(*a, **k))  # noqa: E731
    prof = SP.get(profile_id)
    if prof is None:
        if SP.is_custom_id(profile_id):
            add(WARNING, "PROFILE_CUSTOM", f"'{profile_id}' is not a known profile: semantic retarget rules are "
                                           "undefined, only EXACT (rigId) binding is portable")
        else:
            add(ERROR, "PROFILE_ID", f"invalid or unversioned profile id {profile_id!r}")
        return issues
    if prof["status"] == SP.PROVISIONAL:
        add(WARNING, "PROFILE_PROVISIONAL", f"'{profile_id}' is a PROVISIONAL proposal, not a registered ADM 1.0 "
                                            "profile; files using it are not certified interoperable")
    defs = prof["roles"]

    role_bones = {}
    for bone, role in assignments:
        if not role:
            continue
        if bone not in bones:
            add(ERROR, "ROLE_BONE_MISSING", f"role '{role}' points to a missing bone", role=role, bone=bone)
            continue
        role_bones.setdefault(role, []).append(bone)
    if prof["status"] == SP.EXACT_ONLY:
        if role_bones:
            add(INFO, "ROLES_IGNORED", f"{profile_id} has no semantic roles; {len(role_bones)} role(s) are ignored")
        return issues

    for role, bl in sorted(role_bones.items()):
        if role not in defs:
            for b in bl:
                add(ERROR, "ROLE_UNKNOWN", f"'{role}' is not a role of {profile_id}", role=role, bone=b,
                    fix=FIX_DROP_UNKNOWN)
        if len(bl) > 1:
            add(ERROR, "ROLE_DUPLICATE", f"role '{role}' is assigned to {len(bl)} bones: {', '.join(sorted(bl))}",
                role=role, bone=sorted(bl)[0])
    role_bone = {r: bl[0] for r, bl in role_bones.items() if r in defs and len(bl) == 1}
    node_role = {b: r for r, b in role_bone.items()}
    mapped = set(role_bone)

    for role, d in defs.items():
        if d["required"] and role not in role_bones:
            add(ERROR, "ROLE_MISSING", f"required role '{role}' is not mapped", role=role, fix=FIX_AUTO_MAP)
    for role in sorted(mapped):
        d = defs[role]
        if d.get("needsParent") and d["parent"] not in mapped:
            add(ERROR, "ROLE_NEEDS_PARENT", f"'{role}' requires its parent role '{d['parent']}' to be mapped",
                role=role, bone=role_bone[role])
        actual = _nearest_mapped_ancestor(role_bone[role], bones, node_role)
        expected = _expected_ancestor(role, defs, mapped)
        if actual != expected:
            add(ERROR, "ROLE_HIERARCHY", f"nearest mapped ancestor of '{role}' is {actual!r}, profile requires "
                                         f"{expected!r}", role=role, bone=role_bone[role])
    extra = [b for b in bones if b not in node_role]
    if extra:
        add(INFO, "EXTRA_BONES", f"{len(extra)} unmapped helper/extra bone(s) keep their rest pose (allowed)")

    if check_pose and prof.get("referencePose"):
        rp = prof["referencePose"]
        tol = rp["toleranceDeg"]
        mirrored = facing_mirrored(profile_id, bones, role_bone)
        devs = pose_deviations(profile_id, bones, role_bone)
        bad = [(c, a) for c, a in devs if a > tol]
        if mirrored:
            fixed = [(c, a) for c, a in pose_deviations(profile_id, bones, role_bone, rotate180=True) if a > tol]
            add(ERROR, "REFERENCE_FACING", "rig faces +Z with its left side on +X; ADM reference pose faces -Z "
                                           "(+X = character's right). Rotate 180 deg about the up axis",
                role=prof["referencePose"]["sides"][0]["left"],
                bone=role_bone.get(prof["referencePose"]["sides"][0]["left"], ""),
                fix=FIX_ROTATE_180 if not fixed else "")
            bad = fixed
        for chk, ang in bad:
            add(ERROR, "REFERENCE_POSE", f"{chk['from']}->{chk['to']} deviates {ang:.1f} deg from the "
                                         f"'{rp['name']}' reference direction {chk['direction']} "
                                         f"(maximum deviation {tol:g} deg)",
                role=chk["from"], bone=role_bone.get(chk["from"], ""))
    return issues


def has_errors(issues):
    return any(i.severity == ERROR for i in issues)


# ---------------------------------------------------------------------------------------------
# IK chain checks (ADM-IK-1, §20) on the abstract joint table
# ---------------------------------------------------------------------------------------------
IK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def analyze_ik(chains, bones, profile_id=None, role_of=None):
    """chains: list of dicts {id, root, mid, end, pole(ADM model space), weight}."""
    issues = []
    add = lambda *a, **k: issues.append(RigIssue(*a, **k))  # noqa: E731
    seen_ids, used = set(), {}
    for ch in chains:
        cid = ch.get("id", "")
        if not cid or not IK_ID_RE.match(cid):
            add(ERROR, "IK_ID", f"chain id {cid!r} is empty or not an identifier")
        if cid in seen_ids:
            add(ERROR, "IK_ID_DUPLICATE", f"duplicate chain id {cid!r}")
        seen_ids.add(cid)
        names = [ch.get(k, "") for k in ("root", "mid", "end")]
        if not all(names):
            add(ERROR, "IK_INCOMPLETE", f"chain {cid!r}: root, mid and end must all be set",
                bone=next((n for n in names if n), ""))
            continue
        missing = [n for n in names if n not in bones]
        if missing:
            add(ERROR, "IK_BONE_MISSING", f"chain {cid!r}: bone(s) not in armature: {', '.join(missing)}",
                bone=missing[0])
            continue
        if len(set(names)) != 3:
            add(ERROR, "IK_DUPLICATE_JOINT", f"chain {cid!r}: root/mid/end must be distinct", bone=names[0])
            continue
        root, mid, end = names
        if bones[mid]["parent"] != root or bones[end]["parent"] != mid:
            add(ERROR, "IK_NOT_DIRECT", f"chain {cid!r}: ADM-IK-1 requires direct parent-child links "
                                        f"root->mid->end", bone=end)
        A, B, C = (bones[n]["head"] for n in names)
        if _len(_sub(B, A)) <= 1e-6 or _len(_sub(C, B)) <= 1e-6:
            add(ERROR, "IK_ZERO_LENGTH", f"chain {cid!r}: segment length must be > 1e-6 m", bone=mid)
        pole = tuple(ch.get("pole", (0, 0, 0)))
        pl = _len(pole)
        if pl < 1e-9:
            add(ERROR, "IK_POLE", f"chain {cid!r}: pole must be a non-zero direction", bone=mid)
        else:
            if abs(pl - 1.0) > 1e-4:
                add(WARNING, "IK_POLE_UNIT", f"chain {cid!r}: pole is normalized on export", fix=FIX_NORMALIZE_POLE)
            u = _sub(C, A)
            if _len(u) > 1e-9 and (_angle_deg(pole, u) < 1e-3 or _angle_deg(pole, u) > 180 - 1e-3):
                add(ERROR, "IK_POLE_COLLINEAR", f"chain {cid!r}: pole is collinear with root->end", bone=mid)
        w = ch.get("weight", 1.0)
        if not (0.0 <= w <= 1.0):
            add(ERROR, "IK_WEIGHT", f"chain {cid!r}: weight must be in [0,1]")
        for n in names:
            if n in used:
                add(ERROR, "IK_OVERLAP", f"chains {used[n]!r} and {cid!r} share bone '{n}' (forbidden in ADM-IK-1)",
                    bone=n)
            used[n] = cid
        if profile_id and role_of:
            tmpl = {t["id"]: t for t in SP.ik_templates(profile_id)}
            t = tmpl.get(cid)
            if t is not None:
                for key in ("root", "mid", "end"):
                    if role_of.get(ch[key]) != t[key]:
                        add(WARNING, "IK_TEMPLATE_ROLE", f"chain {cid!r}: {key} bone '{ch[key]}' has role "
                                                         f"{role_of.get(ch[key])!r}, profile template expects "
                                                         f"'{t[key]}'", role=t[key], bone=ch[key])
    return issues


# ---------------------------------------------------------------------------------------------
# Profile detection (quadruped name heuristics; the humanoid mapper is supplied by the caller)
# ---------------------------------------------------------------------------------------------
_Q_AXIAL = {"pelvis": "hips", "hips": "hips", "hip": "hips", "root": None, "spine": "spine", "spine1": "spine",
            "spine01": "spine", "back": "spine", "chest": "chest", "spine2": "chest", "spine02": "chest",
            "ribcage": "chest", "thorax": "chest", "neck": "neck", "neck1": "neck", "neck01": "neck",
            "head": "head", "skull": "head", "jaw": "jaw", "eye": "Eye", "ear": "Ear"}
_Q_SEG = {"scapula": "Shoulder", "shoulder": "Shoulder", "clavicle": "Shoulder",
          "humerus": "UpperLeg", "upperarm": "UpperLeg", "thigh": "UpperLeg", "femur": "UpperLeg",
          "upperleg": "UpperLeg", "upleg": "UpperLeg",
          "forearm": "LowerLeg", "lowerarm": "LowerLeg", "radius": "LowerLeg", "shin": "LowerLeg",
          "tibia": "LowerLeg", "calf": "LowerLeg", "lowerleg": "LowerLeg", "gaskin": "LowerLeg",
          "hand": "Foot", "paw": "Foot", "foot": "Foot", "metacarpus": "Foot", "metatarsus": "Foot",
          "cannon": "Foot", "carpal": "Foot", "hock": "Foot", "wrist": "Foot", "ankle": "Foot",
          "toe": "Toes", "toes": "Toes", "digit": "Toes", "digits": "Toes", "phalanges": "Toes", "finger": "Toes",
          "pastern": "Pastern", "hoof": "Hoof"}
_FRONT = {"front", "fore", "f", "arm", "frontleg", "foreleg"}
_HIND = {"hind", "rear", "back", "h", "b", "hindleg", "backleg"}


def _tokens(name):
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name.strip()).lower()
    return [t for t in re.split(r"[^a-z0-9]+", n) if t]


def _split_digits(tokens):
    out = []
    for t in tokens:
        m = re.match(r"^([a-z]+)(\d+)$", t)
        out.extend([m.group(1), m.group(2)] if m and m.group(1) not in _Q_AXIAL else [t])
    return out


def _depth(bones, b):
    d, seen = 0, set()
    while bones[b]["parent"] is not None and b not in seen:
        seen.add(b)
        b = bones[b]["parent"]
        d += 1
    return d


def auto_map_quadruped(bones, profile_id="animal.generic_quadruped.v1"):
    """Suggest quadruped roles from bone names and hierarchy order. Returns {bone: role}."""
    defs = SP.roles(profile_id)
    result, used = {}, set()
    limbs, tail = {}, []
    for b in sorted(bones, key=lambda x: (_depth(bones, x), x)):
        toks = _split_digits(_tokens(b))
        toks = [t for t in toks if t not in ("def", "org", "mch", "bone", "jnt", "j", "bn", "armature")]
        side = None
        for t in toks:
            if t in ("l", "left", "lf", "lh"):
                side = "left"
            elif t in ("r", "right", "rt", "rf", "rh"):
                side = "right"
        if "tail" in toks:
            tail.append(b)
            continue
        limb = None
        if side:
            if any(t in _FRONT for t in toks) or ("lf" in toks or "rf" in toks):
                limb = "Front"
            elif any(t in _HIND for t in toks) or ("lh" in toks or "rh" in toks):
                limb = "Hind"
        seg = next((_Q_SEG[t] for t in toks if t in _Q_SEG), None)
        if side and limb is None and seg in ("Shoulder",):
            limb = "Front"
        if side and limb is None and any(t in ("thigh", "femur", "hock", "gaskin") for t in toks):
            limb = "Hind"
        if side and limb:
            limbs.setdefault((side, limb), []).append((b, seg))
            continue
        axial = next((_Q_AXIAL[t] for t in toks if t in _Q_AXIAL), None)
        if axial in ("Eye", "Ear"):
            role = side + axial if side else None
        else:
            role = axial
            if role == "spine" and any(t in ("2", "02") for t in toks):
                role = "chest"
        if role and role in defs and role not in used:
            result[b] = role
            used.add(role)
    for (side, limb), items in limbs.items():
        order = [s for s in ("Shoulder", "UpperLeg", "LowerLeg", "Foot", "Toes", "Pastern", "Hoof")
                 if side + limb + s in defs]
        if limb == "Hind":
            order = [s for s in order if s != "Shoulder"]
        named = [(b, s) for b, s in items if s]
        if len(named) == len(items):
            for b, s in items:
                role = side + limb + s
                if role in defs and role not in used:
                    result[b] = role
                    used.add(role)
        else:
            if order and order[0] == "Shoulder" and len(items) < len(order):
                order = order[1:]
            for (b, _s), s in zip(items, order):
                role = side + limb + s
                if role in defs and role not in used:
                    result[b] = role
                    used.add(role)
    for b, role in zip(tail[:3], ("tailBase", "tailMid", "tailTip")):
        if role not in used:
            result[b] = role
            used.add(role)
    return result


def detect_profile(bones, humanoid_mapper=None):
    """Return (profile_id, {bone: role}, reason). ``humanoid_mapper(names)->{bone: role}`` is optional."""
    candidates = []
    if humanoid_mapper is not None:
        hm = humanoid_mapper(list(bones))
        missing = [r for r in SP.required_roles(SP.HUMANOID) if r not in hm.values()]
        candidates.append((SP.HUMANOID, hm, missing))
    qprof = "animal.generic_quadruped.v1"
    qm = auto_map_quadruped(bones, qprof)
    em = auto_map_quadruped(bones, "animal.equine.v1")
    if any(r.endswith(("Pastern", "Hoof")) for r in em.values()):
        qprof, qm = "animal.equine.v1", em
    candidates.append((qprof, qm, [r for r in SP.required_roles(qprof) if r not in qm.values()]))
    complete = [c for c in candidates if not c[2]]
    if len(complete) > 1:
        # both name sets work: decide by spine orientation (vertical -> humanoid)
        hm = complete[0][1]
        rb = {r: b for b, r in hm.items()}
        if "hips" in rb and "head" in rb:
            v = _sub(bones[rb["head"]]["head"], bones[rb["hips"]]["head"])
            if abs(v[1]) < math.hypot(v[0], v[2]):
                complete = complete[1:]
    if complete:
        pid, mapping, _ = complete[0]
        return pid, mapping, "all required roles found"
    best = min(candidates, key=lambda c: len(c[2]))
    if len(best[1]) < 3:
        return SP.GENERIC, {}, "no profile recognised; use generic.v1 (exact rig binding only)"
    return best[0], best[1], "incomplete: missing " + ", ".join(best[2])


# ---------------------------------------------------------------------------------------------
# Animation library compatibility (§11, §13, §16)
# ---------------------------------------------------------------------------------------------
EXACT, SEMANTIC, PROVISIONAL_SEMANTIC, MODEL_ANY, INCOMPATIBLE = (
    "EXACT", "SEMANTIC", "PROVISIONAL_SEMANTIC", "MODEL_ANY", "INCOMPATIBLE")


def library_compatibility(library, rig_profile, rig_roles, exact_match=None, rig_issues=(), channel_roles=()):
    """Decide how a library binds to a rig.

    library       -- the ``library`` object of an .adm_anim file
    rig_profile   -- profile id declared by the target armature ('' when none)
    rig_roles     -- set of roles mapped on the target
    exact_match   -- True/False when the rigId comparison was performed, None when unknown
    rig_issues    -- RigIssue list of the target (errors make SEMANTIC binding INCOMPATIBLE)
    channel_roles -- roles referenced by bone channels of the clips
    Returns (level, [reasons]).
    """
    reasons = []
    binding = library.get("binding")
    target = library.get("targetProfile", "")
    if target == K.MODEL_ANY_PROFILE:
        return MODEL_ANY, ["model.any.v1 library: only morph/expression/material channels, no bones"]
    if binding == "EXACT":
        if not library.get("rigId"):
            return INCOMPATIBLE, ["EXACT library without rigId"]
        if exact_match is True:
            return EXACT, ["rigId matches the target rig"]
        return INCOMPATIBLE, ["rigId does not match the target rig" if exact_match is False
                              else "target rig fingerprint unavailable"]
    if binding != "SEMANTIC":
        return INCOMPATIBLE, [f"unknown binding {binding!r}"]
    if target != rig_profile:
        prof = SP.get(target)
        mapped = prof and rig_profile in prof.get("retargetMaps", {})
        if not mapped:
            return INCOMPATIBLE, [f"library targets '{target}' but the rig declares '{rig_profile or 'no profile'}'; "
                                  "cross-profile retarget requires an approved explicit mapping (none registered)"]
    st = SP.status(target)
    if st is None:
        return INCOMPATIBLE, [f"unknown profile '{target}': retarget rules are undefined"]
    if st == SP.EXACT_ONLY:
        return INCOMPATIBLE, [f"{target} supports only EXACT binding"]
    missing = [r for r in SP.required_roles(target) if r not in rig_roles]
    if missing:
        return INCOMPATIBLE, ["target misses required roles: " + ", ".join(missing)]
    errs = [i for i in rig_issues if i.severity == ERROR]
    if errs:
        return INCOMPATIBLE, ["target rig fails validation: " + "; ".join(f"{i.code} {i.role or i.bone}"
                                                                         for i in errs[:4])]
    absent = sorted(set(channel_roles) - set(rig_roles))
    if absent:
        reasons.append("optional roles absent on target (channels skipped): " + ", ".join(absent))
    if st == SP.PROVISIONAL:
        return PROVISIONAL_SEMANTIC, reasons + [f"'{target}' is PROVISIONAL: same-profile retarget works in this "
                                                "add-on but is not certified interoperable"]
    return SEMANTIC, reasons + ["required roles present and profile ids match"]
