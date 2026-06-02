from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..models.trajectory_status import TrajectoryStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="TrajectoryChanges")


class TrajectoryChanges(BaseModel):
    """Changes to a trajectory.

    This represents a batch of updates returned by the polling API
    when checking for new events and status changes on a trajectory.

    Used to incrementally fetch new events without
    re-downloading the entire trajectory history.

    Attributes:
        status: Current status of the trajectory
        started_at: When the trajectory started execution (None if not yet started)
        finished_at: When the trajectory finished (None if still running)
        error: Error message if trajectory failed (None if no error)
        new_events: List of new events since the last poll (empty if no new events)
        answer: Answer to the trajectory (None if not available)

        Attributes:
            status (TrajectoryStatus): State of a session/trajectory.

                Lifecycle::

                    PENDING → RUNNING → {COMPLETED, FAILED, TIMED_OUT, INTERRUPTED}
                       |        ↑  ↑
                       |        |  └─────→ IDLE (interactive: agent waiting for next task)
                       |        ↓
                       └─────→ PAUSED
            started_at (datetime.datetime | None | Unset):
            finished_at (datetime.datetime | None | Unset):
            error (None | str | Unset):
            new_events (list[TrajectoryEvent] | Unset):
            answer (None | str | TrajectoryChangesAnswerType1 | Unset):
            metrics (Metrics | Unset): Rolled-up usage and cost for a session.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    status: TrajectoryStatus
    started_at: datetime.datetime | None | Unset = UNSET
    finished_at: datetime.datetime | None | Unset = UNSET
    error: None | str | Unset = UNSET
    new_events: list[TrajectoryEvent] | Unset = UNSET
    answer: None | str | TrajectoryChangesAnswerType1 | Unset = UNSET
    metrics: Metrics | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        from ..models.metrics import Metrics
        from ..models.trajectory_changes_answer_type_1 import TrajectoryChangesAnswerType1
        from ..models.trajectory_event import TrajectoryEvent

        status = self.status.value

        started_at: None | str | Unset
        if isinstance(self.started_at, Unset):
            started_at = UNSET
        elif isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        finished_at: None | str | Unset
        if isinstance(self.finished_at, Unset):
            finished_at = UNSET
        elif isinstance(self.finished_at, datetime.datetime):
            finished_at = self.finished_at.isoformat()
        else:
            finished_at = self.finished_at

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        new_events: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.new_events, Unset):
            new_events = []
            for new_events_item_data in self.new_events:
                new_events_item = new_events_item_data.to_dict()
                new_events.append(new_events_item)

        answer: dict[str, Any] | None | str | Unset
        if isinstance(self.answer, Unset):
            answer = UNSET
        elif isinstance(self.answer, TrajectoryChangesAnswerType1):
            answer = self.answer.to_dict()
        else:
            answer = self.answer

        metrics: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metrics, Unset):
            metrics = self.metrics.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "status": status,
            }
        )
        if started_at is not UNSET:
            field_dict["started_at"] = started_at
        if finished_at is not UNSET:
            field_dict["finished_at"] = finished_at
        if error is not UNSET:
            field_dict["error"] = error
        if new_events is not UNSET:
            field_dict["new_events"] = new_events
        if answer is not UNSET:
            field_dict["answer"] = answer
        if metrics is not UNSET:
            field_dict["metrics"] = metrics

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.metrics import Metrics
        from ..models.trajectory_changes_answer_type_1 import TrajectoryChangesAnswerType1
        from ..models.trajectory_event import TrajectoryEvent

        d = dict(src_dict)
        status = TrajectoryStatus(d.pop("status"))

        def _parse_started_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = isoparse(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        started_at = _parse_started_at(d.pop("started_at", UNSET))

        def _parse_finished_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                finished_at_type_0 = isoparse(data)

                return finished_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        finished_at = _parse_finished_at(d.pop("finished_at", UNSET))

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        _new_events = d.pop("new_events", UNSET)
        new_events: list[TrajectoryEvent] | Unset = UNSET
        if _new_events is not UNSET:
            new_events = []
            for new_events_item_data in _new_events:
                new_events_item = TrajectoryEvent.from_dict(new_events_item_data)

                new_events.append(new_events_item)

        def _parse_answer(data: object) -> None | str | TrajectoryChangesAnswerType1 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                answer_type_1 = TrajectoryChangesAnswerType1.from_dict(data)

                return answer_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | str | TrajectoryChangesAnswerType1 | Unset, data)

        answer = _parse_answer(d.pop("answer", UNSET))

        _metrics = d.pop("metrics", UNSET)
        metrics: Metrics | Unset
        if isinstance(_metrics, Unset):
            metrics = UNSET
        else:
            metrics = Metrics.from_dict(_metrics)

        trajectory_changes = cls(
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
            new_events=new_events,
            answer=answer,
            metrics=metrics,
        )

        trajectory_changes.additional_properties = d
        return trajectory_changes

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


from ..models.metrics import Metrics
from ..models.trajectory_changes_answer_type_1 import TrajectoryChangesAnswerType1
from ..models.trajectory_event import TrajectoryEvent
