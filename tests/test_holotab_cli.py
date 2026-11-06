from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("typer")
pytest.importorskip("hai_drivers.web.interface")

from typer.testing import CliRunner  # noqa: E402

from hai_agents_cli.app import app  # noqa: E402
from hai_agents_local import HoloTabBrowserBridge, SeleniumBrowserBridge  # noqa: E402

SESSION_ID = "0b7c8f3e-5d0a-4f43-9a0e-1c1b6f9d2a11"


def test_holo_local_browser_holotab_waits_for_holotab_and_serves_the_holotab_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import connect

    calls: list[Any] = []
    monkeypatch.setattr(connect, "require_holotab", lambda *args: calls.append(("require", *args)))
    monkeypatch.setattr(
        cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.extend([bridge_type, opts])
    )

    result = CliRunner().invoke(app, ["local", "browser", "--holotab"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert calls == [
        ("require", "hk-test", "Holo CLI"),
        HoloTabBrowserBridge,
        {"client": "Holo CLI", "label": None, "stop_on_refusal": True},
    ]


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


def test_holo_local_browser_label_reaches_the_holotab_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import connect

    calls: list[Any] = []
    monkeypatch.setattr(connect, "require_holotab", lambda *_: None)
    monkeypatch.setattr(cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: calls.append(opts))

    result = CliRunner().invoke(
        app, ["local", "browser", "--holotab", "--label", "My group"], env={"HAI_API_KEY": "hk-test"}
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"client": "Holo CLI", "label": "My group", "stop_on_refusal": True}]


@pytest.mark.parametrize(
    ("args", "env", "expected"),
    [
        ([], {}, SeleniumBrowserBridge),
        (["--holotab"], {}, HoloTabBrowserBridge),
    ],
)
def test_holo_local_browser_uses_holotab_only_with_the_flag(
    monkeypatch: pytest.MonkeyPatch, args: list[str], env: dict[str, str], expected: type
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import connect

    served: list[Any] = []
    required: list[int] = []
    monkeypatch.setattr(connect, "require_holotab", lambda *_: required.append(1))
    monkeypatch.setattr(cli, "_run_bridge", lambda state, bridge_type, session_id, **opts: served.append(bridge_type))

    result = CliRunner().invoke(app, ["local", "browser", *args], env={"HAI_API_KEY": "hk-test", **env})

    assert result.exit_code == 0, result.output
    assert served == [expected]
    assert bool(required) is (expected is HoloTabBrowserBridge)


@pytest.mark.parametrize(
    ("args", "env", "message"),
    [
        (["--label", "My group"], {}, "--label names HoloTab's tab group"),
    ],
)
def test_holo_local_browser_refuses_what_it_cannot_honour(
    monkeypatch: pytest.MonkeyPatch, args: list[str], env: dict[str, str], message: str
) -> None:
    import hai_agents_cli.app as cli

    monkeypatch.setattr(cli, "_run_bridge", lambda *_, **__: pytest.fail("a bridge was started"))
    result = CliRunner().invoke(app, ["local", "browser", *args], env={"HAI_API_KEY": "hk-test", **env})
    assert result.exit_code != 0
    assert message in " ".join(result.output.split())


def test_holo_local_browser_says_why_when_the_holotab_it_was_asked_for_cannot_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import connect

    def unreachable(*_: Any) -> None:
        raise RuntimeError("Chrome is not connected through HoloTab.")

    monkeypatch.setattr(connect, "require_holotab", unreachable)
    monkeypatch.setattr(cli, "_run_bridge", lambda *_, **__: pytest.fail("a bridge was started"))
    result = CliRunner().invoke(app, ["local", "browser", "--holotab"], env={"HAI_API_KEY": "hk-test"})
    assert result.exit_code != 0
    assert "Chrome is not connected through HoloTab." in result.output


@pytest.mark.parametrize(("args", "host"), [([], "user_device"), (["--holotab"], "holotab")])
def test_holo_local_browser_prints_an_environment_with_the_host_it_serves(
    monkeypatch: pytest.MonkeyPatch, args: list[str], host: str
) -> None:
    import hai_agents_cli.app as cli
    from hai_agents_local.holotab import connect

    async def serve(bridge: Any) -> None:
        bridge.ready.set()

    monkeypatch.setattr(connect, "require_holotab", lambda *_: None)
    monkeypatch.setattr(HoloTabBrowserBridge, "preflight", lambda self: None)
    monkeypatch.setattr(SeleniumBrowserBridge, "preflight", lambda self: None)
    monkeypatch.setattr(cli, "_serve_bridge", serve)

    result = CliRunner().invoke(
        app, ["local", "browser", *args, "--session-id", SESSION_ID], env={"HAI_API_KEY": "hk-test"}
    )

    assert result.exit_code == 0, result.output
    assert f'{{"kind": "web", "host": "{host}", "session_id": "{SESSION_ID}"}}' in " ".join(result.output.split())
