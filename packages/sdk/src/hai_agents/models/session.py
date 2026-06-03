from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast
from uuid import UUID

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="Session")


class Session(BaseModel):
    """Full session envelope: original request + live status.

    Attributes:
        id (UUID):
        request (SessionRequest): ``POST /api/v2/sessions`` body.
        status (SessionStatus): ``GET /api/v2/sessions/{id}/status`` response.
        created_at (datetime.datetime):
        latest_answer (Any | Unset): The agent's most recent final answer: free-form text, or structured data when the
            agent runs with a custom answer format. Null until the agent first answers. Mirrors the answer streamed from the
            changes endpoint, surfaced here for non-interactive runs.
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
    request: SessionRequest
    status: SessionStatus
    created_at: datetime.datetime
    latest_answer: Any | Unset = UNSET
    started_at: datetime.datetime | None | Unset = UNSET
    finished_at: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.session_request import SessionRequest
        from ..models.session_status import SessionStatus

        id = str(self.id)

        request = self.request.to_dict()

        status = self.status.to_dict()

        created_at = self.created_at.isoformat()

        latest_answer = self.latest_answer

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
                "request": request,
                "status": status,
                "created_at": created_at,
            }
        )
        if latest_answer is not UNSET:
            field_dict["latest_answer"] = latest_answer
        if started_at is not UNSET:
            field_dict["started_at"] = started_at
        if finished_at is not UNSET:
            field_dict["finished_at"] = finished_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.session_request import SessionRequest
        from ..models.session_status import SessionStatus

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        request = SessionRequest.from_dict(d.pop("request"))

        status = SessionStatus.from_dict(d.pop("status"))

        created_at = isoparse(d.pop("created_at"))

        latest_answer = d.pop("latest_answer", UNSET)

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

        session = cls(
            id=id,
            request=request,
            status=status,
            created_at=created_at,
            latest_answer=latest_answer,
            started_at=started_at,
            finished_at=finished_at,
        )

        return session


from ..models.session_request import SessionRequest
from ..models.session_status import SessionStatus
