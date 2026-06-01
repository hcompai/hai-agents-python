from enum import Enum


class ListAgentsSortType0Item(str, Enum):
    AGENT_NAME = "agent_name"
    CREATED_AT = "created_at"
    VALUE_1 = "-created_at"
    VALUE_3 = "-agent_name"

    def __str__(self) -> str:
        return str(self.value)
