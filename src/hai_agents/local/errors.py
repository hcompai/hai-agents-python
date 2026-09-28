"""Error types for hai_agents.local."""

from __future__ import annotations


class LocalRuntimeError(Exception):
    """Base error for local hai-agent-runtime management."""


class BinaryNotFoundError(LocalRuntimeError):
    """No runtime binary: no override, nothing on PATH, no managed install, and download disabled."""


class BinaryIncompatibleError(LocalRuntimeError):
    """The pinned manifest has no verifiable artifact for this platform or requested version."""


class RuntimeUnhealthyError(LocalRuntimeError):
    """The runtime process exited, or /health is not answering with a 200."""


class RuntimeStartTimeoutError(LocalRuntimeError):
    """The spawned runtime did not become healthy before the timeout."""


class DownloadVerificationError(LocalRuntimeError):
    """A runtime download could not be sha256-verified (mismatch, or no digest to verify against)."""
