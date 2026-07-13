from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .bridge import LocalBridge, TokenSource

if TYPE_CHECKING:
    from hai_drivers.desktop.interface import DesktopDriverInterface

ImageFormat = Literal["png", "jpeg", "webp"]

DEFAULT_MAX_WIDTH = 1920
DEFAULT_IMAGE_FORMAT: ImageFormat = "jpeg"
DEFAULT_QUALITY = 85


class PyautoguiDesktopBridge(LocalBridge["DesktopDriverInterface"]):
    """Serves desktop environments (mouse, keyboard, screen, files, shell) on this machine via pyautogui.

    Screenshots are downscaled and encoded here, before they cross the network; set every
    knob to None to serve raw native-resolution captures.
    """

    environment_kind = "desktop"

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        max_width: int | None = DEFAULT_MAX_WIDTH,
        max_height: int | None = None,
        image_format: ImageFormat | None = DEFAULT_IMAGE_FORMAT,
        quality: int = DEFAULT_QUALITY,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.max_width = max_width
        self.max_height = max_height
        self.image_format = image_format
        self.quality = quality

    def create_driver(self) -> DesktopDriverInterface:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        try:
            from hai_drivers.desktop.local import LocalDesktopDriver
        except ImportError as exc:
            raise ImportError(
                "Local desktop control requires extra deps. Install with: pip install 'hai-agents[desktop]'"
            ) from exc
        driver = LocalDesktopDriver()
        if self.max_width is None and self.max_height is None and self.image_format is None:
            return driver
        from hai_drivers.desktop.scaled import ScaledDesktopDriver

        return ScaledDesktopDriver(
            driver,
            max_width=self.max_width,
            max_height=self.max_height,
            image_format=self.image_format,
            quality=self.quality,
        )

    def driver_interface(self) -> type:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        from hai_drivers.desktop.interface import DesktopDriverInterface

        return DesktopDriverInterface
