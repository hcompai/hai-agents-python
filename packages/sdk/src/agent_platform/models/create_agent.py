from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateAgent")


class CreateAgent(BaseModel):
    """``POST /api/v2/agents`` body.

    Attributes:
        spec (Agent): Declarative agent definition.
        reserved (bool | Unset): H employees only; rejected with 403 otherwise. Default: False.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    spec: Agent
    reserved: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent import Agent

        spec = self.spec.to_dict()

        reserved = self.reserved

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "spec": spec,
            }
        )
        if reserved is not UNSET:
            field_dict["reserved"] = reserved

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent import Agent

        d = dict(src_dict)
        spec = Agent.from_dict(d.pop("spec"))

        reserved = d.pop("reserved", UNSET)

        create_agent = cls(
            spec=spec,
            reserved=reserved,
        )

        return create_agent


from ..models.agent import Agent
