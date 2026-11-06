from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("typer")
pytest.importorskip("hai_drivers.web.interface")

from typer.testing import CliRunner  # noqa: E402

from hai_agents_cli.app import app  # noqa: E402
from hai_agents_local import HoloTabBrowserBridge, SeleniumBrowserBridge  # noqa: E402


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
    assert calls == ["install", HoloTabBrowserBridge, {"client": "Holo CLI", "label": None}]


def test_holo_local_browser_label_reaches_the_holotab_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import install

    calls: list[Any] = []
    monkeypatch.setattr(install, "install_host", lambda **_: None)
    monkeypatch.setattr(cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.append(opts))

    result = CliRunner().invoke(
        app, ["local", "browser", "--holotab", "--label", "My group"], env={"HAI_API_KEY": "hk-test"}
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"client": "Holo CLI", "label": "My group"}]


@pytest.mark.parametrize(
    ("args", "env", "connected", "expected"),
    [
        ([], {}, True, HoloTabBrowserBridge),
        ([], {}, False, SeleniumBrowserBridge),
        (["--selenium"], {}, True, SeleniumBrowserBridge),
        (["--holotab"], {}, False, HoloTabBrowserBridge),
        ([], {"HAI_LOCAL_BROWSER": "selenium"}, True, SeleniumBrowserBridge),
        (["--holotab"], {"HAI_LOCAL_BROWSER": "selenium"}, False, HoloTabBrowserBridge),
    ],
)
def test_holo_local_browser_follows_the_routing_rule_and_the_flags_force_one(
    monkeypatch: pytest.MonkeyPatch, args: list[str], env: dict[str, str], connected: bool, expected: type
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local import routing
    from hai_agents_local.holotab import install

    served: list[Any] = []
    monkeypatch.setattr(routing, "holotab_connected", lambda: connected)
    monkeypatch.setattr(install, "install_host", lambda **_: None)
    monkeypatch.setattr(cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: served.append(bridge_type))

    result = CliRunner().invoke(app, ["local", "browser", *args], env={"HAI_API_KEY": "hk-test", **env})

    assert result.exit_code == 0, result.output
    assert served == [expected]


def test_holo_local_browser_refuses_both_flags() -> None:
    result = CliRunner().invoke(app, ["local", "browser", "--holotab", "--selenium"], env={"HAI_API_KEY": "hk-test"})
    assert result.exit_code != 0
