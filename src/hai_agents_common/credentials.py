"""Resolve, construct, and persist Agent API credentials for the CLI."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import urljoin

from dotenv import dotenv_values, set_key, unset_key

from hai_agents import AsyncClient, Client
from hai_agents.environment import HaiAgentsEnvironment

ApiKey = str | Callable[[], str]

API_KEY_VAR = "HAI_API_KEY"
BASE_URL_VAR = "HAI_API_BASE_URL"
PORTAL_URL_VAR = "HAI_PORTAL_URL"

PORTALS = {
    HaiAgentsEnvironment.EU.value: "https://portal.api.eu.hcompany.ai",
    HaiAgentsEnvironment.US.value: "https://portal.production.hcompany.ai",
}
API_KEYS_PAGE = "https://platform.hcompany.ai/settings/api-keys"

LOCAL_ENV_PATH = Path(".env")
GLOBAL_ENV_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai" / ".env"

# Detection, not prevention: a project `.env` is used as is, and the CLI says so every time.
PROJECT_ENV_WARNING = (
    f"Using {API_KEY_VAR} from {LOCAL_ENV_PATH}. Make sure this key is yours: a cloned or forked repo can ship "
    "a .env that carries someone else's key on purpose, and your runs would then land in their account."
)


def portal_base(base_url: str | None = None) -> str:
    """Portal origin used by `hai login`: `HAI_PORTAL_URL`, else the portal of the platform's region."""
    if os.environ.get(PORTAL_URL_VAR):
        return os.environ[PORTAL_URL_VAR]
    platform = (resolve_base_url(base_url) or HaiAgentsEnvironment.EU.value).rstrip("/")
    if platform not in PORTALS:
        raise RuntimeError(
            f"No portal is known for {platform}; set {PORTAL_URL_VAR} to the portal that issues its keys."
        )
    return PORTALS[platform]


def current_api_key(explicit: ApiKey | None = None) -> ApiKey | None:
    """Resolved API key, or None if none is configured."""
    return explicit or _lookup(API_KEY_VAR)


def resolve_api_key(explicit: ApiKey | None = None) -> ApiKey:
    """Resolved API key, or raise with guidance if none is configured."""
    key = current_api_key(explicit)
    if not key:
        raise RuntimeError(f"No API key found. Run `hai login`, set {API_KEY_VAR}, or pass --api-key.")
    return key


def resolve_base_url(explicit: str | None = None) -> str | None:
    """Resolved base URL override, or None to use the SDK default."""
    return explicit or _lookup(BASE_URL_VAR)


def make_client(api_key: ApiKey | None = None, base_url: str | None = None) -> Client:
    """Build a synchronous SDK client from resolved credentials."""
    return Client(**_client_kwargs(api_key, base_url))


def make_async_client(api_key: ApiKey | None = None, base_url: str | None = None) -> AsyncClient:
    """Build an asynchronous SDK client from resolved credentials."""
    return AsyncClient(**_client_kwargs(api_key, base_url))


def absolute_share_url(client: Client | AsyncClient, share_path: str) -> str:
    """Turn the SDK share path into a clickable absolute URL."""
    if share_path.startswith(("http://", "https://")):
        return share_path
    base = client._client_wrapper.get_base_url().rstrip("/") + "/"
    return urljoin(base, share_path.lstrip("/"))


def save_api_key(key: str) -> Path:
    """Persist the API key to the global `.env` (chmod 600) and the process env."""
    GLOBAL_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_ENV_PATH.exists():
        GLOBAL_ENV_PATH.write_text("", encoding="utf-8")
    with contextlib.suppress(OSError):
        GLOBAL_ENV_PATH.chmod(0o600)
    set_key(str(GLOBAL_ENV_PATH), API_KEY_VAR, key)
    os.environ[API_KEY_VAR] = key
    return GLOBAL_ENV_PATH


def clear_api_key() -> Path | None:
    """Remove the API key from the global `.env` and the process env. Idempotent."""
    os.environ.pop(API_KEY_VAR, None)
    if not GLOBAL_ENV_PATH.exists():
        return None
    with contextlib.suppress(KeyError):
        unset_key(str(GLOBAL_ENV_PATH), API_KEY_VAR)
    return GLOBAL_ENV_PATH


def source(explicit: ApiKey | None = None) -> str | None:
    """Where the resolved credential comes from (`argument`, `environment`, or a file path), for `hai whoami`."""
    if explicit:
        return "argument"
    if os.environ.get(API_KEY_VAR):
        return "environment"
    for path in _readable_env_paths():
        if _values(path).get(API_KEY_VAR):
            return str(path)
    return None


def key_file_rejection(path: Path) -> str | None:
    """Why a key file must not be read, or None.

    The global file must be private (`hai login` writes it 0600); a project `.env` only has to be a regular file.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file (symlink?)"
    if path == LOCAL_ENV_PATH or os.name == "nt":
        return None
    if info.st_uid != os.geteuid():
        return "not owned by the current user"
    if info.st_mode & 0o077:
        return "readable by others; run `chmod 600` on it"
    return None


def key_file_warnings() -> list[str]:
    """One line per key file that is present but ignored, for the CLI to show."""
    warnings = []
    for path in _env_paths():
        if not os.path.lexists(path):
            continue
        reason = key_file_rejection(path)  # what the file is, before reading what it contains
        if reason is None and path == LOCAL_ENV_PATH and not project_env_settings(path):
            continue
        if reason:
            warnings.append(f"Ignoring {path}: {reason}")
    return warnings


def project_env_settings(path: Path) -> dict[str, str]:
    """The `HAI_` variables a project `.env` sets; a `.env` without any is not a key file and is left alone."""
    return {name: value for name, value in _values(path).items() if name.startswith("HAI_") and value}


def _values(path: Path) -> dict[str, str | None]:
    """The file's variables, or nothing when it cannot be read or is not text."""
    try:
        return dotenv_values(path)
    except (OSError, UnicodeDecodeError):
        return {}


def _client_kwargs(api_key: ApiKey | None, base_url: str | None) -> dict[str, ApiKey | str]:
    kwargs: dict[str, ApiKey | str] = {"api_key": resolve_api_key(api_key)}
    resolved_base_url = resolve_base_url(base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    return kwargs


def _env_paths() -> tuple[Path, ...]:
    # CWD `.env` overrides the global config `.env`.
    return (LOCAL_ENV_PATH, GLOBAL_ENV_PATH)


def _readable_env_paths() -> Iterator[Path]:
    for path in _env_paths():
        if not os.path.lexists(path) or key_file_rejection(path) is not None:
            continue
        if path == LOCAL_ENV_PATH and not project_env_settings(path):
            continue
        yield path


def _lookup(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    for path in _readable_env_paths():
        value = _values(path).get(name)
        if value:
            return value
    return None
