"""Blender-side skeleton tooling: joint tables, rig validation, safe fixes, normalized reference
corrections, ADM-IK-1 chains (templates, Blender IK import, solver preview) and skin checks.

All geometric analysis is delegated to the bpy-free :mod:`..core.skeleton` / :mod:`..core.ik` so the
same rules run in tests, the validator and the UI.
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..core import ik as IK
from ..core import skeleton as SK
from ..core import skeleton_profiles as SP
from . import convert as cv
from .export_adm import find_model_root
from .rolemap import auto_map

FIX_NORMALIZE_CORRECTIONS = "NORMALIZE_CORRECTIONS"
FIX_LIMIT_WEIGHTS = "LIMIT_WEIGHTS"
MAX_INFLUENCES = 4
CORRECTION_TOL_DEG = 0.01


# --------------------------------------------------------------------------------------------------
# spaces
# --------------------------------------------------------------------------------------------------
def model_matrix(arm):
    """Armature object matrix relative to the ADM model root (Blender axes)."""
    root = find_model_root(arm)
    if root is not None and root != arm:
        return root.matrix_world.inverted_safe() @ arm.matrix_world
    return arm.matrix_world.copy()


def to_adm_point(m, p):
    v = cv.C3 @ (m @ Vector(p))
    return (v.x, v.y, v.z)


def joint_table(arm):
    m = model_matrix(arm)
    return {b.name: {"parent": b.parent.name if b.parent else None, "head": to_adm_point(m, b.head_local)}
            for b in arm.data.bones}


def assignments(arm):
    return [(b.name, b.adm.role.strip()) for b in arm.data.bones if b.adm.role.strip()]


def role_bone_map(arm):
    out = {}
    for b in arm.data.bones:
        r = b.adm.role.strip()
        if r and r not in out:
            out[r] = b.name
    return out


def pole_to_adm(arm, pole):
    v = cv.C3 @ (model_matrix(arm).to_3x3().normalized() @ Vector(pole))
    return tuple(v.normalized()) if v.length > 1e-12 else (0.0, 0.0, 0.0)


def pole_from_adm(arm, pole):
    v = model_matrix(arm).to_3x3().normalized().inverted_safe() @ (cv.C3_INV @ Vector(pole))
    return v.normalized() if v.length > 1e-12 else v


def chains_adm(arm):
    return [{"id": c.chain_id, "root": c.root, "mid": c.mid, "end": c.end,
             "pole": pole_to_adm(arm, c.pole) if Vector(c.pole).length > 1e-12 else (0.0, 0.0, 0.0),
             "weight": c.weight} for c in arm.data.adm.ik_chains]


# --------------------------------------------------------------------------------------------------
# normalized reference corrections (ADM-REF-NORM, see adm-standard/profiles/humanoid.vrm1.md)
# --------------------------------------------------------------------------------------------------
def normalized_correction(arm, bone):
    """Blender-space correction = inverse rest rotation of the joint in model space."""
    q = (model_matrix(arm) @ bone.matrix_local).to_quaternion()
    q.normalize()
    return q.inverted()


def effective_correction(bone):
    if bone.adm.use_reference_correction:
        q = Quaternion(bone.adm.reference_correction)
        q.normalize()
        return q
    return Quaternion((1.0, 0.0, 0.0, 0.0))


def apply_normalized_corrections(arm):
    n = 0
    for b in arm.data.bones:
        if b.adm.role.strip():
            b.adm.use_reference_correction = True
            b.adm.reference_correction = normalized_correction(arm, b)
            n += 1
    return n


def correction_issues(arm):
    bad = []
    for b in arm.data.bones:
        if b.adm.role.strip():
            d = effective_correction(b).rotation_difference(normalized_correction(arm, b))
            if math.degrees(d.angle) > CORRECTION_TOL_DEG:
                bad.append(b)
    if not bad:
        return []
    return [SK.RigIssue(SK.WARNING, "CORRECTION_NOT_NORMALIZED",
                        f"{len(bad)} mapped bone(s) lack normalized reference corrections; SEMANTIC clips then "
                        f"depend on bone roll and only round-trip between identical rigs",
                        role=bad[0].adm.role, bone=bad[0].name, fix=FIX_NORMALIZE_CORRECTIONS)]


# --------------------------------------------------------------------------------------------------
# Blender constraints -> ADM IK contract
# --------------------------------------------------------------------------------------------------
def ik_triplet(pb, con):
    """(root, mid, end) bone names equivalent to a two-bone Blender IK constraint, or None.

    With 'Use Tail' the constrained bone is the mid bone and the end joint is the child starting at its
    tail; without it the constrained bone's head is the end joint.
    """
    if con.chain_count != 2:
        return None
    if con.use_tail:
        if pb.parent is None:
            return None
        kids = sorted(pb.children, key=lambda k: ((k.bone.head_local - pb.bone.tail_local).length, k.name))
        if not kids or (kids[0].bone.head_local - pb.bone.tail_local).length > 1e-4 * max(pb.bone.length, 1e-6):
            return None
        return pb.parent.name, pb.name, kids[0].name
    if pb.parent is None or pb.parent.parent is None:
        return None
    return pb.parent.parent.name, pb.parent.name, pb.name


def constraint_issues(arm):
    issues = []
    chain_ends = {c.end for c in arm.data.adm.ik_chains}
    for pb in arm.pose.bones:
        for con in pb.constraints:
            if con.type == "IK":
                where = f"IK constraint '{con.name}' on '{pb.name}'"
                tri = ik_triplet(pb, con)
                if tri is None and con.chain_count == 2:
                    issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_UNSUPPORTED", where + ": no end joint (the "
                                              "tail has no connected child bone)", bone=pb.name))
                elif tri is not None and tri[2] not in chain_ends:
                    issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_NOT_EXPORTED",
                                              where + " has no matching ADM chain (use 'From Blender IK')",
                                              bone=pb.name, role=pb.bone.adm.role))
                if con.chain_count != 2:
                    issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_UNSUPPORTED",
                                              where + f": chain length {con.chain_count} (ADM-IK-1 is two-bone only)",
                                              bone=pb.name))
                chain = [p for p in (pb.parent, pb.parent.parent if pb.parent else None) if p is not None]
                if con.use_stretch and any(p.ik_stretch > 0 for p in chain):
                    issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_UNSUPPORTED", where + ": stretch is not "
                                              "supported (ADM stretch MUST be false)", bone=pb.name))
                if con.use_rotation:
                    issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_UNSUPPORTED", where + ": target rotation "
                                              "is not solved by ADM-IK-1 (UNSUPPORTED_ORIENTATION)", bone=pb.name))
            elif not con.mute:
                issues.append(SK.RigIssue(SK.WARNING, "BLENDER_CONSTRAINT_UNSUPPORTED",
                                          f"{con.type} constraint '{con.name}' on '{pb.name}' is not exported "
                                          f"(ADM has no runtime constraints)", bone=pb.name, role=pb.bone.adm.role))
        limits = [ax for ax in "xyz" if getattr(pb, "use_ik_limit_" + ax)]
        locks = [ax for ax in "xyz" if getattr(pb, "lock_ik_" + ax)]
        if limits or locks:
            issues.append(SK.RigIssue(SK.WARNING, "BLENDER_IK_LIMITS", f"'{pb.name}': IK joint limits/locks "
                                      f"({', '.join(limits + locks)}) are not part of ADM-IK-1 and are ignored",
                                      bone=pb.name, role=pb.bone.adm.role))
    return issues


# --------------------------------------------------------------------------------------------------
# skinning
# --------------------------------------------------------------------------------------------------
def skinned_meshes(arm):
    return [o for o in bpy.data.objects if o.type == "MESH" and any(
        m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]


def skin_stats(obj, arm):
    deform = {b.name for b in arm.data.bones if b.use_deform}
    gi = {g.index: g.name for g in obj.vertex_groups if g.name in deform}
    over = unweighted = unnormalized = 0
    for v in obj.data.vertices:
        ws = [g.weight for g in v.groups if g.group in gi and g.weight > 0.0]
        if not ws:
            unweighted += 1
            continue
        if len(ws) > MAX_INFLUENCES:
            over += 1
        if abs(sum(ws) - 1.0) > 1e-5:
            unnormalized += 1
    return {"over": over, "unweighted": unweighted, "unnormalized": unnormalized,
            "vertices": len(obj.data.vertices), "groups": len(gi)}


def skin_issues(arm):
    issues = []
    for o in skinned_meshes(arm):
        s = skin_stats(o, arm)
        if s["groups"] == 0:
            issues.append(SK.RigIssue(SK.ERROR, "SKIN_NO_GROUPS", f"'{o.name}' has an Armature modifier but no "
                                      "vertex groups named after deform bones", bone=o.name))
            continue
        if s["unweighted"]:
            issues.append(SK.RigIssue(SK.WARNING, "SKIN_UNWEIGHTED", f"'{o.name}': {s['unweighted']} vertices have "
                                      "no deform weight (exported rigidly bound)", bone=o.name))
        if s["over"]:
            issues.append(SK.RigIssue(SK.WARNING, "SKIN_INFLUENCES", f"'{o.name}': {s['over']} vertices have more "
                                      f"than {MAX_INFLUENCES} influences (exporter drops the smallest)", bone=o.name,
                                      fix=FIX_LIMIT_WEIGHTS))
        if s["unnormalized"]:
            issues.append(SK.RigIssue(SK.INFO, "SKIN_NOT_NORMALIZED", f"'{o.name}': {s['unnormalized']} vertices "
                                      "have weight sums != 1 (exporter renormalizes)", bone=o.name,
                                      fix=FIX_LIMIT_WEIGHTS))
    return issues


def limit_and_normalize_weights(obj, arm, limit=MAX_INFLUENCES):
    deform = {b.name for b in arm.data.bones if b.use_deform}
    groups = {g.index: g for g in obj.vertex_groups if g.name in deform}
    changed = 0
    for v in obj.data.vertices:
        ws = sorted(((g.weight, g.group) for g in v.groups if g.group in groups and g.weight > 0.0), reverse=True)
        if not ws:
            continue
        keep, drop = ws[:limit], ws[limit:]
        total = sum(w for w, _ in keep)
        if not drop and abs(total - 1.0) <= 1e-6:
            continue
        for _w, gi in drop:
            groups[gi].remove([v.index])
        for w, gi in keep:
            groups[gi].add([v.index], w / total, "REPLACE")
        changed += 1
    return changed


# --------------------------------------------------------------------------------------------------
# analysis + fixes
# --------------------------------------------------------------------------------------------------
def analyze(arm):
    sk = arm.data.adm
    pid = sk.profile_id.strip()
    bones = joint_table(arm)
    issues = SK.analyze_rig(pid, bones, assignments(arm))
    role_of = {b: r for b, r in assignments(arm)}
    issues += SK.analyze_ik(chains_adm(arm), bones, pid, role_of)
    if SP.status(pid) in (SP.NORMATIVE, SP.PROVISIONAL):
        issues += correction_issues(arm)
    issues += constraint_issues(arm)
    issues += skin_issues(arm)
    if not sk.export_profile and SP.status(pid) in (SP.NORMATIVE, SP.PROVISIONAL):
        issues.append(SK.RigIssue(SK.WARNING, "PROFILE_NOT_EXPORTED", "'Export Skeleton Profile' is off: the "
                                  "exported model will not declare its skeleton profile"))
    return issues


def semantic_errors(arm):
    """Errors that make SEMANTIC binding invalid (role mapping + reference pose)."""
    return [i for i in SK.analyze_rig(arm.data.adm.profile_id.strip(), joint_table(arm), assignments(arm))
            if i.severity == SK.ERROR]


def top_object_under_root(obj, root):
    o = obj
    while o.parent is not None and o.parent != root:
        o = o.parent
    return o


def rotate_180(arm):
    """Rotate the rig (and meshes deformed by it) 180 deg about the model's up axis."""
    root = find_model_root(arm)
    if root == arm:
        root = None
    tops = {top_object_under_root(arm, root)}
    for o in skinned_meshes(arm):
        tops.add(top_object_under_root(o, root))
    rot = Matrix.Rotation(math.pi, 4, "Z")
    pivot = root.matrix_world if root is not None else Matrix.Identity(4)
    xf = pivot @ rot @ pivot.inverted_safe()
    for t in tops:
        t.matrix_world = xf @ t.matrix_world
    bpy.context.view_layer.update()
    return sorted(t.name for t in tops)


def apply_fix(context, arm, fix, issue_role="", issue_bone=""):
    """Apply an unambiguous fix. Returns a human readable message."""
    if fix == SK.FIX_ROTATE_180:
        names = rotate_180(arm)
        for b in arm.data.bones:
            if b.adm.use_reference_correction:
                b.adm.reference_correction = normalized_correction(arm, b)
        return "rotated 180 deg about up: " + ", ".join(names)
    if fix == FIX_NORMALIZE_CORRECTIONS:
        return f"normalized reference corrections on {apply_normalized_corrections(arm)} bones"
    if fix == SK.FIX_DROP_UNKNOWN and issue_bone in arm.data.bones:
        arm.data.bones[issue_bone].adm.role = ""
        return f"cleared unknown role '{issue_role}' on '{issue_bone}'"
    if fix == SK.FIX_AUTO_MAP:
        n = auto_map_profile(arm, overwrite=False)
        return f"auto-mapped {n} additional bone(s); review the mapping"
    if fix == SK.FIX_NORMALIZE_POLE:
        for c in arm.data.adm.ik_chains:
            v = Vector(c.pole)
            if v.length > 1e-12:
                c.pole = v.normalized()
        return "normalized IK poles"
    if fix == FIX_LIMIT_WEIGHTS:
        n = sum(limit_and_normalize_weights(o, arm) for o in skinned_meshes(arm))
        return f"limited to {MAX_INFLUENCES} influences and normalized {n} vertices"
    return ""


def apply_mapping(arm, mapping, overwrite=False):
    bones = arm.data.bones
    if overwrite:
        for b in bones:
            b.adm.role = ""
    used = {b.adm.role for b in bones if b.adm.role}
    n = 0
    for name, role in sorted(mapping.items()):
        b = bones.get(name)
        if b is None or b.adm.role or role in used:
            continue
        b.adm.role = role
        used.add(role)
        n += 1
    return n


def auto_map_profile(arm, overwrite=False, profile_id=None):
    pid = profile_id or arm.data.adm.profile_id.strip()
    bones = arm.data.bones
    if pid == SP.HUMANOID:
        names = [b.name for b in bones if b.use_deform] or [b.name for b in bones]
        mapping = auto_map(names)
    elif pid in SP.QUADRUPED_IDS:
        mapping = SK.auto_map_quadruped(joint_table(arm), pid)
    else:
        return 0
    return apply_mapping(arm, mapping, overwrite)


def detect(arm):
    table = joint_table(arm)
    deform = {b.name for b in arm.data.bones if b.use_deform}
    sub = {k: v for k, v in table.items() if k in deform} or table
    for k, v in sub.items():
        p = v["parent"]
        while p is not None and p not in sub:
            p = table[p]["parent"]
        sub[k] = {"parent": p, "head": v["head"]}
    return SK.detect_profile(sub, auto_map)


# --------------------------------------------------------------------------------------------------
# IK chains
# --------------------------------------------------------------------------------------------------
def add_chains_from_profile(arm, replace=False):
    sk = arm.data.adm
    rb = role_bone_map(arm)
    if replace:
        sk.ik_chains.clear()
    existing = {c.chain_id for c in sk.ik_chains}
    added, skipped = [], []
    for t in SP.ik_templates(sk.profile_id.strip()):
        if t["id"] in existing:
            continue
        names = [rb.get(t[k]) for k in ("root", "mid", "end")]
        if not all(names):
            skipped.append(t["id"])
            continue
        c = sk.ik_chains.add()
        c.chain_id = t["id"]
        c.root, c.mid, c.end = names
        c.pole = pole_from_adm(arm, t["pole"])
        added.append(t["id"])
    sort_chains(arm)
    return added, skipped


def sort_chains(arm):
    sk = arm.data.adm
    order = sorted(range(len(sk.ik_chains)), key=lambda i: sk.ik_chains[i].chain_id)
    # bubble the collection into lexical order (CollectionProperty.move)
    ids = [sk.ik_chains[i].chain_id for i in order]
    for target, cid in enumerate(ids):
        cur = next(i for i, c in enumerate(sk.ik_chains) if c.chain_id == cid and i >= target)
        if cur != target:
            sk.ik_chains.move(cur, target)


def chains_from_blender_ik(arm):
    """Create ADM chains from two-bone Blender IK constraints. Returns (created ids, messages)."""
    sk = arm.data.adm
    created, notes = [], []
    existing = {c.end for c in sk.ik_chains}
    ids = {c.chain_id for c in sk.ik_chains}
    m = arm.matrix_world
    bones = arm.data.bones
    tmpl = {t["end"]: t for t in SP.ik_templates(sk.profile_id.strip())}
    for pb in arm.pose.bones:
        for con in pb.constraints:
            if con.type != "IK":
                continue
            tri = ik_triplet(pb, con)
            if tri is None:
                notes.append(f"'{pb.name}': IK constraint skipped (ADM-IK-1 is two-bone only, "
                             f"chain_count={con.chain_count})")
                continue
            if tri[2] in existing:
                continue
            root, mid, end = (bones[n] for n in tri)
            role = end.adm.role
            cid = tmpl[role]["id"] if role in tmpl else "".join(ch if ch.isalnum() else "_" for ch in end.name)
            if not cid[:1].isalpha():
                cid = "ik_" + cid
            base, k = cid, 2
            while cid in ids:
                cid, k = f"{base}_{k}", k + 1
            c = sk.ik_chains.add()
            c.chain_id = cid
            ids.add(cid)
            existing.add(end.name)
            c.root, c.mid, c.end = root.name, mid.name, end.name
            A, B, C = root.head_local, mid.head_local, end.head_local
            pole = None
            if con.pole_target is not None:
                pt = m.inverted_safe() @ (con.pole_target.matrix_world.translation if not con.pole_subtarget else
                                          con.pole_target.matrix_world @ con.pole_target.pose.bones[
                                              con.pole_subtarget].head)
                u = (C - A).normalized()
                v = (pt - A) - u * (pt - A).dot(u)
                if v.length > 1e-9:
                    pole = v.normalized()
                notes.append(f"'{pb.name}': pole angle {math.degrees(con.pole_angle):.1f} deg is a Blender twist "
                             "setting and is not exported")
            if pole is None:
                if role in tmpl:
                    pole = pole_from_adm(arm, tmpl[role]["pole"])
                else:
                    u = (C - A).normalized()
                    v = (B - A) - u * (B - A).dot(u)
                    pole = v.normalized() if v.length > 1e-9 else Vector((0.0, -1.0, 0.0))
            c.pole = pole
            created.append(c.chain_id)
    sort_chains(arm)
    return created, notes


def _world_q(m):
    q = m.to_quaternion()
    q.normalize()
    return (q.x, q.y, q.z, q.w)


def _bl_q(t):
    return Quaternion((t[3], t[0], t[1], t[2]))


def preview_ik(context, arm, chains=None):
    """Evaluate ADM-IK-1 (core solver) for chains with a preview target and write the pose.

    Works in armature space (a rigid transform of model space, so the solution is identical).
    Returns [(chain id, status, error)].
    """
    results = []
    context.view_layer.update()
    inv = arm.matrix_world.inverted_safe()
    for c in sorted(chains or arm.data.adm.ik_chains, key=lambda c: c.chain_id):
        if c.target is None or not all(n in arm.pose.bones for n in (c.root, c.mid, c.end)):
            continue
        pr, pm, pe = arm.pose.bones[c.root], arm.pose.bones[c.mid], arm.pose.bones[c.end]
        A, B, C = pr.head.copy(), pm.head.copy(), pe.head.copy()
        P = inv @ c.target.matrix_world.translation
        par = pr.parent.matrix if pr.parent is not None else Matrix.Identity(4)
        r = IK.solve_chain(tuple(A), tuple(B), tuple(C), _world_q(par), _world_q(pr.matrix), _world_q(pm.matrix),
                           tuple(P), tuple(Vector(c.pole).normalized()), c.weight)
        if r["status"] == IK.INVALID:
            results.append((c.chain_id, IK.INVALID, float("nan")))
            continue
        root_w = _bl_q(r["root_world"])
        mid_w = _bl_q(r["mid_world"])
        mr = Matrix.LocRotScale(pr.matrix.translation, root_w, pr.matrix.to_scale())
        pr.matrix = mr
        context.view_layer.update()
        mm = Matrix.LocRotScale(pm.matrix.translation, mid_w, pm.matrix.to_scale())
        pm.matrix = mm
        context.view_layer.update()
        results.append((c.chain_id, r["status"], (arm.pose.bones[c.end].head - P).length))
    return results


def reset_chain_pose(arm, chains=None):
    for c in chains or arm.data.adm.ik_chains:
        for n in (c.root, c.mid):
            pb = arm.pose.bones.get(n)
            if pb is not None:
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                pb.rotation_euler = (0.0, 0.0, 0.0)


def ensure_preview_target(context, arm, chain):
    if chain.target is not None:
        return chain.target
    obj = bpy.data.objects.new(f"IKT_{arm.name}_{chain.chain_id}", None)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.05
    obj["adm_editor_only"] = True
    (context.collection or context.scene.collection).objects.link(obj)
    pe = arm.pose.bones.get(chain.end)
    obj.matrix_world = Matrix.Translation(arm.matrix_world @ (pe.head if pe else Vector()))
    chain.target = obj
    return obj


# --------------------------------------------------------------------------------------------------
# sockets
# --------------------------------------------------------------------------------------------------
def create_profile_sockets(context, arm):
    """Create attachment empties for the profile's socket templates.

    The socket frame is axis-aligned with the ADM reference pose (identity rotation in model space) at
    the role joint origin, so it is portable between rigs whose bone rolls differ.
    """
    from .export_adm import find_model_root as _root  # noqa: F401 (keeps import local for clarity)
    rb = role_bone_map(arm)
    existing = {o.adm.attachment_name for o in bpy.data.objects if o.adm.adm_type == "ATTACHMENT"}
    existing |= {b.adm.attachment_name for b in arm.data.bones if b.adm.attachment_name}
    created, skipped = [], []
    mm = model_matrix(arm)
    model_to_world = arm.matrix_world @ mm.inverted_safe()
    for t in SP.socket_templates(arm.data.adm.profile_id.strip()):
        role = t["role"] if t["role"] in rb else next((r for r in t.get("fallback", []) if r in rb), None)
        if role is None:
            skipped.append(f"{t['name']} (role {t['role']} not mapped)")
            continue
        if t["name"] in existing:
            skipped.append(f"{t['name']} (exists)")
            continue
        bone = arm.data.bones[rb[role]]
        obj = bpy.data.objects.new("ATT_" + t["name"], None)
        obj.empty_display_type = "ARROWS"
        obj.empty_display_size = 0.1
        obj.adm.adm_type = "ATTACHMENT"
        obj.adm.attachment_name = t["name"]
        (context.collection or context.scene.collection).objects.link(obj)
        head_world = arm.matrix_world @ bone.head_local
        rot_world = model_to_world.to_quaternion()
        obj.parent = arm
        obj.parent_type = "BONE"
        obj.parent_bone = bone.name
        context.view_layer.update()
        obj.matrix_world = Matrix.LocRotScale(head_world, rot_world, Vector((1.0, 1.0, 1.0)))
        created.append(t["name"])
    return created, skipped
