"""JSON file reading and schema inference utilities."""

from __future__ import annotations

import json
import logging
from typing import Any

from tap_jsonfile.storage import Storage

logger = logging.getLogger(__name__)

_SIMPLE_TYPE_MAP: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def _infer_type(value: object) -> dict[str, Any]:
    """Infer a JSON Schema type descriptor from a Python value."""
    if value is None:
        return {"type": ["null"]}

    for py_type, json_type in _SIMPLE_TYPE_MAP.items():
        if isinstance(value, py_type):
            return {"type": [json_type, "null"]}

    if isinstance(value, list):
        if value:
            merged: dict[str, Any] = {}
            for item in value:
                merged = _merge_two(merged, _infer_type(item))
            return {"type": ["array", "null"], "items": merged}
        return {"type": ["array", "null"], "items": {}}

    if isinstance(value, dict):
        props = {k: _infer_type(v) for k, v in value.items()}
        return {"type": ["object", "null"], "properties": props}

    return {"type": ["string", "null"]}


def _merge_properties(
    a_props: dict[str, Any],
    b_props: dict[str, Any],
) -> dict[str, Any]:
    """Merge property maps from two object schemas, adding null for missing keys."""
    merged: dict[str, Any] = {}
    for key in set(a_props) | set(b_props):
        if key in a_props and key in b_props:
            merged[key] = _merge_two(a_props[key], b_props[key])
        else:
            prop: dict[str, Any] = a_props.get(key) or b_props.get(key, {})
            prop_types = prop.get("type", [])
            if isinstance(prop_types, str):
                prop_types = [prop_types]
            if "null" not in prop_types:
                prop_types = [*prop_types, "null"]
            merged[key] = {**prop, "type": prop_types}
    return merged


def _merge_two(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two JSON Schema definitions into one."""
    if not a:
        return b
    if not b:
        return a

    a_types = a.get("type", [])
    b_types = b.get("type", [])
    if isinstance(a_types, str):
        a_types = [a_types]
    if isinstance(b_types, str):
        b_types = [b_types]

    merged_types = list(dict.fromkeys(a_types + b_types))
    if "integer" in merged_types and "number" in merged_types:
        merged_types.remove("integer")

    result: dict[str, Any] = {"type": merged_types}

    if "properties" in a or "properties" in b:
        result["properties"] = _merge_properties(
            a.get("properties", {}),
            b.get("properties", {}),
        )

    if "items" in a or "items" in b:
        result["items"] = _merge_two(a.get("items", {}), b.get("items", {}))

    return result


_NULL_ONLY_WIDENED = ["string", "number", "integer", "boolean", "null"]


def _widen_null_only(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace null-only types with a permissive type list.

    When every sampled value was None we cannot know the real type, so we
    accept any JSON primitive rather than rejecting valid data at the target.
    """
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]

    if types == ["null"]:
        schema = {**schema, "type": list(_NULL_ONLY_WIDENED)}

    if "properties" in schema:
        schema["properties"] = {
            k: _widen_null_only(v) for k, v in schema["properties"].items()
        }
    if "items" in schema:
        schema["items"] = _widen_null_only(schema["items"])

    return schema


def _merge_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple JSON Schema definitions into one."""
    result: dict[str, Any] = {}
    for schema in schemas:
        result = _merge_two(result, schema)
    return _widen_null_only(result)


def _record_to_schema(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a single record dict to a JSON Schema definition."""
    props = {k: _infer_type(v) for k, v in record.items()}
    return {"type": "object", "properties": props}


def parse_json_content(content: str) -> list[dict[str, Any]]:
    """Parse a string as JSON (object, array, or JSONL) into record dicts."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
        return records

    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def read_json_records(storage: Storage, path: str) -> list[dict[str, Any]]:
    """Read a JSON or JSONL file and return a list of record dicts."""
    with storage.open(path) as f:
        content: str = f.read()
    return parse_json_content(content)


def infer_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Infer a merged JSON Schema by sampling files matched by configured paths."""
    samples_limit: int = config.get("samples", 20)

    all_files: list[tuple[Storage, str]] = []
    for pattern in config["paths"]:
        store = Storage(pattern)
        paths = store.glob()
        all_files.extend((store, p) for p in paths)

    schemas: list[dict[str, Any]] = []
    sampled = 0
    for store, path in all_files:
        if sampled >= samples_limit:
            break
        try:
            records = read_json_records(store, path)
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s for schema inference, skipping", path)
            continue
        schemas.extend(_record_to_schema(r) for r in records)
        sampled += 1

    if not schemas:
        return {"type": "object", "properties": {}}

    merged = _merge_schemas(schemas)
    merged.setdefault("properties", {})["_sdc_source_file"] = {
        "type": ["string", "null"],
    }
    return merged
