"""Stop crosses the SDK bridge and scaled driver and kills only the active command tree."""

import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("hai_drivers.desktop.utils")
try:
    from hai_drivers.desktop.utils import DesktopCommandRunner
except ImportError:
    pytest.skip("installed hai-drivers lacks DesktopCommandRunner", allow_module_level=True)

from hai_drivers.desktop.scaled import ScaledDesktopDriver

from hai_agents_local.desktop import PyautoguiDesktopBridge
from hai_agents_local.transport import Command


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Process-group liveness requires POSIX; Windows needs native QA")
async def test_desktop_stop_kills_owned_command_tree_and_rejects_queued_work(tmp_path):
    runner = DesktopCommandRunner()

    def run_command(command, timeout=60, env=None, cwd=None, detach=False, ignore_errors=False):
        return runner.run(command, timeout=timeout, env=env, cwd=cwd, detach=detach)

    # Only the UI surface is absent; command execution, scale forwarding and SDK Stop are real.
    desktop = SimpleNamespace(run_command=run_command, close=runner.close)
    bridge = PyautoguiDesktopBridge(api_key="test")
    bridge._driver = ScaledDesktopDriver(desktop, max_width=1920)
    pid_file = tmp_path / "pids.json"
    queued = tmp_path / "queued"
    program = (
        "import subprocess,sys,os,json,time;from pathlib import Path;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(),child.pid]));time.sleep(60)"
    )
    commands = [
        Command(id="one", command_uid="one", name="run_command", args={"command": [sys.executable, "-c", program]}),
        Command(
            id="two",
            command_uid="two",
            name="run_command",
            args={"command": [sys.executable, "-c", f"from pathlib import Path;Path({str(queued)!r}).touch()"]},
        ),
    ]

    class Exchange:
        async def post_result(self, *args, **kwargs):
            pytest.fail("Stopped work must not report a successful result")

    observer = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    dispatch = asyncio.create_task(bridge._process_commands(Exchange(), commands))
    try:
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(0.01)
        owned = json.loads(pid_file.read_text())
        bridge.request_stop()
        await asyncio.wait_for(dispatch, 5)
        assert observer.poll() is None
        assert not queued.exists()
        for pid in owned:
            async with asyncio.timeout(5):
                while True:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    await asyncio.sleep(0.02)
        with pytest.raises(RuntimeError, match="closed"):
            runner.run([sys.executable, "-c", f"from pathlib import Path;Path({str(queued)!r}).touch()"])
    finally:
        await asyncio.to_thread(runner.close)
        observer.terminate()
        observer.wait(timeout=5)
        await dispatch
