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


def test_feed_renders_one_row_per_action_with_server_timings() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=80, color_system=None))

    for event in EVENTS:
        feed.handle(event)
    feed.close()

    navigate, back, reason = [line.rstrip() for line in buffer.getvalue().splitlines() if line.strip()]
    assert "✓" in navigate and "navigate" in navigate and "news.ycombinator.com" in navigate
    assert navigate.endswith("6.3s")
    assert "✗" in back and "back" in back and back.endswith("10.1s")
    assert "└ Error navigating back: Page.go_back" in reason and "Call log" not in reason
    assert feed.answer == "Dolly Parton's Imagination Library"
    assert (feed.steps, feed.cost) == (3, 0.004)
