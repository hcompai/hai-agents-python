"""Pinned hai-agent-runtime version and per-platform artifact digests.

This module is the SDK's single runtime pin: a runtime release bumps
PINNED_RUNTIME_VERSION and MANIFEST here (via the retargeted
release-hai-agent-runtime.yaml pin PR) and nothing else. Artifacts live under an
immutable version-scoped CDN prefix, so an edge can never serve stale bytes.
Cross-ref: eng_plans/14-06-2026-holodesktop-binary-versioning-autoupdate.
"""

from __future__ import annotations

import dataclasses
import platform
import sys
import typing

# SHIP-GATE: repoint to the plan-005 release before merge
PINNED_RUNTIME_VERSION = "0.1.8"
RUNTIME_CDN_BASE = "https://assets.hcompanyprod.fr/hai-agent-runtime"
# Guard value: published manifest entries must never use it (every download would fail verification).
PLACEHOLDER_SHA256 = "0" * 64
BINARY_NAME = "hai-agent-runtime.exe" if sys.platform == "win32" else "hai-agent-runtime"


@dataclasses.dataclass(frozen=True)
class RuntimeArtifact:
    url: str
    sha256: str


def _artifact(filename: str, sha256: str) -> RuntimeArtifact:
    """A published release file resolved to its pinned, version-scoped CDN URL."""
    return RuntimeArtifact(url=f"{RUNTIME_CDN_BASE}/{PINNED_RUNTIME_VERSION}/{filename}", sha256=sha256)


MANIFEST: typing.Dict[str, RuntimeArtifact] = {
    "darwin-arm64": _artifact(
        "hai-agent-runtime-darwin-arm64.zip",
        # SHIP-GATE: repoint to the plan-005 release before merge
        "1aed0055898116732aee031dc4a1235782b2909ee51e0367e2d50bb3be6671c9",
    ),
    "windows-x86_64": _artifact(
        "hai-agent-runtime-windows-x86_64.zip",
        # SHIP-GATE: repoint to the plan-005 release before merge
        "4e6b2bcd42af2bb6b22197fcde947327497f5c62fd60d48bc9037730d80dc691",
    ),
}

UNIMPLEMENTED_PLATFORMS: typing.Dict[str, str] = {
    "darwin-x86_64": "hai-agent-runtime is not published for macOS Intel yet",
    "linux-x86_64": "hai-agent-runtime is not published for Linux yet",
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
