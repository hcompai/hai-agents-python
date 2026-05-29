from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from dateutil.parser import isoparse
from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="TrajectoryEvent")


class TrajectoryEvent(BaseModel):
    """Event from a trajectory.

    Unified from agp_client and agent_platform.
    Uses the richer agent_platform version with screenshot serialization.

    Events represent individual actions, observations, or state changes during
    trajectory execution. They form a chronological log of everything that happened.

    Common event types:
    - AgentStartedEvent: Agent begins execution
    - AgentCompletionEvent: Agent finishes successfully
    - AgentErrorEvent: Agent encounters an error
    - AgentEvent: Generic wrapper for agent-emitted events (policy_event, tool_result, observation_event)
    - LiveViewUrlEvent: Live view URL becomes available
    - ChatMessageEvent: Agent sends a chat message

    Attributes:
        type: The type/name of the event (e.g., "AgentStartedEvent", "AgentEvent")
        data: Event-specific data payload (structure varies by event type)
        timestamp: When the event occurred

        Attributes:
            type_ (str):
            data (Any):
            timestamp (datetime.datetime):
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    type_: str
    data: Any
    timestamp: datetime.datetime
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        data = self.data

        timestamp = self.timestamp.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "data": data,
                "timestamp": timestamp,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = d.pop("type")

        data = d.pop("data")

        timestamp = isoparse(d.pop("timestamp"))

        trajectory_event = cls(
            type_=type_,
            data=data,
            timestamp=timestamp,
        )

        trajectory_event.additional_properties = d
        return trajectory_event

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
