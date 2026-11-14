#!/usr/bin/env python3
"""Rebuild checked-in ADM fixtures from their manifests and verified chunk payloads."""

import argparse
import copy
import json
from pathlib import Path
import struct
import sys

TOOL_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = TOOL_DIR.parent / "fixtures"
sys.path.insert(0, str(TOOL_DIR))
from container import ENTRY, HEADER, create, verify


def load_source(binary_path, manifest_path):
    """Read a fixture's portable JSON and preserve its verified raw chunk payloads."""
    verify(binary_path)
    binary = binary_path.read_bytes()
    fields = HEADER.unpack_from(binary)
    magic, directory_offset, chunk_count = fields[0], fields[8], fields[9]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embedded_manifest = json.loads(binary[fields[6]:fields[6] + fields[7]].decode("utf-8"))
    if embedded_manifest != manifest:
        raise ValueError(f"{manifest_path}: JSON sidecar differs from embedded manifest")

    chunks = []
    for index in range(chunk_count):
        cid, chunk_type, flags, codec, reserved, offset, stored, raw_size, _digest = ENTRY.unpack_from(
            binary, directory_offset + index * ENTRY.size
        )
        if codec != 0 or reserved != 0 or stored != raw_size:
            raise ValueError(f"{binary_path}: fixture chunks must be uncompressed RAW data")
        chunks.append((cid, chunk_type, binary[offset:offset + stored], bool(flags & 1)))
    return magic, manifest, chunks


def source_pairs(source_root):
    """Yield every valid/profile fixture with its checked-in manifest sidecar."""
    for folder in ("valid", "profiles"):
        source_dir = source_root / folder
        for manifest_path in sorted(source_dir.glob("*.json")):
            stem = manifest_path.with_suffix("")
            binary_path = next((Path(str(stem) + suffix) for suffix in (".adm", ".adm_anim")
                                if Path(str(stem) + suffix).is_file()), None)
            if binary_path is None:
                raise FileNotFoundError(f"{manifest_path}: matching .adm or .adm_anim fixture is missing")
            yield folder, binary_path, manifest_path


def write_manifest(path, manifest):
    text = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def build_valid_fixtures(source_root, output_root):
    records = {}
    for folder, source_binary, source_manifest in source_pairs(source_root):
        magic, manifest, chunks = load_source(source_binary, source_manifest)
        relative_binary = source_binary.relative_to(source_root)
        relative_manifest = source_manifest.relative_to(source_root)
        output_binary = output_root / relative_binary
        output_manifest = output_root / relative_manifest
        output_binary.parent.mkdir(parents=True, exist_ok=True)
        output_manifest.parent.mkdir(parents=True, exist_ok=True)
        create(output_binary, magic, manifest, chunks)
        write_manifest(output_manifest, manifest)
        verify(output_binary)
        records[(folder, source_binary.stem)] = (magic, manifest, chunks, output_binary)
        print(f"Built {relative_binary.as_posix()}")
    return records


def build_invalid_fixtures(records, output_root):
    invalid_dir = output_root / "invalid"
    invalid_dir.mkdir(parents=True, exist_ok=True)

    triangle = bytearray(records[("valid", "triangle")][3].read_bytes())
    malformed = (
        ("bad_header_size.adm", lambda data: data.__setitem__(8, 0)),
        ("bad_hash.adm", lambda data: data.__setitem__(-17, data[-17] ^ 0x01)),
        ("bad_file_size.adm",
         lambda data: data.__setitem__(slice(16, 24), struct.pack("<Q", len(data) + 1))),
    )
    for name, mutate in malformed:
        data = bytearray(triangle)
        mutate(data)
        (invalid_dir / name).write_bytes(data)

    bad_offset = bytearray(triangle)
    directory_offset = HEADER.unpack_from(bad_offset)[8]
    bad_offset[directory_offset + 24:directory_offset + 32] = struct.pack("<Q", 4)
    (invalid_dir / "bad_chunk_offset.adm").write_bytes(bad_offset)

    magic, shader_doc, shader_chunks, _source_path = records[("valid", "shader_layered")]
    missing_fallback = copy.deepcopy(shader_doc)
    del missing_fallback["materials"][0]["roughnessFactor"]
    create(invalid_dir / "bad_missing_pbr.adm", magic, missing_fallback, shader_chunks)

    cycle_manifest = {
        "asset": {},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "accessors": [],
        "bufferViews": [],
        "chunkDependencies": [{"chunkId": 1, "requires": [2]}, {"chunkId": 2, "requires": [1]}],
    }
    create(invalid_dir / "bad_dependency_cycle.adm", b"ADM0", cycle_manifest,
           [(1, b"DATA", b"A", True), (2, b"DATA", b"B", True)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR,
                        help="destination root (defaults to adm-standard/fixtures)")
    args = parser.parse_args(argv)
    output_root = args.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    records = build_valid_fixtures(FIXTURE_DIR, output_root)
    build_invalid_fixtures(records, output_root)
    print(f"Built fixtures under {output_root}")


if __name__ == "__main__":
    main()
