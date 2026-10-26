"""How the step feed names a tool call: `label(tool_req)` is a `(verb, target)` pair, shown as `Verb target`."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

Label = tuple[str, str]
Rule = Callable[[dict[str, Any]], Label]

_MCPORTER_CALL = re.compile(r"^mcporter\s+call\s+([\w-]+)\.([\w-]+)")
_SHORT_CVC = re.compile(r"^[^aeiou][^aeiou]?[aeiou][^aeiouwxy]$")
_GERUNDS = {"back": "going back", "forget": "forgetting"}


def label(req: dict[str, Any]) -> Label:
    name = str(req.get("tool_name") or "tool")
    args = req.get("args")
    args = args if isinstance(args, dict) else {}
    rule = _RULES.get(name)
    return rule(args) if rule else _fallback(name, args)


def busy(req: dict[str, Any]) -> str:
    """Spinner text while the call runs; a custom tool's name is not a verb, so it just runs."""
    return gerund(label(req)[0]) if req.get("tool_name") in _RULES else "Running"


def gerund(verb: str) -> str:
    """`type` -> `Typing`, `stop` -> `Stopping`, `load skill` -> `Loading skill`."""
    word, sep, rest = verb.lower().partition(" ")
    if word in _GERUNDS:
        word = _GERUNDS[word]
    elif word.endswith("e") and not word.endswith("ee"):
        word = f"{word[:-1]}ing"
    elif _SHORT_CVC.match(word):
        word = f"{word}{word[-1]}ing"
    else:
        word = f"{word}ing"
    return f"{word}{sep}{rest}".capitalize()


def short_url(url: Any) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    host = parsed.netloc.removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}" if host else str(url)


def _text(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _quoted(args: dict[str, Any], *keys: str) -> str:
    text = _text(args, *keys)
    return f'"{text}"' if text and '"' not in text else text


def _url(args: dict[str, Any], key: str = "url") -> str:
    return short_url(_text(args, key)) or ""


def _point(args: dict[str, Any]) -> str:
    if element := _text(args, "element"):
        return element
    return f"{args['x']}, {args['y']}" if "x" in args and "y" in args else ""


def _in(what: str, args: dict[str, Any]) -> str:
    where = _text(args, "element")
    return f"{what} in {where}" if what and where else what or where


def _names(values: Any, limit: int = 2) -> str:
    names = [str(value) for value in values] if isinstance(values, list) else []
    shown = ", ".join(names[:limit])
    return f"{shown} and {len(names) - limit} more" if len(names) > limit else shown


def _keys(args: dict[str, Any], key: str = "keys") -> str:
    value = args.get(key)
    return "+".join(map(str, value)) if isinstance(value, list) else _text(args, key)


def _seconds(args: dict[str, Any]) -> str:
    seconds = args.get("seconds")
    return f"{seconds}s" if isinstance(seconds, (int, float)) else ""


def _basename(path: Any) -> str:
    return str(path).rstrip("/").rsplit("/", 1)[-1]


def _with(verb: str, target: Callable[[dict[str, Any]], str] = lambda args: "") -> Rule:
    return lambda args: (verb, target(args))


def _switch_tab(args: dict[str, Any]) -> Label:
    if tab := _text(args, "tab_id"):
        return "switch tab", tab
    return "open tab", _url(args)


def _scroll(args: dict[str, Any]) -> Label:
    nested = args.get("scroll_element")
    element = _text(nested, "element") if isinstance(nested, dict) else _text(args, "element")
    direction = _text(args, "direction")
    return "scroll", f"{direction} on {element}" if direction and element else direction or element


def _hotkey(args: dict[str, Any]) -> Label:
    repeat = args.get("repeat_count")
    keys = _keys(args)
    return "press", f"{keys} ×{repeat}" if keys and isinstance(repeat, int) and repeat > 1 else keys


def _hold_and_tap(args: dict[str, Any]) -> Label:
    held, tapped = _keys(args, "hold_keys"), _keys(args, "tap_keys")
    return "press", "+".join(part for part in (held, tapped) if part)


def _fill_secret(args: dict[str, Any]) -> Label:
    return "fill secret", _in(_text(args, "field"), args)


def _switch_chunk(args: dict[str, Any]) -> Label:
    chunks = args.get("n_chunks")
    chunks = chunks if isinstance(chunks, int) else 1
    if chunks < 0:
        return "read", f"back {-chunks} section" + ("s" if chunks < -1 else "")
    return "read", "next section" if chunks == 1 else f"next {chunks} sections"


def _command(args: dict[str, Any]) -> Label:
    command = _text(args, "command")
    if call := _MCPORTER_CALL.match(command):
        server, tool = call.groups()
        return "call", f"{server} {tool.removeprefix(f'{server}_')}"
    return "run", command


def _execution(verb: str) -> Rule:
    return lambda args: (verb, "" if _text(args, "execution_id") in ("", "last") else _text(args, "execution_id"))


def _zoom(args: dict[str, Any]) -> Label:
    factor = args.get("zoom_factor")
    at = f"{args['x']}, {args['y']}" if "x" in args and "y" in args else ""
    return "zoom", f"{at} ×{factor}" if at and factor else at


def _spawn(args: dict[str, Any]) -> Label:
    what = _text(args, "task_summary") or _text(args, "task")
    who = _text(args, "agent_id") or _text(args, "agent_type")
    return "spawn", f"{who}: {what}" if who and what else who or what


def _sleep(args: dict[str, Any]) -> Label:
    return "wait for", _names(args.get("wait_for_ids")) or ("any agent" if args.get("wait_for_any") else "")


def _plan(args: dict[str, Any]) -> Label:
    goals = [goal for goal in args.get("goals") or [] if isinstance(goal, dict)]
    running = next((_text(goal, "title") for goal in goals if goal.get("status") == "running"), "")
    return "plan", f"→ {running}" if running else (
        f"{len(goals)} goal" + ("s" if len(goals) != 1 else "") if goals else ""
    )


def _connector_call(args: dict[str, Any]) -> Label:
    connector, tool = _text(args, "connector"), _text(args, "tool")
    return "call", f"{connector} {tool}" if connector and tool else connector or tool


def _fallback(name: str, args: dict[str, Any]) -> Label:
    """Custom and MCP tools: the name in words, and the first text argument."""
    first = next((value for value in args.values() if isinstance(value, str) and value.strip()), "")
    return " ".join(re.sub(r"[_-]", " ", name).split()).lower(), " ".join(first.split())


_RULES: dict[str, Rule] = {
    "answer": _with("answer"),
    "update_plan": _plan,
    "note": _with("note", lambda args: _quoted(args, "note", "content")),
    "load_skill": _with("load skill", lambda args: _text(args, "name")),
    "web_search": _with("search", lambda args: _quoted(args, "query")),
    "web_fetch": _with("fetch", _url),
    "go_to_web": _with("navigate", _url),
    "go_back_web": _with("back"),
    "refresh_web": _with("refresh"),
    "switch_tab_web": _switch_tab,
    "close_tab_web": _with("close tab", lambda args: _text(args, "tab_id")),
    "scroll_web": _scroll,
    "press_keys_web": _with("press", _keys),
    "ctrl_f_web": _with("find", lambda args: _quoted(args, "query")),
    "find_in_page": _with("find", lambda args: _quoted(args, "query")),
    "switch_chunk": _switch_chunk,
    "click_web": _with("click", _point),
    "write": _with("type", lambda args: _in(_quoted(args, "text"), args)),
    "move_mouse_web": _with("hover", _point),
    "drag_and_drop_web": _with("drag", lambda args: _text(args, "description")),
    "select_option": _with("select", lambda args: _in(_quoted(args, "option"), args)),
    "wait_web": _with("wait", _seconds),
    "list_secrets": _with("list secrets"),
    "fill_secret_at": _fill_secret,
    "list_files_web": _with("list", lambda args: _text(args, "path")),
    "read_file_web": _with("read", lambda args: _text(args, "path")),
    "upload_file_web": _with("upload", lambda args: _text(args, "path")),
    "write_file_web": _with("write", lambda args: _text(args, "path")),
    "click_desktop": _with("click", _point),
    "double_click_desktop": _with("double-click", _point),
    "write_desktop": _with("type", lambda args: _quoted(args, "content")),
    "write_at_desktop": _with("type", lambda args: _in(_quoted(args, "content"), args)),
    "hotkey_desktop": _hotkey,
    "move_to_desktop": _with("hover", _point),
    "drag_and_drop": _with("drag", lambda args: _text(args, "description")),
    "scroll_desktop": _scroll,
    "key_down_desktop": _with("hold", lambda args: _text(args, "key")),
    "key_up_desktop": _with("release", lambda args: _text(args, "key")),
    "hold_and_tap_key_desktop": _hold_and_tap,
    "run_command_desktop": _command,
    "wait_desktop": _with("wait", _seconds),
    "zoom_desktop": _zoom,
    "shell": _command,
    "poll_execution": _execution("read output"),
    "send_execution_input": _with("send input", lambda args: _quoted(args, "data")),
    "terminate_execution": _execution("stop"),
    "read_file": _with("read", lambda args: _text(args, "path")),
    "write_file": _with("write", lambda args: _text(args, "path")),
    "search_replace": _with("edit", lambda args: _text(args, "file_path", "path")),
    "view_image": _with("view", lambda args: _url(args, "source")),
    "share_files": _with("share", lambda args: _names([_basename(p) for p in args.get("paths") or []], 3)),
    "mobile_click": _with("tap", _point),
    "mobile_long_press": _with("long-press", _point),
    "mobile_write": _with("type", lambda args: _in(_quoted(args, "text"), args)),
    "mobile_scroll": _with("scroll", lambda args: _text(args, "direction")),
    "mobile_swipe": _with("swipe"),
    "mobile_drag": _with("drag", _point),
    "mobile_launch_app": _with("launch", lambda args: _text(args, "package_name")),
    "mobile_get_logs": _with("read logs"),
    "mobile_wait": _with("wait", _seconds),
    "mobile_go_back": _with("back"),
    "mobile_go_home": _with("go home"),
    "mobile_go_to_all_apps": _with("open app list"),
    "mobile_copy_to_clipboard": _with("copy"),
    "mobile_paste_from_clipboard": _with("paste"),
    "mobile_hide_keyboard": _with("hide keyboard"),
    "set_memory": _with("remember", lambda args: _text(args, "key")),
    "get_memory": _with("recall", lambda args: _text(args, "key")),
    "delete_memory": _with("forget", lambda args: _text(args, "key")),
    "list_memories": _with("list memories", lambda args: _text(args, "prefix")),
    "spawn": _spawn,
    "sleep": _sleep,
    "connector_tools": _with("list tools", lambda args: _text(args, "connector")),
    "connector_call": _connector_call,
}
