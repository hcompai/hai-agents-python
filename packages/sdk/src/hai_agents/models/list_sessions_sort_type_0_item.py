from enum import Enum


class ListSessionsSortType0Item(str, Enum):
    CREATED_AT = "created_at"
    VALUE_1 = "-created_at"

    def __str__(self) -> str:
        return str(self.value)
