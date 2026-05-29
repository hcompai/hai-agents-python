from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..models.mcp_server_transport import MCPServerTransport
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.mcp_server_env import MCPServerEnv
    from ..models.mcp_server_headers import MCPServerHeaders


T = TypeVar("T", bound="MCPServer")


class MCPServer(BaseModel):
    """MCP server attached to an environment.

    Attributes:
        name (str): Stable identifier.
        transport (MCPServerTransport): MCP transport.
        command (None | str | Unset): Subprocess executable (stdio).
        args (list[str] | Unset): Subprocess argv tail (stdio).
        env (MCPServerEnv | Unset): Subprocess env vars (stdio).
        url (None | str | Unset): Endpoint URL (HTTP).
        headers (MCPServerHeaders | Unset): Request headers (HTTP).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    name: str
    transport: MCPServerTransport
    command: None | str | Unset = UNSET
    args: list[str] | Unset = UNSET
    env: MCPServerEnv | Unset = UNSET
    url: None | str | Unset = UNSET
    headers: MCPServerHeaders | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.mcp_server_env import MCPServerEnv
        from ..models.mcp_server_headers import MCPServerHeaders

        name = self.name

        transport = self.transport.value

        command: None | str | Unset
        if isinstance(self.command, Unset):
            command = UNSET
        else:
            command = self.command

        args: list[str] | Unset = UNSET
        if not isinstance(self.args, Unset):
            args = self.args

        env: dict[str, Any] | Unset = UNSET
        if not isinstance(self.env, Unset):
            env = self.env.to_dict()

        url: None | str | Unset
        if isinstance(self.url, Unset):
            url = UNSET
        else:
            url = self.url

        headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.headers, Unset):
            headers = self.headers.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "transport": transport,
            }
        )
        if command is not UNSET:
            field_dict["command"] = command
        if args is not UNSET:
            field_dict["args"] = args
        if env is not UNSET:
            field_dict["env"] = env
        if url is not UNSET:
            field_dict["url"] = url
        if headers is not UNSET:
            field_dict["headers"] = headers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.mcp_server_env import MCPServerEnv
        from ..models.mcp_server_headers import MCPServerHeaders

        d = dict(src_dict)
        name = d.pop("name")

        transport = MCPServerTransport(d.pop("transport"))

        def _parse_command(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        command = _parse_command(d.pop("command", UNSET))

        args = cast(list[str], d.pop("args", UNSET))

        _env = d.pop("env", UNSET)
        env: MCPServerEnv | Unset
        if isinstance(_env, Unset):
            env = UNSET
        else:
            env = MCPServerEnv.from_dict(_env)

        def _parse_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        url = _parse_url(d.pop("url", UNSET))

        _headers = d.pop("headers", UNSET)
        headers: MCPServerHeaders | Unset
        if isinstance(_headers, Unset):
            headers = UNSET
        else:
            headers = MCPServerHeaders.from_dict(_headers)

        mcp_server = cls(
            name=name,
            transport=transport,
            command=command,
            args=args,
            env=env,
            url=url,
            headers=headers,
        )

        return mcp_server
