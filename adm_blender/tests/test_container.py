"""Focused pure-Python Draft 0.4 container and chunk-addressed buffer tests.

Run: python -m unittest adm_blender.tests.test_container
"""

import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from adm_blender.core.buffers import BinBuilder, read_accessor, read_accessor_flat, read_view
from adm_blender.core.container import (
    ADM_MAGIC, ANIM_MAGIC, HEADER, ENTRY, AdmFormatError, ChunkCollection,
    Limits, ResourceLimitError, chunk_length, chunk_type, dump_json, has_chunk,
    parse_json_strict, read_container, write_container,
)

FIXTURES = Path(__file__).resolve().parents[2] / "adm-standard" / "fixtures"


def manifest():
    return {"asset": {}, "nodes": [], "scenes": [{"nodes": []}], "scene": 0,
            "meshes": [], "accessors": [], "bufferViews": []}


def patch_header(data, index, value):
    fields = list(HEADER.unpack_from(data))
    fields[index] = value
    result = bytearray(data)
    HEADER.pack_into(result, 0, *fields)
    return bytes(result)


def patch_entry(data, index, field, value):
    directory = HEADER.unpack_from(data)[8]
    fields = list(ENTRY.unpack_from(data, directory + index * ENTRY.size))
    fields[field] = value
    result = bytearray(data)
    ENTRY.pack_into(result, directory + index * ENTRY.size, *fields)
    return bytes(result)


class TrackingSource:
    def __init__(self, data):
        self.data = data
        self.reads = []

    def __call__(self, offset, length):
        self.reads.append((offset, length))
        return self.data[offset:offset + length]

    def payload_reads(self, entries):
        return [(off, length) for off, length in self.reads if length and any(
            off < e.file_offset + e.stored_length and off + length > e.file_offset
            for e in entries.values())]


class ContainerTests(unittest.TestCase):
    def test_fixture_generator_is_self_contained(self):
        script = FIXTURES.parent / "tools" / "build_fixtures.py"
        with tempfile.TemporaryDirectory(prefix="adm_fixture_build_") as tmp:
            output = Path(tmp)
            result = subprocess.run([sys.executable, str(script), "--output-dir", str(output)],
                                    cwd=output, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            expected = {p.relative_to(FIXTURES): p.read_bytes()
                        for p in FIXTURES.rglob("*") if p.is_file()}
            actual = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertEqual(actual.keys(), expected.keys())
            for name in expected:
                with self.subTest(fixture=str(name)):
                    self.assertEqual(actual[name], expected[name])

    def test_interactive_fixture_is_independent_of_zlib_backend(self):
        script = FIXTURES.parent / "tools" / "build_interactive_fixture.py"
        alternate_backend = (
            "import runpy, sys, zlib\n"
            "compress = zlib.compress\n"
            "zlib.compress = lambda data, level=-1: compress(data, 0)\n"
            "script = sys.argv[1]\n"
            "sys.path.insert(0, sys.argv[2])\n"
            "sys.argv = [script, '--check']\n"
            "runpy.run_path(script, run_name='__main__')\n"
        )
        with tempfile.TemporaryDirectory(prefix="adm_fixture_zlib_") as tmp:
            result = subprocess.run(
                [sys.executable, "-c", alternate_backend, str(script), str(script.parent)],
                cwd=tmp, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(AdmFormatError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)
        return error.exception

    def sample(self, *, dependencies=None):
        doc = manifest()
        if dependencies is not None:
            doc["chunkDependencies"] = dependencies
        chunks = ChunkCollection({1: b"first", 2: b"second", 3: b"third"},
                                 chunk_types={1: "GEOM", 2: "DATA", 3: "IMAG"})
        return doc, chunks, write_container(ADM_MAGIC, doc, chunks)

    def test_reference_valid_fixtures_and_raw_repack(self):
        for path in sorted((FIXTURES / "valid").glob("*")):
            if path.suffix not in (".adm", ".adm_anim"):
                continue
            with self.subTest(path=path.name):
                magic = ANIM_MAGIC if path.suffix == ".adm_anim" else ADM_MAGIC
                doc, store = read_container(path.read_bytes(), magic)
                store.verify_all()
                repacked = write_container(magic, doc, store)
                doc2, store2 = read_container(repacked, magic)
                self.assertEqual(doc2, doc)
                self.assertEqual(dict(store2), dict(store))

    def test_reference_container_invalid_fixtures(self):
        expected = {
            "bad_header_size.adm": "ADM_ERR_HEADER",
            "bad_file_size.adm": "ADM_ERR_BOUNDS",
            "bad_chunk_offset.adm": "ADM_ERR_CHUNK_BOUNDS",
            "bad_dependency_cycle.adm": "ADM_ERR_DEPENDENCY_CYCLE",
        }
        for name, code in expected.items():
            with self.subTest(name=name):
                self.assert_code(code, read_container,
                                 (FIXTURES / "invalid" / name).read_bytes(), ADM_MAGIC)
        doc, store = read_container((FIXTURES / "invalid" / "bad_hash.adm").read_bytes(),
                                    ADM_MAGIC)
        self.assertTrue(doc)
        self.assert_code("ADM_ERR_HASH_MISMATCH", store.verify_all)
        # bad_missing_pbr.adm is a semantic/material failure, not a container failure.
        _, store = read_container((FIXTURES / "invalid" / "bad_missing_pbr.adm").read_bytes(),
                                  ADM_MAGIC)
        store.verify_all()

    def test_exact_header_directory_and_reference_verification(self):
        doc, chunks, data = self.sample()
        fields = HEADER.unpack_from(data)
        self.assertEqual(HEADER.size, 64)
        self.assertEqual(ENTRY.size, 80)
        self.assertEqual(fields[:8], (ADM_MAGIC, 1, 0, 64, 0, len(data), 64, len(dump_json(doc))))
        self.assertEqual(fields[9:], (3, 80, 0))
        directory_offset = fields[8]
        for i, cid in enumerate(chunks):
            entry = ENTRY.unpack_from(data, directory_offset + i * 80)
            self.assertEqual(entry[0], cid)
            self.assertEqual(entry[6:8], (len(chunks[cid]), len(chunks[cid])))
            self.assertEqual(entry[8], hashlib.sha256(chunks[cid]).digest())
        # Execute the independent reference verifier without writing a scratch file.
        spec = importlib.util.spec_from_file_location(
            "adm_reference_container", FIXTURES.parent / "tools" / "container.py")
        reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reference)
        class InMemoryPath:
            def read_bytes(self):
                return data
        original = reference.pathlib.Path
        reference.pathlib.Path = lambda _: InMemoryPath()
        try:
            self.assertEqual(reference.verify("memory")["chunks"], 3)
        finally:
            reference.pathlib.Path = original

    def test_metadata_only_and_targeted_payload_reads(self):
        data = (FIXTURES / "valid" / "triangle_split.adm").read_bytes()
        source = TrackingSource(data)
        doc, store = read_container(source, ADM_MAGIC, file_size=len(data))
        self.assertFalse(source.payload_reads(store.entries))
        self.assertEqual(chunk_length(store, 2), 6)
        self.assertEqual(chunk_type(store, 2), "GEOM")
        self.assertTrue(has_chunk(store, 2))
        self.assertFalse(source.payload_reads(store.entries))
        self.assertEqual(len(store[2]), 6)
        entry = store.entries[2]
        self.assertEqual(source.payload_reads(store.entries), [(entry.file_offset, 6)])
        self.assertEqual(len(store[2]), 6)
        self.assertEqual(len(source.payload_reads(store.entries)), 1)
        self.assertEqual(len(doc["bufferViews"]), 2)

    def test_animation_catalog_without_payload_reads_and_wrong_magic(self):
        data = (FIXTURES / "valid" / "shader_parameter_tracks.adm_anim").read_bytes()
        source = TrackingSource(data)
        doc, store = read_container(source, ANIM_MAGIC, file_size=len(data))
        self.assertEqual(doc["library"]["id"], "material@surface@dirty")
        self.assertTrue(doc["clips"][0]["description"].strip())
        self.assertFalse(source.payload_reads(store.entries))
        self.assert_code("ADM_ERR_HEADER", read_container, data, ADM_MAGIC)

    def test_dependency_closure_prefetch_and_unrelated_corrupt_chunk(self):
        deps = [{"chunkId": 1, "requires": [2]}]
        _, _, data = self.sample(dependencies=deps)
        _, original = read_container(data, ADM_MAGIC)
        data = bytearray(data)
        data[original.entries[3].file_offset] ^= 1
        source = TrackingSource(bytes(data))
        _, store = read_container(source, ADM_MAGIC, file_size=len(data))
        self.assertEqual(store.dependency_closure([1]), (2, 1))
        self.assertEqual(store[1], b"first")
        self.assertEqual(source.payload_reads(store.entries),
                         [(store.entries[c].file_offset, store.entries[c].stored_length)
                          for c in (2, 1)])
        self.assert_code("ADM_ERR_HASH_MISMATCH", store.load, 3)

    def test_invalid_dependencies(self):
        invalid = [
            None, {}, [{"chunkId": 1, "requires": [9]}],
            [{"chunkId": 1, "requires": [1]}],
            [{"chunkId": 1, "requires": [2, 2]}],
            [{"chunkId": 1, "requires": [True]}],
            [{"chunkId": True, "requires": []}],
            [{"chunkId": 1, "requires": [2]}, {"chunkId": 1, "requires": []}],
            [{"chunkId": 9, "requires": []}],
            [{"chunkId": 1, "requires": [2], "extra": 0}],
        ]
        _, chunks, _ = self.sample()
        for deps in invalid:
            with self.subTest(deps=deps):
                doc = manifest()
                doc["chunkDependencies"] = deps
                self.assert_code("ADM_ERR_DEPENDENCY", write_container, ADM_MAGIC, doc, chunks)
        doc = manifest()
        doc["chunkDependencies"] = [
            {"chunkId": 1, "requires": [2]}, {"chunkId": 2, "requires": [1]}]
        self.assert_code("ADM_ERR_DEPENDENCY_CYCLE", write_container, ADM_MAGIC, doc, chunks)

    def test_deep_dependency_dag_no_recursion(self):
        count = 1100
        doc = manifest()
        doc["chunkDependencies"] = [{"chunkId": c, "requires": [c - 1]}
                                    for c in range(2, count + 1)]
        raw = write_container(ANIM_MAGIC, doc, {c: b"x" for c in range(1, count + 1)})
        _, store = read_container(raw, ANIM_MAGIC)
        self.assertEqual(store.dependency_closure([count]), tuple(range(1, count + 1)))

    def test_stream_hints_bootstrap(self):
        _, chunks, _ = self.sample()
        for hints in (None, {}, [{"chunkId": 9, "priority": 0}],
                      [{"chunkId": 1, "priority": 256}],
                      [{"chunkId": 1, "priority": True}],
                      [{"chunkId": True, "priority": 0}],
                      [{"chunkId": 1, "priority": 0}] * 2):
            doc = manifest()
            doc["streamHints"] = hints
            self.assert_code("ADM_ERR_STREAM_HINT", write_container, ADM_MAGIC, doc, chunks)
        doc = manifest()
        doc["streamHints"] = [{"chunkId": 1, "priority": 0}, {"chunkId": 2, "priority": 255}]
        raw = write_container(ADM_MAGIC, doc, chunks)
        read_container(raw, ADM_MAGIC)
        self.assert_code("ADM_ERR_STREAM_HINT", read_container,
                         raw.replace(b'"priority":255', b'"priority":256'), ADM_MAGIC)

    def test_view_metadata_bounds_and_unknown_references(self):
        for change in ({"chunkId": 9}, {"chunkId": True}, {"byteOffset": -1},
                       {"byteLength": 0x100000000}, {"byteLength": 6}):
            doc = manifest()
            doc["bufferViews"] = [{"chunkId": 1, "byteOffset": 0, "byteLength": 5}]
            doc["bufferViews"][0].update(change)
            self.assert_code("ADM_ERR_BUFFER_VIEW", write_container, ADM_MAGIC, doc, {1: b"first"})
        doc["bufferViews"][0]["byteLength"] = 5
        raw = write_container(ADM_MAGIC, doc, {1: b"first"})
        self.assert_code("ADM_ERR_BUFFER_VIEW", read_container,
                         raw.replace(b'"chunkId":1', b'"chunkId":9'), ADM_MAGIC)
        self.assert_code("ADM_ERR_BUFFER_VIEW", read_container,
                         raw.replace(b'"byteLength":5', b'"byteLength":6'), ADM_MAGIC)

    def test_resource_limits_before_payload_reads(self):
        _, _, data = self.sample()
        for limits in (Limits(max_json_bytes=2), Limits(max_chunks=1),
                       Limits(max_chunk_bytes=4), Limits(max_total_raw_bytes=8),
                       Limits(max_stored_bytes=8), Limits(max_bin_bytes=8)):
            source = TrackingSource(data)
            exc = self.assert_code("ADM_ERR_RESOURCE_LIMIT", read_container, source, ADM_MAGIC,
                                   limits, file_size=len(data))
            self.assertIsInstance(exc, ResourceLimitError)
            directory = HEADER.unpack_from(data)[8]
            start = (directory + 3 * 80 + 15) & ~15
            self.assertFalse(any(off >= start and length for off, length in source.reads))

    def test_optional_unknown_type_and_unsupported_codecs(self):
        _, _, data = self.sample()
        for codec in (1, 99):
            required = patch_entry(data, 0, 3, codec)
            self.assert_code("ADM_ERR_UNSUPPORTED_CODEC", read_container, required, ADM_MAGIC)
            optional = patch_entry(required, 0, 2, 0)
            _, store = read_container(optional, ADM_MAGIC)
            self.assertEqual(store[2], b"second")
            self.assert_code("ADM_ERR_UNSUPPORTED_CODEC", store.load, 1)
        unknown = patch_entry(data, 0, 1, b"FUTR")
        self.assert_code("ADM_ERR_UNSUPPORTED_CHUNK", read_container, unknown, ADM_MAGIC)
        unknown = patch_entry(unknown, 0, 2, 0)
        _, store = read_container(unknown, ADM_MAGIC)
        self.assertEqual(store[2], b"second")
        self.assert_code("ADM_ERR_UNSUPPORTED_CHUNK", store.load, 1)
        doc = manifest()
        doc["bufferViews"] = [{"chunkId": 1, "byteOffset": 0, "byteLength": 1}]
        optional = ChunkCollection()
        optional.add(1, b"x", "FUTR", False)
        self.assert_code("ADM_ERR_UNSUPPORTED_CHUNK", write_container, ADM_MAGIC, doc, optional)

    def test_required_geometry_unsupported_dependency(self):
        _, _, data = self.sample(dependencies=[{"chunkId": 1, "requires": [2]}])
        data = patch_entry(patch_entry(data, 1, 2, 0), 1, 3, 1)
        self.assert_code("ADM_ERR_UNSUPPORTED_CODEC", read_container, data, ADM_MAGIC)

    def test_header_bounds_and_legacy_rejected(self):
        _, _, data = self.sample()
        for index, value, code in (
                (1, 2, "HEADER"), (2, 1, "HEADER"), (3, 32, "HEADER"),
                (4, 1, "HEADER"), (5, len(data) + 1, "BOUNDS"),
                (6, 80, "HEADER"), (7, 0xffffffffffffffff, "BOUNDS"),
                (8, 0xffffffffffffffff, "BOUNDS"), (9, 65536, "BOUNDS"),
                (10, 81, "HEADER"), (11, 1, "HEADER")):
            with self.subTest(field=index):
                self.assert_code("ADM_ERR_" + code, read_container,
                                 patch_header(data, index, value), ADM_MAGIC)
        self.assert_code("ADM_ERR_TRUNCATED_HEADER", read_container, b"ADM0", ADM_MAGIC)
        legacy = ADM_MAGIC + struct.pack("<HHQQII", 1, 0, 2, 32, 0, 0) + b"{}" + b"\0" * 32
        self.assert_code("ADM_ERR_HEADER", read_container, legacy, ADM_MAGIC)

    def test_directory_bounds_order_padding_integrity(self):
        _, _, data = self.sample()
        _, store = read_container(data, ADM_MAGIC)
        first = store.entries[1]
        for field, value, code in (
                (0, 0, "CHUNK_ID"), (0, 2, "CHUNK_ID"),
                (0, 1 << 32, "CHUNK_ID"), (2, 2, "CHUNK_ENTRY"),
                (4, 1, "CHUNK_ENTRY"), (5, first.file_offset + 1, "CHUNK_BOUNDS"),
                (5, 0xfffffffffffffff0, "CHUNK_BOUNDS"), (6, 0, "CHUNK_ENTRY"),
                (6, 0xffffffffffffffff, "BOUNDS"),
                (7, 0, "CHUNK_ENTRY"), (7, 257 * 1024 * 1024, "CHUNK_ENTRY"),
                (7, first.raw_length + 1, "CHUNK_SIZE")):
            with self.subTest(field=field, value=value):
                self.assert_code("ADM_ERR_" + code, read_container,
                                 patch_entry(data, 0, field, value), ADM_MAGIC)
        overlap = patch_entry(data, 1, 5, first.file_offset)
        self.assert_code("ADM_ERR_CHUNK_BOUNDS", read_container, overlap, ADM_MAGIC)
        for offset in (64 + HEADER.unpack_from(data)[7],
                       first.file_offset + first.stored_length, len(data) - 1):
            corrupted = bytearray(data)
            corrupted[offset] = 1
            self.assert_code("ADM_ERR_PADDING", read_container, corrupted, ADM_MAGIC)
        truncated = patch_header(data[:-1], 5, len(data) - 1)
        self.assert_code("ADM_ERR_TRAILING_BYTES", read_container, truncated, ADM_MAGIC)
        extra = patch_header(data + b"\0" * 16, 5, len(data) + 16)
        self.assert_code("ADM_ERR_TRAILING_BYTES", read_container, extra, ADM_MAGIC)

    def test_physical_payload_order_can_differ_from_chunk_ids(self):
        data = write_container(ADM_MAGIC, manifest(), {1: b"one", 2: b"two"})
        _, store = read_container(data, ADM_MAGIC)
        result = bytearray(data)
        off1, off2 = store.entries[1].file_offset, store.entries[2].file_offset
        result[off1:off1 + 3], result[off2:off2 + 3] = b"two", b"one"
        result = patch_entry(patch_entry(result, 0, 5, off2), 1, 5, off1)
        _, store = read_container(result, ADM_MAGIC)
        self.assertEqual(dict(store), {1: b"one", 2: b"two"})

    def test_seekable_stream_and_short_range_source(self):
        _, _, data = self.sample()
        stream = io.BytesIO(data)
        doc, store = read_container(stream, ADM_MAGIC)
        self.assertTrue(doc)
        self.assertEqual(store[1], b"first")
        self.assert_code("ADM_ERR_BOUNDS", read_container,
                         lambda off, length: data[off:off + max(0, length - 1)],
                         ADM_MAGIC, file_size=len(data))

    def test_strict_json(self):
        cases = [(b'{"x":1,"x":2}', "DUPLICATE_JSON_KEY"),
                 (b'{"x":NaN}', "NONFINITE"), (b'{"x":1e9999}', "NONFINITE"),
                 (b'\xef\xbb\xbf{}', "JSON"), (b'{"x":"\\ud800"}', "JSON"),
                 (b'{"x":"\xff"}', "JSON"), (b'[]', "MANIFEST")]
        for raw, code in cases:
            self.assert_code("ADM_ERR_" + code, parse_json_strict, raw)
        self.assert_code("ADM_ERR_RESOURCE_LIMIT", parse_json_strict,
                         b'{"a":[[[0]]]}', Limits(max_json_depth=2))
        self.assertEqual(dump_json({"n": -0.0}), b'{"n":0.0}')

    def test_metadata_only_animation_and_plain_mapping_writer(self):
        doc = {"asset": {}, "library": {}, "clips": [], "accessors": [], "bufferViews": []}
        raw = write_container(ANIM_MAGIC, doc)
        got, store = read_container(raw, ANIM_MAGIC)
        self.assertEqual(got, doc)
        self.assertEqual(dict(store), {})
        raw = write_container(ADM_MAGIC, manifest(), {3: b"x"}, chunk_types={3: "GEOM"})
        _, store = read_container(raw, ADM_MAGIC)
        self.assertEqual(chunk_type(store, 3), "GEOM")
        self.assertEqual(store[3], b"x")
        with self.assertRaises(TypeError):
            write_container(ADM_MAGIC, manifest(), b"legacy BIN")


class BufferTests(unittest.TestCase):
    def test_separate_builder_chunks_and_types(self):
        builder = BinBuilder(chunk_type="ANIM")
        a = builder.add_view(struct.pack("<2f", 0.0, 1.0))
        b = builder.add_view(b"encoded-image", chunk_type="IMAG")
        doc = manifest()
        doc["bufferViews"] = builder.buffer_views
        doc["accessors"] = [{"bufferView": a, "componentType": "F32",
                             "type": "SCALAR", "count": 2}]
        data = write_container(ADM_MAGIC, doc, builder.bytes())
        _, store = read_container(data, ADM_MAGIC)
        self.assertEqual([e.chunk_type for e in store.entries.values()], ["ANIM", "IMAG"])
        self.assertEqual([v["byteOffset"] for v in builder.buffer_views], [0, 0])
        self.assertEqual(read_accessor(doc, store, 0), [(0.0,), (1.0,)])
        self.assertEqual(read_view(doc, store, b), b"encoded-image")

    def test_subview_and_accessor_offsets_normalization(self):
        doc = manifest()
        doc["bufferViews"] = [{"chunkId": 7, "byteOffset": 4, "byteLength": 8}]
        doc["accessors"] = [{"bufferView": 0, "byteOffset": 2, "componentType": "U16",
                             "type": "VEC2", "count": 1, "normalized": True}]
        chunks = ChunkCollection({7: b"abcd" + struct.pack("<4H", 55, 0, 65535, 44)})
        self.assertEqual(read_accessor(doc, chunks, 0), [(0.0, 1.0)])
        flat, count = read_accessor_flat(doc, chunks, 0)
        self.assertEqual((list(flat), count), ([0, 65535], 2))

    def test_view_and_accessor_bounds_and_nonfinite(self):
        doc = manifest()
        doc["bufferViews"] = [{"chunkId": 1, "byteOffset": 0, "byteLength": 4}]
        doc["accessors"] = [{"bufferView": 0, "componentType": "F32",
                             "type": "SCALAR", "count": 1}]
        chunks = ChunkCollection({1: struct.pack("<f", float("inf"))})
        with self.assertRaises(AdmFormatError) as error:
            read_accessor(doc, chunks, 0)
        self.assertEqual(error.exception.code, "ADM_ERR_NONFINITE")
        for index in (-1, 1, True):
            with self.subTest(index=index), self.assertRaises(AdmFormatError) as error:
                read_accessor(doc, chunks, index)
            self.assertEqual(error.exception.code, "ADM_ERR_ACCESSOR")
        for change in ({"byteOffset": 1}, {"count": 2}, {"count": True},
                       {"bufferView": -1}, {"type": "UNKNOWN"}):
            bad = copy.deepcopy(doc)
            bad["accessors"][0].update(change)
            with self.subTest(change=change), self.assertRaises(AdmFormatError) as error:
                read_accessor(bad, chunks, 0)
            self.assertEqual(error.exception.code, "ADM_ERR_ACCESSOR")
        bad = copy.deepcopy(doc)
        bad["bufferViews"][0]["byteLength"] = 5
        with self.assertRaises(AdmFormatError) as error:
            read_view(bad, chunks, 0)
        self.assertEqual(error.exception.code, "ADM_ERR_BUFFER_VIEW")

    def test_numpy_builder_accessor_when_available(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy is optional outside Blender")
        from adm_blender.core.buffers import read_accessor_np
        builder = BinBuilder()
        index = builder.add_accessor([[1, 2, 3], [-0.0, 4, 5]], "F32", "VEC3")
        doc = manifest()
        doc["bufferViews"], doc["accessors"] = builder.buffer_views, builder.accessors
        data = write_container(ADM_MAGIC, doc, builder.bytes())
        _, store = read_container(data, ADM_MAGIC)
        np.testing.assert_array_equal(read_accessor_np(doc, store, index),
                                      [[1, 2, 3], [0, 4, 5]])
        self.assertEqual(read_accessor(doc, store, index), [(1.0, 2.0, 3.0), (0.0, 4.0, 5.0)])


if __name__ == "__main__":
    unittest.main()
