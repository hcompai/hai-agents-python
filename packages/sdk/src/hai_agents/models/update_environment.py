from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="UpdateEnvironment")


class UpdateEnvironment(BaseModel):
    """``PUT /api/v2/environments/{env_identifier}`` body. Full replace; ``spec.id`` is immutable.

    Attributes:
        spec (Browser): Browser environment.
        description (str | Unset):  Default: ''.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    spec: Browser
    description: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser

        spec = self.spec.to_dict()

        description = self.description

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "spec": spec,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser

        d = dict(src_dict)
        spec = Browser.from_dict(d.pop("spec"))

        description = d.pop("description", UNSET)

        update_environment = cls(
            spec=spec,
            description=description,
        )

        return update_environment


from ..models.browser import Browser
