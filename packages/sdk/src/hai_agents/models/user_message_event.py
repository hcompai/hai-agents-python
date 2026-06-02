from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="UserMessageEvent")


class UserMessageEvent(BaseModel):
    """The user is sending a message to an active agent.

    Attributes:
        message (str): Message text sent to the agent.
        type_ (Literal['user_message'] | Unset):  Default: 'user_message'.
        images (list[str] | Unset): Optional images attached to the message, as base64 data URIs.
        caller_id (str | Unset):  Default: 'user'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    message: str
    type_: Literal["user_message"] | Unset = "user_message"
    images: list[str] | Unset = UNSET
    caller_id: str | Unset = "user"
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        type_ = self.type_

        images: list[str] | Unset = UNSET
        if not isinstance(self.images, Unset):
            images = self.images

        caller_id = self.caller_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "message": message,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if images is not UNSET:
            field_dict["images"] = images
        if caller_id is not UNSET:
            field_dict["caller_id"] = caller_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message = d.pop("message")

        type_ = cast(Literal["user_message"] | Unset, d.pop("type", UNSET))
        if type_ != "user_message" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'user_message', got '{type_}'")

        images = cast(list[str], d.pop("images", UNSET))

        caller_id = d.pop("caller_id", UNSET)

        user_message_event = cls(
            message=message,
            type_=type_,
            images=images,
            caller_id=caller_id,
        )

        user_message_event.additional_properties = d
        return user_message_event

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
