"""Pre-stub pyautogui so pytest collection never triggers mouseinfo's DISPLAY check.

On headless Linux CI, mouseinfo (a pyautogui transitive dependency) raises
TclError at import time when $DISPLAY is unset.  Inserting a MagicMock into
sys.modules before any test file is collected prevents that import from running.
"""

import sys
from unittest.mock import MagicMock

for _mod in ("pyautogui", "mouseinfo"):
    sys.modules.setdefault(_mod, MagicMock())
