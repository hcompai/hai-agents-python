"""Filter an OpenAPI spec before SDK generation.

Reads a YAML filter listing paths and operations to drop, then writes a new
OpenAPI JSON with:
  - those paths/operations removed,
  - any schema in components.schemas that becomes unreferenced after the
    removal also removed (transitive cleanup, so we don't ship orphan models).

The filter file format is documented in `sdk/python/filter.yaml`.

Usage:
    python scripts/filter_openapi.py <input.json> <filter.yaml> <output.json>

Designed to run BEFORE `openapi-python-client generate`. Pointing the generator
at <output.json> instead of <input.json> is the only change needed in the
regen pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# yaml is part of openapi-python-client's deps; if we're running this in CI
# the environment already has it. Fall back to a tiny parser otherwise.
try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "PyYAML is required (it ships with openapi-python-client). Install with: uv tool install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


REF_RE = re.compile(r"#/components/schemas/([A-Za-z0-9_.-]+)")

# OpenAPI Path Item keys that denote operations (everything else, like
# `parameters` or `summary`, is metadata on the path itself).
OP_KEYS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _find_array_branch(schema: dict) -> dict | None:
    """Return the array-typed sub-schema of ``schema``, or None.

    Handles both the direct case (``{type: array, ...}``) and the nullable case
    (``{anyOf: [{type: array, ...}, {type: null}]}``) that FastAPI emits for
    ``list[str] | None`` parameters.
    """
    if schema.get("type") == "array":
        return schema
    for key in ("anyOf", "oneOf"):
        for branch in schema.get(key) or []:
            if isinstance(branch, dict) and branch.get("type") == "array":
                return branch
    return None


def fix_array_param_enums(spec: dict) -> list[tuple[str, str, str]]:
    """Move ``enum`` from an array parameter schema onto its ``items`` sub-schema.

    FastAPI's ``Query(default, enum=[...])`` on a ``list[str]`` parameter emits
    the enum at the array level, which is invalid per the OpenAPI spec — enum
    must constrain the items, not the array itself. openapi-python-client then
    fails to parse the default (``['-created_at']`` vs string enum), logs
    ``cannot parse parameter ...`` and **drops the entire operation** from the
    generated SDK. Rewriting to the spec-valid form fixes the codegen.

    Returns a list of ``(path, method, param_name)`` for stats / debugging.
    Mutates ``spec`` in place.
    """
    fixed: list[tuple[str, str, str]] = []
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method.lower() not in OP_KEYS or not isinstance(op, dict):
                continue
            for param in op.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                schema = param.get("schema")
                if not isinstance(schema, dict):
                    continue
                enum = schema.get("enum")
                if not isinstance(enum, list):
                    continue
                array_branch = _find_array_branch(schema)
                if array_branch is None:
                    continue
                items = array_branch.setdefault("items", {})
                if not isinstance(items, dict):
                    continue
                items["enum"] = enum
                del schema["enum"]
                fixed.append((path, method.upper(), str(param.get("name", "?"))))
    return fixed


def collect_refs(node: Any, out: set[str]) -> None:
    """Walk an arbitrary JSON tree and collect every `$ref` pointing into
    components.schemas. Used to determine which schemas are still referenced
    after path removal."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                m = REF_RE.fullmatch(v)
                if m:
                    out.add(m.group(1))
            else:
                collect_refs(v, out)
    elif isinstance(node, list):
        for item in node:
            collect_refs(item, out)


def transitively_reachable(schemas: dict[str, dict], seed: set[str]) -> set[str]:
    """Starting from `seed` (schemas reachable from kept paths), expand to all
    schemas reachable via $ref chains inside components.schemas itself."""
    reachable: set[str] = set()
    frontier: list[str] = list(seed)
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in schemas:
            continue
        reachable.add(name)
        nested: set[str] = set()
        collect_refs(schemas[name], nested)
        frontier.extend(nested - reachable)
    return reachable


def apply_filter(spec: dict, filt: dict) -> tuple[dict, dict]:
    """Return (filtered_spec, stats)."""
    paths = spec.get("paths", {})
    excluded_paths = set(filt.get("exclude_paths") or [])
    excluded_ops = {(op["method"].lower(), op["path"]) for op in (filt.get("exclude_operations") or [])}

    dropped_paths: list[str] = []
    dropped_ops: list[str] = []
    kept_paths: dict[str, dict] = {}

    for path, path_item in paths.items():
        if path in excluded_paths:
            dropped_paths.append(path)
            continue

        kept_methods: dict[str, Any] = {}
        for key, value in path_item.items():
            if key.lower() in OP_KEYS and (key.lower(), path) in excluded_ops:
                dropped_ops.append(f"{key.upper()} {path}")
                continue
            kept_methods[key] = value

        if any(k.lower() in OP_KEYS for k in kept_methods):
            kept_paths[path] = kept_methods
        else:
            # The path had only excluded operations — drop it entirely.
            dropped_paths.append(path)

    # Move array-level enums onto items.enum so openapi-python-client doesn't
    # drop the affected list_* endpoints (workaround for FastAPI emitting
    # `enum` on the array schema instead of `items.enum`).
    array_enum_fixes = fix_array_param_enums({"paths": kept_paths})

    schemas: dict[str, dict] = spec.get("components", {}).get("schemas", {})
    initial_refs: set[str] = set()
    collect_refs(kept_paths, initial_refs)
    reachable = transitively_reachable(schemas, initial_refs)

    dropped_schemas = sorted(set(schemas) - reachable)

    out = dict(spec)
    out["paths"] = kept_paths
    if "components" in out and "schemas" in out["components"]:
        out["components"] = dict(out["components"])
        out["components"]["schemas"] = {k: v for k, v in schemas.items() if k in reachable}

    stats = {
        "paths_in": len(paths),
        "paths_out": len(kept_paths),
        "dropped_paths": sorted(set(dropped_paths)),
        "dropped_operations": sorted(set(dropped_ops)),
        "schemas_in": len(schemas),
        "schemas_out": len(reachable),
        "dropped_schemas": dropped_schemas,
        "array_enum_fixes": array_enum_fixes,
    }
    return out, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Source openapi.json")
    parser.add_argument("filter", type=Path, help="Filter YAML")
    parser.add_argument("output", type=Path, help="Filtered openapi.json")
    args = parser.parse_args()

    with args.input.open() as f:
        spec = json.load(f)
    with args.filter.open() as f:
        filt = yaml.safe_load(f) or {}

    filtered, stats = apply_filter(spec, filt)

    with args.output.open("w") as f:
        json.dump(filtered, f, indent=2, sort_keys=False)
        f.write("\n")

    print(f"Filtered: {args.input} -> {args.output}")
    print(f"  paths    : {stats['paths_in']} -> {stats['paths_out']}")
    print(f"  schemas  : {stats['schemas_in']} -> {stats['schemas_out']}")
    if stats["array_enum_fixes"]:
        print(f"  array-enum: {len(stats['array_enum_fixes'])} param schemas rewritten (enum -> items.enum)")
        for path, method, name in stats["array_enum_fixes"]:
            print(f"    - {method} {path}  ({name})")
    if stats["dropped_paths"]:
        print("  dropped paths:")
        for p in stats["dropped_paths"]:
            print(f"    - {p}")
    if stats["dropped_operations"]:
        print("  dropped operations:")
        for op in stats["dropped_operations"]:
            print(f"    - {op}")
    if stats["dropped_schemas"]:
        print(f"  dropped schemas ({len(stats['dropped_schemas'])}):")
        for s in stats["dropped_schemas"]:
            print(f"    - {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
