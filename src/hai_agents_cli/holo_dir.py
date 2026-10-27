"""~/.holo customizes every agent holo runs: agents.md joins its instructions, skills/*/SKILL.md join its skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

HOLO_DIR = Path.home() / ".holo"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def customized() -> bool:
    return (HOLO_DIR / "agents.md").is_file() or any(HOLO_DIR.glob("skills/*/SKILL.md"))


def overrides(spec: dict[str, Any]) -> dict[str, Any]:
    """Session overrides that add ~/.holo to the agent `spec`, whose own instructions and skills come first."""
    added: dict[str, Any] = {}
    notes = HOLO_DIR / "agents.md"
    if notes.is_file() and (text := notes.read_text(encoding="utf-8").strip()):
        added["agent.instructions"] = "\n\n".join(filter(None, [spec.get("instructions"), text]))
    if mine := [_skill(path) for path in sorted(HOLO_DIR.glob("skills/*/SKILL.md"))]:
        names = {skill["name"] for skill in mine}
        theirs = [s for s in spec.get("skills") or [] if (s if isinstance(s, str) else s.get("name")) not in names]
        added["agent.skills"] = [*theirs, *mine]
    return added


def _skill(path: Path) -> dict[str, str]:
    # ponytail: SKILL.md only; a desktop environment cannot provision a skill's other files.
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    try:
        meta = yaml.safe_load(match[1]) if match else None
    except yaml.YAMLError:
        meta = None
    if not (match and isinstance(meta, dict) and meta.get("description")):
        raise ValueError(f"{path} needs YAML frontmatter with a description")
    return {"name": path.parent.name, "description": str(meta["description"]), "body": match[2].strip()}
