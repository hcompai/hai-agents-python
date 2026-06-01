from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateEnvironment")


class CreateEnvironment(BaseModel):
    """``POST /api/v2/environments`` body.

    Attributes:
        spec (Browser): Browser environment.
        description (str | Unset):  Default: ''.
        reserved (bool | Unset): H employees only; rejected with 403 otherwise. Default: False.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    spec: Browser
    description: str | Unset = ""
    reserved: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser

        spec = self.spec.to_dict()

        description = self.description

        reserved = self.reserved

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "spec": spec,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if reserved is not UNSET:
            field_dict["reserved"] = reserved

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser

        d = dict(src_dict)
        spec = Browser.from_dict(d.pop("spec"))

        description = d.pop("description", UNSET)

        reserved = d.pop("reserved", UNSET)

        create_environment = cls(
            spec=spec,
            description=description,
            reserved=reserved,
        )

        return create_environment


from ..models.browser import Browser
