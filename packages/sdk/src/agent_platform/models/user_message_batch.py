from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.user_message_event import UserMessageEvent


T = TypeVar("T", bound="UserMessageBatch")


class UserMessageBatch(BaseModel):
    """Batch of user messages.

    Attributes:
        messages (list[UserMessageEvent]):
        type_ (Literal['batch'] | Unset):  Default: 'batch'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    messages: list[UserMessageEvent]
    type_: Literal["batch"] | Unset = "batch"

    def to_dict(self) -> dict[str, Any]:
        from ..models.user_message_event import UserMessageEvent

        messages = []
        for messages_item_data in self.messages:
            messages_item = messages_item_data.to_dict()
            messages.append(messages_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "messages": messages,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.user_message_event import UserMessageEvent

        d = dict(src_dict)
        messages = []
        _messages = d.pop("messages")
        for messages_item_data in _messages:
            messages_item = UserMessageEvent.from_dict(messages_item_data)

            messages.append(messages_item)

        type_ = cast(Literal["batch"] | Unset, d.pop("type", UNSET))
        if type_ != "batch" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'batch', got '{type_}'")

        user_message_batch = cls(
            messages=messages,
            type_=type_,
        )

        return user_message_batch
