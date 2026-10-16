"""Runtime identity: each request carries a fresh challenge the runtime answers with an HMAC keyed by its token."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import typing

import httpx

from .errors import LocalRuntimeError

CHALLENGE_HEADER = "X-Hai-Runtime-Challenge"
PROOF_HEADER = "X-Hai-Runtime-Proof"
# A callable token follows a client whose runtime gets replaced.
Token = typing.Union[str, typing.Callable[[], str]]


def challenge() -> str:
    return secrets.token_urlsafe(24)


def verify(token: str, request: httpx.Request, response: httpx.Response) -> None:
    """Raise unless ``response`` proves its server holds ``token`` for the challenge ``request`` sent."""
    sent = request.headers.get(CHALLENGE_HEADER, "")
    expected = hmac.new(token.encode(), sent.encode(), hashlib.sha256).hexdigest()
    received = response.headers.get(PROOF_HEADER, "")
    if not sent or not hmac.compare_digest(received.encode(), expected.encode()):
        raise LocalRuntimeError(
            f"{request.url.scheme}://{request.url.netloc.decode()} did not prove it is the runtime this client "
            "started or attached to: another process holds the port, or the runtime predates identity proofs"
        )


def _current(token: Token) -> str:
    return token if isinstance(token, str) else token()


def event_hooks(token: Token) -> typing.Dict[str, typing.List[typing.Callable[..., None]]]:
    def send_challenge(request: httpx.Request) -> None:
        request.headers[CHALLENGE_HEADER] = challenge()

    def check_proof(response: httpx.Response) -> None:
        verify(_current(token), response.request, response)

    return {"request": [send_challenge], "response": [check_proof]}


def async_event_hooks(token: Token) -> typing.Dict[str, typing.List[typing.Callable[..., typing.Awaitable[None]]]]:
    async def send_challenge(request: httpx.Request) -> None:
        request.headers[CHALLENGE_HEADER] = challenge()

    async def check_proof(response: httpx.Response) -> None:
        verify(_current(token), response.request, response)

    return {"request": [send_challenge], "response": [check_proof]}


def http_client(token: Token, **kwargs: typing.Any) -> httpx.Client:
    """A proxy-free client that rejects any response not proven by the runtime holding ``token``."""
    return httpx.Client(trust_env=False, event_hooks=event_hooks(token), **kwargs)


def async_http_client(token: Token, **kwargs: typing.Any) -> httpx.AsyncClient:
    """``http_client`` for asyncio callers."""
    return httpx.AsyncClient(trust_env=False, event_hooks=async_event_hooks(token), **kwargs)
