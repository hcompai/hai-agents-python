"""`holo` command-line interface."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import difflib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Column, Table
from rich.text import Text

from hai_agents import (
    Client,
    assert_request_under_limit,
    is_settled_session_status,
    is_terminal_session_status,
    stream_session,
    wait_for_session,
)
from hai_agents.core.api_error import ApiError
from hai_agents.environment import HaiAgentsEnvironment
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import PageSessionSummary
from hai_agents_common import credentials
from hai_agents_common.credentials import absolute_share_url, make_client
from hai_agents_common.jsonable import to_jsonable
from hai_agents_local import desktop as desktop_defaults

from . import _CLI_HINT, auth, keys, mcp_hosts, steer, ui, welcome

if TYPE_CHECKING:
    from hai_agents_local import LocalBridge

_AGENT_POLL_S = 3.0
_TURN_GRACE_S = 120.0  # past max_time, sagent spends up to 60s forcing an answer, plus the pod's startup
CLEAN_STATUSES = ("completed", "idle")
IDLE_TIMEOUT_S = 600
LOCAL_MAX_STEPS = 150
LOCAL_MAX_TIME_S = 1800.0
NOTIFY_AFTER_S = 30.0

console = ui.console()
err_console = ui.console(stderr=True)

app = typer.Typer(
    name="holo",
    help="Run H Company agents from your terminal.",
    epilog='\b\nExamples:\n  holo "What is the top story on Hacker News?"\n'
    '  holo --local "Open Calculator and compute 2+2"\n'
    "  holo                                  (interactive session)\n"
    "  holo agents use h/web-surfer-pro      (change the default agent)\n"
    "  holo sessions watch <session-id>",
    no_args_is_help=True,
    rich_markup_mode=None,
)
sessions_app = typer.Typer(no_args_is_help=True, help="Inspect and steer sessions.")
agents_app = typer.Typer(no_args_is_help=True, help="Browse available agents.")
skills_app = typer.Typer(no_args_is_help=True, help="Browse available skills.")
mcp_app = typer.Typer(no_args_is_help=True, help="Manage the hai-agents MCP server.")
local_app = typer.Typer(
    no_args_is_help=True,
    help="Manually run the local browser, desktop or workstation bridge. Only needed when the session is started "
    "elsewhere (the web app, another machine, or an agent referenced by name); sessions created "
    "from the Python SDK with an inline agent start it automatically.",
)


@dataclass(frozen=True)
class AppState:
    api_key: str | None
    base_url: str | None
    json_output: bool


@app.callback()
def configure(
    ctx: typer.Context,
    api_key: str | None = typer.Option(None, "--api-key", help="API key. Defaults to HAI_API_KEY."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override the Agent Platform base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    ctx.obj = AppState(api_key=api_key, base_url=base_url, json_output=json_output)


@app.command()
def login(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Re-authenticate and rotate the stored key."),
    key: bool = typer.Option(
        False,
        "--key",
        help=f"Store an existing API key (from {credentials.API_KEYS_PAGE}) instead of signing in through the browser. "
        "Reads it from a hidden prompt, or from stdin when piped.",
    ),
) -> None:
    """Sign in through the browser or with a pasted key, and store the key in ~/.config/hai/.env."""
    state = _state(ctx)
    if credentials.current_api_key() and not force:
        console.print("Already signed in. Pass --force to rotate the key.")
        return
    if key:
        _store_pasted_key(state.base_url)
        return
    if not _interactive():
        _raise_cli_error(RuntimeError(f"login needs an interactive terminal. {auth.KEY_FALLBACK}"))
    _sign_in(state.base_url)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _sign_in_if_needed(state: AppState) -> None:
    """Commands sign in on first use in a terminal, so a fresh install needs no `holo login` step."""
    if credentials.current_api_key(state.api_key) or state.json_output or not _interactive():
        return
    console.print("No API key found, so let's sign you in first.")
    _sign_in(state.base_url)


def _sign_in(base_url: str | None) -> None:
    console.print(
        "How do you want to sign in?\n"
        "  1. Google account, in your browser\n"
        f"  2. Paste an API key from {credentials.API_KEYS_PAGE}"
    )
    choice = typer.prompt("Choice", default="1").strip()
    if choice == "1":
        _browser_sign_in(base_url)
    elif choice == "2":
        _store_pasted_key(base_url)
    else:
        _raise_cli_error(RuntimeError(f"Choice must be 1 or 2, got {choice!r}."))


def _browser_sign_in(base_url: str | None) -> None:
    label = f"holo CLI ({socket.gethostname()})"
    try:
        minted = auth.login_and_mint(
            credentials.portal_base(base_url),
            label,
            lambda url: console.print(f"Opening your browser. If it does not open, visit:\n  {url}", style="dim"),
        )
    except Exception as exc:
        _raise_cli_error(exc)
    path = credentials.save_api_key(minted)
    ui.ok(console, f"signed in {ui.SEP} key saved to {path}")


def _store_pasted_key(base_url: str | None) -> None:
    prompt = f"API key (create one at {credentials.API_KEYS_PAGE})"
    pasted = typer.prompt(prompt, hide_input=True) if sys.stdin.isatty() else sys.stdin.readline()
    pasted = pasted.strip()
    if not pasted:
        _raise_cli_error(RuntimeError(f"no key given; create one at {credentials.API_KEYS_PAGE}."))
    try:
        make_client(api_key=pasted, base_url=base_url).sessions.get_session_quota()
    except ApiError as exc:
        if exc.status_code in (401, 403):
            _raise_cli_error(
                RuntimeError(
                    f"the platform rejected this key ({exc.status_code}); check it at {credentials.API_KEYS_PAGE}."
                )
            )
        _raise_cli_error(exc)
    except Exception as exc:
        _raise_cli_error(exc)
    path = credentials.save_api_key(pasted)
    ui.ok(console, f"signed in {ui.SEP} key saved to {path}")


@app.command()
def logout() -> None:
    """Remove the stored API key from ~/.config/hai/.env."""
    path = credentials.clear_api_key()
    console.print(f"Removed {credentials.API_KEY_VAR} from {path}." if path else "No stored key found.")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Diagnose this machine's holo setup: login, platform access, local browser/desktop. Read-only."""
    from .doctor import run_checks

    state = _state(ctx)
    results = run_checks(api_key=state.api_key, base_url=state.base_url)
    if state.json_output:
        _print_json([{"name": r.name, "ok": r.ok, "detail": r.detail, "fix": r.fix} for r in results])
    else:
        for r in results:
            ui.check(console, "ok" if r.ok else "fail", r.name, r.detail, fix=r.fix)
        if _interactive() and any(r.name == "desktop" and not r.ok for r in results):
            _offer_privacy_settings()
    if not all(r.ok for r in results):
        raise typer.Exit(1)


def _offer_privacy_settings() -> None:
    from .doctor import missing_macos_grants, settings_urls

    missing = missing_macos_grants()
    if not missing or not typer.confirm(f"\nOpen System Settings to grant {' and '.join(missing)}?", default=True):
        return
    for grant in missing:
        subprocess.run(["open", settings_urls()[grant]], check=False)
    ui.hint(console, "after granting, restart this terminal and run `holo doctor` again")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Show the resolved endpoint and authentication status."""
    state = _state(ctx)
    authenticated = credentials.current_api_key(state.api_key) is not None
    data = {
        "base_url": credentials.resolve_base_url(state.base_url),
        "authenticated": authenticated,
        "source": credentials.source(state.api_key),
    }
    if state.json_output:
        _print_json(data)
        return
    table = Table("Field", "Value", show_header=False)
    table.add_row("Endpoint", data["base_url"] or HaiAgentsEnvironment.EU.value)
    table.add_row("Authenticated", "yes" if authenticated else "no")
    table.add_row("Key source", data["source"] or "(none)")
    console.print(table)


def _parse_overrides(items: list[str]) -> dict[str, Any]:
    """Parse repeated ``PATH=VALUE`` flags into an overrides dict.

    The separating ``=`` is the first one outside ``[...]``, since selector
    clauses like ``[kind=web]`` carry their own ``=``. VALUE is read as JSON,
    falling back to a plain string when it is not valid JSON.
    """
    overrides: dict[str, Any] = {}
    for item in items:
        depth = 0
        cut = None
        for i, char in enumerate(item):
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            elif char == "=" and depth == 0:
                cut = i
                break
        if cut is None:
            raise typer.BadParameter(f"override must be PATH=VALUE: {item!r}")
        path, raw = item[:cut], item[cut + 1 :]
        try:
            overrides[path] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[path] = raw
    return overrides


LOCAL_DESKTOP_AGENT = {
    "name": "holo",
    "description": "Desktop agent that drives the user's machine.",
    "environments": [{"id": "desktop", "kind": "desktop", "host": "user_device"}],
}


def _resolve_agent(agent: str | None, local: bool) -> Any:
    if not local:
        return agent or credentials.default_agent()
    if agent:
        _raise_cli_error(RuntimeError("--local drives this desktop with its own agent; drop --agent"))
    return LOCAL_DESKTOP_AGENT


AGENT_HELP = f"Agent name. Default: {credentials.DEFAULT_AGENT}, or the one set with `holo agents use`."
COMMAND_NAMES = frozenset({"new", "clear", "agent", "live", "share", "help", "exit", "quit"})
EXAMPLE_TASKS = {
    False: "Find the top 3 stories on Hacker News and their URLs",
    True: "Open Calculator and compute 15% of 240",
}


@app.command()
def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task to run."),
    agent: str | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    local: bool = typer.Option(False, "--local", help="Drive this machine's desktop through the local runtime."),
    max_steps: int | None = typer.Option(
        None, "--max-steps", min=1, max=200, help="Maximum reasoning steps. Uncapped, or 150 with --local."
    ),
    max_time_s: float | None = typer.Option(
        None, "--max-time", min=1.0, max=1800.0, help="Maximum run seconds. Uncapped, or 1800 with --local."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the answer."),
    override: list[str] = typer.Option(
        None,
        "--override",
        "-o",
        help=(
            "Per-run override as PATH=VALUE, repeatable. VALUE is parsed as JSON, else a string. "
            "Example: -o 'agent.environments[kind=web].start_url=https://bing.com'"
        ),
    ),
) -> None:
    """Run a task, stream its steps, and print the answer; in a terminal, follow up on the same session."""
    convo = _Conversation(
        _state(ctx),
        _resolve_agent(agent, local),
        local=local,
        max_steps=max_steps or (LOCAL_MAX_STEPS if local else None),
        max_time_s=max_time_s or (LOCAL_MAX_TIME_S if local else None),
        overrides=_parse_overrides(override or []),
        quiet=quiet,
    )
    try:
        assert_request_under_limit(convo.params(task))
    except Exception as exc:
        _raise_cli_error(exc)
    convo.open()
    try:
        if convo.followups:
            convo._send(task, echo=True)
            convo.loop()
        else:
            convo.turn(task, echo=True)
    finally:
        convo.close()
    if convo.result is not None:
        _exit_unless_clean(convo.result.status)


@app.command()
def chat(
    ctx: typer.Context,
    agent: str | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    local: bool = typer.Option(False, "--local", help="Drive this machine's desktop through the local runtime."),
) -> None:
    """Start an interactive session; plain `holo` in a terminal opens this."""
    state = _state(ctx)
    if not _interactive() or state.json_output:
        _raise_cli_error(RuntimeError('chat needs an interactive terminal; run one task with `holo "<task>"`'))
    convo = _Conversation(
        state,
        _resolve_agent(agent, local),
        local=local,
        max_steps=LOCAL_MAX_STEPS if local else None,
        max_time_s=LOCAL_MAX_TIME_S if local else None,
        overrides={},
    )
    convo.open()
    try:
        convo.show_header()
        convo.loop()
    finally:
        convo.close()


@dataclass
class _Conversation:
    """One session across turns: the first message creates it; follow-ups and Esc corrections continue it."""

    state: AppState
    agent: Any
    local: bool
    max_steps: int | None
    max_time_s: float | None
    overrides: dict[str, Any]
    quiet: bool = False
    client: Any = None
    session: Any = None
    result: Any = None
    next_index: int = 0
    steps: int = 0
    cost: float | None = None
    run_steps: int = 0
    _listener: Any = None
    _header_shown: bool = False
    _prompt: Any = None
    _pending: str | None = None
    _pending_shown: bool = False
    _draft: str = ""
    _kinds: list[str] | None = None
    _answer: Any = None
    _task: str | None = None

    @property
    def human(self) -> bool:
        return not (self.state.json_output or self.quiet)

    @property
    def followups(self) -> bool:
        return self.human and _interactive()

    @property
    def view_url(self) -> str | None:
        return getattr(self.session, "agent_view_url", None)

    def params(self, message: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "agent": self.agent,
            "messages": message,
        }
        if self.max_steps:
            params["max_steps"] = self.max_steps
        if self.max_time_s:
            params["max_time_s"] = self.max_time_s
        if self.overrides:
            params["overrides"] = self.overrides
        if self.followups:
            params["idle_timeout_s"] = IDLE_TIMEOUT_S
        return params

    @property
    def kinds(self) -> list[str]:
        """The environments this agent drives on this machine; empty for an agent that runs in the cloud."""
        if self.local:
            return ["desktop"]
        if self._kinds is None:
            self._kinds = _local_kinds(self.client, self.agent)
        return self._kinds

    @property
    def controls_machine(self) -> bool:
        return bool(self.kinds)

    @property
    def drives_desktop(self) -> bool:
        return any(kind in ("desktop", "workstation") for kind in self.kinds)

    @property
    def does(self) -> str:
        if self.drives_desktop:
            return "drives this desktop"
        return "drives this machine's browser" if self.controls_machine else "runs in the cloud"

    def open(self) -> None:
        self.client = _local_client(self.state) if self.local else _client(self.state)
        self._arm_listener()

    def _arm_listener(self) -> None:
        """Double-Esc stops an agent that controls this machine, from any app."""
        if self.controls_machine and self._listener is None:
            self._listener = _arm_local_kill_switch()
        elif not self.controls_machine and self._listener is not None:
            self._listener.stop()
            self._listener = None

    def close(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self.client is not None:
            self.client.close()

    def show_header(self) -> None:
        if self._header_shown or not self.human:
            return
        self._header_shown = True
        if self.followups:
            self._show_welcome()
            return
        stop = f" {ui.SEP} esc esc stops it" if self.controls_machine and self._listener else ""
        ui.header(err_console, "holo", [self.label, self.does + stop, _custom_endpoint_host(self.state)])

    def _show_welcome(self) -> None:
        facts = welcome.gather(self.client, cloud=not self.local)
        current = welcome.current_version()
        if self.controls_machine:
            stop = "esc esc stops it from any app" if self._listener else "ctrl+c stops it"
        else:
            stop = f"type while it works to steer {ui.SEP} esc pauses" if keys.supported() else "ctrl+c stops it"
        tips = [Text(f"{stop} {ui.SEP} / lists commands", style="meta")]
        if welcome.is_newer(facts.latest, current):
            upgrade = f"holo {facts.latest} is available {ui.SEP} pip install -U 'hai-agents[cli]'"
            tips.append(Text(upgrade, style="warn"))
        if self.drives_desktop and (missing := welcome.missing_grants()):
            tips.append(Text(f"missing macOS grants: {', '.join(missing)} {ui.SEP} run holo doctor", style="warn"))
        about = [Text.assemble(self.label, (f" {ui.SEP} {self.does}", "meta"))]
        about += [
            Text(line, style="meta")
            for line in (welcome.quota_line(facts.quota), _custom_endpoint_host(self.state))
            if line
        ]
        ui.welcome(err_console, current, about, tips)

    @property
    def label(self) -> str:
        return "local desktop" if self.local else str(self.agent)

    def commands(self) -> list[tuple[str, str]]:
        rows = [
            ("/new [task]", "end this session; start fresh, optionally with a task"),
            ("/retry", "run the session's first task again, fresh"),
        ]
        if not self.local:
            rows += [
                ("/resume [n]", "continue one of your recent sessions"),
                ("/agent [name]", "switch agent and save it as the default"),
                ("/live", "open the live view in your browser"),
                ("/share", "create a public share link"),
            ]
        rows += [("/status", "session, agent and usage"), ("/copy", "copy the last answer")]
        return [*rows, ("/help", "commands and keys"), ("/exit", "leave")]

    def keys(self) -> list[tuple[str, str]]:
        if self.controls_machine:
            stop = [("esc esc", "stop the agent")]
        elif keys.supported():
            stop = [
                ("type", "message the agent while it works"),
                ("esc", "pause the agent; esc again resumes"),
                ("/answer", "while it works: answer now"),
            ]
        else:
            stop = []
        return [
            ("enter", "send"),
            *stop,
            ("ctrl+c", "cancel the turn or clear the input; twice to exit"),
            ("ctrl+d", "exit"),
            ("up / down", "history"),
            ("ctrl+r", "search history"),
            ("tab or →", "accept the grey suggestion"),
            ("\\ enter", "new line"),
        ]

    def toolbar(self) -> str:
        if self.session is None:
            state = "new task"
        else:
            parts = [f"follow-up on {str(self.session.id)[:8]}", ui.count(self.steps, "step"), ui.money(self.cost)]
            state = f" {ui.SEP} ".join(p for p in parts if p) + f" {ui.SEP} /new for a fresh task"
        return f"  {self.label} {ui.SEP} {state} {ui.SEP} ? for shortcuts"

    def example(self) -> str | None:
        return None if self.session is not None else EXAMPLE_TASKS[self.drives_desktop]

    def placeholder(self) -> str:
        example = self.example()
        return f'Try "{example}"' if example else "Follow up, or /new for a fresh task"

    def turn(self, message: str, *, echo: bool = False) -> None:
        started_at = time.time()
        self.show_header()
        if echo and self.human:
            ui.user(err_console, message)
        if self.session is None:
            try:
                with self._starting():
                    self.session, self.result = self._create_session(message), None
                self._task = message
            except KeyboardInterrupt:
                self._cancel_turn(None)
                return
            except Exception as exc:
                _raise_cli_error(exc)
            self.next_index, self.run_steps = 0, 0
            if self.human and self.view_url:
                ui.url(err_console, self.view_url)
                err_console.print()
        else:
            request = SendSessionMessagesRequestBody_UserMessage(message=message)
            try:
                self.client.sessions.send_session_messages(self.session.id, request=request)
            except KeyboardInterrupt:
                self._cancel_turn(None)
                return
            except Exception as exc:
                if not self._session_ended():
                    _raise_cli_error(exc)
                self._end_session()
                ui.hint(err_console, "that session had ended; starting a new one")
                self.turn(message)
                return
        feed = None
        steering = None
        if self.human:
            stop_hint = "esc esc to stop" if self.controls_machine and self._listener else "ctrl+c to stop"
            feed = ui.StepFeed(
                err_console,
                max_steps=self.max_steps,
                steps=self.steps,
                cost=self.cost,
                run_steps=self.run_steps,
                stop_hint=stop_hint,
                starting=self.next_index == 0,
            )
            if not self.controls_machine and _interactive() and keys.supported():
                steering = steer.Steering(
                    self.client, str(self.session.id), feed, err_console, local_command=self._command_mid_turn
                )
        timeout = self.max_time_s + _TURN_GRACE_S if self.max_time_s else None
        try:
            if feed is not None:
                with steering.watch() if steering else contextlib.nullcontext():
                    try:
                        _follow(
                            self.client,
                            self.session.id,
                            feed,
                            timeout_s=timeout,
                            from_index=self.next_index,
                            stop_at_tool_wait=True,
                        )
                    except KeyboardInterrupt:
                        if steering is not None:
                            steering.stop()
                        raise
                    finally:
                        if steering is not None:
                            steering.finish()
                            self._draft = steering.box.text
                            if steering.pending:
                                self._pending, self._pending_shown = steering.pending, steering.pending_shown
            result = wait_for_session(self.client, self.session.id, from_index=self.next_index, timeout_seconds=timeout)
        except KeyboardInterrupt:
            self._cancel_turn(feed)
            return
        except Exception as exc:
            if feed is not None:
                feed.close()
                self.next_index += feed.handled
                self.steps, self.cost, self.run_steps = feed.steps, feed.cost, feed.run_steps
            if not self.followups:
                _raise_cli_error(exc)
            if isinstance(exc, TimeoutError):
                ui.error(err_console, f"no answer after {ui.duration(timeout or 0)}; the agent may still be working")
            else:
                ui.error(err_console, f"lost the session's stream: {exc}")
            ui.hint(err_console, "follow up to pick it back up, /live to watch, or /new to start over")
            return
        if feed is not None:
            feed.close()
            if feed.answer is None:
                feed.answer = result.answer
            self.steps, self.cost = feed.steps, feed.cost
        self.result, self.next_index, self.run_steps = result, result.next_from_index, 0
        answer = feed.answer if feed is not None else result.answer
        if answer is not None:
            self._answer = answer
        stopped = self.controls_machine and _kill_switch_fired(started_at)
        _print_run_result(
            result,
            self.state.json_output,
            agent_view_url=self.view_url,
            feed=feed,
            stopped=stopped,
            show_session_id=not self.followups,
        )
        if feed is not None and feed.elapsed >= NOTIFY_AFTER_S:
            verdict = ui.outcome(_status_text(result.status), result.outcome)
            ui.notify(err_console, f"holo: {verdict} in {ui.duration(feed.elapsed)}")
        if stopped or is_terminal_session_status(str(result.status)) or _awaits_tools(result):
            self._end_session()
            if self.followups:
                ui.hint(err_console, "session ended; the next message starts a new one")

    def _create_session(self, message: str) -> Any:
        """On ctrl+c, the session is cancelled once the create call returns, even if ctrl+c is pressed again."""
        params = self.params(message)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            created = pool.submit(self.client.sessions.create_session, **params)
            try:
                return created.result()
            except KeyboardInterrupt:
                created.add_done_callback(self._cancel_created)
                raise

    def _cancel_created(self, created: concurrent.futures.Future) -> None:
        if not created.cancelled() and created.exception() is None:
            _cancel_quietly(self.client, created.result().id)

    def _cancel_turn(self, feed: ui.StepFeed | None) -> None:
        if self.session is not None:
            _cancel_quietly(self.client, self.session.id)
        if feed is not None:
            feed.close()
        if not self.followups:
            ui.error(err_console, "interrupted; session cancelled")
            raise typer.Exit(130) from None
        ui.error(err_console, "turn cancelled; the next message starts a new session")
        self.session, self.result, self.steps, self.cost = None, None, 0, None

    def _end_session(self) -> None:
        """Release the session's browser or desktop; the next message starts a new one."""
        if self.session is not None and not is_terminal_session_status(str(getattr(self.result, "status", ""))):
            _cancel_quietly(self.client, self.session.id)
        self.session, self.steps, self.cost, self.run_steps = None, 0, None, 0

    def _session_ended(self) -> bool:
        try:
            return is_terminal_session_status(str(self.client.sessions.get_session_status(self.session.id).status))
        except Exception:
            return False

    def _starting(self) -> Any:
        if not (self.human and ui.interactive(err_console)):
            return contextlib.nullcontext()
        return err_console.status(Text("Starting the agent…", style="accent"), spinner="dots", spinner_style="accent")

    def loop(self) -> None:
        while True:
            shown = self._pending is not None and self._pending_shown
            text = self._pending if self._pending is not None else _read_message(self)
            self._pending, self._pending_shown = None, False
            if text is None:
                self._leave()
                return
            text = text.strip()
            if not text:
                continue
            if not shown:
                ui.user(err_console, text)
            if text == "?":
                self._show_help()
                continue
            if _is_command(text):
                if not self.command(text):
                    self._leave()
                    return
                continue
            self._send(text)

    def _send(self, text: str, *, echo: bool = False) -> None:
        with contextlib.suppress(typer.Exit):
            self.turn(text, echo=echo)
        err_console.print()

    def _leave(self) -> None:
        if self.session is not None and not self.controls_machine:
            minutes = IDLE_TIMEOUT_S // 60
            ui.hint(err_console, f"session {self.session.id} stays open {minutes} min, then closes")

    def _show_help(self) -> None:
        ui.commands(err_console, self.commands())
        err_console.print()
        ui.commands(err_console, self.keys())
        err_console.print()

    def command(self, text: str) -> bool:
        """Run a slash command; False means leave."""
        name, _, arg = text[1:].partition(" ")
        arg = arg.strip()
        if name in ("exit", "quit"):
            return False
        if name == "help":
            self._show_help()
        elif name in ("new", "clear"):
            self._end_session()
            if arg:
                self._send(arg)
            else:
                ui.ok(err_console, "the next message starts a new session")
        elif name == "agent":
            try:
                self._switch_agent(arg)
            except KeyboardInterrupt:
                err_console.print()
        elif name == "live":
            if self.view_url:
                webbrowser.open(self.view_url)
                ui.ok(err_console, "opened", url=self.view_url)
            elif self.session is not None:
                ui.error(err_console, "this session has no live view")
            else:
                ui.error(err_console, "no session yet", fix="send a task first")
        elif name == "share":
            self._share()
        elif name == "retry":
            if self._task is None:
                ui.error(err_console, "nothing to retry yet", fix="send a task first")
            else:
                self._end_session()
                self._send(self._task, echo=True)
        elif name == "resume" and not self.local:
            try:
                self._resume_session(arg)
            except KeyboardInterrupt:
                err_console.print()
        elif name == "status":
            self._status()
        elif name == "copy":
            self._copy()
        elif name == "answer":
            ui.error(err_console, "/answer works while the agent runs", fix="type /answer while it works")
        else:
            ui.error(err_console, f"unknown command /{name}", fix="/help lists the commands")
        return True

    def _resume_session(self, arg: str) -> None:
        try:
            recent = self.client.sessions.list_sessions(page=1, size=10).items
        except Exception as exc:
            ui.error(err_console, str(exc))
            return
        if not recent:
            ui.error(err_console, "no sessions yet", fix="send a task first")
            return
        try:
            picked = _pick_session(recent, arg)
        except typer.Exit:
            return
        if self.session is not None and str(picked.id) == str(self.session.id):
            ui.ok(err_console, "already on this session")
            return
        try:
            session = self.client.sessions.get_session(picked.id)
            changes = self.client.sessions.get_session_changes(
                picked.id, from_index=0, include_events=True, wait_for_seconds=0
            )
        except Exception as exc:
            ui.error(err_console, str(exc))
            return
        if _drives_a_machine(self.client, session.request.agent):
            ui.error(err_console, "a session that drove a machine cannot be resumed", fix="/new starts a fresh one")
            return
        self._end_session()
        self.session, self.result, self._answer = session, None, session.latest_answer
        self._task = picked.first_message.message if picked.first_message else None
        events = [] if changes is None else changes.new_events or []
        self.next_index = 0 if changes is None else (changes.first_index or 0) + len(events)
        self.steps, self.cost = ui.usage(events)
        if picked.agent:
            self._use_agent(picked.agent)
        ui.ok(err_console, f"resumed {ui.SEP} {welcome.activity(picked).task}", url=self.view_url)

    def _status(self) -> None:
        if self.session is None:
            ui.ok(err_console, f"{self.label} {ui.SEP} {self.does} {ui.SEP} no session yet")
        else:
            status = getattr(self.result, "status", None) or "running"
            with contextlib.suppress(Exception):
                status = self.client.sessions.get_session_status(self.session.id).status
            parts = [
                f"session {str(self.session.id)[:8]}",
                _status_text(status),
                ui.count(self.steps, "step"),
                ui.money(self.cost),
            ]
            ui.ok(err_console, f" {ui.SEP} ".join(p for p in parts if p), url=self.view_url)
            ui.hint(err_console, f"{self.label} {ui.SEP} {self.does}")
        if not self.local:
            with contextlib.suppress(Exception):
                if line := welcome.quota_line(self.client.quota.get_token_quota()):
                    ui.hint(err_console, line)

    def _copy(self) -> None:
        if self._answer is None:
            ui.error(err_console, "no answer yet", fix="send a task first")
            return
        text = self._answer if isinstance(self._answer, str) else json.dumps(to_jsonable(self._answer), indent=2)
        if _to_clipboard(text):
            ui.ok(err_console, "copied the last answer")
        else:
            ui.error(err_console, "could not copy", fix="needs a working pbcopy, wl-copy, xclip or xsel")

    def _switch_agent(self, name: str) -> None:
        if self.local:
            ui.error(
                err_console, "the local desktop agent cannot be switched", fix="leave and run `holo` without --local"
            )
            return
        try:
            name = name or _pick_agent(self.client, current=self.agent)
            _save_default_agent(self.client, name)
        except typer.Exit:
            return
        self._end_session()
        self._use_agent(name)
        ui.ok(err_console, f"{name} is now the default {ui.SEP} {self.does} {ui.SEP} next message starts a new session")

    def _use_agent(self, name: str) -> None:
        self.agent, self._kinds = name, None
        self._arm_listener()

    def _share(self) -> None:
        if self.session is None:
            ui.error(err_console, "no session yet", fix="send a task first")
            return
        try:
            share = self.client.sessions.share_session(self.session.id)
        except Exception as exc:
            ui.error(err_console, str(exc))
            return
        ui.ok(err_console, "share link", url=absolute_share_url(self.client, share.share_url))

    def _command_mid_turn(self, text: str) -> bool:
        """Commands typed while the agent works run here; /answer and plain text go to the agent."""
        if text == "?":
            self._show_help()
            return True
        if text == steer.ANSWER or not _is_command(text):
            return False
        name = text[1:].split(maxsplit=1)[0]
        if name in ("help", "live", "share", "status", "copy"):
            self.command(text)
        else:
            ui.hint(err_console, f"/{name} works between turns {ui.SEP} esc pauses, ctrl+c cancels the turn")
        return True


def _read_message(convo: _Conversation) -> str | None:
    """The conversation prompt; None means the user left."""
    if convo._prompt is None:
        try:
            from hai_agents_cli.prompt import Prompt
        except ModuleNotFoundError as exc:
            if (exc.name or "").split(".")[0] != "prompt_toolkit":
                raise
            ui.error(err_console, _CLI_HINT)
            raise typer.Exit(1) from None

        convo._prompt = Prompt(credentials.private_config_dir() / "history", convo.commands)
    draft, convo._draft = convo._draft, ""
    return convo._prompt.read(
        toolbar=convo.toolbar, placeholder=convo.placeholder(), example=convo.example(), default=draft
    )


def _is_command(text: str) -> bool:
    """A known `/name`, or an unknown one that is not a path like `/Users/me/a.pdf`."""
    if not text.startswith("/"):
        return False
    name = text[1:].split(maxsplit=1)[0] if text[1:].strip() else ""
    return name in COMMAND_NAMES or ("/" not in name and "." not in name)


def _follow(
    client: Any,
    session_id: str,
    feed: ui.StepFeed,
    *,
    timeout_s: float | None,
    from_index: int = 0,
    stop_at_tool_wait: bool = False,
) -> None:
    stop = threading.Event()
    threading.Thread(target=_poll_agents, args=(client, feed, stop), daemon=True).start()
    try:
        for event in stream_session(client, session_id, from_index=from_index, timeout_seconds=timeout_s):
            feed.handle(event)
            if stop_at_tool_wait and _awaits_tool_results(event):
                return
    finally:
        stop.set()


def _poll_agents(client: Any, feed: ui.StepFeed, stop: threading.Event) -> None:
    """Refresh spawned subagents' state: the parent emits nothing while it waits on them."""
    while not stop.wait(_AGENT_POLL_S):
        for session_id in feed.running_agents():
            try:
                status = client.sessions.get_session_status(session_id)
            except Exception:
                continue
            feed.agent_status(session_id, status.status, getattr(status, "steps", None))


def _awaits_tool_results(event: Any) -> bool:
    from hai_agents_common.jsonable import to_jsonable

    event = to_jsonable(event)
    data = event.get("data") if isinstance(event, dict) else None
    return (
        event.get("type") == "ActiveStateChangeEvent"
        and isinstance(data, dict)
        and data.get("state") == "awaiting_tool_results"
    )


def _custom_endpoint_host(state: AppState) -> str | None:
    from urllib.parse import urlparse

    base = credentials.resolve_base_url(state.base_url)
    if not base or base.rstrip("/") == HaiAgentsEnvironment.EU.value.rstrip("/"):
        return None
    return urlparse(base).netloc or base


def _local_client(state: AppState) -> Any:
    from hai_agents import Client

    _sign_in_if_needed(state)
    # The spawned runtime and the in-process bridges both read these from the environment.
    for var, value in ((credentials.API_KEY_VAR, state.api_key), (credentials.BASE_URL_VAR, state.base_url)):
        if value:
            os.environ[var] = value
    try:
        return Client.local()
    except (RuntimeError, ValueError, PermissionError) as exc:
        _raise_cli_error(exc)


def _arm_local_kill_switch() -> Any:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    from hai_agents_local.killswitch import KILL_SWITCH_UNAVAILABLE_HINT, arm_esc_listener

    listener = arm_esc_listener()
    if listener is None:
        err_console.print(f"[warn]{ui.ATTENTION}[/warn] {escape(KILL_SWITCH_UNAVAILABLE_HINT)}")
    return listener


def _kill_switch_fired(since: float) -> bool:
    from hai_agents_local.killswitch import StopSentinel

    return StopSentinel(since).stop_requested()


def _cancel_quietly(client: Any, session_id: str) -> None:
    try:
        client.sessions.cancel_session(session_id)
    except Exception:
        pass


@sessions_app.command("list")
def list_sessions(
    ctx: typer.Context,
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(10, "--size", min=1, max=100),
) -> None:
    """List visible sessions."""
    state = _state(ctx)
    client = _client(state)
    try:
        result: PageSessionSummary = client.sessions.list_sessions(page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)

    if state.json_output:
        _print_json(result)
        return

    # The ID column never shrinks: a truncated UUID cannot be pasted into follow-up commands.
    table = Table(Column("ID", min_width=36, no_wrap=True), "Status", "Agent", "Created")
    for item in result.items:
        url = getattr(item, "agent_view_url", None)
        id_cell = f"[link={url}]{item.id}[/link]" if url else item.id
        table.add_row(id_cell, _status_text(item.status), item.agent or "", item.created_at.isoformat())
    console.print(table)


@sessions_app.command("get")
def get(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Fetch a full session envelope."""
    client = _client(_state(ctx))
    try:
        result = client.sessions.get_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@sessions_app.command("cancel")
def cancel(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Cancel a session."""
    state = _state(ctx)
    if not yes and sys.stdin.isatty():
        typer.confirm(f"Cancel session {session_id}?", abort=True)
    client = _client(state)
    try:
        current = client.sessions.get_session_status(session_id)
        if is_settled_session_status(current.status):
            if state.json_output:
                _print_json({"ack": False, "action": "cancel", "status": _status_text(current.status)})
            else:
                console.print(f"Session already {_status_text(current.status)}; nothing to cancel.")
            return
        client.sessions.cancel_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("cancelled", state.json_output)


@sessions_app.command("send")
def send(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    message: str = typer.Argument(..., help="Message text to send."),
) -> None:
    """Send a follow-up message to a session."""
    state = _state(ctx)
    client = _client(state)
    request = SendSessionMessagesRequestBody_UserMessage(message=message)
    try:
        client.sessions.send_session_messages(session_id, request=request)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("sent", state.json_output)


@sessions_app.command("share")
def share(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Create or fetch a public share URL."""
    state = _state(ctx)
    client = _client(state)
    try:
        share_url = absolute_share_url(client, client.sessions.share_session(session_id).share_url)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json({"share_url": share_url})
    else:
        print(share_url)


@sessions_app.command("unshare")
def unshare(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Revoke a session's public share URL."""
    state = _state(ctx)
    client = _client(state)
    try:
        client.sessions.unshare_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("unshared", state.json_output)


@sessions_app.command("status")
def status(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Show a session's live status, step count, and error if any."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.sessions.get_session_status(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Field", "Value", show_header=False)
    table.add_row("Status", _status_text(result.status))
    if result.steps is not None:
        table.add_row("Steps", str(result.steps))
    if result.error:
        table.add_row("Error", escape(result.error))
    console.print(table)


@sessions_app.command("events")
def events(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    from_index: int = typer.Option(0, "--from-index", min=0, help="Skip events before this index."),
    wait: int = typer.Option(0, "--wait", min=0, max=60, help="Long-poll up to N seconds for new events."),
) -> None:
    """Print a session's trajectory events from an index."""
    state = _state(ctx)
    client = _client(state)
    try:
        changes = client.sessions.get_session_changes(
            session_id, from_index=from_index, include_events=True, wait_for_seconds=wait
        )
    except Exception as exc:
        _raise_cli_error(exc)
    new_events = (changes.new_events if changes else None) or []
    if state.json_output:
        _print_json(new_events)
        return
    if not new_events:
        console.print("[dim]No new events.[/dim]")
        return
    for offset, event in enumerate(new_events):
        console.print(_event_line(from_index + offset, event))


@sessions_app.command("watch")
def watch(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    timeout: float = typer.Option(300.0, "--timeout", min=1.0, help="Stop watching after N seconds."),
) -> None:
    """Stream a session's events live until it settles."""
    state = _state(ctx)
    client = _client(state)
    if not state.json_output:
        _watch_human(client, session_id, timeout)
        return
    try:
        for event in stream_session(client, session_id, timeout_seconds=timeout):
            _emit_watch_event(event)
        current = client.sessions.get_session_status(session_id)
        # The terminal answer lives on /changes, not /status.
        final = client.sessions.get_session_changes(session_id, from_index=0, include_events=False, wait_for_seconds=0)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_watch_result(current, final)


def _watch_human(client: Any, session_id: str, timeout: float) -> None:
    ui.header(err_console, "holo", ["watching", session_id])
    feed = ui.StepFeed(err_console)
    try:
        _follow(client, session_id, feed, timeout_s=timeout)
        current = client.sessions.get_session_status(session_id)
        final = client.sessions.get_session_changes(session_id, from_index=0, include_events=False, wait_for_seconds=0)
    except KeyboardInterrupt:
        feed.close()
        raise typer.Exit(130) from None
    except Exception as exc:
        feed.close()
        _raise_cli_error(exc)
    feed.close()
    status = _status_text(current.status)
    answer = feed.answer if feed.answer is not None else getattr(final, "answer", None)
    if answer is not None:
        ui.print_answer(console, answer)
        err_console.print()
    error_text = _error_line(current.error, current.error_code)
    ui.summary(err_console, status, feed, error_text=error_text, answered=getattr(current, "outcome", None))
    _exit_unless_clean(current.status)


@agents_app.command("list")
def list_agents_command(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search", help="Match on agent name or description."),
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(20, "--size", min=1, max=100),
) -> None:
    """List reserved and org agents."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.agents.list_agents(search=search, page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Name", "Description")
    for item in result.items:
        table.add_row(item.name, escape(_truncate(item.description)))
    console.print(table)


@agents_app.command("use")
def use_agent_command(ctx: typer.Context, agent_name: str = typer.Argument(...)) -> None:
    """Set the default agent for `holo run` and `holo chat`."""
    path = _save_default_agent(_client(_state(ctx)), agent_name)
    ui.ok(console, f"default agent {agent_name} {ui.SEP} saved to {path}")


@agents_app.command("get")
def get_agent_command(
    ctx: typer.Context,
    agent_name: str = typer.Argument(...),
    resolve: bool = typer.Option(False, "--resolve", help="Resolve inherited fields."),
) -> None:
    """Fetch a single agent definition."""
    client = _client(_state(ctx))
    try:
        result = client.agents.get_agent(agent_name, resolve=resolve)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@skills_app.command("list")
def list_skills_command(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search", help="Match on skill name or description."),
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(20, "--size", min=1, max=100),
) -> None:
    """List available skills."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.skills.list_skills(search=search, page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Name", "Description")
    for item in result.items:
        table.add_row(item.name, escape(_truncate(item.description)))
    console.print(table)


@skills_app.command("get")
def get_skill_command(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    """Fetch a single skill definition."""
    client = _client(_state(ctx))
    try:
        result = client.skills.get_skill(name)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@mcp_app.command("install")
def mcp_install(
    ctx: typer.Context,
    client: str = typer.Argument(
        None, help="Client id (cursor, vscode, ...), 'list' to enumerate, or omit to wire every detected client."
    ),
    url: str = typer.Option(None, "--url", help="MCP endpoint. Defaults to your --base-url region or the EU host."),
) -> None:
    """Wire the hai-agents MCP server into local clients (writes your API key into each config in plaintext)."""
    state = _state(ctx)
    if client == "list":
        _mcp_list(state.json_output)
        return

    if client is None:
        targets = [(cid, c) for cid, c in mcp_hosts.CLIENTS.items() if mcp_hosts.host_present(c)]
        if not targets:
            _raise_cli_error(RuntimeError("No supported MCP clients detected. Run `holo mcp install list`."))
    elif client in mcp_hosts.CLIENTS:
        targets = [(client, mcp_hosts.CLIENTS[client])]
    else:
        _raise_cli_error(RuntimeError(f"Unknown client {client!r}. Run `holo mcp install list` to see supported ids."))

    _sign_in_if_needed(state)
    try:
        resolved = credentials.resolve_api_key(state.api_key)
        key = resolved() if callable(resolved) else resolved
    except RuntimeError as exc:
        _raise_cli_error(exc)
    server_url = mcp_hosts.resolve_mcp_url(credentials.resolve_base_url(state.base_url), url)

    results = [_install_one(cid, c, server_url, key) for cid, c in targets]
    _print_mcp_results(results, server_url, state.json_output)
    if any(r["status"].fatal or (r["skill"] and r["skill"][0].fatal) for r in results):
        raise typer.Exit(1)


def _install_one(cid: str, c: mcp_hosts.Client, url: str, key: str) -> dict:
    status, detail = mcp_hosts.wire_mcp(c, {mcp_hosts.URL: url, mcp_hosts.KEY: key}, secret=key)
    skill = mcp_hosts.wire_skill(c, mcp_hosts.SERVER_NAME, mcp_hosts.bundled_skill()) if c.skills_dir else None
    return {"client": cid, "status": status, "detail": detail, "skill": skill}


def _mcp_list(json_output: bool) -> None:
    rows = [(cid, mcp_hosts.host_present(c), mcp_hosts.host_target(c)) for cid, c in mcp_hosts.CLIENTS.items()]
    if json_output:
        _print_json({cid: {"detected": detected, "target": tgt} for cid, detected, tgt in rows})
        return
    table = Table("Client", "Detected", "Config")
    for cid, detected, tgt in rows:
        table.add_row(cid, "[green]yes[/green]" if detected else "[dim]no[/dim]", tgt)
    console.print(table)
    console.print(
        "[dim]Wire one with[/dim] [cyan]holo mcp install <id>[/cyan][dim], or all detected with[/dim] [cyan]holo mcp install[/cyan]."
    )


_MCP_GLYPH: dict[mcp_hosts.Status, str] = {
    mcp_hosts.Status.INSTALLED: f"[ok]{ui.DONE}[/ok]",
    mcp_hosts.Status.SKIPPED: f"[meta]{ui.DONE}[/meta]",
    mcp_hosts.Status.ABSENT: f"[meta]{ui.SEP}[/meta]",
    mcp_hosts.Status.FAILED: f"[fail]{ui.FAILED}[/fail]",
}


def _print_mcp_results(results: list[dict], server_url: str, json_output: bool) -> None:
    if json_output:
        _print_json(
            {
                "url": server_url,
                "results": [
                    {
                        "client": r["client"],
                        "status": r["status"].value,
                        "detail": r["detail"],
                        "skill": ({"status": r["skill"][0].value, "detail": r["skill"][1]} if r["skill"] else None),
                    }
                    for r in results
                ],
            }
        )
        return
    for r in results:
        line = f"  {_MCP_GLYPH[r['status']]} [key]{r['client']:<14}[/key] [meta]{escape(r['detail'])}[/meta]"
        if r["skill"] and r["skill"][0].ok:
            line += f"  [meta]+ skill {escape(r['skill'][1])}[/meta]"
        elif r["skill"]:
            line += f"  {_MCP_GLYPH[r['skill'][0]]} [meta]skill: {escape(r['skill'][1])}[/meta]"
        console.print(line)
    console.print(f"\n  [meta]server[/meta] {server_url}")
    console.print(
        f"  [warn]{ui.ATTENTION}[/warn] your API key was written into these configs in plaintext; keep them private"
    )


@local_app.command("browser")
def local_browser(
    ctx: typer.Context,
    session_id: str | None = typer.Option(None, "--session-id", help="Session id to serve. Generated when omitted."),
    debug_port: int = typer.Option(9222, "--debug-port", help="Chrome remote-debugging port to attach to."),
) -> None:
    """Serve browser commands on this machine through Chrome on --debug-port."""
    from hai_agents_local import SeleniumBrowserBridge

    _run_bridge(_state(ctx), SeleniumBrowserBridge, session_id, debugging_port=debug_port)


@local_app.command("desktop")
def local_desktop(
    ctx: typer.Context,
    session_id: str | None = typer.Option(None, "--session-id", help="Session id to serve. Generated when omitted."),
    max_width: int = typer.Option(
        desktop_defaults.DEFAULT_MAX_WIDTH, "--max-width", help="Cap screenshot width in pixels. 0 disables."
    ),
    max_height: int = typer.Option(0, "--max-height", help="Cap screenshot height in pixels. 0 disables."),
    image_format: str = typer.Option(
        desktop_defaults.DEFAULT_IMAGE_FORMAT, "--image-format", help="Screenshot encoding: png, jpeg, or webp."
    ),
    quality: int = typer.Option(
        desktop_defaults.DEFAULT_QUALITY, "--quality", help="Encoding quality (1-100) for jpeg/webp."
    ),
) -> None:
    """Serve desktop commands on this machine's mouse, keyboard, and screen."""
    from hai_agents_local import PyautoguiDesktopBridge

    if image_format not in ("png", "jpeg", "webp"):
        _raise_cli_error(ValueError(f"--image-format must be png, jpeg, or webp; got {image_format!r}"))
    _run_bridge(
        _state(ctx),
        PyautoguiDesktopBridge,
        session_id,
        max_width=max_width or None,
        max_height=max_height or None,
        image_format=image_format,
        quality=quality,
    )


@local_app.command("workstation")
def local_workstation(
    ctx: typer.Context,
    session_id: str | None = typer.Option(None, "--session-id", help="Session id to serve. Generated when omitted."),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Folder the shell starts in. Defaults to ~/hai/<session id>."
    ),
) -> None:
    """Serve workstation commands: a shell on this machine, running as you, that drives its screen and a Chrome."""
    from hai_agents_local import WorkstationBridge

    _run_bridge(_state(ctx), WorkstationBridge, session_id, workspace=workspace)


@local_app.command("stop")
def local_stop() -> None:
    """Stop any in-flight local browser/desktop turn on this machine (same effect as double-Esc)."""
    from hai_agents_local.killswitch import request_stop

    request_stop()
    console.print(
        "Stop requested: local bridges on this machine will halt, and SDK-attached sessions will be cancelled."
    )


def _run_bridge(state: AppState, bridge_type: type[LocalBridge], session_id: str | None, **options: Any) -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _sign_in_if_needed(state)
    try:
        bridge = bridge_type(
            api_key=credentials.resolve_api_key(state.api_key),
            base_url=credentials.resolve_base_url(state.base_url),
            session_id=session_id,
            **options,
        )
        bridge.preflight()
    except (RuntimeError, ValueError, PermissionError) as exc:
        _raise_cli_error(exc)

    console.print(
        f"[bold]Local {bridge.environment_kind} bridge[/bold] serving session id "
        f"[cyan]{bridge.session_id}[/cyan]. Press Ctrl-C to stop, or run `holo local stop` from any terminal."
    )
    console.print(
        "[dim]Point a user_device environment at it: "
        f'{{"kind": "{bridge.environment_kind}", "host": "user_device", "session_id": "{bridge.session_id}"}}[/dim]'
    )
    try:
        asyncio.run(_serve_bridge(bridge))
    except KeyboardInterrupt:
        console.print("Stopped.")
        return
    except Exception as exc:
        _raise_cli_error(exc)
    if not bridge.ready.is_set():
        _raise_cli_error(RuntimeError("the bridge was stopped during setup and never served"))


async def _serve_bridge(bridge: Any) -> None:
    import signal

    from hai_agents_local.killswitch import StopWatcher

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bridge.request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    watcher = StopWatcher(lambda: loop.call_soon_threadsafe(bridge.request_stop))
    listener = _arm_kill_switch(bridge)
    try:
        await bridge.run()
    finally:
        watcher.stop()
        if listener is not None:
            listener.stop()


def _arm_kill_switch(bridge: Any) -> Any:
    """Arm the double-Esc listener for desktop serving; a desktop turn steals focus, so Ctrl-C may be out of reach."""
    if bridge.environment_kind not in ("desktop", "workstation") or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    from hai_agents_local.killswitch import KILL_SWITCH_ARMED_HINT, KILL_SWITCH_UNAVAILABLE_HINT, arm_esc_listener

    listener = arm_esc_listener()
    if listener is not None:
        console.print(f"[dim]{KILL_SWITCH_ARMED_HINT}[/dim]")
    else:
        # A panic button that silently failed to arm is dangerous; always say so.
        console.print(f"[yellow]{KILL_SWITCH_UNAVAILABLE_HINT}[/yellow]")
    return listener


app.add_typer(sessions_app, name="sessions")
app.add_typer(agents_app, name="agents")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")
app.add_typer(local_app, name="local")


_GLOBAL_FLAGS = ("--json",)
_GLOBAL_OPTIONS = ("--api-key", "--base-url")
_HELP_FLAGS = ("--help", "--install-completion", "--show-completion")
_CHAT_FLAGS = ("--local",)
_CHAT_OPTIONS = ("--agent", "-a")


def _only_chat_options(args: list[str]) -> bool:
    i = 0
    while i < len(args):
        name, has_value, _ = args[i].partition("=")
        if args[i] in _CHAT_FLAGS or (has_value and name in _CHAT_OPTIONS):
            i += 1
        elif args[i] in _CHAT_OPTIONS and i + 1 < len(args):
            i += 2
        else:
            return False
    return True


def route(argv: list[str], commands: set[str], interactive: bool) -> list[str]:
    """`holo "task"` runs it, plain `holo` opens a prompt, and global options work in any position."""
    head: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            rest += argv[i:]
            break
        if arg in _GLOBAL_FLAGS or arg.split("=", 1)[0] in _GLOBAL_OPTIONS and "=" in arg:
            head.append(arg)
        elif arg in _GLOBAL_OPTIONS and i + 1 < len(argv):
            head += argv[i : i + 2]
            i += 1
        else:
            rest.append(arg)
        i += 1
    if not rest or (interactive and _only_chat_options(rest)):
        return head + (["chat", *rest] if interactive else [])
    first = rest[0]
    if first in commands or first in _HELP_FLAGS:
        return head + rest
    a_word = not first.startswith("-") and " " not in first
    if a_word and (len(rest) == 1 or difflib.get_close_matches(first, commands, n=1, cutoff=0.75)):
        return head + rest
    return head + ["run", *rest]


def main() -> None:
    commands = set(typer.main.get_command(app).commands)  # type: ignore[attr-defined]
    app(args=route(sys.argv[1:], commands, _interactive()), prog_name="holo")


def _state(ctx: typer.Context) -> AppState:
    if not isinstance(ctx.obj, AppState):
        raise RuntimeError("CLI state was not initialized.")
    return ctx.obj


def _client(state: AppState) -> Client:
    _sign_in_if_needed(state)
    try:
        return make_client(api_key=state.api_key, base_url=state.base_url)
    except RuntimeError as exc:
        _raise_cli_error(exc)


def _choose(rows: list[tuple[str, str]], headers: dict[int, str] | None = None, current: int = 0) -> int:
    """The row picked with the arrow keys; cancelling raises typer.Exit."""
    from hai_agents_cli.prompt import choose

    picked = choose(rows, headers, current)
    if picked is None:
        raise typer.Exit(1)
    return picked


def _pick_agent(client: Client, current: str | None = None) -> str:
    """Pick an agent: H's agents first, then your organization's."""
    try:
        listed = client.agents.list_agents(page=1, size=100).items
    except Exception as exc:
        _raise_cli_error(exc)
    if not listed:
        _raise_cli_error(RuntimeError("No agents available."))
    h_agents = [item for item in listed if item.name.startswith("h/")]
    agents = h_agents + [item for item in listed if not item.name.startswith("h/")]
    headers = {}
    if h_agents:
        headers[0] = "H agents"
    if len(agents) > len(h_agents):
        headers[len(h_agents)] = "Your organization"
    rows = [(item.name, _truncate(" ".join((item.description or "").split()))) for item in agents]
    names = [item.name for item in agents]
    return agents[_choose(rows, headers, names.index(current) if current in names else 0)].name


def _pick_session(recent: list[Any], arg: str) -> Any:
    """A session by list number or id prefix; with no argument, pick one with the arrow keys."""
    if not arg:
        items = [welcome.activity(summary) for summary in recent]
        rows = [
            (_truncate(item.task, 60), f" {ui.SEP} ".join(filter(None, [item.status, item.age, summary.agent])))
            for item, summary in zip(items, recent)
        ]
        return recent[_choose(rows)]
    if arg.isdigit() and 1 <= int(arg) <= len(recent):
        return recent[int(arg) - 1]
    matches = [summary for summary in recent if str(summary.id).startswith(arg)]
    if len(matches) != 1:
        ui.error(err_console, f"no single recent session matches {arg!r}", fix="/resume lists them")
        raise typer.Exit(1)
    return matches[0]


def _local_kinds(client: Any, agent: Any) -> list[str]:
    from hai_agents_local.sessions import local_environment_kinds

    try:
        return local_environment_kinds(client, agent)
    except Exception:
        return []


def _drives_a_machine(client: Any, agent: Any) -> bool:
    """Read-back specs carry their bridges' session ids, which `_local_kinds` skips, so scan for the host too."""
    return _has_user_device(to_jsonable(agent)) or bool(_local_kinds(client, agent))


def _has_user_device(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("host") == "user_device" or any(map(_has_user_device, value.values()))
    return isinstance(value, list) and any(map(_has_user_device, value))


_CLIPBOARD_TOOLS = (
    ("pbcopy",),
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
    ("xsel", "--clipboard", "--input"),
    ("clip",),
)


def _to_clipboard(text: str) -> bool:
    for command in _CLIPBOARD_TOOLS:
        if shutil.which(command[0]):
            data = text.encode("utf-16" if command[0] == "clip" else "utf-8")
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(command, input=data, check=True, timeout=5)
                return True
    return False


def _save_default_agent(client: Client, name: str) -> Any:
    """Check the agent exists, then store it as the default."""
    try:
        client.agents.get_agent(name)
    except Exception as exc:
        _raise_cli_error(exc)
    return credentials.save_default_agent(name)


def _print_run_result(
    result,
    json_output: bool,
    agent_view_url: str | None = None,
    feed: ui.StepFeed | None = None,
    stopped: bool = False,
    show_session_id: bool = True,
) -> None:
    payload = {
        "session_id": result.id,
        "status": _status_text(result.status),
        "answer": result.answer,
        "outcome": result.outcome,
        "error": result.error,
        "error_code": result.error_code,
        "agent_view_url": agent_view_url,
    }
    if json_output:
        _print_json(payload)
        return
    status = _status_text(result.status)
    answer = feed.answer if feed is not None and feed.answer is not None else result.answer
    if answer is not None:
        ui.print_answer(console, answer)
    error_text = _error_line(result.error, result.error_code)
    if _awaits_tools(result):
        error_text = "the agent is waiting on client-side tools the CLI cannot run; drive it from the SDK with tools"
    if stopped:
        error_text = "stopped by the kill switch"
    if feed is not None:
        if answer is not None:
            err_console.print()
        session_id = result.id if show_session_id else None
        ui.summary(err_console, status, feed, error_text=error_text, session_id=session_id, answered=result.outcome)
    elif error_text or status not in CLEAN_STATUSES:
        ui.error(err_console, error_text or f"session {status}")


def _awaits_tools(result) -> bool:
    """The CLI cannot run client-side tools, so a session waiting on them can never progress."""
    return _status_text(result.status) == "awaiting_tool_results"


def _error_line(error: str | None, error_code: str | None) -> str | None:
    if not error:
        return None
    return f"{error} ({error_code})" if error_code else error


def _exit_unless_clean(status) -> None:
    if status not in CLEAN_STATUSES:
        raise typer.Exit(1)


def _print_ack(action: str, json_output: bool) -> None:
    if json_output:
        _print_json({"ack": True, "action": action})
    else:
        console.print(action)


def _print_json(value) -> None:
    # Emit raw JSON to stdout; rich's Console would soft-wrap and corrupt long values.
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


def _print_watch_result(status_result, final) -> None:
    print(json.dumps(to_jsonable(final if final is not None else status_result), sort_keys=True))
    _exit_unless_clean(status_result.status)


def _status_text(status) -> str:
    return str(status)


def _truncate(text: str | None, limit: int = 80) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _event_line(index: int, event) -> str:
    event_type = getattr(event, "type", "Event")
    data = getattr(event, "data", None)
    detail = _truncate(json.dumps(to_jsonable(data), sort_keys=True), 120) if data is not None else ""
    return f"[dim]{index:>4}[/dim] [cyan]{event_type}[/cyan]" + (f"  {escape(detail)}" if detail else "")


def _emit_watch_event(event) -> None:
    print(json.dumps(to_jsonable(event), sort_keys=True))


def _format_api_body(body) -> str:
    """Human-readable message from an API error body, flattening 422 validation detail."""
    if isinstance(body, str):
        return body
    message = body.get("message") if isinstance(body, dict) else getattr(body, "message", None)
    if isinstance(message, str):
        return message
    detail = getattr(body, "detail", None)
    if detail is None and isinstance(body, dict):
        detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            loc = getattr(item, "loc", None) if not isinstance(item, dict) else item.get("loc")
            msg = getattr(item, "msg", None) if not isinstance(item, dict) else item.get("msg")
            if msg:
                where = ".".join(str(p) for p in loc) if loc else ""
                parts.append(f"{where}: {msg}" if where else str(msg))
        if parts:
            return "; ".join(parts)
    return json.dumps(to_jsonable(body), sort_keys=True)


def _raise_cli_error(exc: Exception) -> NoReturn:
    fix = None
    if isinstance(exc, ApiError):
        message = _format_api_body(exc.body)
        if exc.status_code is not None:
            message = f"API error {exc.status_code}: {message}"
        if exc.status_code in (401, 403):
            fix = "holo login --force"
    else:
        message = str(exc)
    ui.error(err_console, message, fix=fix)
    raise typer.Exit(1)
