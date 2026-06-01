from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="Browser")


class Browser(BaseModel):
    """Browser environment.

    Attributes:
        id (str): Catalog id.
        headless (bool): Run without a visible window.
        width (int): Viewport width in pixels.
        height (int): Viewport height in pixels.
        start_url (None | str): Initial URL.
        kind (Literal['web'] | Unset):  Default: 'web'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    id: str
    headless: bool
    width: int
    height: int
    start_url: None | str
    kind: Literal["web"] | Unset = "web"

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        headless = self.headless

        width = self.width

        height = self.height

        start_url: None | str
        start_url = self.start_url

        kind = self.kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "headless": headless,
                "width": width,
                "height": height,
                "start_url": start_url,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        headless = d.pop("headless")

        width = d.pop("width")

        height = d.pop("height")

        def _parse_start_url(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        start_url = _parse_start_url(d.pop("start_url"))

        kind = cast(Literal["web"] | Unset, d.pop("kind", UNSET))
        if kind != "web" and not isinstance(kind, Unset):
            raise ValueError(f"kind must match const 'web', got '{kind}'")

        browser = cls(
            id=id,
            headless=headless,
            width=width,
            height=height,
            start_url=start_url,
            kind=kind,
        )

        return browser
