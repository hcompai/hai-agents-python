"""hai_agents.local unit tests: state files, install, spawn lifecycle.

Offline by construction: a fake zip over a loopback http.server stands in for
the CDN, and a tiny Python HTTP script stands in for the runtime binary.
"""

from __future__ import annotations

import os
import stat

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="local-mode tests exercise POSIX process groups and file modes"
)


def test_all_local_errors_share_one_base() -> None:
    from hai_agents.local import errors

    for name in (
        "BinaryNotFoundError",
        "BinaryIncompatibleError",
        "RuntimeUnhealthyError",
        "RuntimeStartTimeoutError",
        "DownloadVerificationError",
    ):
        assert issubclass(getattr(errors, name), errors.LocalRuntimeError), name


def test_state_files_are_owner_only_and_round_trip(tmp_path) -> None:
    from hai_agents.local import state

    token_path = state.token_file_path(18795, cache_dir=tmp_path)
    state.write_owner_only(token_path, "tok-1")

    assert token_path == tmp_path / "state" / "agent-token-18795"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert state.read_state_file(token_path) == "tok-1"

    pid_path = state.pid_file_path(18795, cache_dir=tmp_path)
    state.write_owner_only(pid_path, "4242")
    assert state.read_pid(18795, cache_dir=tmp_path) == 4242


def test_write_owner_only_refuses_a_planted_symlink(tmp_path) -> None:
    from hai_agents.local import state

    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "state" / "agent-token-1"
    link.parent.mkdir(parents=True)
    link.symlink_to(victim)

    with pytest.raises(OSError):
        state.write_owner_only(link, "tok")
    assert victim.read_text() == "keep"


def test_cache_dir_resolution_order(tmp_path, monkeypatch) -> None:
    from hai_agents.local import state

    monkeypatch.setenv("HAI_AGENT_LOCAL_CACHE_DIR", str(tmp_path / "from-env"))
    assert state.resolve_cache_dir() == tmp_path / "from-env"
    # An explicit argument beats the env override.
    assert state.resolve_cache_dir(tmp_path / "explicit") == tmp_path / "explicit"
    monkeypatch.delenv("HAI_AGENT_LOCAL_CACHE_DIR")
    assert state.resolve_cache_dir() == state.DEFAULT_CACHE_DIR


def test_unlink_if_content_never_removes_a_replaced_token(tmp_path) -> None:
    from hai_agents.local import state

    path = state.token_file_path(1, cache_dir=tmp_path)
    state.write_owner_only(path, "mine")

    state.unlink_if_content(path, "not-mine")
    assert path.exists()
    state.unlink_if_content(path, "mine")
    assert not path.exists()


import contextlib
import functools
import hashlib
import http.server
import pathlib
import threading
import zipfile


@contextlib.contextmanager
def _serving(directory: pathlib.Path):
    """Serve `directory` on an ephemeral loopback port (http-on-loopback is allowed by the URL policy)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _fake_zip(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    payload = tmp_path / "hai-agent-runtime"
    payload.write_text("#!/bin/sh\nexit 0\n")
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(payload, arcname="hai-agent-runtime")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_env_override_download_verifies_and_installs_atomically(tmp_path, monkeypatch) -> None:
    from hai_agents.local import install

    _, digest = _fake_zip(tmp_path)
    cache = tmp_path / "cache"
    with _serving(tmp_path) as base:
        monkeypatch.setenv(install.DOWNLOAD_URL_ENV, f"{base}/artifact.zip")
        monkeypatch.setenv(install.DOWNLOAD_SHA256_ENV, digest)
        artifact = install.pinned_artifact()
        binary = install.install_runtime(artifact, version="0.0.0-test", cache_dir=cache)

    assert binary == cache / "bin" / "0.0.0-test" / "hai-agent-runtime"
    assert os.access(binary, os.X_OK)  # zipfile drops the exec bit; install must restore it
    assert install.installed_binary("0.0.0-test", cache_dir=cache) == binary


def test_sha256_mismatch_raises_and_installs_nothing(tmp_path) -> None:
    from hai_agents.local import install
    from hai_agents.local.errors import DownloadVerificationError

    _fake_zip(tmp_path)
    cache = tmp_path / "cache"
    with _serving(tmp_path) as base:
        artifact = install.RuntimeArtifact(url=f"{base}/artifact.zip", sha256="ab" * 32)
        with pytest.raises(DownloadVerificationError):
            install.install_runtime(artifact, version="0.0.0-test", cache_dir=cache)

    assert install.installed_binary("0.0.0-test", cache_dir=cache) is None


def test_download_url_env_without_sha_is_refused(monkeypatch) -> None:
    from hai_agents.local import install
    from hai_agents.local.errors import DownloadVerificationError

    monkeypatch.setenv(install.DOWNLOAD_URL_ENV, "https://example.test/runtime.zip")
    monkeypatch.delenv(install.DOWNLOAD_SHA256_ENV, raising=False)
    with pytest.raises(DownloadVerificationError, match="unverified"):
        install.pinned_artifact()


def test_non_loopback_plain_http_is_refused(tmp_path) -> None:
    from hai_agents.local import install
    from hai_agents.local.errors import LocalRuntimeError

    artifact = install.RuntimeArtifact(url="http://evil.example/runtime.zip", sha256="00" * 32)
    with pytest.raises(LocalRuntimeError, match="https"):
        install.install_runtime(artifact, version="0.0.0-test", cache_dir=tmp_path / "cache")


def test_manifest_pins_the_cdn_and_never_a_placeholder_digest() -> None:
    from hai_agents.local import manifest

    assert manifest.RUNTIME_CDN_BASE == "https://assets.hcompanyprod.fr/hai-agent-runtime"
    for key, artifact in manifest.MANIFEST.items():
        assert artifact.url.startswith(f"{manifest.RUNTIME_CDN_BASE}/{manifest.PINNED_RUNTIME_VERSION}/"), key
        assert artifact.sha256 != manifest.PLACEHOLDER_SHA256, key
        assert len(artifact.sha256) == 64, key
