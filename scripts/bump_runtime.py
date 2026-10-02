"""Pin a hai-agent-runtime release: its version plus a fresh sha256 for every platform in the pin file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Stdlib only: runs in a bare checkout with no dependencies installed.
PIN_FILE = Path(__file__).parents[1] / "src" / "hai_agents_local" / "runtime" / "pin.json"
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_SHA256 = "0" * 64


def apply_bump(pin: dict, version: str, shas: dict[str, str]) -> dict:
    """`pin` moved to `version`; raises unless `shas` holds a real digest for exactly the pinned platforms."""
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("runtime version must be a release version, e.g. 0.1.13")
    for platform, sha in shas.items():
        if not _SHA256_RE.fullmatch(sha) or sha == _PLACEHOLDER_SHA256:
            raise ValueError(f"{platform}: {sha!r} is not a lowercase 64-char sha256")
    published = set(pin["sha256"])
    extra = shas.keys() - published
    if extra:
        raise ValueError(f"no manifest entry for platform(s): {sorted(extra)}")
    # A platform left on its old digest would fail verification at the new version's URL.
    missing = published - shas.keys()
    if missing:
        raise ValueError(f"missing sha for published platform(s): {sorted(missing)}")
    return {**pin, "version": version, "sha256": {platform: shas[platform] for platform in pin["sha256"]}}


def _parse_args(argv: list[str]) -> tuple[str, dict[str, str]]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--sha",
        action="append",
        required=True,
        metavar="PLATFORM=SHA256",
        help="per-platform digest, e.g. darwin-arm64=<hex> (repeatable)",
    )
    args = parser.parse_args(argv)
    shas: dict[str, str] = {}
    for entry in args.sha:
        platform, _, sha = entry.partition("=")
        if not platform or not sha:
            parser.error(f"--sha must be PLATFORM=SHA256, got {entry!r}")
        if platform in shas:
            parser.error(f"duplicate --sha for {platform}")
        shas[platform] = sha.lower()
    return args.version, shas


def main(argv: list[str]) -> int:
    version, shas = _parse_args(argv)
    pin = apply_bump(json.loads(PIN_FILE.read_text(encoding="utf-8")), version, shas)
    PIN_FILE.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    print(f"bumped runtime to {version} ({', '.join(sorted(shas))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
