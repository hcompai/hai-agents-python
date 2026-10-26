"""Walk through every state of the CLI look with simulated events: `uv run python scripts/cli_look_preview.py`."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone

from hai_agents_cli import ui

FAST = "--fast" in sys.argv
T0 = datetime.now(timezone.utc)

STEPS = [
    ("open_app", {"app": "SAP Logon"}, "SAP Logon is pinned in the dock.", "SAP Logon 770", 1.2),
    ("write_desktop", {"text": "FBL3N"}, "FBL3N lists G/L line items.", "SAP Logon 770", 0.6),
    ("click_desktop", {"element": "Execute"}, "Running the report for Q3.", "G/L Account Line Item Display", 0.4),
    ("click_desktop", {"element": "List > Export > Spreadsheet"}, "412 rows; exporting.", "Export list object", 0.7),
]


def sleep(seconds: float) -> None:
    if not FAST:
        time.sleep(seconds)


def event(offset: float, **data) -> dict:
    return {"type": "AgentEvent", "timestamp": (T0 + timedelta(seconds=offset)).isoformat(), "data": data}


def metrics(offset: float, steps: int, cost: float) -> dict:
    stamp = (T0 + timedelta(seconds=offset)).isoformat()
    return {"type": "MetricsUpdateEvent", "timestamp": stamp, "data": {"metrics": {"steps": steps, "total_cost": cost}}}


def play(feed: ui.StepFeed, clock: float, first: int, steps: list) -> float:
    for n, (tool, args, thought, title, seconds) in enumerate(steps, start=first):
        sleep(seconds * 1.5)
        clock += seconds * 0.4
        feed.handle(
            event(clock, kind="policy_event", reasoning_content=thought, tool_reqs=[{"tool_name": tool, "args": args}])
        )
        sleep(seconds)
        clock += seconds * 0.6
        feed.handle(event(clock, kind="tool_result", tool_req={"tool_name": tool}, result=None))
        feed.handle(metrics(clock, n, 0.009 * n))
        sleep(0.3)
        feed.handle(event(clock, kind="observation_event", metadata={"title": title}))
    return clock


def main() -> None:
    out = ui.console()
    err = ui.console(stderr=True)

    ui.banner(err)
    ui.header(err, "holo", ["local desktop", "holo4-35b-a3b", "approve risky", "Esc Esc stops"])
    ui.user(err, "Export the Q3 report from SAP GUI to ~/Reports as PDF")
    feed = ui.StepFeed(err, max_steps=150)
    feed.handle(event(0.0, kind="observation_event", metadata={"title": "Desktop"}))
    clock = play(feed, 0.0, 1, STEPS)
    feed.close()

    ui.needs_you(
        err,
        '[bold]Click[/bold]("Post document")',
        ["[warn]risk high[/warn]: irreversible ledger write  [meta]conf 0.62[/meta]"],
        ["Approve", "Deny", "Take over", "Tell holo what to do instead"],
        selected=3,
    )
    ui.user(err, "only export, never post anything")
    sleep(0.8)

    feed = ui.StepFeed(err, max_steps=150, steps=4, cost=0.036)
    feed.handle(event(clock, kind="observation_event", metadata={"title": "Export list object"}))
    clock = play(
        feed,
        clock,
        5,
        [
            ("click_desktop", {"element": "Export > PDF"}, "Exporting as PDF instead.", "Save As", 0.8),
            ("write_desktop", {"text": "~/Reports/Q3.pdf"}, "Saving under ~/Reports.", "Q3.pdf", 0.5),
        ],
    )
    feed.handle(
        event(clock, kind="answer_event", answer="Exported the **Q3 report** (412 rows) to `~/Reports/Q3.pdf`.")
    )
    feed.close()
    ui.print_answer(out, feed.answer)
    err.print()
    ui.summary(err, "completed", feed)

    err.print("\n[meta]$ holo run ...[/meta]")
    ui.error(err, "API key rejected (401)", fix="holo login --force")

    err.print("\n[meta]$ holo doctor[/meta]")
    ui.check(err, "ok", "login", "API key found (~/.config/hai/.env)")
    ui.check(err, "ok", "platform", "authenticated against https://agp.eu.hcompany.ai")
    ui.check(
        err,
        "warn",
        "runtime",
        "hai-agent-runtime from PATH, not the pinned build",
        fix="remove it from PATH, or set HAI_AGENT_LOCAL_BINARY_PATH on purpose",
    )
    ui.check(
        err,
        "fail",
        "desktop",
        "this terminal is missing macOS grants: Screen Recording",
        fix="System Settings -> Privacy & Security -> Screen Recording, then restart the terminal",
    )


if __name__ == "__main__":
    main()
