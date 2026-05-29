from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent import Agent


T = TypeVar("T", bound="AgentRecord")


class AgentRecord(BaseModel):
    """Catalog row exposing an ``Agent`` spec payload plus AgP metadata.

    The catalog handle is ``spec.name``; callers reference it directly
    via ``record.spec.name`` rather than a duplicated top-level field.

        Attributes:
            id (UUID):
            spec (Agent): Declarative agent definition.
            reserved (bool): True for H-owned rows; world-readable, write-locked behind employee_only.
            created_at (datetime.datetime):
            updated_at (datetime.datetime):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: UUID
    spec: Agent
    reserved: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent import Agent

        id = str(self.id)

        spec = self.spec.to_dict()

        reserved = self.reserved

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "spec": spec,
                "reserved": reserved,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent import Agent

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        spec = Agent.from_dict(d.pop("spec"))

        reserved = d.pop("reserved")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        agent_record = cls(
            id=id,
            spec=spec,
            reserved=reserved,
            created_at=created_at,
            updated_at=updated_at,
        )

        return agent_record
