"""Exceptions raised by the local bridge stack."""


class AuthError(Exception):
    """The platform rejected the API key; the bridge cannot serve."""


class SessionNotFoundError(Exception):
    """The command channel disappeared server-side and must be recreated."""


class RateLimitedError(Exception):
    """The platform asked the bridge to back off polling."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after:.0f}s")
        self.retry_after = retry_after
