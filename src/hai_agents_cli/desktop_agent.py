"""The agent `--local` runs: it drives this desktop, with the user's ~/.holo/AGENTS.md and ~/.holo/skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

HOLO_DIR = Path.home() / ".holo"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def agent() -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": "holo",
        "description": "Desktop agent that drives the user's machine.",
        "environments": [{"id": "desktop", "kind": "desktop", "host": "user_device"}],
    }
    instructions = HOLO_DIR / "AGENTS.md"
    if instructions.is_file() and (text := instructions.read_text(encoding="utf-8").strip()):
        spec["instructions"] = text
    if skills := [_skill(path) for path in sorted(HOLO_DIR.glob("skills/*/SKILL.md"))]:
        spec["skills"] = skills
    return spec


def _skill(path: Path) -> dict[str, str]:
    # ponytail: SKILL.md only; the desktop environment cannot provision a skill's other files.
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    try:
        meta = yaml.safe_load(match[1]) if match else None
    except yaml.YAMLError:
        meta = None
    if not (match and isinstance(meta, dict) and meta.get("description")):
        raise ValueError(f"{path} needs YAML frontmatter with a description")
    return {"name": path.parent.name, "description": str(meta["description"]), "body": match[2].strip()}
