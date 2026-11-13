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
from typing import TYPE_CHECKING, Any

from .bridge import LocalBridge, TokenSource
from .desktop import ensure_macos_input_permissions

if TYPE_CHECKING:
    from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

logger = logging.getLogger(__name__)

INSTALL_HINT = "A desktop with a shell requires extra deps. Install with: pip install 'hai-agents[workstation]'"
HOLOTAB_STOP_S = 15.0


class WorkstationBridge(LocalBridge["ManagedCodeSandboxInterface"]):
    """Serves shell-mode desktops with a shell in ~/hai/<session_id>, running as the current user.

    While serving, registers the session with the HoloTab daemon so the shell's `holotab` works without the key.
    `holotab_app` names the app in HoloTab (default: the daemon's app name); `holotab_key` is the key to register
    with (default: `api_key` when it is an `hk-` key). Without a key, with an empty `holotab_key`, or without hai-drivers
    support, nothing is registered.
    """

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
        holotab_app: str | None = None,
        holotab_key: str | None = None,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.workspace = Path(workspace).expanduser() if workspace else Path.home() / "hai" / self.session_id
        self.environment_variables = dict(environment_variables or {})
        self.holotab_app = holotab_app
        self.holotab_key = holotab_key

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
                **self.environment_variables,
                "COORDINATE_SYSTEM": "0-1000",
                "CUA_CURSOR": os.environ.get("CUA_CURSOR", "off"),
                "CUA_SESSION": self.session_id,
                "PATH": os.pathsep.join([os.path.dirname(desk), path]),
            },
        )

    async def _serve(self) -> None:
        try:
            from hai_drivers.web.holotab.daemon import APP_NAME, Registration
        except ImportError:
            await super()._serve()
            return
        # sessions imports this module through routing, so a top-level import would be circular.
        from .sessions import _resolve_token

        try:
            key = self.holotab_key
            if key is None:
                resolved = await asyncio.to_thread(_resolve_token, self.api_key)
                key = resolved if isinstance(resolved, str) and resolved.startswith("hk-") else None
        except Exception as exc:
            logger.warning("holotab key resolution failed (%s); serving without registration", type(exc).__name__)
            key = None
        if not key:
            await super()._serve()
            return
        registration = Registration(self.session_id, self.holotab_app or APP_NAME, key)
        starting = asyncio.ensure_future(asyncio.to_thread(self._start_registration, registration))

        async def stop() -> None:
            await asyncio.wait([starting])
            await asyncio.to_thread(registration.close)

        try:
            await asyncio.shield(starting)
            await super()._serve()
        finally:
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.ensure_future(stop())), HOLOTAB_STOP_S)
            except TimeoutError:
                logger.warning("holotab unregister still running after %ss; leaving it to finish", HOLOTAB_STOP_S)

    @staticmethod
    def _start_registration(registration: Any) -> None:
        try:
            registered = registration.start()
        except Exception as exc:
            logger.warning("holotab registration failed (%s); serving without it", type(exc).__name__)
            return
        if registered is False:
            logger.warning("holotab registration failed (daemon unreachable); serving without it")

    async def interrupt_driver(self) -> None:
        # This bridge creates one sandbox per run; close owns only that run's children.
        if self._driver is not None:
            await asyncio.to_thread(self._driver.close)

    def driver_interface(self) -> type:
        from hai_drivers.code_sandbox.interface import ManagedCodeSandboxInterface

        return ManagedCodeSandboxInterface
