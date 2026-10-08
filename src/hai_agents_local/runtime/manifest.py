"""Pinned hai-agent-runtime artifacts, loaded from pin.json (updated by scripts/bump_runtime.py)."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import platform
import sys
import typing

RUNTIME_CDN_BASE = "https://assets.hcompanyprod.fr/hai-agent-runtime"
# Guard value: published manifest entries must never use it (every download would fail verification).
PLACEHOLDER_SHA256 = "0" * 64
BINARY_NAME = "hai-agent-runtime.exe" if sys.platform == "win32" else "hai-agent-runtime"


@dataclasses.dataclass(frozen=True)
class RuntimeArtifact:
    url: str
    sha256: str


_PIN = json.loads(pathlib.Path(__file__).with_name("pin.json").read_text(encoding="utf-8"))

# TODO: pin a runtime release that serves the shared recipe.
PINNED_RUNTIME_VERSION: str = _PIN["version"]

MANIFEST: typing.Dict[str, RuntimeArtifact] = {
    platform_name: RuntimeArtifact(
        url=f"{RUNTIME_CDN_BASE}/{PINNED_RUNTIME_VERSION}/hai-agent-runtime-{platform_name}.zip", sha256=sha256
    )
    for platform_name, sha256 in _PIN["sha256"].items()
}

UNIMPLEMENTED_PLATFORMS: typing.Dict[str, str] = {
    "darwin-x86_64": "hai-agent-runtime is not published for macOS Intel yet",
}


def platform_key() -> str:
    """`<system>-<arch>` manifest key for the current host, e.g. darwin-arm64."""
    if sys.platform == "darwin":
        system = "darwin"
    elif sys.platform.startswith("linux"):
        system = "linux"
    elif sys.platform == "win32":
        system = "windows"
    else:
        raise RuntimeError(f"unsupported platform for hai-agent-runtime: {sys.platform}")
    machine = platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    if arch is None:
        raise RuntimeError(f"unsupported architecture for hai-agent-runtime: {machine}")
    return f"{system}-{arch}"
