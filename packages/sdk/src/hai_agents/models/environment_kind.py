from enum import Enum


class EnvironmentKind(str, Enum):
    CODE = "code"
    MCP = "mcp"
    MEMORY = "memory"
    WEB = "web"

    def __str__(self) -> str:
        return str(self.value)
