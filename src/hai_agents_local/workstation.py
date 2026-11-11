"""Shell desktop bridge: the agent's shell runs on this machine and drives it through the desk, cua and web CLIs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hai_agents.client import credentials_path

from .bridge import LocalBridge, TokenSource
from .config import shell_policy, shell_sandbox
from .desktop import ensure_macos_input_permissions

if TYPE_CHECKING:
    from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "A desktop with a shell requires extra deps. Install with: pip install 'hai-agents[workstation]'"
SANDBOX_HINT = (
    "A desktop with a shell confines its commands with Anthropic's sandbox-runtime, which is not installed: "
    "npm install -g @anthropic-ai/sandbox-runtime. To run them unconfined, as you: HAI_SHELL_SANDBOX=0 or --no-sandbox."
)
STARTER_ALLOWLIST = """\
# Commands the agent runs on this machine without asking, one prefix a line. Any other waits for your approval.
# `cua` sees and drives this screen: its clicks and keys do whatever you can do here, outside any sandbox.
cua
"""
STARTER_REGISTRIES = ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]
STARTER_SECRETS = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.netrc", "~/.kube", "~/.config/gcloud"]


class WorkstationBridge(LocalBridge["ManagedCodeSandboxInterface"]):
    """Serves shell-mode desktops with a shell in ~/hai/<session_id>, running as the current user."""

    environment_kind = "workstation"
    environment = {"kind": "desktop", "mode": {"type": "shell"}}
    drives_desktop = True

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        workspace: str | None = None,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        environment_variables: Mapping[str, str] | None = None,
        policy: str | None = None,
        sandbox: str | Literal[False] | None = None,
    ) -> None:
        """Build the bridge.

        Args:
            policy: This machine's allowlist file, one command prefix a line; defaults to ``HAI_SHELL_POLICY``.
                With one, the shell runs the commands it covers and holds any other until the session's client
                approves it. Without one, every command runs. A file that does not exist yet starts with ``cua``
                allowed.
            sandbox: This machine's sandbox-runtime settings file. Every command runs under ``srt`` by its rules:
                it writes in the workspace and reaches the ``cua`` daemon, which this bridge starts outside the
                sandbox. Defaults to ``HAI_SHELL_SANDBOX``, else on macOS to ``sandbox.json`` beside the stored
                credentials; a file that does not exist yet starts with the package registries reachable and the
                usual credential folders unreadable. ``False`` runs commands unconfined.

        Under either, the agent's file tools stay inside the workspace.
        """
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.workspace = Path(workspace).expanduser() if workspace else Path.home() / "hai" / self.session_id
        self.environment_variables = dict(environment_variables or {})
        self.policy = policy or shell_policy()
        self.sandbox = None if sandbox is False else sandbox or shell_sandbox()

    def preflight(self) -> None:
        if sys.platform == "darwin":
            ensure_macos_input_permissions(prompt=True)

    def create_driver(self) -> ManagedCodeSandboxInterface:
        try:
            from hai_drivers.code_sandbox.local.driver import LocalCodeSandbox
        except ImportError as exc:
            raise ImportError(INSTALL_HINT) from exc
        path = os.environ.get("PATH", os.defpath)
        desk = shutil.which("desk", path=os.pathsep.join([sysconfig.get_path("scripts"), path]))
        if desk is None:
            raise ImportError(INSTALL_HINT)
        subprocess.run([desk, "aliases"], check=True, capture_output=True)
        logger.info("workstation workspace: %s", self.workspace)
        environment = {
            **self.environment_variables,
            "COORDINATE_SYSTEM": "0-1000",
            "CUA_CURSOR": os.environ.get("CUA_CURSOR", "off"),
            "CUA_SESSION": self.session_id,
            "PATH": os.pathsep.join([os.path.dirname(desk), path]),
        }
        policy = sandbox = None
        if self.policy:
            from hai_drivers.code_sandbox.local.allowlist import Allowlist

            allowed = _starting_with(self.policy, STARTER_ALLOWLIST)
            if allowed.resolve().is_relative_to(self.workspace.resolve()):
                raise ValueError(f"{allowed} is inside the workspace, where the agent writes")
            policy = Allowlist(allowed)
            logger.info("commands outside %s wait for approval", allowed)
        if self.sandbox:
            from hai_drivers.code_sandbox.local.sandbox_runtime import SandboxRuntime

            if shutil.which("srt") is None:
                raise RuntimeError(SANDBOX_HINT)
            settings = _starting_with(self.sandbox, _starter_sandbox())
            sandbox = SandboxRuntime(settings, protected=[policy.path] if policy else [], **_host_cua(environment))
            logger.info("commands run confined by %s", settings)
        else:
            logger.warning("commands run unconfined, as you: no sandbox is on")
        return LocalCodeSandbox(str(self.workspace), environment_variables=environment, policy=policy, sandbox=sandbox)

    async def interrupt_driver(self) -> None:
        # This bridge creates one sandbox per run; close owns only that run's children.
        if self._driver is not None:
            await asyncio.to_thread(self._driver.close)

    def driver_interface(self) -> type:
        from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

        return ManagedCodeSandboxInterface


def _starting_with(path: str, starter: str) -> Path:
    """The machine's rules file at `path`, written with `starter` when it does not exist yet."""
    rules = Path(path).expanduser()
    if not rules.exists():
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(starter, encoding="utf-8")
        logger.info("wrote starter rules: %s", rules)
    return rules


def _starter_sandbox() -> str:
    """Sandbox-runtime settings to start from: the package registries reachable, the usual secrets unreadable."""
    secrets = [*STARTER_SECRETS, str(credentials_path().parent)]
    rules = {
        "network": {"allowedDomains": STARTER_REGISTRIES, "deniedDomains": []},
        "filesystem": {"denyRead": secrets, "allowWrite": [], "denyWrite": []},
    }
    return json.dumps(rules, indent=2) + "\n"


def _host_cua(environment: dict[str, str]) -> dict[str, list[Path]]:
    """Start the cua daemon here, where it can drive the screen, and give the confined commands its socket."""
    from cua_cli.config import load

    host = {**os.environ, **environment}
    started = subprocess.run(["cua", "windows"], env=host, capture_output=True, text=True)
    if started.returncode:
        raise RuntimeError(f"the cua daemon did not start: {(started.stderr or started.stdout).strip()}")
    cua = load(host)
    # With CUA_SOCKET set, a cua command never starts a daemon: one started inside the sandbox cannot see the screen.
    environment["CUA_SOCKET"] = str(cua.socket)
    return {"writable": [cua.state()], "sockets": [cua.socket]}
