"""Shell desktop bridge: the agent's shell runs on this machine and drives it through the desk, cua and web CLIs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hai_agents.client import credentials_path

from .bridge import LocalBridge, TokenSource
from .config import machine_allowlist, refuse_unread_settings, shell_sandbox
from .connections import Connection, connections_path, load_connections
from .desktop import ensure_macos_input_permissions
from .mcporter import shell_tools
from .resolver import Resolver
from .runtime.install import install_pinned
from .transport import Json, serialize_result

if TYPE_CHECKING:
    from cua_cli.config import Config
    from hai_drivers.code_sandbox.interface import CommandPolicy, ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "A desktop with a shell requires extra deps. Install with: pip install 'hai-agents[shell]'"
COMMAND_REFUSED = "command_refused"
SANDBOX_HINT = (
    "Anthropic's sandbox-runtime confines shell commands to the workspace. macOS downloads it on the first session; "
    "elsewhere: npm install -g --omit=optional @anthropic-ai/sandbox-runtime (needs Node 22.12 or later), "
    "then on Windows, once and as an administrator: srt windows-install"
)
# Standalone builds of sandbox-runtime, which need no Node: hai's publish_sandbox_runtime.sh makes and uploads them.
SRT_CDN = "https://assets.hcompanyprod.fr/sandbox-runtime"
SRT_VERSION = "0.0.82"
SRT_SHA256 = {
    "darwin-arm64": "51e9de47563827184a1b50d91edbd3077c2a8ac79ffe7e7d82b7c0efa9280dca",
    "darwin-x86_64": "09d1654458ffb79d7ffcfcf1c066257cd6a3d842afed923797f40aa8a2f4e75b",
}
SRT_HOME = Path.home() / ".hai" / "sandbox-runtime"
STARTER_ALLOWLIST = """\
# Commands the agent runs on this machine without asking, one prefix a line. Any other waits for your approval.
# `cua` sees and drives this screen: its clicks and keys do whatever you can do here, outside any sandbox.
cua
# `mcporter list` names the MCP servers in mcp.json, beside this file, and their tools: it reads, and changes nothing.
mcporter list
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
    "~/.mcporter",
    "~/Library/Application Support/Claude",
    "~/.bash_history",
    "~/.zsh_history",
    "~/Library/Keychains",
    "~/Library/Cookies",
    "~/Library/Application Support/Google/Chrome",
]
_SECRET_NAME = re.compile(r"API_?KEY|ACCESS_KEY|PRIVATE_KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)
_SECRET_URL = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def _workspace(session_id: str) -> Path:
    """The current folder; a new one under ~/hai when that is the home folder or above it."""
    here, home = Path.cwd().resolve(), Path.home()
    above = here == Path(here.anchor) or home.resolve().is_relative_to(here)
    return home / "hai" / session_id if above else here


class WorkstationBridge(LocalBridge["ManagedCodeSandboxInterface"]):
    """Serves shell-mode desktops with a shell in the workspace, running as the current user."""

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
        only: Sequence[str] = (),
        connections: Sequence[Connection] | None = None,
    ) -> None:
        """Build the bridge.

        The last five are the agent's, from its desktop's shell mode. What the machine sets itself wins: an
        allowlist passed here decides alone which commands wait, its own settings file what the sandbox lets
        through, and it serves no agent that requires a sandbox it turned off.

        Args:
            workspace: The folder the shell starts in and the file tools act in; defaults to the current one,
                and from the home folder or above it to ``~/hai/<session_id>``. With ``only``, always the latter.
            policy: This machine's allowlist file, one command prefix a line. With one, the shell runs the
                commands it covers and holds any other until the session's client approves it, whatever the agent
                asks. Without one, commands wait only for an agent that requires approval. A file that does not
                exist yet starts with ``cua`` allowed.
            sandbox: This machine's sandbox-runtime settings file; defaults to ``sandbox.json`` beside the stored
                credentials. Every command runs under ``srt`` by its rules: it writes in the workspace and reaches
                the ``cua`` daemon, which this bridge starts outside the sandbox. Where that file does not exist,
                the rules are the built-in ones: the package registries reachable, the usual credential files
                unreadable, the environment's tokens unset. ``False`` runs commands unconfined. A Mac without
                ``srt`` downloads it under ``~/.hai`` on its first session. Where there is none and none to
                download, the default sandbox gives way with a warning and commands run unconfined; one asked for
                here, by the agent or by a settings file of the machine's own fails the session.
            require_approval: Hold commands for approval by the allowlist beside the stored credentials, which
                ``always allow`` adds to.
            allowed_commands: Prefixes that run without approval besides that file's.
            require_sandbox: Serve no session whose commands would run unconfined.
            allowed_domains: Hosts the built-in rules let commands reach besides the registries.
            writable_folders: Folders the built-in rules let commands write besides the workspace.
            only: Programs the shell runs, refusing every other command with no approval to wait for; the
                allowlists and the sandbox then do not apply, and the bridge leaves the screen to other agents.
            connections: The MCP servers the shell reaches with ``mcporter``; defaults to ``mcp.json`` beside the
                stored credentials, and to none with ``only``. An app with its own servers passes ``[]``.

        Under either, the agent's file tools stay inside the workspace.
        """
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.only = tuple(only)
        self.drives_desktop = not self.only
        if self.only:
            # `web` reaches Chrome over its debugging socket, outside any sandbox and without the screen.
            sandbox, require_sandbox = False, False
        if self.only:
            self.workspace = Path.home() / "hai" / self.session_id
        elif workspace:
            self.workspace = Path(workspace).expanduser().absolute()
        else:
            self.workspace = _workspace(self.session_id)
        self.environment_variables = dict(environment_variables or {})
        refuse_unread_settings()
        self.policy = policy
        self.allowed_commands: list[str] = []
        if require_approval and not policy:
            self.policy, self.allowed_commands = machine_allowlist(), list(allowed_commands)
        self.sandbox = None if sandbox is False else sandbox or shell_sandbox()
        self.require_sandbox = require_sandbox
        self._sandbox_asked = bool(sandbox or require_sandbox)
        self.allowed_domains, self.writable_folders = list(allowed_domains), list(writable_folders)
        self._starter: tempfile.TemporaryDirectory[str] | None = None
        self._mcporter: tempfile.TemporaryDirectory[str] | None = None
        self._resolver: Resolver | None = None
        self.connections = list(connections) if connections is not None else [] if self.only else load_connections()
        """This machine's MCP servers, served to the shell and named in the session request."""

    def preflight(self) -> None:
        _keep_off_path(self.workspace, ["srt"] if self.sandbox else [])
        self._sandbox_runtime()
        if sys.platform == "darwin" and not self.only:
            ensure_macos_input_permissions(prompt=True)

    def create_driver(self) -> ManagedCodeSandboxInterface:
        try:
            from hai_drivers.code_sandbox.local.driver import LocalCodeSandbox
            from hai_drivers.code_sandbox.server.engine import bash
        except ImportError as exc:
            raise ImportError(INSTALL_HINT) from exc
        _keep_off_path(self.workspace, ["srt"] if self.sandbox else [])
        path = os.environ.get("PATH", os.defpath)
        desk = shutil.which("desk", path=os.pathsep.join([sysconfig.get_path("scripts"), path]))
        if desk is None:
            raise ImportError(INSTALL_HINT)
        tools = os.pathsep.join([os.path.dirname(desk), path])
        # A file on Windows only: the bash beside `git`, which is looked up there in the current folder first.
        shell = [bash()] if os.path.dirname(bash()) else []
        _refuse_what_runs_the_session(
            self.workspace, [desk, *(shutil.which(cli, path=tools) for cli in ("cua", "web")), *shell]
        )
        subprocess.run([desk, "aliases"], check=True, capture_output=True)
        logger.info("workstation workspace: %s", self.workspace)
        environment = {
            **self.environment_variables,
            "COORDINATE_SYSTEM": "0-1000",
            "CUA_CURSOR": os.environ.get("CUA_CURSOR", "off"),
            "CUA_SESSION": self.session_id,
            "WEB_SESSION": self.session_id,
            "PATH": tools,
        }
        resolver = self._serve_connections(environment)
        policy: CommandPolicy | None = None
        allowed: Path | None = None
        sandbox = None
        if self.only:
            policy = _Only(self.only)
            logger.info("the shell runs only %s", ", ".join(self.only))
        elif self.policy:
            from hai_drivers.code_sandbox.local.allowlist import Allowlist

            allowed = Path(self.policy).expanduser()
            _refuse_a_guard_in(self.workspace, allowed)
            _starting_with(allowed, STARTER_ALLOWLIST)
            policy = Allowlist(allowed, also=self.allowed_commands)
            logger.info("commands outside %s wait for approval", allowed)
        srt = self._sandbox_runtime()
        if resolver and not srt:
            raise RuntimeError(
                f"MCP servers need the sandbox, so their keys stay out of the agent's shell. {SANDBOX_HINT}"
            )
        if srt:
            from hai_drivers.code_sandbox.local.sandbox_runtime import SandboxRuntime

            settings, config = Path(self.sandbox).expanduser(), credentials_path().parent
            protected = [
                config,
                *filter(Path.exists, [SRT_HOME]),
                *([allowed] if allowed else []),
            ]
            for guard in protected:
                _refuse_a_guard_in(self.workspace, guard)
            host = _host_cua(environment)
            # `web` keeps its daemon's socket in /tmp and reads Chrome's profile, and the sandbox's rules close both.
            host["outside"] = [*host.get("outside", []), "web"]
            asked = [
                f"{does} {', '.join(what)}"
                for does, what in (("reach", self.allowed_domains), ("write", self.writable_folders))
                if what
            ]
            if settings.exists():
                rules = f"the rules in {settings}"
                rules += f", which decide alone: the agent's asks to {' and '.join(asked)} are not added" * bool(asked)
                if resolver:
                    rules += f", and reach this machine's MCP servers at {resolver.host}"
                    _refuse_a_guard_in(self.workspace, settings)
                    owned = json.loads(settings.read_text(encoding="utf-8"))
                    settings = self._starter_settings(
                        config,
                        _with_resolver(
                            owned,
                            resolver,
                            passed=self.environment_variables,
                            mcporter=Path(self._mcporter.name) if self._mcporter else None,
                        ),
                    )
            else:
                rules = "the built-in rules" + f", and may {' and '.join(asked)} as the agent asks" * bool(asked)
                rules += f"; a {settings} replaces them"
                built_in = _starter_sandbox(self.environment_variables, self.allowed_domains)
                settings = self._starter_settings(
                    config,
                    (
                        _with_resolver(
                            built_in,
                            resolver,
                            passed=self.environment_variables,
                            mcporter=Path(self._mcporter.name) if self._mcporter else None,
                        )
                        if resolver
                        else built_in
                    ),
                )
                host["writable"] = [*host.get("writable", []), *map(Path, self.writable_folders)]
            _refuse_a_guard_in(self.workspace, settings)
            sandbox = SandboxRuntime(settings, protected=protected, program=srt, **host)
            # A warning, so that it shows where nothing sets logging up: `holo`, `holo mcp`, a script.
            logger.warning("shell commands are confined to %s by %s", self.workspace, rules)
        elif self.sandbox:
            logger.warning("shell commands run unconfined, as you. %s", SANDBOX_HINT)
        elif not self.only:
            logger.warning("commands run unconfined, as you: no sandbox is on")
        return LocalCodeSandbox(
            str(self.workspace),
            environment_variables=environment,
            policy=policy,
            sandbox=sandbox,
            folders=[_cua({**os.environ, **environment}).state()],
        )

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            await asyncio.to_thread(self._stop_connections)

    def _serve_connections(self, environment: dict[str, str]) -> Resolver | None:
        """Serve this machine's MCP servers to the shell's `mcporter`; None where it has none."""
        if not self.connections:
            return None
        self._resolver = Resolver(self.connections)
        self._resolver.start()
        folder = _private_temp(self.workspace, credentials_path().parent)
        self._mcporter = tempfile.TemporaryDirectory(prefix="hai-mcp-", dir=folder)
        variables, tools = shell_tools(Path(self._mcporter.name), self._resolver)
        environment.update(variables)
        environment["PATH"] = os.pathsep.join([str(tools), environment["PATH"]])
        return self._resolver

    def _stop_connections(self) -> None:
        resolver, self._resolver = self._resolver, None
        if resolver is not None:
            resolver.stop()
        folder, self._mcporter = self._mcporter, None
        if folder is not None:
            folder.cleanup()

    def _starter_settings(self, config: Path, rules: Mapping[str, Any]) -> Path:
        self._starter = tempfile.TemporaryDirectory(prefix="hai-sandbox-", dir=_private_temp(self.workspace, config))
        settings = Path(self._starter.name) / "sandbox.json"
        settings.write_text(json.dumps(rules), encoding="utf-8")
        return settings

    def _sandbox_runtime(self) -> str | None:
        """This machine's `srt`; None where commands run unconfined."""
        if not self.sandbox:
            if self.require_sandbox:
                raise RuntimeError("The agent requires the sandbox, and this session turns it off.")
            return None
        try:
            return _sandbox_runtime(self.workspace)
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

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Json, str | None]:
        if self.only and name == "approve_command":
            return None, f"this machine approves no command: it runs only {_named(self.only)}"
        if self.only and name == "execute" and (refused := _Only(self.only).refusal(args.get("command", ""))):
            from hai_drivers.code_sandbox.interface import ShellResult

            # Exit 126 as a shell answers a program it cannot run: an error would end the session's startup probe.
            return serialize_result(ShellResult(stderr=refused, exit_code=126, execution_time=0.0)), None
        return super()._dispatch(name, args)

    def _is_expected(self, exc: Exception) -> bool:
        from hai_drivers.code_sandbox.interface import CodeSandboxRequestError
        from hai_drivers.common.exceptions import CommandApprovalRequired

        refused = isinstance(exc, CodeSandboxRequestError) and exc.code == COMMAND_REFUSED
        return refused or isinstance(exc, CommandApprovalRequired)


class _Only:
    """Runs a command made only of calls to ``programs``, and refuses any other."""

    def __init__(self, programs: Sequence[str]) -> None:
        self.programs = frozenset(programs)

    def refusal(self, command: str) -> str | None:
        from hai_drivers.code_sandbox.local.allowlist import only_runs

        if only_runs(command, self.programs):
            return None
        return f"this machine runs only {_named(self.programs)} for this agent, each called by its bare name"

    def hold(self, command: str) -> str | None:
        from hai_drivers.code_sandbox.interface import CodeSandboxRequestError

        if refused := self.refusal(command):
            raise CodeSandboxRequestError(COMMAND_REFUSED, {"message": refused})
        return None


def _named(programs: Iterable[str]) -> str:
    return " and ".join(f"`{program}`" for program in sorted(programs))


def _refuse_what_runs_the_session(workspace: Path, programs: Sequence[str | None]) -> None:
    """A workspace holds none of what runs the session outside its guards: a command there could rewrite it."""
    for program in filter(None, [sys.prefix, sys.base_prefix, __file__, *programs]):
        if _holds(workspace, Path(program)):
            raise ValueError(
                f"{program} runs this session and is inside the workspace {workspace}, where the agent writes: "
                "work in a folder that does not hold it, or install hai-agents outside this one"
            )


def _refuse_a_guard_in(workspace: Path, guard: Path) -> None:
    if _holds(workspace, guard):
        raise ValueError(f"{guard} is inside the workspace, where the agent writes: work in another folder")


def _keep_off_path(workspace: Path, needed: Sequence[str]) -> None:
    """Take off this process's PATH each folder that is relative or in the workspace: the agent could write there."""
    folders = os.environ.get("PATH", os.defpath).split(os.pathsep)
    kept = [folder for folder in folders if os.path.isabs(folder) and not _holds(workspace, Path(folder))]
    if not kept:
        # An empty PATH is the current folder, which is the workspace.
        raise ValueError(f"PATH holds only folders the agent could write: {os.pathsep.join(folders)!r}")
    for program in needed:
        found = shutil.which(program)
        if found and found != shutil.which(program, path=os.pathsep.join(kept)):
            raise ValueError(
                f"{found} runs this session and is in a folder the agent could write: install it outside the "
                "workspace, or take its folder off PATH"
            )
    if kept != folders:
        os.environ["PATH"] = os.pathsep.join(kept)
    if named := [folder for folder in folders if folder and folder not in kept]:
        # A warning, so that it shows where nothing sets logging up: `holo`, `holo mcp`, a script.
        logger.warning("programs are no longer looked up in %s, where the agent could write one", ", ".join(named))


def _holds(folder: Path, path: Path) -> bool:
    """Whether `path`, or the file it links to, is in `folder`, under any name the disk opens that folder by."""
    names = {folder.absolute(), folder.resolve()}
    ends = {path.absolute(), path.resolve()}
    on_the_way = {place for end in ends for place in (end, *end.parents)}
    there = os.path.exists(folder)
    return any(
        place in names or (there and os.path.exists(place) and os.path.samefile(place, folder)) for place in on_the_way
    )


def _starting_with(rules: Path, starter: str) -> None:
    """Write the machine's rules file with `starter` when it does not exist yet."""
    if not rules.exists():
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(starter, encoding="utf-8")
        logger.info("wrote starter rules: %s", rules)


def _sandbox_runtime(workspace: Path) -> str:
    """This machine's `srt`: its own on PATH, else the pinned build, downloaded on its first use."""
    srt = shutil.which("srt") or _pinned_sandbox_runtime()
    if srt is None:
        raise RuntimeError(f"The sandbox this session requires is not installed. {SANDBOX_HINT}")
    try:
        from hai_drivers.code_sandbox.local.sandbox_runtime import launch
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    command = launch(srt)
    _refuse_what_runs_the_session(workspace, command)
    started = subprocess.run([*command, "--version"], capture_output=True, text=True)
    if started.returncode:
        raise RuntimeError(f"{srt} did not start: {started.stderr.strip()[-300:]} {SANDBOX_HINT}")
    return str(srt)


def _pinned_sandbox_runtime() -> Path | None:
    return install_pinned(
        "srt", SRT_HOME / SRT_VERSION, SRT_SHA256, lambda platform: f"{SRT_CDN}/{SRT_VERSION}/srt-{platform}.zip"
    )


def _private_temp(workspace: Path, config: Path) -> Path | None:
    """Where a session's own temporary files go: the system's folder, else beside the stored credentials.

    A folder, as Windows opens a temporary file a second time for nobody while it is open; beside the credentials
    where the system's temporary folder is in the workspace, and a command could write it."""
    if not _holds(workspace, Path(tempfile.gettempdir())):
        return None
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    return config


def _with_resolver(
    rules: Mapping[str, Any],
    resolver: Resolver,
    *,
    passed: Mapping[str, str] | None = None,
    mcporter: Path | None = None,
) -> dict[str, Any]:
    """`rules` that also let commands reach `resolver`, and never read the keys of the servers it serves.

    Always applies the built-in secret-env scrub, even when the user owns ``sandbox.json``.
    """
    passed = dict(passed or ())
    network, filesystem = dict(rules.get("network") or {}), dict(rules.get("filesystem") or {})
    credentials = dict(rules.get("credentials") or {})
    network["allowedDomains"] = [*network.get("allowedDomains", []), resolver.host]
    denied = [
        str(connections_path()),
        str(credentials_path()),
        *([str(mcporter / "mcporter.json")] if mcporter else []),
    ]
    filesystem["denyRead"] = [*filesystem.get("denyRead", []), *denied]
    keys = sorted({name for connection in resolver.connections.values() for name in connection.variables})
    tokens = sorted(
        name
        for name, value in os.environ.items()
        if name not in passed and (_SECRET_NAME.search(name) or _SECRET_URL.search(value))
    )
    scrub = [*({"name": name, "mode": "deny"} for name in dict.fromkeys([*keys, *tokens]))]
    credentials["envVars"] = [*credentials.get("envVars", []), *scrub]
    return {**rules, "network": network, "filesystem": filesystem, "credentials": credentials}


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


def _cua(environment: Mapping[str, str]) -> Config:
    try:
        from cua_cli.config import load
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return load(environment)


def _host_cua(environment: dict[str, str]) -> dict[str, Sequence[str | Path]]:
    """What lets a confined shell drive the screen: `cua` outside the sandbox, or on macOS its daemon's socket."""
    if sys.platform != "darwin":
        # Only macOS opens one socket by its path: a Linux sandbox opens every socket or none, a Windows one no pipe.
        return {"outside": ["cua"]}
    host = {**os.environ, **environment}
    started = subprocess.run(["cua", "windows"], env=host, capture_output=True, text=True)
    if started.returncode:
        raise RuntimeError(f"the cua daemon did not start: {(started.stderr or started.stdout).strip()}")
    cua = _cua(host)
    # With CUA_SOCKET set, a cua command never starts a daemon: one started inside the sandbox cannot see the screen.
    environment["CUA_SOCKET"] = str(cua.socket)
    return {"writable": [cua.state()], "sockets": [cua.socket]}
