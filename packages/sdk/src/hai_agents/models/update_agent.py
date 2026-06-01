from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="UpdateAgent")


class UpdateAgent(BaseModel):
    """``PUT /api/v2/agents/{agent_identifier}`` body. Full replace; ``spec.name`` is immutable.

    Attributes:
        spec (Agent): Declarative agent definition.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    spec: Agent

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent import Agent

        spec = self.spec.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "spec": spec,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent import Agent

        d = dict(src_dict)
        spec = Agent.from_dict(d.pop("spec"))

        update_agent = cls(
            spec=spec,
        )

        return update_agent


from ..models.agent import Agent
