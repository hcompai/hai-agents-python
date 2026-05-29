from enum import Enum


class ListSessionsOwner(str, Enum):
    ME = "me"
    ME_IN_ORGANIZATION = "me-in-organization"
    ME_OR_ORGANIZATION = "me-or-organization"
    ORGANIZATION = "organization"

    def __str__(self) -> str:
        return str(self.value)
