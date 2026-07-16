"""HTTP transport for the platform's command channel."""

from __future__ import annotations

import base64
import logging
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import AuthError, RateLimitedError, SessionNotFoundError

logger = logging.getLogger(__name__)

Json = Union[None, bool, int, float, str, List["Json"], Dict[str, "Json"]]


class Command(BaseModel):
    """One command from the channel: ``name`` is a driver interface method, ``args`` its kwargs as JSON."""

    model_config = ConfigDict(extra="ignore")

    id: str
    command_uid: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})
DEFAULT_RETRY_AFTER_S = 5.0


def serialize_result(value: object) -> Json:
    """Make a driver return value JSON-safe: bytes to base64, pydantic models dumped, containers recursed."""
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: serialize_result(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_result(v) for v in value]
    return value  # type: ignore[return-value]


def deserialize_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Undo the JSON encodings the driver signatures cannot accept directly."""
    if name == "write_file" and isinstance(args.get("content"), str):
        args = {**args, "content": base64.b64decode(args["content"])}
    if name == "run_command" and args.get("cwd") is not None:
        args = {**args, "cwd": Path(args["cwd"])}
    return args


class CommandExchange:
    """Fetches Command batches from the platform and posts back their results."""

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    async def ensure_channel(self, session_id: str) -> None:
        check = await self._client.get(f"{self._base}/api/v1/trajectories/{session_id}/")
        if check.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise AuthError(f"auth error checking channel ({check.status_code})")
        if check.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise RateLimitedError(_retry_after(check))
        if check.status_code == HTTPStatus.OK:
            return
        resp = await self._client.post(
            f"{self._base}/api/v1/trajectories/",
            json={"id": session_id, "task": {"type": "interactive"}, "launch": False},
        )
        if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise AuthError(f"auth error creating channel ({resp.status_code})")
        if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise RateLimitedError(_retry_after(resp))
        if resp.status_code == HTTPStatus.CONFLICT:
            return
        resp.raise_for_status()

    async def fetch_commands(
        self,
        session_id: str,
        *,
        wait_for_seconds: int,
        read_timeout: float,
        max_retries: int,
    ) -> list[Command] | None:
        url = f"{self._base}/api/v1/commands/{session_id}/commands"
        for attempt in range(max_retries + 1):
            resp = await self._client.get(url, params={"wait_for_seconds": wait_for_seconds}, timeout=read_timeout)
            match resp.status_code:
                case HTTPStatus.NO_CONTENT:
                    return None
                case HTTPStatus.NOT_FOUND:
                    raise SessionNotFoundError(f"channel {session_id!r} not found")
                case HTTPStatus.UNAUTHORIZED | HTTPStatus.FORBIDDEN:
                    raise AuthError(f"auth error ({resp.status_code})")
                case HTTPStatus.TOO_MANY_REQUESTS:
                    raise RateLimitedError(_retry_after(resp))
                case status if status in TRANSIENT_STATUS_CODES and attempt < max_retries:
                    continue
                case _:
                    resp.raise_for_status()
                    return _parse_commands(resp)
        return None

    async def post_result(
        self, command_id: str, *, command_uid: str, result: Json, error: str | None, timeout: float
    ) -> None:
        url = f"{self._base}/api/v1/commands/{command_id}/result"
        body = {"result": result, "error": error, "command_uid": command_uid}
        resp = await self._client.post(url, json=body, timeout=timeout)
        if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise AuthError(f"auth error posting result ({resp.status_code})")
        if resp.status_code == HTTPStatus.CONFLICT:
            # Another delivery of the same command_uid already landed; the result is recorded.
            return
        resp.raise_for_status()


def _retry_after(resp: httpx.Response) -> float:
    try:
        return max(0.0, float(resp.headers.get("Retry-After", "")))
    except ValueError:
        return DEFAULT_RETRY_AFTER_S


def _parse_commands(resp: httpx.Response) -> list[Command] | None:
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    commands: list[Command] = []
    for item in data:
        try:
            commands.append(Command.model_validate(item))
        except ValidationError:
            logger.warning("skipping malformed command: %s", item)
    return commands
