from __future__ import annotations

import io
import threading

from rich.console import Console
from rich.text import Text

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
        f"{ui.DOT} Navigate news.ycombinator.com",
        f"  {ui.RESULT}  Hacker News · 6.3s",
        f"{ui.DOT} Back",
        f"  {ui.RESULT}  Error navigating back: Page.go_back: Timeout 10000ms exceeded. · 10.1s",
    ]
    assert feed.answer == "Dolly Parton's Imagination Library"
    assert (feed.steps, feed.cost) == (3, 0.004)


def test_each_step_says_what_changed_on_screen_and_a_blind_spell_once() -> None:
    page = {"url": "https://a.test/", "title": "A", "tabs": ["0"], "current_tab": "0"}
    page |= {"page_size": [1000, 3000], "viewport_size": [1000, 1000], "scroll_position": [0, 0]}
    screens = [
        page | {"scroll_position": [0, 1000]},
        page | {"scroll_position": [0, 1000], "tabs": ["0", "1"], "current_tab": "1"},
        page | {"scroll_position": [0, 1000], "tabs": ["0", "1"], "current_tab": "1"},
        {"url": "https://b.test/", "title": "B", "chunk_number": 1, "total_chunks": 3},
        {"url": "https://b.test/", "title": "B", "chunk_number": 2, "total_chunks": 3},
        None,
        None,
    ]
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=100, color_system=None))
    feed.handle(_agent("2026-10-26T12:00:00Z", kind="observation_event", metadata=page))
    for n, screen in enumerate(screens, start=1):
        feed.handle(_agent(f"2026-10-26T12:00:{n:02}Z", kind="policy_event", tool_reqs=[{"tool_name": "scroll"}]))
        feed.handle(_agent(f"2026-10-26T12:00:{n:02}.5Z", kind="tool_result", tool_req={"tool_name": "scroll"}))
        if screen is None:
            feed.handle(_agent(f"2026-10-26T12:00:{n:02}.9Z", kind="error_event", origin="failed_observation"))
        else:
            feed.handle(_agent(f"2026-10-26T12:00:{n:02}.9Z", kind="observation_event", metadata=screen))
    feed.close()

    outcomes = [line.strip() for line in buffer.getvalue().splitlines() if ui.RESULT in line]
    assert outcomes == [
        f"{ui.RESULT}  scrolled to 50% · 1.5s",
        f"{ui.RESULT}  tab 2 of 2 · 1.0s",
        f"{ui.RESULT}  1.0s",
        f"{ui.RESULT}  B · 1.0s",
        f"{ui.RESULT}  part 2 of 3 · 1.0s",
        f"{ui.RESULT}  couldn't capture the screen · 1.0s",
        f"{ui.RESULT}  0.6s",
    ]


def test_the_last_line_says_when_the_agent_could_not_finish() -> None:
    lines = []
    for answered in ("success", "blocked"):
        buffer = io.StringIO()
        ui.summary(Console(file=buffer, width=100, color_system=None), "idle", None, answered=answered)
        lines.append(buffer.getvalue().strip())

    assert lines == [f"{ui.SPARK} Done", f"{ui.DOT} Blocked"]


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
        f"{ui.DOT} Spawn Reader1: Read story 1",
        f"{ui.DOT} Spawn Reader2: Read story 2",
        f'{ui.DOT} Search "q1"',
        f'{ui.DOT} Search "q2"',
        f'{ui.DOT} Search "q3"',
        "  +3 more",
        f"{ui.DOT} Get weather Paris",
    ]


def test_spawn_lines_follow_each_subagent_to_its_report_and_hold_back_later_output(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=100, color_system="standard", theme=ui.THEME))
    names = ("Blog", "News", "Wiki")
    spawns = [{"tool_name": "spawn", "args": {"agent_id": name}, "id": f"call_{name}"} for name in names]
    feed.handle(_agent("2026-10-26T12:00:00Z", kind="policy_event", tool_reqs=spawns))
    for req in spawns:
        result = {"agent_id": req["args"]["agent_id"], "trajectory_id": f"sess_{req['args']['agent_id']}"}
        feed.handle(_agent("2026-10-26T12:00:01Z", kind="tool_result", tool_req=req, result=result))
    feed.handle(_agent("2026-10-26T12:00:02Z", kind="policy_event", tool_reqs=[{"tool_name": "sleep"}]))
    sleep = {"completed": ["Blog", "News"]}
    feed.handle(_agent("2026-10-26T12:00:09Z", kind="tool_result", tool_req={"tool_name": "sleep"}, result=sleep))
    feed.handle(_agent("2026-10-26T12:00:10Z", kind="policy_event", tool_reqs=[{"tool_name": "web_search"}]))
    assert "Spawn" not in buffer.getvalue()

    feed.agent_status("sess_Wiki", "running", steps=4)
    attachment = {"origin": "agent", "name": "report.csv", "size_bytes": 2048, "url": "https://x.test/r"}
    feed.handle({"type": "AttachmentEvent", "timestamp": "2026-10-26T12:00:11Z", "data": attachment})
    feed.handle(_agent("2026-10-26T12:00:11Z", kind="message_event", caller_id="Blog", content=["Read it. Details."]))
    feed.handle(_agent("2026-10-26T12:00:11Z", kind="message_event", caller_id="squad_failure:News", content=["Boom"]))
    feed.close()

    output = buffer.getvalue()
    lines = [line.rstrip() for line in Text.from_ansi(output).plain.splitlines() if line.strip()]
    assert lines[:6] == [
        f"{ui.DOT} Spawn Blog",
        f"  {ui.RESULT}  Read it.",
        f"{ui.DOT} Spawn News",
        f"  {ui.RESULT}  Boom",
        f"{ui.DOT} Spawn Wiki",
        f"  {ui.RESULT}  step 4",
    ]
    assert lines[6] == f"{ui.DOT} Shared report.csv · 2 KB"
    assert lines[7].startswith(f"{ui.DOT} Search") and not any("Wait" in line for line in lines)
    dots = [line for line in output.splitlines() if ui.DOT in line][:3]
    assert [line.startswith(f"\x1b[{code}m{ui.DOT}") for line, code in zip(dots, (32, 31, 2))] == [True] * 3
    assert "1 agent still running" in output


def test_follow_up_step_waits_for_its_last_call_and_counts_from_the_turn() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=100, color_system=None), steps=5, cost=0.01)
    searches = [{"tool_name": "web_search", "args": {"query": q}, "id": q} for q in ("a", "b")]
    feed.handle(_agent("2026-10-26T12:00:00Z", kind="message_event", caller_id="user", content=["more"]))
    feed.handle(_agent("2026-10-26T12:00:01Z", kind="policy_event", tool_reqs=searches))
    for second, req in ((4, searches[0]), (19, searches[1])):
        feed.handle(_agent(f"2026-10-26T12:00:{second:02}Z", kind="tool_result", tool_req=req, result="ok"))
    feed.handle({"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": 1, "total_cost": 0.012}}})
    feed.close()

    assert f"{ui.RESULT}  19.0s" in buffer.getvalue()
    assert (feed.turn_steps, feed.steps) == (1, 6)


def test_the_input_box_never_rides_back_up_during_a_run() -> None:
    out = Console(file=io.StringIO(), width=100, height=40, color_system=None)
    feed = ui.StepFeed(out, box=ui.InputBox())
    heights = []
    for event in EVENTS[:6]:
        feed.handle(event)
        heights.append(len(out.render_lines(feed._render_live(), out.options, pad=False)))

    assert heights == sorted(heights)


def test_a_redraw_never_waits_on_an_event_being_handled() -> None:
    feed = ui.StepFeed(Console(file=io.StringIO(), width=100, color_system=None))
    shown = feed._render_live()
    holding, release = threading.Event(), threading.Event()

    def handle() -> None:
        with feed._lock:
            holding.set()
            release.wait()

    worker = threading.Thread(target=handle, daemon=True)
    worker.start()
    holding.wait()
    try:
        assert feed._render_live() is shown
    finally:
        release.set()
        worker.join()
    assert feed._render_live() is not shown


def test_a_run_carried_into_the_next_turn_counts_its_steps_once() -> None:
    def metrics(steps: int) -> dict:
        return {"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": steps}}}

    feed = ui.StepFeed(Console(file=io.StringIO()), steps=5, run_steps=3)
    feed.handle(metrics(4))
    assert feed.steps == 6
    feed.handle(metrics(1))
    assert feed.steps == 7


def test_feed_surfaces_environment_and_tool_failures() -> None:
    buffer = io.StringIO()
    feed = ui.StepFeed(Console(file=buffer, width=200, color_system=None))
    run = {"tool_name": "run_command_desktop", "args": {"command": "open -a Calculator"}}

    feed.handle(
        _agent("2026-10-26T12:05:16Z", kind="error_event", origin="failed_observation", error="Screenshot timed out")
    )
    feed.handle(_agent("2026-10-26T12:05:17Z", kind="error_event", origin="no_tool_called", error="Call a tool"))
    feed.handle(_agent("2026-10-26T12:07:28Z", kind="policy_event", tool_reqs=[run]))
    feed.handle(
        _agent(
            "2026-10-26T12:08:29Z",
            kind="tool_result",
            tool_req=run,
            result="error:\nCOMMAND_TIMEOUT: run_command timed out",
        )
    )
    feed.close()

    output = buffer.getvalue()
    assert f"{ui.DOT} couldn't capture the screen" in output
    assert f"{ui.RESULT}  run_command timed out" in output
    assert "Call a tool" not in output


def test_welcome_drops_failing_and_slow_sources(monkeypatch) -> None:
    import time
    from types import SimpleNamespace

    from hai_agents_cli import welcome

    def broken():
        raise RuntimeError("503")

    def slow(**_):
        time.sleep(1)

    monkeypatch.setattr(welcome, "FETCH_TIMEOUT_S", 0.1)
    monkeypatch.setattr(welcome, "latest_version", broken)
    client = SimpleNamespace(quota=SimpleNamespace(get_token_quota=slow))

    started = time.monotonic()
    facts = welcome.gather(client, cloud=True)

    assert time.monotonic() - started < 0.5
    assert (facts.quota, facts.latest) == (None, None)
