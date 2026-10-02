"""The release updater must never move URLs while retaining a platform's old digest."""

import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("src") / "hai_agents_local" / "runtime"


@pytest.mark.parametrize("case", ["complete", "partial", "unknown-platform", "placeholder-sha"])
def test_release_pin_update_is_complete_or_leaves_pin_unchanged(tmp_path, case):
    for relative in (Path("scripts") / "bump_runtime.py", RUNTIME / "manifest.py", RUNTIME / "pin.json"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    pin, manifest = tmp_path / RUNTIME / "pin.json", tmp_path / RUNTIME / "manifest.py"
    before = pin.read_bytes()
    original = runpy.run_path(str(manifest))["MANIFEST"]
    shas = {platform: f"{index:064x}" for index, platform in enumerate(original, start=1)}
    if case == "partial":
        shas.popitem()
    elif case == "unknown-platform":
        shas["plan9-mips"] = "f" * 64
    elif case == "placeholder-sha":
        shas[next(iter(shas))] = "0" * 64
    args = [sys.executable, str(tmp_path / "scripts" / "bump_runtime.py"), "--version", "9.8.7"]
    for platform, sha in shas.items():
        args.extend(["--sha", f"{platform}={sha}"])
    result = subprocess.run(args, capture_output=True, text=True)
    if case != "complete":
        assert result.returncode != 0
        assert pin.read_bytes() == before
        return
    assert result.returncode == 0, result.stderr
    updated = runpy.run_path(str(manifest))
    assert updated["PINNED_RUNTIME_VERSION"] == "9.8.7"
    assert set(updated["MANIFEST"]) == set(original)
    for platform, artifact in updated["MANIFEST"].items():
        assert artifact.sha256 == shas[platform]
        assert artifact.url.endswith(f"/9.8.7/hai-agent-runtime-{platform}.zip")
