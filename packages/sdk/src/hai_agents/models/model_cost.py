from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="ModelCost")


class ModelCost(BaseModel):
    """Token usage and cost for a single model.

    Attributes:
        name (str): Model id.
        input_tokens (int): Input tokens consumed.
        output_tokens (int): Output tokens produced.
        reasoning_tokens (int): Reasoning tokens produced.
        input_cost (float | None | Unset): Input cost in USD; null if the model is unpriced.
        output_cost (float | None | Unset): Output cost in USD; null if the model is unpriced.
        reasoning_cost (float | None | Unset): Reasoning cost in USD; null if the model is unpriced.
        total_cost (float | None | Unset): Total cost in USD; null if the model is unpriced.
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
    input_cost: float | None | Unset = UNSET
    output_cost: float | None | Unset = UNSET
    reasoning_cost: float | None | Unset = UNSET
    total_cost: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        input_tokens = self.input_tokens

        output_tokens = self.output_tokens

        reasoning_tokens = self.reasoning_tokens

        input_cost: float | None | Unset
        if isinstance(self.input_cost, Unset):
            input_cost = UNSET
        else:
            input_cost = self.input_cost

        output_cost: float | None | Unset
        if isinstance(self.output_cost, Unset):
            output_cost = UNSET
        else:
            output_cost = self.output_cost

        reasoning_cost: float | None | Unset
        if isinstance(self.reasoning_cost, Unset):
            reasoning_cost = UNSET
        else:
            reasoning_cost = self.reasoning_cost

        total_cost: float | None | Unset
        if isinstance(self.total_cost, Unset):
            total_cost = UNSET
        else:
            total_cost = self.total_cost

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
        if input_cost is not UNSET:
            field_dict["input_cost"] = input_cost
        if output_cost is not UNSET:
            field_dict["output_cost"] = output_cost
        if reasoning_cost is not UNSET:
            field_dict["reasoning_cost"] = reasoning_cost
        if total_cost is not UNSET:
            field_dict["total_cost"] = total_cost

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        input_tokens = d.pop("input_tokens")

        output_tokens = d.pop("output_tokens")

        reasoning_tokens = d.pop("reasoning_tokens")

        def _parse_input_cost(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        input_cost = _parse_input_cost(d.pop("input_cost", UNSET))

        def _parse_output_cost(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        output_cost = _parse_output_cost(d.pop("output_cost", UNSET))

        def _parse_reasoning_cost(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        reasoning_cost = _parse_reasoning_cost(d.pop("reasoning_cost", UNSET))

        def _parse_total_cost(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        total_cost = _parse_total_cost(d.pop("total_cost", UNSET))

        model_cost = cls(
            name=name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            reasoning_cost=reasoning_cost,
            total_cost=total_cost,
        )

        model_cost.additional_properties = d
        return model_cost

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
