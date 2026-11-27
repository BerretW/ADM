"""Build a standalone World Tile ZIP from the current checkout."""

import argparse
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path("appartus_world_tile/reference_project/advanced_material_reference.adm")
INPUTS = (
    "LICENSE",
    "adm_blender/__init__.py",
    "adm_blender/core",
    "appartus_world_tile/README.md",
    "appartus_world_tile/pyproject.toml",
    "appartus_world_tile/run_gui.bat",
    "appartus_world_tile/awt",
    "appartus_world_tile/reference_project",
    "appartus_world_tile/tools/render_advanced_reference.py",
)


def build(output: Path) -> int:
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", *INPUTS]
    ).decode("utf-8").split("\0")
    paths = {Path(path) for path in tracked if path}
    paths.add(REFERENCE)
    if not (ROOT / REFERENCE).is_file():
        raise FileNotFoundError(f"Missing bundled reference ADM: {ROOT / REFERENCE}")
    for path in paths:
        if not (ROOT / path).is_file() or (ROOT / path).is_symlink():
            raise ValueError(f"Packaging input is missing or is a symlink: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths, key=lambda value: value.as_posix()):
            info = zipfile.ZipInfo(path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (ROOT / path).read_bytes(), compresslevel=9)
    return len(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="ZIP path; must not already exist")
    args = parser.parse_args()
    count = build(args.output)
    print(f"Built {args.output} with {count} files")


if __name__ == "__main__":
    main()
