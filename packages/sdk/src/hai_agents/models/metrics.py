from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="Metrics")


class Metrics(BaseModel):
    """Metrics for a trajectory.

    Attributes:
        steps (int | Unset):  Default: 0.
        cost_per_model (list[ModelCost] | Unset):
        input_cost (float | None | Unset):
        output_cost (float | None | Unset):
        reasoning_cost (float | None | Unset):
        total_cost (float | None | Unset):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    steps: int | Unset = 0
    cost_per_model: list[ModelCost] | Unset = UNSET
    input_cost: float | None | Unset = UNSET
    output_cost: float | None | Unset = UNSET
    reasoning_cost: float | None | Unset = UNSET
    total_cost: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        from ..models.model_cost import ModelCost

        steps = self.steps

        cost_per_model: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.cost_per_model, Unset):
            cost_per_model = []
            for cost_per_model_item_data in self.cost_per_model:
                cost_per_model_item = cost_per_model_item_data.to_dict()
                cost_per_model.append(cost_per_model_item)

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
        field_dict.update({})
        if steps is not UNSET:
            field_dict["steps"] = steps
        if cost_per_model is not UNSET:
            field_dict["cost_per_model"] = cost_per_model
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
        from ..models.model_cost import ModelCost

        d = dict(src_dict)
        steps = d.pop("steps", UNSET)

        _cost_per_model = d.pop("cost_per_model", UNSET)
        cost_per_model: list[ModelCost] | Unset = UNSET
        if _cost_per_model is not UNSET:
            cost_per_model = []
            for cost_per_model_item_data in _cost_per_model:
                cost_per_model_item = ModelCost.from_dict(cost_per_model_item_data)

                cost_per_model.append(cost_per_model_item)

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

        metrics = cls(
            steps=steps,
            cost_per_model=cost_per_model,
            input_cost=input_cost,
            output_cost=output_cost,
            reasoning_cost=reasoning_cost,
            total_cost=total_cost,
        )

        metrics.additional_properties = d
        return metrics

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


from ..models.model_cost import ModelCost
