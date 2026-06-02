from enum import Enum


class BrowserMode(str, Enum):
    MULTIMODAL = "multimodal"
    TEXT = "text"
    VISUAL = "visual"

    def __str__(self) -> str:
        return str(self.value)
