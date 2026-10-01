"""The release updater must never move URLs while retaining a platform's old digest."""

import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("complete", [True, False])
def test_release_pin_update_is_complete_or_leaves_manifest_unchanged(tmp_path, complete):
    script = tmp_path / "scripts" / "bump_runtime.py"
    manifest = tmp_path / "src" / "hai_agents_local" / "runtime" / "manifest.py"
    script.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "bump_runtime.py", script)
    shutil.copyfile(ROOT / "src" / "hai_agents_local" / "runtime" / "manifest.py", manifest)
    before = manifest.read_bytes()
    original = runpy.run_path(str(manifest))["MANIFEST"]
    shas = {platform: f"{index:064x}" for index, platform in enumerate(original, start=1)}
    args = [sys.executable, str(script), "--version", "9.8.7"]
    for platform, sha in list(shas.items())[: len(shas) if complete else -1]:
        args.extend(["--sha", f"{platform}={sha}"])
    result = subprocess.run(args, capture_output=True, text=True)
    if not complete:
        assert result.returncode != 0
        assert manifest.read_bytes() == before
        return
    assert result.returncode == 0, result.stderr
    updated = runpy.run_path(str(manifest))["MANIFEST"]
    assert set(updated) == set(original)
    for platform, artifact in updated.items():
        assert artifact.sha256 == shas[platform]
        assert artifact.url.endswith(f"/9.8.7/hai-agent-runtime-{platform}.zip")
