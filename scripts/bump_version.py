"""Print the SDK version, bump its patch in every file that stamps it, or tell whether the wheel changed since a ref."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
_V = r"\d+\.\d+\.\d+"
STAMPS = {
    Path("pyproject.toml"): [re.compile(rf'^(version = ")({_V})(")', re.MULTILINE)],
    Path("uv.lock"): [re.compile(rf'(name = "hai-agents"\nversion = ")({_V})(")')],
    Path("src/hai_agents/core/client_wrapper.py"): [
        re.compile(rf'("User-Agent": "hai_agents/)({_V})(")'),
        re.compile(rf'("X-HCompany-Client-Version": ")({_V})(")'),
    ],
}
SHIPPED_PATHS = ("src", "README.md")


def current(root: Path = ROOT) -> str:
    match = STAMPS[Path("pyproject.toml")][0].search((root / "pyproject.toml").read_text())
    if match is None:
        raise SystemExit("pyproject.toml has no version")
    return match.group(2)


def bump(root: Path = ROOT) -> str:
    """Raise the patch version everywhere; fails before writing if any stamp is missing or out of step."""
    old = current(root)
    major, minor, patch = old.split(".")
    new = f"{major}.{minor}.{int(patch) + 1}"
    rewritten: dict[Path, str] = {}
    for relative, patterns in STAMPS.items():
        text = (root / relative).read_text()
        for pattern in patterns:
            found = pattern.findall(text)
            if [stamp for _, stamp, _ in found] != [old]:
                raise SystemExit(f"{relative}: expected one {pattern.pattern!r} stamped {old}, found {found}")
            text = pattern.sub(rf"\g<1>{new}\g<3>", text)
        rewritten[relative] = text
    for relative, text in rewritten.items():
        (root / relative).write_text(text)
    return new


def _wheel_metadata(pyproject: str) -> dict:
    data = tomllib.loads(pyproject)
    return {
        "build-system": data.get("build-system"),
        "project": data.get("project"),
        "hatch": data.get("tool", {}).get("hatch"),
    }


def shipped_changed(ref: str, root: Path = ROOT) -> bool:
    diff = subprocess.run(["git", "diff", "--quiet", ref, "HEAD", "--", *SHIPPED_PATHS], cwd=root)
    if diff.returncode > 1:
        raise SystemExit(f"git diff {ref} failed")
    if diff.returncode == 1:
        return True
    before = subprocess.run(
        ["git", "show", f"{ref}:pyproject.toml"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return _wheel_metadata(before) != _wheel_metadata((root / "pyproject.toml").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", action="store_true", help="print the version without bumping")
    parser.add_argument("--changed-since", metavar="REF", help="print whether the wheel changed since REF")
    args = parser.parse_args()
    if args.changed_since:
        print(str(shipped_changed(args.changed_since)).lower())
    else:
        print(current() if args.current else bump())


if __name__ == "__main__":
    main()
