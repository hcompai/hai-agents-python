"""Startup facts for the welcome panel, fetched in parallel; a slow or failing source just drops its line."""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from hai_agents_common import credentials

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
    found: dict[str, Any] = {}

    def run(name: str, job: Callable[[], Any]) -> None:
        with contextlib.suppress(Exception):
            found[name] = job()

    # Daemon threads, so a fetch stuck past the deadline (DNS has no timeout) never holds up exit.
    threads = [threading.Thread(target=run, args=job, daemon=True) for job in jobs.items()]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + FETCH_TIMEOUT_S
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return Facts(**found.copy())


def latest_version() -> str | None:
    cache = credentials.GLOBAL_ENV_PATH.parent / "latest-version.json"
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        cached = json.loads(cache.read_text())
        if time.time() - cached["checked_at"] < UPDATE_CHECK_EVERY_S:
            return None if cached["version"] is None else str(cached["version"])
    latest = None
    with contextlib.suppress(Exception):
        latest = str(httpx.get(PYPI_URL, timeout=FETCH_TIMEOUT_S).json()["info"]["version"])
    with contextlib.suppress(OSError):
        credentials.private_config_dir()
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
