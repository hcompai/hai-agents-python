"""Environment variables read by hai_agents_local."""

from __future__ import annotations

import os

from hai_agents.environment import HaiAgentsEnvironment

BASE_URL_ENV_VAR = "HAI_API_BASE_URL"
AUTO_BRIDGE_ENV_VAR = "HAI_AUTO_BRIDGE"
SHELL_POLICY_ENV_VAR = "HAI_SHELL_POLICY"

DEFAULT_BASE_URL = HaiAgentsEnvironment.EU.value

_FLAG_FALSE = {"0", "false", "no"}


def default_base_url() -> str:
    return os.getenv(BASE_URL_ENV_VAR, "").strip() or DEFAULT_BASE_URL


def shell_policy() -> str | None:
    """This machine's command allowlist file for shell desktops, when it has one."""
    return os.getenv(SHELL_POLICY_ENV_VAR, "").strip() or None


def auto_bridges_enabled() -> bool:
    """Read at each session creation, so the flag can be flipped at runtime."""
    return os.getenv(AUTO_BRIDGE_ENV_VAR, "").strip().lower() not in _FLAG_FALSE
