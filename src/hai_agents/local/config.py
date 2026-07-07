"""Every environment variable read by hai_agents.local, as one validated model."""

from __future__ import annotations

import os
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticUseDefault

from ..environment import HaiAgentsEnvironment

API_KEY_ENV_VAR = "HAI_API_KEY"
BASE_URL_ENV_VAR = "HAI_API_BASE_URL"
AUTO_BRIDGE_ENV_VAR = "HAI_AUTO_BRIDGE"

DEFAULT_BASE_URL = HaiAgentsEnvironment.EU.value

_FLAG_FALSE = {"0", "false", "no"}


class LocalSettings(BaseModel):
    """Environment variables read by the local bridge stack.

    Blank or whitespace-only values fall back to the field default, so an
    empty ``HAI_API_KEY`` never masquerades as a configured key.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str | None = Field(default=None, validation_alias=API_KEY_ENV_VAR)
    """Platform API key; bridges require it here or as an explicit argument."""
    base_url: str = Field(default=DEFAULT_BASE_URL, validation_alias=BASE_URL_ENV_VAR)
    """Platform API base URL."""
    auto_bridge: bool = Field(default=True, validation_alias=AUTO_BRIDGE_ENV_VAR)
    """Auto-start bridges for user_device environments on session creation."""

    @field_validator("api_key", "base_url", mode="before")
    @classmethod
    def _blank_uses_default(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise PydanticUseDefault()
        return value

    @field_validator("auto_bridge", mode="before")
    @classmethod
    def _parse_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower() not in _FLAG_FALSE
        return value

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LocalSettings:
        return cls.model_validate(dict(os.environ if environ is None else environ))


def auto_bridges_enabled() -> bool:
    """Read at each session creation, so the flag can be flipped at runtime."""
    return LocalSettings.from_env().auto_bridge
