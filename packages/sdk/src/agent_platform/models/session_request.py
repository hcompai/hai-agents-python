from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="SessionRequest")


class SessionRequest(BaseModel):
    """``POST /api/v2/sessions`` body.

    Attributes:
        agent (Agent | str): Catalog id or inline Agent. Carries its own environments.
        messages (list[UserMessageEvent] | None | str | Unset | UserMessageEvent): Queued before turn 1. Accepts a
            string, a single UserMessageEvent, or a list.
        max_steps (int | None | Unset): Cap on policy calls; runtime default if null.
        max_time_s (float | None | Unset): Cap on wall-clock seconds.
        idle_timeout_s (int | None | Unset): Idle window before auto-termination; null terminates on Answer.
        group_id (None | str | Unset): Group id for cascading and listing.
        parent_session_id (None | str | Unset): Parent session id.
        answer_format (None | SessionRequestAnswerFormatType0 | Unset): JSON Schema the final answer must conform to.
            Null returns free-form text.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    agent: Agent | str
    messages: list[UserMessageEvent] | None | str | Unset | UserMessageEvent = UNSET
    max_steps: int | None | Unset = UNSET
    max_time_s: float | None | Unset = UNSET
    idle_timeout_s: int | None | Unset = UNSET
    group_id: None | str | Unset = UNSET
    parent_session_id: None | str | Unset = UNSET
    answer_format: None | SessionRequestAnswerFormatType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent import Agent
        from ..models.session_request_answer_format_type_0 import SessionRequestAnswerFormatType0
        from ..models.user_message_event import UserMessageEvent

        agent: dict[str, Any] | str
        if isinstance(self.agent, Agent):
            agent = self.agent.to_dict()
        else:
            agent = self.agent

        messages: dict[str, Any] | list[dict[str, Any]] | None | str | Unset
        if isinstance(self.messages, Unset):
            messages = UNSET
        elif isinstance(self.messages, UserMessageEvent):
            messages = self.messages.to_dict()
        elif isinstance(self.messages, list):
            messages = []
            for messages_type_2_item_data in self.messages:
                messages_type_2_item = messages_type_2_item_data.to_dict()
                messages.append(messages_type_2_item)

        else:
            messages = self.messages

        max_steps: int | None | Unset
        if isinstance(self.max_steps, Unset):
            max_steps = UNSET
        else:
            max_steps = self.max_steps

        max_time_s: float | None | Unset
        if isinstance(self.max_time_s, Unset):
            max_time_s = UNSET
        else:
            max_time_s = self.max_time_s

        idle_timeout_s: int | None | Unset
        if isinstance(self.idle_timeout_s, Unset):
            idle_timeout_s = UNSET
        else:
            idle_timeout_s = self.idle_timeout_s

        group_id: None | str | Unset
        if isinstance(self.group_id, Unset):
            group_id = UNSET
        else:
            group_id = self.group_id

        parent_session_id: None | str | Unset
        if isinstance(self.parent_session_id, Unset):
            parent_session_id = UNSET
        else:
            parent_session_id = self.parent_session_id

        answer_format: dict[str, Any] | None | Unset
        if isinstance(self.answer_format, Unset):
            answer_format = UNSET
        elif isinstance(self.answer_format, SessionRequestAnswerFormatType0):
            answer_format = self.answer_format.to_dict()
        else:
            answer_format = self.answer_format

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent": agent,
            }
        )
        if messages is not UNSET:
            field_dict["messages"] = messages
        if max_steps is not UNSET:
            field_dict["max_steps"] = max_steps
        if max_time_s is not UNSET:
            field_dict["max_time_s"] = max_time_s
        if idle_timeout_s is not UNSET:
            field_dict["idle_timeout_s"] = idle_timeout_s
        if group_id is not UNSET:
            field_dict["group_id"] = group_id
        if parent_session_id is not UNSET:
            field_dict["parent_session_id"] = parent_session_id
        if answer_format is not UNSET:
            field_dict["answer_format"] = answer_format

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.agent import Agent
        from ..models.session_request_answer_format_type_0 import SessionRequestAnswerFormatType0
        from ..models.user_message_event import UserMessageEvent

        d = dict(src_dict)

        def _parse_agent(data: object) -> Agent | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                agent_type_1 = Agent.from_dict(data)

                return agent_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Agent | str, data)

        agent = _parse_agent(d.pop("agent"))

        def _parse_messages(data: object) -> list[UserMessageEvent] | None | str | Unset | UserMessageEvent:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                messages_type_1 = UserMessageEvent.from_dict(data)

                return messages_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, list):
                    raise TypeError()
                messages_type_2 = []
                _messages_type_2 = data
                for messages_type_2_item_data in _messages_type_2:
                    messages_type_2_item = UserMessageEvent.from_dict(messages_type_2_item_data)

                    messages_type_2.append(messages_type_2_item)

                return messages_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[UserMessageEvent] | None | str | Unset | UserMessageEvent, data)

        messages = _parse_messages(d.pop("messages", UNSET))

        def _parse_max_steps(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_steps = _parse_max_steps(d.pop("max_steps", UNSET))

        def _parse_max_time_s(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_time_s = _parse_max_time_s(d.pop("max_time_s", UNSET))

        def _parse_idle_timeout_s(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        idle_timeout_s = _parse_idle_timeout_s(d.pop("idle_timeout_s", UNSET))

        def _parse_group_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        group_id = _parse_group_id(d.pop("group_id", UNSET))

        def _parse_parent_session_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        parent_session_id = _parse_parent_session_id(d.pop("parent_session_id", UNSET))

        def _parse_answer_format(data: object) -> None | SessionRequestAnswerFormatType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                answer_format_type_0 = SessionRequestAnswerFormatType0.from_dict(data)

                return answer_format_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SessionRequestAnswerFormatType0 | Unset, data)

        answer_format = _parse_answer_format(d.pop("answer_format", UNSET))

        session_request = cls(
            agent=agent,
            messages=messages,
            max_steps=max_steps,
            max_time_s=max_time_s,
            idle_timeout_s=idle_timeout_s,
            group_id=group_id,
            parent_session_id=parent_session_id,
            answer_format=answer_format,
        )

        return session_request


from ..models.agent import Agent
from ..models.session_request_answer_format_type_0 import SessionRequestAnswerFormatType0
from ..models.user_message_event import UserMessageEvent
