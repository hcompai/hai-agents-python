from __future__ import annotations

import pytest
from hai_agents_extras.runners import RunAgentParams, run_agent


@pytest.mark.integration
def test_runner_live_run(client) -> None:
    result = run_agent(
        client,
        RunAgentParams(task="Reply with exactly: hello", max_steps=3, max_time_s=60),
        on_event=lambda event: None,
    )

    assert result.id
    assert str(result.status) in {"completed", "idle"}
