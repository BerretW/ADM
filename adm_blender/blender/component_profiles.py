"""Model-root component profile bindings shared by animation import and export."""

from ..core.container import AdmFormatError, parse_json_strict


def component_model_binding(root, profile_id):
    if root is None or root.type != "EMPTY" or root.adm.adm_type != "MODEL":
        raise ValueError("select an ADM Model Root")
    try:
        wrapper = '{"modelProfiles":' + (root.adm.model_profiles_json or "[]") + "}"
        profiles = parse_json_strict(wrapper.encode("utf-8"))["modelProfiles"]
    except (AdmFormatError, UnicodeError) as exc:
        raise ValueError(f"model root has invalid Model Profiles JSON: {exc}") from exc
    if not isinstance(profiles, list):
        raise ValueError("modelProfiles must be a JSON array")
    matches = [entry for entry in profiles
               if isinstance(entry, dict) and entry.get("id") == profile_id]
    if len(matches) != 1:
        raise ValueError(f"model root must declare exactly one {profile_id} profile")
    profile = matches[0]
    if (not isinstance(profile.get("schemaVersion"), int) or isinstance(profile["schemaVersion"], bool)
            or profile["schemaVersion"] != 1 or not isinstance(profile.get("metadata"), dict)):
        raise ValueError(f"model root must declare {profile_id} schemaVersion 1 metadata")
    metadata = profile["metadata"]
    components = {}
    for obj in root.children_recursive:
        props = obj.adm
        role = props.component_role.strip()
        if not role or props.component_profile != profile_id:
            continue
        if role in components:
            raise ValueError(f"duplicate component role {role!r}")
        components[role] = obj
    if profile_id == "vehicle.car.v1":
        required = {"chassis"}
        axles = metadata.get("axles")
        if isinstance(axles, list) and len(axles) >= 2:
            if any(not isinstance(axle, dict) or axle.get("index") != index
                   or isinstance(axle.get("index"), bool) for index, axle in enumerate(axles)):
                raise ValueError("vehicle.car.v1 axles must have consecutive indexes from zero")
            for index in range(len(axles)):
                for side in ("left", "right"):
                    required.add(f"wheel.axle{index}.{side}")
        else:
            raise ValueError("vehicle.car.v1 metadata must declare at least two axles")
    elif profile_id == "weapon.firearm.v1":
        if metadata.get("feedType") not in ("DETACHABLE_MAGAZINE", "INTERNAL", "OTHER", "NONE"):
            raise ValueError("weapon.firearm.v1 metadata must declare a valid feedType")
        required = {"weapon.receiver", "weapon.muzzle"}
        if metadata.get("feedType") == "DETACHABLE_MAGAZINE":
            required.add("weapon.magazine")
    else:
        raise ValueError(f"unsupported component profile {profile_id!r}")
    missing = sorted(required - components.keys())
    if missing:
        raise ValueError("model root is missing required component roles: " + ", ".join(missing))
    return metadata, components


def component_rest_issues(root, components, *, tolerance=1e-5):
    root_inverse = root.matrix_world.inverted_safe()
    issues = []
    for role, obj in components.items():
        _location, rotation, scale = obj.matrix_basis.decompose()
        if any(abs(value - 1.0) > tolerance for value in scale):
            issues.append(f"{role!r} rest scale must be unit")
        if (abs(rotation.x) > tolerance or abs(rotation.y) > tolerance or abs(rotation.z) > tolerance
                or abs(abs(rotation.w) - 1.0) > tolerance):
            issues.append(f"{role!r} rest rotation must be identity")
        frame = (root_inverse @ obj.matrix_world).to_3x3()
        for axis in range(3):
            vector = frame.col[axis]
            if vector.length <= tolerance:
                issues.append(f"{role!r} rest frame has a zero axis")
                break
            vector.normalize()
            if any(abs(vector[index] - (1.0 if index == axis else 0.0)) > tolerance
                   for index in range(3)):
                issues.append(f"{role!r} rest axes must align with the profile frame")
                break
    return issues


def snapshot_component_transform(obj):
    return (obj.rotation_mode, obj.location.copy(), obj.rotation_euler.copy(),
            obj.rotation_quaternion.copy(), tuple(obj.rotation_axis_angle), obj.scale.copy())


def restore_component_transform(obj, snapshot):
    mode, location, euler, quaternion, axis_angle, scale = snapshot
    obj.rotation_mode = mode
    obj.location = location
    obj.rotation_euler = euler
    obj.rotation_quaternion = quaternion
    obj.rotation_axis_angle = axis_angle
    obj.scale = scale
