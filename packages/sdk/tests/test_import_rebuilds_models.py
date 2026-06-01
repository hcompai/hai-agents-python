from __future__ import annotations

import subprocess
import sys
import textwrap


def test_package_import_rebuilds_pydantic_models() -> None:
    script = textwrap.dedent(
        """
        from agent_platform import Agent, Browser, SessionRequest
        from agent_platform.models.page_agent_record import PageAgentRecord
        from agent_platform.models.user_message_event import UserMessageEvent

        SessionRequest(
            agent="h/web",
            messages=[UserMessageEvent(message="Open https://example.com")],
        )
        Agent(
            name="smoke-agent",
            description="Smoke test agent",
            environments=[
                Browser(
                    id="browser",
                    kind="web",
                    headless=True,
                    width=1280,
                    height=720,
                    start_url="https://example.com",
                )
            ],
        )
        PageAgentRecord.from_dict(
            {
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "spec": {
                            "name": "h/web",
                            "description": "Web agent.",
                            "environments": ["h/web"],
                        },
                        "reserved": True,
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
            }
        )
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
