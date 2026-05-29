from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..models.trajectory_status import TrajectoryStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.model_usage import ModelUsage


T = TypeVar("T", bound="SessionStatus")


class SessionStatus(BaseModel):
    """``GET /api/v2/sessions/{id}/status`` response.

    Attributes:
        status (TrajectoryStatus): State of a session/trajectory.

            Lifecycle::

                PENDING → RUNNING → {COMPLETED, FAILED, TIMED_OUT, INTERRUPTED}
                   |        ↑  ↑
                   |        |  └─────→ IDLE (interactive: agent waiting for next task)
                   |        ↓
                   └─────→ PAUSED
        error (None | str | Unset):
        steps (int | Unset):  Default: 0.
        usage_per_model (list[ModelUsage] | Unset):
        subagent_session_ids (list[UUID] | Unset):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    status: TrajectoryStatus
    error: None | str | Unset = UNSET
    steps: int | Unset = 0
    usage_per_model: list[ModelUsage] | Unset = UNSET
    subagent_session_ids: list[UUID] | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        from ..models.model_usage import ModelUsage

        status = self.status.value

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        steps = self.steps

        usage_per_model: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.usage_per_model, Unset):
            usage_per_model = []
            for usage_per_model_item_data in self.usage_per_model:
                usage_per_model_item = usage_per_model_item_data.to_dict()
                usage_per_model.append(usage_per_model_item)

        subagent_session_ids: list[str] | Unset = UNSET
        if not isinstance(self.subagent_session_ids, Unset):
            subagent_session_ids = []
            for subagent_session_ids_item_data in self.subagent_session_ids:
                subagent_session_ids_item = str(subagent_session_ids_item_data)
                subagent_session_ids.append(subagent_session_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "status": status,
            }
        )
        if error is not UNSET:
            field_dict["error"] = error
        if steps is not UNSET:
            field_dict["steps"] = steps
        if usage_per_model is not UNSET:
            field_dict["usage_per_model"] = usage_per_model
        if subagent_session_ids is not UNSET:
            field_dict["subagent_session_ids"] = subagent_session_ids

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.model_usage import ModelUsage

        d = dict(src_dict)
        status = TrajectoryStatus(d.pop("status"))

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        steps = d.pop("steps", UNSET)

        _usage_per_model = d.pop("usage_per_model", UNSET)
        usage_per_model: list[ModelUsage] | Unset = UNSET
        if _usage_per_model is not UNSET:
            usage_per_model = []
            for usage_per_model_item_data in _usage_per_model:
                usage_per_model_item = ModelUsage.from_dict(usage_per_model_item_data)

                usage_per_model.append(usage_per_model_item)

        _subagent_session_ids = d.pop("subagent_session_ids", UNSET)
        subagent_session_ids: list[UUID] | Unset = UNSET
        if _subagent_session_ids is not UNSET:
            subagent_session_ids = []
            for subagent_session_ids_item_data in _subagent_session_ids:
                subagent_session_ids_item = UUID(subagent_session_ids_item_data)

                subagent_session_ids.append(subagent_session_ids_item)

        session_status = cls(
            status=status,
            error=error,
            steps=steps,
            usage_per_model=usage_per_model,
            subagent_session_ids=subagent_session_ids,
        )

        session_status.additional_properties = d
        return session_status

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
