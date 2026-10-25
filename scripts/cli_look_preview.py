"""Walk through every state of the CLI look with simulated events: `uv run python scripts/cli_look_preview.py`."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone

from hai_agents_cli import ui

FAST = "--fast" in sys.argv
T0 = datetime.now(timezone.utc)

STEPS = [
    ("open_app", {"app": "SAP Logon"}, "Opening SAP Logon from the dock.", 1.2),
    ("type_text", {"text": "FBL3N"}, "Typing the G/L line items transaction.", 0.6),
    ("click", {"element": "Execute"}, "Running the report for Q3.", 0.4),
    ("read", {"target": "report table"}, "The table has 412 rows; exporting through List > Export.", 2.1),
    ("click", {"element": "List > Export > Spreadsheet"}, "Choosing the spreadsheet export.", 0.7),
]


def sleep(seconds: float) -> None:
    if not FAST:
        time.sleep(seconds)


def event(offset: float, **data) -> dict:
    return {"type": "AgentEvent", "timestamp": (T0 + timedelta(seconds=offset)).isoformat(), "data": data}


def metrics(offset: float, steps: int, cost: float) -> dict:
    stamp = (T0 + timedelta(seconds=offset)).isoformat()
    return {"type": "MetricsUpdateEvent", "timestamp": stamp, "data": {"metrics": {"steps": steps, "total_cost": cost}}}


def main() -> None:
    out = ui.console()
    err = ui.console(stderr=True)

    err.print('[meta]$[/meta] holo "Export the Q3 report from SAP GUI to ~/Reports as PDF"\n')
    ui.header(err, "holo", ["local desktop", "holo4-35b-a3b", "approve risky", "Esc Esc stops"])
    feed = ui.StepFeed(err, max_steps=150)
    clock = 0.0
    feed.handle(event(clock, kind="observation_event", metadata={"title": "Desktop"}))
    for i, (tool, args, thought, seconds) in enumerate(STEPS, start=1):
        sleep(0.6)
        clock += seconds * 0.4
        feed.handle(event(clock, kind="policy_event", content=thought, tool_reqs=[{"tool_name": tool, "args": args}]))
        sleep(seconds)
        clock += seconds * 0.6
        feed.handle(event(clock, kind="tool_result", tool_req={"tool_name": tool}, result=None))
        feed.handle(metrics(clock, i, 0.009 * i))
    feed.close()

    err.print()
    ui.needs_you(
        err,
        'step 6 · click "Post document"',
        [
            "risk high: irreversible ledger write            [meta]conf 0.62[/meta]",
            "[meta]\\[inline crop of the target button][/meta]",
        ],
        [("a", "approve"), ("d", "deny"), ("t", "take over"), ("e", "edit instruction")],
    )
    err.print(f"\n[accent]{ui.PROMPT}[/accent] d")
    err.print(f"[accent]{ui.PROMPT}[/accent] e  only export, never post anything\n")
    sleep(0.8)

    feed = ui.StepFeed(err, max_steps=150, steps=5, cost=0.045)
    feed.handle(event(clock, kind="observation_event", metadata={"title": "SAP Easy Access"}))
    for n, (tool, args, seconds) in enumerate(
        [("click", {"element": "Export > PDF"}, 0.8), ("type_text", {"text": "~/Reports/Q3.pdf"}, 0.5)], start=6
    ):
        sleep(0.5)
        clock += seconds * 0.4
        feed.handle(
            event(
                clock,
                kind="policy_event",
                content="Exporting as PDF instead.",
                tool_reqs=[{"tool_name": tool, "args": args}],
            )
        )
        sleep(seconds)
        clock += seconds * 0.6
        feed.handle(event(clock, kind="tool_result", tool_req={"tool_name": tool}, result=None))
        feed.handle(metrics(clock, n, 0.009 * n))
    feed.handle(
        event(clock, kind="answer_event", answer="Exported the **Q3 report** (412 rows) to `~/Reports/Q3.pdf`.")
    )
    feed.close()
    err.print()
    ui.print_answer(out, feed.answer)
    err.print()
    ui.summary(err, "completed", feed)

    err.print('\n[meta]$[/meta] holo "..."')
    ui.error(err, "API key rejected (401)", fix="hai login --force")

    err.print("\n[meta]$[/meta] hai doctor")
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
