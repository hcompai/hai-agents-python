"""Verified download and atomic install of the hai-agent-runtime binary.

Port of holo_desktop.agent_client.runtime_install with the TTY prompt and rich
progress removed: the SDK is a library, so consent is the caller's
``download=True`` and progress is plain logging.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import shutil
import tempfile
import typing
import zipfile
from urllib.parse import urlsplit

import httpx

from .errors import BinaryIncompatibleError, DownloadVerificationError, LocalRuntimeError
from .manifest import (
    BINARY_NAME,
    MANIFEST,
    PINNED_RUNTIME_VERSION,
    PLACEHOLDER_SHA256,
    UNIMPLEMENTED_PLATFORMS,
    RuntimeArtifact,
    platform_key,
)
from .state import resolve_cache_dir

logger = logging.getLogger(__name__)

DOWNLOAD_URL_ENV = "HAI_AGENT_RUNTIME_DOWNLOAD_URL"
DOWNLOAD_SHA256_ENV = "HAI_AGENT_RUNTIME_DOWNLOAD_SHA256"
_DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=600.0)
# Generous ceiling (the runtime is hundreds of MB); guards against a lying/absent Content-Length.
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_PathInput = typing.Union[str, "os.PathLike[str]"]


def _require_secure_url(url: str) -> None:
    """Allow https anywhere, plain http only against loopback (test/ops overrides); reject the rest."""
    parsed = urlsplit(url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS):
        return
    raise LocalRuntimeError(f"refusing insecure hai-agent-runtime download URL (need https): {url}")


def bin_dir(version: str, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    return resolve_cache_dir(cache_dir) / "bin" / version


def _find_binary(root: pathlib.Path) -> typing.Optional[pathlib.Path]:
    direct = root / BINARY_NAME
    if direct.is_file():
        return direct
    # macOS app-bundle shape: <version>/<name>.app/Contents/MacOS/hai-agent-runtime
    for candidate in sorted(root.glob("*.app/Contents/MacOS/hai-agent-runtime")):
        if candidate.is_file():
            return candidate
    return None


def installed_binary(version: str, *, cache_dir: typing.Optional[_PathInput] = None) -> typing.Optional[pathlib.Path]:
    """The managed install's executable for `version`, or None if absent/incomplete."""
    return _find_binary(bin_dir(version, cache_dir=cache_dir))


def pinned_artifact() -> RuntimeArtifact:
    """Artifact to install: env override (tests/ops) or the pinned per-platform manifest entry."""
    override_url = os.environ.get(DOWNLOAD_URL_ENV, "").strip()
    if override_url:
        override_sha = os.environ.get(DOWNLOAD_SHA256_ENV, "").strip()
        if not override_sha:
            raise DownloadVerificationError(
                f"{DOWNLOAD_URL_ENV} is set but {DOWNLOAD_SHA256_ENV} is not; refusing an unverified download"
            )
        return RuntimeArtifact(url=override_url, sha256=override_sha)
    key = platform_key()
    if key in UNIMPLEMENTED_PLATFORMS:
        raise BinaryIncompatibleError(
            f"{UNIMPLEMENTED_PLATFORMS[key]}; put hai-agent-runtime on PATH, "
            f"or set {DOWNLOAD_URL_ENV} + {DOWNLOAD_SHA256_ENV} to a trusted build"
        )
    artifact = MANIFEST.get(key)
    if artifact is None:
        raise BinaryIncompatibleError(f"no hai-agent-runtime release artifact for platform {key}")
    if artifact.sha256 == PLACEHOLDER_SHA256:
        raise BinaryIncompatibleError(
            f"hai-agent-runtime v{PINNED_RUNTIME_VERSION} has no published artifact for {key} yet; "
            f"put hai-agent-runtime on PATH, or set {DOWNLOAD_URL_ENV} + {DOWNLOAD_SHA256_ENV} to a trusted build"
        )
    return artifact


def install_runtime(
    artifact: RuntimeArtifact, *, version: str, cache_dir: typing.Optional[_PathInput] = None
) -> pathlib.Path:
    """Download, sha256-verify, and atomically install `artifact` as `version`; returns the executable path."""
    root = resolve_cache_dir(cache_dir) / "bin"
    root.mkdir(parents=True, exist_ok=True)
    version_dir = root / version

    # Stage on the same filesystem as the final location so os.replace stays atomic.
    with tempfile.TemporaryDirectory(dir=root, prefix=".staging-") as staging_str:
        staging = pathlib.Path(staging_str)
        download_path = staging / "artifact"
        actual_sha256 = _download_to(artifact.url, download_path)
        if actual_sha256 != artifact.sha256.lower():
            raise DownloadVerificationError(
                f"hai-agent-runtime download failed sha256 verification: expected {artifact.sha256}, "
                f"got {actual_sha256} (url: {artifact.url})"
            )

        staged_version = staging / "version"
        staged_version.mkdir()
        if artifact.url.endswith(".zip"):
            # Contents are sha256-verified above, so extraction is trusted.
            with zipfile.ZipFile(download_path) as archive:
                archive.extractall(staged_version)
        else:
            shutil.move(str(download_path), str(staged_version / BINARY_NAME))

        binary = _find_binary(staged_version)
        if binary is None:
            raise LocalRuntimeError(
                f"downloaded artifact contains no hai-agent-runtime executable (url: {artifact.url})"
            )
        binary.chmod(0o755)  # zipfile does not preserve the exec bit

        try:
            os.replace(staged_version, version_dir)
        except OSError:
            # Target occupied: a concurrent installer won the race, or a half-finished dir is in the way.
            existing = installed_binary(version, cache_dir=cache_dir)
            if existing is not None:
                logger.info("hai-agent-runtime %s already installed by a concurrent run", version)
                return existing
            shutil.rmtree(version_dir, ignore_errors=True)
            os.replace(staged_version, version_dir)

    installed = installed_binary(version, cache_dir=cache_dir)
    assert installed is not None, "atomic rename just published the staged install"
    logger.info("installed hai-agent-runtime %s at %s", version, installed)
    return installed


def _download_to(url: str, dest: pathlib.Path) -> str:
    """Stream `url` into `dest`; returns the sha256 hex digest of the bytes written."""
    _require_secure_url(url)
    digest = hashlib.sha256()
    written = 0
    logger.info("downloading hai-agent-runtime from %s", url)
    try:
        with (
            httpx.Client(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT) as client,
            client.stream("GET", url) as response,
        ):
            _require_secure_url(str(response.url))  # a redirect must not downgrade to plain http
            if response.status_code != 200:
                raise LocalRuntimeError(f"hai-agent-runtime download failed: HTTP {response.status_code} from {url}")
            total = int(response.headers.get("Content-Length", "0")) or None
            if total is not None and total > MAX_DOWNLOAD_BYTES:
                raise LocalRuntimeError(
                    f"hai-agent-runtime download too large: {total} bytes exceeds {MAX_DOWNLOAD_BYTES}"
                )
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise LocalRuntimeError(
                            f"hai-agent-runtime download exceeded {MAX_DOWNLOAD_BYTES} bytes; aborting"
                        )
                    digest.update(chunk)
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise LocalRuntimeError(f"hai-agent-runtime download failed: {exc} (url: {url})") from exc
    logger.info("download complete (%d bytes)", written)
    return digest.hexdigest()
