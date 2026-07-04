"""Local-mode runtime management: install/find/start a hai-agent-runtime binary.

Never imported by the base ``hai_agents`` package; ``Client.local`` pulls it in
lazily so remote-only users pay nothing for it.
"""

from .errors import (
    BinaryIncompatibleError,
    BinaryNotFoundError,
    DownloadVerificationError,
    LocalRuntimeError,
    RuntimeStartTimeoutError,
    RuntimeUnhealthyError,
)

__all__ = [
    "BinaryIncompatibleError",
    "BinaryNotFoundError",
    "DownloadVerificationError",
    "LocalRuntimeError",
    "RuntimeStartTimeoutError",
    "RuntimeUnhealthyError",
]
