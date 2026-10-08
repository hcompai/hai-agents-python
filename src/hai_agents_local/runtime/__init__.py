"""Local agent runtime management, imported lazily by ``Client.local`` so remote-only users pay nothing for it."""

from .acquire import acquire_runtime, acquire_runtime_async
from .errors import (
    BinaryIncompatibleError,
    BinaryNotFoundError,
    DownloadVerificationError,
    LocalRuntimeError,
    RuntimeStartTimeoutError,
    RuntimeUnhealthyError,
)
from .inference import Inference
from .runtime import LocalRuntime, locate_runtime

__all__ = [
    "BinaryIncompatibleError",
    "BinaryNotFoundError",
    "DownloadVerificationError",
    "Inference",
    "LocalRuntime",
    "LocalRuntimeError",
    "RuntimeStartTimeoutError",
    "RuntimeUnhealthyError",
    "acquire_runtime",
    "acquire_runtime_async",
    "locate_runtime",
]
