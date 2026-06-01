from enum import Enum


class ListSessionEventsSortType0Item(str, Enum):
    TIMESTAMP = "timestamp"
    VALUE_1 = "-timestamp"

    def __str__(self) -> str:
        return str(self.value)
