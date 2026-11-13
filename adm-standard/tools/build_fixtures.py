#!/usr/bin/env python3
"""Rebuild Draft 0.4 fixtures from checked-in manifests and explicit payloads."""

import argparse
import copy
import json
from pathlib import Path
import shutil
import struct

from container import create, verify


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def build_fixtures(output_dir):
    valid = output_dir / "valid"
    invalid = output_dir / "invalid"
    valid.mkdir(parents=True, exist_ok=True)
    invalid.mkdir(parents=True, exist_ok=True)

    positions = struct.pack("<9f", -1, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    tracks = struct.pack("<6f", 0, 2, 0, 1, 0.45, 0.8)
    samples = (
        ("triangle", "adm", b"ADM0", [(1, b"GEOM", positions + indices, True)]),
        ("triangle_split", "adm", b"ADM0",
         [(1, b"GEOM", positions, True), (2, b"GEOM", indices, True)]),
        ("shader_layered", "adm", b"ADM0", [(1, b"GEOM", positions + indices, True)]),
        ("catalog-only", "adm_anim", b"AMA0", []),
        ("shader_parameter_tracks", "adm_anim", b"AMA0", [(1, b"ANIM", tracks, True)]),
    )
    manifests = {}
    for name, extension, magic, chunks in samples:
        source = FIXTURES / "valid" / f"{name}.json"
        manifest = json.loads(source.read_text(encoding="utf-8"))
        manifests[name] = manifest
        path = valid / f"{name}.{extension}"
        create(path, magic, manifest, chunks)
        if source.resolve() != (valid / source.name).resolve():
            shutil.copyfile(source, valid / source.name)
        print(verify(path))

    base = (valid / "triangle.adm").read_bytes()
    bad = bytearray(base)
    bad[8] = 0
    (invalid / "bad_header_size.adm").write_bytes(bad)
    bad = bytearray(base)
    bad[-17] ^= 0x01
    (invalid / "bad_hash.adm").write_bytes(bad)
    bad = bytearray(base)
    struct.pack_into("<Q", bad, 16, len(bad) + 1)
    (invalid / "bad_file_size.adm").write_bytes(bad)
    bad = bytearray(base)
    directory = struct.unpack_from("<Q", bad, 40)[0]
    struct.pack_into("<Q", bad, directory + 24, 4)
    (invalid / "bad_chunk_offset.adm").write_bytes(bad)

    cyclic = {
        "asset": {}, "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
        "accessors": [], "bufferViews": [],
        "chunkDependencies": [{"chunkId": 1, "requires": [2]}, {"chunkId": 2, "requires": [1]}],
    }
    create(invalid / "bad_dependency_cycle.adm", b"ADM0", cyclic,
           [(1, b"DATA", b"A", True), (2, b"DATA", b"B", True)])

    missing_pbr = copy.deepcopy(manifests["shader_layered"])
    del missing_pbr["materials"][0]["roughnessFactor"]
    create(invalid / "bad_missing_pbr.adm", b"ADM0", missing_pbr,
           [(1, b"GEOM", positions + indices, True)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURES,
                        help="Destination fixture directory (default: checked-in fixtures)")
    build_fixtures(parser.parse_args().output_dir)
