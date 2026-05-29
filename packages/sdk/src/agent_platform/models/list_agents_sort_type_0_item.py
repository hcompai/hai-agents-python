from enum import Enum


class ListAgentsSortType0Item(str, Enum):
    AGENT_IDENTIFIER = "agent_identifier"
    CREATED_AT = "created_at"
    VALUE_1 = "-created_at"
    VALUE_3 = "-agent_identifier"

    def __str__(self) -> str:
        return str(self.value)
