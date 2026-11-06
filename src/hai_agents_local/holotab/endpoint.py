"""Where the native host reaches the link: a Unix socket, or loopback TCP behind a per-user token on Windows."""

from __future__ import annotations

import contextlib
import errno
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

HOST_NAME = "ai.hcompany.hai"
STORE_EXTENSION_ID = "hlaoiikljjgcjdhkakedfngifaopbcop"
DEV_EXTENSION_ENV = "HAI_HOLOTAB_EXTENSION_ID"
SHARED_DIR_ENV = "HAI_HOLOTAB_DIR"
FRAME = struct.Struct("<I")
MAX_FRAME_BYTES = 2 * 1024 * 1024
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


def claim_lock(path: Path) -> IO[bytes]:
    """An exclusive lock the operating system drops with the process, so one owner wins a race and a crash frees it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise EndpointBusy(f"HoloTab native messaging is already served through {path}") from exc
    return handle


class Endpoint(ABC):
    """One place the link listens and the shim, or another local process, connects."""

    greeting_required: bool = False

    @abstractmethod
    def bind(self) -> socket.socket:
        """A listening socket; raises EndpointBusy while another process serves this endpoint."""

    @abstractmethod
    def release(self, server: socket.socket) -> None:
        """Forget a socket from ``bind`` once it is closed."""

    @abstractmethod
    def connect(self) -> socket.socket:
        """A connected socket, before any greeting; raises OSError when nobody serves."""

    @abstractmethod
    def greeting(self) -> dict[str, Any] | None:
        """The message a connecting side sends first to be admitted, if the endpoint wants one."""

    @abstractmethod
    def admits(self, conn: socket.socket, greeting: dict[str, Any] | None) -> bool:
        """Whether an accepted connection, with its greeting when one is required, may talk to the link."""

    def open(self) -> socket.socket:
        conn = self.connect()
        if (greeting := self.greeting()) is not None:
            try:
                conn.sendall(json.dumps(greeting).encode("utf-8") + b"\n")
            except OSError:
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
                    raise RuntimeError(f"HoloTab native messaging is already served at {path}") from exc
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

    def release(self, server: socket.socket) -> None:
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

    def greeting(self) -> dict[str, Any] | None:
        return None

    def admits(self, conn: socket.socket, greeting: dict[str, Any] | None) -> bool:
        uid = peer_uid(conn)
        return uid is None or uid == own_uid()


class TcpEndpoint(Endpoint):
    """Loopback TCP for Windows, where the port and a random token sit in a file only this user reads."""

    greeting_required = True

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

    def release(self, server: socket.socket) -> None:
        self._token = None
        claim, self._claim_handle = self._claim_handle, None
        if claim is not None:
            with contextlib.suppress(OSError):
                self.info_path.unlink(missing_ok=True)
            claim.close()

    def connect(self) -> socket.socket:
        conn = socket.create_connection(("127.0.0.1", self._read()["port"]), timeout=2.0)
        conn.settimeout(None)
        return conn

    def greeting(self) -> dict[str, Any] | None:
        return {"type": "AUTH", "token": self._read()["token"]}

    def admits(self, conn: socket.socket, greeting: dict[str, Any] | None) -> bool:
        token = self._token
        return (
            token is not None
            and greeting is not None
            and greeting.get("type") == "AUTH"
            and secrets.compare_digest(str(greeting.get("token", "")), token)
        )


def default_endpoint() -> Endpoint:
    folder = shared_dir()
    return TcpEndpoint(folder / "link.json") if sys.platform == "win32" else UnixEndpoint(folder / "link.sock")
