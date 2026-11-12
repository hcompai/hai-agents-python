"""Shell desktop bridge: the agent's shell runs on this machine and drives it through the desk, cua and web CLIs."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Literal

from hai_agents.client import credentials_path

from .bridge import LocalBridge, TokenSource
from .config import SHELL_SANDBOX_ENV_VAR, agent_shell_policy, shell_policy, shell_sandbox
from .desktop import ensure_macos_input_permissions

if TYPE_CHECKING:
    from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "A desktop with a shell requires extra deps. Install with: pip install 'hai-agents[workstation]'"
SANDBOX_HINT = (
    "Anthropic's sandbox-runtime confines shell commands to the workspace: "
    "npm install -g --omit=optional @anthropic-ai/sandbox-runtime (needs Node 22.12 or later)."
)
# Where npm puts `srt`: an app started from the Dock gives its children a PATH without them.
SRT_HOMES = ["/opt/homebrew/bin", "/usr/local/bin", "~/.volta/bin", "~/.npm-global/bin", "~/.nvm/versions/node/*/bin"]
STARTER_ALLOWLIST = """\
# Commands the agent runs on this machine without asking, one prefix a line. Any other waits for your approval.
# `cua` sees and drives this screen: its clicks and keys do whatever you can do here, outside any sandbox.
cua
"""
STARTER_REGISTRIES = ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]
STARTER_SECRETS = [
    "~/.ssh",
    "~/.aws",
    "~/.azure",
    "~/.gnupg",
    "~/.netrc",
    "~/.kube",
    "~/.config/gcloud",
    "~/.config/gh",
    "~/.git-credentials",
    "~/.docker/config.json",
    "~/.npmrc",
    "~/.pypirc",
    "~/.pip",
    "~/.config/pip",
    "~/.codex",
    "~/.claude.json",
    "~/.cursor/mcp.json",
    "~/.bash_history",
    "~/.zsh_history",
    "~/Library/Keychains",
    "~/Library/Cookies",
    "~/Library/Application Support/Google/Chrome",
]
_SECRET_NAME = re.compile(r"API_?KEY|ACCESS_KEY|PRIVATE_KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)
_SECRET_URL = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


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
        require_approval: bool = False,
        allowed_commands: Sequence[str] = (),
        require_sandbox: bool = False,
        allowed_domains: Sequence[str] = (),
        writable_folders: Sequence[str] = (),
    ) -> None:
        """Build the bridge.

        The last five are the agent's, from its desktop's shell mode. What the machine sets itself wins: its own
        allowlist decides alone which commands wait, its own settings file what the sandbox lets through, and it
        serves no agent that requires a sandbox it turned off.

        Args:
            policy: This machine's allowlist file, one command prefix a line; defaults to ``HAI_SHELL_POLICY``.
                With one, the shell runs the commands it covers and holds any other until the session's client
                approves it. Without one, every command runs. A file that does not exist yet starts with ``cua``
                allowed.
            sandbox: This machine's sandbox-runtime settings file. Every command runs under ``srt`` by its rules:
                it writes in the workspace and reaches the ``cua`` daemon, which this bridge starts outside the
                sandbox. Defaults to ``HAI_SHELL_SANDBOX``, else on macOS to ``sandbox.json`` beside the stored
                credentials. Where that file does not exist, the rules are the built-in ones: the package
                registries reachable, the usual credential files unreadable, the environment's tokens unset.
                ``False`` runs commands unconfined. Where ``srt`` is not installed, the default sandbox gives way
                with a warning and commands run unconfined; one asked for here, by ``HAI_SHELL_SANDBOX`` or by a
                settings file of the machine's own fails the session.
            require_approval: Hold commands for approval on a machine without an allowlist too, by the one beside
                the stored credentials.
            allowed_commands: Prefixes that run without approval besides that file's.
            require_sandbox: Serve no session whose commands would run unconfined.
            allowed_domains: Hosts the built-in rules let commands reach besides the registries.
            writable_folders: Folders the built-in rules let commands write besides the workspace.

        Under either, the agent's file tools stay inside the workspace.
        """
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.workspace = Path(workspace).expanduser() if workspace else Path.home() / "hai" / self.session_id
        self.environment_variables = dict(environment_variables or {})
        self.policy = policy or shell_policy()
        self.allowed_commands: list[str] = []
        if require_approval and not self.policy:
            self.policy, self.allowed_commands = agent_shell_policy(), list(allowed_commands)
        self.sandbox = None if sandbox is False else sandbox or shell_sandbox(required=require_sandbox)
        self.require_sandbox = require_sandbox
        self._sandbox_asked = bool(sandbox or require_sandbox or os.getenv(SHELL_SANDBOX_ENV_VAR, "").strip())
        self.allowed_domains, self.writable_folders = list(allowed_domains), list(writable_folders)
        self._starter: IO[str] | None = None

    def preflight(self) -> None:
        self._sandbox_runtime()
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
            policy = Allowlist(allowed, also=self.allowed_commands)
            logger.info("commands outside %s wait for approval", allowed)
        srt = self._sandbox_runtime()
        if srt:
            from hai_drivers.code_sandbox.local.sandbox_runtime import SandboxRuntime

            settings = Path(self.sandbox).expanduser()
            host = _host_cua(environment)
            asked = [
                f"{does} {', '.join(what)}"
                for does, what in (("reach", self.allowed_domains), ("write", self.writable_folders))
                if what
            ]
            if settings.exists():
                rules = f"the rules in {settings}"
                rules += f", which decide alone: the agent's asks to {' and '.join(asked)} are not added" * bool(asked)
            else:
                rules = "the built-in rules" + f", and may {' and '.join(asked)} as the agent asks" * bool(asked)
                rules += f"; a {settings} replaces them"
                self._starter = tempfile.NamedTemporaryFile("w", prefix="hai-sandbox-", suffix=".json")
                json.dump(_starter_sandbox(self.environment_variables, self.allowed_domains), self._starter)
                self._starter.flush()
                host["writable"] = [*host.get("writable", []), *map(Path, self.writable_folders)]
                settings = Path(self._starter.name)
            protected = [credentials_path().parent, *([policy.path] if policy else [])]
            sandbox = SandboxRuntime(settings, protected=protected, program=srt, **host)
            # A warning, so that it shows where nothing sets logging up: `holo`, `holo mcp`, a script.
            logger.warning("shell commands are confined to %s by %s", self.workspace, rules)
        elif self.sandbox:
            logger.warning("shell commands run unconfined, as you. %s", SANDBOX_HINT)
        else:
            logger.warning("commands run unconfined, as you: no sandbox is on")
        return LocalCodeSandbox(str(self.workspace), environment_variables=environment, policy=policy, sandbox=sandbox)

    def _sandbox_runtime(self) -> str | None:
        """This machine's `srt`; None where commands run unconfined."""
        if not self.sandbox:
            if self.require_sandbox:
                raise RuntimeError(
                    f"The agent requires the sandbox, and this machine turns it off: unset {SHELL_SANDBOX_ENV_VAR}."
                )
            return None
        try:
            return _sandbox_runtime()
        except RuntimeError:
            if self._sandbox_asked or Path(self.sandbox).expanduser().exists():
                raise
            return None

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


def _sandbox_runtime() -> str:
    """This machine's `srt`, on PATH or where npm puts it."""
    if os.name == "nt":
        raise RuntimeError("The sandbox runs on macOS and Linux.")
    homes = [home for pattern in SRT_HOMES for home in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)]
    srt = shutil.which("srt", path=os.pathsep.join([os.environ.get("PATH", os.defpath), *homes]))
    if srt is None:
        raise RuntimeError(f"The sandbox this session requires is not installed. {SANDBOX_HINT}")
    try:
        from hai_drivers.code_sandbox.local.sandbox_runtime import launch
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    started = subprocess.run([*launch(srt), "--version"], capture_output=True, text=True)
    if started.returncode:
        raise RuntimeError(f"{srt} did not start: {started.stderr.strip()[-300:]} {SANDBOX_HINT}")
    return srt


def _starter_sandbox(passed: Mapping[str, str], domains: Sequence[str] = ()) -> dict[str, object]:
    """Sandbox-runtime settings for a machine with none of its own; `passed` are the variables the host gives the agent."""
    secrets = [*STARTER_SECRETS, str(credentials_path().parent)]
    tokens = sorted(
        name
        for name, value in os.environ.items()
        if name not in passed and (_SECRET_NAME.search(name) or _SECRET_URL.search(value))
    )
    return {
        "network": {"allowedDomains": [*STARTER_REGISTRIES, *domains], "deniedDomains": []},
        "filesystem": {"denyRead": secrets, "allowWrite": [], "denyWrite": []},
        "credentials": {"envVars": [{"name": name, "mode": "deny"} for name in tokens]},
    }


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
