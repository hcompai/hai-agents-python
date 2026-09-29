"""Local workstation bridge: the agent's shell runs on this machine and drives it through the desk and web CLIs."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING

from .bridge import LocalBridge, TokenSource
from .desktop import ensure_macos_input_permissions

if TYPE_CHECKING:
    from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "Local workstation control requires extra deps. Install with: pip install 'hai-agents[workstation]'"


class WorkstationBridge(LocalBridge["ManagedCodeSandboxInterface"]):
    """Serves workstation environments with a shell in ~/hai/<session_id>, running as the current user."""

    environment_kind = "workstation"

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        workspace: str | None = None,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.workspace = Path(workspace).expanduser() if workspace else Path.home() / "hai" / self.session_id

    def preflight(self) -> None:
        if sys.platform == "darwin":
            ensure_macos_input_permissions(prompt=True)

    def create_driver(self) -> ManagedCodeSandboxInterface:
        try:
            from hai_drivers.code_sandbox.local.driver import LocalCodeSandbox
        except ImportError as exc:
            raise ImportError(INSTALL_HINT) from exc
        path = os.environ.get("PATH", os.defpath)
        desk = shutil.which("desk", path=os.pathsep.join([sysconfig.get_path("scripts"), path]))
        if desk is None:
            raise ImportError(INSTALL_HINT)
        subprocess.run([desk, "aliases"], check=True, capture_output=True)
        logger.info("workstation workspace: %s", self.workspace)
        return LocalCodeSandbox(
            str(self.workspace),
            environment_variables={
                "COORDINATE_SYSTEM": "0-1000",
                "PATH": os.pathsep.join([os.path.dirname(desk), path]),
            },
        )

    def driver_interface(self) -> type:
        from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

        return ManagedCodeSandboxInterface
