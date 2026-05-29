from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, Literal, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

T = TypeVar("T", bound="Memory")


class Memory(BaseModel):
    """Cross-session key-value memory backed by AgP.

    Attributes:
        id (str): Catalog id.
        namespace (str): Memory namespace; scope for keys across sessions.
        kind (Literal['memory'] | Unset):  Default: 'memory'.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: str
    namespace: str
    kind: Literal["memory"] | Unset = "memory"

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        namespace = self.namespace

        kind = self.kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "namespace": namespace,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        namespace = d.pop("namespace")

        kind = cast(Literal["memory"] | Unset, d.pop("kind", UNSET))
        if kind != "memory" and not isinstance(kind, Unset):
            raise ValueError(f"kind must match const 'memory', got '{kind}'")

        memory = cls(
            id=id,
            namespace=namespace,
            kind=kind,
        )

        return memory
