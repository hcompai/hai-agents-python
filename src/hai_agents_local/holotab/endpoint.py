"""Where the native host reaches the link: a Unix socket, or loopback TCP behind a per-user token on Windows."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import hmac
import json
import os
import secrets
import socket
import stat
import struct
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Any

from ..file_lock import try_lock

HOST_NAME = "ai.hcompany.hai"
STORE_EXTENSION_ID = "hlaoiikljjgcjdhkakedfngifaopbcop"
DEV_EXTENSION_ENV = "HAI_HOLOTAB_EXTENSION_ID"
SHARED_DIR_ENV = "HAI_HOLOTAB_DIR"
FRAME = struct.Struct("<I")
MAX_FRAME_BYTES = 1024 * 1024
AUTH_TIMEOUT_S = 5.0
MAX_AUTH_BYTES = 1024
SOL_LOCAL = 0
LOCAL_PEERCRED = 1
XUCRED = struct.Struct("=II")
UCRED = struct.Struct("=iII")


def shared_dir() -> Path:
    override = os.environ.get(SHARED_DIR_ENV)
    return Path(override) if override else Path.home() / ".hai" / "holotab"


def allowed_extension_ids() -> tuple[str, ...]:
    dev = os.environ.get(DEV_EXTENSION_ENV, "").strip()
    return (STORE_EXTENSION_ID, dev) if dev and dev != STORE_EXTENSION_ID else (STORE_EXTENSION_ID,)


def own_uid() -> int:
    return os.getuid()


def peer_uid(conn: socket.socket) -> int | None:
    """The user id behind a Unix socket's other end, or None where the system does not say."""
    try:
        if sys.platform == "darwin":
            _version, uid = XUCRED.unpack(conn.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, 76)[: XUCRED.size])
            return uid
        if sys.platform.startswith("linux"):
            _pid, uid, _gid = UCRED.unpack(conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, UCRED.size))
            return uid
    except (OSError, struct.error):
        return None
    return None


class EndpointBusy(RuntimeError):
    """Another live process already serves the endpoint."""


BUSY = "HoloTab is already linked to another program on this computer: close it to use HoloTab here"


def claim_lock(path: Path) -> IO[bytes]:
    """An exclusive lock the operating system drops with the process, so one owner wins a race and a crash frees it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    if not try_lock(handle.fileno()):
        handle.close()
        raise EndpointBusy(BUSY)
    return handle


class Endpoint(ABC):
    """One place the link listens and the shim, or another local process, connects."""

    auth_timeout_s: float = AUTH_TIMEOUT_S

    @abstractmethod
    def bind(self) -> socket.socket:
        """A listening socket; raises EndpointBusy while another process serves this endpoint."""

    @abstractmethod
    def release(self) -> None:
        """Frees the endpoint once the socket from ``bind`` is closed."""

    @abstractmethod
    def connect(self) -> socket.socket:
        """A connected socket, before any handshake; raises OSError when nobody serves."""

    @abstractmethod
    def prove(self, conn: socket.socket) -> None:
        """The connecting side's handshake: raises ConnectionRefusedError unless the listener is this user's link."""

    @abstractmethod
    def admits(self, conn: socket.socket) -> bool:
        """The listening side's handshake: whether an accepted connection is this user's."""

    def open(self) -> socket.socket:
        """A connection to the link, once the link has shown it is this user's: nothing is sent to it before."""
        conn = self.connect()
        try:
            self.prove(conn)
            conn.settimeout(None)
        except BaseException:
            conn.close()
            raise
        return conn


class UnixEndpoint(Endpoint):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._inode: int | None = None
        self._claim_handle: IO[bytes] | None = None

    def bind(self) -> socket.socket:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        claim = claim_lock(path.with_suffix(".lock"))
        try:
            if os.path.lexists(path):
                found = path.lstat()
                if not stat.S_ISSOCK(found.st_mode) or found.st_uid != own_uid():
                    raise RuntimeError(f"refusing to replace unsafe HoloTab socket path at {path}")
                path.unlink()
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
            except OSError as exc:
                server.close()
                if exc.errno == errno.EADDRINUSE:
                    raise EndpointBusy(BUSY) from exc
                raise
            try:
                os.chmod(path, 0o600)
                server.listen(8)
                self._inode = path.stat().st_ino
            except BaseException:
                server.close()
                path.unlink(missing_ok=True)
                raise
        except BaseException:
            claim.close()
            raise
        self._claim_handle = claim
        return server

    def release(self) -> None:
        inode, self._inode = self._inode, None
        claim, self._claim_handle = self._claim_handle, None
        try:
            current = self.path.lstat()
            if inode is not None and stat.S_ISSOCK(current.st_mode) and current.st_ino == inode:
                self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            if claim is not None:
                claim.close()

    def connect(self) -> socket.socket:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.connect(str(self.path))
        except OSError:
            conn.close()
            raise
        return conn

    def prove(self, conn: socket.socket) -> None:
        uid = peer_uid(conn)
        if uid is not None and uid != own_uid():
            raise ConnectionRefusedError(f"the HoloTab link at {self.path} belongs to another user")

    def admits(self, conn: socket.socket) -> bool:
        uid = peer_uid(conn)
        return uid is None or uid == own_uid()


class TcpEndpoint(Endpoint):
    """Loopback TCP for Windows, where the port and a random token sit in a file only this user reads."""

    def __init__(self, info_path: Path) -> None:
        self.info_path = info_path
        self._token: str | None = None
        self._claim_handle: IO[bytes] | None = None

    def _read(self) -> dict[str, Any]:
        try:
            info = json.loads(self.info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConnectionRefusedError(f"no HoloTab link is advertised at {self.info_path}") from exc
        if not isinstance(info, dict) or not isinstance(info.get("port"), int) or not info.get("token"):
            raise ConnectionRefusedError(f"unreadable HoloTab link file at {self.info_path}")
        return info

    def bind(self) -> socket.socket:
        claim = claim_lock(self.info_path.with_suffix(".lock"))
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(8)
            self._token = secrets.token_urlsafe(32)
            self.info_path.write_text(
                json.dumps({"port": server.getsockname()[1], "token": self._token}), encoding="utf-8"
            )
            os.chmod(self.info_path, 0o600)
        except BaseException:
            server.close()
            claim.close()
            raise
        self._claim_handle = claim
        return server

    def release(self) -> None:
        self._token = None
        claim, self._claim_handle = self._claim_handle, None
        if claim is not None:
            with contextlib.suppress(OSError):
                self.info_path.unlink(missing_ok=True)
            claim.close()

    def connect(self) -> socket.socket:
        return socket.create_connection(("127.0.0.1", self._read()["port"]), timeout=self.auth_timeout_s)

    def prove(self, conn: socket.socket) -> None:
        """Mutual proof without the token on the wire: the link answers the client's nonce with an HMAC, so a process
        that took over the port of a link that crashed learns nothing, then the client answers the link's nonce."""
        token = self._read()["token"]
        nonce = secrets.token_hex(16)
        send_line(conn, {"type": "AUTH", "nonce": nonce})
        answer = _read_line(conn)
        if not _matches(answer.get("proof"), proof(token, "link", nonce)) or not isinstance(answer.get("nonce"), str):
            raise ConnectionRefusedError(f"the process on the port in {self.info_path} is not this user's HoloTab link")
        send_line(conn, {"type": "AUTH", "proof": proof(token, "client", answer["nonce"])})

    def admits(self, conn: socket.socket) -> bool:
        token = self._token
        if token is None:
            return False
        conn.settimeout(self.auth_timeout_s)
        try:
            greeting = _read_line(conn)
            if greeting.get("type") != "AUTH" or not isinstance(greeting.get("nonce"), str):
                return False
            nonce = secrets.token_hex(16)
            send_line(conn, {"type": "AUTH", "nonce": nonce, "proof": proof(token, "link", greeting["nonce"])})
            if not _matches(_read_line(conn).get("proof"), proof(token, "client", nonce)):
                return False
        except (OSError, ValueError):
            return False
        conn.settimeout(None)
        return True


def proof(token: str, role: str, nonce: str) -> str:
    return hmac.new(token.encode("utf-8"), f"{role}:{nonce}".encode(), hashlib.sha256).hexdigest()


def _matches(received: Any, expected: str) -> bool:
    return isinstance(received, str) and hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


def send_line(conn: socket.socket, message: dict[str, Any]) -> None:
    conn.sendall(json.dumps(message).encode("utf-8") + b"\n")


def _read_line(conn: socket.socket) -> dict[str, Any]:
    """One handshake line, read a byte at a time so nothing after it is consumed, and never more than the cap."""
    data = bytearray()
    while not data.endswith(b"\n"):
        if len(data) >= MAX_AUTH_BYTES:
            raise ConnectionRefusedError(f"a HoloTab link handshake line exceeds {MAX_AUTH_BYTES} bytes")
        chunk = conn.recv(1)
        if not chunk:
            raise ConnectionRefusedError("the HoloTab link connection closed during its handshake")
        data += chunk
    try:
        message = json.loads(data)
    except ValueError:
        message = None
    if not isinstance(message, dict):
        raise ConnectionRefusedError("a HoloTab link handshake line must be a JSON object")
    return message


def default_endpoint() -> Endpoint:
    folder = shared_dir()
    return TcpEndpoint(folder / "link.json") if sys.platform == "win32" else UnixEndpoint(folder / "link.sock")
