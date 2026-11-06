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
    from hai_agents_local.holotab import bridge

    calls: list[Any] = []
    monkeypatch.setattr(bridge, "install_host", lambda: calls.append("install"))
    monkeypatch.setattr(
        cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.extend([bridge_type, opts])
    )

    result = CliRunner().invoke(app, ["local", "browser", "--holotab"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert calls == ["install", HoloTabBrowserBridge, {"client": "Holo CLI", "stop_on_refusal": True}]


def test_holo_local_browser_refuses_a_debug_port_with_holotab() -> None:
    result = CliRunner().invoke(
        app, ["local", "browser", "--holotab", "--debug-port", "9333"], env={"HAI_API_KEY": "hk-test"}
    )
    assert result.exit_code != 0
    assert "--debug-port" in result.output


@pytest.mark.parametrize(("flags", "options"), [([], {}), (["--debug-port", "9333"], {"debugging_port": 9333})])
def test_holo_local_browser_passes_only_an_explicit_debug_port_to_selenium(
    monkeypatch: pytest.MonkeyPatch, flags: list[str], options: dict[str, Any]
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local import SeleniumBrowserBridge

    calls: list[Any] = []
    monkeypatch.setattr(
        cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.extend([bridge_type, opts])
    )
    result = CliRunner().invoke(app, ["local", "browser", *flags], env={"HAI_API_KEY": "hk-test"})
    assert result.exit_code == 0, result.output
    assert calls == [SeleniumBrowserBridge, options]
