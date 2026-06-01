from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateSkill")


class CreateSkill(BaseModel):
    """Request to create a skill.

    Attributes:
        name (str): Kebab-case stable handle the agent uses to reference this skill.
        description (str): One-line routing hint shown in the skill catalog.
        body (str | Unset): Markdown prompt fragment. Required unless `uri` is set. Default: ''.
        source (None | str | Unset): Provenance URL.
        url_pattern (None | str | Unset): Inject only when an observation URL matches this regex. Mutually exclusive
            with `uri`.
        uri (None | str | Unset): Fetch body on demand from this location. Mutually exclusive with `url_pattern`.
        reserved (bool | Unset): H employees only; rejected with 403 otherwise. Reserved rows are world-readable.
            Default: False.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    name: str
    description: str
    body: str | Unset = ""
    source: None | str | Unset = UNSET
    url_pattern: None | str | Unset = UNSET
    uri: None | str | Unset = UNSET
    reserved: bool | Unset = False
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        name = self.name

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

        reserved = self.reserved

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
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
        if reserved is not UNSET:
            field_dict["reserved"] = reserved

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

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

        reserved = d.pop("reserved", UNSET)

        create_skill = cls(
            name=name,
            description=description,
            body=body,
            source=source,
            url_pattern=url_pattern,
            uri=uri,
            reserved=reserved,
        )

        create_skill.additional_properties = d
        return create_skill

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
