"""Resolve credentials and region from flags, environment, then config file."""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

DEFAULT_REGION = "eu"
TOKEN_VAR = "HAI_API_KEY"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DOTENV_PATH = Path(".env")
PORTAL_BASE = "https://portal.production.hcompany.ai"


def portal_base() -> str:
    return os.environ.get("HAI_PORTAL_URL") or PORTAL_BASE


@dataclass(frozen=True)
class Config:
    token: str | None
    region: str
    base_url: str | None


def _read_file() -> dict:
    try:
        with CONFIG_PATH.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def resolve(
    token: str | None = None,
    region: str | None = None,
    base_url: str | None = None,
) -> Config:
    """Merge flags (highest), process env, a local ``.env``, then the config file (lowest)."""
    saved = _read_file()
    env = dotenv_values(DOTENV_PATH) if DOTENV_PATH.exists() else {}
    return Config(
        token=token or os.environ.get(TOKEN_VAR) or env.get(TOKEN_VAR) or saved.get("token"),
        region=(
            region or os.environ.get("HAI_REGION") or env.get("HAI_REGION") or saved.get("region") or DEFAULT_REGION
        ).lower(),
        base_url=base_url or os.environ.get("HAI_BASE_URL") or env.get("HAI_BASE_URL") or saved.get("base_url"),
    )


def read_env_key() -> str | None:
    """Current API key from the process env or a local ``.env``."""
    if os.environ.get(TOKEN_VAR):
        return os.environ[TOKEN_VAR]
    return dotenv_values(DOTENV_PATH).get(TOKEN_VAR) if DOTENV_PATH.exists() else None


def save_env_key(key: str) -> Path:
    """Write the API key to a local ``.env`` (and the process env), without clobbering other keys."""
    if not DOTENV_PATH.exists():
        DOTENV_PATH.write_text("", encoding="utf-8")
    set_key(str(DOTENV_PATH), TOKEN_VAR, key)
    with contextlib.suppress(OSError):
        DOTENV_PATH.chmod(0o600)
    os.environ[TOKEN_VAR] = key
    return DOTENV_PATH


def clear_env_key() -> Path | None:
    """Remove the API key from the local ``.env`` and the process env. Idempotent."""
    os.environ.pop(TOKEN_VAR, None)
    if not DOTENV_PATH.exists():
        return None
    with contextlib.suppress(KeyError):
        unset_key(str(DOTENV_PATH), TOKEN_VAR)
    return DOTENV_PATH


def key_source() -> str | None:
    """Where the resolved API key comes from, for ``hai whoami``."""
    if os.environ.get(TOKEN_VAR):
        return "environment"
    if DOTENV_PATH.exists() and dotenv_values(DOTENV_PATH).get(TOKEN_VAR):
        return str(DOTENV_PATH)
    if _read_file().get("token"):
        return str(CONFIG_PATH)
    return None


def mask(secret: str) -> str:
    """Reveal just enough of a key to recognise it, hiding the rest."""
    return f"{secret[:6]}...{secret[-2:]}" if len(secret) > 10 else "(set)"


def save(token: str | None, region: str | None, base_url: str | None) -> Path:
    """Persist non-empty values to the config file with owner-only permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    if token:
        lines.append(f'token = "{token}"')
    if region:
        lines.append(f'region = "{region}"')
    if base_url:
        lines.append(f'base_url = "{base_url}"')
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
    return CONFIG_PATH
