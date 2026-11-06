"""Registers the native messaging host with Chrome: the manifest it reads and the shim it starts."""

from __future__ import annotations

import json
import re
import shlex
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


def cmd_quote(arg: str) -> str:
    """One argument for a batch line: quoted, so `&`, `|`, `<`, `>` and `^` stay literal; `%` doubled, since cmd.exe
    expands it even inside quotes; trailing backslashes doubled, so they do not escape the closing quote."""
    trailing = len(arg) - len(arg.rstrip("\\"))
    return '"' + arg.replace("%", "%%") + "\\" * trailing + '"'


def shim_script(command: list[str]) -> str:
    """On Windows, cmd.exe decodes each batch line in the console code page: switching it to UTF-8 first lets the
    UTF-8 script name any interpreter path."""
    if platform_name() == "win32":
        return f"@echo off\r\n@chcp 65001>nul\r\n{' '.join(cmd_quote(arg) for arg in command)} %*\r\n"
    return f'#!/bin/sh\nexec {shlex.join(command)} "$@"\n'


def _register_manifest(manifest: Path) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))


def install_host() -> Path:
    """Writes the shim and the host manifest where Chrome looks; returns the manifest path."""
    extension_ids = allowed_extension_ids()
    invalid = [value for value in extension_ids if not EXTENSION_ID.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid Chrome extension id: {invalid[0]!r}")
    shim = shim_path()
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.parent.chmod(0o700)
    shim.write_text(shim_script(default_shim_command()), encoding="utf-8", newline="")
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
    manifests = [folder / f"{HOST_NAME}.json" for folder in hosts_dirs()]
    for manifest in manifests:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(document, encoding="utf-8")
        manifest.chmod(0o600)
    if platform_name() == "win32":
        _register_manifest(manifests[0])
    return manifests[0]
