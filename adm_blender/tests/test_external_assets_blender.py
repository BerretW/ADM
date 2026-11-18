"""Run the generated, reference, and opt-in external asset catalog in Blender."""

import argparse
import os
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402
import adm_blender  # noqa: E402
from adm_blender.tests.external_asset_catalog import FORMATS, discover, permission  # noqa: E402
from adm_blender.core.validate import validate_file  # noqa: E402
from adm_blender.blender.import_adm import ModelImporter  # noqa: E402


def result(status, label, reason):
    print(f"{status}: {label}: {reason}", flush=True)


def reset():
    bpy.ops.wm.read_homefile(use_empty=True)


def validate(path):
    report = validate_file(str(path))
    if not report.ok:
        raise ValueError("; ".join(str(issue) for issue in report.errors[:4]))


def generated():
    reset()
    mesh = bpy.data.meshes.new("generated_triangle")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("generated_triangle", mesh)
    bpy.context.scene.collection.objects.link(obj)
    if len(obj.data.vertices) != 3 or len(obj.data.polygons) != 1:
        raise ValueError("generated triangle geometry is incorrect")
    return "in-memory triangle geometry created"


def reference():
    reset()
    path = REPO / "adm-standard" / "fixtures" / "valid" / "triangle.adm"
    validate(path)
    if ModelImporter(bpy.context, str(path)).run() is None:
        raise ValueError("reference model import returned no root")
    return "triangle.adm validated and imported"


def process(kind, path):
    reset()
    if kind == "ADM":
        validate(path)
        if ModelImporter(bpy.context, str(path)).run() is None:
            raise ValueError("model import returned no root")
        return "validated and imported as ADM model"
    if kind == "ADM_ANIM":
        validate(path)
        result("PASS", f"{kind} validation ({path.name})", "animation container and schema valid")
        return None
    if kind == "FBX":
        if not hasattr(bpy.ops.import_scene, "fbx"):
            return None
        outcome = bpy.ops.import_scene.fbx(filepath=str(path))
        if "FINISHED" not in outcome:
            raise ValueError(f"FBX importer returned {outcome}")
        if not bpy.context.scene.objects:
            raise ValueError("FBX import produced no scene objects")
        return "FBX imported into an empty scene"
    if kind == "BLEND":
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            target.objects = source.objects
        objects = [obj for obj in target.objects if obj is not None]
        if not objects:
            raise ValueError("BLEND library contains no loadable objects")
        for obj in objects:
            bpy.context.scene.collection.objects.link(obj)
        return f"appended {len(objects)} object(s) without opening the file"
    raise ValueError(f"unknown format {kind}")


def run(directory):
    failures = 0
    adm_blender.register()
    for name, operation in (("generated", generated), ("reference", reference)):
        try:
            result("PASS", name, operation())
        except Exception as exc:
            traceback.print_exc()
            result("FAIL", name, str(exc))
            failures += 1
    for kind, files in discover(directory).items():
        if not files:
            result("SKIP", kind, f"no {FORMATS[kind]} files in {directory}")
        for path in files:
            allowed, reason = permission(path)
            if not allowed:
                result("SKIP", kind, f"{path.name}: {reason}")
                continue
            try:
                detail = process(kind, path)
                if detail is None:
                    reason = ("binding/import not tested: no compatible target is configured"
                              if kind == "ADM_ANIM" else "Blender FBX importer is unavailable")
                    result("SKIP", kind, f"{path.name}: {reason}")
                else:
                    result("PASS", kind, f"{path.name}: {detail}")
            except Exception as exc:
                traceback.print_exc()
                result("FAIL", kind, f"{path.name}: {type(exc).__name__}: {exc}")
                failures += 1
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-dir", type=Path, default=HERE / "external_data",
                        help="Directory containing optional external assets and rights sidecars")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    return 1 if run(args.external_dir) else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        result("FAIL", "catalog", "unexpected error")
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
