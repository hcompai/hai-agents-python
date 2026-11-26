"""`mcporter` in the agent's shell: its config names the resolver alone, which holds every key."""

from __future__ import annotations

import json
import logging
import shlex
import shutil
from pathlib import Path

from .resolver import MCPORTER_CALL_TIMEOUT_MS, Resolver
from .runtime.install import install_pinned

logger = logging.getLogger(__name__)

MCPORTER_HINT = "npm install -g mcporter"
MCPORTER_RELEASES = "https://github.com/openclaw/mcporter/releases/download"
MCPORTER_VERSION = "0.17.1"
MCPORTER_SHA256 = {
    "darwin-arm64": "fe463c4b2563ff58c8866f1d2f64980d44c82eefbdb101473b87db2516ce9260",
    "darwin-x86_64": "16413e60684cbd32c3d96a5b42ca357895f32248a4869b2318f1b9f0cb7f1d26",
}
MCPORTER_HOME = Path.home() / ".hai" / "mcporter"


def mcporter() -> str | None:
    """This machine's `mcporter`: its own on PATH, else the pinned build, downloaded on its first use."""
    if found := shutil.which("mcporter"):
        return found
    pinned = install_pinned("mcporter", MCPORTER_HOME / MCPORTER_VERSION, MCPORTER_SHA256, _release)
    return str(pinned) if pinned else None


def _release(platform: str) -> str:
    name = f"mcporter_{MCPORTER_VERSION}_{platform.replace('-', '_')}.tar.gz"
    return f"{MCPORTER_RELEASES}/v{MCPORTER_VERSION}/{name}"


def shell_tools(folder: Path, resolver: Resolver) -> tuple[dict[str, str], Path]:
    """Write into `folder` the config naming `resolver`'s servers and an `mcporter` for the shell's PATH.

    Returns the variables the shell needs and the folder to put first on its PATH."""
    config = folder / "mcporter.json"
    headers = {"Authorization": f"Bearer {resolver.token}"}
    servers = {name: {"baseUrl": resolver.url(name), "headers": headers} for name in resolver.connections}
    config.write_text(json.dumps({"mcpServers": servers, "imports": []}, indent=2), encoding="utf-8")
    tools = folder / "bin"
    tools.mkdir(exist_ok=True)
    real = mcporter()
    if real:
        # The sandbox's NO_PROXY sends loopback past its proxy, the one way out to the resolver.
        script = f'#!/bin/sh\nNO_PROXY= no_proxy= exec {shlex.quote(real)} "$@"\n'
    else:
        logger.warning("mcporter is not installed, so the agent cannot reach MCP servers: %s", MCPORTER_HINT)
        script = f'#!/bin/sh\necho "mcporter is not installed on this machine: {MCPORTER_HINT}" >&2\nexit 127\n'
    shim = tools / "mcporter"
    shim.write_text(script, encoding="utf-8")
    shim.chmod(0o755)
    variables = {
        "MCPORTER_CONFIG": str(config),
        "MCPORTER_CALL_TIMEOUT": str(MCPORTER_CALL_TIMEOUT_MS),
        "MCPORTER_OAUTH_NO_BROWSER": "1",
        "MCPORTER_NO_SPINNER": "1",
    }
    return variables, tools
