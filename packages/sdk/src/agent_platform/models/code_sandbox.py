from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.code_sandbox_env import CodeSandboxEnv
    from ..models.mcp_server import MCPServer


T = TypeVar("T", bound="CodeSandbox")


class CodeSandbox(BaseModel):
    """Code sandbox environment.

    Attributes:
        id (str): Catalog id.
        kind (Literal['code'] | Unset):  Default: 'code'.
        pip_packages (list[str] | Unset): Pip packages installed at provision time.
        env (CodeSandboxEnv | Unset): Environment variables.
        mcp_servers (list[MCPServer] | Unset): MCP servers reachable from the sandbox.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: str
    kind: Literal["code"] | Unset = "code"
    pip_packages: list[str] | Unset = UNSET
    env: CodeSandboxEnv | Unset = UNSET
    mcp_servers: list[MCPServer] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.code_sandbox_env import CodeSandboxEnv
        from ..models.mcp_server import MCPServer

        id = self.id

        kind = self.kind

        pip_packages: list[str] | Unset = UNSET
        if not isinstance(self.pip_packages, Unset):
            pip_packages = self.pip_packages

        env: dict[str, Any] | Unset = UNSET
        if not isinstance(self.env, Unset):
            env = self.env.to_dict()

        mcp_servers: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.mcp_servers, Unset):
            mcp_servers = []
            for mcp_servers_item_data in self.mcp_servers:
                mcp_servers_item = mcp_servers_item_data.to_dict()
                mcp_servers.append(mcp_servers_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind
        if pip_packages is not UNSET:
            field_dict["pip_packages"] = pip_packages
        if env is not UNSET:
            field_dict["env"] = env
        if mcp_servers is not UNSET:
            field_dict["mcp_servers"] = mcp_servers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.code_sandbox_env import CodeSandboxEnv
        from ..models.mcp_server import MCPServer

        d = dict(src_dict)
        id = d.pop("id")

        kind = cast(Literal["code"] | Unset, d.pop("kind", UNSET))
        if kind != "code" and not isinstance(kind, Unset):
            raise ValueError(f"kind must match const 'code', got '{kind}'")

        pip_packages = cast(list[str], d.pop("pip_packages", UNSET))

        _env = d.pop("env", UNSET)
        env: CodeSandboxEnv | Unset
        if isinstance(_env, Unset):
            env = UNSET
        else:
            env = CodeSandboxEnv.from_dict(_env)

        _mcp_servers = d.pop("mcp_servers", UNSET)
        mcp_servers: list[MCPServer] | Unset = UNSET
        if _mcp_servers is not UNSET:
            mcp_servers = []
            for mcp_servers_item_data in _mcp_servers:
                mcp_servers_item = MCPServer.from_dict(mcp_servers_item_data)

                mcp_servers.append(mcp_servers_item)

        code_sandbox = cls(
            id=id,
            kind=kind,
            pip_packages=pip_packages,
            env=env,
            mcp_servers=mcp_servers,
        )

        return code_sandbox
