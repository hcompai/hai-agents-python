from enum import Enum


class QuotaStatusScope(str, Enum):
    ORG = "org"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
