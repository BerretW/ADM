"""``.awtp`` project files: everything needed to rebuild, retexture and re-export a world.

The file is JSON. Paths are stored relative to the project file when possible, so a project
folder can be moved or shared together with its heightmap and textures.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from . import __version__
from .adm_export import ExportSettings
from .masks import ZoneRules
from .material import TerrainMaterial
from .pipeline import BuildParams

PROJECT_FORMAT = "apparatus-world-tile-project"
PROJECT_VERSION = 1
PROJECT_EXTENSION = ".awtp"
PROJECT_FILTER = "Apparatus World Tile project (*.awtp)"


@dataclass
class Project:
    params: BuildParams
    material: TerrainMaterial = field(default_factory=TerrainMaterial)
    export: ExportSettings = field(default_factory=ExportSettings)
    selection: list[str] = field(default_factory=list)  # tile ids
    path: str = ""

    @classmethod
    def new(cls, heightmap: str = "") -> "Project":
        base = os.path.splitext(heightmap)[0] if heightmap else ""
        return cls(params=BuildParams(input_path=heightmap, out_dir=base + "_tiles" if base else ""),
                   export=ExportSettings(out_dir=base + "_adm" if base else ""))

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0] if self.path else "Untitled"

    def to_dict(self) -> dict:
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else None
        params = asdict(self.params)
        params["input_path"] = _relative(self.params.input_path, base)
        params["out_dir"] = _relative(self.params.out_dir, base)
        params["zones"] = self.params.zones.to_dict()
        if params["raw_size"] is not None:
            params["raw_size"] = list(params["raw_size"])
        export = asdict(self.export)
        export["out_dir"] = _relative(self.export.out_dir, base)
        return {
            "format": PROJECT_FORMAT,
            "format_version": PROJECT_VERSION,
            "generator": f"appartus_world_tile {__version__}",
            "build": params,
            "material": self.material.to_dict(base),
            "export": export,
            "selection": sorted(self.selection),
        }

    @classmethod
    def from_dict(cls, data: dict, path: str = "") -> "Project":
        if data.get("format") != PROJECT_FORMAT:
            raise ValueError("Not an Apparatus World Tile project")
        if int(data.get("format_version", 0)) > PROJECT_VERSION:
            raise ValueError(f"Project version {data['format_version']} is newer than this tool")
        base = os.path.dirname(os.path.abspath(path)) if path else None
        raw = dict(data.get("build") or {})
        fields = BuildParams.__dataclass_fields__
        params = BuildParams(input_path="", out_dir="")
        for key, value in raw.items():
            if key in fields and key not in ("zones", "input_path", "out_dir", "raw_size"):
                setattr(params, key, type(getattr(params, key))(value) if not isinstance(value, list) else
                        [float(v) for v in value])
        params.input_path = _absolute(raw.get("input_path"), base)
        params.out_dir = _absolute(raw.get("out_dir"), base)
        size = raw.get("raw_size")
        params.raw_size = (int(size[0]), int(size[1])) if isinstance(size, list) and len(size) == 2 else None
        params.zones = ZoneRules.from_dict(raw.get("zones") or {})
        export = ExportSettings()
        for key, value in (data.get("export") or {}).items():
            if key in ExportSettings.__dataclass_fields__ and key != "out_dir":
                setattr(export, key, type(getattr(export, key))(value))
        export.out_dir = _absolute((data.get("export") or {}).get("out_dir"), base)
        selection = [s for s in data.get("selection", []) if isinstance(s, str)]
        return cls(params=params, material=TerrainMaterial.from_dict(data.get("material") or {}, base),
                   export=export, selection=selection, path=os.path.abspath(path) if path else "")

    def save(self, path: str | None = None) -> None:
        if path:
            if not path.lower().endswith(PROJECT_EXTENSION):
                path += PROJECT_EXTENSION
            self.path = os.path.abspath(path)
        if not self.path:
            raise ValueError("The project has no file name yet")
        text = json.dumps(self.to_dict(), indent=1)
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, self.path)


def load_project(path: str) -> Project:
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as exc:
            raise ValueError(f"{path}: not a valid project file ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a valid project file")
    return Project.from_dict(data, path)


def _relative(path: str, base: str | None) -> str:
    if not path or base is None:
        return path
    try:
        return os.path.relpath(os.path.abspath(path), base).replace("\\", "/")
    except ValueError:  # another drive on Windows
        return os.path.abspath(path)


def _absolute(path, base: str | None) -> str:
    if not isinstance(path, str) or not path:
        return ""
    if os.path.isabs(path) or base is None:
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base, path))
