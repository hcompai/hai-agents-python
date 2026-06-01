from enum import Enum


class MCPServerTransport(str, Enum):
    SSE = "sse"
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"

    def __str__(self) -> str:
        return str(self.value)
