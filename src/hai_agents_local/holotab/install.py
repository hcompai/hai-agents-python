"""Registers the native messaging host with Chrome: the manifest it reads and the shim it starts."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .endpoint import HOST_NAME, allowed_extension_ids, shared_dir

HOST_MODULE = "hai_agents_local.holotab.host"
EXTENSION_ID = re.compile(r"[a-p]{32}")
REGISTRY_KEY = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"


def platform_name() -> str:
    return sys.platform


def default_shim_command() -> list[str]:
    """The venv's own `python`: resolving its symlink would give the base interpreter, which cannot import this."""
    return [sys.executable, "-m", HOST_MODULE]


def hosts_dirs() -> list[Path]:
    home = Path.home()
    if platform_name() == "darwin":
        return [home / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"]
    if platform_name() == "win32":
        return [shared_dir()]
    return [
        home / ".config" / "google-chrome" / "NativeMessagingHosts",
        home / ".config" / "chromium" / "NativeMessagingHosts",
    ]


def shim_path() -> Path:
    return shared_dir() / ("holotab-native-host.cmd" if platform_name() == "win32" else "holotab-native-host.sh")


def shim_script(command: list[str]) -> str:
    """On Windows, cmd.exe decodes each batch line in the console code page: switching it to UTF-8 first lets the
    UTF-8 script name any interpreter path."""
    if platform_name() == "win32":
        return f"@echo off\r\n@chcp 65001>nul\r\n{subprocess.list2cmdline(command)} %*\r\n"
    return f'#!/bin/sh\nexec {shlex.join(command)} "$@"\n'


def shim_program(shim: Path) -> str | None:
    """The program a shim runs, read back from its script."""
    try:
        lines = shim.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("exec "):
            words = shlex.split(line[len("exec ") :])
        elif line.strip() and not line.startswith(("#", "@")):
            words = shlex.split(line.replace("\\", "\\\\"))
        else:
            continue
        return words[0] if words else None
    return None


def shim_works(shim: Path) -> bool:
    if not shim.is_file() or not os.access(shim, os.X_OK):
        return False
    program = shim_program(shim)
    return program is not None and (Path(program).exists() or shutil.which(program) is not None)


def other_client_serves(manifest: Path, shim: Path) -> bool:
    """A manifest that names another client's shim, whose program still exists, is left as it is: the shim only
    relays to the one endpoint, so whichever client wrote it works for both."""
    try:
        registered = Path(json.loads(manifest.read_text(encoding="utf-8")).get("path", ""))
    except (OSError, ValueError, AttributeError):
        return False
    return registered != shim and shim_works(registered)


def _registered_manifest() -> Path | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            return Path(winreg.QueryValueEx(key, "")[0])
    except OSError:
        return None


def _register_manifest(manifest: Path) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))


def host_registered(hosts: list[Path] | None = None) -> bool:
    """Whether Chrome already has a manifest for the host whose shim program exists."""
    manifests = [folder / f"{HOST_NAME}.json" for folder in (hosts or hosts_dirs())]
    if platform_name() == "win32" and (registered := _registered_manifest()) is not None:
        manifests = [registered]
    for manifest in manifests:
        try:
            if shim_works(Path(json.loads(manifest.read_text(encoding="utf-8")).get("path", ""))):
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def install_host(
    *,
    shim_command: list[str] | None = None,
    extension_ids: tuple[str, ...] | None = None,
    hosts: list[Path] | None = None,
    shim: Path | None = None,
) -> Path:
    """Writes the shim and the host manifest where Chrome looks; returns the manifest path."""
    extension_ids = allowed_extension_ids() if extension_ids is None else extension_ids
    invalid = [value for value in extension_ids if not EXTENSION_ID.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid Chrome extension id: {invalid[0]!r}")
    shim = shim or shim_path()
    windows = platform_name() == "win32"
    manifests = [folder / f"{HOST_NAME}.json" for folder in (hosts or hosts_dirs())]
    if windows and (registered := _registered_manifest()) is not None:
        manifests = [registered]
    pending = [manifest for manifest in manifests if not other_client_serves(manifest, shim)]
    if pending:
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.parent.chmod(0o700)
        shim.write_text(shim_script(shim_command or default_shim_command()), encoding="utf-8", newline="")
        shim.chmod(0o755)
    document = (
        json.dumps(
            {
                "name": HOST_NAME,
                "description": "The Agents API's link to the HoloTab extension",
                "path": str(shim),
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{value}/" for value in extension_ids],
            },
            indent=2,
        )
        + "\n"
    )
    for manifest in pending:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(document, encoding="utf-8")
        manifest.chmod(0o600)
    if windows and pending:
        _register_manifest(pending[0])
    return manifests[0]
