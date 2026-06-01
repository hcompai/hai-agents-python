from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar(
    "T", bound="PageAnnotatedUnionBrowserCodeSandboxMCPMemoryFieldInfoannotationNoneTypeRequiredTrueDiscriminatorkind"
)


class PageAnnotatedUnionBrowserCodeSandboxMCPMemoryFieldInfoannotationNoneTypeRequiredTrueDiscriminatorkind(BaseModel):
    """
    Attributes:
        items (list[Browser]):
        total (int):
        page (int):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    items: list[Browser]
    total: int
    page: int
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser

        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        total = self.total

        page = self.page

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "total": total,
                "page": page,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = Browser.from_dict(items_item_data)

            items.append(items_item)

        total = d.pop("total")

        page = d.pop("page")

        page_annotated_union_browser_code_sandbox_mcp_memory_field_infoannotation_none_type_required_true_discriminatorkind = cls(
            items=items,
            total=total,
            page=page,
        )

        page_annotated_union_browser_code_sandbox_mcp_memory_field_infoannotation_none_type_required_true_discriminatorkind.additional_properties = d
        return page_annotated_union_browser_code_sandbox_mcp_memory_field_infoannotation_none_type_required_true_discriminatorkind

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


from ..models.browser import Browser
