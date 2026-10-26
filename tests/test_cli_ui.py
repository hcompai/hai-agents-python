from __future__ import annotations

import io

from rich.console import Console

from hai_agents_cli import ui


def _agent(ts: str, **data) -> dict:
    return {"type": "AgentEvent", "timestamp": ts, "data": data}


EVENTS = [
    _agent(
        "2026-10-25T20:35:31.4Z", kind="observation_event", metadata={"url": "https://www.bing.com/", "title": "Bing"}
    ),
    _agent(
        "2026-10-25T20:35:35.6Z",
        kind="policy_event",
        reasoning_content="I need to open Hacker News. Then read the top story.",
        content="",
        tool_reqs=[{"tool_name": "go_to_web", "args": {"url": "https://news.ycombinator.com"}}],
    ),
    _agent("2026-10-25T20:35:37.7Z", kind="tool_result", tool_req={"tool_name": "go_to_web"}, result=None),
    {
        "type": "MetricsUpdateEvent",
        "timestamp": "2026-10-25T20:35:37.8Z",
        "data": {"metrics": {"steps": 1, "total_cost": 0.0028}},
    },
    _agent("2026-10-25T20:35:38.0Z", kind="observation_event", metadata={"title": "Hacker News"}),
    _agent("2026-10-25T20:35:40.0Z", kind="policy_event", content="", tool_reqs=[{"tool_name": "go_back_web"}]),
    _agent(
        "2026-10-25T20:35:47.8Z",
        kind="error_event",
        origin="tool",
        error="Error navigating back: Page.go_back: Timeout 10000ms exceeded.\nCall log:\n  - waiting",
    ),
    _agent(
        "2026-10-25T20:35:50.3Z",
        kind="policy_event",
        content="",
        tool_reqs=[{"tool_name": "answer", "args": {"content": "Dolly Parton's Imagination Library"}}],
    ),
    _agent(
        "2026-10-25T20:35:50.4Z", kind="answer_event", answer="Dolly Parton's Imagination Library", outcome="success"
    ),
    {
        "type": "MetricsUpdateEvent",
        "timestamp": "2026-10-25T20:35:50.5Z",
        "data": {"metrics": {"steps": 3, "total_cost": 0.004}},
    },
]


def test_feed_renders_one_block_per_action_with_server_timings() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=100, color_system=None))

    for event in EVENTS:
        feed.handle(event)
    feed.close()

    lines = [line.rstrip() for line in buffer.getvalue().splitlines() if line.strip()]
    assert lines == [
        f"{ui.DOT} Navigate(news.ycombinator.com)",
        f"  {ui.RESULT}  Hacker News · 6.3s",
        f"{ui.DOT} Back",
        f"  {ui.RESULT}  Error navigating back: Page.go_back: Timeout 10000ms exceeded. · 10.1s",
    ]
    assert feed.answer == "Dolly Parton's Imagination Library"
    assert (feed.steps, feed.cost) == (3, 0.004)


def test_feed_names_every_parallel_call_and_unknown_tools() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=100, color_system=None))
    spawns = [
        {"tool_name": "spawn", "args": {"agent_id": f"Reader{n}", "task_summary": f"Read story {n}", "task": "..."}}
        for n in range(1, 3)
    ]
    searches = [{"tool_name": "web_search", "args": {"query": f"q{n}"}} for n in range(1, 7)]
    custom = [{"tool_name": "get_weather", "args": {"city": "Paris"}}]
    for second, reqs in enumerate((spawns, searches, custom)):
        feed.handle(_agent(f"2026-10-26T12:00:0{second}Z", kind="policy_event", tool_reqs=reqs))
    feed.close()

    lines = [line.rstrip() for line in buffer.getvalue().splitlines() if line.strip()]
    assert [line for line in lines if ui.RESULT not in line] == [
        f"{ui.DOT} Spawn(Reader1 · Read story 1)",
        "  Spawn(Reader2 · Read story 2)",
        f'{ui.DOT} Search("q1")',
        '  Search("q2")',
        '  Search("q3")',
        "  +3 more",
        f"{ui.DOT} Get weather(Paris)",
    ]


def test_feed_surfaces_environment_and_tool_failures() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=200, color_system=None))
    run = {"tool_name": "run_command_desktop", "args": {"command": "open -a Calculator"}}

    feed.handle(
        _agent("2026-10-26T12:05:16Z", kind="error_event", origin="failed_observation", error="Screenshot timed out")
    )
    feed.handle(_agent("2026-10-26T12:07:28Z", kind="policy_event", tool_reqs=[run]))
    feed.handle(
        _agent("2026-10-26T12:08:29Z", kind="tool_result", tool_req=run, result="error:\nrun_command timed out")
    )
    feed.close()

    output = buffer.getvalue()
    assert f"{ui.DOT} Screenshot timed out" in output
    assert f"{ui.RESULT}  run_command timed out" in output


def test_welcome_drops_failing_and_slow_sources(monkeypatch) -> None:
    import time
    from types import SimpleNamespace

    from hai_agents_cli import welcome

    def broken(**_):
        raise RuntimeError("503")

    def slow(**_):
        time.sleep(1)

    monkeypatch.setattr(welcome, "FETCH_TIMEOUT_S", 0.1)
    monkeypatch.setattr(welcome, "latest_version", lambda: "9.0.0")
    client = SimpleNamespace(
        quota=SimpleNamespace(get_token_quota=broken), sessions=SimpleNamespace(list_sessions=slow)
    )

    started = time.monotonic()
    facts = welcome.gather(client, cloud=True)

    assert time.monotonic() - started < 0.5
    assert (facts.quota, facts.recent, facts.latest) == (None, None, "9.0.0")
