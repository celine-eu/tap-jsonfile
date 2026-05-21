"""Tests for tap-jsonfile."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tap_jsonfile.client import (
    _infer_type,
    _merge_schemas,
    _merge_two,
    _record_to_schema,
    infer_schema,
    read_json_records,
)
from tap_jsonfile.storage import Storage
from tap_jsonfile.tap import TapJsonFile


class TestInferType:
    def test_string(self):
        assert _infer_type("hello") == {"type": ["string", "null"]}

    def test_integer(self):
        assert _infer_type(42) == {"type": ["integer", "null"]}

    def test_float(self):
        assert _infer_type(3.14) == {"type": ["number", "null"]}

    def test_boolean(self):
        assert _infer_type(True) == {"type": ["boolean", "null"]}

    def test_none(self):
        assert _infer_type(None) == {"type": ["string", "null"]}

    def test_list(self):
        result = _infer_type([1, 2, 3])
        assert result["type"] == ["array", "null"]
        assert result["items"]["type"] == ["integer", "null"]

    def test_dict(self):
        result = _infer_type({"a": 1, "b": "hello"})
        assert result["type"] == ["object", "null"]
        assert "a" in result["properties"]
        assert "b" in result["properties"]

    def test_empty_list(self):
        result = _infer_type([])
        assert result["type"] == ["array", "null"]
        assert result["items"] == {}

    def test_nested_dict(self):
        result = _infer_type({"x": {"y": 1}})
        assert result["type"] == ["object", "null"]
        inner = result["properties"]["x"]
        assert inner["type"] == ["object", "null"]
        assert inner["properties"]["y"]["type"] == ["integer", "null"]

    def test_mixed_list(self):
        result = _infer_type([1, "hello", 3.14])
        assert result["type"] == ["array", "null"]
        item_types = result["items"]["type"]
        assert "string" in item_types
        assert "number" in item_types


class TestMergeSchemas:
    def test_merge_same_types(self):
        a = {"type": ["string", "null"]}
        b = {"type": ["string", "null"]}
        result = _merge_two(a, b)
        assert result["type"] == ["string", "null"]

    def test_merge_different_types(self):
        a = {"type": ["string", "null"]}
        b = {"type": ["integer", "null"]}
        result = _merge_two(a, b)
        assert "string" in result["type"]
        assert "integer" in result["type"]
        assert "null" in result["type"]

    def test_merge_int_and_float_widens_to_number(self):
        a = {"type": ["integer", "null"]}
        b = {"type": ["number", "null"]}
        result = _merge_two(a, b)
        assert "number" in result["type"]
        assert "integer" not in result["type"]

    def test_merge_object_properties(self):
        a = {"type": ["object"], "properties": {"x": {"type": ["integer", "null"]}}}
        b = {"type": ["object"], "properties": {"y": {"type": ["string", "null"]}}}
        result = _merge_two(a, b)
        assert "x" in result["properties"]
        assert "y" in result["properties"]

    def test_merge_empty(self):
        assert _merge_two({}, {"type": ["string"]}) == {"type": ["string"]}
        assert _merge_two({"type": ["string"]}, {}) == {"type": ["string"]}

    def test_merge_multiple_records(self):
        schemas = [
            _record_to_schema({"a": 1, "b": "x"}),
            _record_to_schema({"a": 2, "c": True}),
        ]
        result = _merge_schemas(schemas)
        assert "a" in result["properties"]
        assert "b" in result["properties"]
        assert "c" in result["properties"]

    def test_missing_key_becomes_nullable(self):
        schemas = [
            _record_to_schema({"a": 1, "b": "x"}),
            _record_to_schema({"a": 2}),
        ]
        result = _merge_schemas(schemas)
        b_types = result["properties"]["b"]["type"]
        assert "null" in b_types


class TestReadJsonRecords:
    def test_single_object(self, tmp_path: Path):
        f = tmp_path / "single.json"
        f.write_text(json.dumps({"a": 1, "b": "hello"}))
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert records == [{"a": 1, "b": "hello"}]

    def test_array_of_objects(self, tmp_path: Path):
        f = tmp_path / "array.json"
        f.write_text(json.dumps([{"a": 1}, {"a": 2}]))
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert records == [{"a": 1}, {"a": 2}]

    def test_jsonl(self, tmp_path: Path):
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}\n{"a": 2}\n{"a": 3}\n')
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert len(records) == 3
        assert records[0] == {"a": 1}

    def test_empty_array(self, tmp_path: Path):
        f = tmp_path / "empty.json"
        f.write_text("[]")
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert records == []

    def test_nested_object(self, tmp_path: Path):
        data = {"id": 1, "meta": {"created": "2024-01-01", "tags": ["a", "b"]}}
        f = tmp_path / "nested.json"
        f.write_text(json.dumps(data))
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert records == [data]

    def test_skips_non_dict_array_items(self, tmp_path: Path):
        f = tmp_path / "mixed.json"
        f.write_text(json.dumps([{"a": 1}, "not a dict", {"b": 2}]))
        store = Storage(str(tmp_path / "*.json"))
        records = read_json_records(store, str(f))
        assert len(records) == 2


class TestInferSchema:
    def test_basic(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"x": 1, "y": "hello"}))
        (tmp_path / "b.json").write_text(json.dumps({"x": 2, "z": True}))
        config = {"paths": [str(tmp_path / "*.json")], "samples": 20}
        schema = infer_schema(config)
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        assert "z" in schema["properties"]
        assert "_sdc_source_file" in schema["properties"]

    def test_samples_limit(self, tmp_path: Path):
        for i in range(10):
            (tmp_path / f"f{i}.json").write_text(json.dumps({"id": i}))
        config = {"paths": [str(tmp_path / "*.json")], "samples": 3}
        schema = infer_schema(config)
        assert "id" in schema["properties"]

    def test_no_files(self, tmp_path: Path):
        config = {"paths": [str(tmp_path / "*.json")], "samples": 20}
        schema = infer_schema(config)
        assert schema == {"type": "object", "properties": {}}

    def test_nested_schema(self, tmp_path: Path):
        data = {"user": {"name": "alice", "age": 30}, "active": True}
        (tmp_path / "nested.json").write_text(json.dumps(data))
        config = {"paths": [str(tmp_path / "*.json")], "samples": 20}
        schema = infer_schema(config)
        user_schema = schema["properties"]["user"]
        assert "name" in user_schema["properties"]
        assert "age" in user_schema["properties"]


class TestTap:
    def test_discover(self, tmp_path: Path):
        (tmp_path / "test.json").write_text(json.dumps({"id": 1, "name": "test"}))
        config = {
            "paths": [str(tmp_path / "*.json")],
            "stream_name": "my_stream",
            "samples": 5,
        }
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        assert len(streams) == 1
        assert streams[0].name == "my_stream"

    def test_records(self, tmp_path: Path):
        for i in range(3):
            (tmp_path / f"file{i}.json").write_text(
                json.dumps({"id": i, "value": f"v{i}"}),
            )
        config = {"paths": [str(tmp_path / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        records = list(streams[0].get_records(None))
        assert len(records) == 3
        assert all("_sdc_source_file" in r for r in records)

    def test_array_file_records(self, tmp_path: Path):
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        (tmp_path / "data.json").write_text(json.dumps(data))
        config = {"paths": [str(tmp_path / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        records = list(streams[0].get_records(None))
        assert len(records) == 2

    def test_default_stream_name(self, tmp_path: Path):
        (tmp_path / "test.json").write_text(json.dumps({"a": 1}))
        config = {"paths": [str(tmp_path / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        assert streams[0].name == "records"

    def test_mixed_schemas(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"x": 1}))
        (tmp_path / "b.json").write_text(json.dumps({"x": "hello", "y": 2}))
        config = {"paths": [str(tmp_path / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        schema = streams[0].schema
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        x_types = schema["properties"]["x"]["type"]
        assert "integer" in x_types
        assert "string" in x_types

    def test_multiple_patterns(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "f1.json").write_text(json.dumps({"src": "a"}))
        (dir_b / "f2.json").write_text(json.dumps({"src": "b"}))
        config = {
            "paths": [
                str(dir_a / "*.json"),
                str(dir_b / "*.json"),
            ],
        }
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        records = list(streams[0].get_records(None))
        assert len(records) == 2

    def test_jsonl_records(self, tmp_path: Path):
        (tmp_path / "data.json").write_text('{"id": 1}\n{"id": 2}\n')
        config = {"paths": [str(tmp_path / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        records = list(streams[0].get_records(None))
        assert len(records) == 2

    def test_subdirectory_glob(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.json").write_text(json.dumps({"nested": True}))
        config = {"paths": [str(tmp_path / "**" / "*.json")]}
        tap = TapJsonFile(config=config)
        streams = tap.discover_streams()
        records = list(streams[0].get_records(None))
        assert len(records) == 1
        assert records[0]["nested"] is True


class TestIncremental:
    def _run(self, config, prev_state=None):
        """Run tap, return (records, state) — optionally seeding previous state."""
        tap = TapJsonFile(config=config)
        stream = tap.discover_streams()[0]
        if prev_state:
            stream.stream_state.update(prev_state)
        records = list(stream.get_records(None))
        state = copy.deepcopy(dict(stream.stream_state))
        return records, state

    def test_first_run_stores_hashes(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"id": 1}))
        (tmp_path / "b.json").write_text(json.dumps({"id": 2}))
        config = {"paths": [str(tmp_path / "*.json")]}

        records, state = self._run(config)
        assert len(records) == 2
        assert "file_hashes" in state
        assert len(state["file_hashes"]) == 2

    def test_skips_unchanged_files(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"id": 1}))
        config = {"paths": [str(tmp_path / "*.json")]}

        _, state = self._run(config)
        records, _ = self._run(config, prev_state=state)
        assert len(records) == 0

    def test_processes_modified_file(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"id": 1}))
        config = {"paths": [str(tmp_path / "*.json")]}

        _, state = self._run(config)

        f.write_text(json.dumps({"id": 99}))

        records, _ = self._run(config, prev_state=state)
        assert len(records) == 1
        assert records[0]["id"] == 99

    def test_processes_new_file(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"id": 1}))
        config = {"paths": [str(tmp_path / "*.json")]}

        _, state = self._run(config)

        (tmp_path / "b.json").write_text(json.dumps({"id": 2}))

        records, _ = self._run(config, prev_state=state)
        assert len(records) == 1
        assert records[0]["id"] == 2

    def test_state_drops_deleted_files(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"id": 1}))
        (tmp_path / "b.json").write_text(json.dumps({"id": 2}))
        config = {"paths": [str(tmp_path / "*.json")]}

        _, state = self._run(config)
        assert len(state["file_hashes"]) == 2

        (tmp_path / "b.json").unlink()

        _, state2 = self._run(config, prev_state=state)
        assert len(state2["file_hashes"]) == 1

    def test_mix_of_new_unchanged_modified(self, tmp_path: Path):
        (tmp_path / "unchanged.json").write_text(json.dumps({"id": 1}))
        (tmp_path / "will_change.json").write_text(json.dumps({"id": 2}))
        config = {"paths": [str(tmp_path / "*.json")]}

        _, state = self._run(config)

        (tmp_path / "will_change.json").write_text(json.dumps({"id": 20}))
        (tmp_path / "brand_new.json").write_text(json.dumps({"id": 3}))

        records, state2 = self._run(config, prev_state=state)
        ids = {r["id"] for r in records}
        assert ids == {20, 3}
        assert len(state2["file_hashes"]) == 3
