from __future__ import annotations

import json
import os
import stat
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
    return tmp_path


def make_program(folder: Path) -> Path:
    program = folder / "python"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    return program


@UNIX_ONLY
def test_install_registers_the_host_for_the_store_extension(tmp_path: Path) -> None:
    program = make_program(tmp_path)
    manifest = install.install_host(
        shim_command=[str(program), "-m", install.HOST_MODULE], hosts=[tmp_path / "hosts"], shim=tmp_path / "H" / "s.sh"
    )

    written = json.loads(manifest.read_text())
    assert manifest.name == f"{HOST_NAME}.json"
    assert written["name"] == HOST_NAME == "ai.hcompany.hai"
    assert written["type"] == "stdio"
    assert written["path"] == str(tmp_path / "H" / "s.sh")
    assert written["allowed_origins"] == [f"chrome-extension://{STORE_EXTENSION_ID}/"]
    assert os.access(tmp_path / "H" / "s.sh", os.X_OK)
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600


def test_the_dev_extension_id_is_allowed_beside_the_store_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dev = "a" * 32
    monkeypatch.setenv(DEV_EXTENSION_ENV, dev)

    manifest = install.install_host(hosts=[tmp_path / "hosts"], shim=tmp_path / "H" / "s.sh")

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


@UNIX_ONLY
def test_a_manifest_that_points_at_another_clients_working_shim_stays(tmp_path: Path) -> None:
    program = make_program(tmp_path)
    other = tmp_path / "other.sh"
    other.write_text(install.shim_script([str(program)]))
    other.chmod(0o755)
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    existing = hosts / f"{HOST_NAME}.json"
    existing.write_text(json.dumps({"name": HOST_NAME, "path": str(other)}))

    install.install_host(hosts=[hosts], shim=tmp_path / "H" / "s.sh")

    assert json.loads(existing.read_text())["path"] == str(other)
    assert not (tmp_path / "H" / "s.sh").exists()


@UNIX_ONLY
def test_a_manifest_whose_shim_program_is_gone_is_replaced(tmp_path: Path) -> None:
    other = tmp_path / "other.sh"
    other.write_text(install.shim_script([str(tmp_path / "deleted-venv" / "python"), "-m", "x"]))
    other.chmod(0o755)
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    existing = hosts / f"{HOST_NAME}.json"
    existing.write_text(json.dumps({"name": HOST_NAME, "path": str(other)}))

    install.install_host(hosts=[hosts], shim=tmp_path / "H" / "s.sh")

    assert json.loads(existing.read_text())["path"] == str(tmp_path / "H" / "s.sh")


def test_a_manifest_that_points_nowhere_is_replaced(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    existing = hosts / f"{HOST_NAME}.json"
    existing.write_text(json.dumps({"name": HOST_NAME, "path": str(tmp_path / "gone.sh")}))

    install.install_host(hosts=[hosts], shim=tmp_path / "H" / "s.sh")

    assert json.loads(existing.read_text())["path"] == str(tmp_path / "H" / "s.sh")


def test_our_own_manifest_is_rewritten_each_start(tmp_path: Path) -> None:
    shim, hosts = tmp_path / "H" / "s.sh", [tmp_path / "hosts"]
    install.install_host(hosts=hosts, shim=shim, shim_command=["a"])
    install.install_host(hosts=hosts, shim=shim, shim_command=["b"])

    assert shim.read_text() == install.shim_script(["b"])


def test_an_extension_id_that_is_not_one_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid Chrome extension id"):
        install.install_host(hosts=[tmp_path], shim=tmp_path / "s.sh", extension_ids=("not-an-id",))


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
    install.install_host(shim=isolated / "s.sh", shim_command=["a"])
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

    manifest = install.install_host(shim_command=[r"C:\Program Files\Python\python.exe", "-m", install.HOST_MODULE])

    assert winreg.values[install.REGISTRY_KEY] == str(manifest)
    assert install.REGISTRY_KEY.endswith(r"NativeMessagingHosts\ai.hcompany.hai")
    shim = Path(json.loads(manifest.read_text())["path"])
    assert (
        shim.read_bytes().decode()
        == f'@echo off\r\n@chcp 65001>nul\r\n"C:\\Program Files\\Python\\python.exe" -m {install.HOST_MODULE} %*\r\n'
    )
    assert install.shim_program(shim) == r"C:\Program Files\Python\python.exe"


def test_a_windows_shim_names_a_non_ascii_interpreter_in_utf8_after_switching_cmd_to_utf8(
    monkeypatch: pytest.MonkeyPatch, isolated: Path
) -> None:
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())
    monkeypatch.setattr(install, "platform_name", lambda: "win32")
    python = r"C:\Users\José\AppData\Local\Programs\Python\python.exe"

    manifest = install.install_host(shim_command=[python, "-m", install.HOST_MODULE])

    shim = Path(json.loads(manifest.read_text())["path"])
    first, switch, run = shim.read_bytes().split(b"\r\n")[:3]
    assert (first, switch) == (b"@echo off", b"@chcp 65001>nul")
    assert run.decode("utf-8").startswith(python)
    assert install.shim_program(shim) == python


def test_windows_leaves_a_registered_manifest_whose_program_exists(
    monkeypatch: pytest.MonkeyPatch, isolated: Path
) -> None:
    winreg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", winreg)
    monkeypatch.setattr(install, "platform_name", lambda: "win32")
    program = make_program(isolated)
    other_shim = isolated / "other.cmd"
    other_shim.write_text(install.shim_script([str(program)]))
    other_shim.chmod(0o755)
    other_manifest = isolated / "other.json"
    other_manifest.write_text(json.dumps({"name": HOST_NAME, "path": str(other_shim)}))
    winreg.values[install.REGISTRY_KEY] = str(other_manifest)

    assert install.install_host(shim_command=["x"]) == other_manifest
    assert json.loads(other_manifest.read_text())["path"] == str(other_shim)
