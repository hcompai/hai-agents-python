from enum import Enum


class ListSkillsSortType0Item(str, Enum):
    CREATED_AT = "created_at"
    NAME = "name"
    VALUE_1 = "-created_at"
    VALUE_3 = "-name"

    def __str__(self) -> str:
        return str(self.value)
