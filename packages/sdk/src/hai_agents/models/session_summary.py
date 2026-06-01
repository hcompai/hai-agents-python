from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..models.trajectory_status import TrajectoryStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="SessionSummary")


class SessionSummary(BaseModel):
    """Flat projection for session listings.

    Attributes:
        id (UUID):
        status (TrajectoryStatus): State of a session/trajectory.

            Lifecycle::

                PENDING → RUNNING → {COMPLETED, FAILED, TIMED_OUT, INTERRUPTED}
                   |        ↑  ↑
                   |        |  └─────→ IDLE (interactive: agent waiting for next task)
                   |        ↓
                   └─────→ PAUSED
        created_at (datetime.datetime):
        first_message (None | Unset | UserMessageEvent):
        started_at (datetime.datetime | None | Unset):
        finished_at (datetime.datetime | None | Unset):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    id: UUID
    status: TrajectoryStatus
    created_at: datetime.datetime
    first_message: None | Unset | UserMessageEvent = UNSET
    started_at: datetime.datetime | None | Unset = UNSET
    finished_at: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.user_message_event import UserMessageEvent

        id = str(self.id)

        status = self.status.value

        created_at = self.created_at.isoformat()

        first_message: dict[str, Any] | None | Unset
        if isinstance(self.first_message, Unset):
            first_message = UNSET
        elif isinstance(self.first_message, UserMessageEvent):
            first_message = self.first_message.to_dict()
        else:
            first_message = self.first_message

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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "status": status,
                "created_at": created_at,
            }
        )
        if first_message is not UNSET:
            field_dict["first_message"] = first_message
        if started_at is not UNSET:
            field_dict["started_at"] = started_at
        if finished_at is not UNSET:
            field_dict["finished_at"] = finished_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.user_message_event import UserMessageEvent

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        status = TrajectoryStatus(d.pop("status"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_first_message(data: object) -> None | Unset | UserMessageEvent:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                first_message_type_0 = UserMessageEvent.from_dict(data)

                return first_message_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UserMessageEvent, data)

        first_message = _parse_first_message(d.pop("first_message", UNSET))

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

        session_summary = cls(
            id=id,
            status=status,
            created_at=created_at,
            first_message=first_message,
            started_at=started_at,
            finished_at=finished_at,
        )

        return session_summary


from ..models.user_message_event import UserMessageEvent
