from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.mcp_server import MCPServer


T = TypeVar("T", bound="MCP")


class MCP(BaseModel):
    """MCP environment.

    Attributes:
        id (str): Catalog id.
        servers (list[MCPServer]): At least one MCP server.
        kind (Literal['mcp'] | Unset):  Default: 'mcp'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: str
    servers: list[MCPServer]
    kind: Literal["mcp"] | Unset = "mcp"

    def to_dict(self) -> dict[str, Any]:
        from ..models.mcp_server import MCPServer

        id = self.id

        servers = []
        for servers_item_data in self.servers:
            servers_item = servers_item_data.to_dict()
            servers.append(servers_item)

        kind = self.kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "servers": servers,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.mcp_server import MCPServer

        d = dict(src_dict)
        id = d.pop("id")

        servers = []
        _servers = d.pop("servers")
        for servers_item_data in _servers:
            servers_item = MCPServer.from_dict(servers_item_data)

            servers.append(servers_item)

        kind = cast(Literal["mcp"] | Unset, d.pop("kind", UNSET))
        if kind != "mcp" and not isinstance(kind, Unset):
            raise ValueError(f"kind must match const 'mcp', got '{kind}'")

        mcp = cls(
            id=id,
            servers=servers,
            kind=kind,
        )

        return mcp
