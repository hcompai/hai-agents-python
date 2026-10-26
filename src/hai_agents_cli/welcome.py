"""Startup facts for the welcome panel, fetched in parallel; a slow or failing source just drops its line."""

from __future__ import annotations

import contextlib
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from hai_agents.client import credentials_path

from . import ui

FETCH_TIMEOUT_S = 1.5
UPDATE_CHECK_EVERY_S = 24 * 3600
PYPI_URL = "https://pypi.org/pypi/hai-agents/json"
_REQUEST_OPTIONS = {"timeout_in_seconds": 2, "max_retries": 0}


@dataclass
class Facts:
    quota: Any = None
    recent: list[Any] | None = None
    latest: str | None = None


def current_version() -> str:
    try:
        return version("hai-agents")
    except PackageNotFoundError:
        return "dev"


def gather(client: Any, *, cloud: bool) -> Facts:
    jobs: dict[str, Callable[[], Any]] = {"latest": latest_version}
    if cloud:
        jobs["quota"] = lambda: client.quota.get_token_quota(request_options=_REQUEST_OPTIONS)
        jobs["recent"] = lambda: client.sessions.list_sessions(page=1, size=3, request_options=_REQUEST_OPTIONS).items
    pool = ThreadPoolExecutor(len(jobs))
    futures = {name: pool.submit(job) for name, job in jobs.items()}
    wait(futures.values(), timeout=FETCH_TIMEOUT_S)
    pool.shutdown(wait=False, cancel_futures=True)
    return Facts(**{name: f.result() for name, f in futures.items() if f.done() and f.exception() is None})


def latest_version() -> str | None:
    cache = credentials_path().parent / "latest-version.json"
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        cached = json.loads(cache.read_text())
        if time.time() - cached["checked_at"] < UPDATE_CHECK_EVERY_S:
            return str(cached["version"])
    latest = str(httpx.get(PYPI_URL, timeout=FETCH_TIMEOUT_S).json()["info"]["version"])
    with contextlib.suppress(OSError):
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"version": latest, "checked_at": time.time()}))
    return latest


def is_newer(latest: str | None, current: str) -> bool:
    try:
        return latest is not None and tuple(map(int, latest.split("."))) > tuple(map(int, current.split(".")))
    except ValueError:
        return False


def missing_grants() -> list[str]:
    if sys.platform != "darwin":
        return []
    try:
        from .doctor import missing_macos_grants

        return missing_macos_grants()
    except Exception:
        return []


def quota_line(quota: Any) -> str | None:
    if quota is None:
        return None
    if not quota.limit:
        return f"{_tokens(quota.used)} tokens used since {_day(quota.window_start)}" if quota.used else None
    left = quota.remaining if quota.remaining is not None else max(quota.limit - (quota.used or 0), 0)
    line = f"{_tokens(left)} of {_tokens(quota.limit)} tokens left"
    if quota.window_end:
        line += f" {ui.SEP} resets {_day(quota.window_end)}"
    return line


def activity(summary: Any) -> ui.Activity:
    message = summary.first_message.message if summary.first_message else summary.agent or summary.id
    return ui.Activity(
        str(summary.status),
        " ".join(message.split()),
        age(summary.last_activity_at or summary.created_at),
        summary.agent_view_url,
    )


def age(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - when).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return "just now"


def _tokens(n: int) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}".removesuffix(".0") + unit
    return str(n)


def _day(when: datetime) -> str:
    return f"{when:%b} {when.day}"
