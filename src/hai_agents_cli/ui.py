"""Terminal look shared by the hai and holo CLIs: one accent, one glyph set, lines instead of boxes."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.text import Text
from rich.theme import Theme

IRIS = "#7114eb"

RUNNING = "●"
DONE = "✓"
FAILED = "✗"
ATTENTION = "!"
PROMPT = "›"
DETAIL = "└"
SEP = "·"
BAR = "┃"

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
_TARGET_KEYS = ("url", "app", "text", "content", "query", "element", "target", "description", "selector", "key", "keys")
_VERB_WIDTH = 10


def console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, theme=THEME, highlight=False)


def interactive(out: Console) -> bool:
    """A real TTY; `is_terminal` alone is also true under FORCE_COLOR, where live redraws garble CI logs."""
    isatty = getattr(out.file, "isatty", None)
    return out.is_terminal and bool(isatty and isatty())


def error(out: Console, message: str, *, fix: str | None = None) -> None:
    out.print(f"[fail]{FAILED}[/fail] {escape(message)}")
    _fix(out, fix)


def check(out: Console, state: CheckState, name: str, detail: str, *, fix: str | None = None) -> None:
    out.print(f"[{state}]{_CHECK_GLYPH[state]}[/{state}] {name:<10} {escape(detail)}")
    _fix(out, fix)


def _fix(out: Console, fix: str | None) -> None:
    if fix:
        out.print(Padding(Text.assemble(("fix: ", "meta"), fix), (0, 0, 0, 2), expand=False))


def needs_you(out: Console, title: str, lines: list[str], keys: list[tuple[str, str]]) -> None:
    bar = f"  [warn]{BAR}[/warn] "
    out.print(f"{bar}[warn]needs you[/warn]  {escape(title)}")
    for line in lines:
        out.print(f"{bar}{line}")
    out.print(bar.rstrip())
    out.print(bar + "   ".join(f"[key]{k}[/key] {escape(label)}" for k, label in keys))


def header(out: Console, name: str, parts: list[str], link: str | None = None) -> None:
    meta = f" {SEP} ".join(escape(p) for p in parts if p)
    out.print(f"[accent]{RUNNING}[/accent] [key]{escape(name)}[/key]  [meta]{meta}[/meta]")
    if link:
        out.print(f"  [link={link}]{escape(link)}[/link]", soft_wrap=True)
    out.print()


def duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def money(usd: float | None) -> str | None:
    if usd is None:
        return None
    return f"${usd:.3f}" if usd < 1 else f"${usd:.2f}"


@dataclass
class _Step:
    n: int
    verb: str
    target: str
    detail: str | None
    started: float
    started_ts: float | None


@dataclass
class StepFeed:
    """Renders session events as one row per step, with a live row and status line on a terminal.

    Step durations come from event timestamps when present, so replaying a finished session shows real timings.
    """

    out: Console
    max_steps: int | None = None
    steps: int = 0
    cost: float | None = None
    answer: Any = None
    page: str | None = None
    _current: _Step | None = None
    _last_end: float = field(default_factory=time.monotonic)
    _last_end_ts: float | None = None
    _first_ts: float | None = None
    _latest_ts: float | None = None
    _started: float = field(default_factory=time.monotonic)
    _live: Live | None = None

    def __post_init__(self) -> None:
        if interactive(self.out):
            self._live = Live(self._render_live(), console=self.out, transient=True, refresh_per_second=8)
            self._live.start()

    def handle(self, event: Any) -> None:
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
            self.page = meta.get("title") or _short_url(meta.get("url")) or self.page
        elif kind == "policy_event":
            self._start_step(data, ts)
        elif kind == "tool_result":
            self._finish_step(data, ts)
        elif kind == "error_event" and data.get("origin") == "tool" and self._current is not None:
            self._close(FAILED, ts, note=_first_line(data.get("error")))
        elif kind == "answer_event":
            self.answer = data.get("answer")
        self._refresh()

    def close(self) -> None:
        if self._current is not None:
            self._close(DONE, None)
        if self._live is not None:
            self._live.stop()
            self._live = None

    @property
    def elapsed(self) -> float:
        span = (self._latest_ts - self._first_ts) if self._first_ts and self._latest_ts else 0.0
        return max(span, time.monotonic() - self._started)

    def _start_step(self, data: dict[str, Any], ts: float | None) -> None:
        reqs = [r for r in data.get("tool_reqs") or [] if isinstance(r, dict)]
        reqs = [r for r in reqs if r.get("tool_name") != "answer"]
        if not reqs:
            return
        if self._current is not None:
            self._close(DONE, ts)
        verb, target = _describe(reqs[0])
        if len(reqs) > 1:
            target = f"{target}  +{len(reqs) - 1}"
        self._current = _Step(self.steps + 1, verb, target, _first_sentence(data), self._last_end, self._last_end_ts)

    def _finish_step(self, data: dict[str, Any], ts: float | None) -> None:
        if self._current is None or (data.get("tool_req") or {}).get("tool_name") == "answer":
            return
        result = data.get("result")
        error = result.get("error") if isinstance(result, dict) else None
        self._close(FAILED if error else DONE, ts, note=_first_line(error))

    def _close(self, glyph: str, end_ts: float | None, *, note: str | None = None) -> None:
        step = self._current
        assert step is not None
        if end_ts is not None and step.started_ts is not None:
            seconds = max(0.0, end_ts - step.started_ts)
        else:
            seconds = time.monotonic() - step.started
        self.out.print(self._row(step, glyph, "fail" if glyph == FAILED else "ok", duration(seconds)))
        if note:
            self.out.print(Text(f"         {DETAIL} {note}", style="fail", overflow="ellipsis", no_wrap=True))
        self._last_end = time.monotonic()
        self._last_end_ts = end_ts
        self.steps = max(self.steps, step.n)
        self._current = None

    def _row(self, step: _Step, glyph: str, style: str, right: str) -> Text:
        width = max(40, self.out.width)
        target_width = max(10, width - 9 - _VERB_WIDTH - len(right) - 4)
        target = step.target if len(step.target) <= target_width else step.target[: target_width - 1] + "…"
        row = Text("  ")
        row.append(glyph, style=style)
        row.append(f" {step.n:>3}  ", style="meta")
        row.append(f"{step.verb:<{_VERB_WIDTH}}")
        row.append(f"{target:<{target_width}}")
        row.append(f" {right}", style="meta")
        return row

    def _render_live(self) -> Group:
        now = time.monotonic()
        lines: list[Any] = []
        if self._current is not None:
            lines.append(self._row(self._current, RUNNING, "accent", duration(now - self._current.started)))
            if self._current.detail:
                lines.append(Text(f"         {DETAIL} {self._current.detail}", style="meta", overflow="ellipsis"))
        else:
            thinking = _Step(self.steps + 1, "thinking", "", None, self._last_end, None)
            lines.append(self._row(thinking, RUNNING, "accent", duration(now - self._last_end)))
        lines.append(Text(""))
        lines.append(Text(self._status(), style="meta", overflow="ellipsis", no_wrap=True))
        return Group(*lines)

    def _status(self) -> str:
        n = self._current.n if self._current else self.steps + 1
        step = f"step {n}/{self.max_steps}" if self.max_steps else f"step {n}"
        page = self.page if not self.page or len(self.page) <= 32 else self.page[:31] + "…"
        parts = [step, duration(self.elapsed), money(self.cost), page, "ctrl+c cancel"]
        return f" {SEP} ".join(p for p in parts if p)

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render_live(), refresh=True)


def print_answer(out: Console, answer: Any) -> None:
    if answer is None:
        return
    if isinstance(answer, str):
        if interactive(out):
            out.print(Markdown(answer))
        else:
            out.print(answer, markup=False, highlight=False, soft_wrap=True)
    else:
        import json

        out.print(json.dumps(answer, indent=2, default=str))


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
        parts = [f"{feed.steps} steps", duration(feed.elapsed), money(feed.cost)]
    if session_id:
        parts.append(f"session {session_id}")
    meta = f" {SEP} ".join(p for p in parts if p)
    if status in ("completed", "idle"):
        out.print(f"[ok]{DONE} done[/ok]  [meta]{meta}[/meta]")
    elif status == "failed":
        out.print(f"[fail]{FAILED} failed[/fail]  [meta]{meta}[/meta]")
        if error_text:
            out.print(f"  {escape(error_text)}")
    else:
        out.print(f"[warn]{ATTENTION} {escape(status)}[/warn]  [meta]{meta}[/meta]")
        if error_text:
            out.print(f"  {escape(error_text)}")


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
    verb = _VERBS.get(base) or base.split("_")[0][:_VERB_WIDTH]
    for key in _TARGET_KEYS:
        value = args.get(key)
        if value:
            if key == "url":
                return verb, _short_url(str(value)) or str(value)
            text = " ".join(str(value).split())
            return verb, f'"{text}"' if key in ("text", "content", "query") else text
    if "x" in args and "y" in args:
        return verb, f"({args['x']}, {args['y']})"
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


def _first_sentence(data: dict[str, Any]) -> str | None:
    text = data.get("content") or data.get("reasoning_content") or ""
    text = " ".join(str(text).split())
    if not text:
        return None
    for stop in (". ", "! ", "? "):
        cut = text.find(stop)
        if 0 < cut < 160:
            return text[: cut + 1]
    return text[:160]


def _first_line(text: Any) -> str | None:
    lines = str(text).strip().splitlines() if text else []
    return lines[0] if lines else None
