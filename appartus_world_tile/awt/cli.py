"""Command line: ``python -m awt build ...`` and ``python -m awt gui``."""

from __future__ import annotations

import argparse
import math
import sys

from . import __version__


def _build(args: argparse.Namespace) -> int:
    from .heightmap import load_heightmap
    from .pipeline import BuildParams, build, estimate_memory, fit_material

    hm = load_heightmap(args.input, tuple(args.raw_size) if args.raw_size else None)
    spacing = args.spacing
    if args.size is not None:
        spacing = args.size / (hm.width - 1)
    tile_cells = args.tile_cells
    if args.tile_m is not None:
        tile_cells = 1 << min(12, max(1, round(math.log2(max(2.0, args.tile_m / spacing)))))
    params = BuildParams(
        input_path=args.input,
        out_dir=args.out,
        spacing_m=spacing,
        height_min_m=args.height_range[0],
        height_max_m=args.height_range[1],
        remap_float=args.remap_float,
        tile_cells=tile_cells,
        max_errors_m=args.max_error,
        origin=args.origin,
        threads=args.threads,
        raw_size=tuple(args.raw_size) if args.raw_size else None,
        texture_error=args.texture_error,
        texture_detail_m=args.texture_detail,
    )
    params.validate()
    project = None
    if args.project:
        from .project import load_project

        project = load_project(args.project)
        material = project.material
    else:
        from .material import TerrainMaterial

        material = TerrainMaterial()
    if args.project is None or args.fit:
        levels = fit_material(hm, params, material, water_m=args.water_level, shore_m=args.shore,
                              snow_start_m=args.snow[0] if args.snow else None,
                              snow_full_m=args.snow[1] if args.snow else None)
        print(f"biome levels: water <= {levels['water_m']:g} m (+{levels['shore_m']:g} m shore), "
              f"snow {levels['snow_start_m']:g}..{levels['snow_full_m']:g} m")
    memory = estimate_memory(hm.width, hm.height, tile_cells, hm.data.itemsize)
    print(f"{hm.width} x {hm.height} samples, {spacing:g} m/sample, tile {tile_cells} cells "
          f"({tile_cells * spacing:g} m), working memory about {memory / 2**30:.2f} GiB")

    manifest = build(params, material, _progress_printer(), heightmap=hm)
    if args.save_project:
        from .project import Project

        if project is None:
            project = Project.new(args.input)
        project.params = params
        project.material = material
        project.save(args.save_project)
        print(f"\nproject saved to {project.path}", end="")
    unshared = manifest["texturing"].get("unshared_neighbours") or []
    if unshared:
        print("\nwarning: touching biomes without a shared surface (hard texture edge): "
              + ", ".join("-".join(pair) for pair in unshared), end="")
    print()
    for lod in manifest["lods"]:
        print(f"LOD {lod['index']}: max error {lod['max_error_m']:g} m, measured {lod['measured_error_m']:.4f} m, "
              f"{lod['triangles']:,} triangles, {lod['vertices']:,} vertices")
    timings = manifest["timings"]
    print(f"{manifest['tiles_x']} x {manifest['tiles_y']} tiles in {timings['total_s']:.1f} s "
          f"(errors {timings['errors_s']:.1f} s, tiles {timings['tiles_s']:.1f} s) -> {params.out_dir}")
    return 0


def _progress_printer():
    last = [-1]

    def progress(fraction: float, message: str) -> None:
        percent = int(fraction * 100)
        if percent != last[0]:
            last[0] = percent
            sys.stdout.write(f"\r[{percent:3d}%] {message:<48}")
            sys.stdout.flush()

    return progress


def _export(args: argparse.Namespace) -> int:
    from .adm_export import export_tiles
    from .pipeline import build, load_manifest
    from .project import load_project

    project = load_project(args.project)
    if args.out:
        project.export.out_dir = args.out
    if args.no_validate:
        project.export.validate = False
    if args.build:
        print(f"building {project.params.input_path} -> {project.params.out_dir}")
        build(project.params, project.material, _progress_printer())
        print()
    manifest = load_manifest(project.params.out_dir)
    mode = "all" if args.all else "selected" if args.tiles else "changed"
    result = export_tiles(manifest, project.material, project.export, mode, args.tiles, _progress_printer())
    print()
    print(f"{len(result['written'])} tiles written ({result['bytes'] / 2**20:,.1f} MiB), "
          f"{result['skipped']} unchanged or not selected, {result['seconds']:.1f} s -> {result['out_dir']}")
    if result["conflicts"]:
        print(f"note: {result['conflicts']:,} triangles needed more than four surfaces; the weakest were dropped")
    for warning in result["warnings"]:
        print(f"warning: {warning}")
    return 0


def _gui(args: argparse.Namespace) -> int:
    from .gui.app import run

    return run(args.path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awt", description="Apparatus World Tile " + __version__)
    sub = parser.add_subparsers(dest="command")

    b = sub.add_parser("build", help="tile a heightmap into PLY meshes and a manifest")
    b.add_argument("input", help="heightmap: PNG, TIFF, RAW 16-bit (.r16/.raw) or .npy")
    b.add_argument("-o", "--out", required=True, help="output directory")
    group = b.add_mutually_exclusive_group()
    group.add_argument("--spacing", type=float, default=1.0, help="metres between samples (default 1)")
    group.add_argument("--size", type=float, help="terrain width in metres (overrides --spacing)")
    b.add_argument("--height-range", type=float, nargs=2, default=[0.0, 500.0], metavar=("MIN", "MAX"),
                   help="metres for integer black..white (default 0 500)")
    b.add_argument("--remap-float", action="store_true", help="remap float heightmaps min..max to --height-range")
    tiles = b.add_mutually_exclusive_group()
    tiles.add_argument("--tile-cells", type=int, default=256, help="tile size in cells, power of two (default 256)")
    tiles.add_argument("--tile-m", type=float, help="approximate tile size in metres (rounded to a power of two)")
    b.add_argument("--max-error", type=float, nargs="+", default=[0.25], metavar="M",
                   help="max height error in metres, one value per LOD (default 0.25)")
    b.add_argument("--origin", choices=("corner", "center"), default="corner")
    b.add_argument("--threads", type=int, default=0, help="worker threads (default all cores)")
    b.add_argument("--raw-size", type=int, nargs=2, metavar=("W", "H"), help="RAW width and height")
    z = b.add_argument_group("texturing (biomes blend surfaces; COLOR_1 vertex weights)")
    z.add_argument("--project", metavar="FILE", help="take surfaces, biomes and paint from an .awtp project")
    z.add_argument("--fit", action="store_true", help="with --project: re-fit biome heights to this heightmap")
    z.add_argument("--water-level", type=float, help="water surface height, metres (default from the heights)")
    z.add_argument("--shore", type=float, help="shore band above the water level, metres")
    z.add_argument("--snow", type=float, nargs=2, metavar=("START", "FULL"), help="snow fade-in heights, metres")
    z.add_argument("--texture-error", type=float, default=0.15,
                   help="split triangles where vertex weights miss the field by more than this (0..1, 0 = off)")
    z.add_argument("--texture-detail", type=float, default=4.0, metavar="M",
                   help="shortest triangle leg the texture split may create, metres (default 4)")
    b.add_argument("--save-project", metavar="FILE", help="also save these settings as an .awtp project")
    b.set_defaults(func=_build)

    e = sub.add_parser("export", help="write ADM tiles with the project's four_layer@2.0.0 materials")
    e.add_argument("project", help=".awtp project file")
    which = e.add_mutually_exclusive_group()
    which.add_argument("--all", action="store_true", help="export every tile (default: only changed tiles)")
    which.add_argument("--tiles", nargs="+", metavar="ID", help="export these tiles, e.g. x000_y001")
    e.add_argument("--build", action="store_true", help="rebuild the tiles from the heightmap first")
    e.add_argument("-o", "--out", help="export folder (default: the one stored in the project)")
    e.add_argument("--no-validate", action="store_true", help="skip ADM validation of written files")
    e.set_defaults(func=_export)

    g = sub.add_parser("gui", help="open the visual editor and 3D viewer")
    g.add_argument("path", nargs="?", help="project (.awtp), heightmap or manifest.json to open")
    g.set_defaults(func=_gui)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return _gui(argparse.Namespace(path=None))
    try:
        return args.func(args)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
