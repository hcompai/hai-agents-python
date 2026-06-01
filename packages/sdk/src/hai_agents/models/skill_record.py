from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="SkillRecord")


class SkillRecord(BaseModel):
    """Named prompt fragment loaded into an agent's system prompt.

    Attributes:
        id (UUID):
        name (str):
        description (str):
        body (str):
        source (None | str):
        url_pattern (None | str):
        uri (None | str):
        reserved (bool):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    id: UUID
    name: str
    description: str
    body: str
    source: None | str
    url_pattern: None | str
    uri: None | str
    reserved: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        name = self.name

        description = self.description

        body = self.body

        source: None | str
        source = self.source

        url_pattern: None | str
        url_pattern = self.url_pattern

        uri: None | str
        uri = self.uri

        reserved = self.reserved

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "description": description,
                "body": body,
                "source": source,
                "url_pattern": url_pattern,
                "uri": uri,
                "reserved": reserved,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        name = d.pop("name")

        description = d.pop("description")

        body = d.pop("body")

        def _parse_source(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source = _parse_source(d.pop("source"))

        def _parse_url_pattern(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        url_pattern = _parse_url_pattern(d.pop("url_pattern"))

        def _parse_uri(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        uri = _parse_uri(d.pop("uri"))

        reserved = d.pop("reserved")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        skill_record = cls(
            id=id,
            name=name,
            description=description,
            body=body,
            source=source,
            url_pattern=url_pattern,
            uri=uri,
            reserved=reserved,
            created_at=created_at,
            updated_at=updated_at,
        )

        skill_record.additional_properties = d
        return skill_record

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
