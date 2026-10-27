"""Terminal look of the holo CLI, in the style of Claude Code."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.segment import Segment
from rich.style import Style
from rich.table import Column, Table
from rich.text import Text
from rich.theme import Theme

from . import tools

IRIS = "#9a5bec"

LOGO = (
    "   ########           ",
    " ############         ",
    "##############   ## ##",
    "##############   #####",
    "##############   ## ##",
    " ############         ",
    "   ########           ",
)

DOT = "●"
RESULT = "⎿"
SPARK = "✻"
PROMPT = "❯"
POINTER = "❯"
DONE = "✓"
FAILED = "✗"
ATTENTION = "!"
SEP = "·"

_OSC9_TERMINALS = frozenset({"iTerm.app", "WezTerm", "ghostty"})
_ACTIVITY_GLYPH = {
    "completed": (DONE, "ok"),
    "idle": (DONE, "ok"),
    "failed": (FAILED, "fail"),
    "timed_out": (FAILED, "fail"),
    "interrupted": (FAILED, "meta"),
}

RULE = "#4e4e4e"
_USER = Style(bgcolor="#303030")
_INK = Style(reverse=True)
_SPINNER = "·✢✳✶✻✽" if sys.platform == "darwin" else "·✢*✶✻✽"
_FRAMES = _SPINNER + _SPINNER[-2:0:-1]

THEME = Theme(
    {
        "accent": IRIS,
        "ok": "green",
        "fail": "red",
        "warn": "yellow",
        "meta": "dim",
        "key": "bold",
        "thought": "dim italic",
        "attention": "bold yellow",
    }
)

CheckState = Literal["ok", "warn", "fail"]
_CHECK_GLYPH: dict[CheckState, str] = {"ok": DONE, "warn": ATTENTION, "fail": FAILED}

_BLIND = "couldn't capture the screen"
_REPORT_PREFIXES = (("squad_failure:", "failed"), ("squad_no_answer:", "interrupted"))
_VERDICTS = {"partial": "partly done", "infeasible": "not possible", "blocked": "blocked"}
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,}:\s+")
MAX_CALLS = 4
_MAX_TAIL = 12
_MODEL_NUDGES = frozenset({"no_tool_called", "tool_skipped", "answer_validation", "prompt_too_large_recovery"})


def console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, theme=THEME, highlight=False)


def interactive(out: Console) -> bool:
    """A real TTY; `is_terminal` alone is also true under FORCE_COLOR, where live redraws garble CI logs."""
    isatty = getattr(out.file, "isatty", None)
    return out.is_terminal and not out.is_dumb_terminal and bool(isatty and isatty())


@dataclass
class Activity:
    status: str
    task: str
    age: str
    url: str | None = None


def welcome(out: Console, version: str, about: list[Text], tips: list[Text]) -> None:
    """The logo beside what answers, then how to steer it; the logo drops on narrow terminals."""
    lines = [Text.assemble(("holo", f"bold {IRIS}"), (f" v{version}", "meta")), *(_clip(line) for line in about)]
    body: RenderableType = Group(*lines)
    if out.width >= 60:
        body = Table.grid(Column(no_wrap=True), Column(vertical="middle"), padding=(0, 3, 0, 0))
        body.add_row(Group(*_logo()), Group(*lines))
    out.print()
    out.print(body)
    out.print()
    for tip in tips:
        out.print(_clip(tip))
    out.print()


def _logo() -> list[Text]:
    """Whole cells in the text color: block glyphs leave gaps between rows and columns in many fonts."""
    return [Text.assemble(*((" ", _INK if pixel == "#" else "") for pixel in row)) for row in LOGO]


def _clip(text: Text) -> Text:
    text.no_wrap, text.overflow = True, "ellipsis"
    return text


def header(out: Console, name: str, parts: list[str | None], link: str | None = None) -> None:
    title, *rest = [p for p in parts if p] or [""]
    lines: list[RenderableType] = [
        Text.assemble((f"{SPARK} ", "accent"), (name, "bold"), "  ", title),
        Text(""),
    ]
    if rest:
        lines.append(Text(f"  {f' {SEP} '.join(rest)}", style="meta"))
    if link:
        lines.append(Text(f"  {link}", style=f"dim link {link}"))
    out.print(Panel(Group(*lines), box=box.ROUNDED, border_style="accent", expand=False, padding=(0, 1)))
    out.print()


def user(out: Console, text: str) -> None:
    out.print(user_message(text))
    out.print()


def user_message(text: str) -> Table:
    grid = Table.grid(padding=(0, 1, 0, 0))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column()
    grid.add_row(Text(PROMPT, style="meta"), Text(text), style=_USER)
    return grid


@dataclass
class InputBox:
    """The message line pinned under a running turn, between two rules, with a hint line below."""

    text: str = ""
    placeholder: str = ""
    hint: str = ""
    hint_style: str = "meta"

    def lines(self) -> list[RenderableType]:
        line = Text.assemble((f"{PROMPT} ", "accent"), self.text, (" ", "reverse"))
        if not self.text:
            line.append(self.placeholder, style="meta")
        hint = Text(f"  {self.hint}", style=self.hint_style, no_wrap=True, overflow="ellipsis")
        return [Text(""), Rule(style=RULE), line, Rule(style=RULE), hint]


class _Lines:
    def __init__(self, lines: list[list[Segment]]) -> None:
        self.lines = lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for line in self.lines:
            yield from line
            yield Segment.line()


def _pinned(
    out: Console, body: list[RenderableType], bottom: list[RenderableType], floor: int
) -> tuple[RenderableType, int]:
    """Keep ``bottom`` on screen, and never let it ride back up from the tallest frame so far."""
    rendered = out.render_lines(Group(*body), out.options, pad=False)
    under = sum(len(out.render_lines(item, out.options, pad=False)) for item in bottom)
    rendered = rendered[max(0, len(rendered) - (out.size.height - under)) :]
    height = min(max(floor, len(rendered) + under), out.size.height)
    blanks: list[list[Segment]] = [[] for _ in range(height - len(rendered) - under)]
    return Group(_Lines(rendered + blanks), *bottom), height


def ok(out: Console, message: str, *, url: str | None = None) -> None:
    out.print(Text.assemble((f"{DONE} ", "ok"), message, *_link(url)), soft_wrap=url is not None)


def hint(out: Console, message: str, *, url: str | None = None) -> None:
    out.print(Text.assemble((f"  {message}", "meta"), *_link(url)), soft_wrap=url is not None)


def url(out: Console, address: str) -> None:
    out.print(Text.assemble("  ", *_link(address)[1:]), soft_wrap=True)


def _link(url: str | None) -> tuple[tuple[str, str], ...]:
    """An OSC 8 hyperlink that still shows the URL; printed soft-wrapped, so a terminal's own URL detection sees it whole."""
    return ((" ", ""), (url, Style(dim=True, underline=True, link=url))) if url else ()


def commands(out: Console, rows: list[tuple[str, str]]) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="accent", no_wrap=True)
    grid.add_column(style="meta")
    for name, description in rows:
        grid.add_row(name, description)
    out.print(grid)


def error(out: Console, message: str, *, fix: str | None = None) -> None:
    out.print(Text.assemble((f"{DOT} ", "fail"), message))
    if fix:
        out.print(_result(Text.assemble(("fix: ", "meta"), fix), wrap=True))


def check(out: Console, state: CheckState, name: str, detail: str, *, fix: str | None = None) -> None:
    out.print(Text.assemble((_CHECK_GLYPH[state], state), f" {name:<11} {detail}"))
    if fix:
        out.print(_result(Text.assemble(("fix: ", "meta"), fix), wrap=True))


def needs_you(out: Console, action: str, lines: list[str], options: list[str], *, selected: int = 0) -> None:
    body: list[RenderableType] = [
        Text("Needs you", style="attention"),
        Text(""),
        Text.from_markup(f"  {action}"),
        *(Text.from_markup(f"  {line}") for line in lines),
        Text(""),
        Text("Do you want to proceed?"),
    ]
    for i, option in enumerate(options):
        mark, style = (POINTER, "accent") if i == selected else (" ", "")
        body.append(Text(f"{mark} {i + 1}. {option}", style=style))
    out.print(Panel(Group(*body), box=box.ROUNDED, border_style="warn", expand=False, padding=(0, 1)))
    out.print()


def duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs}s"


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def money(usd: float | None) -> str | None:
    if usd is None:
        return None
    return f"${usd:.3f}" if usd < 1 else f"${usd:.2f}"


def _bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def _result(text: Text, *, wrap: bool = False) -> RenderableType:
    if not wrap:
        return Text.assemble((f"  {RESULT}  ", "meta"), text, no_wrap=True, overflow="ellipsis")
    grid = Table.grid()
    grid.add_column(width=5, no_wrap=True)
    grid.add_column()
    grid.add_row(Text(f"  {RESULT}  ", style="meta"), text)
    return grid


@dataclass
class _Step:
    n: int
    calls: list[tools.Label]
    busy: str
    thought: str | None
    started: float
    started_ts: float | None
    call_ids: list[Any] = field(default_factory=list)
    agents: dict[int, str] = field(default_factory=dict)
    waiting: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass
class _Done:
    step: _Step
    seconds: float
    error: str | None
    title: str | Text | None = None


@dataclass
class _Agent:
    name: str
    status: str = "running"
    steps: int | None = None
    report: str | None = None


@dataclass
class StepFeed:
    """Renders session events as one `⏺ Tool(args)` block per step, with a live spinner on a terminal.

    Step durations come from event timestamps when present, so replaying a finished session shows real timings.
    """

    out: Console
    max_steps: int | None = None
    steps: int = 0
    cost: float | None = None
    run_steps: int = 0
    handled: int = 0
    answer: Any = None
    starting: bool = False
    paused: bool = False
    stop_hint: str = "ctrl+c to stop"
    _current: _Step | None = None
    _done: _Done | None = None
    _seen: dict[str, Any] = field(default_factory=dict)
    _blind: bool = False
    _last_end: float = field(default_factory=time.monotonic)
    _last_end_ts: float | None = None
    _first_ts: float | None = None
    _latest_ts: float | None = None
    _started: float = field(default_factory=time.monotonic)
    box: InputBox | None = None
    _live: Live | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _frame: RenderableType = field(default_factory=Group)
    _floor: int = 0
    _agents: dict[str, _Agent] = field(default_factory=dict)
    _tail: list[_Done | RenderableType] = field(default_factory=list)
    _notes: list[RenderableType] = field(default_factory=list)
    _turn_from_steps: int = 0
    _turn_from_cost: float = 0.0
    _tally: _Tally = field(init=False)

    def __post_init__(self) -> None:
        self._turn_from_steps, self._turn_from_cost = self.steps, self.cost or 0.0
        self._tally = _Tally(base=self.steps - self.run_steps, run=self.run_steps, cost=self.cost)
        self._start_live()

    @property
    def turn_steps(self) -> int:
        return self.steps - self._turn_from_steps

    @property
    def turn_cost(self) -> float | None:
        return None if self.cost is None else max(0.0, self.cost - self._turn_from_cost)

    def handle(self, event: Any) -> None:
        with self._lock:
            self.handled += 1
            self._handle(event)

    def note(self, text: str) -> None:
        """Show a message typed mid-run after the step in flight, which is where the agent reads it."""
        with self._lock:
            self._notes += [user_message(text), Text("")]
            if self._current is None and self._done is None:
                self._flush()

    def running_agents(self) -> list[str]:
        """Session ids of the spawned subagents still running."""
        with self._lock:
            return [session_id for session_id, agent in self._agents.items() if agent.status == "running"]

    def agent_status(self, session_id: str, status: str, steps: int | None = None) -> None:
        with self._lock:
            agent = self._agents.get(session_id)
            if agent is None or agent.status != "running":
                return
            agent.steps = steps if isinstance(steps, int) else agent.steps
            if status in _ACTIVITY_GLYPH:
                agent.status = status
                self._settle()

    def _end_agents(self, names: Any) -> None:
        for agent in self._agents.values():
            if agent.status == "running" and agent.name in (names or ()):
                agent.status = "completed"
        self._settle()

    def _reported(self, caller: str, content: Any) -> None:
        """A subagent's answer reaches the parent as a message from it; failures carry a prefix."""
        status = "completed"
        for prefix, ended in _REPORT_PREFIXES:
            if caller.startswith(prefix):
                caller, status = caller.removeprefix(prefix), ended
        text = next((part for part in content or [] if isinstance(part, str)), None)
        for agent in self._agents.values():
            if agent.name == caller:
                agent.report = _first_sentence(text) or ""
                if agent.status == "running" or status != "completed":
                    agent.status = status
        self._settle()

    def _track_spawn(self, req: dict[str, Any], result: dict[str, Any]) -> None:
        session_id = str(result["trajectory_id"])
        self._agents[session_id] = _Agent(str(result.get("agent_id") or session_id))
        for step in (self._current, self._done.step if self._done else None):
            if step is None:
                continue
            if req.get("id") in step.call_ids:
                index: int | None = step.call_ids.index(req.get("id"))
            else:
                free = [i for i, (verb, _) in enumerate(step.calls) if verb == "spawn" and i not in step.agents]
                index = free[0] if free else None
            if index is not None:
                step.agents[index] = session_id
                return

    def _emit(self, item: _Done | RenderableType) -> None:
        """Print in order; a block whose subagents still run stays live, and holds back what follows it."""
        self._tail.append(item)
        self._settle()

    def _settle(self, *, force: bool = False) -> None:
        while self._tail and (force or len(self._tail) > _MAX_TAIL or not self._runs_agents(self._tail[0])):
            for line in self._render(self._tail.pop(0)):
                self.out.print(line)

    def _runs_agents(self, item: _Done | RenderableType) -> bool:
        """Its subagents have not all reported back; a report can trail the wait that saw them finish."""
        return isinstance(item, _Done) and any(self._agents[s].report is None for s in item.step.agents.values())

    def _render(self, item: _Done | RenderableType, *, live: bool = False) -> list[RenderableType]:
        return self._block(item, live=live) if isinstance(item, _Done) else [item]

    def _start_live(self) -> None:
        if self._live is None and interactive(self.out):
            self._live = Live(console=self.out, transient=True, refresh_per_second=12, get_renderable=self._render_live)
            self._live.start()

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _handle(self, event: Any) -> None:
        kind, data, ts = unwrap(event)
        if ts is not None:
            self._first_ts = self._first_ts or ts
            self._latest_ts = ts
            if self._last_end_ts is None and kind in ("observation_event", "message_event"):
                self._last_end_ts = ts
        if kind in ("observation_event", "policy_event", "error_event"):
            self.starting = False
        if kind == "metrics":
            self._tally.add(data)
            self.steps, self.cost = max(self.steps, self._tally.steps), self._tally.cost
            self.run_steps = self._tally.run
        elif kind == "observation_event":
            meta = data.get("metadata") or {}
            self._flush(_observed(data, self._seen))
            self._blind = False
            if meta:
                self._seen = meta
        elif kind == "policy_event":
            self._flush()
            self._start_step(data, ts)
        elif kind == "tool_result":
            req = data.get("tool_req") or {}
            result = data.get("result")
            if req.get("tool_name") == "spawn" and isinstance(result, dict) and result.get("trajectory_id"):
                self._track_spawn(req, result)
            if req.get("tool_name") == "sleep" and isinstance(result, dict):
                self._end_agents(result.get("completed"))
            if self._current is not None and req.get("tool_name") != "answer":
                self._call_done(req, ts, _tool_error(result))
        elif kind == "message_event":
            self._reported(str(data.get("caller_id") or ""), data.get("content"))
        elif kind == "error_event":
            message = _first_line(data.get("error")) or "error"
            origin = data.get("origin")
            req = data.get("tool_req") or {}
            if origin == "tool_skipped" and self._current is not None and req:
                self._call_done(req, ts, None)
            elif origin in _MODEL_NUDGES:
                pass
            elif origin in ("tool", "tool_validation") and self._current is not None:
                self._call_done(req, ts, message)
            elif origin == "failed_observation":
                self._restart_clock(ts)
                if not self._blind:
                    self._blind = True
                    if self._done is None:
                        self._emit(_bullet(Text(_BLIND, style="meta"), "meta"))
                    self._flush(Text(_BLIND, style="meta"))
            else:
                self._flush()
                self._emit(_bullet(Text(message, style="warn"), "warn"))
                self._emit(Text(""))
        elif kind == "AttachmentEvent" and data.get("origin") == "agent":
            self._flush()
            size = data.get("size_bytes")
            line = Text.assemble(("Shared ", "bold"), str(data.get("name") or "a file"))
            if isinstance(size, int):
                line.append(f" {SEP} {_bytes(size)}", style="meta")
            self._emit(_bullet(line, "accent"))
            self._emit(Text(""))
        elif kind == "answer_event":
            self.answer = data.get("answer")
        if self._live is not None:
            self._live.refresh()

    def close(self) -> None:
        with self._lock:
            if self._current is not None:
                self._finish(None, None)
            self._flush()
            self._settle(force=True)
            if running := len(self.running_agents()):
                self.out.print(Text(f"  {count(running, 'agent')} still running", style="meta"))
                self.out.print()
            self._stop_live()

    @property
    def elapsed(self) -> float:
        span = (self._latest_ts - self._first_ts) if self._first_ts and self._latest_ts else 0.0
        return max(span, time.monotonic() - self._started)

    def _start_step(self, data: dict[str, Any], ts: float | None) -> None:
        reqs = [r for r in data.get("tool_reqs") or [] if isinstance(r, dict) and r.get("tool_name") != "answer"]
        if not reqs:
            return
        if self._current is not None:
            self._finish(ts, None)
            self._flush()
        content = str(data.get("content") or "").strip()
        if content:
            self._emit(_bullet(Markdown(content)))
            self._emit(Text(""))
        calls = [tools.label(req) for req in reqs]
        thought = None if content else _first_sentence(data.get("reasoning_content"))
        set_title(self.out, f"holo {SEP} step {self.steps + 1 - self._turn_from_steps}")
        busy = tools.busy(reqs[0])
        ids = [req.get("id") for req in reqs]
        self._current = _Step(
            self.steps + 1, calls, busy, thought, self._last_end, self._last_end_ts, ids, waiting=list(ids)
        )

    def _call_done(self, req: dict[str, Any], ts: float | None, error: str | None) -> None:
        """Calls in a step run one after another; the step ends with its last result."""
        step = self._current
        assert step is not None
        step.error = step.error or error
        call_id = req.get("id")
        if call_id in step.waiting:
            step.waiting.remove(call_id)
        elif call_id is None and step.waiting:
            step.waiting.pop(0)
        if not step.waiting:
            self._finish(ts, None)

    def _finish(self, end_ts: float | None, error: str | None) -> None:
        step = self._current
        assert step is not None
        if end_ts is not None and step.started_ts is not None:
            seconds = max(0.0, end_ts - step.started_ts)
        else:
            seconds = time.monotonic() - step.started
        self._done = _Done(step, seconds, error or step.error)
        self._last_end = time.monotonic()
        self._last_end_ts = end_ts
        self.steps = max(self.steps, step.n)
        self._current = None

    def resumed(self) -> None:
        """Time spent paused is not the next step's."""
        with self._lock:
            self._restart_clock(None)

    def _restart_clock(self, ts: float | None) -> None:
        if self._current is None:
            self._last_end, self._last_end_ts = time.monotonic(), ts

    def _flush(self, title: str | Text | None = None) -> None:
        done, self._done = self._done, None
        if done is not None:
            done.title = title
            self._emit(done)
        notes, self._notes = self._notes, []
        for item in notes:
            self._emit(item)

    def _block(self, done: _Done, *, live: bool = False) -> list[RenderableType]:
        style = "fail" if done.error else "ok"
        if done.error:
            outcome = Text(done.error, style="fail")
        else:
            outcome = done.title.copy() if isinstance(done.title, Text) else Text(done.title or "")
        if outcome.plain:
            outcome.append(f" {SEP} ", style="meta")
        outcome.append(duration(done.seconds), style="meta")
        verbs = {verb for verb, _ in done.step.calls}
        if verbs == {"wait"} and not done.error:
            return []
        calls = self._calls(done.step, style, live=live)
        if len(done.step.agents) == len(done.step.calls) and not done.error and not done.title:
            return [*calls, Text("")]
        return [*calls, _result(outcome), Text("")]

    def _calls(self, step: _Step, dot: str, *, live: bool = False) -> list[RenderableType]:
        """One dotted line per call; a spawn's dot blinks while its subagent runs, with its progress, then its report."""
        shown = step.calls if len(step.calls) <= MAX_CALLS else step.calls[: MAX_CALLS - 1]
        lines: list[RenderableType] = []
        for i, (verb, target) in enumerate(shown):
            lines.append(Text.assemble((f"{DOT} ", self._dot(step, i, dot, live)), self._call(verb, target)))
            if i in step.agents and (progress := self._progress(self._agents[step.agents[i]])):
                lines.append(_result(progress))
        if hidden := len(step.calls) - len(shown):
            lines.append(Text(f"  +{hidden} more", style="meta"))
        return lines

    def _progress(self, agent: _Agent) -> Text | None:
        if agent.report:
            return Text(agent.report, style="fail" if agent.status == "failed" else "")
        if agent.status == "running":
            return Text(f"step {agent.steps}" if agent.steps else "starting…", style="meta")
        return None

    def _dot(self, step: _Step, index: int, default: str, live: bool) -> str:
        if index not in step.agents:
            return default
        status = self._agents[step.agents[index]].status
        if status == "running":
            return _blink() if live else "meta"
        return _ACTIVITY_GLYPH[status][1]

    def _call(self, verb: str, target: str) -> Text:
        name = verb.capitalize()
        call = Text(no_wrap=True, overflow="ellipsis")
        call.append(name, style="bold")
        if target:
            call.append(f" {target}")
        return call

    def _render_live(self) -> RenderableType:
        """Live's refresh thread holds its own lock here, and a print holding ours waits on it: never block."""
        if not self._lock.acquire(blocking=False):
            return self._frame
        try:
            self._frame = self._draw_live()
        finally:
            self._lock.release()
        return self._frame

    def _draw_live(self) -> RenderableType:
        now = time.monotonic()
        current, done = self._current, self._done
        lines: list[RenderableType] = []
        for item in self._tail:
            lines += self._render(item, live=True)
        if done is not None:
            lines += self._block(done, live=True)
        if current is not None:
            lines += self._calls(current, _blink(), live=True)
            if current.thought:
                lines.append(_result(Text(current.thought, style="thought")))
            lines.append(Text(""))
        lines += self._notes
        if self.paused:
            verb = "Paused"
        else:
            verb = current.busy if current else "Starting" if self.starting else "Thinking"
        n = current.n if current else self.steps + 1
        cost = self.turn_cost
        parts = [
            _clock(self.elapsed),
            f"step {n - self._turn_from_steps}/{self.max_steps}" if self.max_steps else None,
            money(cost) if cost and cost >= 0.001 else None,
            None if self.box else self.stop_hint,
        ]
        meta = f" {SEP} ".join(p for p in parts if p)
        frame = _FRAMES[int(now * 8) % len(_FRAMES)]
        lines.append(
            Text.assemble((f"{frame} {verb}…", "accent"), (f" ({meta})", "meta"), no_wrap=True, overflow="ellipsis")
        )
        if self.box is None:
            return Group(*lines)
        live, self._floor = _pinned(self.out, lines, self.box.lines(), self._floor)
        return live


def _observed(data: dict[str, Any], seen: dict[str, Any]) -> str | None:
    """What a step left on screen: a new page's title, else the one thing that moved."""
    meta = data.get("metadata") or {}
    if not meta:
        return "page unchanged" if "[page unchanged" in str(data.get("text") or "") else None
    title = meta.get("title") or tools.short_url(meta.get("url"))
    if not title:
        return None
    if title != (seen.get("title") or tools.short_url(seen.get("url"))) or meta.get("url") != seen.get("url"):
        return title
    tabs, tab = meta.get("tabs") or [], meta.get("current_tab")
    if len(tabs) > 1 and tab != seen.get("current_tab") and tab in tabs:
        return f"tab {tabs.index(tab) + 1} of {len(tabs)}"
    part, parts = meta.get("chunk_number"), meta.get("total_chunks")
    if isinstance(part, int) and isinstance(parts, int) and parts > 1 and part != seen.get("chunk_number"):
        return f"part {part} of {parts}"
    scrolled = _scrolled(meta)
    if scrolled is not None and meta.get("scroll_position") != seen.get("scroll_position"):
        return f"scrolled to {scrolled}%"
    return None


def _scrolled(meta: dict[str, Any]) -> int | None:
    try:
        top, page, view = meta["scroll_position"][1], meta["page_size"][1], meta["viewport_size"][1]
    except (KeyError, IndexError, TypeError):
        return None
    return max(0, min(100, round(100 * top / (page - view)))) if page > view else None


def _blink() -> str:
    return "accent" if int(time.monotonic() * 2) % 2 == 0 else "meta"


def print_answer(out: Console, answer: Any) -> None:
    if answer is None:
        return
    if not isinstance(answer, str):
        out.print(json.dumps(answer, indent=2, default=str), markup=False, highlight=False, soft_wrap=True)
    elif interactive(out):
        out.print(_bullet(Markdown(answer), "accent"))
    else:
        out.print(answer, markup=False, highlight=False, soft_wrap=True)


def _bullet(body: RenderableType, style: str = "") -> Table:
    grid = Table.grid()
    grid.add_column(width=2, no_wrap=True)
    grid.add_column()
    grid.add_row(Text(DOT, style=style), body)
    return grid


def set_title(out: Console, text: str) -> None:
    if interactive(out):
        out.set_window_title(text)


def outcome(status: str, answered: str | None = None) -> str:
    """``answered`` is the agent's own verdict on a finished task: success, partial, infeasible or blocked."""
    if status not in ("completed", "idle"):
        return status
    return _VERDICTS.get(answered or "", "done")


def notify(out: Console, message: str) -> None:
    """Desktop notification where the terminal supports OSC 9, else the bell (dock bounce or tab badge)."""
    if not interactive(out):
        return
    if os.environ.get("TERM_PROGRAM") in _OSC9_TERMINALS:
        out.file.write(f"\x1b]9;{message}\x07")
    else:
        out.file.write("\a")
    out.file.flush()


def summary(
    out: Console,
    status: str,
    feed: StepFeed | None,
    *,
    error_text: str | None = None,
    session_id: str | None = None,
    answered: str | None = None,
) -> None:
    parts: list[str | None] = []
    if feed is not None:
        parts = [count(feed.turn_steps, "step"), money(feed.turn_cost)]
    if session_id:
        parts.append(f"session {session_id}")
    meta = "".join(f" {SEP} {p}" for p in parts if p)
    took = duration(feed.elapsed) if feed is not None else None
    verdict = outcome(status, answered)
    set_title(out, f"holo {SEP} {f'{DONE} done' if verdict == 'done' else f'{FAILED} {verdict}'}")
    if verdict == "done":
        line = Text.assemble((f"{SPARK} ", "accent"), f"Done in {took}" if took else "Done", (meta, "meta"))
    elif status in ("completed", "idle"):
        line = Text.assemble(
            (f"{DOT} ", "warn"), verdict.capitalize(), (f" {SEP} {took}" if took else "", "meta"), (meta, "meta")
        )
    elif status == "failed":
        line = Text.assemble((f"{DOT} ", "fail"), f"Failed after {took}" if took else "Failed", (meta, "meta"))
    else:
        line = Text.assemble((f"{DOT} ", "warn"), status, (meta, "meta"))
    out.print(line)
    if error_text:
        out.print(_result(Text(error_text, style="fail"), wrap=True))


def usage(events: list[Any]) -> tuple[int, float | None]:
    """Session steps and cost from its metrics events."""
    tally = _Tally()
    for event in events:
        kind, data, _ = unwrap(event)
        if kind == "metrics":
            tally.add(data)
    return tally.steps, tally.cost


@dataclass
class _Tally:
    """Metrics restart their step count on every run (each follow-up), while cost spans the session."""

    base: int = 0
    run: int = 0
    cost: float | None = None

    @property
    def steps(self) -> int:
        return self.base + self.run

    def add(self, data: dict[str, Any]) -> None:
        metrics = data.get("metrics") or {}
        steps = metrics.get("steps")
        if isinstance(steps, int):
            if steps < self.run:
                self.base += self.run
            self.run = steps
        self.cost = metrics.get("total_cost", self.cost)


def unwrap(event: Any) -> tuple[str, dict[str, Any], float | None]:
    if not isinstance(event, dict):
        from hai_agents_common.jsonable import to_jsonable

        event = to_jsonable(event)
    ts = _timestamp(event.get("timestamp"))
    data = event.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    if event.get("type") == "MetricsUpdateEvent":
        return "metrics", data, ts
    if event.get("type") == "AgentEvent":
        return str(data.get("kind") or ""), data, ts
    return str(event.get("type") or ""), data, ts


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _first_sentence(text: Any) -> str | None:
    text = " ".join(str(text or "").split())
    if not text:
        return None
    for stop in (". ", "! ", "? "):
        cut = text.find(stop)
        if 0 < cut < 160:
            return text[: cut + 1]
    return text[:160]


def _tool_error(result: Any) -> str | None:
    if isinstance(result, dict):
        return _first_line(result.get("error"))
    if isinstance(result, str) and result.startswith("error:\n"):
        return _first_line(result.removeprefix("error:\n")) or "failed"
    return None


def _first_line(text: Any) -> str | None:
    """The first line, without a leading `ERROR_CODE: ` the tool adds for the model."""
    lines = str(text).strip().splitlines() if text else []
    if not lines:
        return None
    return _ERROR_CODE.sub("", lines[0]) or lines[0]
