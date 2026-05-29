from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="ShareLink")


class ShareLink(BaseModel):
    """Public share URL for a session.

    ``share_url`` is a path; clients prepend the AgP host. Today this points at the
    v1 share router (``/share/api/v1/trajectories/{id}``); will migrate to
    ``/share/v1/sessions/{id}`` once the v2 share router lands.

        Attributes:
            share_url (str):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    share_url: str

    def to_dict(self) -> dict[str, Any]:
        share_url = self.share_url

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "share_url": share_url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        share_url = d.pop("share_url")

        share_link = cls(
            share_url=share_url,
        )

        return share_link
