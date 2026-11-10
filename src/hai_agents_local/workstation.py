"""Shell desktop bridge: the agent's shell runs on this machine and drives it through the desk, cua and web CLIs."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from .bridge import LocalBridge, TokenSource
from .config import shell_policy
from .desktop import ensure_macos_input_permissions

if TYPE_CHECKING:
    from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "A desktop with a shell requires extra deps. Install with: pip install 'hai-agents[workstation]'"


class WorkstationBridge(LocalBridge["ManagedCodeSandboxInterface"]):
    """Serves shell-mode desktops with a shell in ~/hai/<session_id>, running as the current user."""

    environment_kind = "workstation"
    environment = {"kind": "desktop", "mode": {"type": "shell"}}
    drives_desktop = True

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        workspace: str | None = None,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        environment_variables: Mapping[str, str] | None = None,
        policy: str | None = None,
    ) -> None:
        """Build the bridge.

        Args:
            policy: This machine's allowlist file, one command prefix a line; defaults to ``HAI_SHELL_POLICY``.
                With one, the shell runs the commands it covers and holds any other until the session's client
                approves it, and the agent's file tools stay inside the workspace. Without one, every command runs.
        """
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.workspace = Path(workspace).expanduser() if workspace else Path.home() / "hai" / self.session_id
        self.environment_variables = dict(environment_variables or {})
        self.policy = policy or shell_policy()

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
        policy = None
        if self.policy:
            from hai_drivers.code_sandbox.local.policy import SafetyPolicy

            policy = SafetyPolicy(self.policy)
            logger.info("commands outside %s wait for approval", policy.allowed_path)
        return LocalCodeSandbox(
            str(self.workspace),
            environment_variables={
                **self.environment_variables,
                "COORDINATE_SYSTEM": "0-1000",
                "CUA_CURSOR": os.environ.get("CUA_CURSOR", "off"),
                "CUA_SESSION": self.session_id,
                "PATH": os.pathsep.join([os.path.dirname(desk), path]),
            },
            policy=policy,
        )

    async def interrupt_driver(self) -> None:
        # This bridge creates one sandbox per run; close owns only that run's children.
        if self._driver is not None:
            await asyncio.to_thread(self._driver.close)

    def driver_interface(self) -> type:
        from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

        return ManagedCodeSandboxInterface
