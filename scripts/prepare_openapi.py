"""Normalize an OpenAPI spec so openapi-python-client emits a clean SDK.

No endpoint policy lives here: the published surface is decided upstream in
agent_platform's public v2 schema. This only smooths over generator quirks.

Usage:
    python scripts/prepare_openapi.py <input.json> <output.json>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_OP_KEYS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _find_array_branch(schema: dict) -> dict | None:
    """Return the array-typed sub-schema of ``schema`` (direct or nullable anyOf), or None."""
    if schema.get("type") == "array":
        return schema
    for key in ("anyOf", "oneOf"):
        for branch in schema.get(key) or []:
            if isinstance(branch, dict) and branch.get("type") == "array":
                return branch
    return None


def shorten_operation_ids(spec: dict) -> list[tuple[str, str]]:
    """Strip FastAPI's ``_<path>_<method>`` suffix so methods import as ``create_session``."""
    fixed: list[tuple[str, str]] = []
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in _OP_KEYS or not isinstance(op, dict):
                continue
            old = op.get("operationId")
            if not isinstance(old, str):
                continue
            new = re.sub(r"_api_v2_.*$", "", old)
            if new and new != old:
                op["operationId"] = new
                fixed.append((old, new))

    seen: dict[str, str] = {}
    for old, new in fixed:
        if new in seen:
            raise ValueError(f"operationId collision after suffix strip: {old!r} and {seen[new]!r} both -> {new!r}")
        seen[new] = old
    return fixed


def fix_array_param_enums(spec: dict) -> list[tuple[str, str, str]]:
    """Move an array parameter's ``enum`` onto ``items.enum``; otherwise the generator drops the operation."""
    fixed: list[tuple[str, str, str]] = []
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method.lower() not in _OP_KEYS or not isinstance(op, dict):
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Source openapi.json")
    parser.add_argument("output", type=Path, help="Normalized openapi.json")
    args = parser.parse_args()

    with args.input.open() as f:
        spec = json.load(f)

    op_id_renames = shorten_operation_ids(spec)
    array_enum_fixes = fix_array_param_enums(spec)

    with args.output.open("w") as f:
        json.dump(spec, f, indent=2, sort_keys=False)
        f.write("\n")

    print(f"Prepared {args.input} -> {args.output}")
    if op_id_renames:
        print(f"  operationId renames: {len(op_id_renames)}")
    if array_enum_fixes:
        print(f"  array-enum fixes: {len(array_enum_fixes)} param schemas rewritten (enum -> items.enum)")
        for path, method, name in array_enum_fixes:
            print(f"    - {method} {path}  ({name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
