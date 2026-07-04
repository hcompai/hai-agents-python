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
