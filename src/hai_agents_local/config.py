"""Environment variables read by hai_agents_local."""

from __future__ import annotations

import os
import sys

from hai_agents.client import credentials_path
from hai_agents.environment import HaiAgentsEnvironment

BASE_URL_ENV_VAR = "HAI_API_BASE_URL"
AUTO_BRIDGE_ENV_VAR = "HAI_AUTO_BRIDGE"
SHELL_POLICY_ENV_VAR = "HAI_SHELL_POLICY"
SHELL_SANDBOX_ENV_VAR = "HAI_SHELL_SANDBOX"

DEFAULT_BASE_URL = HaiAgentsEnvironment.EU.value

_FLAG_FALSE = {"0", "false", "no"}
_FLAG_TRUE = {"1", "true", "yes"}


def default_base_url() -> str:
    return os.getenv(BASE_URL_ENV_VAR, "").strip() or DEFAULT_BASE_URL


def shell_policy() -> str | None:
    """This machine's command allowlist file for shell desktops, when it has one."""
    return os.getenv(SHELL_POLICY_ENV_VAR, "").strip() or None


def agent_shell_policy() -> str:
    """The allowlist file of a machine without one, for an agent that requires approval."""
    return str(credentials_path().with_name("allowed-commands"))


def shell_sandbox(required: bool = False) -> str | None:
    """This machine's sandbox-runtime settings file for shell desktops; None runs their commands unconfined."""
    value = os.getenv(SHELL_SANDBOX_ENV_VAR, "").strip()
    if value.lower() in _FLAG_FALSE:
        return None
    if value and value.lower() not in _FLAG_TRUE:
        return value
    # Confinement is the default where the SDK installs it by itself: macOS. Elsewhere it takes the variable, the
    # machine's own rules, or an agent's requirement.
    rules = credentials_path().with_name("sandbox.json")
    return str(rules) if value or required or sys.platform == "darwin" or rules.exists() else None


def auto_bridges_enabled() -> bool:
    """Read at each session creation, so the flag can be flipped at runtime."""
    return os.getenv(AUTO_BRIDGE_ENV_VAR, "").strip().lower() not in _FLAG_FALSE
