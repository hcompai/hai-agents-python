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
from urllib.parse import urlparse

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Column, Table
from rich.text import Text
from rich.theme import Theme

IRIS = "#9a5bec"
SKY = "#5b9cec"

LOGO = (
    "   ▄▄█████▄▄           ",
    " ▄███████████▄         ",
    "▄█████████████▄   ██ ██",
    "███████████████   █████",
    "▀█████████████▀   ██ ██",
    " ▀███████████▀         ",
    "   ▀▀█████▀▀           ",
)

DOT = "●"
RESULT = "⎿"
SPARK = "✻"
PROMPT = ">"
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
    }
)

CheckState = Literal["ok", "warn", "fail"]
_CHECK_GLYPH: dict[CheckState, str] = {"ok": DONE, "warn": ATTENTION, "fail": FAILED}

_TOOL_SUFFIX = re.compile(r"(_localizer|_vectorizer)?_(web|desktop)$")
_VERBS = {
    "go_to": "navigate",
    "goto": "navigate",
    "go_back": "back",
    "double_click": "click",
    "right_click": "click",
    "write": "type",
    "write_at": "type",
    "press_keys": "press",
    "hotkey": "press",
    "hold_and_tap_key": "press",
    "move_mouse": "hover",
    "move_to": "hover",
    "ctrl_f": "find",
    "run_command": "run",
    "crawl": "read",
    "read_file": "read",
    "write_file": "write",
    "upload_file": "upload",
    "open_app": "open",
}
_GERUNDS = {"back": "Going back", "drag": "Dragging", "run": "Running", "hover": "Hovering"}
_TARGET_KEYS = ("url", "app", "text", "content", "query", "element", "target", "description", "selector", "key", "keys")


def console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, theme=THEME, highlight=False)


def interactive(out: Console) -> bool:
    """A real TTY; `is_terminal` alone is also true under FORCE_COLOR, where live redraws garble CI logs."""
    isatty = getattr(out.file, "isatty", None)
    return out.is_terminal and bool(isatty and isatty())


@dataclass
class Activity:
    status: str
    task: str
    age: str
    url: str | None = None


def welcome(
    out: Console, version: str, about: list[str], tips: list[Text], recent: list[Activity] | None = None
) -> None:
    """Logo and identity on the left, tips and recent activity on the right; stacks when the terminal is narrow."""
    wide = out.width >= 80
    rows = [*_logo(), Text(" ")] if wide else []
    rows += [_clip(Text(line, style="meta")) for line in about]
    left = Group(*(Align.center(row) for row in rows))
    right: list[RenderableType] = [Text("Tips", style=f"bold {IRIS}"), *(_clip(tip) for tip in tips)]
    if recent is not None:
        right += [
            Rule(style=f"dim {IRIS}"),
            Text("Recent activity", style=f"bold {IRIS}"),
            *([_activity(a) for a in recent] or [Text("No recent activity", style="meta")]),
        ]
    if wide:
        body: RenderableType = Table(
            Column(ratio=2),
            Column(ratio=3),
            box=box.MINIMAL,
            show_header=False,
            show_edge=False,
            expand=True,
            border_style=f"dim {IRIS}",
            padding=(0, 1),
        )
        body.add_row(left, Group(*right))
    else:
        body = Group(left, Rule(style=f"dim {IRIS}"), *right)
    title = Text.assemble(("holo", f"bold {IRIS}"), (f" v{version}", "meta"))
    out.print(Panel(body, title=title, title_align="left", box=box.ROUNDED, border_style="accent", padding=(0, 1)))
    out.print()


def _logo() -> list[Text]:
    width = len(LOGO[0])
    gradient = [_blend(IRIS, SKY, i / (width - 1)) for i in range(width)]
    lines = []
    for row in LOGO:
        line = Text()
        for char, color in zip(row, gradient, strict=True):
            line.append(char, style=color)
        lines.append(line)
    return lines


def _clip(text: Text) -> Text:
    text.no_wrap, text.overflow = True, "ellipsis"
    return text


def _activity(item: Activity) -> Table:
    glyph, style = _ACTIVITY_GLYPH.get(item.status, (DOT, "accent"))
    row = Table.grid(expand=True, padding=(0, 1, 0, 0))
    row.add_column(no_wrap=True)
    row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    row.add_column(no_wrap=True, justify="right")
    task_style = f"link {item.url}" if item.url else ""
    row.add_row(Text(glyph, style=style), Text(item.task, style=task_style), Text(item.age, style="meta"))
    return row


def _blend(start: str, end: str, t: float) -> str:
    a, b = (tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in (start, end))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=True))


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
    grid = Table.grid()
    grid.add_column(width=2, no_wrap=True)
    grid.add_column()
    grid.add_row(Text(PROMPT, style="meta"), Text(text, style="meta"))
    out.print(grid)
    out.print()


def prompt_text() -> Text:
    return Text(f"{PROMPT} ", style="accent")


def ok(out: Console, message: str, *, url: str | None = None) -> None:
    out.print(Text.assemble((f"{DONE} ", "ok"), message, *_link(url)))


def hint(out: Console, message: str, *, url: str | None = None) -> None:
    out.print(Text.assemble((f"  {message}", "meta"), *_link(url)))


def _link(url: str | None) -> tuple[tuple[str, str], ...]:
    """An OSC 8 hyperlink that still shows the URL, for terminals that only auto-detect plain URLs."""
    return ((" ", ""), (url, f"underline link {url}")) if url else ()


def paused(out: Console) -> None:
    out.print()
    out.print(
        Text.assemble((f"{DOT} ", "warn"), "Paused", (" · say what to do instead, or press enter to resume", "meta"))
    )


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
    out.print(Text.assemble((_CHECK_GLYPH[state], state), f" {name:<10} {detail}"))
    if fix:
        out.print(_result(Text.assemble(("fix: ", "meta"), fix), wrap=True))


def needs_you(out: Console, action: str, lines: list[str], options: list[str], *, selected: int = 0) -> None:
    body: list[RenderableType] = [
        Text("Needs you", style="bold warn"),
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
    verb: str
    target: str
    thought: str | None
    started: float
    started_ts: float | None


@dataclass
class _Done:
    step: _Step
    seconds: float
    error: str | None


@dataclass
class StepFeed:
    """Renders session events as one `⏺ Tool(args)` block per step, with a live spinner on a terminal.

    Step durations come from event timestamps when present, so replaying a finished session shows real timings.
    """

    out: Console
    max_steps: int | None = None
    steps: int = 0
    cost: float | None = None
    answer: Any = None
    page: str | None = None
    stop_hint: str = "ctrl+c to stop"
    _current: _Step | None = None
    _done: _Done | None = None
    _last_end: float = field(default_factory=time.monotonic)
    _last_end_ts: float | None = None
    _first_ts: float | None = None
    _latest_ts: float | None = None
    _started: float = field(default_factory=time.monotonic)
    _live: Live | None = None
    _held: list[Any] | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _turn_from_steps: int = 0
    _turn_from_cost: float = 0.0

    def __post_init__(self) -> None:
        self._turn_from_steps, self._turn_from_cost = self.steps, self.cost or 0.0
        self._start_live()

    @property
    def turn_steps(self) -> int:
        return self.steps - self._turn_from_steps

    @property
    def turn_cost(self) -> float | None:
        return None if self.cost is None else max(0.0, self.cost - self._turn_from_cost)

    def handle(self, event: Any) -> None:
        with self._lock:
            if self._held is not None:
                self._held.append(event)
            else:
                self._handle(event)

    def hold(self) -> None:
        """Queue events and clear the live area, so a prompt can take the terminal."""
        with self._lock:
            self._held = []
            self._stop_live()

    def release(self) -> None:
        with self._lock:
            held, self._held = self._held or [], None
            self._start_live()
            for event in held:
                self._handle(event)

    def _start_live(self) -> None:
        if self._live is None and interactive(self.out):
            self._live = Live(console=self.out, transient=True, refresh_per_second=12, get_renderable=self._render_live)
            self._live.start()

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _handle(self, event: Any) -> None:
        kind, data, ts = _unwrap(event)
        if ts is not None:
            self._first_ts = self._first_ts or ts
            self._latest_ts = ts
            if self._last_end_ts is None and kind in ("observation_event", "message_event"):
                self._last_end_ts = ts
        if kind == "metrics":
            metrics = data.get("metrics") or {}
            self.steps = int(metrics.get("steps") or self.steps)
            self.cost = metrics.get("total_cost", self.cost)
        elif kind == "observation_event":
            meta = data.get("metadata") or {}
            title = meta.get("title") or _short_url(meta.get("url"))
            self._flush(title if title != self.page else None)
            self.page = title or self.page
        elif kind == "policy_event":
            self._flush()
            self._start_step(data, ts)
        elif kind == "tool_result":
            req = data.get("tool_req") or {}
            result = data.get("result")
            if self._current is not None and req.get("tool_name") != "answer":
                self._finish(ts, _tool_error(result))
        elif kind == "error_event":
            message = _first_line(data.get("error")) or "error"
            if data.get("origin") == "tool" and self._current is not None:
                self._finish(ts, message)
            else:
                self._flush()
                self.out.print(_bullet(Text(message, style="warn"), "warn"))
                self.out.print()
        elif kind == "answer_event":
            self.answer = data.get("answer")
        if self._live is not None:
            self._live.refresh()

    def close(self) -> None:
        with self._lock:
            for event in self._held or []:
                self._handle(event)
            self._held = None
            if self._current is not None:
                self._finish(None, None)
            self._flush()
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
        content = " ".join(str(data.get("content") or "").split())
        if content:
            self.out.print(_bullet(Text(content)))
            self.out.print()
        verb, target = _describe(reqs[0])
        if len(reqs) > 1:
            target = f"{target}  +{len(reqs) - 1}"
        thought = _first_sentence(data.get("reasoning_content"))
        set_title(self.out, f"holo {SEP} step {self.steps + 1 - self._turn_from_steps}")
        self._current = _Step(self.steps + 1, verb, target, thought, self._last_end, self._last_end_ts)

    def _finish(self, end_ts: float | None, error: str | None) -> None:
        step = self._current
        assert step is not None
        if end_ts is not None and step.started_ts is not None:
            seconds = max(0.0, end_ts - step.started_ts)
        else:
            seconds = time.monotonic() - step.started
        self._done = _Done(step, seconds, error)
        self._last_end = time.monotonic()
        self._last_end_ts = end_ts
        self.steps = max(self.steps, step.n)
        self._current = None

    def _flush(self, title: str | None = None) -> None:
        done, self._done = self._done, None
        if done is None:
            return
        for line in self._block(done, title):
            self.out.print(line)

    def _block(self, done: _Done, title: str | None) -> list[RenderableType]:
        style = "fail" if done.error else "ok"
        outcome = Text(done.error, style="fail") if done.error else Text(title or "")
        if outcome.plain:
            outcome.append(f" {SEP} ", style="meta")
        outcome.append(duration(done.seconds), style="meta")
        return [Text.assemble((f"{DOT} ", style), self._call(done.step)), _result(outcome), Text("")]

    def _call(self, step: _Step) -> Text:
        name = step.verb.capitalize()
        call = Text(no_wrap=True, overflow="ellipsis")
        call.append(name, style="bold")
        if step.target:
            room = max(10, self.out.width - len(name) - 6)
            target = step.target if len(step.target) <= room else step.target[: room - 1] + "…"
            call.append(f"({target})")
        return call

    def _render_live(self) -> RenderableType:
        now = time.monotonic()
        current, done = self._current, self._done
        lines: list[RenderableType] = []
        if done is not None:
            lines += self._block(done, None)
        if current is not None:
            dot = "accent" if int(now * 2) % 2 == 0 else "meta"
            lines.append(Text.assemble((f"{DOT} ", dot), self._call(current)))
            lines.append(_result(Text(current.thought or "Running…", style="meta italic")))
            lines.append(Text(""))
        verb = _gerund(current.verb) if current else "Thinking"
        n = current.n if current else self.steps + 1
        parts = [
            _clock(self.elapsed),
            f"step {n}/{self.max_steps}" if self.max_steps else f"step {n - self._turn_from_steps}",
            money(self.turn_cost),
            self.stop_hint,
        ]
        meta = f" {SEP} ".join(p for p in parts if p)
        frame = _FRAMES[int(now * 8) % len(_FRAMES)]
        lines.append(
            Text.assemble((f"{frame} {verb}…", "accent"), (f" ({meta})", "meta"), no_wrap=True, overflow="ellipsis")
        )
        return Group(*lines)


def print_answer(out: Console, answer: Any) -> None:
    if answer is None:
        return
    if not isinstance(answer, str):
        out.print(json.dumps(answer, indent=2, default=str), markup=False, highlight=False, soft_wrap=True)
    elif interactive(out):
        out.print()
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
) -> None:
    parts: list[str | None] = []
    if feed is not None:
        parts = [count(feed.turn_steps, "step"), money(feed.turn_cost)]
    if session_id:
        parts.append(f"session {session_id}")
    meta = "".join(f" {SEP} {p}" for p in parts if p)
    took = duration(feed.elapsed) if feed is not None else None
    set_title(out, f"holo {SEP} {f'{DONE} done' if status in ('completed', 'idle') else f'{FAILED} {status}'}")
    if status in ("completed", "idle"):
        line = Text.assemble((f"{SPARK} ", "accent"), f"Done in {took}" if took else "Done", (meta, "meta"))
    elif status == "failed":
        line = Text.assemble((f"{DOT} ", "fail"), f"Failed after {took}" if took else "Failed", (meta, "meta"))
    else:
        line = Text.assemble((f"{DOT} ", "warn"), status, (meta, "meta"))
    out.print(line)
    if error_text:
        out.print(_result(Text(error_text, style="fail"), wrap=True))


def _gerund(verb: str) -> str:
    if verb in _GERUNDS:
        return _GERUNDS[verb]
    stem = verb[:-1] if verb.endswith("e") and not verb.endswith("ee") else verb
    return f"{stem}ing".capitalize()


def _unwrap(event: Any) -> tuple[str, dict[str, Any], float | None]:
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


def _describe(req: dict[str, Any]) -> tuple[str, str]:
    name = str(req.get("tool_name") or "tool")
    args = req.get("args") or {}
    base = _TOOL_SUFFIX.sub("", name)
    verb = _VERBS.get(base) or base.split("_")[0]
    for key in _TARGET_KEYS:
        value = args.get(key)
        if value:
            if key == "url":
                return verb, _short_url(str(value)) or str(value)
            text = " ".join(str(value).split())
            return verb, f'"{text}"' if key in ("text", "content", "query") else text
    if "x" in args and "y" in args:
        return verb, f"{args['x']}, {args['y']}"
    if "coordinates" in args:
        return verb, str(args["coordinates"])
    return verb, ""


def _short_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else url


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
    lines = str(text).strip().splitlines() if text else []
    return lines[0] if lines else None
