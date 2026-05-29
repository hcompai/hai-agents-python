from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="MemoryRecord")


class MemoryRecord(BaseModel):
    """Persistent KV entry scoped to ``(org_id, namespace, key)``.

    Attributes:
        id (UUID):
        namespace (str):
        key (str):
        value (str):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: UUID
    namespace: str
    key: str
    value: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        namespace = self.namespace

        key = self.key

        value = self.value

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "namespace": namespace,
                "key": key,
                "value": value,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        namespace = d.pop("namespace")

        key = d.pop("key")

        value = d.pop("value")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        memory_record = cls(
            id=id,
            namespace=namespace,
            key=key,
            value=value,
            created_at=created_at,
            updated_at=updated_at,
        )

        memory_record.additional_properties = d
        return memory_record

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
