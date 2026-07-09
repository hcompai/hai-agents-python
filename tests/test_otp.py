"""Behavior tests for the prebuilt OTP tool (``hai_agents_tools.otp``).

Package resolution and re-export meta checks live in test_tools_package; this file
only tests the OTP tool's behavior.
"""

from __future__ import annotations

import asyncio
import re
from typing import Awaitable

import pytest

from hai_agents_tools import OTP_TOOL_INPUT_SCHEMA, OtpRequest, extract_otp, imap_otp_handler, otp_tool
from hai_agents_tools.otp import _html_to_text


def test_otp_tool_definition_defaults() -> None:
    t = otp_tool()
    definition = t.definition()
    assert definition["name"] == "request_otp"
    assert "one-time password" in definition["description"]
    schema = definition["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["prompt"]
    assert set(schema["properties"]) == {"prompt", "kind", "source"}
    assert schema["properties"]["kind"]["enum"] == ["code", "link"]


def test_otp_tool_custom_handler_receives_request_and_trims() -> None:
    seen: list[OtpRequest] = []

    def handler(request: OtpRequest) -> str:
        seen.append(request)
        return "  123456  "

    t = otp_tool(handler)
    assert t.fn(prompt="Enter the code sent to a@b.com", kind="code", source="email") == "123456"
    assert seen == [OtpRequest(prompt="Enter the code sent to a@b.com", kind="code", source="email")]


def test_otp_tool_defaults_kind_and_source() -> None:
    seen: list[OtpRequest] = []

    def handler(request: OtpRequest) -> str:
        seen.append(request)
        return "ok"

    otp_tool(handler).fn(prompt="Enter the code")
    assert seen == [OtpRequest(prompt="Enter the code", kind="code", source=None)]


def test_otp_tool_empty_value_raises() -> None:
    t = otp_tool(lambda request: "   ")
    with pytest.raises(ValueError, match="No code"):
        t.fn(prompt="Enter the code")
    t = otp_tool(lambda request: "")
    with pytest.raises(ValueError, match="No link"):
        t.fn(prompt="Open the link", kind="link")


def test_otp_tool_async_handler() -> None:
    async def handler(request: OtpRequest) -> str:
        return " 654321 "

    result = otp_tool(handler).fn(prompt="Enter the code")
    assert asyncio.run(_await(result)) == "654321"


async def _await(value: Awaitable[str]) -> str:
    return await value


def test_otp_tool_default_handler_prompts_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "42"

    monkeypatch.setattr("builtins.input", fake_input)
    assert otp_tool().fn(prompt="Enter the 6-digit code", source="sms") == "42"
    assert prompts == ["Enter the 6-digit code (sent via sms)\nEnter the code: "]


def test_otp_tool_name_and_description_overrides() -> None:
    t = otp_tool(lambda request: "x", name="get_2fa_code", description="Fetch the 2FA code.")
    assert t.definition() == {
        "name": "get_2fa_code",
        "description": "Fetch the 2FA code.",
        "input_schema": OTP_TOOL_INPUT_SCHEMA,
    }


def test_extract_otp_code_near_keyword() -> None:
    assert extract_otp("Your verification code is 482913. It expires in 10 minutes.") == "482913"
    assert extract_otp("Your OTP code is 1234") == "1234"


def test_extract_otp_grouped_digits() -> None:
    assert extract_otp("Enter 123 456 to continue") == "123 456"
    assert extract_otp("Your code is 1234-5678") == "1234-5678"
    assert extract_otp("Use 123 456 789 now") == "123 456 789"


def test_extract_otp_collapses_whitespace_from_html_layouts() -> None:
    # Table-based HTML mail turns into text with the code far from the keyword.
    text = "Your verification code\n\n\n" + " " * 50 + "\n\n482913"
    assert extract_otp(text) == "482913"


def test_extract_otp_alphanumeric_code() -> None:
    assert extract_otp("Use passcode 7GK4-P2Q to continue.") == "7GK4-P2Q"


def test_extract_otp_bare_digits_fallback() -> None:
    assert extract_otp("314159 is your Acme sign-in key") == "314159"


def test_extract_otp_custom_pattern_capture_group() -> None:
    assert extract_otp("Ticket ABC-99-XYZ opened", code_pattern=re.compile(r"Ticket ([A-Z0-9-]+)")) == "ABC-99-XYZ"


def test_extract_otp_link_prefers_verification_url() -> None:
    text = "View in browser: https://news.example.com/open?id=1 Confirm: https://app.example.com/verify?token=abc"
    assert extract_otp(text, kind="link") == "https://app.example.com/verify?token=abc"


def test_extract_otp_link_hint_ignores_embedded_words() -> None:
    # "authors" / "hotpicks" must not trip the "auth" / "otp" hints and outrank the real link.
    text = (
        "Meet our team: https://blog.example.com/authors/jane "
        "Deals: https://shop.example.com/hotpicks "
        "Confirm your account: https://app.example.com/verify?id=1"
    )
    assert extract_otp(text, kind="link") == "https://app.example.com/verify?id=1"


def test_extract_otp_link_hint_still_matches_auth_segments() -> None:
    text = "Docs: https://docs.example.com/start Login: https://id.example.com/auth/callback?sid=9"
    assert extract_otp(text, kind="link") == "https://id.example.com/auth/callback?sid=9"
    text = "Docs: https://docs.example.com/start Login: https://oauth.example.com/approve?sid=9"
    assert extract_otp(text, kind="link") == "https://oauth.example.com/approve?sid=9"


def test_extract_otp_link_falls_back_to_first_url() -> None:
    assert extract_otp("See https://example.com/a then https://example.com/b", kind="link") == "https://example.com/a"


def test_extract_otp_no_match_returns_none() -> None:
    assert extract_otp("Hello there, nothing to see.") is None
    assert extract_otp("Hello there, nothing to see.", kind="link") is None


def test_html_to_text_surfaces_hrefs_and_entities() -> None:
    text = _html_to_text(
        '<style>.x{color:red}</style><p>Click <a href="https://x.test/verify?t=1">here</a>&nbsp;to verify</p>'
    )
    assert "https://x.test/verify?t=1" in text
    assert "to verify" in text
    assert "color:red" not in text


class _FakeImapConn:
    """Two unread messages; only the newest (id 2) carries a code."""

    last: "_FakeImapConn"

    def __init__(self, host: str, port: int) -> None:
        type(self).last = self
        self.host, self.port = host, port
        self.stored: list = []
        self.searches: list = []
        self.logged_out = False

    def login(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def select(self, mailbox: str) -> None:
        self.mailbox = mailbox

    def search(self, charset, *criteria):  # type: ignore[no-untyped-def]
        self.searches.append(criteria)
        return "OK", [b"1 2"]

    def fetch(self, msg_id, spec):  # type: ignore[no-untyped-def]
        bodies = {
            b"1": b"Subject: Welcome\r\nContent-Type: text/plain\r\n\r\nThanks for signing up!\r\n",
            b"2": b"Subject: Your login code\r\nContent-Type: text/plain\r\n\r\nYour login code is 314159.\r\n",
        }
        return "OK", [(msg_id + b" (BODY[] {0}", bodies[msg_id]), b")"]

    def store(self, msg_id, op, flags):  # type: ignore[no-untyped-def]
        self.stored.append((msg_id, op, flags))

    def logout(self) -> None:
        self.logged_out = True


def test_imap_otp_handler_reads_newest_unread_and_marks_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    import imaplib

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeImapConn)
    handler = imap_otp_handler(host="imap.test", username="u@test", password="pw", sender="no-reply@x.test")
    assert handler(OtpRequest(prompt="Enter the code")) == "314159"
    conn = _FakeImapConn.last
    assert conn.credentials == ("u@test", "pw")
    assert conn.searches == [("UNSEEN", "FROM", '"no-reply@x.test"')]
    assert conn.stored == [(b"2", "+FLAGS", "\\Seen")]
    assert conn.logged_out


def test_imap_otp_handler_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import imaplib

    class _EmptyImapConn(_FakeImapConn):
        def search(self, charset, *criteria):  # type: ignore[no-untyped-def]
            return "OK", [b""]

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _EmptyImapConn)
    handler = imap_otp_handler(host="imap.test", username="u@test", password="pw", timeout_s=0)
    with pytest.raises(TimeoutError, match="No code found"):
        handler(OtpRequest(prompt="Enter the code"))
    assert _EmptyImapConn.last.logged_out
