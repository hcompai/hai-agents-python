from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..models.browser_mode import BrowserMode
from ..types import UNSET, Unset

T = TypeVar("T", bound="Browser")


class Browser(BaseModel):
    """A local web browser the agent navigates and acts on.

    Attributes:
        id (str): Catalog identifier for this environment.
        headless (bool): Run without a visible window.
        width (int): Viewport width in pixels.
        height (int): Viewport height in pixels.
        start_url (None | str): Initial URL to open. Null starts on a blank page.
        kind (Literal['web'] | Unset):  Default: 'web'.
        mode (BrowserMode | Unset): How the agent perceives and drives the browser. 'visual': act on screenshots by
            viewport coordinates. 'multimodal': the same, with the page also included as markdown text alongside each
            screenshot. 'text': read-only markdown with URL navigation, no screenshots. Default: BrowserMode.VISUAL.
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
    mode: BrowserMode | Unset = BrowserMode.VISUAL
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        headless = self.headless

        width = self.width

        height = self.height

        start_url: None | str
        start_url = self.start_url

        kind = self.kind

        mode: str | Unset = UNSET
        if not isinstance(self.mode, Unset):
            mode = self.mode.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
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
        if mode is not UNSET:
            field_dict["mode"] = mode

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

        _mode = d.pop("mode", UNSET)
        mode: BrowserMode | Unset
        if isinstance(_mode, Unset):
            mode = UNSET
        else:
            mode = BrowserMode(_mode)

        browser = cls(
            id=id,
            headless=headless,
            width=width,
            height=height,
            start_url=start_url,
            kind=kind,
            mode=mode,
        )

        browser.additional_properties = d
        return browser

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
