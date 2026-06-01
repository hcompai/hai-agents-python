from enum import Enum


class ListEnvironmentsSortType0Item(str, Enum):
    CREATED_AT = "created_at"
    ENV_IDENTIFIER = "env_identifier"
    VALUE_1 = "-created_at"
    VALUE_3 = "-env_identifier"

    def __str__(self) -> str:
        return str(self.value)
