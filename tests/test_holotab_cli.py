from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("typer")
pytest.importorskip("hai_drivers.web.interface")

from typer.testing import CliRunner  # noqa: E402

from hai_agents_cli.app import app  # noqa: E402
from hai_agents_local import HoloTabBrowserBridge  # noqa: E402


def test_holo_local_browser_holotab_installs_the_host_and_serves_the_holotab_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import install

    calls: list[Any] = []
    monkeypatch.setattr(install, "install_host", lambda **_: calls.append("install"))
    monkeypatch.setattr(
        cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.extend([bridge_type, opts])
    )

    result = CliRunner().invoke(app, ["local", "browser", "--holotab"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert calls == ["install", HoloTabBrowserBridge, {"client": "Holo CLI"}]
