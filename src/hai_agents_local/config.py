"""Environment variables read by hai_agents_local."""

from __future__ import annotations

import os

from hai_agents.client import credentials_path
from hai_agents.environment import HaiAgentsEnvironment

BASE_URL_ENV_VAR = "HAI_API_BASE_URL"

DEFAULT_BASE_URL = HaiAgentsEnvironment.EU.value

# A machine set up with one of these expects held or confined commands: set, it fails the session, so that no
# command runs with less than the machine asked for.
_UNREAD = {
    "HAI_SHELL_POLICY": "an agent asks with `command_approval: required`, and WorkstationBridge takes `policy=`",
    "HAI_SHELL_SANDBOX": "the sandbox is on where srt runs, and `--no-sandbox` or `sandbox=False` turns it off",
}


def default_base_url() -> str:
    return os.getenv(BASE_URL_ENV_VAR, "").strip() or DEFAULT_BASE_URL


def refuse_unread_settings() -> None:
    for name, instead in _UNREAD.items():
        if os.getenv(name, "").strip():
            raise ValueError(f"{name} is not read: {instead}. Unset it.")


def machine_allowlist() -> str:
    """This machine's allowlist file for shell desktops: the commands an agent that asks runs without asking."""
    return str(credentials_path().with_name("allowed-commands"))


def shell_sandbox() -> str:
    """This machine's sandbox-runtime settings file for shell desktops; the built-in rules apply where it is missing."""
    return str(credentials_path().with_name("sandbox.json"))
