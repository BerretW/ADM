"""Skeleton profile registry, rig validation, IK solver and library compatibility tests (no Blender).

Run: python -m unittest adm_blender.tests.test_skeleton_profiles -v
"""

import math
from pathlib import Path
import unittest

from adm_blender.core import constants as K
from adm_blender.core import ik as IK
from adm_blender.core import skeleton as SK
from adm_blender.core import skeleton_profiles as SP
from adm_blender.core.rolemap import auto_map

STANDARD = Path(__file__).resolve().parents[2] / "adm-standard"


# --------------------------------------------------------------------------------------------------
# rig builders (ADM model space: +Y up, +X character's right, forward -Z)
# --------------------------------------------------------------------------------------------------
def humanoid_rig(scale=1.0, arm_drop_deg=0.0, mirrored=False):
    s = scale
    p = {"hips": (0, 1.0, 0), "spine": (0, 1.1, 0), "chest": (0, 1.25, 0), "upperChest": (0, 1.35, 0),
         "neck": (0, 1.5, 0), "head": (0, 1.6, 0)}
    parent = {"hips": None, "spine": "hips", "chest": "spine", "upperChest": "chest", "neck": "upperChest",
              "head": "neck"}
    drop = math.radians(arm_drop_deg)
    for side, sx in (("right", 1.0), ("left", -1.0)):
        p[side + "Shoulder"] = (0.05 * sx, 1.45, 0)
        p[side + "UpperArm"] = (0.15 * sx, 1.45, 0)
        for name, dist in ((side + "LowerArm", 0.3), (side + "Hand", 0.55)):
            p[name] = (sx * (0.15 + dist * math.cos(drop)), 1.45 - dist * math.sin(drop), 0)
        p[side + "UpperLeg"] = (0.1 * sx, 0.95, 0)
        p[side + "LowerLeg"] = (0.1 * sx, 0.5, 0)
        p[side + "Foot"] = (0.1 * sx, 0.08, 0)
        p[side + "Toes"] = (0.1 * sx, 0.0, -0.1)
        parent.update({side + "Shoulder": "upperChest", side + "UpperArm": side + "Shoulder",
                       side + "LowerArm": side + "UpperArm", side + "Hand": side + "LowerArm",
                       side + "UpperLeg": "hips", side + "LowerLeg": side + "UpperLeg",
                       side + "Foot": side + "LowerLeg", side + "Toes": side + "Foot"})
    bones = {}
    for role, pos in p.items():
        pos = (pos[0] * s, pos[1] * s, pos[2] * s)
        if mirrored:
            pos = (-pos[0], pos[1], -pos[2])
        bones["B_" + role] = {"parent": "B_" + parent[role] if parent[role] else None, "head": pos}
    assignments = [("B_" + r, r) for r in p]
    return bones, assignments


def quadruped_rig(kind="digitigrade"):
    bones = {"pelvis": {"parent": None, "head": (0, 0.6, 0.4)},
             "spine_01": {"parent": "pelvis", "head": (0, 0.62, 0.2)},
             "chest": {"parent": "spine_01", "head": (0, 0.65, -0.2)},
             "neck": {"parent": "chest", "head": (0, 0.75, -0.4)},
             "head": {"parent": "neck", "head": (0, 0.85, -0.55)},
             "tail_01": {"parent": "pelvis", "head": (0, 0.6, 0.5)},
             "tail_02": {"parent": "tail_01", "head": (0, 0.55, 0.65)}}
    front = ["scapula", "humerus", "forearm", "paw", "toes"]
    hind = ["thigh", "shin", "hock", "toes"]
    if kind == "unguligrade":
        front = ["scapula", "humerus", "forearm", "cannon", "pastern", "hoof"]
        hind = ["thigh", "gaskin", "cannon", "pastern", "hoof"]
    for side, sx in (("L", -1.0), ("R", 1.0)):
        parent, y = "chest", 0.6
        for i, seg in enumerate(front):
            n = f"front_{seg}_{side}"
            bones[n] = {"parent": parent, "head": (0.12 * sx, y, -0.25 - 0.01 * i)}
            parent, y = n, y - 0.6 / len(front)
        parent, y = "pelvis", 0.55
        for i, seg in enumerate(hind):
            n = f"hind_{seg}_{side}"
            bones[n] = {"parent": parent, "head": (0.12 * sx, y, 0.4 + 0.01 * i)}
            parent, y = n, y - 0.55 / len(hind)
    return bones


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}


# --------------------------------------------------------------------------------------------------
class RegistryTests(unittest.TestCase):
    def test_humanoid_roles_follow_vrm1(self):
        self.assertEqual(set(SP.roles("humanoid.vrm1")), set(K.VRM1_PARENT))
        self.assertEqual(len(SP.roles("humanoid.vrm1")), 55)
        self.assertEqual(set(SP.required_roles("humanoid.vrm1")), set(K.VRM1_REQUIRED))
        self.assertEqual(SP.status("humanoid.vrm1"), SP.NORMATIVE)
        defs = SP.roles("humanoid.vrm1")
        self.assertTrue(defs["upperChest"].get("needsParent"))
        self.assertTrue(defs["leftThumbDistal"].get("needsParent"))
        self.assertFalse(defs["leftIndexProximal"].get("needsParent", False))

    def test_animal_profiles_are_provisional_and_specialised(self):
        for pid in ("animal.generic_quadruped.v1", "animal.canine.v1", "animal.feline.v1", "animal.equine.v1"):
            self.assertEqual(SP.status(pid), SP.PROVISIONAL, pid)
            self.assertIn("hips", SP.required_roles(pid))
        self.assertNotIn("leftFrontToes", SP.required_roles("animal.generic_quadruped.v1"))
        self.assertIn("leftFrontToes", SP.required_roles("animal.canine.v1"))
        self.assertIn("leftHindPastern", SP.required_roles("animal.equine.v1"))
        self.assertNotIn("leftHindToes", SP.roles("animal.equine.v1"))
        self.assertEqual(SP.status("generic.v1"), SP.EXACT_ONLY)
        self.assertTrue(SP.is_custom_id("org.example.robot.v2"))
        self.assertFalse(SP.is_custom_id("custom"))

    def test_published_registry_json_matches_code(self):
        path = STANDARD / "profiles" / "skeleton-profiles.json"
        self.assertEqual(path.read_text(encoding="utf-8"), SP.registry_json(),
                         "regenerate with: python -m adm_blender.tests.test_skeleton_profiles --write-registry")


class HumanoidRigTests(unittest.TestCase):
    def test_valid_rig(self):
        bones, asg = humanoid_rig()
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        self.assertFalse(SK.has_errors(issues), issues)

    def test_missing_required_role(self):
        bones, asg = humanoid_rig()
        asg = [a for a in asg if a[1] != "leftHand"]
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        miss = [i for i in issues if i.code == "ROLE_MISSING"]
        self.assertEqual([i.role for i in miss], ["leftHand"])
        self.assertEqual(miss[0].fix, SK.FIX_AUTO_MAP)

    def test_duplicate_role(self):
        bones, asg = humanoid_rig()
        asg.append(("B_leftLowerArm", "leftHand"))
        asg = [a for a in asg if a != ("B_leftLowerArm", "leftLowerArm")]
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        dup = [i for i in issues if i.code == "ROLE_DUPLICATE"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0].role, "leftHand")
        self.assertIn("B_leftHand", dup[0].message)
        self.assertIn("B_leftLowerArm", dup[0].message)

    def test_extra_helper_bones_are_allowed(self):
        bones, asg = humanoid_rig()
        bones["twist_spine"] = {"parent": "B_spine", "head": (0, 1.18, 0)}
        bones["B_chest"]["parent"] = "twist_spine"
        for i in range(40):
            bones[f"hair_{i}"] = {"parent": "B_head", "head": (0.01 * i, 1.7, 0.05)}
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        self.assertFalse(SK.has_errors(issues), issues)
        extra = [i for i in issues if i.code == "EXTRA_BONES"]
        self.assertIn("41", extra[0].message)

    def test_wrong_parent(self):
        bones, asg = humanoid_rig()
        bones["B_leftHand"]["parent"] = "B_spine"
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        h = [i for i in issues if i.code == "ROLE_HIERARCHY"]
        self.assertEqual([(i.role, i.bone) for i in h], [("leftHand", "B_leftHand")])
        self.assertIn("'spine'", h[0].message)
        self.assertIn("'leftLowerArm'", h[0].message)

    def test_needs_parent_rule(self):
        bones, asg = humanoid_rig()
        bones["B_idx3"] = {"parent": "B_leftHand", "head": (-0.8, 1.45, 0)}
        asg.append(("B_idx3", "leftIndexDistal"))
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        self.assertIn("ROLE_NEEDS_PARENT", codes(issues, SK.ERROR))

    def test_unknown_role(self):
        bones, asg = humanoid_rig()
        asg.append(("B_upperChest", "leftWing"))
        asg = [a for a in asg if a[1] != "upperChest"]
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        unk = [i for i in issues if i.code == "ROLE_UNKNOWN"]
        self.assertEqual(unk[0].fix, SK.FIX_DROP_UNKNOWN)

    def test_wrong_reference_pose_a_pose(self):
        bones, asg = humanoid_rig(arm_drop_deg=45)
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        bad = {i.role for i in issues if i.code == "REFERENCE_POSE"}
        self.assertEqual(bad, {"leftUpperArm", "leftLowerArm", "rightUpperArm", "rightLowerArm"})
        ok = SK.analyze_rig("humanoid.vrm1", *humanoid_rig(arm_drop_deg=10))
        self.assertNotIn("REFERENCE_POSE", codes(ok))

    def test_mirrored_facing_offers_safe_fix(self):
        bones, asg = humanoid_rig(mirrored=True)
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        f = [i for i in issues if i.code == "REFERENCE_FACING"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].fix, SK.FIX_ROTATE_180)
        self.assertNotIn("REFERENCE_POSE", codes(issues))

    def test_auto_detect_humanoid(self):
        names = ["mixamorig:Hips", "mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2", "mixamorig:Neck",
                 "mixamorig:Head"]
        for s in ("Left", "Right"):
            names += [f"mixamorig:{s}{b}" for b in ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot",
                                                    "ToeBase")]
        bones, _ = humanoid_rig()
        geo = {n: {"parent": None, "head": (0, i * 0.1, 0)} for i, n in enumerate(names)}
        pid, mapping, _reason = SK.detect_profile(geo, auto_map)
        self.assertEqual(pid, "humanoid.vrm1")
        self.assertEqual(mapping["mixamorig:LeftForeArm"], "leftLowerArm")
        self.assertEqual(mapping["mixamorig:Spine2"], "upperChest")


class QuadrupedTests(unittest.TestCase):
    def test_generic_quadruped_auto_map_and_validate(self):
        bones = quadruped_rig()
        pid, mapping, reason = SK.detect_profile(bones, auto_map)
        self.assertEqual(pid, "animal.generic_quadruped.v1", reason)
        self.assertEqual(mapping["front_forearm_L"], "leftFrontLowerLeg")
        self.assertEqual(mapping["hind_hock_R"], "rightHindFoot")
        self.assertEqual(mapping["tail_02"], "tailMid")
        issues = SK.analyze_rig(pid, bones, list(mapping.items()))
        self.assertFalse(SK.has_errors(issues), issues)
        self.assertIn("PROFILE_PROVISIONAL", codes(issues, SK.WARNING))

    def test_specialisations_enforce_anatomy(self):
        bones = quadruped_rig()
        mapping = SK.auto_map_quadruped(bones, "animal.canine.v1")
        del bones["front_toes_L"]
        asg = [(b, r) for b, r in mapping.items() if b in bones]
        self.assertFalse(SK.has_errors(SK.analyze_rig("animal.generic_quadruped.v1", bones, asg)))
        canine = SK.analyze_rig("animal.canine.v1", bones, asg)
        self.assertEqual([i.role for i in canine if i.code == "ROLE_MISSING"], ["leftFrontToes"])
        equine = SK.analyze_rig("animal.equine.v1", bones, asg)
        self.assertIn("ROLE_UNKNOWN", codes(equine))      # digit roles do not exist on a horse
        self.assertIn("ROLE_MISSING", codes(equine))      # pastern/hoof required

    def test_equine_detection(self):
        bones = quadruped_rig("unguligrade")
        pid, mapping, reason = SK.detect_profile(bones, auto_map)
        self.assertEqual(pid, "animal.equine.v1", reason)
        self.assertEqual(mapping["hind_pastern_L"], "leftHindPastern")
        self.assertFalse(SK.has_errors(SK.analyze_rig(pid, bones, list(mapping.items()))))


class IKTests(unittest.TestCase):
    def setUp(self):
        self.bones, asg = humanoid_rig()
        self.role_of = {b: r for b, r in asg}
        self.chains = [{"id": t["id"], "root": "B_" + t["root"], "mid": "B_" + t["mid"], "end": "B_" + t["end"],
                        "pole": t["pole"], "weight": 1.0} for t in SP.ik_templates("humanoid.vrm1")]

    def test_valid_profile_chains(self):
        issues = SK.analyze_ik(self.chains, self.bones, "humanoid.vrm1", self.role_of)
        self.assertEqual(issues, [])
        self.assertEqual([c["id"] for c in self.chains], sorted(c["id"] for c in self.chains))

    def test_invalid_chains(self):
        bad = [dict(self.chains[0], end=""),                                         # incomplete
               dict(self.chains[2], id="notDirect", root="B_hips", mid="B_leftLowerLeg", end="B_leftFoot"),
               dict(self.chains[3], id="collinear", pole=(0, -1, 0))]
        issues = SK.analyze_ik(bad, self.bones)
        c = codes(issues, SK.ERROR)
        self.assertIn("IK_INCOMPLETE", c)
        self.assertIn("IK_NOT_DIRECT", c)
        self.assertIn("IK_POLE_COLLINEAR", c)
        over = SK.analyze_ik(self.chains + [dict(self.chains[0], id="zz")], self.bones)
        self.assertIn("IK_OVERLAP", codes(over))
        self.assertIn("IK_ID_DUPLICATE", codes(SK.analyze_ik(self.chains + [self.chains[0]], self.bones)))

    def _leg(self):
        b = self.bones
        return b["B_leftUpperLeg"]["head"], b["B_leftLowerLeg"]["head"], b["B_leftFoot"]["head"]

    def test_solver_reachable(self):
        A, B, C = self._leg()
        ident = (0.0, 0.0, 0.0, 1.0)
        P = (-0.1, 0.3, -0.2)
        r = IK.solve_chain(A, B, C, ident, ident, ident, P, (0, 0, -1), 1.0)
        self.assertEqual(r["status"], IK.SOLVED)
        self.assertLess(r["error"], 1e-9)
        l1, l2 = IK.length(IK.sub(B, A)), IK.length(IK.sub(C, B))
        self.assertAlmostEqual(IK.length(IK.sub(r["mid"], A)), l1, places=9)
        self.assertAlmostEqual(IK.length(IK.sub(r["end"], r["mid"])), l2, places=9)
        self.assertLess(r["mid"][2], A[2] - 1e-3, "knee must bend toward the pole (-Z)")

    def test_solver_clamped_and_weight(self):
        A, B, C = self._leg()
        ident = (0.0, 0.0, 0.0, 1.0)
        P = (-0.1, -2.0, 0.0)
        r = IK.solve_chain(A, B, C, ident, ident, ident, P, (0, 0, -1), 1.0)
        self.assertEqual(r["status"], IK.CLAMPED)
        reach = IK.length(IK.sub(B, A)) + IK.length(IK.sub(C, B))
        self.assertAlmostEqual(IK.length(IK.sub(r["end"], A)), reach, places=9)
        z = IK.solve_chain(A, B, C, ident, ident, ident, (0.3, 0.3, 0.3), (0, 0, -1), 0.0)
        self.assertEqual(z["root_local"], ident)
        self.assertEqual(z["end"], C)
        half = IK.solve_chain(A, B, C, ident, ident, ident, (-0.1, 0.3, -0.2), (0, 0, -1), 0.5)
        full = IK.solve_chain(A, B, C, ident, ident, ident, (-0.1, 0.3, -0.2), (0, 0, -1), 1.0)
        ang = lambda q: 2 * math.degrees(math.acos(min(1.0, abs(q[3]))))  # noqa: E731
        self.assertAlmostEqual(ang(half["root_local"]), ang(full["root_local"]) / 2, places=6)

    def test_from_to_antipodal_and_pole_fallback(self):
        q = IK.from_to((0, 1, 0), (0, -1, 0))
        v = IK.q_rotate(q, (0, 1, 0))
        self.assertAlmostEqual(v[1], -1.0, places=12)
        # least aligned axis of +Y is X (tie X before Z): axis = cross(Y, X) = -Z, angle pi
        self.assertAlmostEqual(q[2], -1.0, places=12)
        A, B, C = self._leg()
        P = (-0.1, 0.2, 0.0)
        s = IK.solve_points(A, B, C, P, (0, -1, 0))   # pole collinear with root->target
        self.assertEqual(s["status"], IK.SOLVED)
        # fallback pole = least aligned axis of u (-Y) -> X; the knee bends toward +X
        self.assertGreater(s["mid"][0], A[0] + 1e-3)
        self.assertAlmostEqual(IK.length(IK.sub(s["mid"], A)), IK.length(IK.sub(B, A)), places=9)

    def test_solver_equal_length_zero_fold_is_deterministic(self):
        A, B, C = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
        solved = IK.solve_points(A, B, C, A, (0.0, 0.0, 1.0))
        self.assertEqual(solved["status"], IK.SOLVED)
        self.assertEqual(solved["mid"], B)
        self.assertEqual(solved["end"], A)
        self.assertEqual(solved["d_solved"], 0.0)


class CompatibilityTests(unittest.TestCase):
    def lib(self, profile, binding="SEMANTIC", rig=None):
        d = {"targetProfile": profile, "binding": binding}
        if rig:
            d["rigId"] = rig
        return d

    def test_semantic_humanoid(self):
        roles = set(K.VRM1_REQUIRED)
        lvl, _ = SK.library_compatibility(self.lib("humanoid.vrm1"), "humanoid.vrm1", roles)
        self.assertEqual(lvl, SK.SEMANTIC)
        lvl, why = SK.library_compatibility(self.lib("humanoid.vrm1"), "humanoid.vrm1", roles - {"leftHand"})
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        self.assertIn("leftHand", why[0])

    def test_bad_target_rig_is_incompatible(self):
        bones, asg = humanoid_rig(arm_drop_deg=45)
        issues = SK.analyze_rig("humanoid.vrm1", bones, asg)
        lvl, _ = SK.library_compatibility(self.lib("humanoid.vrm1"), "humanoid.vrm1", {r for _, r in asg}, None,
                                          issues)
        self.assertEqual(lvl, SK.INCOMPATIBLE)

    def test_cross_species_is_incompatible(self):
        roles = set(SP.required_roles("animal.equine.v1"))
        lvl, why = SK.library_compatibility(self.lib("animal.canine.v1"), "animal.equine.v1", roles)
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        self.assertIn("approved explicit mapping", why[0])
        lvl, _ = SK.library_compatibility(self.lib("humanoid.vrm1"), "animal.canine.v1", roles)
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        # identical topology, different species: still no automatic binding
        lvl, _ = SK.library_compatibility(self.lib("animal.canine.v1"), "animal.feline.v1",
                                          set(SP.required_roles("animal.feline.v1")))
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        lvl, _ = SK.library_compatibility(self.lib("animal.canine.v1"), "animal.canine.v1",
                                          set(SP.required_roles("animal.canine.v1")))
        self.assertEqual(lvl, SK.PROVISIONAL_SEMANTIC)

    def test_exact_and_unknown(self):
        lvl, _ = SK.library_compatibility(self.lib("generic.v1", "EXACT", "a" * 64), "generic.v1", set(), True)
        self.assertEqual(lvl, SK.EXACT)
        lvl, _ = SK.library_compatibility(self.lib("generic.v1", "EXACT", "a" * 64), "generic.v1", set(), False)
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        lvl, _ = SK.library_compatibility(self.lib("org.example.robot.v1"), "org.example.robot.v1", set())
        self.assertEqual(lvl, SK.INCOMPATIBLE)
        lvl, _ = SK.library_compatibility(self.lib("generic.v1"), "generic.v1", set())
        self.assertEqual(lvl, SK.INCOMPATIBLE)


if __name__ == "__main__":
    import sys
    if "--write-registry" in sys.argv:
        out = STANDARD / "profiles" / "skeleton-profiles.json"
        out.write_text(SP.registry_json(), encoding="utf-8", newline="\n")
        print("wrote", out)
    else:
        unittest.main()
