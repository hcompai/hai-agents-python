from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="UpdateSkill")


class UpdateSkill(BaseModel):
    """Request to update a skill. Full replacement; `name` is immutable.

    Attributes:
        description (str):
        body (str | Unset):  Default: ''.
        source (None | str | Unset):
        url_pattern (None | str | Unset):
        uri (None | str | Unset):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    description: str
    body: str | Unset = ""
    source: None | str | Unset = UNSET
    url_pattern: None | str | Unset = UNSET
    uri: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        body = self.body

        source: None | str | Unset
        if isinstance(self.source, Unset):
            source = UNSET
        else:
            source = self.source

        url_pattern: None | str | Unset
        if isinstance(self.url_pattern, Unset):
            url_pattern = UNSET
        else:
            url_pattern = self.url_pattern

        uri: None | str | Unset
        if isinstance(self.uri, Unset):
            uri = UNSET
        else:
            uri = self.uri

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "description": description,
            }
        )
        if body is not UNSET:
            field_dict["body"] = body
        if source is not UNSET:
            field_dict["source"] = source
        if url_pattern is not UNSET:
            field_dict["url_pattern"] = url_pattern
        if uri is not UNSET:
            field_dict["uri"] = uri

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        description = d.pop("description")

        body = d.pop("body", UNSET)

        def _parse_source(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source = _parse_source(d.pop("source", UNSET))

        def _parse_url_pattern(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        url_pattern = _parse_url_pattern(d.pop("url_pattern", UNSET))

        def _parse_uri(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        uri = _parse_uri(d.pop("uri", UNSET))

        update_skill = cls(
            description=description,
            body=body,
            source=source,
            url_pattern=url_pattern,
            uri=uri,
        )

        update_skill.additional_properties = d
        return update_skill

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
