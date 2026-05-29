from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar

from pydantic import BaseModel, ConfigDict

from ..models.quota_status_scope import QuotaStatusScope
from ..types import UNSET, Unset

T = TypeVar("T", bound="QuotaStatus")


class QuotaStatus(BaseModel):
    """Quota status.

    Attributes:
        scope (QuotaStatusScope):
        limit (int):
        active (int):
        available (int):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    scope: QuotaStatusScope
    limit: int
    active: int
    available: int
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        scope = self.scope.value

        limit = self.limit

        active = self.active

        available = self.available

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "scope": scope,
                "limit": limit,
                "active": active,
                "available": available,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        scope = QuotaStatusScope(d.pop("scope"))

        limit = d.pop("limit")

        active = d.pop("active")

        available = d.pop("available")

        quota_status = cls(
            scope=scope,
            limit=limit,
            active=active,
            available=available,
        )

        quota_status.additional_properties = d
        return quota_status

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
