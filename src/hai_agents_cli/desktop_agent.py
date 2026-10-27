"""The agent that drives this desktop: app skills for this OS, plus the user's notes and skills in ~/.holo."""

from __future__ import annotations

import os
import platform
import re
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from hai_agents_local.runtime.inference import MODEL_ENV, URL_ENV, Inference

HOLO_DIR = Path.home() / ".holo"
BUNDLED_SKILLS = {"Darwin": "macos", "Windows": "windows"}
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def agent(*, model: str | None = None, fast: bool = False) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": "holo",
        "description": "Desktop agent that drives the user's machine.",
        "environments": [{"id": "desktop", "kind": "desktop", "host": "user_device"}],
    }
    if instructions := _instructions():
        spec["instructions"] = instructions
    if skills := list(_skills().values()):
        spec["skills"] = skills
    if model:
        spec["model"] = model
    if fast:
        spec["reasoning_effort"] = "disabled"
    return spec


def inference(model: str | None, model_url: str | None) -> Inference | None:
    """Where the runtime infers, when flags set it; ``None`` leaves the runtime to its environment."""
    if not (model or model_url):
        return None
    url = model_url or os.environ.get(URL_ENV)
    model = model or os.environ.get(MODEL_ENV, "")
    return Inference.self_hosted(url, model=model) if url else Inference(model=model)


def _instructions() -> str:
    return "\n\n".join(text for path in sorted(HOLO_DIR.glob("*.md")) if (text := _read(path)))


def _skills() -> dict[str, dict[str, str]]:
    """This OS's bundled skills, then the user's, which replace a bundled skill of the same name."""
    roots = [HOLO_DIR / "skills"]
    if bundled := BUNDLED_SKILLS.get(platform.system()):
        roots.insert(0, Path(str(resources.files("hai_agents_cli.desktop_skills").joinpath(bundled))))
    skills: dict[str, dict[str, str]] = {}
    for root in roots:
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if skill := _skill(folder):
                    skills[skill["name"]] = skill
    return skills


def _skill(folder: Path) -> dict[str, str] | None:
    match = _FRONTMATTER.match(_read(folder / "SKILL.md"))
    try:
        meta = yaml.safe_load(match[1]) if match else None
    except yaml.YAMLError:
        meta = None
    description = str(meta.get("description") or "").strip() if isinstance(meta, dict) else ""
    name = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")
    if not (match and name and description):
        return None
    return {"name": name, "description": description, "body": match[2].strip()}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
