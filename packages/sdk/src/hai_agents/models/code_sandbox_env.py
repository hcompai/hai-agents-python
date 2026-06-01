from __future__ import annotations

from collections.abc import Mapping
from typing import Any, BinaryIO, Generator, TextIO, TypeVar

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="CodeSandboxEnv")


class CodeSandboxEnv(BaseModel):
    """Environment variables."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        defer_build=True,
    )

    additional_properties: dict[str, str] = {}

    def to_dict(self) -> dict[str, Any]:

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        code_sandbox_env = cls()

        code_sandbox_env.additional_properties = d
        return code_sandbox_env

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> str:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: str) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
