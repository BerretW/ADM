"""Profile-specific checks for sampled mechanical component animation."""

import math
import re


_WHEEL_ROLE = re.compile(r"^wheel\.axle([0-9]+)\.(left|right)$")
_STEERING_ROLE = re.compile(r"^steering\.axle([0-9]+)\.(left|right)$")
_SUSPENSION_ROLE = re.compile(r"^suspension\.axle([0-9]+)\.(left|right)$")


def sample_track_values(times, values, interpolation, in_tangents=None, out_tangents=None,
                        *, rotation=False, subdivisions=32):
    """Return bounded samples at keys and within each segment for profile-limit checks."""
    if len(times) == 0:
        return []
    samples = [tuple(values[0])]
    for index in range(len(times) - 1):
        duration = times[index + 1] - times[index]
        for step in range(1, subdivisions + 1):
            u = step / subdivisions
            if interpolation == "STEP":
                value = values[index] if step < subdivisions else values[index + 1]
            elif interpolation == "LINEAR" and rotation:
                value = _slerp(values[index], values[index + 1], u)
            elif interpolation == "LINEAR":
                value = tuple(a * (1.0 - u) + b * u
                              for a, b in zip(values[index], values[index + 1]))
            elif interpolation == "CUBICSPLINE":
                u2, u3 = u * u, u * u * u
                h00, h10 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u
                h01, h11 = -2 * u3 + 3 * u2, u3 - u2
                value = tuple(h00 * a + h10 * duration * ta + h01 * b + h11 * duration * tb
                              for a, ta, b, tb in zip(values[index], out_tangents[index],
                                                      values[index + 1], in_tangents[index + 1]))
                if rotation:
                    value = _normalize_quaternion(value)
            else:
                raise ValueError(f"unsupported interpolation {interpolation!r}")
            samples.append(tuple(value))
    return samples


def component_track_issues(profile_id, metadata, role, path, values, *, tolerance=1e-5):
    """Validate sampled ADM delta values against a vehicle/firearm profile contract."""
    if not isinstance(role, str):
        return ["component role must be a string"]
    if not isinstance(metadata, dict):
        return ["component profile metadata must be an object"]
    if profile_id == "vehicle.car.v1":
        rule = _vehicle_rule(metadata, role)
    elif profile_id == "weapon.firearm.v1":
        rule = _weapon_rule(metadata, role)
    else:
        return [f"component profile {profile_id!r} has no ADM 1.0 animation contract"]
    if rule is None:
        return [f"role {role!r} has no animated component contract in {profile_id}"]
    constraint = rule.get(path)
    if constraint is None:
        return [f"{role!r} does not permit {path} animation"]
    axis, low, high, signed_limit = constraint
    issues = []
    for index, value in enumerate(values):
        if path == "translation":
            if len(value) != 3 or any(not math.isfinite(x) for x in value):
                issues.append(f"sample {index} is not a finite vec3")
                continue
            if axis is not None and any(
                    abs(value[i] - (value[axis] if i == axis else 0.0)) > tolerance for i in range(3)):
                issues.append(f"sample {index} moves outside the declared local axis")
                break
            if axis is not None:
                amount = value[axis]
                if ((low is not None and amount < low - tolerance)
                        or (high is not None and amount > high + tolerance)):
                    issues.append(f"sample {index} translation {amount:g} is outside [{low:g}, {high:g}]")
                    break
        else:
            angle, error = _axis_angle(value, axis, tolerance)
            if error is not None:
                issues.append(f"sample {index} {error}")
                break
            if signed_limit is not None:
                if angle * signed_limit < -tolerance or abs(angle) > abs(signed_limit) + tolerance:
                    issues.append(f"sample {index} rotation {angle:g} exceeds signed limit {signed_limit:g}")
                    break
            elif ((low is not None and angle < low - tolerance)
                  or (high is not None and angle > high + tolerance)):
                issues.append(f"sample {index} rotation {angle:g} is outside [{low:g}, {high:g}]")
                break
    return issues


def _vehicle_rule(metadata, role):
    match = _WHEEL_ROLE.fullmatch(role)
    if match:
        if _axle(metadata, int(match.group(1))) is None:
            return None
        return {"rotation": (0, None, None, None)}
    match = _STEERING_ROLE.fullmatch(role)
    if match:
        axle = _axle(metadata, int(match.group(1)))
        if axle is None:
            return None
        limit = axle.get("steeringAngleRad", 0.0)
        if not isinstance(limit, (int, float)) or isinstance(limit, bool) or not math.isfinite(limit) or limit < 0:
            return None
        return {"rotation": (1, -limit, limit, None)}
    match = _SUSPENSION_ROLE.fullmatch(role)
    if match:
        if _axle(metadata, int(match.group(1))) is None:
            return None
        return {"translation": (1, None, None, None)}
    if role == "steering.wheel":
        return {"rotation": (2, None, None, None)}
    if role.startswith("door.") or role in ("hood", "trunk"):
        hinges = metadata.get("hinges", [])
        hinge = next((entry for entry in hinges if isinstance(entry, dict) and entry.get("role") == role), None) \
            if isinstance(hinges, list) else None
        angle = hinge.get("openAngleRad") if hinge is not None else None
        if (not isinstance(angle, (int, float)) or isinstance(angle, bool) or not math.isfinite(angle)
                or angle == 0):
            return None
        return {"rotation": (1 if role.startswith("door.") else 0,
                             None, None, angle)}
    return None


def _weapon_rule(metadata, role):
    articulations = metadata.get("articulations", [])
    articulation = next((entry for entry in articulations
                         if isinstance(entry, dict) and entry.get("role") == role), None) \
        if isinstance(articulations, list) else None
    if articulation is not None:
        allowed = articulation.get("allowed")
        if allowed not in ("TRANSLATION", "ROTATION", "BOTH"):
            return None
        axes = {"X": 0, "Y": 1, "Z": 2}
        paths = {}
        if allowed in ("TRANSLATION", "BOTH"):
            if articulation.get("translationAxis") not in axes:
                return None
            axis = axes[articulation["translationAxis"]]
            low, high = articulation.get("translationMin"), articulation.get("translationMax")
            if not _valid_range(low, high):
                return None
            paths["translation"] = (axis, low, high, None)
        if allowed in ("ROTATION", "BOTH"):
            if articulation.get("rotationAxis") not in axes:
                return None
            axis = axes[articulation["rotationAxis"]]
            low, high = articulation.get("rotationMinRad"), articulation.get("rotationMaxRad")
            if not _valid_range(low, high):
                return None
            paths["rotation"] = (axis, low, high, None)
        return paths
    if role in ("weapon.bolt", "weapon.slide", "weapon.charging_handle"):
        return {"translation": (2, None, None, None)}
    if role in ("weapon.trigger", "weapon.safety"):
        return {"rotation": (0, None, None, None)}
    if role == "weapon.magazine":
        return {"translation": (None, None, None, None), "rotation": (None, None, None, None)}
    return None


def _axle(metadata, index):
    axles = metadata.get("axles", [])
    if isinstance(axles, list) and 0 <= index < len(axles):
        axle = axles[index]
        if isinstance(axle, dict) and axle.get("index") == index:
            return axle
    return None


def _valid_range(low, high):
    return (isinstance(low, (int, float)) and not isinstance(low, bool)
            and isinstance(high, (int, float)) and not isinstance(high, bool)
            and math.isfinite(low) and math.isfinite(high) and low <= 0 <= high and low <= high)


def _axis_angle(quaternion, axis, tolerance):
    if len(quaternion) != 4 or any(not math.isfinite(x) for x in quaternion):
        return 0.0, "is not a finite quaternion"
    norm = math.sqrt(sum(x * x for x in quaternion))
    if abs(norm - 1.0) > 2e-3:
        return 0.0, "is not a unit quaternion"
    x, y, z, w = (component / norm for component in quaternion)
    vector = (x, y, z)
    if w < 0:
        vector = tuple(-component for component in vector)
        w = -w
    if axis is not None and any(
            abs(vector[i] - (vector[axis] if i == axis else 0.0)) > tolerance for i in range(3)):
        return 0.0, "rotates outside the declared local axis"
    if axis is None:
        return 2.0 * math.atan2(math.sqrt(sum(component * component for component in vector)), w), None
    return 2.0 * math.atan2(vector[axis], w), None


def _normalize_quaternion(value):
    norm = math.sqrt(sum(component * component for component in value))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise ValueError("cubic quaternion sample has zero length")
    return tuple(component / norm for component in value)


def _slerp(a, b, amount):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b = tuple(-x for x in b)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        return _normalize_quaternion(tuple(x * (1.0 - amount) + y * amount for x, y in zip(a, b)))
    theta = math.acos(dot)
    scale = math.sin(theta)
    return tuple((math.sin((1.0 - amount) * theta) * x + math.sin(amount * theta) * y) / scale
                 for x, y in zip(a, b))
