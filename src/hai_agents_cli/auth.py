"""Browser sign-in: RFC 8252 loopback redirect + PKCE, then mint an API key."""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import socket
import time
import typing
import urllib.parse
import webbrowser

import httpx

from hai_agents_common.credentials import API_KEYS_PAGE

from .login_pages import ERROR_HTML, SUCCESS_HTML

SIGN_IN_TIMEOUT_S = 180
KEY_FALLBACK = (
    f"Browser sign-in works with Google accounts. Otherwise create a key at {API_KEYS_PAGE} and run `hai login --key`."
)


class PortalError(RuntimeError):
    """A portal request failed; the message is the portal's own explanation."""


def login_and_mint(portal: str, label: str, on_open: typing.Callable[[str], None]) -> str:
    """Run the full browser sign-in and return a freshly minted API key."""
    verifier, challenge = _pkce_pair()
    redirect_uri = _free_redirect_uri()
    authorize_url = (
        f"{portal}/api/auth/authorize?provider=google"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&code_challenge={challenge}&code_challenge_method=S256"
    )
    on_open(authorize_url)
    webbrowser.open(authorize_url)
    code = _await_code(redirect_uri)

    with httpx.Client(timeout=20.0) as client:
        try:
            token = _ok(
                client.post(
                    f"{portal}/api/auth/desktop/exchange",
                    json={"code": code, "code_verifier": verifier, "redirect_uri": redirect_uri},
                )
            )
        except PortalError as exc:
            raise PortalError(f"sign-in failed: {exc} {KEY_FALLBACK}") from None
        client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"

        me = _ok(client.get(f"{portal}/api/auth/me")).json()
        org_id = me.get("org_id") or (me.get("organization") or {}).get("id")
        if not org_id:
            owned = _ok(client.get(f"{portal}/api/organizations/owned")).json()
            if not owned:
                raise RuntimeError("no organization is available to mint a key against.")
            org_id = owned[0]["id"]

        return _mint_key(client, portal, org_id, label)["key"]


def _ok(response: httpx.Response) -> httpx.Response:
    """The response, or a PortalError carrying the portal's `detail` instead of a bare status line."""
    if response.is_success:
        return response
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("detail") if isinstance(body, dict) else None
    reason = str(detail or response.text.strip()[:200] or response.reason_phrase).rstrip(".")
    raise PortalError(f"{response.request.method} {response.url.path} returned {response.status_code}: {reason}.")


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256: URL-safe verifier and its base64url(SHA-256) challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        if code:
            self.server.auth_code = code  # type: ignore[attr-defined]
            self._respond(200, SUCCESS_HTML)
        elif error:
            self.server.auth_error = params.get("error_description", [error])[0]  # type: ignore[attr-defined]
            self._respond(400, ERROR_HTML)
        else:
            self._respond(404, b"")

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: typing.Any) -> None:
        pass


def _await_code(redirect_uri: str) -> str:
    """Serve the loopback callback until the browser delivers a code or we time out."""
    port = int(urllib.parse.urlparse(redirect_uri).port or 0)
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.auth_code = None  # type: ignore[attr-defined]
    server.auth_error = None  # type: ignore[attr-defined]
    deadline = time.monotonic() + SIGN_IN_TIMEOUT_S
    try:
        while server.auth_code is None and server.auth_error is None:  # type: ignore[attr-defined]
            server.timeout = deadline - time.monotonic()
            if server.timeout <= 0:
                raise RuntimeError(f"no browser sign-in within {SIGN_IN_TIMEOUT_S}s. {KEY_FALLBACK}")
            server.handle_request()
    finally:
        server.server_close()
    if server.auth_error is not None:  # type: ignore[attr-defined]
        raise PortalError(f"sign-in failed: {server.auth_error}. {KEY_FALLBACK}")  # type: ignore[attr-defined]
    return server.auth_code  # type: ignore[attr-defined]


def _free_redirect_uri() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/"


def _mint_key(client: httpx.Client, portal: str, org_id: str, label: str) -> dict[str, typing.Any]:
    """Mint a key; on a name collision, reclaim the stale per-machine key and remint once."""
    keys_url = f"{portal}/api/organizations/{org_id}/keys/"
    response = client.post(keys_url, json={"name": label})
    if not (response.status_code == 400 and "already_exists" in response.text):
        return _ok(response).json()
    stale = next((k for k in _ok(client.get(keys_url)).json() if k.get("name") == label), None)
    if stale is not None:
        client.delete(f"{keys_url}{stale['id']}")
    return _ok(client.post(keys_url, json={"name": label})).json()
