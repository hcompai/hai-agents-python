from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="EnvironmentRecord")


class EnvironmentRecord(BaseModel):
    """Catalog row exposing an ``Environment`` spec plus AgP metadata.

    The catalog handle is ``spec.id``; callers reference it directly via
    ``record.spec.id`` rather than a duplicated top-level field.

        Attributes:
            id (UUID):
            spec (Browser): Browser environment.
            reserved (bool): True for H-owned rows; world-readable, write-locked behind employee_only.
            created_at (datetime.datetime):
            updated_at (datetime.datetime):
            description (str | Unset):  Default: ''.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    id: UUID
    spec: Browser
    reserved: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    description: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser

        id = str(self.id)

        spec = self.spec.to_dict()

        reserved = self.reserved

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        description = self.description

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
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        spec = Browser.from_dict(d.pop("spec"))

        reserved = d.pop("reserved")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        description = d.pop("description", UNSET)

        environment_record = cls(
            id=id,
            spec=spec,
            reserved=reserved,
            created_at=created_at,
            updated_at=updated_at,
            description=description,
        )

        return environment_record


from ..models.browser import Browser
