"""Browser sign-in: RFC 8252 loopback redirect + PKCE, then mint an API key."""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import socket
import typing
import urllib.parse
import webbrowser

import httpx

from .login_pages import ERROR_HTML, SUCCESS_HTML

SIGN_IN_TIMEOUT_S = 180


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
        token = client.post(
            f"{portal}/api/auth/desktop/exchange",
            json={"code": code, "code_verifier": verifier, "redirect_uri": redirect_uri},
        )
        token.raise_for_status()
        client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"

        me = client.get(f"{portal}/api/auth/me")
        me.raise_for_status()
        org_id = me.json().get("org_id") or (me.json().get("organization") or {}).get("id")
        if not org_id:
            owned = client.get(f"{portal}/api/organizations/owned")
            owned.raise_for_status()
            if not owned.json():
                raise RuntimeError("no organization is available to mint a key against.")
            org_id = owned.json()[0]["id"]

        return _mint_key(client, portal, org_id, label)["key"]


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
    server.timeout = SIGN_IN_TIMEOUT_S
    try:
        while server.auth_code is None and server.auth_error is None:  # type: ignore[attr-defined]
            server.handle_request()
    finally:
        server.server_close()
    if server.auth_error is not None:  # type: ignore[attr-defined]
        raise RuntimeError(f"portal returned an error: {server.auth_error}")  # type: ignore[attr-defined]
    return server.auth_code  # type: ignore[attr-defined]


def _free_redirect_uri() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/"


def _is_name_collision(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 400 and "already_exists" in exc.response.text


def _mint_key(client: httpx.Client, portal: str, org_id: str, label: str) -> dict[str, typing.Any]:
    """Mint a key; on a name collision, reclaim the stale per-machine key and remint once."""
    keys_url = f"{portal}/api/organizations/{org_id}/keys/"
    try:
        response = client.post(keys_url, json={"name": label})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if not _is_name_collision(exc):
            raise
    existing = client.get(keys_url)
    existing.raise_for_status()
    stale = next((k for k in existing.json() if k.get("name") == label), None)
    if stale is not None:
        client.delete(f"{keys_url}{stale['id']}")
    response = client.post(keys_url, json={"name": label})
    response.raise_for_status()
    return response.json()
