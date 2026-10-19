"""Block a release whose API spec needs operations prod lacks, or session fields the pinned runtime does not accept."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROD_SPECS = ("https://agp.hcompany.ai/share/openapi.json", "https://agp.eu.hcompany.ai/share/openapi.json")
RUNTIME_SPEC = "https://assets.hcompanyprod.fr/hai-agent-runtime/{}/openapi.json"
# The local runtime answers every other resource with 501, so only sessions carry fields it must accept.
RUNTIME_RESOURCE = "/api/v2/sessions"
METHODS = ("get", "post", "put", "patch", "delete")

Spec = dict[str, Any]
Schema = dict[str, Any]


def operations(spec: Spec) -> dict[str, Schema]:
    return {
        f"{method.upper()} {path}": op
        for path, item in spec.get("paths", {}).items()
        for method, op in item.items()
        if method in METHODS
    }


def fields(spec: Spec, schema: Schema, prefix: str = "", seen: frozenset[str] = frozenset()) -> set[str]:
    """Every property path `schema` accepts, union branches merged, array items as `[]`."""
    ref = schema.get("$ref")
    if ref is not None:
        if ref in seen:
            return set()
        seen |= {ref}
        schema = spec
        for part in ref.removeprefix("#/").split("/"):
            schema = schema[part]
    found: set[str] = set()
    for key in ("anyOf", "oneOf", "allOf"):
        for branch in schema.get(key, []):
            found |= fields(spec, branch, prefix, seen)
    for key, suffix in (("items", "[]"), ("additionalProperties", ".*")):
        if isinstance(schema.get(key), dict):
            found |= fields(spec, schema[key], prefix + suffix, seen)
    for name, sub in schema.get("properties", {}).items():
        path = f"{prefix}.{name}" if prefix else name
        found |= {path} | fields(spec, sub, path, seen)
    return found


def _body_fields(spec: Spec, op: Schema) -> set[str]:
    schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    return fields(spec, schema) if schema else set()


def missing_operations(sdk: Spec, server: Spec) -> list[str]:
    return sorted(operations(sdk).keys() - operations(server).keys())


def unaccepted_session_fields(sdk: Spec, runtime: Spec) -> list[str]:
    served = operations(runtime)
    return sorted(
        f"{name}: {field}"
        for name, op in operations(sdk).items()
        if name.split(" ", 1)[1].startswith(RUNTIME_RESOURCE) and name in served
        for field in _body_fields(sdk, op) - _body_fields(runtime, served[name])
    )


def _fetch(url: str) -> Spec | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return None
        raise


def problems(sdk: Spec, runtime_version: str | None) -> list[str]:
    found: list[str] = []
    for url in PROD_SPECS:
        prod = _fetch(url)
        if prod is None:
            raise SystemExit(f"cannot read {url}")
        found += [f"{url} does not serve {op}" for op in missing_operations(sdk, prod)]
    if runtime_version:
        runtime = _fetch(RUNTIME_SPEC.format(runtime_version))
        if runtime is None:
            print(f"::warning::hai-agent-runtime {runtime_version} has no published openapi.json; skipping its check")
        else:
            found += [
                f"hai-agent-runtime {runtime_version} does not accept {f}"
                for f in unaccepted_session_fields(sdk, runtime)
            ]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "openapi.json")
    parser.add_argument("--runtime-pin", type=Path, help="pin.json naming the hai-agent-runtime the release bundles")
    args = parser.parse_args()
    runtime_version = json.loads(args.runtime_pin.read_text())["version"] if args.runtime_pin else None
    found = problems(json.loads(args.spec.read_text()), runtime_version)
    for problem in found:
        print(f"::error::{problem}")
    if found:
        sys.exit(1)
    print("release is compatible with prod" + (f" and hai-agent-runtime {runtime_version}" if runtime_version else ""))


if __name__ == "__main__":
    main()
