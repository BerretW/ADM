"""ADM Skeleton Profile Registry (data-driven, bpy-free).

Each profile is a plain dictionary so the very same data can be published as
``adm-standard/profiles/skeleton-profiles.json`` (see :func:`registry_json`) and consumed by the
Blender add-on, the validator and the tests.

Status values
-------------
``NORMATIVE``   the role list/hierarchy is normative ADM 1.0 Draft 0.4 data (``humanoid.vrm1``).
``EXACT_ONLY``  no semantic roles; only EXACT (rigId) binding is possible (``generic.v1``).
``PROVISIONAL`` proposed data that is NOT a registered ADM profile.  Tools may author, map and
                validate against it, but MUST NOT claim interoperable SEMANTIC compatibility.

Directions (``referencePose.checks``, IK poles, ...) are in ADM model space: +Y up, +X is the
character's right, forward is -Z (ADM 1.0 §2, §11).
"""

import copy
import json
import re

from . import constants as K

REGISTRY_VERSION = "0.4-P2"

NORMATIVE = "NORMATIVE"
EXACT_ONLY = "EXACT_ONLY"
PROVISIONAL = "PROVISIONAL"

# Advisory angular tolerance for reference pose direction checks (SPEC_GAP-REFPOSE-TOL).
DEFAULT_POSE_TOLERANCE_DEG = 25.0

LEFT, RIGHT, UP, DOWN, FORWARD, BACK = (-1, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, -1), (0, 0, 1)


def _role(parent, required=False, needs_parent=False, description=""):
    r = {"parent": parent, "required": bool(required)}
    if needs_parent:
        r["needsParent"] = True
    if description:
        r["description"] = description
    return r


# ---------------------------------------------------------------------------------------------
# humanoid.vrm1 — VRM 1.0 humanoid (role names, parents, required set are taken from VRM 1.0)
# ---------------------------------------------------------------------------------------------
# VRM 1.0 "needs parent bone" rules: the direct VRM parent role MUST be mapped too.
VRM1_NEEDS_PARENT = {"upperChest"}
for _s in ("left", "right"):
    VRM1_NEEDS_PARENT.update({_s + "ThumbProximal", _s + "ThumbDistal"})
    for _f in ("Index", "Middle", "Ring", "Little"):
        VRM1_NEEDS_PARENT.update({_s + _f + "Intermediate", _s + _f + "Distal"})
del _s, _f


def _humanoid():
    roles = {r: _role(p, r in K.VRM1_REQUIRED, r in VRM1_NEEDS_PARENT) for r, p in K.VRM1_PARENT.items()}
    checks = []
    for side, d in (("left", LEFT), ("right", RIGHT)):
        checks += [
            {"from": side + "UpperArm", "to": side + "LowerArm", "direction": list(d)},
            {"from": side + "LowerArm", "to": side + "Hand", "direction": list(d)},
            {"from": side + "UpperLeg", "to": side + "LowerLeg", "direction": list(DOWN)},
            {"from": side + "LowerLeg", "to": side + "Foot", "direction": list(DOWN)},
        ]
    checks += [{"from": "hips", "to": "head", "direction": list(UP)}]
    ik = []
    for side in ("left", "right"):
        # elbows bend backward (+Z), knees bend forward (-Z)
        ik.append({"id": side + "Arm", "root": side + "UpperArm", "mid": side + "LowerArm", "end": side + "Hand",
                   "pole": list(BACK)})
        ik.append({"id": side + "Leg", "root": side + "UpperLeg", "mid": side + "LowerLeg", "end": side + "Foot",
                   "pole": list(FORWARD)})
    ik.sort(key=lambda c: c["id"])
    return {
        "id": "humanoid.vrm1", "version": 1, "status": NORMATIVE, "family": "humanoid",
        "title": "Humanoid (VRM 1.0 humanoid bones)",
        "source": "https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md",
        "roles": roles,
        "referencePose": {
            "name": "T", "up": list(UP), "forward": list(FORWARD), "right": list(RIGHT),
            "sides": [{"left": "leftUpperLeg", "right": "rightUpperLeg"},
                      {"left": "leftUpperArm", "right": "rightUpperArm"}],
            "checks": checks, "toleranceDeg": DEFAULT_POSE_TOLERANCE_DEG, "toleranceStatus": "ADVISORY",
        },
        "localAxes": "UNCONSTRAINED",
        "ikTemplates": ik,
        "socketTemplates": [
            {"name": "hand.left", "role": "leftHand"}, {"name": "hand.right", "role": "rightHand"},
            {"name": "head", "role": "head"}, {"name": "spine.back", "role": "chest", "fallback": ["spine"]},
        ],
        "semanticCompatibleWith": ["humanoid.vrm1"],
        "retargetMaps": {},
        "translationRoles": ["hips"],
    }


# ---------------------------------------------------------------------------------------------
# Quadruped family (PROVISIONAL — not registered in ADM 1.0 Draft 0.4)
# ---------------------------------------------------------------------------------------------
def _quadruped_roles(front, hind, scapula_required, toes_required):
    roles = {
        "hips": _role(None, True, description="pelvis, root of the semantic hierarchy"),
        "spine": _role("hips", True), "chest": _role("spine", True),
        "neck": _role("chest", True), "head": _role("neck", True),
        "jaw": _role("head"), "leftEye": _role("head"), "rightEye": _role("head"),
        "leftEar": _role("head"), "rightEar": _role("head"),
        "tailBase": _role("hips"), "tailMid": _role("tailBase", needs_parent=True),
        "tailTip": _role("tailMid", needs_parent=True),
    }
    for side in ("left", "right"):
        roles[side + "FrontShoulder"] = _role("chest", scapula_required, description="scapula")
        parent = side + "FrontShoulder"
        for seg in front:
            req = toes_required if seg == "Toes" else True
            roles[side + "Front" + seg] = _role(parent, req, needs_parent=seg in ("Pastern", "Hoof", "Toes"))
            parent = side + "Front" + seg
        parent = "hips"
        for seg in hind:
            req = toes_required if seg == "Toes" else True
            roles[side + "Hind" + seg] = _role(parent, req, needs_parent=seg in ("Pastern", "Hoof", "Toes"))
            parent = side + "Hind" + seg
    return roles


def _quadruped(pid, title, front, hind, scapula_required, toes_required, gait, extends=None):
    checks = [{"from": "hips", "to": "chest", "direction": list(FORWARD)}]
    for side in ("left", "right"):
        for limb, segs in (("Front", front), ("Hind", hind)):
            checks.append({"from": side + limb + segs[0], "to": side + limb + segs[2], "direction": list(DOWN)})
    ik = []
    for side in ("left", "right"):
        # ADM-IK-1 is two-bone only: upper/lower/foot.  Elbow (front) bends back, stifle (hind) forward.
        ik.append({"id": side + "FrontLeg", "root": side + "Front" + front[0], "mid": side + "Front" + front[1],
                   "end": side + "Front" + front[2], "pole": list(BACK)})
        ik.append({"id": side + "HindLeg", "root": side + "Hind" + hind[0], "mid": side + "Hind" + hind[1],
                   "end": side + "Hind" + hind[2], "pole": list(FORWARD)})
    ik.sort(key=lambda c: c["id"])
    sockets = [{"name": "head", "role": "head"}, {"name": "back", "role": "chest"},
               {"name": "saddle", "role": "spine"}] if pid == "animal.equine.v1" else \
        [{"name": "head", "role": "head"}, {"name": "back", "role": "chest"}, {"name": "collar", "role": "neck"}]
    d = {
        "id": pid, "version": 1, "status": PROVISIONAL, "family": "quadruped", "title": title,
        "gait": gait, "roles": _quadruped_roles(front, hind, scapula_required, toes_required),
        "referencePose": {
            "name": "STAND", "up": list(UP), "forward": list(FORWARD), "right": list(RIGHT),
            "sides": [{"left": "leftFront" + front[0], "right": "rightFront" + front[0]},
                      {"left": "leftHind" + hind[0], "right": "rightHind" + hind[0]}],
            "checks": checks, "toleranceDeg": 45.0, "toleranceStatus": "ADVISORY",
        },
        "localAxes": "UNCONSTRAINED",
        "ikTemplates": ik,
        "socketTemplates": sockets,
        "semanticCompatibleWith": [pid],
        "retargetMaps": {},
        "translationRoles": ["hips"],
        "notes": "PROVISIONAL: not a registered ADM 1.0 profile; SEMANTIC compatibility must not be claimed.",
    }
    if extends:
        d["extends"] = extends
    return d


_DIGITIGRADE_FRONT = ("UpperLeg", "LowerLeg", "Foot", "Toes")   # humerus, radius/ulna, metacarpus, phalanges
_DIGITIGRADE_HIND = ("UpperLeg", "LowerLeg", "Foot", "Toes")    # femur, tibia, metatarsus, phalanges
_UNGULIGRADE = ("UpperLeg", "LowerLeg", "Foot", "Pastern", "Hoof")  # ..., cannon, pastern, hoof


def _build():
    profiles = [
        _humanoid(),
        {"id": "generic.v1", "version": 1, "status": EXACT_ONLY, "family": "generic",
         "title": "Generic / custom rig (exact rig binding only)", "roles": {}, "referencePose": None,
         "localAxes": "UNCONSTRAINED", "ikTemplates": [], "socketTemplates": [], "semanticCompatibleWith": [],
         "retargetMaps": {}, "translationRoles": []},
        _quadruped("animal.generic_quadruped.v1", "Generic quadruped mammal (proposal)",
                   _DIGITIGRADE_FRONT, _DIGITIGRADE_HIND, False, False, "GENERIC"),
        _quadruped("animal.canine.v1", "Canine (proposal)", _DIGITIGRADE_FRONT, _DIGITIGRADE_HIND, True, True,
                   "DIGITIGRADE", extends="animal.generic_quadruped.v1"),
        _quadruped("animal.feline.v1", "Feline (proposal)", _DIGITIGRADE_FRONT, _DIGITIGRADE_HIND, True, True,
                   "DIGITIGRADE", extends="animal.generic_quadruped.v1"),
        _quadruped("animal.equine.v1", "Equine (proposal)", _UNGULIGRADE, _UNGULIGRADE, True, False,
                   "UNGULIGRADE", extends="animal.generic_quadruped.v1"),
    ]
    return {p["id"]: p for p in profiles}


_REGISTRY = _build()
PROFILE_IDS = tuple(_REGISTRY)
HUMANOID = "humanoid.vrm1"
GENERIC = "generic.v1"
QUADRUPED_IDS = tuple(p for p in PROFILE_IDS if _REGISTRY[p]["family"] == "quadruped")
_CUSTOM_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)*\.v[0-9]+$")


def get(profile_id):
    """Return a deep copy of a registered/provisional profile or ``None`` for unknown ids."""
    p = _REGISTRY.get(profile_id)
    return copy.deepcopy(p) if p is not None else None


def status(profile_id):
    p = _REGISTRY.get(profile_id)
    return p["status"] if p else None


def is_known(profile_id):
    return profile_id in _REGISTRY


def is_custom_id(profile_id):
    return isinstance(profile_id, str) and not is_known(profile_id) and bool(_CUSTOM_ID_RE.match(profile_id))


def roles(profile_id):
    p = _REGISTRY.get(profile_id)
    return dict(p["roles"]) if p else {}


def required_roles(profile_id):
    return tuple(r for r, d in roles(profile_id).items() if d["required"])


def ik_templates(profile_id):
    p = _REGISTRY.get(profile_id)
    return copy.deepcopy(p["ikTemplates"]) if p else []


def socket_templates(profile_id):
    p = _REGISTRY.get(profile_id)
    return copy.deepcopy(p["socketTemplates"]) if p else []


def semantic_role_names(profile_id):
    """Roles a SEMANTIC library may target for this profile (empty for unknown/exact-only)."""
    if profile_id == K.MODEL_ANY_PROFILE:
        return set()
    return set(roles(profile_id))


def registry_document():
    return {"registryVersion": REGISTRY_VERSION, "specification": "ADM 1.0 Draft 0.4",
            "coordinateSystem": {"up": list(UP), "forward": list(FORWARD), "right": list(RIGHT)},
            "profiles": [copy.deepcopy(_REGISTRY[k]) for k in PROFILE_IDS]}


def registry_json():
    """Canonical JSON text published as adm-standard/profiles/skeleton-profiles.json."""
    return json.dumps(registry_document(), indent=2, ensure_ascii=False) + "\n"
