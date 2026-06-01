<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# agent-platform

Python SDK for [H Company's Agent Platform](https://hcompany.ai). Sync and async clients, fully typed with Pydantic v2.

## Quickstart

Install from a repository checkout:

```bash
git clone https://github.com/hcompai/hai-agents-python.git
cd hai-agents-python
pip install ./packages/sdk
```

Do not use `pip install agent-platform` from public PyPI yet. That package name
currently resolves to an unrelated project and will not provide this SDK's
`agent_platform` module. Use a repository checkout, or an internal package
index only if your organization has published this SDK there.

```python
from agent_platform import Client, Agent, SessionRequest
from agent_platform.api.sessions import create_session
from agent_platform.models.browser import Browser
from agent_platform.models.user_message_event import UserMessageEvent

client = Client(api_key="hk-...")

session = create_session.sync(
    client=client,
    body=SessionRequest(
        agent=Agent(
            name="my-agent",
            description="A demo agent.",
            instructions="Reply concisely.",
            environments=[Browser(id="browser", kind="web",
                                  headless=True,
                                  width=1280, height=800,
                                  start_url="https://bing.com")],
        ),
        messages=[UserMessageEvent(message="What is the weather in Paris?")],
        max_steps=12,
    ),
)
print(session.id)
```

Grab a key at [portal.hcompany.ai](https://portal.hcompany.ai). The default `base_url` is the production endpoint; pass `base_url=` to point at staging.

## Poll, stream, send

```python
from agent_platform.api.sessions import get_session_status, get_session_changes, send_session_messages

status = get_session_status.sync(client=client, id=session.id)

# Long-poll for new events
changes = get_session_changes.sync(client=client, id=session.id, from_index=0)

# Inject a message mid-run
send_session_messages.sync(
    client=client,
    id=session.id,
    body=[UserMessageEvent(message="Actually, switch to Lyon.")],
)
```

## Async

```python
from agent_platform import AsyncClient
from agent_platform.api.sessions import list_session_events

client = AsyncClient(api_key="hk-...")
events = await list_session_events.asyncio(client=client, id="...")
```

## Memories, skills, environments, agents

CRUD endpoints for each catalog live under `agent_platform.api.{memories,skills,environments,agents}`.

## Errors

```python
from agent_platform.errors import UnexpectedStatus

try:
    get_session_status.sync(client=client, id="missing")
except UnexpectedStatus as e:
    print(e.status_code, e.content)
```

## Requirements

Python 3.10+. Runtime deps: `httpx`, `pydantic>=2`, `python-dateutil`, `attrs`.
