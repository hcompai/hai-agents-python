from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="Skill")


class Skill(BaseModel):
    """Named instruction content. Loaded by name via ``load_skill`` or rendered inline by toolboxes.

    Attributes:
        name (str): Catalog id. Format: lowercase ASCII letters, digits and hyphens; must start and end with
            alphanumeric; max 63 chars per segment; optional single 'org/' namespace prefix (e.g. 'h/web-environment').
        description (str): One-line routing hint.
        body (str): Markdown content.
        source (None | str | Unset): Provenance URL.
        url_pattern (None | str | Unset): Informational regex hinting at URLs where this skill applies (not gated).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    name: str
    description: str
    body: str
    source: None | str | Unset = UNSET
    url_pattern: None | str | Unset = UNSET

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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "description": description,
                "body": body,
            }
        )
        if source is not UNSET:
            field_dict["source"] = source
        if url_pattern is not UNSET:
            field_dict["url_pattern"] = url_pattern

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        description = d.pop("description")

        body = d.pop("body")

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

        skill = cls(
            name=name,
            description=description,
            body=body,
            source=source,
            url_pattern=url_pattern,
        )

        return skill
