from typing import Any, Dict, Optional


def server_detail(body: Any) -> Optional[str]:
    """The human-readable reason the server sent, when it sent one.

    The API answers errors with ``{"message", "detail"}`` where ``detail`` is a string, a
    ``{"message"}`` object, or a list of ``{"msg"}`` / ``{"message"}`` items (FastAPI
    validation errors). The body may be the raw dict or a parsed pydantic model.
    """
    detail = _field(body, "detail")
    if isinstance(detail, list):
        parts = [text for text in (_text(item) for item in detail) if text is not None]
        if parts:
            return "; ".join(parts)
        return _text(_field(body, "message"))
    return _text(detail) or _text(_field(body, "message"))


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    if isinstance(obj, (str, bytes, list)) or obj is None:
        return None
    return getattr(obj, name, None)


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    for key in ("msg", "message"):
        text = _field(value, key)
        if isinstance(text, str):
            return text
    return None


class ApiError(Exception):
    headers: Optional[Dict[str, str]]
    status_code: Optional[int]
    body: Any

    def __init__(
        self,
        *,
        headers: Optional[Dict[str, str]] = None,
        status_code: Optional[int] = None,
        body: Any = None,
    ) -> None:
        self.headers = headers
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:
        detail = server_detail(self.body)
        if detail is not None:
            return f"{detail} (status_code: {self.status_code})"
        return f"headers: {self.headers}, status_code: {self.status_code}, body: {self.body}"
