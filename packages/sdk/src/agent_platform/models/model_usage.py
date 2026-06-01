from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="ModelUsage")


class ModelUsage(BaseModel):
    """Per-model token usage.

    Attributes:
        name (str):
        input_tokens (int):
        output_tokens (int):
        reasoning_tokens (int):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    name: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        input_tokens = self.input_tokens

        output_tokens = self.output_tokens

        reasoning_tokens = self.reasoning_tokens

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        input_tokens = d.pop("input_tokens")

        output_tokens = d.pop("output_tokens")

        reasoning_tokens = d.pop("reasoning_tokens")

        model_usage = cls(
            name=name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )

        model_usage.additional_properties = d
        return model_usage

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
