"""Physical surface type lookup helpers."""

import copy

from . import constants as K


def resolve_type_id(type_id):
    """Return a registered type ID, or the registry's unknown-type fallback."""
    if isinstance(type_id, str) and type_id in K.PHYSICAL_SURFACE_TYPES:
        return type_id
    return K.PHYSICAL_SURFACE_REGISTRY["unknownType"]


def query_physical_material(document, collider_index, primitive_index=None, triangle_index=None):
    """Resolve the physical material for a collider or one of its mesh triangles."""
    if not isinstance(document, dict):
        raise TypeError("document must be an object")
    if not isinstance(collider_index, int) or isinstance(collider_index, bool):
        raise TypeError("collider_index must be an integer")
    colliders = document.get("colliders", [])
    if not isinstance(colliders, list) or not 0 <= collider_index < len(colliders):
        raise IndexError("collider_index is out of range")
    collider = colliders[collider_index]
    if not isinstance(collider, dict):
        raise ValueError("collider record must be an object")
    shape = collider.get("shape")
    if shape not in {"BOX", "SPHERE", "CAPSULE", "MESH"}:
        raise ValueError("collider shape must be BOX, SPHERE, CAPSULE, or MESH")
    if shape != "MESH":
        if primitive_index is not None or triangle_index is not None:
            raise ValueError("primitive and triangle indices apply only to MESH colliders")
        return _material_record(document, collider.get("physicalMaterial"))
    if primitive_index is None and triangle_index is None:
        return _material_record(document, collider.get("physicalMaterial"))
    if primitive_index is None or triangle_index is None:
        raise ValueError("primitive_index and triangle_index must be provided together")
    if not isinstance(primitive_index, int) or isinstance(primitive_index, bool):
        raise TypeError("primitive_index must be an integer")
    if not isinstance(triangle_index, int) or isinstance(triangle_index, bool):
        raise TypeError("triangle_index must be an integer")

    meshes = document.get("meshes", [])
    mesh_index = collider.get("mesh")
    if not isinstance(meshes, list) or not isinstance(mesh_index, int) or isinstance(mesh_index, bool) \
            or not 0 <= mesh_index < len(meshes):
        raise ValueError("MESH collider must reference an existing mesh")
    mesh = meshes[mesh_index]
    primitives = mesh.get("primitives") if isinstance(mesh, dict) else None
    if not isinstance(primitives, list) or not 0 <= primitive_index < len(primitives):
        raise IndexError("primitive_index is out of range")
    primitive = primitives[primitive_index]
    accessors = document.get("accessors", [])
    indices = primitive.get("indices") if isinstance(primitive, dict) else None
    if not isinstance(accessors, list) or not isinstance(indices, int) or isinstance(indices, bool) \
            or not 0 <= indices < len(accessors):
        raise ValueError("primitive must reference an existing indices accessor")
    accessor = accessors[indices]
    index_count = accessor.get("count") if isinstance(accessor, dict) else None
    if not isinstance(index_count, int) or isinstance(index_count, bool) or index_count % 3:
        raise ValueError("primitive indices accessor must describe a triangle list")
    if not 0 <= triangle_index < index_count // 3:
        raise IndexError("triangle_index is out of range")

    material_id = collider.get("physicalMaterial")
    extensions = primitive.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("primitive extensions must be an object")
    physical_extension = extensions.get(K.PHYSICAL_SURFACES_EXT)
    if physical_extension is not None:
        face_materials = physical_extension.get("faceMaterials") if isinstance(physical_extension, dict) else None
        if not isinstance(face_materials, list) or len(face_materials) != index_count // 3:
            raise ValueError("faceMaterials must contain one ID per primitive triangle")
        material_id = face_materials[triangle_index]
    return _material_record(document, material_id)


def _material_record(document, material_id):
    if material_id is None:
        return None
    materials = document.get("physicalMaterials", [])
    if not isinstance(materials, list):
        raise ValueError("physicalMaterials must be an array")
    matches = [record for record in materials if isinstance(record, dict) and record.get("id") == material_id]
    if len(matches) != 1:
        raise ValueError(f"physical material reference {material_id!r} must resolve to one record")
    return copy.deepcopy(matches[0])
