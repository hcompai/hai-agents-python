from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.browser import Browser
    from ..models.code_sandbox import CodeSandbox
    from ..models.mcp import MCP
    from ..models.memory import Memory


T = TypeVar("T", bound="UpdateEnvironment")


class UpdateEnvironment(BaseModel):
    """``PUT /api/v2/environments/{env_identifier}`` body. Full replace; ``spec.id`` is immutable.

    Attributes:
        spec (Browser | CodeSandbox | MCP | Memory):
        description (str | Unset):  Default: ''.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    spec: Browser | CodeSandbox | MCP | Memory
    description: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser
        from ..models.code_sandbox import CodeSandbox
        from ..models.mcp import MCP
        from ..models.memory import Memory

        spec: dict[str, Any]
        if isinstance(self.spec, Browser):
            spec = self.spec.to_dict()
        elif isinstance(self.spec, CodeSandbox):
            spec = self.spec.to_dict()
        elif isinstance(self.spec, MCP):
            spec = self.spec.to_dict()
        else:
            spec = self.spec.to_dict()

        description = self.description

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "spec": spec,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser
        from ..models.code_sandbox import CodeSandbox
        from ..models.mcp import MCP
        from ..models.memory import Memory

        d = dict(src_dict)

        def _parse_spec(data: object) -> Browser | CodeSandbox | MCP | Memory:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                spec_type_0 = Browser.from_dict(data)

                return spec_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                spec_type_1 = CodeSandbox.from_dict(data)

                return spec_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                spec_type_2 = MCP.from_dict(data)

                return spec_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            spec_type_3 = Memory.from_dict(data)

            return spec_type_3

        spec = _parse_spec(d.pop("spec"))

        description = d.pop("description", UNSET)

        update_environment = cls(
            spec=spec,
            description=description,
        )

        return update_environment
