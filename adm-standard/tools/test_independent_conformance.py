#!/usr/bin/env python3
"""Security and cross-reader checks for the standalone ADM reference container reader."""

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "adm-standard" / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import container as reference  # noqa: E402
from adm_blender.core.validate import validate_file  # noqa: E402

FIXTURES = ROOT / "adm-standard" / "fixtures"


def empty_model():
    return {"asset": {}, "nodes": [], "scenes": [{"nodes": []}], "scene": 0,
            "meshes": [], "accessors": [], "bufferViews": []}


def malformed_manifest_file(path, manifest_bytes):
    directory_offset = reference.align(64 + len(manifest_bytes))
    file_size = directory_offset
    header = reference.HEADER.pack(
        b"ADM0", 1, 0, 64, 0, file_size, 64, len(manifest_bytes), directory_offset, 0, 80, 0
    )
    path.write_bytes(header + manifest_bytes + bytes(directory_offset - 64 - len(manifest_bytes)))


class IndependentConformanceTests(unittest.TestCase):
    def test_published_valid_fixtures_pass_both_readers(self):
        fixtures = list((FIXTURES / "valid").glob("*.adm*")) + list((FIXTURES / "profiles").glob("*.adm*"))
        for path in fixtures:
            with self.subTest(path=path.name):
                reference.verify(path)
                report = validate_file(path)
                self.assertTrue(report.ok, report.format())

    def test_published_invalid_fixtures_fail_independent_container_reader(self):
        for path in sorted((FIXTURES / "invalid").glob("*.adm*")):
            with self.subTest(path=path.name):
                with self.assertRaises(reference.AdmError):
                    reference.verify(path)

    def test_shader_mask_negative_fixtures_are_container_valid_but_semantically_invalid(self):
        fixtures = sorted((FIXTURES / "semantic_invalid").glob("*.adm"))
        self.assertEqual(len(fixtures), 3)
        for path in fixtures:
            with self.subTest(path=path.name):
                reference.verify(path)
                report = validate_file(path)
                self.assertFalse(report.ok, report.format())

    def test_file_size_limit_is_checked_before_reading_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oversized.adm"
            path.write_bytes(b"x" * 128)
            with mock.patch.object(reference, "_read_at", side_effect=AssertionError("read before limit")):
                with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_RESOURCE_LIMIT"):
                    reference.verify(path, max_file_bytes=127)

    def test_payload_hashing_reads_bounded_blocks(self):
        payload = b"x" * (reference.HASH_BLOCK * 2 + 17)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large_payload.adm"
            reference.create(path, b"ADM0", empty_model(), [(1, b"GEOM", payload, True)])
            original = reference._read_at
            read_sizes = []

            def tracked(stream, offset, length, file_size):
                read_sizes.append(length)
                return original(stream, offset, length, file_size)

            with mock.patch.object(reference, "_read_at", side_effect=tracked):
                reference.verify(path)
            self.assertLessEqual(max(read_sizes), reference.HASH_BLOCK)
            self.assertGreaterEqual(sum(read_sizes), len(payload))

    def test_malformed_nonfinite_json_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nonfinite.adm"
            manifest = (b'{"asset":{},"nodes":[],"scenes":[{"nodes":[]}],"scene":0,'
                        b'"meshes":[],"accessors":[],"bufferViews":[],"value":1e9999}')
            malformed_manifest_file(path, manifest)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_NONFINITE"):
                reference.verify(path, verify_payload=False)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_NONFINITE"):
                reference.RangeReader(path)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.adm"
            manifest = (b'{"asset":{},"nodes":[],"scenes":[{"nodes":[]}],"scene":0,'
                        b'"meshes":[],"accessors":[],"bufferViews":[],"asset":{}}')
            malformed_manifest_file(path, manifest)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_DUPLICATE_JSON_KEY"):
                reference.verify(path, verify_payload=False)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_DUPLICATE_JSON_KEY"):
                reference.RangeReader(path)

    def test_range_reader_caps_file_and_rejects_chunk_ranges_outside_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "range_reader.adm"
            reference.create(path, b"ADM0", empty_model(), [(1, b"GEOM", b"payload", True)])
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_RESOURCE_LIMIT"):
                reference.RangeReader(path, max_file_bytes=1)

            data = bytearray(path.read_bytes())
            directory_offset = reference.HEADER.unpack_from(data)[8]
            fields = list(reference.ENTRY.unpack_from(data, directory_offset))
            fields[5] = len(data) + 16
            reference.ENTRY.pack_into(data, directory_offset, *fields)
            path.write_bytes(data)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_CHUNK_ENTRY"):
                reference.RangeReader(path)

    def test_dependency_graph_depth_does_not_use_python_recursion(self):
        count = 1400
        doc = empty_model()
        doc["chunkDependencies"] = [
            {"chunkId": index + 1, "requires": [index + 2]}
            for index in range(count - 1)
        ]
        chunks = [(index + 1, b"DATA", b"x", True) for index in range(count)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "deep_dependencies.adm"
            reference.create(path, b"ADM0", doc, chunks)
            result = reference.verify(path, verify_payload=False)
            self.assertEqual(result["chunks"], count)

    def test_dependency_cycle_is_rejected_without_recursion(self):
        count = 1400
        doc = empty_model()
        doc["chunkDependencies"] = [
            {"chunkId": index + 1, "requires": [(index + 1) % count + 1]}
            for index in range(count)
        ]
        chunks = [(index + 1, b"DATA", b"x", True) for index in range(count)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cyclic_dependencies.adm"
            reference.create(path, b"ADM0", doc, chunks)
            with self.assertRaisesRegex(reference.AdmError, "ADM_ERR_DEPENDENCY_CYCLE"):
                reference.verify(path, verify_payload=False)


if __name__ == "__main__":
    unittest.main()
