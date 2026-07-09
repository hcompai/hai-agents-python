"""Prebuilt OTP tool: hand the agent one-time passwords, verification codes, and confirmation links.

The agent calls :func:`otp_tool` when a login or verification step asks for a code or
link sent out of band; the handler resolves it -- interactively on stdin by default, or
straight from a mailbox with :func:`imap_otp_handler`.
"""

from __future__ import annotations

import html
import inspect
import re
import time
import typing
from dataclasses import dataclass

from hai_agents.tools import Tool

# Public surface, re-exported by the tools package __init__ (enforced by the SDK tests).
__all__ = [
    "OTP_TOOL_DESCRIPTION",
    "OTP_TOOL_INPUT_SCHEMA",
    "OTP_TOOL_NAME",
    "OtpHandler",
    "OtpRequest",
    "extract_otp",
    "imap_otp_handler",
    "otp_tool",
]

OTP_TOOL_NAME = "request_otp"

OTP_TOOL_DESCRIPTION = (
    "Ask the human operator for a one-time password (OTP), verification code, or "
    "confirmation link. Use this whenever a login, signup, or verification step "
    "asks for a code or link that was sent to the user out of band (email, SMS, "
    "or an authenticator app). Never guess or fabricate a code: call this tool "
    "and wait for the value."
)

OTP_TOOL_INPUT_SCHEMA: typing.Dict[str, typing.Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "Message shown to the user explaining exactly what is needed, "
                "e.g. 'Enter the 6-digit code sent to j***@example.com'."
            ),
        },
        "kind": {
            "type": "string",
            "enum": ["code", "link"],
            "default": "code",
            "description": "Whether a code (numeric or alphanumeric) or a full confirmation URL is expected.",
        },
        "source": {
            "type": "string",
            "description": "Where the code or link was sent, e.g. 'email', 'sms', 'authenticator app'.",
        },
    },
    "required": ["prompt"],
}


@dataclass(frozen=True)
class OtpRequest:
    """One OTP request from the agent, passed to the :func:`otp_tool` handler."""

    prompt: str
    kind: str = "code"  # "code" or "link"
    source: typing.Optional[str] = None


OtpHandler = typing.Callable[[OtpRequest], typing.Union[str, typing.Awaitable[str]]]


def _default_otp_handler(request: OtpRequest) -> str:
    """Interactive fallback: prompt for the value on stdin."""
    label = "link" if request.kind == "link" else "code"
    message = request.prompt
    if request.source:
        message += f" (sent via {request.source})"
    return input(f"{message}\nEnter the {label}: ")


def _validated_otp(value: str, kind: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"No {'link' if kind == 'link' else 'code'} was provided.")
    return value


async def _await_validated_otp(value: typing.Awaitable[str], kind: str) -> str:
    return _validated_otp(await value, kind)


def otp_tool(
    handler: typing.Optional[OtpHandler] = None,
    *,
    name: str = OTP_TOOL_NAME,
    description: str = OTP_TOOL_DESCRIPTION,
) -> Tool:
    """A ready-made custom tool the agent calls when it needs an OTP, verification code, or confirmation link.

    ``handler`` receives an :class:`OtpRequest` and returns the value the user supplied
    (it may be async: fetch the code from an inbox API, a Slack prompt, ...). Without a
    handler, the tool prompts interactively on stdin.

    Usage::

        handler = imap_otp_handler(
            host="imap.gmail.com",
            username="agent-inbox@gmail.com",
            password=os.environ["GMAIL_APP_PASSWORD"],  # Google app password
        )
        client.run_session(agent="surfer", messages="Log in to example.com", tools=[otp_tool(handler)])
    """
    resolved = handler or _default_otp_handler

    def run(prompt: str, kind: str = "code", source: typing.Optional[str] = None) -> typing.Any:
        result = resolved(OtpRequest(prompt=prompt, kind=kind, source=source))
        if inspect.isawaitable(result):
            return _await_validated_otp(result, kind)
        return _validated_otp(result, kind)

    return Tool(name=name, description=description, input_schema=OTP_TOOL_INPUT_SCHEMA, fn=run)


_OTP_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_OTP_LINK_HINT = re.compile(
    r"verify|confirm|activat|validat|sign-?in|log-?in|magic|authenticat|authoriz"
    r"|(?<![a-z])oauth|(?<![a-z])auth(?![a-z])|(?<![a-z])otp(?![a-z])|token",
    re.IGNORECASE,
)
_OTP_KEYWORD = re.compile(r"(?:code|otp|passcode|password|pin|token)\b", re.IGNORECASE)
_OTP_TOKEN = re.compile(r"\b\d{3,4}(?:[ -]\d{3,4}){1,2}\b|\b[A-Za-z0-9][A-Za-z0-9-]{2,10}[A-Za-z0-9]\b")
_OTP_BARE_CODE = re.compile(r"\b\d{3,4}(?:[ -]\d{3,4}){1,2}\b|\b\d{4,8}\b")


def extract_otp(
    text: str,
    kind: str = "code",
    code_pattern: typing.Optional[typing.Pattern[str]] = None,
) -> typing.Optional[str]:
    """Best-effort extraction of an OTP code or confirmation link from an email's text.

    Links: prefers a URL that looks like a verification/login link, falling back to the
    first URL. Codes: prefers a digit-bearing token near a keyword ("code", "OTP",
    "passcode", ...), falling back to any standalone digit run -- contiguous ("482913")
    or grouped ("123 456", "1234-5678"). ``code_pattern`` replaces the code heuristics;
    its first capture group (or the whole match) is the code.
    """
    if kind == "link":
        urls = _OTP_URL.findall(text)
        hinted = [u for u in urls if _OTP_LINK_HINT.search(u)]
        candidates = hinted or urls
        return candidates[0] if candidates else None
    if code_pattern is not None:
        match = code_pattern.search(text)
        if match is None:
            return None
        return match.group(1) if match.groups() else match.group(0)
    # HTML-derived text carries long whitespace runs (stripped tags, table layouts)
    # that would push the code out of the keyword window; collapse them first.
    text = re.sub(r"\s+", " ", text)
    for keyword in _OTP_KEYWORD.finditer(text):
        window = text[keyword.end() : keyword.end() + 60]
        for token in _OTP_TOKEN.findall(window):
            if any(ch.isdigit() for ch in token):
                return token
    match = _OTP_BARE_CODE.search(text)
    return match.group(0) if match else None


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", markup, flags=re.IGNORECASE | re.DOTALL)
    # Surface link targets: html mail hides the URL behind anchor text ("Click here").
    markup = re.sub(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>", r" \1 ", markup, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def _message_text(message: typing.Any) -> str:
    parts = [str(message.get("Subject") or "")]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        parts.append(_html_to_text(content) if body.get_content_type() == "text/html" else content)
    return "\n".join(parts)


def imap_otp_handler(
    *,
    host: str,
    username: str,
    password: str,
    port: int = 993,
    mailbox: str = "INBOX",
    sender: typing.Optional[str] = None,
    timeout_s: float = 120.0,
    poll_interval_s: float = 5.0,
    max_age_s: float = 900.0,
    mark_seen: bool = True,
    code_pattern: typing.Union[str, typing.Pattern[str], None] = None,
) -> OtpHandler:
    """An :func:`otp_tool` handler that reads the OTP code or confirmation link from a mailbox over IMAP.

    Polls ``mailbox`` for unread messages -- newest first, at most ``max_age_s`` old,
    optionally filtered by ``sender`` -- and runs :func:`extract_otp` on each until one
    yields a value; that message is then marked read (``mark_seen``) so a retry cannot
    reuse a stale code. Raises :class:`TimeoutError` after ``timeout_s`` without a
    match, which surfaces to the agent as a tool error. Works with any IMAP server
    (for Gmail / Google Workspace use an app password).

    Privacy: like every custom tool, this runs entirely in your process. The IMAP
    credentials and connection stay on your machine and are never sent to the API or
    the agent. The agent cannot browse or read the mailbox: it only calls the tool,
    and the only thing sent back is the single extracted code or link -- never email
    bodies, subjects, senders, or any other message content.

    Usage::

        handler = imap_otp_handler(
            host="imap.gmail.com",
            username="agent-inbox@gmail.com",
            password=os.environ["GMAIL_APP_PASSWORD"],
            sender="no-reply@service-being-logged-into.com",
        )
        client.run_session(agent="surfer", messages="Log in to example.com", tools=[otp_tool(handler)])
    """
    compiled = re.compile(code_pattern, re.IGNORECASE) if isinstance(code_pattern, str) else code_pattern

    def handler(request: OtpRequest) -> str:
        import email
        import email.policy
        import imaplib

        deadline = time.monotonic() + timeout_s
        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(username, password)
            while True:
                conn.select(mailbox)
                criteria = ["UNSEEN"] + (["FROM", f'"{sender}"'] if sender else [])
                _, data = conn.search(None, *criteria)
                for msg_id in reversed((data[0] or b"").split()):
                    _, fetched = conn.fetch(msg_id, "(INTERNALDATE BODY.PEEK[])")
                    if not fetched or not isinstance(fetched[0], tuple):
                        continue
                    received = imaplib.Internaldate2tuple(fetched[0][0])
                    if received is not None and time.time() - time.mktime(received) > max_age_s:
                        continue
                    message = email.message_from_bytes(fetched[0][1], policy=email.policy.default)
                    value = extract_otp(_message_text(message), request.kind, compiled)
                    if value:
                        if mark_seen:
                            conn.store(msg_id, "+FLAGS", "\\Seen")
                        return value
                if time.monotonic() >= deadline:
                    label = "link" if request.kind == "link" else "code"
                    raise TimeoutError(f"No {label} found in unread mail for {username} within {timeout_s:.0f}s.")
                time.sleep(poll_interval_s)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return handler
