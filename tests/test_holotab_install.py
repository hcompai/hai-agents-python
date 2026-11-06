from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hai_agents_local.holotab import install
from hai_agents_local.holotab.endpoint import DEV_EXTENSION_ENV, HOST_NAME, STORE_EXTENSION_ID, allowed_extension_ids

UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and sh shims")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(DEV_EXTENSION_ENV, raising=False)
    monkeypatch.setenv("HAI_HOLOTAB_DIR", str(tmp_path / "shared"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())
    return tmp_path


def make_program(folder: Path) -> Path:
    program = folder / "python"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    return program


@UNIX_ONLY
def test_install_registers_the_host_for_the_store_extension() -> None:
    manifest = install.install_host()

    written = json.loads(manifest.read_text())
    assert manifest.name == f"{HOST_NAME}.json"
    assert written["name"] == HOST_NAME == "ai.hcompany.hai"
    assert written["type"] == "stdio"
    assert written["path"] == str(install.shim_path())
    assert written["allowed_origins"] == [f"chrome-extension://{STORE_EXTENSION_ID}/"]
    assert os.access(install.shim_path(), os.X_OK)
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600


def test_the_dev_extension_id_is_allowed_beside_the_store_id(monkeypatch: pytest.MonkeyPatch) -> None:
    dev = "a" * 32
    monkeypatch.setenv(DEV_EXTENSION_ENV, dev)

    manifest = install.install_host()

    assert allowed_extension_ids() == (STORE_EXTENSION_ID, dev)
    assert json.loads(manifest.read_text())["allowed_origins"] == [
        f"chrome-extension://{STORE_EXTENSION_ID}/",
        f"chrome-extension://{dev}/",
    ]


def test_an_unset_or_repeated_dev_id_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEV_EXTENSION_ENV, " ")
    assert allowed_extension_ids() == (STORE_EXTENSION_ID,)
    monkeypatch.setenv(DEV_EXTENSION_ENV, STORE_EXTENSION_ID)
    assert allowed_extension_ids() == (STORE_EXTENSION_ID,)


def test_the_default_shim_runs_the_host_module_with_the_unresolved_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "executable", "/venv/bin/python")
    assert install.default_shim_command() == ["/venv/bin/python", "-m", install.HOST_MODULE]
    monkeypatch.setattr(install, "platform_name", lambda: "linux")
    assert install.shim_script(["/venv/bin/python", "-m", "m"]) == '#!/bin/sh\nexec /venv/bin/python -m m "$@"\n'
    assert install.shim_script(["/my app/core", "--program", "host"]).startswith("#!/bin/sh\nexec '/my app/core' ")


@pytest.mark.parametrize("platform", [sys.platform, "win32"])
def test_a_manifest_another_client_wrote_is_replaced_with_ours(
    tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(install, "platform_name", lambda: platform)
    program = make_program(tmp_path)
    other = tmp_path / "other.sh"
    other.write_text(install.shim_script([str(program)]))
    other.chmod(0o755)
    existing = install.hosts_dirs()[0] / f"{HOST_NAME}.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(json.dumps({"name": HOST_NAME, "path": str(other)}))

    assert install.install_host() == existing
    assert json.loads(existing.read_text())["path"] == str(install.shim_path())


@pytest.mark.parametrize("platform", [sys.platform, "win32"])
def test_our_own_manifest_is_rewritten_each_start(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install, "platform_name", lambda: platform)
    monkeypatch.setattr(sys, "executable", "a")
    install.install_host()
    monkeypatch.setattr(sys, "executable", "b")
    install.install_host()

    assert install.shim_path().read_bytes().decode() == install.shim_script(["b", "-m", install.HOST_MODULE])


def test_an_extension_id_that_is_not_one_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEV_EXTENSION_ENV, "not-an-id")
    with pytest.raises(ValueError, match="invalid Chrome extension id"):
        install.install_host()


def test_macos_registers_under_chromes_application_support(monkeypatch: pytest.MonkeyPatch, isolated: Path) -> None:
    monkeypatch.setattr(install, "platform_name", lambda: "darwin")
    assert install.hosts_dirs() == [
        isolated / "home" / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"
    ]


def test_linux_registers_for_chrome_and_chromium(monkeypatch: pytest.MonkeyPatch, isolated: Path) -> None:
    monkeypatch.setattr(install, "platform_name", lambda: "linux")
    assert install.hosts_dirs() == [
        isolated / "home" / ".config" / "google-chrome" / "NativeMessagingHosts",
        isolated / "home" / ".config" / "chromium" / "NativeMessagingHosts",
    ]
    install.install_host()
    for name in ("google-chrome", "chromium"):
        assert (isolated / "home" / ".config" / name / "NativeMessagingHosts" / f"{HOST_NAME}.json").exists()


class FakeWinreg(types.SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(HKEY_CURRENT_USER="HKCU", REG_SZ=1, values={})

    def CreateKey(self, root: str, name: str):  # noqa: N802
        return self._Key(self, name)

    def OpenKey(self, root: str, name: str):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self._Key(self, name)

    def SetValueEx(self, key, _name: str, _reserved: int, _kind: int, value: str) -> None:  # noqa: N802
        self.values[key.name] = value

    def QueryValueEx(self, key, _name: str):  # noqa: N802
        return self.values[key.name], 1

    class _Key:
        def __init__(self, owner, name: str) -> None:
            self.owner, self.name = owner, name

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None


def test_windows_points_a_registry_key_at_the_manifest_and_writes_a_cmd_shim(
    monkeypatch: pytest.MonkeyPatch, isolated: Path
) -> None:
    winreg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", winreg)
    monkeypatch.setattr(install, "platform_name", lambda: "win32")
    assert install.shim_path().name == "holotab-native-host.cmd"

    manifest = install.install_host()

    assert winreg.values[install.REGISTRY_KEY] == str(manifest)
    assert install.REGISTRY_KEY.endswith(r"NativeMessagingHosts\ai.hcompany.hai")
    assert json.loads(manifest.read_text())["path"] == str(install.shim_path())


def test_a_windows_shim_names_a_non_ascii_interpreter_in_utf8_after_switching_cmd_to_utf8(
    monkeypatch: pytest.MonkeyPatch, isolated: Path
) -> None:
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())
    monkeypatch.setattr(install, "platform_name", lambda: "win32")
    python = r"C:\Users\José\AppData\Local\Programs\Python\python.exe"
    monkeypatch.setattr(sys, "executable", python)

    manifest = install.install_host()

    shim = Path(json.loads(manifest.read_text())["path"])
    first, switch, run = shim.read_bytes().split(b"\r\n")[:3]
    assert (first, switch) == (b"@echo off", b"@chcp 65001>nul")
    assert run.decode("utf-8").startswith(f'"{python}"')


@pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe")
def test_cmd_passes_ampersands_percent_signs_and_trailing_backslashes_through_the_shim_unchanged(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "R&D 100%"
    folder.mkdir()
    marker = folder / "ran %PATH% & more.txt"
    write = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('|'.join(sys.argv[2:]))"
    shim = tmp_path / "shim.cmd"
    command = [sys.executable, "-c", write, str(marker), "C:\\dir\\"]
    shim.write_text(install.shim_script(command), encoding="utf-8", newline="")

    subprocess.run([str(shim), "hello"], check=True, timeout=60)

    assert marker.read_text() == "C:\\dir\\|hello"
