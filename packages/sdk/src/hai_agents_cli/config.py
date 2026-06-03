"""Resolve credentials and region from flags, environment, then config file."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

DEFAULT_REGION = "eu"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai"
CONFIG_PATH = CONFIG_DIR / "config.toml"


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
    """Merge flags (highest), environment, then the config file (lowest)."""
    saved = _read_file()
    return Config(
        token=token or os.environ.get("H_API_KEY") or saved.get("token"),
        region=(region or os.environ.get("H_REGION") or saved.get("region") or DEFAULT_REGION).lower(),
        base_url=base_url or os.environ.get("H_BASE_URL") or saved.get("base_url"),
    )


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
