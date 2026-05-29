from enum import Enum


class ListMemoriesSortType0Item(str, Enum):
    UPDATED_AT = "updated_at"
    VALUE_1 = "-updated_at"

    def __str__(self) -> str:
        return str(self.value)
