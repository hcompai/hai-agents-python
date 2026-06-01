from enum import Enum


class ListEnvironmentsSortType0Item(str, Enum):
    CREATED_AT = "created_at"
    ID = "id"
    VALUE_1 = "-created_at"
    VALUE_3 = "-id"

    def __str__(self) -> str:
        return str(self.value)
